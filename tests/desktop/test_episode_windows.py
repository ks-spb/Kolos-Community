"""Opt-in real Windows evidence. Only disposable subprocess windows are changed."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager

from kolos_states.core import StateEngine
from kolos_states.episode_desktop import UIAObserver, EpisodeAdapter, EpisodeRecorder
from kolos_states.desktop import Indeterminate
from kolos_states.episode_experiment import memory_signature
from kolos_states.storage import Store

ROOT = Path(__file__).resolve().parents[2]
ENABLED = sys.platform == 'win32' and os.environ.get('KOLOS_EPISODE_WINDOWS_SMOKE') == '1'


@contextmanager
def pad(source, *, source2=None, layout=0, fail_save=False):
    command = [sys.executable, '-m', 'kolos_states.episode_pad', '--source', source, '--layout', str(layout)]
    if source2 is not None:
        command += ['--source2', source2]
    if fail_save:
        command += ['--fail-save']
    process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding='utf-8')
    out = queue.Queue()
    threading.Thread(target=lambda: out.put(process.stdout.readline()), daemon=True).start()
    try:
        line = out.get(timeout=12)
        if not line.strip():
            raise RuntimeError(process.stderr.read())
        hwnd = int(line)
        time.sleep(.2)
        observer = UIAObserver(hwnd)
        observer.observe()
        yield observer
    finally:
        if process.poll() is None:
            # We terminate only the disposable process created by this fixture.
            process.terminate()
        process.wait(timeout=8)
        process.stdout.close()
        process.stderr.close()


def by_name(obs, name):
    return next(o for o in obs['objects'] if o['descriptor']['name'] == name)


def teach_native(engine, observer, count=1):
    adapter = EpisodeAdapter(observer, allow=lambda: True, timeout=3)
    recorder = EpisodeRecorder(adapter, 'Native demonstrated episode')
    for i in range(count):
        recorder.capture('read', by_name(observer.observe(), f'Source {i+1}')['id'])
        recorder.capture('write', by_name(observer.observe(), f'Target {i+1}')['id'], source=f'v{i}')
    recorder.capture('activate', by_name(observer.observe(), 'Save')['id'])
    engine.learn_episode(recorder.finish())


def execute_native(engine, observer, timeout=3):
    before = observer.observe()
    adapter = EpisodeAdapter(observer, allow=lambda: True, timeout=timeout)
    frozen = memory_signature(engine)
    engine.start_episode('Native demonstrated episode', before)
    for _ in range(60):
        event = engine.tick()
        if event['kind'] == 'dispatch':
            engine.accept_receipt(adapter.execute(engine.model['pending']))
        if engine.model['status'] not in ('running', 'waiting'):
            break
    after = observer.observe()
    assert engine.model['status'] == 'complete', engine.model['message']
    assert memory_signature(engine) == frozen
    return before, after, adapter


@unittest.skipUnless(ENABLED, 'Opt-in disposable native Windows episode smoke')
class EpisodeWindowsTests(unittest.TestCase):
    def test_new_value_new_layout_restart_and_1_to_12_in_same_engine(self):
        from kolos_states.shared_experiment import SharedSession
        session = SharedSession()
        self.assertTrue(all(r['pass'] for r in session.run_all()))
        engine = session.engine
        engine.reset()
        with pad('Native training 1700') as observer:
            training = observer.observe()
            teach_native(engine, observer)
        evidence = []
        for index, value in enumerate(['new 6143', '  новая строка Ω  ', '']):
            engine.reset()
            with pad(value, layout=index % 2) as observer:
                before, after, adapter = execute_native(engine, observer)
                self.assertEqual(by_name(after, 'Source 1')['value'], value)
                self.assertEqual(by_name(after, 'Target 1')['value'], value)
                self.assertEqual(by_name(after, 'Saved 1')['value'], value)
                self.assertEqual(by_name(after, 'Unrelated')['value'], 'do not touch')
                self.assertEqual(by_name(training, 'Source 1')['descriptor'], by_name(before, 'Source 1')['descriptor'])
                evidence.append(dict(value=value, layout=index % 2, passed=True, operations=len(adapter.sent),
                                     sourceRuntimeId=by_name(before, 'Source 1')['id'],
                                     sourceBounds=by_name(before, 'Source 1')['bbox'],
                                     saved=by_name(after, 'Saved 1')['value'],
                                     verifiedBy=sorted({r['verified_by'] for r in adapter.receipts.values()})))
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            store.save(engine)
            loaded = store.load()
            store.close()
        with pad('after memory reload', layout=1) as observer:
            _, after, _ = execute_native(loaded, observer)
            self.assertEqual(by_name(after, 'Saved 1')['value'], 'after memory reload')
        loaded.reset()
        self.assertTrue(all(r['pass'] for r in SharedSession(engine=loaded).run_all(range(12, 0, -1))))
        out = ROOT / 'tests/desktop-output/episode-windows.json'
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(dict(passed=True, nativeRuns=evidence, reloadPassed=True,
                                      regression1to12BeforeAfter=True, scope='Real Win32 controls observed through UI Automation'),
                                  ensure_ascii=False, indent=2), encoding='utf-8')

    def test_two_sources_and_input_blocks_in_native_window(self):
        engine = StateEngine()
        with pad('sample A', source2='sample B') as observer:
            teach_native(engine, observer, 2)
        with pad('fresh one', source2='fresh two', layout=1) as observer:
            _, after, adapter = execute_native(engine, observer)
            for i, value in [(1, 'fresh one'), (2, 'fresh two')]:
                for role in ('Source', 'Target', 'Saved'):
                    self.assertEqual(by_name(after, f'{role} {i}')['value'], value)
            self.assertEqual(len(adapter.sent), 5)

    def test_native_save_without_effect_never_passes_or_repeats(self):
        engine = StateEngine()
        with pad('sample') as observer:
            teach_native(engine, observer)
        with pad('fresh value', layout=1, fail_save=True) as observer:
            adapter = EpisodeAdapter(observer, allow=lambda: True, timeout=.5)
            engine.start_episode('Native demonstrated episode', observer.observe())
            uncertain = None
            for _ in range(20):
                event = engine.tick()
                if event['kind'] == 'dispatch':
                    request = engine.model['pending']
                    try:
                        engine.accept_receipt(adapter.execute(request))
                    except Indeterminate:
                        uncertain = request
                        break
            self.assertIsNotNone(uncertain)
            self.assertEqual(uncertain['action']['kind'], 'activate')
            self.assertTrue(engine.model['heldGoal'])
            self.assertNotEqual(engine.model['status'], 'complete')
            count = len(adapter.sent)
            with self.assertRaises(Indeterminate):
                adapter.execute(uncertain)
            self.assertEqual(len(adapter.sent), count)
            self.assertEqual(by_name(observer.observe(), 'Source 1')['value'], 'fresh value')


if __name__ == '__main__':
    unittest.main()
