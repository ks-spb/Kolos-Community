"""Behavioral controls for new topologies, fair caching and receipt-safe preemption."""
from __future__ import annotations

import copy
import unittest

from kolos_states.simulator import observe
from kolos_states.topology_experiment import oracle
from kolos_states.topology_experiment.selectors import LOW_THRESHOLD, Selector
from kolos_states.topology_experiment.topologies import FAMILIES
from kolos_states.topology_experiment.trial import Trial
from kolos_states.topology_experiment.world import make_lab, teach
from kolos_states.transfer import planner


class TopologyExperimentTests(unittest.TestCase):
    """Only development seed zero is used to debug the experiment."""

    def test_families_have_real_structural_differences(self) -> None:
        """The extended test changes edges and reachability, not just icon IDs."""
        labs = {f: make_lab(f, 0) for f in FAMILIES}
        chain = labs['chain']
        self.assertEqual(len(chain.edges), len(chain.labels) - 1)
        self.assertTrue(all(b == a + 1 for a, b, _ in chain.edges))
        self.assertNotIn(0, oracle.costs(labs['disconnected'], labs['disconnected'].goals[0]))
        dense = labs['dense']
        self.assertGreater(len(dense.edges) / (len(dense.labels) * (len(dense.labels) - 1)),
                           2 * len(chain.edges) / (len(chain.labels) * (len(chain.labels) - 1)))
        self.assertTrue(any(a > b for a, b, _ in labs['cycles'].edges))
        self.assertEqual(make_lab('dense', 0), labs['dense'])

    def test_training_is_individual_fragments_and_weights_are_shared(self) -> None:
        """No complete test path or hidden route is installed in the controller."""
        for family in FAMILIES:
            lab = make_lab(family, 0)
            self.assertLessEqual(len(lab.edges), 20)
            base = teach(lab)
            self.assertEqual(len(lab.lessons), len(lab.edges))
            self.assertTrue(all([r['action']['kind'] for r in l['receipts']] == ['move', 'check', 'click']
                                for l in lab.lessons))
            self.assertEqual(sum(n['kind'] == 'transition' for n in base.model['memory']['nodes']), len(lab.edges))

    def test_valid_equal_cost_alternatives_have_zero_regret(self) -> None:
        """A valid tie choice by Dijkstra cannot be scored as an unsafe action."""
        lab = make_lab('equal_diamond', 0)
        actions = [dict(kind='click', object=obj) for obj, (a, _, _) in lab.objects.items() if a == 0]
        self.assertEqual(len(actions), 2)
        self.assertTrue(all(oracle.click_regret(lab, lab.goals[0], a) < 1e-8 for a in actions))

    def test_cached_planner_matches_original_and_invalidates_goal_and_weight(self) -> None:
        """Caching preserves the baseline policy and does not reuse an obsolete goal."""
        lab = make_lab('cycles', 0)
        engine = teach(lab)
        engine.start_goals([lab.goal(lab.goals[0])], observe(lab.at()))
        cached = Selector('dijkstra_cached')
        goal = engine.model['intent']['goals'][0]
        for _ in range(2):
            cached.route(engine.model, goal, dict(flows=[]))
        self.assertEqual(cached.stats['builds'], 1)
        self.assertEqual(cached.stats['cache_hits'], 1)
        reference = copy.deepcopy(engine.model)
        for node in reference['memory']['nodes']:
            if node['kind'] == 'state':
                node['sensory'] = 1
        event = planner.route(reference, goal, dict(flows=[]))
        duplicate = copy.deepcopy(reference)
        duplicate['refractory'] = {}
        event2 = cached.route(duplicate, goal, dict(flows=[]))
        self.assertEqual(event['winner'], event2['winner'])
        engine.start_goals([lab.goal(lab.goals[1])], observe(lab.at()))
        goal = engine.model['intent']['goals'][0]
        cached.route(engine.model, goal, dict(flows=[]))
        self.assertEqual(cached.stats['builds'], 2)
        edge = next(e for e in engine.model['memory']['edges'] if e['kind'] == 'backward')
        engine.set_weight(edge['id'], .1)
        cached.route(engine.model, goal, dict(flows=[]))
        self.assertEqual(cached.stats['builds'], 3)
        state = next(n for n in engine.model['memory']['nodes'] if n['kind'] == 'state')
        state['features'].append('new-observed-feature')
        cached.route(engine.model, goal, dict(flows=[]))
        self.assertEqual(cached.stats['builds'], 4)

    def test_distance_floor_control_exposes_default_threshold_limit(self) -> None:
        """A long known chain is solvable; lowering the predeclared floor isolates its limit."""
        lab = make_lab('chain', 0)
        base = teach(lab)
        self.assertGreater(LOW_THRESHOLD, .25)
        native = Trial(base, lab, 'native', 'static').run()
        self.assertFalse(native['success'])
        self.assertTrue(native['reachable'])
        for selector in ('native_low_threshold', 'dijkstra_cached'):
            row = Trial(base, lab, selector, 'static').run()
            self.assertTrue(row['success'], row)
            self.assertEqual(row['memory_before'], row['memory_after'])

    def test_spread_goal_change_is_delivered_and_resets_the_episode(self) -> None:
        """Every selector receives the change before any physical action."""
        lab = make_lab('chain', 0)
        for selector in ('native', 'native_low_threshold', 'dijkstra_cached'):
            row = Trial(teach(lab), lab, selector, 'during_spread').run()
            change = row['changes'][0]
            self.assertTrue(row['changed'])
            self.assertEqual(change['action_index'], 0)
            self.assertTrue(change['activation_cleared'] and change['old_episode_cleared'])
            self.assertFalse(row['false_success'])

    def test_reverse_goal_can_become_unreachable_after_irreversible_action(self) -> None:
        """Reachability must use the actual delivery state, not the initial state."""
        lab = make_lab('chain', 0)
        for selector in ('native', 'native_low_threshold', 'dijkstra_cached'):
            row = Trial(teach(lab), lab, selector, 'after_click').run()
            self.assertTrue(row['changed'])
            self.assertFalse(row['reachable'])
            self.assertTrue(row['correct'], row)
            self.assertFalse(row['success'])
            self.assertFalse(any(a['after_change'] for a in row['actions']))

    def test_pending_goal_is_delivered_after_exactly_one_inflight_click(self) -> None:
        """A request never discards or repeats an outstanding physical effect."""
        lab = make_lab('cycles', 0)
        for selector in ('native', 'native_low_threshold', 'dijkstra_cached'):
            row = Trial(teach(lab), lab, selector, 'pending_click').run()
            change = row['changes'][0]
            self.assertTrue(change['pending'])
            self.assertEqual(change['deliver_tick'] - change['request_tick'], 1)
            self.assertEqual(change['delivered_action_index'] - change['action_index'], 1)
            self.assertEqual(row['failed_effects'], 0)
            self.assertEqual(row['off_goal_after_change'], 0)
            requests = [a['receipt']['id'] for a in row['actions']]
            self.assertEqual(len(requests), len(set(requests)))

    def test_goal_api_rejects_preemption_before_receipt(self) -> None:
        """The harness deferral is required by the real execution contract."""
        lab = make_lab('chain', 0)
        engine = teach(lab)
        engine.start_goals([lab.goal(2)], observe(lab.at()))
        engine.model['pending'] = dict(id='inflight', action=dict(kind='click', object='x'))
        before = copy.deepcopy(engine.model)
        with self.assertRaises(ValueError):
            engine.start_goals([lab.goal(0)], observe(lab.at()))
        self.assertEqual(before, engine.model)


if __name__ == '__main__':
    unittest.main()
