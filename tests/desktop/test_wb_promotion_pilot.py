"""Synthetic manifests for a versioned lesson, durable post-restart replay and accounting."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from kolos_states import wb_promotion_pilot as pilot
from kolos_states.ipc import atomic_json
from kolos_states.wb_promotion_codex import turn_result


class WbPromotionPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = pilot.OUTPUT / 'test' / uuid4().hex
        cls.root.mkdir(parents=True)
        cls.data = pilot.read(pilot.DATA / 'manifests.json')
        cls.truth = pilot.read(pilot.DATA / 'expected.json')
        cls.original = pilot._base(cls.root, None)

    def folder(self):
        return self.root / uuid4().hex

    def rule(self, threshold=2):
        return dict(rule_version='v2', operation=pilot.OPERATION, fresh_exports=threshold)

    def controls(self):
        return tuple((self.data[key], self.truth[key]) for key in ('B', 'C'))

    def test_local_series_restarts_and_does_not_instantiate_codex(self):
        folder = self.root / 'Проверка WB'
        with patch.object(pilot, 'Codex', side_effect=AssertionError('unexpected model adapter')):
            report = pilot.run_series(folder)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['summary']['cycle']['kolos']['total_tokens'], 0)
        self.assertIsNone(report['summary']['cycle']['saved_tokens'])
        lesson, replay = (report['kolos'][key] for key in ('B', 'C'))
        for key in ('rule_sha256', 'memory_sha256'):
            self.assertEqual(lesson[key], replay[key])
        for key in ('pid', 'run_id', 'input_sha256'):
            self.assertNotEqual(lesson[key], replay[key])
        self.assertEqual(replay['result'], self.truth['C'])
        self.assertTrue(all(row['status'] == 'not_run' for row in report['direct_codex'].values()))
        self.assertEqual(pilot.read(folder / 'report.json'), report)

    def test_candidate_matching_open_case_can_fail_closed_check(self):
        folder = self.folder()
        result, _ = pilot.classify(self.data['B'], 3)
        self.assertEqual(result, self.truth['B'])
        with self.assertRaisesRegex(ValueError, 'эталоном'):
            pilot.publish_rule(folder, self.rule(3), self.original, self.controls())
        self.assertFalse(folder.exists())

    def test_reload_checks_rule_and_native_graph_confirmation(self):
        folder = self.folder()
        evidence = pilot.publish_rule(folder, self.rule(), self.original, self.controls())
        atomic_json(folder / 'rule.json', self.rule(3))
        with self.assertRaisesRegex(ValueError, 'Отпечатки'):
            pilot.load_rule(folder)
        atomic_json(folder / 'rule.json', self.rule())
        atomic_json(folder / 'memory.json', self.original)
        atomic_json(folder / 'published.json', dict(evidence, memory_sha256=pilot.digest(self.original)))
        with self.assertRaisesRegex(ValueError, 'подтверждения'):
            pilot.load_rule(folder)

    def test_different_threshold_is_read_from_saved_rule(self):
        folder = self.folder()
        expected = dict(self.truth['C'], missing_ids=['C01', 'C02', 'C03', 'C05', 'C06'],
                        complete_ids=['C04'], excess_fresh_ids=[])
        pilot.publish_rule(folder, self.rule(3), self.original, ((self.data['C'], expected),))
        self.assertEqual(pilot.replay_process(folder, self.data['C'])['result'], expected)

    def test_partial_publication_keeps_v1_available(self):
        folder = self.folder()

        def interrupt(path: Path, payload: dict) -> None:
            if path.name == 'published.json':
                raise OSError('interrupted')
            atomic_json(path, payload)

        with patch.object(pilot, 'atomic_json', side_effect=interrupt):
            with self.assertRaisesRegex(OSError, 'interrupted'):
                pilot.publish_rule(folder, self.rule(), self.original, self.controls())
        self.assertTrue((folder / 'memory.json').is_file())
        with self.assertRaisesRegex(ValueError, 'Требуется урок'):
            pilot.load_rule(folder)
        result, _ = pilot.classify(self.data['D'], 1, self.root / 'v1')
        self.assertEqual(result, self.truth['D'])

    def test_one_attempt_per_directory(self):
        folder = self.folder()
        record = pilot._step(self.data['B'], 'kolos')
        candidate = self.rule()

        def respond(prompt, schema):
            self.assertNotIn('C03', prompt)
            self.assertEqual(schema, pilot.RULE_SCHEMA)
            return dict(answer=candidate, usage=pilot._usage(15), codex_exec_count=1,
                        completed_turns=1, failure=None, seconds=.1)

        with patch.object(pilot, '_prompt', wraps=pilot._prompt) as prompt:
            self.assertEqual(pilot._call(folder, record, self.data['B'], respond, teach=True), candidate)
            with self.assertRaises(FileExistsError):
                pilot._call(folder, record, self.data['B'], respond, teach=True)
            self.assertEqual(prompt.call_count, 1)
        self.assertEqual(pilot.read(folder / 'attempt.json')['codex_exec_count'], 1)

    def test_bad_source_cannot_request_a_model(self):
        with patch.object(pilot, 'Codex', side_effect=AssertionError('unexpected model adapter')):
            report = pilot.run_series(self.folder(), 'unused', self.folder() / 'memory.json')
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['summary']['cycle']['kolos']['codex_exec_count'], 0)

    def test_compare_pairs_calls_and_usage_without_counting_cached_input_twice(self):
        source = self.root / 'base' / 'memory.json'
        for complete in (True, False):
            with self.subTest(complete=complete), patch.object(pilot, 'Codex') as codex:
                seen = []

                def respond(prompt, schema):
                    data = json.loads(prompt.rsplit('\n', 1)[-1])
                    key = next(key for key, manifest in self.data.items() if manifest == data)
                    teach = schema == pilot.RULE_SCHEMA
                    seen.append((key, teach))
                    output = 3 if complete or key != 'D' else None
                    return dict(answer=self.rule() if teach else self.truth[key],
                                usage=dict(input_tokens=20, output_tokens=output, cached_input_tokens=7),
                                codex_exec_count=1, completed_turns=1, failure=None, seconds=.1)

                codex.return_value.side_effect = respond
                codex.return_value.version = 'test'
                report = pilot.run_series(self.folder(), 'test', source)

                self.assertEqual(seen, [('B', True), *((key, False) for key in pilot.STEPS)])
                self.assertEqual([report['kolos'][key]['codex_exec_count'] for key in pilot.STEPS], [0, 1, 0, 0])
                self.assertEqual(report['status'], 'passed' if complete else 'incomplete_usage')
                full = report['summary']['cycle']
                self.assertEqual(full['kolos']['total_tokens'], 23)
                self.assertEqual(full['direct_codex']['known']['cached_input_tokens'], 28)
                self.assertEqual(full['direct_codex']['total_tokens'], 92 if complete else None)
                self.assertEqual(full['saved_tokens'], 69 if complete else None)
                self.assertEqual(report['summary']['lesson_and_repeat']['saved_tokens'], 23)

    def test_invalid_inputs_and_boundary_time(self):
        invalid = copy.deepcopy(self.data['A'])
        invalid['manifest']['expected_promotions'] = True
        with self.assertRaises(ValueError):
            pilot.validate_manifest(invalid)
        invalid = dict(self.data['A'], expected_ids=['A01', 'A01', 'A02'])
        with self.assertRaises(ValueError):
            pilot.validate_manifest(invalid)
        with self.assertRaises(ValueError):
            pilot.validate_rule(self.rule(True))
        invalid = dict(self.data['A'], rule_version='v3')
        with self.assertRaises(ValueError):
            pilot.validate_manifest(invalid)
        data = dict(self.data['B'], observed_at='2026-11-27T00:00:00+03:00', expected_ids=['B01'], manifest=dict(
            expected_promotions=1, unique_products=0, failed=[], collected=[
                dict(promotion_id='B01', observed_at='2026-11-26T21:00:00Z'),
                dict(promotion_id='B01', observed_at='2026-11-27T00:00:01+03:00'),
                dict(promotion_id='B01', observed_at='2026-11-26T23:59:59+03:00')]))
        result, _ = pilot.classify(pilot.validate_manifest(data), 1)
        self.assertEqual(result['complete_ids'], ['B01'])
        self.assertEqual(result['stale_ids'], ['B01'])


class UsageTests(unittest.TestCase):
    def test_keep_usage_before_truncated_line_and_tool_during_failure(self):
        usage = dict(input_tokens=40, output_tokens=7, cached_input_tokens=20)
        records = [dict(type='item.started', item=dict(type='command_execution')),
                   dict(type='turn.completed', usage=usage)]
        source = ('\n'.join(map(json.dumps, records)) + '\n{"type":').encode()
        result = turn_result(source, 'codex_timeout')
        self.assertEqual(result['failure'], 'codex_timeout')
        self.assertEqual(result['usage'], usage)
        self.assertIsNone(result['answer'])

    def test_invalid_or_duplicate_response_is_not_a_zero_cost_result(self):
        usage = dict(input_tokens=40, output_tokens=7, cached_input_tokens=80)
        source = '\n'.join(map(json.dumps, [dict(type='item.completed', item=dict(
            type='agent_message', text='{"fresh_exports":3,"fresh_exports":2}')),
            dict(type='turn.completed', usage=usage)]))
        result = turn_result(source)
        self.assertEqual(result['failure'], 'codex_invalid_response')
        self.assertEqual(result['usage'], dict(input_tokens=40, output_tokens=7, cached_input_tokens=None))
        duplicate = turn_result(source + '\n' + json.dumps(dict(type='turn.completed', usage=usage)))
        self.assertEqual(duplicate['usage'], pilot._usage(None))
