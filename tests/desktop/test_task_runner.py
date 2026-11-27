"""Exercise the normal runner path, including learn-once behavior and shared memory."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest
from unittest.mock import patch

from kolos_states import task_runner as runner
from kolos_states.runner_providers import claude_result

WB_RULE = dict(rule_version='v2', operation='exact_fresh_exports', fresh_exports=2)
TABLE_RULE = dict(reduce='sum', value='units', group='category', predicate=dict(column='units', op='>', threshold=2))


def model_reply(rule):
    return dict(answer=rule, codex_exec_count=1, usage=dict(input_tokens=42, output_tokens=8, cached_input_tokens=7),
                failure=None)


class TaskRunnerTests(unittest.TestCase):
    def setUp(self):
        scratch = TemporaryDirectory(prefix='kolos-runner-test-')
        self.addCleanup(scratch.cleanup)
        self.state = Path(scratch.name)

    def run_sample(self, family, name, **options):
        return runner.run(runner.SAMPLES / f'{family}-task.json', runner.SAMPLES / f'{family}-{name}.json',
                          state=self.state, **options)

    def test_wb_lesson_and_repeat_do_not_send_manifests(self):
        with patch.object(runner.runner_providers, 'teach', return_value=model_reply(WB_RULE)) as teach:
            first = self.run_sample('wb', 'first')
            second = self.run_sample('wb', 'next', provider='claude')
        teach.assert_called_once()
        _, _, prompt, _ = teach.call_args.args
        self.assertIn('две', prompt)
        self.assertNotIn('P01', prompt)
        self.assertNotIn('B01', prompt)
        self.assertEqual((first['status'], first['mode'], first['model_calls']), ('ok', 'lesson', 1))
        self.assertEqual(first['usage']['input_tokens'], 42)
        self.assertEqual((second['status'], second['mode'], second['model_calls']), ('ok', 'local', 0))
        self.assertEqual(second['usage'], dict.fromkeys(runner.USAGE_KEYS, 0))
        self.assertEqual(first['rule_sha256'], second['rule_sha256'])
        self.assertNotEqual(first['input_sha256'], second['input_sha256'])
        self.assertEqual(second['result']['missing_ids'], ['R01', 'R02'])
        self.assertEqual(second['result']['complete_ids'], ['R03', 'R05', 'R06'])
        self.assertEqual(runner.read_json(Path(second['report_path'])), second)

    def test_table_task_reuses_rule_and_key_changes_with_instruction(self):
        with patch.object(runner.runner_providers, 'teach', return_value=model_reply(TABLE_RULE)) as teach:
            first = self.run_sample('table', 'first', provider='claude')
            again = self.run_sample('table', 'next', provider='none')
        self.assertEqual(teach.call_args.args[0], 'claude')
        teach.assert_called_once()
        self.assertEqual(first['result'], {'Hardware': 5, 'Office': 7})
        self.assertEqual(again['result'], {'Tools': 10})

        new_task = self.state / 'updated.json'
        definition = runner.read_json(runner.SAMPLES / 'table-task.json')
        definition['instruction'] += ' Новая версия.'
        new_task.write_text(json.dumps(definition), encoding='utf-8')
        missing = runner.run(new_task, runner.SAMPLES / 'table-next.json', state=self.state, provider='none')
        self.assertEqual(missing['status'], 'needs_lesson')
        self.assertNotEqual(missing['task_sha256'], again['task_sha256'])

    def test_bad_rule_keeps_usage_and_does_not_publish(self):
        with patch.object(runner.runner_providers, 'teach', return_value=model_reply(dict(WB_RULE, fresh_exports=3))):
            first = self.run_sample('wb', 'first')
        self.assertEqual(first['status'], 'error')
        self.assertEqual(first['model_calls'], 1)
        self.assertEqual(first['usage']['output_tokens'], 8)
        self.assertEqual(self.run_sample('wb', 'next', provider='none')['status'], 'needs_lesson')

    def test_bad_input_and_corruption_never_pay_for_lesson(self):
        invalid = self.state / 'bad.json'
        invalid.write_text('[{"category": "Private name", "units": true}]', encoding='utf-8')
        with patch.object(runner.runner_providers, 'teach', return_value=model_reply(TABLE_RULE)) as teach:
            self.assertEqual(runner.run(runner.SAMPLES / 'table-task.json', invalid, state=self.state)['status'], 'error')
            teach.assert_not_called()
            proof = self.run_sample('table', 'first')
            self.assertEqual(proof['status'], 'ok')
            stored = self.state / 'rules' / proof['task_sha256'] / 'published.json'
            payload = runner.read_json(stored)
            payload['rule']['value'] = 'nonexistent'
            stored.write_text(json.dumps(payload), encoding='utf-8')
            repeated = self.run_sample('table', 'next')
            self.assertEqual((repeated['status'], repeated['model_calls']), ('error', 0))
            teach.assert_called_once()

    def test_single_lesson_across_two_concurrent_jobs(self):
        started, release = Event(), Event()
        results = []

        def respond(*_):
            started.set()
            self.assertTrue(release.wait(10))
            return model_reply(WB_RULE)

        with patch.object(runner.runner_providers, 'teach', side_effect=respond) as teach:
            work = Thread(target=lambda: results.append(self.run_sample('wb', 'first')))
            work.start()
            try:
                self.assertTrue(started.wait(10))
                competing = self.run_sample('wb', 'next')
                self.assertEqual((competing['status'], competing['model_calls']), ('error', 0))
            finally:
                release.set()
                work.join(timeout=10)
            self.assertEqual(results[0]['status'], 'ok')
            teach.assert_called_once()

    def test_claude_counts_include_fresh_and_cached_usage(self):
        event = dict(type='result', subtype='success', is_error=False, num_turns=1, structured_output=WB_RULE,
                     usage=dict(input_tokens=5, cache_creation_input_tokens=9, cache_read_input_tokens=7, output_tokens=2))
        answer = claude_result(json.dumps(event))
        self.assertEqual(answer['answer'], WB_RULE)
        self.assertEqual(answer['usage'], dict(input_tokens=21, output_tokens=2, cached_input_tokens=7))
        failed = copy.deepcopy(event)
        failed['num_turns'] = 2
        failed['usage'].pop('output_tokens')
        answer = claude_result(json.dumps(failed))
        self.assertIsNone(answer['answer'])
        self.assertIsNone(answer['usage']['output_tokens'])
        self.assertEqual(answer['usage']['input_tokens'], 21)
