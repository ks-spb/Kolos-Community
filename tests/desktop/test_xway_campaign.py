"""The campaign handoff reports verified observations and cannot authorize ads."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
import unittest
import uuid

from kolos_states.xway_readonly.campaign import ROOT, run
from kolos_states.storage import Store


def payload(run_id: str, campaign_id: int = 401, budget: int | None = 500) -> dict:
    task = dict(shop_id=100, nm_id=200 + campaign_id, campaign_id=campaign_id)
    query = dict(shop_id=task['shop_id'], product_id=[task['nm_id']], id=[campaign_id])
    campaign = dict(id=campaign_id, name=f'Кампания {campaign_id}', type='MANUAL', currency='RUB',
                    status='11' if campaign_id == 401 else '7', budget=budget, is_active=True)
    response = dict(items=[campaign], pagination=dict(offset=0, count=1, next_offset=None))
    now = datetime.now(timezone.utc)
    observations = [dict(query=copy.deepcopy(query), response=copy.deepcopy(response),
                         observed_at=(now - timedelta(seconds=seconds)).isoformat()) for seconds in (2, 1)]
    return dict(run_id=run_id, task=task, observations=observations)


class CampaignHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = ROOT / ('unit-' + uuid.uuid4().hex)

    def test_teach_then_read_new_values_from_frozen_memory(self) -> None:
        lesson = run(payload('lesson'), self.root, teach=True)
        self.assertEqual(lesson['status'], 'taught')
        memory = self.root / 'lesson' / 'memory' / 'memory.json'
        saved = memory.read_bytes()
        for campaign_id, budget in ((402, 0), (403, None)):
            name = f'control-{campaign_id}'
            result = run(payload(name, campaign_id, budget), self.root, teach=False, memory_run='lesson')
            self.assertEqual(result['status'], 'observed')
            self.assertEqual(result['campaign']['id'], campaign_id)
            self.assertEqual(result['campaign']['status'], '7')
            self.assertEqual(result['campaign']['budget'], budget)
            self.assertTrue(result['memory_unchanged'])
            self.assertEqual(result['dispatches'], lesson['dispatches'])
            self.assertFalse(result['may_execute'])
            saved_report = self.root / name / 'handoff.json'
            self.assertEqual(json.loads(saved_report.read_text(encoding='utf-8')), result)
        self.assertEqual(memory.read_bytes(), saved)

    def test_empty_memory_blocks_with_no_campaign(self) -> None:
        result = run(payload('empty'), self.root, teach=False)
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('Unknown or ambiguous', result['reason'])
        self.assertIsNone(result['campaign'])

    def test_scheduled_read_writes_to_caller_project_and_only_reads_source_memory(self) -> None:
        lesson = run(payload('lesson'), self.root, teach=True)
        self.assertEqual(lesson['status'], 'taught')
        memory = self.root / 'lesson' / 'memory'
        saved = (memory / 'memory.json').read_bytes()
        caller = self.root / 'caller' / 'reports'
        lease = Store(memory)
        try:
            result = run(payload('scheduled', 402), caller, teach=False,
                         memory_run='lesson', memory_root=self.root)
        finally:
            lease.close()
        self.assertEqual(result['status'], 'observed')
        self.assertTrue((caller / 'scheduled' / 'handoff.json').is_file())
        self.assertEqual((memory / 'memory.json').read_bytes(), saved)
        self.assertFalse((self.root / 'scheduled').exists())

    def test_unreliable_input_cannot_publish_campaign_data(self) -> None:
        def first(data):
            return data['observations'][0]

        cases = {
            'wrong-product': lambda data: first(data)['query'].update(product_id=[999]),
            'wrong-id': lambda data: first(data)['response']['items'][0].update(id=999),
            'incomplete': lambda data: first(data)['response']['pagination'].update(next_offset=1),
            'duplicate': lambda data: first(data)['response']['items'].__imul__(2),
            'missing-status': lambda data: first(data)['response']['items'][0].pop('status'),
            'changed-status': lambda data: first(data)['response']['items'][0].update(status='7'),
            'stale': lambda data: first(data).update(observed_at='2020-01-01T00:00:00+00:00'),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                data = payload(name)
                mutate(data)
                result = run(data, self.root, teach=True)
                self.assertEqual(result['status'], 'blocked')
                self.assertIsNone(result['campaign'])
                self.assertFalse(result['may_execute'])
                self.assertFalse((self.root / name / 'memory').exists())

    def test_repeated_run_cannot_replace_handoff(self) -> None:
        data = payload('same-run')
        run(data, self.root, teach=True)
        with self.assertRaises(FileExistsError):
            run(data, self.root, teach=False)
