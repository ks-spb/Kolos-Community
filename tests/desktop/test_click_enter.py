"""CLICK -> Enter retains the chosen instance without another recognition pass."""
import contextlib
import io
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image
from kolos_states.cli import Terminal
from kolos_states.core import StateEngine, STOP
from kolos_states.desktop import DesktopAdapter, DesktopObserver, Indeterminate
from kolos_states.protocol import clone, guard
from kolos_states.targeting import click_followup
from kolos_states.visual import sample_frame
from tests.perception.test_integration import motor_lesson


class ClickScreen:
    """Three identical icons; selection changes one ID and adds a tooltip."""
    def __init__(self):
        self.cursor = dict(x=37, y=37)
        self.sent = []; self.scans = []; self.version = 0
        self.clicked = False; self.open = False; self.no_enter_effect = False
        self.allowed = True; self.own = False; self.foreground = 100; self.focus = ''
        self.output = ''; self.window = None
        self.block_after_click_scans = True
        self.context_valid = True
        self.session = 's'; self.monitor = dict(left=0, top=0, width=900, height=200)

    def request(self, *, after=0, mode=None, **options):
        kind = self.sent[-1]['kind'] if self.sent else None
        self.scans.append((kind, mode))
        if self.block_after_click_scans and kind == 'click' and mode != 'frame-only':
            raise AssertionError('Object recognition after CLICK and before Enter')
        self.version += 1
        image = Image.new('RGB', (900, 200), 'white' if self.open else '#5478a1' if self.clicked else '#203050')
        result = dict(mode=mode, cursor=clone(self.cursor), frame=self.version, session=self.session,
                      captured_at=max(time.time(), after+.00001), monitor=clone(self.monitor),
                      visual_sample=sample_frame(image), complete=True)
        if mode != 'frame-only':
            result['icons'] = [dict(id='OPEN', x=10, y=10, bbox=[0,0,20,20])] if self.open else [
                dict(id='glaz.43' if self.clicked and x==37 else 'glaz.56',
                     x=x, y=37, bbox=[x-20,17,x+20,57], ambiguous=True) for x in (37,400,800)]
        return result

    def read(self):
        return dict(focus=self.focus, output=self.output, readable=False, own=self.own, reason='',
                    foreground=self.foreground, context_valid=self.context_valid,
                    window=self.window or ('window:folder' if self.open else 'window:desktop'),
                    selected_bbox=[17,17,57,57] if self.clicked else None)

    def send(self, action):
        self.sent.append(clone(action))
        if action['kind']=='move':self.cursor=dict(x=action['x'], y=action['y'])
        elif action['kind']=='click':self.clicked=True
        elif action['kind']=='enter' and not self.no_enter_effect:self.open=True


def ordinary_terminal(*, recorded_click_effect=False):
    lesson=motor_lesson();lesson['query']='o3'
    for receipt in lesson['receipts']:
        if receipt['action'].get('object')=='A':receipt['action']['object']='glaz.56'
        for key in ('before','after'):
            observed=receipt[key]
            for icon in observed['icons']:
                if icon['id']=='A':icon['id']='glaz.56'
            observed['features']=[f.replace('visible:A','visible:glaz.56') for f in observed['features']]
            if observed.get('last_clicked')=='A':observed['last_clicked']='glaz.56'
        if receipt['action']['kind']=='click':receipt['effect_observed']=recorded_click_effect
    engine=StateEngine();engine.learn(lesson)
    screen=ClickScreen();observer=DesktopObserver(screen,screen)
    adapter=DesktopAdapter(observer,screen,allow=lambda:screen.allowed,timeout=.1)
    terminal=Terminal.__new__(Terminal)
    terminal.engine=engine;terminal.observer=observer;terminal.adapter=adapter
    terminal.receipt=None;terminal.store=Mock();terminal.running=True;terminal.language_auto=False
    terminal.pause=threading.Event();terminal.abort=threading.Event();terminal.schedule=None
    terminal.recording=False;terminal.recorder=None;terminal.closed=False
    engine.start('o3',observer.observe())
    return terminal,screen


