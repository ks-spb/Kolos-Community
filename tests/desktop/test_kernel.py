import json
import shutil
import subprocess
import unittest
from pathlib import Path
from kolos_states.core import StateEngine
from kolos_states.protocol import clone, persistent_graph, guard
from kolos_states.simulator import prepare_case, run_case, apply, observe, default_world, demonstrate, icon_actions
ROOT=Path(__file__).resolve().parents[2]

class KernelTests(unittest.TestCase):
    def waiting_for_icon(self):
        """Suspend a learned check after one frame loses a stationary target."""
        w=default_world();e=StateEngine()
        e.learn(demonstrate('o1',w,icon_actions(w,'A')))
        e.start('o1',observe(w))
        for _ in range(10):
            e.tick()
            if e.model['pending']:
                e.accept_receipt(apply(w,e.model['pending']));break
        w['surfaces']['desk']['icons'][0]['hidden']=True
        e.observe(observe(w))
        self.assertEqual(e.tick()['kind'],'need-state')
        return e,w

    def test_reappearing_target_resumes_even_when_other_desktop_icons_changed(self):
        e,w=self.waiting_for_icon();memory=persistent_graph(e.model['memory'])
        w['surfaces']['desk']['icons'][0]['hidden']=False
        w['surfaces']['desk']['icons'].append(dict(id='NEW',x=600,y=450))
        e.observe(observe(w))
        ev=e.tick()
        self.assertEqual(ev['kind'],'dispatch')
        self.assertEqual(e.model['pending']['action'],dict(kind='check',object='A'))
        self.assertIsNone(e.model['plan'])
        self.assertEqual(persistent_graph(e.model['memory']),memory)
        self.assertEqual([r['action']['kind'] for r in w['effects']],['move'])

    def test_reappearing_target_at_new_position_uses_fresh_coordinates(self):
        e,w=self.waiting_for_icon()
        w['surfaces']['desk']['icons'][0].update(hidden=False,x=300,y=400)
        e.observe(observe(w));e.tick()
        self.assertEqual(e.model['pending']['action'],dict(kind='move',x=300,y=400))
        self.assertTrue(e.model['pending']['relocate'])

    def test_missing_target_keeps_waiting_and_pending_effect_is_never_repeated(self):
        e,w=self.waiting_for_icon()
        for _ in range(3):
            self.assertEqual(e.tick()['kind'],'spread')
            self.assertIsNone(e.model['pending'])
        w['surfaces']['desk']['icons'][0]['hidden']=False
        e.observe(observe(w));e.tick()
        pending=clone(e.model['pending'])
        self.assertIsNotNone(pending)
        for _ in range(3):
            self.assertEqual(e.tick()['kind'],'waiting')
            self.assertEqual(e.model['pending'],pending)
        self.assertEqual(len(w['effects']),1)

    def test_suspended_enter_requires_selection_and_typing_requires_its_original_focus(self):
        for case,kind in ((1,'enter'),(4,'drive')):
            with self.subTest(action=kind):
                e,w,query=prepare_case(case);e.start(query,observe(w))
                for _ in range(100):
                    step=e.node(e.model['entry'])
                    if e.model['phase']=='execute' and step['action']['kind']==kind:break
                    e.tick()
                    if e.model['pending']:e.accept_receipt(apply(w,e.model['pending']))
                self.assertEqual(e.node(e.model['entry'])['action']['kind'],kind)
                field='selected' if kind=='enter' else 'focus'
                expected=w[field];w[field]='OTHER'
                w['surfaces'][w['surface']]['icons'].append(dict(id='NEW',x=600,y=450))
                e.observe(observe(w));self.assertEqual(e.tick()['kind'],'need-state')
                if kind=='enter':
                    # The learned selection click can now actively restore Enter's prerequisite.
                    for _ in range(100):
                        if e.model['status']=='complete':break
                        e.observe(observe(w));e.tick()
                        if e.model['pending']:
                            p=e.model['pending']
                            self.assertFalse(guard(observe(w),p['action']))
                            e.accept_receipt(apply(w,p))
                    self.assertEqual(e.model['status'],'complete')
                    continue
                for _ in range(3):
                    self.assertEqual(e.tick()['kind'],'spread')
                    self.assertIsNone(e.model['pending'])
                w[field]=expected;e.observe(observe(w));e.tick()
                self.assertIsNone(e.model['plan'])
                for _ in range(3):
                    if e.model['pending']:break
                    e.tick()
                self.assertEqual(e.model['pending']['action']['kind'],'enter' if kind=='enter' else 'key')

    def test_four_mandatory_scenarios(self):
        for n in range(1,5):
            with self.subTest(case=n):
                result,e,w=run_case(n);self.assertTrue(result['passed'],result)
                self.assertGreater(e.model['config']['decay'],0);self.assertLess(e.model['config']['decay'],1)

    def test_two_typing_lessons_execute_a_new_order_without_a_third_lesson(self):
        from kolos_states.simulator import demonstrate, icon_actions
        for separator in ('',' '):
            with self.subTest(separator=separator):
                engine=StateEngine();engine.configure(plasticity=0)
                world=default_world()
                for digits in ('12345','6789'):
                    value=separator.join(digits)
                    engine.learn(demonstrate('Впиши '+value,world,
                        icon_actions(world,'CALC')+[dict(kind='key',value=char) for char in value]))
                learned=persistent_graph(engine.model['memory'])
                target=separator.join('4532')
                engine.start('Впиши '+target,observe(world))
                for _ in range(400):
                    if engine.model['status']=='complete':break
                    engine.tick()
                    if engine.model['pending']:engine.accept_receipt(apply(world,engine.model['pending']))
                self.assertEqual(engine.model['status'],'complete',engine.model['message'])
                self.assertEqual(world['output'],target)
                self.assertEqual(len(engine.model['lessons']),2)
                self.assertEqual(persistent_graph(engine.model['memory']),learned)
    def test_js_numerical_parity(self):
        if not shutil.which('node'):self.skipTest('Node only required for JS/Python parity, not live runtime')
        data=json.loads(subprocess.check_output(['node',str(ROOT/'tests/desktop/js_reference.mjs')],cwd=ROOT,text=True,encoding='utf-8'))
        for case in data:
            with self.subTest(case=case['n']):
                e=StateEngine()
                for record in case['exposures']:e.learn(record,exposure=True)
                for record in case['lessons']:e.learn(record)
                e.start(case['query'],case['observation'])
                for row in case['trace']:
                    expected=row['event'];event=e.tick()
                    if expected['kind']=='effect': pass
                    elif expected['kind']=='ack':e.accept_receipt(expected['receipt'])
                    else:
                        self.assertEqual(event['kind'],expected['kind'],(case['n'],row['state']['tick'],event,expected))
                        self.assertEqual(len(event.get('candidates',[])),len(expected.get('candidates',[])))
                        for left,right in zip(event.get('candidates',[]),expected.get('candidates',[])):
                            self.assertEqual(left['id'],right['id']);self.assertAlmostEqual(left['a'],right['a'],places=8)
                    m=e.model;s=row['state']
                    for k in ('tick','phase','entry','context','heldGoal','recoveries'):
                        self.assertEqual(m[k],s[k],(case['n'],s['tick'],k))
                    self.assertEqual(m['goalActivation'],s['active'])
                    self.assertEqual(m['activation'],s['activation'])
                    self.assertEqual([dict(id=q['id'],held=q['held'],a=q['a']) for q in m['occ']],s['occ'])
    def test_pending_keeps_source_and_duplicate_ack_is_ignored(self):
        e,w,q=prepare_case(4);e.start(q,observe(w))
        for _ in range(300):
            e.tick()
            p=e.model['pending']
            if not p:continue
            r=apply(w,p)
            if p['action']['kind']=='key':break
            e.accept_receipt(r)
        source=p['source'];self.assertTrue(next(x for x in e.model['occ'] if x['id']==source)['held'])
        self.assertEqual(w['output'],'2')
        for _ in range(3):e.tick()
        self.assertEqual(w['output'],'2')
        e.accept_receipt(r);after=clone(e.model['occ']);e.accept_receipt(r);self.assertEqual(after,e.model['occ'])
    def test_goal_needs_learned_backward_weight(self):
        e,w,q=prepare_case(3);t=next(n for n in e.model['memory']['nodes'] if n['kind']=='transition' and n['label']=='CLICK X')
        edge=next(x for x in e.model['memory']['edges'] if x['kind']=='backward' and x['to']==t['id']);e.set_weight(edge['id'],0)
        e.start(q,observe(w))
        for _ in range(200):
            ev=e.tick()
            if e.model['pending']:e.accept_receipt(apply(w,e.model['pending']))
        self.assertEqual(e.model['status'],'blocked');self.assertTrue(e.model['heldGoal'])
    def test_preview_never_has_effect(self):
        e,w,q=prepare_case(1);e.start(q,observe(w));before=clone(e.model);p=e.preview();self.assertEqual(e.model,before)
        e.commit(p)
        with self.assertRaises(ValueError):e.commit(p)
    def test_wrong_key_observation_rejected(self):
        e,w,q=prepare_case(4);e.start(q,observe(w))
        for _ in range(300):
            e.tick()
            if e.model['pending']:
                p=e.model['pending'];r=apply(w,p)
                if p['action']['kind']=='key':break
                e.accept_receipt(r)
        r['after']['output']='WRONG'
        with self.assertRaises(ValueError):e.accept_receipt(r)
        self.assertIsNotNone(e.model['pending'])

if __name__=='__main__':unittest.main()
