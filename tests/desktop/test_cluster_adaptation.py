"""Procedure-change regressions use synthetic development tasks only."""
from __future__ import annotations

import copy
from pathlib import Path
import unittest
import uuid

from kolos_states.cluster_replay.controllers import teach
from kolos_states.cluster_replay.corpus import digest, save
from kolos_states.cluster_replay.model import public_input
from kolos_states.cluster_adaptation.controllers import NEW_QUERY, teach_revision, trial
from kolos_states.cluster_adaptation.suite import run
from kolos_states.cluster_adaptation.world import PREVIEW_ROLE, REVIEW, World, operations, variants
from tests.desktop.test_cluster_replay import example


class ClusterAdaptationTests(unittest.TestCase):
    """The extra step is learned once; held-out values and faults are not taught."""

    def setUp(self) -> None:
        """Keep the original graph and train a separate v2 restoration command."""
        self.original, _ = teach(example())
        self.revised, self.cost = teach_revision(self.original, example())

    def test_frozen_policies_stop_at_new_gate_but_exclusion_still_works(self) -> None:
        """Changed procedures do not magically edit the script or the existing memory."""
        for selector in ('script', 'kolos'):
            row = trial(example(False, 7), 'clean', selector, self.original, False)
            self.assertEqual(row['status'], 'blocked')
            self.assertEqual(row['review_rejections'], 1)
            self.assertEqual(row['applied'], 0)
            self.assertFalse(row['correct_outcome'])
            old = trial(example(True, 8), 'clean', selector, self.original, False)
            self.assertTrue(old['correct_outcome'], old)
            self.assertEqual(old['review_calls'], 0)

    def test_one_demonstration_transfers_to_other_products_and_object_layouts(self) -> None:
        """Nine operations on restoration, eight on unchanged exclusion, no case-specific retraining."""
        frozen = digest(self.revised)
        for selector in ('script', 'kolos'):
            for target in (False, True):
                for layout in (1, 2):
                    row = trial(example(target, 100 + layout), 'clean', selector, self.revised, True, layout=layout)
                    self.assertTrue(row['correct_outcome'], row)
                    self.assertEqual(len(row['operations']), 8 if target else 9)
                    self.assertEqual(row['review_calls'], 0 if target else 1)
                    self.assertEqual(row['save_attempts'], 1)
        self.assertEqual(digest(self.revised), frozen)

    def test_missing_preview_effect_or_invalidated_binding_blocks_before_effect(self) -> None:
        """Neither a clicked button nor an old preview substitutes for a verified current result."""
        for selector in ('script', 'kolos'):
            for variant in ('preview_no_effect', 'preview_invalidated'):
                row = trial(example(False, 77), variant, selector, self.revised, True)
                self.assertTrue(row['correct_outcome'], row)
                self.assertEqual(row['status'], 'blocked')
                self.assertEqual(row['applied'], 0)
                self.assertFalse(row['false_success'])
                self.assertEqual(row['save_attempts'], 0 if variant == 'preview_no_effect' else 1)

    def test_every_original_fault_remains_safe_after_the_new_lesson(self) -> None:
        """New knowledge does not weaken scope, approval, receipt or readback checks."""
        for selector in ('script', 'kolos'):
            for target in (False, True):
                case = example(target, 20)
                for variant in variants(case):
                    with self.subTest(selector=selector, target=target, variant=variant):
                        row = trial(case, variant, selector, self.revised, True)
                        self.assertTrue(row['correct_outcome'], row)
                        self.assertFalse(row['repeated_save'])

    def test_old_graph_is_preserved_and_the_new_graph_path_is_causally_required(self) -> None:
        """Adding a command is explicit full-episode learning, not an undisclosed scripted fallback."""
        self.assertTrue(self.cost['old_graph_preserved'])
        self.assertEqual(self.cost['demonstrations'], 1)
        self.assertEqual(self.cost['demonstrated_operations'], 9)
        self.assertFalse(self.cost['incremental_splice'])
        damaged = copy.deepcopy(self.revised)
        command = next(c for c in damaged['model']['episodeCommands'] if c['query'] == NEW_QUERY)
        edge = next(e for e in damaged['model']['memory']['edges']
                    if e['kind'] == 'episode_next' and e['from'] == command['node'])
        edge['weight'] = 0
        self.assertEqual(trial(example(False, 5), 'clean', 'kolos', damaged, True)['status'], 'blocked')
        self.assertTrue(trial(example(True, 6), 'clean', 'kolos', damaged, True)['completed'])

    def test_retained_v1_restoration_needs_no_preview(self) -> None:
        """A separate old-form query still follows the original learned eight steps."""
        for selector in ('script', 'kolos'):
            row = trial(example(False, 3), 'clean', selector, self.revised, True, revision=1)
            self.assertTrue(row['completed'])
            self.assertEqual(row['review_calls'], 0)
            self.assertEqual(len(row['operations']), 8)

    def test_new_model_surface_still_rejects_unknown_parameters(self) -> None:
        """The added role extends one local operation without adding an execution escape."""
        plan = dict(operations=operations(True), outcome='complete')
        plan['operations'][4] = dict(REVIEW, command='write-to-real-advertising')
        row = trial(example(False, 7), 'clean', 'model_skill', self.revised, True, plan=plan)
        self.assertTrue(row['protocol_error'])
        self.assertEqual(row['applied'], 0)
        payload = public_input(World(example(False, 987)))
        self.assertEqual(payload['context']['task']['identity']['nm_id'], 'demo-product')
        self.assertTrue(any(o['descriptor']['name'] == PREVIEW_ROLE for o in payload['observation']['objects']))

    def test_local_suite_restores_revised_memory_in_a_real_new_process(self) -> None:
        """Full orchestration is testable without a model or any live business input."""
        directory = Path(__file__).resolve().parents[1] / 'desktop-output' / ('adapt-unit-' + uuid.uuid4().hex)
        directory.mkdir(parents=True)
        teacher = example()
        corpus = dict(schema='kolos-cluster-replay/1', cases=[teacher, example(False, 1), example(True, 2)])
        save(directory / 'corpus-input.json', corpus)
        data = run(directory / 'run', directory / 'corpus-input.json', False, None,
                   teaching_product_id=teacher['identity']['nm_id'])
        self.assertEqual(data['protocol']['teaching_case'], teacher['id'])
        self.assertEqual(len(data['rows']), 48)
        self.assertTrue(data['restart']['different_pid'])
        self.assertTrue(data['restart']['graph_equal'])
        self.assertTrue(data['restart']['graph_unchanged'])
        self.assertTrue(all(r['correct_outcome'] for r in data['restart']['rows']))


if __name__ == '__main__':
    unittest.main()
