"""Native recording -> learned graph -> desktop adapter, with independent screen I/O."""
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from kolos_states.cli import Terminal
from kolos_states.core import StateEngine, STOP
from kolos_states.desktop import DesktopAdapter, DesktopObserver, Indeterminate, click_trace
from kolos_states.protocol import clone, guard, persistent_graph, observation_key
from kolos_states.recorder import Recorder
from kolos_states.simulator import default_world, demonstrate, icon_actions, observe, apply, prepare_case
from kolos_states.storage import Store
from kolos_states.visual import SAMPLE_BYTES
from kolos_states.dynamics import transition_candidates, sensory_tick, orienting_choice

ROOT = Path(__file__).resolve().parents[2]


class Screen:
    """Screen physics only. The learner receives no window flag or transition rule."""
    def __init__(self):
        self.open = False; self.stamp = 100.0; self.cursor = dict(x=200,y=190)
        self.delay = 0; self.sent = []; self.extra = False

    def observe(self, **kwargs):
        self.stamp = max(self.stamp + 1, kwargs.get('after', 0) + .01)
        if self.delay:
            self.delay -= 1
            if not self.delay:self.open = False
        target = dict(id='glaz.202',x=920,y=75,bbox=[910,65,930,85]) if self.open else dict(id='glaz.101',x=200,y=190,bbox=[190,180,210,200])
        icons = [target]
        if self.extra:icons.append(dict(id='noise',x=600,y=400,bbox=[590,390,610,410]))
        return dict(icons=icons,features=['visible:'+i['id'] for i in icons],focus='',selected='',output='',
                    cursor=clone(self.cursor),captured_at=self.stamp,version=int(self.stamp),readable=False,own_focus=False,
                    visual_sample=bytes([240 if self.open else 20]*SAMPLE_BYTES).hex())

    def send(self, action):
        self.sent.append(clone(action))
        if action['kind']=='move':self.cursor=dict(x=action['x'],y=action['y'])
        elif action['kind']=='enter':self.open=True
        elif action['kind']=='click' and self.open:self.delay=2

    def teach_click(self, recorder, object):
        box=[910,65,930,85] if object==202 else [190,180,210,200]
        point=(920,75) if object==202 else (200,190)
        target=SimpleNamespace(refined_id=object,timestamp=self.stamp+.1,bbox_ltrb=box)
        at=self.stamp+.5;self.cursor=dict(zip(('x','y'),point))
        self.send(dict(kind='click',object='glaz.'+str(object)))
        recorder.capture(dict(kind='click'),at,point,at-.1,target)


class HighlightedScreen(Screen):
    """Selection changes the icon's appearance; old visual ID also matches elsewhere."""
    def __init__(self):
        super().__init__();self.highlighted=False

    def observe(self, **kwargs) -> dict:
        result=super().observe(**kwargs)
        if not self.open and self.highlighted:
            result['icons'][0]['id']='glaz.43'
            result['features']=['visible:glaz.43','visible:glaz.101']
            result['object_issues']={'glaz.101':'Объект glaz.101 распознан в нескольких местах; нужный экземпляр не подтверждён'}
        return result

    def send(self, action: dict) -> None:
        if action['kind']=='click':self.highlighted=not self.open
        elif action['kind']=='enter':self.highlighted=False
        super().send(action)


class DuplicateScreen(Screen):
    """A repeated visual ID becomes eligible only after pointing at one instance."""
    def observe(self, **kwargs) -> dict:
        result=super().observe(**kwargs)
        if not self.open and not (190<=self.cursor['x']<=210 and 180<=self.cursor['y']<=200):
            result['icons']=[i for i in result['icons'] if i['id']!='glaz.101']
            result['object_issues']={'glaz.101':'Объект glaz.101 распознан в нескольких местах; нужный экземпляр не подтверждён'}
        return result


