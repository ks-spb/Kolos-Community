"""Confirmed tasks come from saved lessons, never from typed or staged commands."""
import copy
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from kolos_states.cli import Terminal
from kolos_states.core import StateEngine
from kolos_states.ipc import read_json
from kolos_states.learned_tasks import confirmed_tasks
from kolos_states.simulator import default_world, demonstrate, icon_actions
from kolos_states.storage import Store


def lesson(query='открой окно'):
    world = default_world()
    return demonstrate(query, world, icon_actions(world, 'A'))


class ConfirmedTasksTests(unittest.TestCase):
    def terminal(self, folder):
        terminal = Terminal.__new__(Terminal)
        terminal.engine = StateEngine()
        terminal.store = Store(Path(folder) / 'memory')
        self.addCleanup(terminal.store.close)
        terminal.path = Path(folder)
        terminal.args = SimpleNamespace(session='tasks-test')
        terminal.neuron_trace = Mock()
        terminal.running = False
        terminal.pause = threading.Event()
        terminal.recording = False
        terminal.record = None
        terminal.staged = None
        return terminal

    def tasks(self, terminal):
        terminal.publish()
        return read_json(terminal.path / 'status.json')['confirmedTasks']

    def test_query_record_and_save_stay_hidden_until_approval(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        terminal = self.terminal(folder)
        terminal.command('/query открой окно')
        self.assertEqual(self.tasks(terminal), [])
        terminal.record = lesson()
        self.assertEqual(self.tasks(terminal), [])
        with patch('builtins.print'):
            terminal.command('5')
            self.assertEqual(self.tasks(terminal), [])
            terminal.command('1')
        tasks = self.tasks(terminal)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]['query'], 'открой окно')
        self.assertEqual(tasks[0]['demonstrations'], 1)
        self.assertEqual(len(tasks[0]['actions']), len(terminal.record['receipts']))
        self.assertEqual(confirmed_tasks(terminal.store.load().model['lessons']), tasks)

    def test_failed_approval_and_prior_key_exposure_do_not_create_a_task(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        terminal = self.terminal(folder)
        with self.assertRaises(ValueError):
            terminal.command('1')
        self.assertEqual(self.tasks(terminal), [])
        world = default_world()
        world.update(surface='calculator', focus='FIELD')
        terminal.staged = demonstrate('прежние клавиши', world, [dict(kind='key', value='1')])
        with patch('builtins.print'):
            terminal.command('/expose')
        self.assertEqual(len(terminal.engine.model['exposures']), 1)
        self.assertEqual(self.tasks(terminal), [])
        invalid = lesson()
        invalid['receipts'][0]['ok'] = False
        terminal.staged = invalid
        with self.assertRaises(ValueError):
            terminal.command('1')
        self.assertEqual(self.tasks(terminal), [])

    def test_repeat_approval_groups_exact_queries_without_mutating_memory(self):
        engine = StateEngine()
        for query in ('открой окно', 'открой окно', 'Открой окно', 'открой окно '):
            engine.learn(lesson(query))
        before = copy.deepcopy(engine.model)
        tasks = confirmed_tasks(engine.model['lessons'])
        self.assertEqual([task['query'] for task in tasks], ['открой окно', 'Открой окно', 'открой окно '])
        self.assertEqual([task['demonstrations'] for task in tasks], [2, 1, 1])
        tasks[0]['actions'].append('presentation only')
        self.assertEqual(engine.model, before)


if __name__ == '__main__':
    unittest.main()
