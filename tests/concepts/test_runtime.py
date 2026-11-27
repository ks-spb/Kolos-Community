"""Transport, hover changes, persistence failures and retired launcher contracts."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from test_object_concepts import World, lesson, waiting, learned, run
ROOT=Path(__file__).resolve().parents[2]
from kolos_states.core import StateEngine
from kolos_states.protocol import clone, persistent_graph, mark_clicked
from kolos_states.desktop import DesktopAdapter, Indeterminate
from kolos_states import object_concepts as oc, concept_graph as cg
from kolos_states.concept_console import scheduled
from kolos_states.neuron_trace import NeuronTraceWriter
from kolos_states.neuron_projection import project_neurons
from kolos_states.ipc import atomic_json, read_json
from kolos_states.targeting import click_followup

class RuntimeTests(unittest.TestCase):
    def prepare_request(self,kind='check'):
        e,w,a,q=learned()
        for _ in range(100):
            if e.model['pending']:
                p=e.model['pending']
                if p['action']['kind']==kind:return e,w,a,p
                e.accept_receipt(a.execute(p,allow_unexpected=True))
            else:e.observe(w.observe());e.tick()
        self.fail('No requested motor step')
    def test_hover_removed_while_answering_still_learns_same_instance(self):
        e,w,a=waiting();q=e.model['objectQuestion'];w.identifier='glaz.63'
        oc.answer(e,q['id'],'yes',w.observe());self.assertEqual(run(e,w,a),'complete')
        self.assertEqual(sum(n['kind']=='object_view' for n in e.model['memory']['nodes']),2)
    def test_hover_change_rebinds_actual_id_before_single_click(self):
        e,w,a,p=self.prepare_request('click');self.assertEqual(p['action']['object'],'glaz.50');w.identifier='glaz.63'
        receipt=a.execute(p,allow_unexpected=True);self.assertTrue(receipt['ok'])
        self.assertEqual(receipt['action']['object'],'glaz.63');self.assertEqual(w.clicks,1)
        e.accept_receipt(receipt);self.assertEqual(run(e,w,a),'complete')
        self.assertTrue(any(x.get('kind')=='object-rebind-before-input' for x in e.model['audit']))
    def test_rebinding_does_not_accept_unknown_view(self):
        e,w,a,p=self.prepare_request('click');w.identifier='glaz.87'
        self.assertFalse(a.execute(p)['ok']);self.assertEqual(w.clicks,0)
    def test_rebinding_does_not_follow_moved_instance(self):
        e,w,a,p=self.prepare_request('click');w.identifier='glaz.63';w.box=[190,190,210,210]
        self.assertFalse(a.execute(p)['ok']);self.assertEqual(w.clicks,0)
    def test_foreign_window_instance_cannot_excitate_motor(self):
        e,w,a,p=self.prepare_request('click');obs=w.observe();obs['object_instances'][0]['in_foreground']=False
        self.assertFalse(cg.evaluate(e.model['memory'],p['step'],obs,.7)['winner'])
        self.assertTrue(oc.motor_reason(e.model,obs,p))
    def test_foreign_instance_cannot_start_question(self):
        e,w,a=waiting();q=e.model['objectQuestion'];obs=w.observe();obs['object_instances'][0]['in_foreground']=False
        with self.assertRaises(ValueError):oc.answer(e,q['id'],'yes',obs)
    def test_save_failure_rolls_back_learning_and_never_runs(self):
        e,w,a=waiting();before=clone(e.model);q=e.model['objectQuestion']
        terminal=SimpleNamespace(engine=e,observer=w,store=Mock(),object_answer=dict(id=q['id'],choice='yes'),
                                 _arm=lambda:None,abort=threading.Event(),running=False,pause=threading.Event())
        terminal.pause.set();terminal.store.save.side_effect=OSError('disk failure')
        with self.assertRaises(OSError):scheduled(terminal)
        self.assertEqual(e.model,before);self.assertFalse(terminal.running);self.assertEqual(w.clicks,0)
    def test_stop_cancels_queued_yes_without_arming(self):
        terminal=SimpleNamespace(abort=threading.Event(),_arm=Mock());terminal.abort.set()
        with self.assertRaises(ValueError):scheduled(terminal)
        terminal._arm.assert_not_called()
    def test_missing_effect_never_repeats_click(self):
        e,w,a,p=self.prepare_request('click')
        def no_effect(action):w.clicks+=1
        w.send=no_effect
        with self.assertRaises(Indeterminate):a.execute(p,allow_unexpected=True)
        self.assertTrue(e.model['heldGoal']);self.assertIsNotNone(e.model['pending'])
        with self.assertRaises(Indeterminate):a.execute(p,allow_unexpected=True)
        self.assertEqual(w.clicks,1)
    def test_wrong_effect_does_not_complete_goal(self):
        e,w,a,p=self.prepare_request('click')
        def wrong_effect(action):w.clicks+=1;w.identifier='glaz.7'
        w.send=wrong_effect;r=a.execute(p,allow_unexpected=True);event=e.accept_receipt(r)
        self.assertEqual(event['kind'],'prediction-error');self.assertTrue(e.model['heldGoal'])
        self.assertTrue(any(x.get('kind')=='object-outcome' and not x['matched'] for x in e.model['audit']))
    def test_serialized_neuron_trace_has_real_concept_currents(self):
        e,w,a,p=self.prepare_request();before=clone(e.model)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d);atomic_json(path/'neuron-watch.json',dict(session='s',enabled=True))
            writer=NeuronTraceWriter(path,'s');self.assertTrue(writer.capture(e))
            row=read_json(next((path/'neuron-frames').glob('*.json')));self.assertIn('objectCurrents',row['model'])
            projected=project_neurons(row['model'],row['event']);concept=p['object_concept']['concept']
            view=next(n for n in projected['nodes'] if n['id']==concept)
            self.assertGreater(view['S'],.7);self.assertGreater(view['A'],.7)
            self.assertTrue(any(x['kind']=='object_member' and x['flow'] for x in projected['edges']))
        self.assertEqual(e.model,before)
    def test_click_enter_continues_actual_concept_without_second_click(self):
        record=lesson();before=record['receipts'][-1]['before'];closed=record['receipts'][-1]['after']
        clicked=mark_clicked(before,'glaz.63',before['icons'][0])
        record['receipts'][-1].update(after=clicked,effect_observed=False)
        record['receipts'].append(dict(id='enter',action=dict(kind='enter',object='glaz.63'),before=clicked,after=closed,ok=True))
        e=StateEngine();e.learn(record);w=World('glaz.50');w.model_provider=lambda:e.model
        def send(action):
            w.sent.append(clone(action))
            if action['kind']=='move':w.cursor=dict(x=action['x'],y=action['y'])
            if action['kind']=='click':w.clicks+=1
            if action['kind']=='enter':w.open=False
        w.send=send;a=DesktopAdapter(w,w,allow=lambda:True,timeout=.1);e.start('O1',w.observe())
        for _ in range(150):
            if e.model.get('objectQuestion'):
                oc.answer(e,e.model['objectQuestion']['id'],'yes',w.observe())
            if e.model['status']=='complete':break
            if e.model['pending']:
                p=e.model['pending'];step=e.node(p['step']);follow=click_followup(e.model['memory'],step)
                if follow and p.get('object_concept'):follow['object']=p['action']['object']
                e.accept_receipt(a.execute(p,allow_unexpected=True,followup=follow,assume_click=step.get('dispatch_only',False)))
            else:e.observe(a.observe());e.tick()
        self.assertEqual(e.model['status'],'complete',e.model['message']);self.assertEqual(w.clicks,1)
        self.assertEqual([x['kind'] for x in w.sent if x['kind'] in ('click','enter')],['click','enter'])

class StatesOnlyTests(unittest.TestCase):
    def controller(self):
        spec=importlib.util.spec_from_file_location('concept_controller',ROOT/'Glaz/kolos_subprocess.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        return m,m.KolosSubprocessController(ROOT,Mock())
    def test_default_launcher_is_states(self):
        m,c=self.controller()
        with patch.object(m.subprocess,'Popen') as p,patch.object(m.threading.Thread,'start'):
            p.return_value.poll.return_value=None
            self.assertEqual(c.start(ipc_dir='session',session='s'),'')
            self.assertEqual(p.call_args.args[0][:3],[sys.executable,'-m','kolos_states.cli'])
    def test_legacy_cannot_spawn(self):
        m,c=self.controller()
        with patch.object(m.subprocess,'Popen') as p:
            self.assertIn('Legacy',c.start(engine='legacy'));p.assert_not_called()
    def test_direct_legacy_entry_stops_before_dependencies(self):
        p=subprocess.run([sys.executable,str(ROOT/'main.py')],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        self.assertNotEqual(p.returncode,0);self.assertIn('Legacy',p.stdout+p.stderr);self.assertNotIn('Traceback',p.stderr)
    def test_interfaces_have_no_legacy_selector(self):
        for name in ('states_app.py','studio_app.py'):
            text=(ROOT/'Glaz'/name).read_text(encoding='utf-8');self.assertNotIn("values=['Legacy",text)
        self.assertNotIn("os.environ.get('KOLOS_ENGINE'",(ROOT/'Glaz/states_app.py').read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main()