class NearestIconScreen(Screen):
    """Fresh duplicate detections; only screen physics observes the actual click."""
    def __init__(self, cursor: tuple[int, int], positions: list[tuple[int, int]]):
        super().__init__()
        self.cursor = dict(zip(('x', 'y'), cursor))
        self.positions = positions
        self.clicked: list[tuple[int, int]] = []

    def request(self, **kwargs) -> dict:
        result = super().observe(**kwargs)
        if not self.open:
            result['icons'] = [dict(id='glaz.101', x=x, y=y,
                                    bbox=[x-10, y-10, x+10, y+10], ambiguous=True)
                               for x, y in self.positions]
        result.update(frame=result['version'], session='nearest',
                      monitor=dict(left=0, top=0, width=1920, height=1080))
        return result

    def send(self, action: dict) -> None:
        if action['kind'] == 'click' and not self.open:
            self.clicked.append((self.cursor['x'], self.cursor['y']))
        super().send(action)


def desktop_lessons(screen=None):
    screen=screen or Screen();opened=Recorder(screen,'o1',settle_timeout=.02)
    screen.teach_click(opened,101)
    at=screen.stamp+.5;screen.send(dict(kind='enter',object='glaz.101'))
    opened.capture(dict(kind='enter'),at)
    opening=opened.finish()
    closed=Recorder(screen,'o2',settle_timeout=.02);screen.teach_click(closed,202)
    closing=closed.finish()
    return screen, opening, closing


