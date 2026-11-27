import json
from pathlib import Path
import shutil
import subprocess
import unittest
from kolos_states.core import StateEngine
from kolos_states.protocol import clone
from kolos_states.simulator import observe
from kolos_states.capabilities import prepare
from kolos_states.imagery_experiment import run
from kolos_states import imagery
ROOT=Path(__file__).resolve().parents[2]

class ImageryTests(unittest.TestCase):
    def test_experiment_eleven(self):
        r,_,_=run();self.assertTrue(r['passed'],r)
    def test_python_js_all_channels_match_on_every_tick(self):
        if not shutil.which('node'):self.skipTest('Node for development parity only')
        data=json.loads(subprocess.check_output(['node',str(ROOT/'tests/desktop/imagery_reference.mjs')],cwd=ROOT,text=True,encoding='utf-8'))
        e=StateEngine()
        for op in data['setup']:
            if op['kind'] in ('teach','expose'):e.learn(op['record'],exposure=op['kind']=='expose')
            elif op['kind']=='world':e.observe(observe(op['world']))
        e.imagine(data['goals'],e.model['observed'])
        for row in data['trace']:
            if 'command' in row:e.control_image(row['command']);continue
            e.observe(row['before']);event=e.tick();expected=row['event']
            if expected['kind']=='ack':e.accept_receipt(expected['receipt'])
            elif expected['kind']!='effect':self.assertEqual(event['kind'],expected['kind'])
            self.assertEqual(e.model['imagery'],row['image'],('channels',e.model['tick']))
            self.assertEqual(e.model['status'],row['status']);self.assertEqual(e.model['heldGoal'],row['heldGoal'])
    def test_strong_image_cannot_be_its_own_evidence(self):
        e,w,req=prepare(9);e.imagine(req['goals'],observe(w));before=clone(w)
        for _ in range(80):e.tick()
        self.assertEqual(w,before);self.assertEqual(e.model['imagery']['ready'],1);self.assertEqual(e.model['imagery']['match'],0)
        self.assertTrue(e.model['heldGoal']);self.assertIsNone(e.model['pending'])
    def test_invalid_image_transactional(self):
        e,w,_=prepare(9);before=clone(e.model)
        with self.assertRaises(ValueError):e.imagine([dict(kind='field',focus='FIELD',value='8')],observe(w))
        self.assertEqual(e.model,before)
    def test_disappearance_not_overridden_by_sensory_trace(self):
        e,w,req=prepare(9);e.imagine(req['goals'],observe(w));g=e.model['intent']['goals'][0]
        e.model['observed'].update(focus='FIELD',output='2345')
        for _ in range(6):imagery.update(e.model,g)
        self.assertTrue(imagery.satisfied(e.model))
        e.model['observed']['output']='234';imagery.update(e.model,g)
        self.assertFalse(imagery.satisfied(e.model));self.assertTrue(any(n['S'] and not n['present'] for n in e.model['imagery']['nodes']))
    def test_mental_receipt_never_confirms_goal(self):
        e,w,req=prepare(9);e.imagine(req['goals'],observe(w));before=clone(e.model)
        with self.assertRaises(ValueError):e.accept_receipt(dict(source='imagined',id='fake'))
        self.assertEqual(e.model,before)
    def test_reset_discards_imagery(self):
        e,w,req=prepare(9);e.imagine(req['goals'],observe(w));e.reset()
        self.assertFalse(e.model.get('imagery'));self.assertFalse(e.model['heldGoal'])
    def test_restart_discards_imagined_world(self):
        import tempfile
        from kolos_states.storage import Store
        e,w,req=prepare(9);e.imagine(req['goals'],observe(w));e.tick()
        with tempfile.TemporaryDirectory() as path:
            store=Store(Path(path));store.save(e);other=store.load();store.close()
        self.assertFalse(other.model.get('imagery'));self.assertFalse(other.model['heldGoal']);self.assertIsNone(other.model['pending'])
if __name__=='__main__':unittest.main()
