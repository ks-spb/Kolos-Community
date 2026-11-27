"""Regressions for premature route selection, bounds and retained adaptation."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
import uuid
from pathlib import Path

from kolos_states import dynamics, goal_network
from kolos_states.backward import backward_wave
from kolos_states.route_selection import certified_choice, route_decision
from kolos_states.simulator import observe
from kolos_states.transfer.runner import fingerprint, remove_focus_links, run_case
from kolos_states.transfer.suite import adaptation
from kolos_states.transfer.world import make_lab, teach


class RouteSelectionTests(unittest.TestCase):
    """Develop only on seed zero, separate from both held-out selections."""

    def setUp(self) -> None:
        """Initialize a real learned graph with a direct path and a longer alternative."""
        self.lab = make_lab(0)
        self.engine = teach(self.lab)
        self.engine.start_goals([dict(kind='field', focus=self.lab.field, value='3521')],
                                observe(self.lab.at('desk')))

    def wave(self, exhausted: bool = False) -> tuple[dict, dict]:
        """Advance the production selector on a fixed observed state."""
        m = self.engine.model
        dynamics.sensory_tick(m, [])
        event = dict(flows=[])
        decision = route_decision(m, m['intent'], m['intent']['config'],
                                  ['focus:' + self.lab.field], .55, event, exhausted)
        return decision, event

    def test_crossing_threshold_does_not_certify_an_unfinished_race(self) -> None:
        """An early lead cannot defeat a rival whose remaining signal is larger."""
        candidates = [dict(id='fast', a=.56, upper=.65, allowed=True),
                      dict(id='detour', a=.35, upper=.68, allowed=True)]
        self.assertEqual(certified_choice(candidates, .55, False), {})
        candidates[1]['a'] = .66
        self.assertEqual(certified_choice(candidates, .55, False)['winner']['id'], 'detour')

    def test_ties_empty_zero_and_threshold_boundaries(self) -> None:
        """No arbitrary ID choice or action without sufficient evidence, even at timeout."""
        self.assertEqual(certified_choice([], .55, True), dict(blocked=True))
        self.assertEqual(certified_choice([dict(a=0, upper=0, allowed=True)], .55, True), dict(blocked=True))
        tied = [dict(id=id, a=.7, upper=.7, allowed=True) for id in ('b', 'a')]
        for rows in (tied, list(reversed(tied))):
            self.assertEqual(certified_choice(rows, .55, False), {})
            self.assertEqual(certified_choice(rows, .55, True), dict(ambiguous=True))
        edge = [dict(id='only', a=.55, upper=.55, allowed=True), dict(a=1, upper=1, allowed=False)]
        self.assertEqual(certified_choice(edge, .55, False)['winner']['id'], 'only')
        edge[0]['a'] = .549999999
        self.assertEqual(certified_choice(edge, .55, True), dict(blocked=True))

    def test_bounds_enclose_settled_cyclic_dynamics_and_certify_winner(self) -> None:
        """Independent continued propagation must never escape the recorded intervals."""
        m = self.engine.model
        nodes = [n for n in m['memory']['nodes'] if n['kind'] in ('state', 'transition')]
        settled: dict = {}
        for _ in range(300):
            settled = backward_wave(m['memory'], nodes, settled, m['intent']['config'], [])
            dynamics.seed_demand(m, settled, ['focus:' + self.lab.field])
        before = fingerprint(self.engine)
        for _ in range(100):
            decision, event = self.wave()
            upper = m['intent']['routeBounds']['upper']
            for node_id, value in settled.items():
                self.assertLessEqual(m['goalActivation'][node_id], value + 1e-8)
                self.assertGreaterEqual(upper[node_id] + 1e-8, value)
            if decision.get('winner'):
                settled_scores = dynamics.transition_candidates(m, settled, m['intent']['config'], .55)
                best = max((c for c in settled_scores if c['allowed']), key=lambda c: c['a'])
                self.assertEqual(decision['winner']['id'], best['id'])
                break
        else:
            self.fail('No certified winner within the configured budget')
        self.assertEqual(before, fingerprint(self.engine))

    def test_weight_changes_cannot_reuse_stale_activity(self) -> None:
        """Removing the goal path after a charged wave invalidates both bounds."""
        for _ in range(20):
            self.wave()
        remove_focus_links(self.engine, self.lab.field)
        for _ in range(100):
            decision, event = self.wave(exhausted=True)
            self.assertNotIn('winner', decision)
        self.assertEqual(decision, dict(blocked=True))

    def test_goal_and_operator_changes_restart_bounds(self) -> None:
        """Changed demand and decay cannot inherit a certificate for a different map."""
        for _ in range(20):
            self.wave()
        m = self.engine.model
        cfg = m['intent']['config']
        for key, value in (('decay', .3), ('discount', 0), ('stateCompetition', 0)):
            cfg[key] = value
            self.wave()
            self.assertTrue(all(v == 0 for id, v in m['goalActivation'].items()
                                if self.engine.node(id)['kind'] == 'transition'))
        decision = route_decision(m, m['intent'], cfg, ['focus:unseen'], .55, dict(flows=[]), True)
        self.assertNotIn('winner', decision)
        self.assertTrue(all(v == 0 for v in m['goalActivation'].values()))

    def test_learning_survives_restart_and_early_rule_still_repeats_error(self) -> None:
        """Same saved graph: fixed rule and planner avoid the error; old rule repeats it."""
        data = dict(groups={}, restarts=[])
        directory = Path(__file__).resolve().parents[1] / 'desktop-output' / ('selection-unit-' + uuid.uuid4().hex)
        directory.mkdir(parents=True)
        adaptation(data, self.lab, teach(self.lab), directory, 'native', 1)
        for name in ('native_post_on', 'planner_post_from_native'):
            rows = data['groups'][name]
            self.assertTrue(all(r['success'] and r['wrong_fast'] == 0 for r in rows), rows)
            self.assertTrue(all(r['memory_before'] == r['memory_after'] for r in rows))
        self.assertEqual(sum(r['wrong_fast'] for r in data['groups']['early_post_from_native']), 10)
        self.assertTrue(all(r['different_pid'] and r['transient_clean'] and r['graph_equal'] for r in data['restarts']))

    def test_learned_detour_bounds_and_choice_match_javascript(self) -> None:
        """The changed-environment regression must also work in the browser engine."""
        if not shutil.which('node'):
            self.skipTest('Node required for development parity only')
        engine = self.engine
        engine.configure(plasticity=1)
        for i in range(5):
            run_case(engine, self.lab, dict(case=i, start='overlay', value='3521'), changed=True)
        engine.start_goals([dict(kind='field', focus=self.lab.field, value='3521')],
                           observe(self.lab.at('desk', changed=True)))
        script = Path(__file__).with_name('route_selection_reference.mjs')
        expected = json.loads(subprocess.check_output(['node', str(script)],
                              input=json.dumps(engine.model), text=True, encoding='utf-8'))
        for row in expected:
            event = goal_network.tick(engine.model)
            self.assertEqual((event['kind'], event.get('winner')), (row['kind'], row['winner']))
            for left, right in zip(event.get('candidates', []), row['candidates'], strict=True):
                self.assertEqual(left['id'], right['id'])
                self.assertAlmostEqual(left['a'], right['a'], places=8)
                self.assertAlmostEqual(left['upper'], right['upper'], places=8)
        self.assertEqual(expected[-1]['kind'], 'route')
        self.assertEqual(engine.node(expected[-1]['winner'])['label'], 'CLICK ' + self.lab.objects['panel'])


if __name__ == '__main__':
    unittest.main()