class NativeRecoveryTests(unittest.TestCase):
    @staticmethod
    def _terminal(e: StateEngine, screen: Screen) -> Terminal:
        """Use the production tick/receipt path, with screen physics supplying fresh frames."""
        t=Terminal.__new__(Terminal);t.engine=e;t.observer=screen
        t.adapter=DesktopAdapter(screen,screen,allow=lambda:True,timeout=.05)
        t.receipt=None;t.store=Mock();t.running=True;t.pause=threading.Event();t.language_auto=False
        return t

    def _nearest_terminal(self, opening: dict, screen: NearestIconScreen) -> Terminal:
        """Connect the saved lesson to the real observer and motor receipt path."""
        observer = DesktopObserver(screen, SimpleNamespace(read=lambda: dict(
            focus='', output='', readable=False, own=False, reason='')))
        engine = StateEngine(); engine.learn(opening); engine.configure(plasticity=0)
        terminal = self._terminal(engine, screen)
        terminal.observer = observer
        terminal.adapter = DesktopAdapter(observer, screen, allow=lambda: True, timeout=.05)
        return terminal

    @staticmethod
    def _run_terminal(terminal: Terminal) -> None:
        """Drive the production loop without emitting test diagnostic ticks."""
        with patch('builtins.print'):
            for _ in range(250):
                if terminal.engine.model['status'] in STOP:
                    break
                terminal.tick_once()

    def test_existing_command_selects_nearest_copy_before_its_first_move(self):
        """Moved copies use the current cursor, including equal-distance ties."""
        _, opening, _ = desktop_lessons()
        positions = [(230, 190), (870, 190), (900, 500)]
        for cursor, expected in [((200, 190), (230, 190)), ((840, 190), (870, 190)),
                                 ((550, 190), (230, 190))]:
            for reverse in (False, True):
                with self.subTest(cursor=cursor, reverse=reverse):
                    screen = NearestIconScreen(cursor, positions[::-1] if reverse else positions)
                    terminal = self._nearest_terminal(opening, screen); engine = terminal.engine
                    memory = persistent_graph(engine.model['memory'])
                    engine.start('o1', terminal.observer.observe())
                    self._run_terminal(terminal)
                    self.assertEqual(engine.model['status'], 'complete', engine.model['message'])
                    self.assertEqual([(a['x'], a['y']) for a in screen.sent if a['kind']=='move'], [expected])
                    self.assertEqual(screen.clicked, [expected])
                    self.assertEqual([a['kind'] for a in screen.sent], ['move', 'click', 'enter'])
                    self.assertEqual(persistent_graph(engine.model['memory']), memory)

    def test_result_goal_uses_nearest_copy_for_the_learned_move(self):
        """Goal execution shares the same nearest target as an explicit command."""
        _, opening, _ = desktop_lessons()
        screen = NearestIconScreen((840, 190), [(230, 190), (870, 190), (900, 500)])
        terminal = self._nearest_terminal(opening, screen); engine = terminal.engine
        engine.start_goals([dict(kind='state', features=opening['receipts'][-1]['after']['features'])],
                           terminal.observer.observe())
        self._run_terminal(terminal)
        self.assertEqual(engine.model['status'], 'complete', engine.model['message'])
        self.assertEqual([(a['x'], a['y']) for a in screen.sent if a['kind']=='move'], [(870, 190)])
        self.assertEqual(screen.clicked, [(870, 190)])
        self.assertEqual([a['kind'] for a in screen.sent], ['move', 'click', 'enter'])

    def test_missing_copies_never_allow_a_click(self):
        """The nearest-target policy cannot manufacture an absent icon."""
        _, opening, _ = desktop_lessons()
        screen = NearestIconScreen((200, 190), [])
        terminal = self._nearest_terminal(opening, screen); engine = terminal.engine
        engine.start('o1', terminal.observer.observe())
        self._run_terminal(terminal)
        self.assertEqual(engine.model['status'], 'blocked', engine.model['message'])
        self.assertTrue(engine.model['heldGoal'])
        self.assertFalse(screen.clicked)
        self.assertFalse(any(a['kind'] in ('click', 'enter') for a in screen.sent))

    def test_recovery_replays_learned_move_before_checking_duplicate_target(self):
        screen,opening,closing=desktop_lessons(DuplicateScreen())
        e=StateEngine();e.learn(opening);e.learn(closing)
        screen.open=True;screen.sent=[]
        t=self._terminal(e,screen);e.start('o1',screen.observe())
        with patch('builtins.print'):
            for _ in range(200):
                if e.model['status'] in STOP:break
                t.tick_once()
        self.assertEqual(e.model['status'],'complete',e.model['message'])
        self.assertEqual([a.get('object') for a in screen.sent if a['kind']=='click'],['glaz.202','glaz.101'])
        self.assertEqual([(a['x'],a['y']) for a in screen.sent if a['kind']=='move'],[(200,190),(920,75),(200,190)])
        steps=[ev['action']['kind'] for ev in e.events if ev['kind']=='dispatch']
        self.assertEqual(steps, ['move','move','check','click','move','check','click','enter'])
        movements=[ev for ev in e.events if ev['kind']=='dispatch' and ev.get('winner')==e.model['commands'][0]['first']]
        self.assertEqual(len(movements),2)
        self.assertTrue(any(f['aggregation']=='motor-demand' for f in movements[-1]['flows']))

    def test_goal_episode_reorients_after_cursor_disturbs_learned_check(self):
        screen,opening,closing=desktop_lessons(DuplicateScreen())
        e=StateEngine();e.learn(opening);e.learn(closing)
        screen.open=False;screen.cursor=dict(x=500,y=300);screen.sent=[]
        t=self._terminal(e,screen)
        e.start_goals([dict(kind='state',features=opening['receipts'][-1]['after']['features'])],screen.observe())
        disturbed=False
        with patch('builtins.print'):
            for _ in range(200):
                if e.model['status'] in STOP:break
                ep=e.model['intent']['episode']
                if ep and not e.model['pending'] and not disturbed and e.node(ep['step'])['action']['kind']=='check':
                    screen.cursor=dict(x=920,y=75);disturbed=True
                t.tick_once()
        self.assertTrue(disturbed)
        self.assertEqual(e.model['status'],'complete',e.model['message'])
        self.assertEqual([(a['x'],a['y']) for a in screen.sent if a['kind']=='move'],[(200,190),(200,190)])
        self.assertEqual([a.get('object') for a in screen.sent if a['kind']=='click'],['glaz.101'])

    def test_missing_recalled_move_receipt_keeps_check_and_does_not_repeat_motion(self):
        screen,opening,_=desktop_lessons(DuplicateScreen());e=StateEngine();e.learn(opening)
        screen.open=False;screen.cursor=dict(x=920,y=75);screen.sent=[]
        e.start('o1',screen.observe());e.model['phase']='execute'
        check=next(n for n in e.model['memory']['nodes'] if n.get('action',{}).get('kind')=='check')
        e.model['entry']=check['id']
        for _ in range(30):
            e.tick()
            if e.model['pending']:break
        pending=clone(e.model['pending']);self.assertTrue(pending['relocate'])
        screen.send(pending['action'])
        for _ in range(e.model['config']['timeout']):e.tick()
        self.assertEqual(e.model['status'],'timeout');self.assertTrue(e.model['heldGoal'])
        self.assertEqual(e.model['entry'],check['id']);self.assertEqual(len(screen.sent),1)

    def test_recorded_recovery_continues_enter_despite_duplicate_id_after_highlighting(self):
        screen,opening,closing=desktop_lessons(HighlightedScreen())
        enter=opening['receipts'][-1]
        self.assertIn('glaz.101',enter['before']['object_issues'])
        self.assertEqual(enter['before']['last_clicked'],'glaz.101')
        e=StateEngine();e.learn(opening);e.learn(closing)
        screen.open=True;screen.sent=[]
        t=Terminal.__new__(Terminal);t.engine=e;t.observer=screen
        t.adapter=DesktopAdapter(screen,screen,allow=lambda:True,timeout=.05)
        t.receipt=None;t.store=Mock();t.running=True;t.pause=threading.Event();t.language_auto=False
        e.start('o1',screen.observe())
        with patch('builtins.print'):
            for _ in range(200):
                if e.model['status'] in STOP:break
                t.tick_once()
        self.assertEqual(e.model['status'],'complete',e.model['message'])
        self.assertEqual([a.get('object') for a in screen.sent if a['kind']=='click'],['glaz.202','glaz.101'])
        self.assertEqual([a['kind'] for a in screen.sent if a['kind']=='enter'],['enter'])
        self.assertTrue(screen.open)

    def test_goal_network_preserves_dispatch_only_click_trace_before_enter(self):
        screen,opening,closing=desktop_lessons();e=StateEngine();e.learn(opening);e.learn(closing)
        screen.open=False;screen.sent=[]
        t=Terminal.__new__(Terminal);t.engine=e;t.observer=screen
        t.adapter=DesktopAdapter(screen,screen,allow=lambda:True,timeout=.05)
        t.receipt=None;t.store=Mock();t.running=True;t.pause=threading.Event();t.language_auto=False
        e.start_goals([dict(kind='state',features=opening['receipts'][-1]['after']['features'])],screen.observe())
        with patch('builtins.print'):
            for _ in range(200):
                if e.model['status'] in STOP:break
                t.tick_once()
        self.assertEqual(e.model['status'],'complete',e.model['message'])
        self.assertEqual([a['kind'] for a in screen.sent],['move','click','enter'])

    def test_recorded_delayed_close_drives_recovery_with_new_distractors(self):
        screen, opening, closing=desktop_lessons()
        self.assertTrue(closing['receipts'][-1]['effect_observed'])
        self.assertNotIn('glaz.202',[i['id'] for i in closing['receipts'][-1]['after']['icons']])
        e=StateEngine();e.learn(opening);e.learn(closing)
        self.assertFalse(any(n['kind']=='transition' and n['label'].startswith(('MOVE','CHECK')) for n in e.model['memory']['nodes']))
        self.assertFalse(any(f.startswith('clicked:') for n in e.model['memory']['nodes'] for f in n.get('features',[])))
        screen.open=True;screen.extra=True;screen.sent=[]
        t=Terminal.__new__(Terminal);t.engine=e;t.observer=screen
        t.adapter=DesktopAdapter(screen,screen,allow=lambda:True,timeout=.05)
        t.receipt=None;t.store=Mock();t.running=True;t.pause=threading.Event();t.language_auto=False
        e.start('o1',screen.observe())
        with patch('builtins.print'):
            for _ in range(200):
                if e.model['status'] in STOP:break
                t.tick_once()
        self.assertEqual(e.model['status'],'complete',e.model['message'])
        self.assertEqual([a.get('object') for a in screen.sent if a['kind']=='click'],['glaz.202','glaz.101'])
        self.assertTrue(screen.open)
        self.assertTrue(any(x['kind']=='route' for x in e.events))
        self.assertTrue(any(x.get('plasticity',{}).get('changes') for x in e.events))

    def test_dispatch_only_and_movement_do_not_teach_a_world_transition(self):
        screen=Screen();r=Recorder(screen,'tap',settle_timeout=0)
        screen.teach_click(r,101);record=r.finish();e=StateEngine();e.learn(record)
        self.assertFalse(record['receipts'][-1]['effect_observed'])
        self.assertFalse(any(n['kind']=='transition' for n in e.model['memory']['nodes']))

    def test_without_observed_close_or_its_connection_recovery_is_absent(self):
        for lesion in ('effect','weight'):
            screen,opening,closing=desktop_lessons();e=StateEngine()
            if lesion=='effect':closing['receipts'][-1]['effect_observed']=False
            e.learn(opening);e.learn(closing)
            if lesion=='weight':
                t=next(n for n in e.model['memory']['nodes'] if n['kind']=='transition' and n['label']=='CLICK glaz.202')
                next(x for x in e.model['memory']['edges'] if x['kind']=='backward' and x['to']==t['id'])['weight']=0
            screen.open=True;screen.sent=[];adapter=DesktopAdapter(screen,screen,allow=lambda:True,timeout=.05)
            e.start('o1',screen.observe())
            for _ in range(120):
                if e.model['status'] in STOP:break
                e.tick()
                if e.model['pending']:e.accept_receipt(adapter.execute(e.model['pending']))
            self.assertTrue(e.model['heldGoal']);self.assertEqual(e.model['status'],'blocked')
            self.assertFalse(any(a['kind']=='click' for a in screen.sent))

    def test_click_trace_does_not_resurrect_hidden_target_or_allow_enter(self):
        screen=Screen();before=screen.observe();icon=before['icons'][0];screen.open=True
        marked=click_trace(before,screen.observe(),icon['id'],icon)
        self.assertNotIn(icon['id'],[i['id'] for i in marked['icons']])
        self.assertTrue(guard(marked,dict(kind='enter',object=icon['id'])))

    def test_single_missing_detection_is_reobserved_before_dispatch(self):
        screen=Screen();missing=screen.observe();missing.update(icons=[],features=[])
        original=screen.observe;count=0
        def observe_once_missing(**kwargs):
            nonlocal count
            count+=1
            return missing if count==1 else original(**kwargs)
        observer=SimpleNamespace(observe=observe_once_missing)
        adapter=DesktopAdapter(observer,screen,allow=lambda:True,timeout=.05)
        r=adapter.execute(dict(id='check',action=dict(kind='check',object='glaz.101')))
        self.assertTrue(r['ok']);self.assertGreaterEqual(count,4);self.assertEqual(screen.sent,[])

    def test_repeated_frame_cannot_confirm_a_result(self):
        screen=Screen();before=screen.observe();after=clone(before)
        after['selected']='glaz.101';after['features'].append('selected:glaz.101');after['captured_at']+=1
        class Observer:
            def observe(self, **kwargs):return after if kwargs else before
        adapter=DesktopAdapter(Observer(),screen,allow=lambda:True,timeout=.001)
        with self.assertRaises(Indeterminate):
            adapter.execute(dict(id='click',action=dict(kind='click',object='glaz.101')))
        self.assertEqual(len(screen.sent),1);self.assertFalse(adapter.receipts)

    def test_later_action_cannot_be_credited_to_previous_click(self):
        screen=Screen();r=Recorder(screen,'open',settle_timeout=0);screen.teach_click(r,101)
        with self.assertRaisesRegex(ValueError,'до исходного наблюдения'):
            r.capture(dict(kind='enter'),screen.stamp-.1)
        with self.assertRaisesRegex(ValueError,'до исходного наблюдения'):
            r.capture(dict(kind='click'),screen.stamp+1,(200,190),pressed_at=screen.stamp-.1)

    def test_ambiguous_recognition_excites_vision_without_authorizing_click(self):
        screen=Screen();o=screen.observe();icon=clone(o['icons'][0]);icon['ambiguous']=True
        raw=dict(icons=[icon],cursor=o['cursor'],frame=1,session='s',captured_at=1,monitor={})
        uia=SimpleNamespace(read=lambda:dict(focus='',output='',readable=False,own=False,reason=''))
        observer=DesktopObserver(SimpleNamespace(request=lambda **_:raw),uia)
        observed=observer.observe()
        self.assertIn('visible:glaz.101',observed['features']);self.assertEqual(observed['icons'],[])
        motor=Mock();r=DesktopAdapter(observer,motor,allow=lambda:True).execute(dict(id='a',action=dict(kind='click',object='glaz.101')))
        self.assertFalse(r['ok']);motor.send.assert_not_called()


