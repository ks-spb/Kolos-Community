import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from kolos_states.shared_experiment import SharedSession, persistent, FIXTURE
from kolos_states.storage import Store
from kolos_states.backward import backward_wave

ROOT=Path(__file__).resolve().parents[2]

class SharedTests(unittest.TestCase):
    def test_twelve_in_one_engine_and_both_orders(self):
        s=SharedSession();original=s.engine
        for order in (range(1,13),range(12,0,-1)):
            rows=s.run_all(order)
            self.assertTrue(all(r['pass'] for r in rows),rows)
            self.assertEqual({r['memoryAfter'] for r in rows},{s.hash})
            self.assertIs(s.engine,original)
        self.assertEqual(len(s.engine.model['lessons']),18)

    def test_old_mean_fails_five_capabilities_in_shared_memory(self):
        rows=SharedSession(competition=0).run_all()
        self.assertEqual([r['number'] for r in rows if not r['pass']],[5,7,9,11,12])
        self.assertTrue(all(r['checks']['memoryUnchanged'] for r in rows))

    def test_memory_rebuild_preserves_shared_knowledge_and_weights(self):
        s=SharedSession();s.run(12)
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d));store.save(s.engine);restored=store.load();store.close()
        self.assertEqual(persistent(restored),s.signature)
        other=SharedSession(engine=restored)
        self.assertTrue(all(r['pass'] for r in other.run_all([12,3,10,1,8,5,11,2,6,9,7,4])))

    def test_backward_state_competition_has_no_silent_degree_penalty(self):
        memory={'edges':[{'id':'e','kind':'backward','from':'good','to':'s','weight':.9}]}
        nodes=[dict(id='s',kind='state')];old={'good':1};cfg=dict(decay=.5,discount=.9,stateCompetition=1)
        first=backward_wave(memory,nodes,old,cfg,[])
        for i in range(50):
            memory['edges'].append(dict(id=str(i),kind='backward',to='s',weight=1,**{'from':'zero'+str(i)}))
        self.assertEqual(backward_wave(memory,nodes,old,cfg,[]),first)

    def test_shared_fixture_is_identical_across_languages(self):
        js=(ROOT/'web/shared/fixture.mjs').read_text(encoding='utf-8').split('export const SHARED_FIXTURE = ',1)[1].strip()[:-1]
        self.assertEqual(json.loads(js),FIXTURE)

    def test_glaz_can_serve_all_shared_modules_but_no_control_endpoint(self):
        from urllib.request import urlopen, Request
        from urllib.error import HTTPError
        from kolos_states.neuron_server import NeuronServer, STATIC_FILES
        with tempfile.TemporaryDirectory() as d:
            server=NeuronServer(ROOT,Path(d),'shared-proof')
            try:
                base=f'http://127.0.0.1:{server.server.server_port}'
                for path in STATIC_FILES:
                    with urlopen(base+'/'+path) as response:
                        self.assertEqual(response.status,200,path)
                        self.assertTrue(response.read(),path)
                with self.assertRaises(HTTPError) as denied:
                    urlopen(Request(base+'/api/shared-run',method='POST',data=b'1'))
                self.assertEqual(denied.exception.code,405)
            finally:
                server.close()

    def test_python_and_javascript_shared_execution_match_every_step(self):
        if not shutil.which('node'):self.skipTest('Node needed for parity only')
        raw=json.loads(subprocess.check_output(['node',str(ROOT/'tests/desktop/shared_reference.mjs')],cwd=ROOT,text=True,encoding='utf-8'))
        s=SharedSession()
        for case in raw:
            s.begin(case['number'])
            for i,row in enumerate(case['frames']):
                if i:s.step()
                m=s.engine.model
                for key in ('tick','status','phase','entry','context','heldGoal','goalActivation','activation','occ','refractory'):
                    self.assertEqual(m.get(key),row.get(key),(case['number'],i,key))
                self.assertEqual(m.get('imagery'),row['image'],(case['number'],i,'I/S'))
                self.assertEqual(m.get('language'),row['language'],(case['number'],i,'language'))
                self.assertEqual((m.get('intent') or {}).get('error'),row['error'])
                self.assertEqual({k:m['observed'][k] for k in ('features','focus','output','version')},row['observed'])
            self.assertTrue(s.active['result']['pass'])

if __name__=='__main__':unittest.main()
