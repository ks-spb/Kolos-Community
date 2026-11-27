"""Behavioral checks for routing ownership, safe fallback and actual goal verification."""
from __future__ import annotations

import copy
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
import uuid

from kolos_states.cluster_replay.controllers import teach
from kolos_states.cluster_replay.world import VARIANTS
from kolos_states.hermes_shadow import audit, replay, routing
from kolos_states.hermes_shadow.routing import Capability, CLUSTER, READ
from tests.desktop.test_cluster_replay import example

NOW = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)


def task(command: str = CLUSTER, **changes: object) -> dict:
    value = dict(proposal_id='unit-proposal', version=1, command=command, status='proposed',
                 identity=dict(shop_id=101, nm_id=123, vendor_code='unit-sku'),
                 payload=dict(campaign_id=456, nm_id=123, norm_query='unit query', excluded=True))
    return dict(value, **changes)


def state() -> dict:
    return dict(supervisor_policy=dict(enabled=True, starts_at=(NOW - timedelta(days=1)).isoformat(),
                expires_at=(NOW + timedelta(days=1)).isoformat(), allowed_commands=[CLUSTER]))


def preflight(**changes: object) -> dict:
    return dict(dict(stage='preflight', attempt_id=None, may_interact_issued=False,
                     write_dispatched=False, save_unknown=False, lock_held=False, reason='missing_skill'), **changes)


class RoutingTests(unittest.TestCase):
    def selected(self, value: dict | None = None) -> dict:
        return routing.route(value or task(), state(), NOW,
            capabilities=(Capability(CLUSTER, 'hermes_yandex', 'live_write_verified', 'unit-fixture-only'),))

    def test_local_binding_preserves_executor_in_shadow_route(self) -> None:
        decision = routing.route(task(), state(), NOW, owner='fixture-executor')
        self.assertEqual(decision['owner'], 'fixture-executor')
        self.assertFalse(decision['may_execute'])

    def test_replay_and_other_transport_cannot_enable_real_writes(self) -> None:
        for transport in ('hermes_yandex', 'offline_contract', 'codex_iab'):
            with self.subTest(transport=transport):
                decision = routing.route(task(), state(), NOW, transport=transport)
                self.assertEqual(decision['suggested_route'], 'hermes_executor')
                self.assertFalse(decision['may_execute'])
        self.assertEqual(routing.route(task(READ), state(), NOW)['suggested_route'], 'hermes_executor')

    def test_qualified_candidate_still_cannot_authorize_execution(self) -> None:
        selected = self.selected()
        self.assertEqual(selected['suggested_route'], 'kolos_candidate')
        self.assertFalse(selected['may_execute'])
        self.assertTrue(selected['requires_canonical_gate'])

    def test_one_shared_pending_attempt_blocks_another_candidate(self) -> None:
        for command in (CLUSTER, 'xway.position_hold.set'):
            decision = routing.route(task(command), dict(state(), ui_active_proposal='existing-attempt'), NOW)
            self.assertEqual(decision['suggested_route'], 'wait_existing_attempt')
            self.assertEqual(decision['owner'], routing.OWNER)

    def test_readonly_task_can_help_existing_owner_without_claiming_a_second_write(self) -> None:
        decision = routing.route(task(READ), dict(state(), ui_active_proposal='existing-attempt'), NOW)
        self.assertEqual(decision['suggested_route'], 'hermes_executor')
        self.assertEqual(decision['owner'], routing.OWNER)
        self.assertFalse(decision['may_execute'])

    def test_unknown_or_reserved_outcome_never_becomes_a_new_executor(self) -> None:
        for status in routing.PENDING:
            decision = routing.route(task(status=status), state(), NOW)
            self.assertEqual(decision['suggested_route'], 'reconcile')
        self.assertEqual(routing.route(task(submitted_at=NOW.isoformat()), state(), NOW)['suggested_route'], 'reconcile')

    def test_verified_and_closed_failed_tasks_are_not_replayed(self) -> None:
        self.assertEqual(routing.route(task(status='verified'), state(), NOW)['suggested_route'], 'none')
        self.assertEqual(routing.route(task(status='failed', submitted_at=NOW.isoformat()), state(), NOW)['suggested_route'], 'review')

    def test_expired_policy_and_prices_do_not_gain_scope(self) -> None:
        late = NOW + timedelta(days=2)
        self.assertEqual(routing.route(task(), state(), late)['suggested_route'], 'review')
        self.assertEqual(routing.route(task('prices.manual_profit'), state(), NOW)['suggested_route'], 'existing_server_route')
        self.assertEqual(routing.route(task('terminal.execute'), state(), NOW)['suggested_route'], 'review')

    def test_safe_handover_preserves_exact_task_and_still_requires_gate(self) -> None:
        selected = self.selected()
        result = routing.handover(task(), selected, preflight())
        self.assertEqual(result['suggested_route'], 'hermes_executor')
        self.assertEqual(result['task_sha256'], selected['task_sha256'])
        self.assertFalse(result['may_execute'])

    def test_handover_after_any_reservation_or_uncertainty_is_forbidden(self) -> None:
        changes = [dict(stage='reserved'), dict(attempt_id='issued'), dict(may_interact_issued=True),
                   dict(write_dispatched=True), dict(save_unknown=True), dict(lock_held=True)]
        for change in changes:
            with self.subTest(change=change):
                result = routing.handover(task(), self.selected(), preflight(**change))
                self.assertEqual(result['suggested_route'], 'reconcile')

    def test_incomplete_preflight_or_changed_proposal_cannot_transfer(self) -> None:
        self.assertEqual(routing.handover(task(), self.selected(), dict(stage='preflight'))['suggested_route'], 'reconcile')
        for change in (dict(version=2), dict(proposal_id='another'),
                       dict(payload=dict(task()['payload'], excluded=False))):
            with self.subTest(change=change), self.assertRaises(ValueError):
                routing.handover(task(**change), self.selected(), preflight())

    def test_a_blocked_route_or_late_claim_cannot_be_overridden_by_fallback(self) -> None:
        value = task()
        blocked = routing.route(value, dict(state(), ui_active_proposal='busy'), NOW)
        self.assertEqual(routing.handover(value, blocked, preflight())['suggested_route'], 'review')
        self.assertEqual(routing.handover(task(status='pending_verification'), self.selected(), preflight())['suggested_route'], 'reconcile')


class AuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path('tests/desktop-output') / ('hermes-unit-' + uuid.uuid4().hex)
        self.directory.mkdir(parents=True)

    def test_native_messages_exclude_runtime_notices_and_pair_actual_final_reply(self) -> None:
        path = self.directory / 'sessions.db'
        proposal_id = 'a' * 64
        with closing(sqlite3.connect(path)) as connection:
            connection.executescript('CREATE TABLE sessions(id TEXT,title TEXT,profile_name TEXT,parent_session_id TEXT,archived INT);'
                'CREATE TABLE messages(id INT,session_id TEXT,role TEXT,content TEXT,tool_calls TEXT,timestamp REAL);')
            connection.execute('INSERT INTO sessions VALUES(?,?,?,?,?)', ('s', 'Bot Chat', 'wb-executor-test', None, 0))
            connection.executemany('INSERT INTO messages VALUES(?,?,?,?,?,?)', [
                (1, 's', 'user', 'Message from Bot (@fixture-supervisor): dispatch_id=unit proposal' + proposal_id, None, 1),
                (2, 's', 'assistant', 'tool call', '[{"name":"browser"}]', 2),
                (3, 's', 'user', "You've reached the maximum number of tool-calling iterations allowed.", None, 3),
                (4, 's', 'assistant', 'Real final result', None, 4)])
            connection.commit()
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        result = audit.executor_messages(path, {proposal_id}, profile='wb-executor-test', supervisor='fixture-supervisor')
        self.assertEqual(result['counts'], {'supervisor_instruction': 1})
        self.assertEqual(result['requests'][0]['reply_id'], 4)
        self.assertEqual(result['requests'][0]['proposal_refs'], [proposal_id])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_credentials_are_masked_without_reinterpreting_business_text(self) -> None:
        raw = 'bearer UNIT-BEARER password=UNIT-PASSWORD "access_token":"dummy-access-token" excluded=false'
        redacted = audit.redact(raw)
        for token in ('UNIT-BEARER', 'UNIT-PASSWORD', 'dummy-access-token'):
            self.assertNotIn(token, redacted)
        self.assertIn('excluded=false', redacted)

    def test_invalid_ledger_is_not_an_empty_successful_queue(self) -> None:
        path = self.directory / 'state.json'
        path.write_text(json.dumps(dict(version=99, proposals={})), encoding='utf-8')
        with self.assertRaises(ValueError):
            audit.read_state(path)


class RehearsalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.learned, _cost = teach(example())
        self.case = dict(example(True, 32), source_kind='unit_simulation')
        self.proposal = task(payload=dict(campaign_id=self.case['campaign_id'],
                                         norm_query=self.case['query'], excluded=self.case['target']))

    def test_model_or_kernel_completion_without_independent_goal_is_not_success(self) -> None:
        row = replay.run_case(self.case, self.proposal, 'clean', 'kolos', self.learned, lambda _p, _c: False, 1)
        self.assertEqual(row['status'], 'complete')
        self.assertFalse(row['confirmed_goal'])
        self.assertTrue(row['false_success'])
        self.assertFalse(row['correct_outcome'])

    def test_faults_do_not_trigger_hidden_script_fallback_or_repeat_save(self) -> None:
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                row = replay.run_case(self.case, self.proposal, variant, 'kolos', self.learned,
                                      lambda p, c: p['payload']['excluded'] == c['excluded'], 7)
                self.assertTrue(row['correct_outcome'], row)
                self.assertFalse(row['repeated_save'])

    def test_disabled_graph_does_not_execute_script(self) -> None:
        broken = copy.deepcopy(self.learned)
        next(e for e in broken['model']['memory']['edges'] if e['kind'] == 'episode_next')['weight'] = 0
        row = replay.run_case(self.case, self.proposal, 'clean', 'kolos', broken, lambda _p, _c: True, 2)
        self.assertEqual(row['status'], 'blocked')
        self.assertEqual(row['save_attempts'], 0)
        self.assertFalse(row['confirmed_goal'])

    def test_unexecuted_preview_is_explicitly_simulation_and_scope_mismatch_rejected(self) -> None:
        p = task(preconditions=dict(campaign_id=456, norm_query='unit query', excluded=False))
        cases, _proposals = replay.cases(dict(proposals={'p': p}))
        self.assertEqual(cases[0]['source_kind'], 'unexecuted_proposal_simulation')
        self.assertEqual(cases[0]['after']['excluded'], True)
        p['payload']['nm_id'] = 999
        with self.assertRaises(ValueError):
            replay.cases(dict(proposals={'p': p}))


if __name__ == '__main__':
    unittest.main()