class OrientingDynamicsTests(unittest.TestCase):
    def prepare(self, kind='check'):
        screen,opening,_=desktop_lessons(DuplicateScreen());e=StateEngine();e.learn(opening)
        screen.open=False;screen.cursor=dict(x=920,y=75);e.observe(screen.observe())
        step=next(n for n in e.model['memory']['nodes'] if n.get('action',{}).get('kind')==kind)
        return e,step

    def choice(self,e,step):
        for _ in range(20):
            sensory_tick(e.model,[])
            choice=orienting_choice(e.model,step,e.model['config'],[])
        return choice

    def test_zero_sequence_connection_prevents_recalled_movement(self):
        for kind in ('check','click'):
            e,step=self.prepare(kind)
            link=next(x for x in e.model['memory']['edges'] if x['kind']=='next' and x['to']==step['id'])
            link['weight']=0;choice=self.choice(e,step)
            self.assertNotIn('winner',choice);self.assertFalse(choice['charging'])
            self.assertTrue(all(c['a']==0 for c in choice['candidates']))

    def test_equal_motor_candidates_do_not_choose_by_id_or_storage_order(self):
        for reverse in (False,True):
            e,step=self.prepare();move=e.node(e.model['commands'][0]['first'])
            other=clone(move);other.update(id='other-move',action=dict(kind='move',x=700,y=500))
            e.model['memory']['nodes'].append(other)
            e.model['memory']['edges'].append(dict(id='other-edge',kind='next',weight=.9,to=step['id'],**{'from':other['id']}))
            if reverse:e.model['memory']['nodes'].reverse();e.model['memory']['edges'].reverse()
            choice=self.choice(e,step)
            self.assertTrue(choice['ambiguous']);self.assertNotIn('winner',choice)

    def test_ambiguous_instance_at_learned_point_does_not_repeat_move_or_allow_click(self):
        e,step=self.prepare('click');e.model['observed']['cursor']=dict(x=200,y=190)
        self.assertTrue(guard(e.model['observed'],step['action']))
        self.assertEqual(self.choice(e,step),dict(candidates=[],charging=False))


