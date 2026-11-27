"""Production command/observer/motor handshake driven by actual label pixels."""
from __future__ import annotations

import contextlib
import io
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from PIL import Image, ImageDraw
from kolos_states.core import StateEngine, STOP
from kolos_states.cli import Terminal
from kolos_states.desktop import DesktopAdapter, DesktopObserver
from kolos_states.protocol import clone, mark_clicked
from kolos_states.visual import sample_frame
from kolos_states.perception.learning import bind
from kolos_states.perception.types import views
from tests.perception.fixtures import scene, learned
from Glaz.perception.retina import collect


def motor_lesson() -> dict:
    """A previous ordinary command has no knowledge of the later relocation."""
    icon = dict(id='A', x=45, y=50, bbox=[30,35,60,65])
    before = dict(features=['visible:A'], icons=[icon], focus='', selected='', output='', cursor=dict(x=0,y=0))
    moved = dict(clone(before), cursor=dict(x=45,y=50))
    clicked = mark_clicked(moved, 'A', icon)
    opened = dict(clone(clicked), features=['visible:OPEN'], icons=[dict(id='OPEN',x=10,y=10,bbox=[0,0,20,20])])
    receipts = []
    for index, (action, left, right, effect) in enumerate([
        (dict(kind='move',x=45,y=50), before, moved, False),
        (dict(kind='check',object='A'), moved, moved, False),
        (dict(kind='click',object='A'), moved, clicked, False),
        (dict(kind='enter',object='A'), clicked, opened, True),
    ]):
        receipts.append(dict(id=str(index), action=action, before=left, after=right, ok=True,
                             effect_observed=effect, verified_by='observed-user-action'))
    return dict(query='o1', receipts=receipts)


