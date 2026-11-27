import contextlib
import io
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from kolos_states.core import StateEngine
from kolos_states.episode_desktop import EpisodeAdapter, EpisodeRecorder
from kolos_states.episode_experiment import FormWorld, demonstration, memory_signature
from kolos_states.episode_console import command, tick_once
from kolos_states.desktop import Indeterminate
from kolos_states.protocol import clone
from kolos_states.neuron_projection import project_neurons
from kolos_states.storage import Store


class Observer:
    def __init__(self, world=None):
        self.world = world or FormWorld()
        self.after_send = None
        self.latest = {}

    def observe(self):
        self.latest = self.world.observe()
        return self.latest

    def send(self, a):
        self.world.execute(dict(id='physical', action=a))
        if self.after_send:
            self.after_send()


def request(observer, kind='read', name='Source 1', value=None, rid='one'):
    before = observer.observe()
    obj = next(o for o in before['objects'] if o['descriptor']['name'] == name)
    a = dict(kind=kind, object=obj['id'], descriptor=obj['descriptor'], effects=[])
    if kind == 'write':
        a['value'] = value
    return dict(id=rid, action=a, before=before)


class EpisodeBoundaryTests(unittest.TestCase):
    def test_permission_pause_and_emergency_stop_prevent_dispatch(self):
        for reason in ('permission', 'pause', 'stop'):
            with self.subTest(reason=reason):
                observer = Observer()
                stop = threading.Event()
                if reason == 'stop':
                    stop.set()
                adapter = EpisodeAdapter(observer, allow=lambda: reason != 'permission',
                                         paused=lambda: reason == 'pause', stop=stop)
                with self.assertRaises((PermissionError, InterruptedError)):
                    adapter.execute(request(observer))
                self.assertFalse(observer.world.actions)
                self.assertFalse(adapter.sent)

    def test_source_change_after_selection_prevents_dispatch(self):
        observer = Observer()
        adapter = EpisodeAdapter(observer, allow=lambda: True)
        req = request(observer, 'write', 'Target 1', 'new')
        observer.world.data['Source 1'] = 'changed after choosing action'
        with self.assertRaises(ValueError):
            adapter.execute(req)
        self.assertFalse(observer.world.actions)

    def test_duplicate_request_is_idempotent_and_cannot_change_action(self):
        observer = Observer()
        adapter = EpisodeAdapter(observer, allow=lambda: True)
        req = request(observer, 'write', 'Target 1', 'new')
        first = adapter.execute(req)
        self.assertEqual(adapter.execute(req), first)
        self.assertEqual(len(observer.world.actions), 1)
        altered = clone(req)
        altered['action']['value'] = 'other'
        with self.assertRaises(ValueError):
            adapter.execute(altered)
        self.assertEqual(len(observer.world.actions), 1)

    def test_stop_after_effect_does_not_turn_it_into_success_or_retry(self):
        observer = Observer()
        stop = threading.Event()
        observer.after_send = stop.set
        adapter = EpisodeAdapter(observer, allow=lambda: True, stop=stop)
        req = request(observer, 'write', 'Target 1', 'new')
        with self.assertRaises(InterruptedError):
            adapter.execute(req)
        self.assertEqual(observer.world.data['Target 1'], 'new')
        self.assertFalse(adapter.receipts)
        stop.clear()
        with self.assertRaises(Indeterminate):
            adapter.execute(req)
        self.assertEqual(len(observer.world.actions), 1)

    def test_native_adapter_requires_two_fresh_observations(self):
        observer = Observer()
        adapter = EpisodeAdapter(observer, allow=lambda: True)
        r = adapter.execute(request(observer))
        self.assertEqual(r['verified_by'], 'two-fresh-uia-observations')
        self.assertGreaterEqual(r['after']['version'] - r['before']['version'], 2)
        self.assertEqual(len(observer.world.actions), 1)

    def test_same_frame_cannot_be_reused_for_different_observation(self):
        e, w = StateEngine(), FormWorld()
        e.learn_episode(demonstration())
        obs = w.observe()
        e.start_episode('Copy the observed fields and save', obs)
        changed = clone(obs)
        changed['objects'][0]['value'] = 'different data in same frame'
        with self.assertRaises(ValueError):
            e.observe(changed)

    def test_late_receipt_after_timeout_cannot_resume_execution(self):
        e, w = StateEngine(), FormWorld()
        e.learn_episode(demonstration())
        e.start_episode('Copy the observed fields and save', w.observe())
        e.tick()
        r = w.execute(e.model['pending'])
        for _ in range(50):
            e.tick()
        with self.assertRaises(ValueError):
            e.accept_receipt(r)
        self.assertEqual(e.model['status'], 'timeout')
        self.assertTrue(e.model['heldGoal'])
        self.assertFalse(e.model['episode']['working'])

    def test_failed_demonstration_is_not_continued_or_saved(self):
        observer = Observer()
        stop = threading.Event()
        adapter = EpisodeAdapter(observer, allow=lambda: True, stop=stop)
        recorder = EpisodeRecorder(adapter, 'demo')
        stop.set()
        with self.assertRaises(InterruptedError):
            recorder.capture('read', observer.world.ids['Source 1'])
        stop.clear()
        with self.assertRaises(ValueError):
            recorder.capture('read', observer.world.ids['Source 1'])
        with self.assertRaises(ValueError):
            recorder.finish()

    def test_terminal_teaches_executes_and_persists_same_engine_with_two_values(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            t = SimpleNamespace(engine=StateEngine(), running=False, recording=False, schedule=None,
                                hooks_ready=True, allowed=lambda: True, abort=threading.Event(),
                                pause=threading.Event(), store=Store(Path(directory)), receipt=None,
                                args=SimpleNamespace(glaz_pid=0))
            t.episode_observer = Observer(FormWorld(('sample A', 'sample B')))
            t.episode_adapter = EpisodeAdapter(t.episode_observer, allow=t.allowed, stop=t.abort, paused=t.pause.is_set)
            original = t.engine
            try:
                command(t, '/episode-begin working task')
                for i in range(2):
                    command(t, '/episode-read ' + t.episode_observer.world.ids[f'Source {i+1}'])
                    import json
                    command(t, '/episode-write ' + json.dumps(dict(object=t.episode_observer.world.ids[f'Target {i+1}'], source=f'v{i}')))
                command(t, '/episode-activate ' + t.episode_observer.world.ids['Save'])
                command(t, '/episode-save')
                t.episode_observer = Observer(FormWorld(('fresh A', 'fresh B'), layout=1))
                t.episode_adapter = EpisodeAdapter(t.episode_observer, allow=t.allowed, stop=t.abort, paused=t.pause.is_set)
                command(t, '/episode-run working task')
                for _ in range(60):
                    tick_once(t)
                    if not t.running:
                        break
                self.assertIs(t.engine, original)
                self.assertEqual(t.engine.model['status'], 'complete')
                self.assertEqual(t.episode_observer.world.data['Saved 2'], 'fresh B')
                self.assertEqual(memory_signature(t.store.load()), memory_signature(t.engine))
            finally:
                t.store.close()

    def test_read_only_neuron_projection_handles_roles_values_and_flows(self):
        e, w = StateEngine(), FormWorld()
        e.learn_episode(demonstration())
        e.start_episode('Copy the observed fields and save', w.observe())
        e.tick()
        event = e.accept_receipt(w.execute(e.model['pending']))
        frozen = clone(e.model)
        view = project_neurons(e.model, event)
        self.assertTrue(any(n.get('working') for n in view['nodes']))
        self.assertTrue(any(n.get('runtime_id') for n in view['nodes']))
        self.assertEqual(e.model, frozen)


if __name__ == '__main__':
    unittest.main()