class PlasticityTests(unittest.TestCase):
    def run_close(self,e,w):
        e.start('close',observe(w))
        for _ in range(150):
            if e.model['status'] in STOP:break
            e.tick()
            if e.model['pending']:
                p=clone(e.model['pending']);r=apply(w,p);e.tick();e.accept_receipt(r)
        return r

    def lesson(self):
        w=default_world();w['surface']='window';e=StateEngine()
        e.learn(demonstrate('close',w,icon_actions(w,'X')))
        return e,w

    def test_only_involved_outcome_weight_changes_and_duplicate_is_inert(self):
        e,w=self.lesson();before={x['id']:x['weight'] for x in e.model['memory']['edges']}
        r=self.run_close(e,w)
        changed=[x for x in e.model['memory']['edges'] if x['id'] in before and x['weight']!=before[x['id']]]
        self.assertEqual(len(changed),1);self.assertEqual(changed[0]['kind'],'backward')
        self.assertGreater(changed[0]['weight'],before[changed[0]['id']])
        saved=persistent_graph(e.model['memory']);e.accept_receipt(r)
        self.assertEqual(saved,persistent_graph(e.model['memory']))

    def test_unexpected_observed_outcome_inhibits_and_learns_actual_result(self):
        e,w=self.lesson();before={x['id']:x['weight'] for x in e.model['memory']['edges']}
        t=next(n for n in e.model['memory']['nodes'] if n['kind']=='transition')
        w['surfaces']['window']['icons'][0]['click']='calculator'
        e.start('close',observe(w))
        for _ in range(80):
            e.tick()
            if not e.model['pending']:continue
            p=clone(e.model['pending']);r=apply(w,p);e.tick();event=e.accept_receipt(r)
            if p['action']['kind']=='click':break
        self.assertEqual(event['kind'],'prediction-error');self.assertTrue(e.model['heldGoal'])
        changes=event['plasticity']['changes'];self.assertEqual(len(changes),1)
        self.assertAlmostEqual(changes[0]['after'],.9-.05*.9*.9)
        self.assertEqual(e.node(t['id'])['inhibition'],1)
        self.assertIsNotNone(event['plasticity']['learned'])
        actual=e.node(event['plasticity']['learned']);self.assertIn('focus:FIELD',e.node(actual['to'])['features'])
        e.model['observed']=r['before'];e.node(t['from'])['sensory']=1
        c=next(c for c in transition_candidates(e.model,{t['id']:1},e.model['config'],.65) if c['id']==t['id'])
        self.assertEqual(c['a'],0);self.assertEqual(c['inhibition'],1)
        for edge in e.model['memory']['edges']:
            if edge['id'] in before and edge['id']!=changes[0]['edge']:self.assertEqual(edge['weight'],before[edge['id']])
        saved=persistent_graph(e.model['memory']);e.accept_receipt(r)
        self.assertEqual(saved,persistent_graph(e.model['memory']))

    def test_internal_image_does_not_train_with_plasticity_enabled(self):
        from kolos_states.capabilities import prepare
        e,w,request=prepare(9);e.configure(plasticity=1);before=persistent_graph(e.model['memory'])
        e.imagine(request['goals'],observe(w))
        for _ in range(40):e.tick()
        self.assertEqual(before,persistent_graph(e.model['memory']));self.assertIsNone(e.model['pending'])

    def test_new_context_reuses_motor_actions_and_survives_reload(self):
        e,w=self.lesson();initial=len(e.model['memory']['nodes'])
        w['surfaces']['window']['icons'][1]['id']='new-1';w['surfaces']['window']['icons'][2]['id']='new-2'
        self.run_close(e,w)
        self.assertEqual(e.model['status'],'complete');self.assertGreater(len(e.model['memory']['nodes']),initial)
        learned=[n for n in e.model['memory']['nodes'] if n['kind']=='transition']
        self.assertEqual(len(learned),2);self.assertEqual(len(e.model['commands']),1)
        count=len(e.model['memory']['nodes']);w.update(surface='window',effects=[],selected='',focus='')
        self.run_close(e,w);self.assertEqual(len(e.model['memory']['nodes']),count)
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder));store.save(e);restored=store.load();store.close()
        self.assertEqual(persistent_graph(e.model['memory']),restored.model['memory'])
        self.assertIsNone(restored.model['pending']);self.assertEqual(restored.model['status'],'idle')

    def test_missing_receipt_does_not_learn_and_disabled_plasticity_freezes_graph(self):
        for plasticity in (0,1):
            e,w=self.lesson();e.configure(plasticity=plasticity);before=persistent_graph(e.model['memory'])
            e.start('close',observe(w))
            while not e.model['pending']:e.tick()
            for _ in range(45):e.tick()
            self.assertEqual(before,persistent_graph(e.model['memory']))
        e,w=self.lesson();e.configure(plasticity=0);before=persistent_graph(e.model['memory'])
        self.run_close(e,w);self.assertEqual(before,persistent_graph(e.model['memory']))

    def test_send_without_observed_effect_cannot_confirm_learned_close(self):
        e,w=self.lesson();before=persistent_graph(e.model['memory']);e.start('close',observe(w))
        for _ in range(50):
            e.tick()
            p=e.model['pending']
            if not p:continue
            if p['action']['kind']=='click':break
            e.accept_receipt(apply(w,p))
        observed=observe(w);r=dict(id=p['id'],action=p['action'],ok=True,before=observed,after=observed,effect_observed=False)
        self.assertEqual(e.accept_receipt(r)['kind'],'unconfirmed')
        self.assertIsNotNone(e.model['pending']);self.assertTrue(e.model['heldGoal'])
        self.assertEqual(before,persistent_graph(e.model['memory']))
        for _ in range(e.model['config']['timeout']):e.tick()
        self.assertEqual(e.model['status'],'timeout');self.assertEqual(before,persistent_graph(e.model['memory']))

    def test_legacy_backup_is_exact_and_invalid_snapshot_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);old='{"schema":"kolos-desktop-states/1","lessons":[]}'
            (path/'memory.json').write_text(old,encoding='utf-8')
            store=Store(path);e=store.load()
            self.assertEqual(next(path.glob('memory-v1-*.json')).read_text(encoding='utf-8'),old)
            self.assertFalse(e.model['commands'])
            raw=json.loads((path/'memory.json').read_text(encoding='utf-8'));raw['memory']['root']='missing'
            text=json.dumps(raw);(path/'memory.json').write_text(text,encoding='utf-8')
            with self.assertRaises(ValueError):store.load()
            self.assertEqual((path/'memory.json').read_text(encoding='utf-8'),text);store.close()

    def test_python_js_online_weights_and_new_topology_match(self):
        if not shutil.which('node'):self.skipTest('Node is required for cross-language checks')
        cases=json.loads(subprocess.check_output(['node',str(ROOT/'tests/desktop/neural_reference.mjs')],cwd=ROOT,text=True,encoding='utf-8'))
        for case in cases:
            e=StateEngine()
            for record in case['lessons']:e.learn(record)
            e.start(case['query'],case['observed'])
            for row in case['trace']:
                e.observe(row['before']);ev=e.tick();expected=row['event']
                if expected['kind'] in ('ack','prediction-error'):ev=e.accept_receipt(expected['receipt'])
                elif expected['kind']!='effect':self.assertEqual(ev['kind'],expected['kind'])
                if expected['kind']=='dispatch' and any(f.get('aggregation')=='motor-demand' for f in expected.get('flows',[])):
                    self.assertEqual(ev['flows'],expected['flows']);self.assertEqual(ev['candidates'],expected['candidates'])
                self.assertEqual(persistent_graph(e.model['memory']),row['memory'])
                self.assertEqual(e.model['goalActivation'],row['goalActivation'])
                self.assertEqual(e.model['activation'],row['activation'])
                self.assertEqual([{k:n.get(k,0) for k in ('id','sensory','eligibility','inhibition')} for n in e.model['memory']['nodes']],row['currents'])


if __name__=='__main__':unittest.main()
