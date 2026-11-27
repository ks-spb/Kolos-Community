"""Behavioral checks for information boundaries, fair controls and persistence."""
from __future__ import annotations

import copy
import unittest
import uuid
from pathlib import Path

from kolos_states.transfer.planner import distances
from kolos_states.transfer.report import paired_interval
from kolos_states.transfer.runner import fingerprint, remove_focus_links, run_case
from kolos_states.transfer.suite import adaptation, source_hashes
from kolos_states.transfer.world import cases, make_lab, teach


class TransferExperimentTests(unittest.TestCase):
    """Only development seed 0 is inspected before the held-out experiment."""

    def setUp(self) -> None:
        """Create the same eight independent lessons for each test."""
        self.lab = make_lab(0)
        self.base = teach(self.lab)

    def test_unseen_composition_and_values_without_memory_changes(self) -> None:
        """Both complete all novel combinations with fixed long-term memory."""
        for selector in ('native', 'planner'):
            for spec in cases(0):
                row = run_case(copy.deepcopy(self.base), self.lab, spec, selector)
                self.assertTrue(row['success'], row)
                self.assertFalse(row['false_success'])
                self.assertEqual(row['memory_before'], row['memory_after'])

    def test_single_fragment_control_is_capable_but_cannot_compose(self) -> None:
        """The weak baseline has a positive control, rather than being broken."""
        row = run_case(copy.deepcopy(self.base), self.lab, cases(0)[0], 'single')
        self.assertFalse(row['success'])
        row = run_case(copy.deepcopy(self.base), self.lab,
                       dict(case=0, start='form', value='3521'), 'single')
        self.assertTrue(row['success'])

    def test_removing_all_known_focus_edges_blocks_both_selectors(self) -> None:
        """Neither controller has a hidden route to a goal disconnected in memory."""
        for selector in ('native', 'planner'):
            engine = copy.deepcopy(self.base)
            remove_focus_links(engine, self.lab.field)
            row = run_case(engine, self.lab, cases(0)[0], selector)
            self.assertEqual(row['status'], 'blocked')
            self.assertFalse(row['false_success'])
            self.assertFalse(any(a['kind'] == 'key' for a in row['actions']))

    def test_planner_reacts_to_learned_weights_without_world_access(self) -> None:
        """The planner consumes only model data; zero learned edges remove paths."""
        from kolos_states.simulator import observe
        engine = copy.deepcopy(self.base)
        goal = dict(kind='field', focus=self.lab.field, value='3521')
        engine.start_goals([goal], observe(self.lab.at('desk')))
        costs, _ = distances(engine.model, goal)
        desk = engine.state(observe(self.lab.at('desk')))['id']
        self.assertIn(desk, costs)
        remove_focus_links(engine, self.lab.field)
        costs, _ = distances(engine.model, goal)
        self.assertNotIn(desk, costs)

    def test_distractor_learning_really_shares_the_old_state(self) -> None:
        """New paths branch from an existing state, not isolated disconnected toys."""
        from kolos_states.simulator import observe
        engine = copy.deepcopy(self.base)
        desk = engine.state(observe(self.lab.at('desk')))['id']
        before = sum(n.get('from') == desk for n in engine.model['memory']['nodes'])
        for lesson in self.lab.extra_lessons:
            engine.learn(lesson)
        after = sum(n.get('from') == desk for n in engine.model['memory']['nodes'])
        self.assertEqual(after - before, 5)

    def test_no_complete_solution_is_in_demonstrations(self) -> None:
        """Each regular demonstration contains exactly one observed transition."""
        self.assertEqual(len(self.lab.lessons), 7)
        for lesson in self.lab.lessons:
            self.assertEqual([r['action']['kind'] for r in lesson['receipts']], ['move', 'check', 'click'])
        self.assertEqual(len(self.base.model['exposures']), 1)
        self.assertFalse(any(c['value'] == '0123456789' for c in cases(0)))

    def test_process_restart_and_frozen_graph(self) -> None:
        """Production serialization restores the identical graph in another PID."""
        data = dict(groups={}, restarts=[])
        directory = Path(__file__).resolve().parents[1] / 'desktop-output' / ('transfer-unit-' + uuid.uuid4().hex)
        directory.mkdir(parents=True)
        adaptation(data, self.lab, self.base, directory, 'native', 0)
        restart = data['restarts'][0]
        self.assertTrue(restart['different_pid'])
        self.assertTrue(restart['transient_clean'])
        self.assertTrue(restart['graph_equal'])
        self.assertEqual(restart['retention'], dict(passed=8, total=8))
        self.assertTrue(all(r['memory_before'] == r['memory_after'] for r in data['groups']['native_post_off']))

    def test_snapshot_hash_ignores_transients_but_not_learning(self) -> None:
        """A restart comparison cannot be passed just by omitting changed weights."""
        before = fingerprint(self.base)
        node = self.base.model['memory']['nodes'][1]
        node.update(inhibition=1, sensory=1, eligibility=1)
        self.assertEqual(before, fingerprint(self.base))
        self.base.model['memory']['edges'][0]['weight'] = .1
        self.assertNotEqual(before, fingerprint(self.base))

    def test_cluster_summary_and_source_provenance(self) -> None:
        """Bootstrap uses paired world means and source hashes include the core."""
        a = [dict(seed=seed, value=value) for seed, value in [(1, 1), (1, 1), (2, 0)]]
        b = [dict(seed=seed, value=0) for seed in (1, 1, 2)]
        self.assertEqual(paired_interval(a, b, 'value')['mean_left_minus_right'], .5)
        self.assertIn('kolos_states/core.py', source_hashes())


if __name__ == '__main__':
    unittest.main()