class ClickEnterTests(unittest.TestCase):
    def run_until(self, terminal, predicate):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            for _ in range(150):
                terminal.tick_once()
                if predicate():return output.getvalue()
        self.fail('Attempt did not reach the expected step')

    def clicked(self, terminal, screen):
        self.run_until(terminal, lambda:screen.clicked and terminal.receipt is None)

    def test_o3_uses_clicked_56_when_selected_id_becomes_43(self):
        for recorded_effect in (False,True):
            with self.subTest(recorded_effect=recorded_effect):
                terminal,screen=ordinary_terminal(recorded_click_effect=recorded_effect)
                self.run_until(terminal,lambda:terminal.engine.model['status'] in STOP)
                self.assertEqual(terminal.engine.model['status'],'complete',terminal.engine.model['message'])
                self.assertEqual([a['kind'] for a in screen.sent],['move','click','enter'])
                self.assertEqual(screen.sent[-1]['object'],'glaz.56')
                self.assertTrue(all(mode=='frame-only' for kind,mode in screen.scans if kind=='click'))
                receipt=next(r for r in terminal.engine.model['receipts'] if r['action']['kind']=='click')
                self.assertFalse(receipt['effect_observed'])
                self.assertEqual(receipt['verified_by'],'verified-target-click')

    def test_goal_mode_keeps_the_direct_enter_despite_missing_old_state_features(self):
        terminal,screen=ordinary_terminal()
        terminal.engine.start_goals([dict(kind='state',features=['visible:OPEN'])],terminal.observer.observe())
        self.run_until(terminal,lambda:terminal.engine.model['status'] in STOP)
        self.assertEqual(terminal.engine.model['status'],'complete',terminal.engine.model['message'])
        self.assertEqual([a['kind'] for a in screen.sent],['move','click','enter'])

    def test_image_only_enter_can_finish_when_baseline_has_no_state_features(self):
        terminal,screen=ordinary_terminal()
        for n in terminal.engine.model['memory']['nodes']:
            if n.get('action',{}).get('kind')=='enter':n['visual_ack']=True
        original=screen.read
        def image_context():
            result=original();result['window']=''
            return result
        screen.read=image_context
        self.run_until(terminal,lambda:terminal.engine.model['status'] in STOP)
        self.assertEqual(terminal.engine.model['status'],'complete',terminal.engine.model['message'])
        self.assertEqual([a['kind'] for a in screen.sent],['move','click','enter'])

    def test_click_returns_without_post_click_frames_and_duplicate_cannot_repeat_it(self):
        terminal,screen=ordinary_terminal();adapter=terminal.adapter
        request=dict(id='click',action=dict(kind='click',object='glaz.56'))
        followup=dict(kind='enter',object='glaz.56')
        receipt=adapter.execute(request,followup=followup)
        self.assertTrue(receipt['ok'])
        self.assertFalse(any(kind=='click' for kind,_ in screen.scans))
        self.assertEqual(adapter.execute(request,followup=followup),receipt)
        self.assertEqual(len(screen.sent),1)
        entered=adapter.execute(dict(id='enter',action=followup),visual_ack=True)
        self.assertTrue(entered['ok'])
        self.assertIsNone(adapter._continuation)
        self.assertEqual(adapter.execute(dict(id='enter',action=followup)),entered)
        self.assertEqual(len(screen.sent),2)

    def test_context_changes_continue_enter_once_in_commands_and_goals(self):
        changes = dict(foreground=200, focus='tooltip', own=True, output='expanded label',
                       window='window:other', context_valid=False)
        for goals in (False,True):
            for change in (*changes, 'all'):
                with self.subTest(goals=goals, change=change):
                    terminal,screen=ordinary_terminal()
                    if goals:
                        terminal.engine.start_goals([dict(kind='state',features=['visible:OPEN'])],terminal.observer.observe())
                    self.clicked(terminal,screen)
                    for key,value in changes.items():
                        if change in (key,'all'):setattr(screen,key,value)
                    output=self.run_until(terminal,lambda:terminal.engine.model['status'] in STOP)
                    self.assertEqual(terminal.engine.model['status'],'complete',terminal.engine.model['message'])
                    self.assertEqual([a['kind'] for a in screen.sent],['move','click','enter'])
                    self.assertEqual(screen.sent[-1]['object'],'glaz.56')
                    self.assertTrue(all(mode=='frame-only' for kind,mode in screen.scans if kind=='click'))
                    self.assertNotIn('click-continuation-lost',output)
                    self.assertIsNone(terminal.adapter._continuation)

    def test_enter_without_saved_continuation_still_rejects_glaz_focus(self):
        terminal,screen=ordinary_terminal()
        screen.clicked=True;screen.own=True
        receipt=terminal.adapter.execute(dict(id='standalone-enter',action=dict(kind='enter',object='glaz.43')))
        self.assertFalse(receipt['ok'])
        self.assertIn('Фокус находится в Glaz',receipt['reason'])
        self.assertFalse(screen.sent)

    def test_stop_permission_and_pause_prevent_enter(self):
        for change in ('stop','permission','pause'):
            with self.subTest(change=change):
                terminal,screen=ordinary_terminal();self.clicked(terminal,screen)
                if change=='stop':terminal.adapter.stop.set()
                elif change=='permission':screen.allowed=False
                else:terminal.adapter.paused=lambda:True
                with self.assertRaises((InterruptedError,PermissionError)):
                    self.run_until(terminal,lambda:terminal.engine.model['status'] in STOP)
                self.assertEqual([a['kind'] for a in screen.sent],['move','click'])
                if change!='pause':self.assertIsNone(terminal.adapter._continuation)

    def test_reset_and_stop_discard_click_continuation(self):
        for command in ('/reset','/stop'):
            with self.subTest(command=command):
                terminal,screen=ordinary_terminal();self.clicked(terminal,screen)
                with contextlib.redirect_stdout(io.StringIO()):terminal.command(command)
                self.assertIsNone(terminal.adapter._continuation)
                self.assertEqual([a['kind'] for a in screen.sent],['move','click'])
                if command=='/reset':self.assertIsNone(terminal.adapter._lost_followup)

    def test_another_motor_action_or_new_attempt_does_not_reuse_click_selection(self):
        for change in ('move','new-attempt'):
            with self.subTest(change=change):
                terminal,screen=ordinary_terminal();self.clicked(terminal,screen)
                if change=='move':
                    screen.block_after_click_scans=False
                    terminal.adapter.execute(dict(id='other-move',action=dict(kind='move',x=400,y=37)))
                else:
                    terminal.adapter.clear_click()
                    terminal.engine.start('o3',dict(features=['visible:glaz.56'],icons=[],
                        focus='',selected='',output='',cursor=dict(x=37,y=37)))
                self.assertIsNone(terminal.adapter._continuation)
                self.assertIsNone(terminal.adapter._assumed_click)

    def test_highlighting_without_enter_effect_is_not_completion_and_is_not_resent(self):
        terminal,screen=ordinary_terminal();screen.no_enter_effect=True
        with self.assertRaises(Indeterminate):
            self.run_until(terminal,lambda:terminal.engine.model['status'] in STOP)
        self.assertNotEqual(terminal.engine.model['status'],'complete')
        self.assertTrue(terminal.engine.model['heldGoal'])
        pending=terminal.engine.model['pending']
        with self.assertRaises(Indeterminate):terminal.adapter.execute(pending)
        self.assertEqual([a['kind'] for a in screen.sent],['move','click','enter'])

    def test_only_the_direct_same_target_enter_can_follow_a_click(self):
        terminal,_=ordinary_terminal();memory=terminal.engine.model['memory']
        click=next(n for n in memory['nodes'] if n.get('action',{}).get('kind')=='click')
        self.assertEqual(click_followup(memory,click),dict(kind='enter',object='glaz.56'))
        entered=next(n for n in memory['nodes'] if n.get('action',{}).get('kind')=='enter')
        entered['action']['object']='other'
        self.assertIsNone(click_followup(memory,click))
        self.assertTrue(guard(dict(icons=[],cursor=dict(x=0,y=0),focus='',selected='',output=''),entered['action']))


if __name__=='__main__':unittest.main()
