import json
from pathlib import Path
import shutil
import subprocess
import unittest
from kolos_states.core import StateEngine
from kolos_states.protocol import clone
from kolos_states.simulator import observe
from kolos_states.capabilities import run, prepare
ROOT = Path(__file__).resolve().parents[2]


class GoalTests(unittest.TestCase):
    def test_all_ten_capabilities_are_verified_without_learning_control_targets(self):
        for n in range(1, 11):
            with self.subTest(case=n):
                r, e, w = run(n)
                self.assertTrue(r['passed'], r)
                self.assertGreater(e.model['config']['decay'], 0)
                self.assertLess(e.model['config']['decay'], 1)
                self.assertFalse(any('2345' in l['query'] or '3521' in l['query'] for l in e.model['lessons']))

    def test_python_js_goal_dynamics_agree_at_every_tick(self):
        if not shutil.which('node'):
            self.skipTest('Node required for development parity, not desktop runtime')
        data = json.loads(subprocess.check_output(['node', str(ROOT/'tests/desktop/goals_reference.mjs')], cwd=ROOT, text=True, encoding='utf-8'))
        for case in data:
            with self.subTest(case=case['number']):
                e = StateEngine()
                for op in case['setup']:
                    if op['kind'] in ('teach', 'expose'): e.learn(op['record'], exposure=op['kind'] == 'expose')
                    elif op['kind'] == 'weight': e.set_weight(op['id'], op['value'])
                    elif op['kind'] == 'config': e.configure(**op['values'])
                    elif op['kind'] == 'world': e.observe(observe(op['world']))
                e.start_goals(case['operation']['goals'], e.model['observed'], case['operation'].get('config'))
                for row in case['trace']:
                    e.observe(row['before']); ev = e.tick(); expected = row['event']
                    if expected['kind'] == 'effect': pass
                    elif expected['kind'] in ('ack', 'prediction-error'):
                        # The independent native simulator is checked above. Here
                        # identical observations probe equations and decision timing.
                        receipt = expected.get('receipt')
                        if not receipt:
                            request = expected['error']['request']
                            receipt = next(r['event']['receipt'] for r in case['trace'] if r['event']['kind'] == 'effect' and r['event']['receipt']['id'] == request)
                        ev = e.accept_receipt(receipt)
                        self.assertEqual(ev['kind'], expected['kind'])
                    else:
                        self.assertEqual(ev['kind'], expected['kind'], (case['number'], row['state']['tick']))
                        self.assertEqual(ev.get('winner'), expected.get('winner'))
                        self.assertEqual(len(ev.get('candidates', [])), len(expected.get('candidates', [])))
                        for a, b in zip(ev.get('candidates', []), expected.get('candidates', [])):
                            self.assertEqual(a['id'], b['id']); self.assertAlmostEqual(a['a'], b['a'], places=8)
                            if 'upper' in a:
                                self.assertAlmostEqual(a['upper'], b['upper'], places=8)
                    m = e.model; s = row['state']
                    for k in ('tick', 'status', 'phase', 'entry', 'heldGoal', 'goalActivation', 'activation', 'occ', 'recoveries'):
                        self.assertEqual(m[k], s[k], (case['number'], s['tick'], k))
                    for k in ('error', 'goals'):
                        self.assertEqual(m['intent'][k], s[k], (case['number'], s['tick'], k))

    def test_result_goal_does_not_invoke_known_command_parser(self):
        e, w, req = prepare(9)
        e.inspect = lambda *_: (_ for _ in ()).throw(AssertionError('Do not look up a command'))
        e.start_goals(req['goals'], observe(w))
        self.assertEqual(e.model['phase'], 'intent')
        self.assertTrue(e.model['heldGoal'])

    def test_mixed_training_order_and_weights_survive_native_reload(self):
        import tempfile
        from kolos_states.storage import Store
        e, _, _ = prepare(5)
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            try:
                store.save(e); restored = store.load()
                self.assertEqual(restored.model['memory'], e.model['memory'])
                self.assertIsNone(restored.model['pending'])
            finally: store.close()

    def test_unknown_goal_validation_is_transactional(self):
        e, w, req = prepare(9); old = clone(e.model)
        with self.assertRaises(ValueError): e.start_goals([dict(kind='field', focus='FIELD', value='89')], observe(w))
        self.assertEqual(e.model, old)

if __name__ == '__main__': unittest.main()
