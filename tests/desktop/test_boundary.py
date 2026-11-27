import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from kolos_states.desktop import DesktopAdapter,DesktopObserver,Indeterminate
from kolos_states.ipc import atomic_json,read_json,ScanClient
from kolos_states.protocol import clone,observation_key,persistent_graph
from kolos_states.simulator import default_world,observe,apply,prepare_case,run_case
from kolos_states.storage import Store

class FakeObserver:
    def __init__(self,w):self.w=w
    def observe(self,**kw):
        o=observe(self.w);o['readable']=bool(o['focus']);o['own_focus']=False;return o

class FakeMotor:
    def __init__(self,w,change=True):self.w=w;self.count=0;self.change=change
    def send(self,a):
        self.count+=1
        if self.change:apply(self.w,dict(id='physical-'+str(self.count),action=a))

class BoundaryTests(unittest.TestCase):
    def test_changed_but_wrong_effect_is_reported_only_to_opted_in_goal_network(self):
        w=default_world();w['cursor']={'x':200,'y':190};motor=FakeMotor(w)
        expected_world=default_world();expected_world['surface']='window'
        a=DesktopAdapter(FakeObserver(w),motor,allow=lambda:True)
        r=a.execute(dict(id='x',action=dict(kind='click',object='A')),expected=observation_key(observe(expected_world)),allow_unexpected=True)
        self.assertTrue(r['ok']);self.assertFalse(r['prediction_match']);self.assertEqual(w['selected'],'A');self.assertEqual(motor.count,1)
    def test_legacy_does_not_accept_changed_but_unexpected_effect(self):
        w=default_world();w['cursor']={'x':200,'y':190};motor=FakeMotor(w)
        expected_world=default_world();expected_world['surface']='window'
        a=DesktopAdapter(FakeObserver(w),motor,allow=lambda:True,timeout=.002)
        with self.assertRaises(Indeterminate):a.execute(dict(id='x',action=dict(kind='click',object='A')),expected=observation_key(observe(expected_world)))
        self.assertEqual(motor.count,1)
    def test_no_permission_means_no_input(self):
        w=default_world();motor=FakeMotor(w);adapter=DesktopAdapter(FakeObserver(w),motor)
        with self.assertRaises(PermissionError):adapter.execute(dict(id='x',action=dict(kind='move',x=200,y=190)))
        self.assertEqual(motor.count,0)
    def test_key_requires_observed_delta_not_send_return(self):
        w=default_world();w.update(surface='calculator',focus='FIELD');motor=FakeMotor(w,False)
        a=DesktopAdapter(FakeObserver(w),motor,allow=lambda:True,timeout=.001)
        req=dict(id='key-1',action=dict(kind='key',value='1'))
        with self.assertRaises(Indeterminate):a.execute(req)
        with self.assertRaises(Indeterminate):a.execute(req)
        self.assertEqual(motor.count,1);self.assertEqual(w['output'],'')
    def test_confirmed_key_is_applied_once_and_receipt_is_cached(self):
        w=default_world();w.update(surface='calculator',focus='FIELD');motor=FakeMotor(w)
        a=DesktopAdapter(FakeObserver(w),motor,allow=lambda:True)
        req=dict(id='key-1',action=dict(kind='key',value='1'))
        r=a.execute(req);self.assertTrue(r['ok']);self.assertEqual(r['after']['output'],'1');self.assertEqual(a.execute(req),r);self.assertEqual(motor.count,1)
    def test_focus_changed_after_key_selection_never_types_into_other_field(self):
        w=default_world();w.update(surface='calculator',focus='OTHER');motor=FakeMotor(w)
        a=DesktopAdapter(FakeObserver(w),motor,allow=lambda:True)
        r=a.execute(dict(id='x',action=dict(kind='key',value='1')),target_focus='FIELD')
        self.assertFalse(r['ok']);self.assertEqual(motor.count,0);self.assertEqual(w['output'],'')
    def test_missing_object_never_clicks(self):
        w=default_world();w['surface']='window';motor=FakeMotor(w)
        r=DesktopAdapter(FakeObserver(w),motor,allow=lambda:True).execute(dict(id='x',action=dict(kind='click',object='A')))
        self.assertFalse(r['ok']);self.assertEqual(motor.count,0)
    def test_stop_between_dispatch_and_effect(self):
        w=default_world();motor=FakeMotor(w);stop=threading.Event();stop.set()
        with self.assertRaises(InterruptedError):DesktopAdapter(FakeObserver(w),motor,stop=stop,allow=lambda:True).execute(dict(id='x',action=dict(kind='move',x=1,y=1)))
        self.assertEqual(motor.count,0)
    def test_pause_received_during_scan_prevents_new_effect(self):
        w=default_world();motor=FakeMotor(w)
        a=DesktopAdapter(FakeObserver(w),motor,allow=lambda:True,paused=lambda:True)
        with self.assertRaises(InterruptedError):a.execute(dict(id='x',action=dict(kind='move',x=100,y=100)))
        self.assertEqual(motor.count,0);self.assertNotIn('x',a.sent)
    def test_readonly_source_filters_ambiguous_ids_and_field_glyphs(self):
        class Scan:
            def request(self,**kwargs):return dict(icons=[dict(id='glyph',x=10,y=10,bbox=[1,1,20,20]),dict(id='button',x=80,y=80,bbox=[70,70,90,90]),dict(id='ambiguous',x=50,y=50,bbox=[40,40,60,60],ambiguous=True)],cursor=dict(x=80,y=80),frame=2,session='s',captured_at=time.time(),monitor={})
        class UIA:
            def read(self):return dict(field_bbox=[0,0,30,30],selected_bbox=[70,70,90,90],focus='field',output='123',readable=True,own=False,reason='')
        o=DesktopObserver(Scan(),UIA()).observe();self.assertEqual([i['id'] for i in o['icons']],['button']);self.assertEqual(o['selected'],'button')
    def test_atomic_ipc_malformed_and_cross_session(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);atomic_json(p/'observation.json',dict(session='old',request='x',captured_at=time.time(),complete=True))
            with self.assertRaises(TimeoutError):ScanClient(p,'new',timeout=.03).request()
            (p/'bad.json').write_text('{');self.assertIsNone(read_json(p/'bad.json'))
    @unittest.skipUnless(os.name == 'nt', 'Windows file replacement semantics')
    def test_atomic_json_waits_for_open_reader(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'status.json'
            atomic_json(path, {'tick': 1})
            errors=[]
            def write():
                try:atomic_json(path, {'tick': 2})
                except Exception as exc:errors.append(exc)
            with path.open(encoding='utf-8') as reader:
                worker=threading.Thread(target=write)
                worker.start()
                time.sleep(.03)
                self.assertTrue(worker.is_alive())
                self.assertEqual(json.load(reader), {'tick': 1})
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(read_json(path), {'tick': 2})
    @unittest.skipUnless(os.name == 'nt', 'Windows file replacement semantics')
    def test_atomic_json_keeps_old_file_when_reader_stays_open(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'status.json'
            atomic_json(path, {'tick': 1})
            with path.open(encoding='utf-8'):
                with self.assertRaises(PermissionError):atomic_json(path, {'tick': 2})
            self.assertEqual(read_json(path), {'tick': 1})
            self.assertEqual(list(path.parent.glob('*.tmp')), [])
    def test_scan_must_be_captured_after_its_request(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            def stale_server():
                end=time.monotonic()+.5
                while time.monotonic()<end:
                    req=read_json(p/'request.json')
                    if req:
                        atomic_json(p/'observation.json',dict(session='s',request=req['id'],captured_at=req['issued']-.1,complete=True))
                        return
                    time.sleep(.002)
            t=threading.Thread(target=stale_server);t.start()
            with self.assertRaises(TimeoutError):ScanClient(p,'s',timeout=.08).request()
            t.join()
    def test_native_memory_does_not_resume_pending(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d));_,e,w=run_case(4);before=persistent_graph(e.model['memory']);store.save(e)
            try:
                loaded=store.load();self.assertEqual(before,loaded.model['memory']);self.assertIsNone(loaded.model['pending']);self.assertEqual(loaded.model['status'],'idle')
            finally:store.close()
    def test_store_refuses_second_process_lease(self):
        with tempfile.TemporaryDirectory() as d:
            first=Store(Path(d))
            with self.assertRaises(RuntimeError):Store(Path(d))
            first.close()
    def test_no_legacy_database_paths(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d));e,_,_=prepare_case(4);store.save(e);store.close()
            self.assertEqual({x.name for x in Path(d).iterdir()},{'memory.json','last-attempt.json','process.lock'})

if __name__=='__main__':unittest.main()
