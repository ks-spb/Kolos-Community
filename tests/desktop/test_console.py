import json
import importlib.util
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from kolos_states.cli import Terminal
from kolos_states.ipc import atomic_json, read_json
from kolos_states.protocol import clone

ROOT = Path(__file__).resolve().parents[2]


class ConsoleTests(unittest.TestCase):
    def terminal(self, folder):
        terminal = Terminal(SimpleNamespace(ipc=folder, session='console-test',
                                            memory=str(Path(folder) / 'memory'), glaz_pid=0))
        self.addCleanup(terminal.store.close)
        return terminal

    @unittest.skipUnless(os.name == 'nt', 'Windows file replacement semantics')
    def test_status_survives_busy_reader_and_publishes_latest_state_after_release(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        terminal = self.terminal(folder)
        terminal.publish()
        path = terminal.path / 'status.json'
        previous = read_json(path)
        terminal.engine.model['tick'] += 1
        before = clone(terminal.engine.model)
        with patch('builtins.print') as output:
            with path.open(encoding='utf-8') as reader:
                terminal.publish()
                terminal.publish()
                self.assertEqual(json.load(reader), previous)
                self.assertEqual(read_json(path), previous)
                self.assertEqual(list(terminal.path.glob('*.tmp')), [])
            self.assertEqual(output.call_count, 1)
            terminal.publish()
            self.assertEqual(read_json(path)['tick'], before['tick'])
            self.assertEqual(read_json(path)['session'], 'console-test')
            with path.open(encoding='utf-8'):
                terminal.publish()
            self.assertEqual(output.call_count, 2)
        self.assertEqual(terminal.engine.model, before)
        self.assertIsNone(terminal.adapter)

    @unittest.skipUnless(os.name == 'nt', 'Windows file replacement semantics')
    def test_quit_with_busy_status_still_saves_memory_and_releases_store(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        terminal = self.terminal(folder)
        terminal.publish()
        previous = read_json(terminal.path / 'status.json')
        terminal.queue.put(('command', '/quit'))
        with (terminal.path / 'status.json').open(encoding='utf-8'), \
                patch.object(terminal, 'hook'), patch('threading.Thread.start'), \
                patch('builtins.print'):
            terminal.run()
        self.assertTrue(terminal.closed)
        self.assertTrue(terminal.abort.is_set())
        self.assertTrue(terminal.store.lock.closed)
        self.assertIsNotNone(read_json(terminal.store.path / 'memory.json'))
        self.assertEqual(read_json(terminal.path / 'status.json'), previous)
        self.assertEqual(list(terminal.path.glob('*.tmp')), [])

    def test_status_does_not_hide_other_write_errors(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        terminal = self.terminal(folder)
        for error in (PermissionError('cannot create temporary file'),
                      OSError('disk full'), ValueError('invalid JSON value')):
            with self.subTest(error=type(error).__name__), \
                    patch('kolos_states.cli.atomic_json', side_effect=error):
                with self.assertRaises(type(error)) as raised:
                    terminal.publish()
                self.assertIs(raised.exception, error)

    def test_standalone_reports_are_utf8_even_with_western_windows_pipe(self):
        for module, args in [('kolos_states.cli', ['--acceptance']),
                             ('kolos_states.capabilities', [])]:
            with self.subTest(module=module):
                env = os.environ.copy()
                env['PYTHONIOENCODING'] = 'cp1252:strict'
                result = subprocess.run([sys.executable, '-m', module, *args],
                                        cwd=ROOT, env=env, capture_output=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8'))
                report = json.loads(result.stdout.decode('utf-8'))
                cases = report if isinstance(report, list) else report['cases']
                self.assertEqual(len(cases), 10)
                self.assertTrue(all(case['passed'] for case in cases))
                self.assertIn('Конкуренция', result.stdout.decode('utf-8'))

    @unittest.skipUnless(os.name == 'nt', 'Windows native import and stdin lock')
    def test_first_record_command_responds_while_stdin_pipe_stays_open(self):
        for module in ('pyautogui', 'pynput'):
            if importlib.util.find_spec(module) is None:
                self.skipTest('Desktop dependency not installed: ' + module)
        folder = self.enterContext(tempfile.TemporaryDirectory())
        # Keep real native imports and the CLI reader, but observe a model and
        # disable all global input hooks and motor sends in this child process.
        script = '''
from types import SimpleNamespace
from kolos_states.cli import Terminal, main
from kolos_states.desktop import WindowsMotor
from kolos_states.simulator import default_world, observe
original_init = Terminal.__init__
def init(self, *args, **kwargs):
    original_init(self, *args, **kwargs)
    self.observer.accessibility = SimpleNamespace(ensure_available=lambda: None)
    self.observer.observe = lambda **kwargs: observe(default_world())
Terminal.__init__ = init
def listener(self, module):
    return SimpleNamespace(start=lambda: None, stop=lambda: None)
Terminal._keyboard_listener = listener
Terminal._mouse_listener = listener
def forbidden_input(self, action):
    raise AssertionError('This test must never send desktop input')
WindowsMotor.send = forbidden_input
raise SystemExit(main())
'''
        env = os.environ.copy()
        env.update(PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8')
        proc = subprocess.Popen([sys.executable, '-c', script, '--ipc', folder,
                                 '--session', 'record-pipe-test', '--memory', str(Path(folder) / 'memory')],
                                cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                creationflags=subprocess.CREATE_NO_WINDOW)
        lines = queue.Queue(); output = []
        def read():
            for line in proc.stdout:
                lines.put(line.rstrip())
            lines.put(None)
        reader = threading.Thread(target=read, daemon=True); reader.start()
        def send(command):
            proc.stdin.write(command + '\n'); proc.stdin.flush()
        def expect(marker):
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    line = lines.get(timeout=max(.01, deadline - time.monotonic()))
                except queue.Empty:
                    break
                if line is None:
                    break
                output.append(line)
                if marker in line:
                    return line
            self.fail('CLI did not respond with ' + marker + ':\n' + '\n'.join(output))
        try:
            expect('Движок готов.')
            send('o3'); expect('Для обучения действиям нажмите 3')
            atomic_json(Path(folder) / 'permission.json',
                        dict(session='record-pipe-test', live=True, stamp=time.time()))
            send('3')
            expect('Через 2 с начинается запись')
            expect('Запись включена.')
            send('/status'); expect('"permission"')
            status = read_json(Path(folder) / 'status.json')
            self.assertTrue(status['recording'])
            self.assertIsNone(status['pending'])
            send('/reset'); send('/status'); expect('"permission"')
            self.assertFalse(read_json(Path(folder) / 'status.json')['recording'])
            send('/quit'); proc.wait(timeout=5)
            self.assertEqual(proc.returncode, 0, '\n'.join(output))
            self.assertEqual(read_json(Path(folder) / 'memory' / 'memory.json')['lessons'], [])
        finally:
            if proc.poll() is None:
                proc.kill(); proc.wait(timeout=5)
            reader.join(timeout=2)
            proc.stdin.close(); proc.stdout.close()


if __name__ == '__main__':
    unittest.main()