class PixelScreen:
    """Only the independent world knows which item a physical click touches."""

    def __init__(self, engine: StateEngine, *, names: tuple = ('Contracts', 'Documents', 'Reports')):
        self.engine = engine; self.frame, self.boxes, _ = scene(names, order=(2,0,1))
        self.cursor = dict(x=45, y=50); self.open = False; self.clicked = None; self.sent = []; self.version = 0
        self.monitor = dict(left=0,top=0,width=600,height=230)
        self.scans = []

    def request(self, *, after: float = 0, visual_requests: list | None = None, mode=None) -> dict:
        """Serve actual pixels plus ordinary coarse icon classes, never label strings."""
        self.version += 1
        self.scans.append((self.sent[-1]['kind'] if self.sent else None, mode))
        frame = self.frame; boxes = self.boxes
        if self.open:
            frame = Image.new('RGB', (600,230), '#554477'); boxes = [[0,0,20,20]]
        obj = 'OPEN' if self.open else 'glaz.43' if self.clicked is not None else 'A'
        icons = [dict(id=obj,x=(b[0]+b[2])//2,y=(b[1]+b[3])//2,bbox=b, ambiguous=not self.open) for b in boxes]
        result = dict(cursor=clone(self.cursor),frame=self.version,session='pixels',
                    captured_at=max(time.time(),after+.00001),monitor=self.monitor,complete=True,
                    visual_sample=sample_frame(frame))
        if mode == 'frame-only':
            return dict(result, mode=mode)
        result.update(icons=icons,perception_samples=collect(frame,boxes,visual_requests or [],40,self.monitor))
        return result

    def send(self, action: dict) -> None:
        """The recognizer does not receive this scene's click/open rules."""
        self.sent.append(clone(action))
        if action['kind'] == 'move':
            self.cursor = dict(x=action['x'],y=action['y'])
        if action['kind'] == 'click':
            self.clicked = next((i for i,b in enumerate(self.boxes) if b[0] <= self.cursor['x'] <= b[2]
                                 and b[1] <= self.cursor['y'] <= b[3]), None)
        if action['kind'] == 'enter':
            self.open = True


def terminal_case(names: tuple = ('Contracts', 'Documents', 'Reports')) -> tuple:
    """Use the real Terminal tick path and DesktopAdapter confirmation protocol."""
    engine = StateEngine(); engine.learn(motor_lesson()); target, _ = learned(engine)
    bind(engine,'o1','A',target)
    screen = PixelScreen(engine,names=names)
    empty = SimpleNamespace(read=lambda: dict(focus='',output='',own=False,readable=False,reason=''))
    observer = DesktopObserver(screen,empty); observer.model_provider = lambda: engine.model
    adapter = DesktopAdapter(observer,screen,allow=lambda:True,timeout=1)
    terminal = Terminal.__new__(Terminal); terminal.engine = engine; terminal.observer = observer
    terminal.adapter=adapter;terminal.receipt=None;terminal.store=Mock();terminal.running=True
    terminal.pause=threading.Event();terminal.language_auto=False
    engine.start('o1',observer.observe())
    return terminal, screen, target


class VisualIntegrationTests(unittest.TestCase):
    def run_attempt(self, terminal: Terminal) -> str:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            for _ in range(100):
                terminal.tick_once()
                if terminal.engine.model['status'] in STOP:
                    break
        return output.getvalue()

    def test_existing_command_moves_to_new_instance_and_opens_once(self) -> None:
        terminal, screen, target = terminal_case()
        self.run_attempt(terminal)
        self.assertEqual(terminal.engine.model['status'],'complete',terminal.engine.model['message'])
        self.assertEqual(screen.clicked,0)
        self.assertEqual([a['kind'] for a in screen.sent],['move','click','enter'])
        self.assertEqual((screen.sent[0]['x'],screen.sent[0]['y']),(425,50))
        self.assertTrue(all(a['visual'] == target for a in screen.sent))

    def test_goal_mode_uses_the_same_grounded_motor_steps(self) -> None:
        terminal,screen,_=terminal_case()
        terminal.engine.start_goals([dict(kind='state',features=['visible:OPEN'])],terminal.observer.observe())
        self.run_attempt(terminal)
        self.assertEqual(terminal.engine.model['status'],'complete',terminal.engine.model['message'])
        self.assertEqual(screen.clicked,0)
        self.assertEqual([a['kind'] for a in screen.sent],['move','click','enter'])

    def test_changed_labels_and_context_after_click_do_not_require_more_attention(self) -> None:
        for goals in (False,True):
            with self.subTest(goals=goals):
                terminal,screen,_=terminal_case()
                if goals:
                    terminal.engine.start_goals([dict(kind='state',features=['visible:OPEN'])],terminal.observer.observe())
                with contextlib.redirect_stdout(io.StringIO()):
                    for _ in range(100):
                        terminal.tick_once()
                        if screen.clicked is not None and terminal.receipt is None:break
                    self.assertIsNotNone(screen.clicked)
                    perception_ticks=terminal.engine.model['perception']['ticks']
                    screen.frame,_,_=scene(('Contracts',)*3,order=(2,0,1))
                    terminal.observer.accessibility.read=lambda:dict(focus='tooltip',output='expanded label',
                        own=True,readable=False,reason='UIA unavailable',foreground=200,
                        window='window:other',context_valid=False)
                    output=self.run_attempt(terminal)
                self.assertEqual(terminal.engine.model['status'],'complete',terminal.engine.model['message'])
                self.assertEqual(terminal.engine.model['perception']['ticks'],perception_ticks)
                self.assertTrue(all(mode=='frame-only' for kind,mode in screen.scans if kind=='click'))
                self.assertEqual([a['kind'] for a in screen.sent],['move','click','enter'])
                self.assertNotIn('click-continuation-lost',output)

    def test_lost_click_confirmation_never_recovers_by_clicking_again(self) -> None:
        terminal,screen,_=terminal_case()
        with contextlib.redirect_stdout(io.StringIO()):
            for _ in range(100):
                terminal.tick_once()
                if screen.clicked is not None and terminal.receipt is None:break
            terminal.adapter.clear_click('Выбор утрачен')
            self.run_attempt(terminal)
        self.assertEqual(terminal.engine.model['status'],'needs-help')
        self.assertTrue(terminal.engine.model['heldGoal'])
        self.assertEqual([a['kind'] for a in screen.sent],['move','click'])

    def test_indistinguishable_objects_hold_goal_and_never_move_or_click(self) -> None:
        terminal, screen, _ = terminal_case(('Contracts',)*3)
        self.run_attempt(terminal)
        self.assertEqual(terminal.engine.model['status'],'needs-help')
        self.assertTrue(terminal.engine.model['heldGoal'])
        self.assertFalse(screen.sent)

    def test_swap_between_choice_and_click_is_rejected_by_fresh_scan(self) -> None:
        terminal, screen, _ = terminal_case()
        with contextlib.redirect_stdout(io.StringIO()):
            for _ in range(100):
                terminal.tick_once()
                pending = terminal.engine.model['pending']
                if pending and pending['action']['kind'] == 'click':
                    break
            else:
                self.fail('No proposed click')
            screen.frame, screen.boxes, _ = scene(order=(0,2,1))
            terminal.tick_once()
        self.assertFalse(any(a['kind'] == 'click' for a in screen.sent))
        self.assertFalse(terminal.receipt['ok'])

    def test_stop_before_send_preserves_pending_without_effect(self) -> None:
        terminal, screen, _ = terminal_case()
        with contextlib.redirect_stdout(io.StringIO()):
            for _ in range(100):
                terminal.tick_once()
                if terminal.engine.model['pending']:
                    break
        terminal.adapter.stop.set()
        with self.assertRaises(InterruptedError):
            terminal.tick_once()
        self.assertFalse(screen.sent)
        self.assertIsNotNone(terminal.engine.model['pending'])


if __name__ == '__main__':
    unittest.main()
