"""Read-only guards, live identity contracts, graph dependence and receipt discipline."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest
import uuid

from kolos_states.episode_browser import BrowserEpisodeBridge
from kolos_states.xway_readonly.protocol import authorize, shop_scope, snapshot
from kolos_states.xway_readonly.worker import OUTPUT, Worker


TASK = dict(sku='held-out-sku', wb_id='100002', shop_id='412', shop_name='Тестовый магазин')
REPORT = dict(sku='', wb_id='', budget='')


def dom() -> dict:
    return dict(url='https://am.xway.ru/wb/shop/412?tab=product', shop='Тестовый магазин',
                session='unit-only', version=1, captured_at=1, result_count=1, search='',
                editor_visible=True, exact=True, apply_count=1,
                rows=[dict(**TASK, budget='30\u00a0₽', ai_enabled=True)])


def teach_synthetic_search(bridge: BrowserEpisodeBridge) -> None:
    """Record a minimal isolated search demonstration for the synthetic shop."""
    raw = dom()
    def frame(version: int, search: str = '') -> dict:
        return snapshot(dict(raw, version=version, captured_at=version, search=search), TASK, REPORT, 'search')

    bridge.begin_teaching('Найди товар по артикулу XWAY')
    bridge.prepare(frame(1), 'read', 'Requested SKU')
    bridge.confirm(frame(2), frame(3))
    bridge.prepare(frame(4), 'write', 'Product search', source='v0')
    bridge.confirm(frame(5, TASK['sku']), frame(6, TASK['sku']))
    bridge.finish_teaching()


class ReadOnlyContractTests(unittest.TestCase):
    def test_live_identity_and_editor_fail_closed(self) -> None:
        mutations = [dict(url='https://example.org/wb/shop/412'),
                     dict(url='https://am.xway.ru/wb/shop/999'), dict(shop='Other'),
                     dict(result_count=2), dict(exact=False), dict(editor_visible=False),
                     dict(apply_count=2), dict(rows=[]),
                     dict(rows=[dict(sku='other', wb_id=TASK['wb_id'], budget='30 ₽', ai_enabled=True)]),
                     dict(rows=[dict(sku=TASK['sku'], wb_id='000', budget='30 ₽', ai_enabled=True)]),
                     dict(rows=[dict(**TASK, budget='', ai_enabled=False)])]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                snapshot(dict(dom(), **mutation), TASK, REPORT, 'read')

    def test_ad_budget_is_never_writable(self) -> None:
        obs = snapshot(dom(), TASK, REPORT, 'read')
        budget = next(o for o in obs['objects'] if o['descriptor']['name'] == 'Daily budget')
        self.assertFalse(budget['writable'])
        for kind in ('write', 'activate'):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                authorize(dict(kind=kind, object=budget['id'], descriptor=budget['descriptor'], value='999'), obs, TASK)

    def test_search_is_bound_to_current_task(self) -> None:
        obs = snapshot(dom(), TASK, REPORT, 'search')
        target = next(o for o in obs['objects'] if o['descriptor']['name'] == 'Product search')
        action = dict(kind='write', object=target['id'], descriptor=target['descriptor'], value=TASK['sku'])
        self.assertEqual(authorize(action, obs, TASK), 'search-fill')
        for replacement in ('another SKU', 'a\nb', ''):
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                authorize(dict(action, value=replacement), obs, TASK)

    def test_stale_object_and_wrong_scope_are_rejected(self) -> None:
        obs = snapshot(dom(), TASK, REPORT, 'read')
        target = next(o for o in obs['objects'] if o['descriptor']['name'] == 'Report budget')
        action = dict(kind='write', object=target['id'], descriptor=target['descriptor'], value='30 ₽')
        self.assertEqual(authorize(action, obs, TASK), 'local-report')
        with self.assertRaises(ValueError):
            authorize(dict(action, object='stale'), obs, TASK)
        action['descriptor'] = dict(action['descriptor'], scope=shop_scope(TASK, 'product'))
        with self.assertRaises(ValueError):
            authorize(action, obs, TASK)

    def test_missing_memory_cannot_invent_a_route(self) -> None:
        bridge = BrowserEpisodeBridge()
        with self.assertRaisesRegex(ValueError, 'Unknown or ambiguous'):
            bridge.start('Найди товар по артикулу XWAY', snapshot(dom(), TASK, REPORT, 'search'))
        self.assertIsNone(bridge.pending)


class WorkerBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        # Persistent ignored evidence avoids Windows sandbox ACL failures in tempfile cleanup.
        self.worker = Worker(OUTPUT / ('xway-unit-' + uuid.uuid4().hex))

    def test_report_write_needs_pending_request(self) -> None:
        self.worker.task = TASK
        with self.assertRaises(ValueError):
            self.worker.local(dom())
        self.assertEqual(json.loads(self.worker.report_path.read_text()), REPORT)

    def test_empty_condition_loads_without_inventing_commands(self) -> None:
        loaded = self.worker.load(dict(task=TASK, mode='empty'))
        self.assertEqual(loaded['commands'], 0)
        self.assertEqual(self.worker.signature(), loaded['memory_sha256'])

    def test_output_and_memory_paths_stay_in_evidence_workspace(self) -> None:
        with self.assertRaises(ValueError):
            Worker(Path('C:/outside-project'))
        with self.assertRaises(ValueError):
            self.worker.load(dict(task=TASK, mode='trained', memory='C:/outside-project/memory.json'))

    def test_unknown_operations_have_no_fallback(self) -> None:
        for op in ('browser-click', 'eval', 'set-budget', 'shell'):
            with self.subTest(op=op), self.assertRaises(ValueError):
                self.worker.handle(dict(op=op))

    def test_cut_breaks_learned_topology_before_browser_write(self) -> None:
        self.worker.task = TASK
        teach_synthetic_search(self.worker.bridge)
        self.assertIsNotNone(self.worker.cut()['id'])
        self.worker.stage = 'search'
        raw = dom()
        self.worker.bridge.start('Найди товар по артикулу XWAY', self.worker.observation(raw))
        raw.update(version=2, captured_at=2)
        request = self.worker.bridge.next(self.worker.observation(raw))
        self.assertEqual(request['action']['kind'], 'read')
        first, second = copy.deepcopy(raw), copy.deepcopy(raw)
        first.update(version=3, captured_at=3)
        second.update(version=4, captured_at=4)
        self.worker.bridge.confirm(self.worker.observation(first), self.worker.observation(second))
        raw.update(version=5, captured_at=5)
        result = self.worker.bridge.next(self.worker.observation(raw))
        self.assertEqual(result['status'], 'blocked')
        self.assertIsNone(self.worker.bridge.pending)


if __name__ == '__main__':
    unittest.main()
