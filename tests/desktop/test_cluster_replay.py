"""Behavioral and isolation regressions for the offline cluster comparison."""
from __future__ import annotations

import copy
import json
import os
import socket
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
import uuid

from kolos_states.cluster_replay.controllers import teach, trial
from kolos_states.cluster_replay.corpus import digest, save, split
from kolos_states.cluster_replay.model import public_input
from kolos_states.cluster_replay.isolation import offline_host
from kolos_states.cluster_replay.settings import read_settings
from kolos_states.cluster_replay.world import VARIANTS, World


def example(target: bool = False, index: int = 0) -> dict:
    """Explicit synthetic test fixture; the real benchmark imports saved records separately."""
    return dict(id='fixture-' + str(index), identity=dict(shop_id=1, nm_id=100 + index,
        vendor_code='private-sku-' + str(index)), campaign_id=200 + index, query='private-query-' + str(index),
        target=target, before=dict(excluded=not target, mode='AI', bid=300 + index),
        after=dict(excluded=target), evidence_ref='private-source-' + str(index))


class ReplaySettingsTests(unittest.TestCase):
    """Installation data can be absent and is never required by the simulator."""

    def test_default_and_private_config_are_loaded_without_source_data(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            self.assertIsNone(read_settings(path).teaching_product_id)
            save(path, {'teaching_product_id': 123, 'corpus': 'corpus.json'})
            self.assertEqual(read_settings(path).teaching_product_id, 123)
            self.assertEqual(read_settings(path).corpus, path.parent / 'corpus.json')
            save(path, {'teaching_product_id': True})
            with self.assertRaisesRegex(ValueError, 'positive integer'):
                read_settings(path)


class ClusterReplayTests(unittest.TestCase):
    """No test imports a WB connector or calls a model/network endpoint."""

    def setUp(self) -> None:
        """Teach only the restoration; exclusion is a new value and task identity."""
        self.learned, self.setup_cost = teach(example())

    def test_split_selects_first_restoration_or_explicit_synthetic_product(self) -> None:
        """Never choose an exclusion as the restoration teaching example."""
        excluded, first, other = example(True, 1), example(False, 2), example(False, 3)
        corpus = {'cases': [excluded, first, other]}
        self.assertEqual(split(corpus), (first, [excluded, other]))
        self.assertEqual(split(corpus, teaching_product_id=103), (other, [excluded, first]))
        for missing in (101, 999):
            with self.assertRaisesRegex(ValueError, 'No restoration'):
                split(corpus, teaching_product_id=missing)

    def test_new_product_ids_and_reverse_operation_use_learned_dataflow(self) -> None:
        """No whole exclusion demonstration or literal remembered value is needed."""
        before = digest(self.learned)
        for target in (True, False):
            for layout in (0, 1, 2):
                row = trial(example(target, 99), 'clean', 'kolos', self.learned, layout=layout)
                self.assertTrue(row['correct_outcome'], row)
                self.assertEqual(row['save_attempts'], 1)
        self.assertEqual(before, digest(self.learned))

    def test_all_failure_variants_are_safe_for_both_deterministic_controllers(self) -> None:
        """Guard rejection, stale proof and unknown receipts never become false success."""
        for selector in ('script', 'kolos'):
            for variant in VARIANTS:
                with self.subTest(selector=selector, variant=variant):
                    row = trial(example(True, 1), variant, selector, self.learned)
                    self.assertTrue(row['correct_outcome'], row)
                    self.assertFalse(row['false_success'])
                    self.assertLessEqual(row['save_attempts'], 1)
                    if variant in ('wrong_identity', 'no_approval', 'already_applied', 'ambiguous_field', 'changed_after_begin'):
                        self.assertEqual(row['applied'], 0)

    def test_disabling_learned_connection_stops_kolos_without_script_fallback(self) -> None:
        """The Kolos arm actually consumes the production graph, not a renamed script."""
        damaged = copy.deepcopy(self.learned)
        edge = next(e for e in damaged['model']['memory']['edges'] if e['kind'] == 'episode_next')
        edge['weight'] = 0
        row = trial(example(True, 1), 'clean', 'kolos', damaged)
        self.assertEqual(row['status'], 'blocked')
        self.assertEqual(row['save_attempts'], 0)
        self.assertTrue(trial(example(True, 1), 'clean', 'script', damaged)['completed'])

    def test_arbitrary_model_instructions_are_data_and_cannot_execute(self) -> None:
        """The only execution surface is a finite local operation allowlist."""
        bad = dict(operations=[dict(kind='terminal', role='curl https://example.invalid')], outcome='complete')
        row = trial(example(True, 1), 'clean', 'model_skill', self.learned, bad)
        self.assertEqual(row['status'], 'blocked')
        self.assertEqual(row['operations'], [])
        self.assertEqual(row['applied'], 0)
        self.assertTrue(row['protocol_error'])

    def test_model_cannot_claim_success_without_observed_effect_and_record(self) -> None:
        """The outcome oracle is independent of the plan's final declaration."""
        row = trial(example(True, 1), 'clean', 'model_skill', self.learned,
                    dict(operations=[], outcome='complete'))
        self.assertTrue(row['false_success'])
        self.assertFalse(row['correct_outcome'])

    def test_replay_host_rejects_network_even_for_local_connections(self) -> None:
        """An accidental connector cannot reach real ads from the benchmark process."""
        with offline_host():
            with self.assertRaises(PermissionError):
                socket.create_connection(('127.0.0.1', 1))
            with socket.socket() as client, self.assertRaises(PermissionError):
                client.connect(('127.0.0.1', 1))

    def test_model_input_contains_no_business_identifiers_or_source_strings(self) -> None:
        """Aliasing preserves equality/inequality while excluding the real source values."""
        case = example(True, 42)
        for variant in ('clean', 'wrong_identity'):
            payload = public_input(World(case, variant))
            text = json.dumps(payload)
            for value in (case['id'], case['identity']['vendor_code'], case['query'], case['evidence_ref']):
                self.assertNotIn(value, text)
            context = payload['context']
            self.assertEqual(context['expected_scope'] == context['observed_scope'], variant == 'clean')
            self.assertEqual(context['task']['identity']['nm_id'], 'demo-product')

    def test_real_process_reload_retains_episode_without_teaching_test_task(self) -> None:
        """A fresh interpreter receives only JSON memory and a new task value/identity."""
        directory = Path(__file__).resolve().parents[1] / 'desktop-output' / ('cluster-unit-' + uuid.uuid4().hex)
        directory.mkdir(parents=True)
        save(directory / 'learned.json', self.learned)
        save(directory / 'case.json', example(True, 7))
        script = ('import json,sys,os; from pathlib import Path; '
                  'from kolos_states.cluster_replay.controllers import trial; '
                  'p=Path(sys.argv[1]); '
                  'r=trial(json.loads((p/"case.json").read_text()),"clean","kolos",'
                  'json.loads((p/"learned.json").read_text()),layout=7); '
                  'print(json.dumps({"pid":os.getpid(),"row":r}))')
        result = json.loads(subprocess.check_output([sys.executable, '-B', '-c', script, str(directory)],
                            cwd=Path(__file__).resolve().parents[2], text=True))
        self.assertTrue(result['row']['correct_outcome'], result)
        self.assertEqual(result['row']['save_attempts'], 1)
        self.assertNotEqual(result['pid'], os.getpid())


if __name__ == '__main__':
    unittest.main()
