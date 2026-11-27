"""63/50 integration regression. No real mouse, keyboard or private memory."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from kolos_states.core import StateEngine
from kolos_states.protocol import clone, persistent_graph, SCHEMA
from kolos_states.desktop import DesktopAdapter
from kolos_states.storage import Store
from kolos_states.memory import validate_graph
from kolos_states import object_concepts as oc, concept_graph as cg

REGISTRY=cg.registry({(1,2,3):[63],(1,2,4):[50],(1,3,4):[87],(4,5):[7]})

class World:
    def __init__(self,identifier='glaz.63'):
        self.identifier=identifier;self.open=True;self.cursor=dict(x=100,y=100)
        self.frame=0;self.stamp=0.;self.clicks=0;self.sent=[];self.extra=[]
        self.foreground=100;self.session='session';self.context='explorer';self.own=False
        self.registry=clone(REGISTRY);self.box=[90,90,110,110]
    def observe(self,*,after=0.,**kwargs):
        self.frame+=1;self.stamp=max(time.time(),self.stamp+.000001,after+.000001)
        icons=([dict(id=self.identifier,x=(self.box[0]+self.box[2])/2,y=(self.box[1]+self.box[3])/2,bbox=clone(self.box))]
               if self.open else [dict(id='glaz.7',x=300,y=300,bbox=[290,290,310,310])])+clone(self.extra)
        return dict(features=sorted(['visible:'+i['id'] for i in icons]+['window:'+('Explorer' if self.open else 'Desktop')]),
            icons=clone(icons),object_instances=clone(icons),focus='',selected='',output='',cursor=clone(self.cursor),
            session=self.session,version=self.frame,captured_at=self.stamp,observed_at=self.stamp,
            foreground=self.foreground,window_context=self.context if self.open else 'desktop',
            context_valid=True,own_focus=self.own,readable=False,object_registry=clone(self.registry),
            recognition_complete=True,monitor=dict(left=0,top=0,width=1000,height=800),object_issues={})
    def send(self,a):
        self.sent.append(clone(a))
        if a['kind']=='move':self.cursor=dict(x=a['x'],y=a['y'])
        elif a['kind']=='click':self.clicks+=1;self.open=False

def lesson():
    w=World();w.cursor=dict(x=10,y=10);before=w.observe();w.cursor=dict(x=100,y=100);moved=w.observe();w.open=False;closed=w.observe()
    steps=[(dict(kind='move',x=100,y=100),before,moved),(dict(kind='check',object='glaz.63'),moved,moved),(dict(kind='click',object='glaz.63'),moved,closed)]
    return dict(query='O1',receipts=[dict(id=str(i),action=a,before=b,after=c,ok=True) for i,(a,b,c) in enumerate(steps)])

def setup(identifier='glaz.50'):
    e=StateEngine();e.learn(lesson());w=World(identifier);w.model_provider=lambda:e.model
    a=DesktopAdapter(w,w,allow=lambda:True,timeout=.1);e.start('O1',w.observe());return e,w,a

def run(e,w,a,limit=100):
    for _ in range(limit):
        if e.model['status'] not in ('running','waiting'):return e.model['status']
        if e.model['pending']:e.accept_receipt(a.execute(e.model['pending'],allow_unexpected=True))
        else:e.observe(w.observe());e.tick()
    raise AssertionError('Loop: '+e.model['status'])

def waiting(identifier='glaz.50'):
    e,w,a=setup(identifier);assert run(e,w,a)=='needs-help',e.model['message']
    assert e.model.get('objectQuestion'),e.model['message'];return e,w,a

def learned():
    e,w,a=waiting();q=clone(e.model['objectQuestion']);oc.answer(e,q['id'],'yes',w.observe());return e,w,a,q

class CommonObjectTests(unittest.TestCase):
    def test_question_before_click_without_memory_change(self):
        e,w,a=setup();before=persistent_graph(e.model['memory']);run(e,w,a)
        self.assertEqual(w.clicks,0);self.assertTrue(e.model['heldGoal']);self.assertIsNone(e.model['pending'])
        self.assertEqual(before,persistent_graph(e.model['memory']));q=e.model['objectQuestion']
        self.assertEqual((q['expected'],q['actual']),('glaz.63','glaz.50'))
    def test_yes_learns_shared_ensemble_not_alias_then_executes(self):
        e,w,a=waiting();old=clone([n['action'] for n in e.model['memory']['nodes'] if n['kind']=='step'])
        oc.answer(e,e.model['objectQuestion']['id'],'yes',w.observe())
        self.assertEqual(w.clicks,0);self.assertTrue(e.model['heldGoal'])
        self.assertEqual(old,[n['action'] for n in e.model['memory']['nodes'] if n['kind']=='step'])
        self.assertEqual({n['object'] for n in e.model['memory']['nodes'] if n['kind']=='object_view'},{'glaz.50','glaz.63'})
        self.assertEqual([i['id'] for i in e.model['observed']['icons']],['glaz.50'])
        self.assertEqual(run(e,w,a),'complete');self.assertEqual(w.clicks,1)
        self.assertTrue(any(s.get('object')=='glaz.50' for s in w.sent if s['kind']=='click'))
    def test_both_views_reuse_same_ensemble(self):
        e,w,a,_=learned();self.assertEqual(run(e,w,a),'complete');count=len(e.model['memory']['nodes'])
        for identifier in ('glaz.63','glaz.50'):
            e.reset();w.open=True;w.identifier=identifier;e.start('O1',w.observe())
            self.assertEqual(run(e,w,a),'complete');self.assertNotIn('objectQuestion',e.model)
        self.assertEqual(sum(n['kind']=='object_concept' for n in e.model['memory']['nodes']),1)
        self.assertEqual(len(e.model['memory']['nodes']),count)
    def test_third_view_joins_same_concept(self):
        e,w,a,_=learned();run(e,w,a);e.reset();w.open=True;w.identifier='glaz.87';e.start('O1',w.observe());run(e,w,a)
        oc.answer(e,e.model['objectQuestion']['id'],'yes',w.observe());self.assertEqual(run(e,w,a),'complete')
        self.assertEqual(sum(n['kind']=='object_concept' for n in e.model['memory']['nodes']),1)
        self.assertEqual(sum(n['kind']=='object_view' for n in e.model['memory']['nodes']),3)
    def test_no_and_unsure_do_not_learn_or_repeat_question(self):
        for choice in ('no','unsure'):
            e,w,a=waiting();before=persistent_graph(e.model['memory']);oc.answer(e,e.model['objectQuestion']['id'],choice)
            self.assertEqual(before,persistent_graph(e.model['memory']));self.assertEqual(w.clicks,0)
            e.model['status']='running';run(e,w,a);self.assertNotIn('objectQuestion',e.model)
    def test_replayed_answer_rejected(self):
        e,w,a,q=learned()
        with self.assertRaises(ValueError):oc.answer(e,q['id'],'yes',w.observe())
    def test_expired_answer_rejected(self):
        e,w,a=waiting();e.model['objectQuestion']['issued']-=121
        with self.assertRaises(ValueError):oc.answer(e,e.model['objectQuestion']['id'],'yes',w.observe())
    def test_reset_invalidates_answer(self):
        e,w,a=waiting();q=e.model['objectQuestion'];e.reset()
        with self.assertRaises(ValueError):oc.answer(e,q['id'],'yes',w.observe())
    def test_wrong_question_rejected(self):
        e,w,a=waiting();before=persistent_graph(e.model['memory'])
        with self.assertRaises(ValueError):oc.answer(e,'wrong','yes',w.observe())
        self.assertEqual(before,persistent_graph(e.model['memory']))
    def test_changed_context_rejected(self):
        for attr,value in [('foreground',200),('context','other'),('session','other'),('own',True)]:
            e,w,a=waiting();setattr(w,attr,value)
            with self.assertRaises(ValueError):oc.answer(e,e.model['objectQuestion']['id'],'yes',w.observe())
            self.assertEqual(w.clicks,0)
    def test_changed_bbox_or_prototype_rejected(self):
        for kind in ('box','registry'):
            e,w,a=waiting()
            if kind=='box':w.box=[190,190,210,210]
            else:w.registry['glaz.50']='f'*64
            with self.assertRaises(ValueError):oc.answer(e,e.model['objectQuestion']['id'],'yes',w.observe())
    def test_answer_needs_new_frame(self):
        e,w,a=waiting()
        with self.assertRaises(ValueError):oc.answer(e,e.model['objectQuestion']['id'],'yes',clone(e.model['observed']))
    def test_repeated_frame_does_not_trigger_question(self):
        e,w,a=setup();step=next(n for n in e.model['memory']['nodes'] if n.get('action',{}).get('kind')=='check')
        e.model.update(phase='execute',entry=step['id']);e.observe(w.observe())
        for _ in range(8):oc.before_step(e.model,step,{})
        self.assertNotIn('objectQuestion',e.model)
    def test_duplicate_actual_does_not_trigger_question(self):
        e,w,a=setup();w.extra=[dict(id='glaz.50',x=300,y=100,bbox=[290,90,310,110])]
        # Raw instances can duplicate, while the protocol's old icons are unique.
        obs=w.observe();obs['icons']=obs['icons'][:1];step=next(n for n in e.model['memory']['nodes'] if n.get('action',{}).get('kind')=='check');e.observe(obs)
        for _ in range(8):oc.before_step(e.model,step,{})
        self.assertNotIn('objectQuestion',e.model);self.assertEqual(w.clicks,0)
    def test_expected_elsewhere_never_teaches_alias(self):
        e,w,a=setup();w.extra=[dict(id='glaz.63',x=300,y=100,bbox=[290,90,310,110])];run(e,w,a)
        self.assertNotIn('objectQuestion',e.model);self.assertFalse(any(n['kind']=='object_concept' for n in e.model['memory']['nodes']))
    def test_two_accepted_views_stop(self):
        e,w,a,_=learned();w.extra=[dict(id='glaz.63',x=300,y=100,bbox=[290,90,310,110])]
        self.assertEqual(run(e,w,a),'needs-help');self.assertEqual(w.clicks,0)
    def test_zero_required_synapses_stop(self):
        for kind in ('object_member','object_context','object_ground'):
            e,w,a,_=learned()
            for edge in e.model['memory']['edges']:
                if edge['kind']==kind:edge['weight']=0
            run(e,w,a);self.assertEqual(w.clicks,0)
    def test_other_context_requires_another_confirmation(self):
        e,w,a,_=learned();run(e,w,a);e.reset();w.open=True;w.context='other-folder';e.start('O1',w.observe());previous=w.clicks
        run(e,w,a);self.assertEqual(w.clicks,previous);self.assertIn('objectQuestion',e.model)
    def test_observed_result_strengthens_used_member(self):
        e,w,a,_=learned();edge=next(x for x in e.model['memory']['edges'] if x['kind']=='object_member' and cg.node(e.model['memory'],x['from'])['object']=='glaz.50')
        old=edge['weight'];run(e,w,a);self.assertGreater(edge['weight'],old)
        self.assertTrue(any(x.get('kind')=='object-outcome' and x['matched'] for x in e.model['audit']))
    def test_no_unscoped_paths_created(self):
        e,w,a,_=learned();run(e,w,a)
        self.assertFalse(any(n['kind']=='step' and n['action'].get('object')=='glaz.50' for n in e.model['memory']['nodes']))

class MotorAndStorageTests(unittest.TestCase):
    def request(self):
        e,w,a,_=learned()
        for _ in range(40):
            e.observe(w.observe());e.tick()
            if e.model['pending']:return e,w,a,clone(e.model['pending'])
        self.fail('No request')
    def test_motor_rechecks_window(self):
        e,w,a,p=self.request();w.foreground=200;self.assertFalse(a.execute(p)['ok']);self.assertEqual(w.clicks,0)
    def test_motor_rechecks_new_competing_view(self):
        e,w,a,p=self.request();w.extra=[dict(id='glaz.63',x=300,y=100,bbox=[290,90,310,110])]
        self.assertFalse(a.execute(p)['ok']);self.assertEqual(w.clicks,0)
    def test_motor_rechecks_disabled_synapse(self):
        e,w,a,p=self.request();edge=next(x for x in e.model['memory']['edges'] if x['id']==p['object_concept']['member']);edge['weight']=0
        self.assertFalse(a.execute(p)['ok'])
    def test_permission_still_required(self):
        e,w,a,p=self.request();a.allow=lambda:False
        with self.assertRaises(PermissionError):a.execute(p)
    def test_pause_prevents_input(self):
        e,w,a,p=self.request();a.paused=lambda:True
        with self.assertRaises(InterruptedError):a.execute(p)
    def test_outcome_no_effect_does_not_learn(self):
        e,w,a,p=self.request();before=persistent_graph(e.model['memory'])
        self.assertEqual(oc.outcome(e.model,p,dict(id='x',ok=True,effect_observed=False),True),[])
        self.assertEqual(before,persistent_graph(e.model['memory']))
    def test_wrong_outcome_weakens_used_view(self):
        e,w,a,p=self.request();changes=oc.outcome(e.model,p,dict(id='x',ok=True,effect_observed=True),False)
        self.assertLess(changes[0]['after'],.7)
    def test_roundtrip_keeps_memory_not_transients(self):
        e,w,a,_=learned();original=persistent_graph(e.model['memory'])
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d));store.save(e);loaded=store.load();store.close()
            self.assertEqual(original,persistent_graph(loaded.model['memory']))
            for key in ('objectQuestion','objectBinding','objectCurrents'):self.assertNotIn(key,loaded.model)
            w.model_provider=lambda:loaded.model;loaded.start('O1',w.observe());self.assertEqual(run(loaded,w,a),'complete')
    def test_v2_v3_upgrade_preserves_backup(self):
        for version in ('2','3'):
            e,w,a=setup()
            with tempfile.TemporaryDirectory() as d:
                store=Store(Path(d));store.save(e);p=Path(d)/'memory.json';raw=json.loads(p.read_text(encoding='utf-8'));raw['schema']='kolos-desktop-states/'+version;p.write_text(json.dumps(raw),encoding='utf-8')
                store.load();self.assertEqual(json.loads(p.read_text(encoding='utf-8'))['schema'],SCHEMA)
                self.assertEqual(len(list(Path(d).glob('memory-v'+version+'-*.json'))),1);store.close()
    def test_broken_graph_not_overwritten(self):
        e,w,a,_=learned()
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d));store.save(e);p=Path(d)/'memory.json';raw=json.loads(p.read_text(encoding='utf-8'));raw['memory']['edges']=[x for x in raw['memory']['edges'] if x['kind']!='object_context'];p.write_text(json.dumps(raw),encoding='utf-8');before=p.read_bytes()
            with self.assertRaises(ValueError):store.load()
            self.assertEqual(before,p.read_bytes());store.close()
    def test_original_view_required_in_graph(self):
        e,w,a,_=learned();memory=clone(e.model['memory']);memory['edges']=[x for x in memory['edges'] if not(x['kind']=='object_member' and cg.node(memory,x['from'])['object']=='glaz.63')]
        with self.assertRaises(ValueError):validate_graph(memory,e.model['commands'])
    def test_registry_tracks_prototype_not_number(self):
        self.assertNotEqual(cg.registry({(1,2):[50]})['glaz.50'],cg.registry({(1,3):[50]})['glaz.50'])

if __name__=='__main__':unittest.main()
