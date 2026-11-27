"""Regression checks for tool-hosted episodes and the bounded XWAY experiment."""
from __future__ import annotations

import tempfile
import time
from pathlib import Path
import unittest

from kolos_states.episode_browser import BrowserEpisodeBridge
from kolos_states.episode_experiment import FormWorld, memory_signature
from kolos_states.protocol import clone
from tests.desktop.experiment_gate import check_gate, write_json
from tests.desktop.xway_browser_lab import budget_transition, handle_budget, operate, validate_page


def shown(bridge: BrowserEpisodeBridge, world: FormWorld, kind: str, role: str, source: str | None = None) -> None:
    """Use independent fixture observations to demonstrate one real primitive."""
    request = bridge.prepare(world.observe(), kind, role, source)
    receipt = world.execute(request)
    bridge.confirm(receipt['after'], world.observe())


def dom(budget: str = '100 ₽') -> dict:
    """Only this explicit fixture is synthetic; live observations come from the browser tool."""
    return dict(url='https://am.xway.ru/wb/shop/13614', search='11016-70х12', epoch='test-page',
                product=dict(sku='11016-70х12', wb_id='1391386148', budget=budget))


class BrowserBridgeTests(unittest.TestCase):
    """A learned sequence must use new observations and must not fake acknowledgements."""

    def test_teach_then_new_element_ids_and_values_without_relearning(self) -> None:
        bridge, world = BrowserEpisodeBridge(), FormWorld(('100 ₽',))
        bridge.begin_teaching('Read and report')
        shown(bridge, world, 'read', 'Source 1')
        shown(bridge, world, 'write', 'Target 1', 'v0')
        shown(bridge, world, 'activate', 'Save')
        bridge.finish_teaching()
        frozen = memory_signature(bridge.engine)
        bridge = BrowserEpisodeBridge(bridge.dump())
        other = FormWorld(('105 ₽',), layout=1)
        bridge.start('Read and report', other.observe())
        for _ in range(4):
            request = bridge.next(other.observe())
            if request.get('status') == 'complete':
                break
            receipt = other.execute(request)
            bridge.confirm(receipt['after'], other.observe())
        self.assertEqual(bridge.engine.model['status'], 'complete')
        self.assertEqual(other.data['Target 1'], '105 ₽')
        self.assertEqual(memory_signature(bridge.engine), frozen)

    def test_inconsistent_or_stale_evidence_cannot_finish_teaching(self) -> None:
        bridge, world = BrowserEpisodeBridge(), FormWorld()
        bridge.begin_teaching('Read and report')
        bridge.prepare(world.observe(), 'read', 'Source 1')
        after = world.observe()
        with self.assertRaisesRegex(ValueError, 'Stale'):
            bridge.confirm(after, after)
        world.data['Source 1'] = 'unexpected'
        with self.assertRaisesRegex(ValueError, 'inconsistent'):
            bridge.confirm(world.observe(), world.observe())
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            bridge.finish_teaching()
        self.assertEqual(bridge.engine.model['learningLog'], [])

    def test_unconfirmed_action_cannot_be_dispatched_again(self) -> None:
        bridge, world = BrowserEpisodeBridge(), FormWorld()
        bridge.begin_teaching('Read and report')
        bridge.prepare(world.observe(), 'read', 'Source 1')
        with self.assertRaises(ValueError):
            bridge.prepare(world.observe(), 'read', 'Source 1')
        with self.assertRaises(ValueError):
            bridge.next(world.observe())


class XwayBoundaryTests(unittest.TestCase):
    """Human readiness, product identity, and money limits are independent checks."""

    def test_waiting_stopped_blocked_complete_and_expired_gates_all_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            for state, ready, deadline in [('waiting', None, None), ('stopped', 'yes', time.time()+60),
                                           ('blocked', 'yes', time.time()+60), ('complete', 'yes', time.time()+60),
                                           ('running', 'yes', time.time()-1)]:
                write_json(path / 'gate.json', dict(state=state, human_ready_utc=ready, deadline=deadline))
                with self.subTest(state=state), self.assertRaises(PermissionError):
                    operate(path, dict(op='init'))
                self.assertFalse((path / 'task.json').exists())

    def test_only_one_100_105_100_cycle_is_permitted(self) -> None:
        self.assertEqual(budget_transition(dom(), 105, 0)['after'], 105)
        self.assertEqual(budget_transition(dom('105 ₽'), 100, 1)['after'], 100)
        for before, target, completed in [('100 ₽', 95, 0), ('100 ₽', 110, 0), ('105 ₽', 105, 1),
                                           ('100 ₽', 105, 2), ('99 ₽', 105, 0)]:
            with self.subTest(before=before, target=target), self.assertRaises(ValueError):
                budget_transition(dom(before), target, completed)

    def test_other_shop_product_or_non_numeric_budget_is_rejected(self) -> None:
        variants = []
        wrong_shop = dom()
        wrong_shop['url'] = 'https://am.xway.ru/wb/shop/22270'
        variants.append(wrong_shop)
        for key, value in [('sku', 'Other SKU'), ('wb_id', '123'), ('budget', 'из 100 ₽')]:
            wrong = dom()
            wrong['product'][key] = value
            variants.append(wrong)
        for raw in variants:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                validate_page(raw, True)

    def test_budget_prepare_requires_matching_api_and_no_outstanding_write(self) -> None:
        api = dict(sku='11016-70х12', wb_id='1391386148', budget=100, grouped_ai=False)
        for key, value in [('budget', 105), ('grouped_ai', True), ('wb_id', 'other')]:
            changed = dict(api, **{key: value})
            state = dict(budget_log=[])
            with self.subTest(key=key), self.assertRaises(ValueError):
                handle_budget(Path('.'), state, dict(op='budget-prepare', dom=dom(), target=105, api=changed))
            self.assertIsNone(state.get('budget_pending'))
        state = dict(budget_log=[])
        request = dict(op='budget-prepare', dom=dom(), target=105, api=api)
        handle_budget(Path('.'), state, request)
        with self.assertRaisesRegex(ValueError, 'unconfirmed'):
            handle_budget(Path('.'), state, request)


if __name__ == '__main__':
    unittest.main()
