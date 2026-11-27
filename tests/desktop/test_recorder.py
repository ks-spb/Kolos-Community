"""Recording a desktop click after Glaz recognizes its hovered object."""
import sys
import queue
import threading
import time
import unittest
from collections import namedtuple
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PIL import Image, ImageDraw

from kolos_states.cli import Terminal
from kolos_states.core import StateEngine
from kolos_states.desktop import DesktopAdapter, DesktopObserver, Indeterminate
from kolos_states.protocol import clone, guard, observation_key, persistent_graph, validate_record
from kolos_states.recorder import Recorder as NativeRecorder
from kolos_states.simulator import default_world, observe
from kolos_states.visual import changed as visual_changed, sample_frame

PhysicalKey = namedtuple('PhysicalKey', 'char vk')


class SequenceObserver:
    def __init__(self, *observations):
        self.observations = iter(observations)
        self.last=None;self.stamp=None

    def observe(self, **_kwargs):
        self.last=clone(next(self.observations,self.last))
        if self.last.get('captured_at') is not None:
            self.stamp=max(self.last['captured_at'],(self.stamp or 0)+.00001,_kwargs.get('after',0)+.00001)
            self.last['captured_at']=self.stamp
        return clone(self.last)


def Recorder(*args, **kwargs):
    """Bound only the test observer's no-effect settling time."""
    return NativeRecorder(*args,settle_timeout=.002,**kwargs)


def fresh_copy(obs):
    result=clone(obs);result['captured_at']=time.time();return result


class RecorderHoverTests(unittest.TestCase):
    @staticmethod
    def target(timestamp=100.0, bbox=(190, 180, 210, 200)):
        return SimpleNamespace(refined_id=56, timestamp=timestamp, bbox_ltrb=bbox)

    def observations(self):
        world = default_world()
        world['cursor'] = {'x': 200, 'y': 190}
        initial = observe(world)
        initial['icons'] = []
        initial['features'] = ['focus:', 'selected:']
        initial['captured_at'] = 99.0
        after = observe(world)
        after['selected'] = 'glaz.56'
        after['icons'] = [{'id': 'glaz.56', 'x': 200, 'y': 190, 'bbox': [190, 180, 210, 200]}]
        after['features'] = ['focus:', 'selected:glaz.56', 'visible:glaz.56']
        after['captured_at'] = 102.0
        return initial, after

    def test_glaz_id_is_accepted_without_second_kolos_scan(self):
        initial, after = self.observations()
        recorder = Recorder(SequenceObserver(initial, after, after), 'открой')
        with patch('kolos_states.recorder.read_last_confirmed_target', return_value=self.target()) as read:
            recorder.capture({'kind': 'click'}, 102.0, (200, 190), 101.0)
        read.assert_called_once_with(max_age_sec=10, now=101.0)
        record = recorder.finish()
        self.assertEqual([r['action']['kind'] for r in record['receipts']], ['move', 'check', 'click'])
        self.assertEqual(record['receipts'][-1]['action']['object'], 'glaz.56')

    def test_press_time_target_survives_later_file_change(self):
        initial, after = self.observations()
        recorder = Recorder(SequenceObserver(initial, after, after), 'открой')
        with patch('kolos_states.recorder.read_last_confirmed_target') as read:
            recorder.capture({'kind': 'click'}, 102.0, (200, 190), 101.0, self.target())
        read.assert_not_called()
        self.assertEqual(recorder.finish()['receipts'][-1]['action']['object'], 'glaz.56')

    def test_target_confirmed_after_press_cannot_authorize_click(self):
        initial, _ = self.observations()
        recorder = Recorder(SequenceObserver(initial), 'открой')
        with patch('kolos_states.recorder.read_last_confirmed_target', return_value=self.target(timestamp=101.1)):
            with self.assertRaisesRegex(ValueError, 'Glaz не подтвердил'):
                recorder.capture({'kind': 'click'}, 102.0, (200, 190), 101.0)
        self.assertEqual(recorder.receipts, [])

    def test_expired_or_mismatched_target_cannot_authorize_click(self):
        initial, _ = self.observations()
        for target in (self.target(timestamp=90.0), self.target(bbox=(10, 10, 20, 20))):
            with self.subTest(target=target):
                recorder = Recorder(SequenceObserver(initial), 'открой')
                with patch('kolos_states.recorder.read_last_confirmed_target', return_value=target):
                    with self.assertRaisesRegex(ValueError, 'Glaz не подтвердил'):
                        recorder.capture({'kind': 'click'}, 102.0, (200, 190), 101.0)

    def test_conflicting_known_icon_cannot_authorize_click(self):
        initial, _ = self.observations()
        initial['icons'].append({'id': 'other', 'x': 200, 'y': 190})
        recorder = Recorder(SequenceObserver(initial), 'открой')
        with patch('kolos_states.recorder.read_last_confirmed_target', return_value=self.target()):
            with self.assertRaisesRegex(ValueError, 'несколько известных'):
                recorder.capture({'kind': 'click'}, 102.0, (200, 190), 101.0)

    def test_confirmed_hover_replaces_old_id_at_the_same_bounds(self):
        # Actual bounds from the reported #50 scan followed by a #63 hover.
        bounds = (1890, 5, 1901, 16)
        initial, _ = self.observations()
        old = dict(id='glaz.50', x=1896, y=10, bbox=list(bounds))
        unrelated = dict(id='glaz.7', x=100, y=100, bbox=[90, 90, 110, 110])
        initial['icons'] = [old, unrelated]
        initial['selected'] = 'glaz.50'
        initial['features'] = ['focus:', 'selected:glaz.50', 'visible:glaz.50', 'visible:glaz.7']
        target = SimpleNamespace(refined_id=63, timestamp=100.0, bbox_ltrb=bounds)
        closed = clone(initial)
        closed['icons'] = [unrelated]
        closed['selected'] = ''
        closed['features'] = ['focus:', 'selected:', 'visible:glaz.7']
        closed['captured_at'] = 102.0
        recorder = Recorder(SequenceObserver(initial, closed), 'закрой окно')
        recorder.capture({'kind': 'click'}, 102.0, (1894, 9), 101.0, target)
        record = recorder.finish()
        self.assertEqual([r['action']['kind'] for r in record['receipts']], ['move', 'check', 'click'])
        for receipt in record['receipts'][1:]:
            self.assertEqual(receipt['action']['object'], 'glaz.63')
            before = receipt['before']
            self.assertEqual([i['id'] for i in before['icons']], ['glaz.7', 'glaz.63'])
            self.assertNotIn('visible:glaz.50', before['features'])
            self.assertNotIn('selected:glaz.50', before['features'])
            self.assertEqual(before['selected'], '')
            self.assertNotIn('selected:glaz.63', before['features'])
            self.assertEqual(guard(before, receipt['action']), '')
        self.assertEqual(record['receipts'][-1]['after']['last_clicked'], 'glaz.63')
        self.assertEqual(initial['icons'], [old, unrelated])
        self.assertEqual(observation_key(recorder.click_baseline), observation_key(closed))
        self.assertNotIn('glaz.63',[i['id'] for i in record['receipts'][-1]['after']['icons']])
        engine = StateEngine()
        engine.learn(record)

    def test_hover_does_not_replace_a_fresh_or_different_overlapping_object(self):
        for captured_at, bounds in ((100.0, (190, 180, 210, 200)),
                                    (100.5, (190, 180, 210, 200)),
                                    (None, (190, 180, 210, 200)),
                                    (99.0, (195, 180, 215, 200)),
                                    (99.0, (180, 170, 220, 210))):
            with self.subTest(captured_at=captured_at, bounds=bounds):
                initial, _ = self.observations()
                initial['captured_at'] = captured_at
                initial['icons'] = [dict(id='glaz.50', x=200, y=190, bbox=list(bounds))]
                recorder = Recorder(SequenceObserver(initial), 'открой')
                with self.assertRaisesRegex(ValueError, 'несколько известных'):
                    recorder.capture({'kind': 'click'}, 102.0, (200, 190), 101.0, self.target())
                self.assertEqual(recorder.receipts, [])

    def test_replacing_old_id_does_not_hide_another_conflicting_object(self):
        initial, _ = self.observations()
        initial['icons'] = [dict(id='glaz.50', x=200, y=190, bbox=[190, 180, 210, 200]),
                            dict(id='glaz.7', x=205, y=190, bbox=[195, 180, 215, 200])]
        recorder = Recorder(SequenceObserver(initial), 'открой')
        with self.assertRaisesRegex(ValueError, 'несколько известных'):
            recorder.capture({'kind': 'click'}, 102.0, (200, 190), 101.0, self.target())
        self.assertEqual(recorder.receipts, [])

    def test_click_without_visible_effect_is_recorded_from_confirmed_target(self):
        initial, _ = self.observations()
        recorder = Recorder(SequenceObserver(initial, initial), 'открой')
        with patch('kolos_states.recorder.read_last_confirmed_target', return_value=self.target()):
            recorder.capture({'kind': 'click'}, 102.0, (200, 190), 101.0)
        click = recorder.finish()['receipts'][-1]
        self.assertEqual(click['verified_by'], 'confirmed-target-user-click')
        self.assertEqual(click['after']['last_clicked'], 'glaz.56')

    def test_enter_after_unobserved_click_requires_real_screen_change(self):
        initial, _ = self.observations()
        initial['icons']=[dict(id='glaz.56',x=200,y=190,bbox=[190,180,210,200])]
        initial['features'].append('visible:glaz.56')
        initial['visual_sample']=sample_frame(Image.new('RGB',(240,140),(20,70,120)))
        recorder = Recorder(SequenceObserver(initial, initial, initial), 'открой')
        recorder.capture({'kind': 'click'}, 102.0, (200, 190), 101.0, self.target())
        with patch('kolos_states.recorder.time.monotonic', side_effect=[0, 1, 8]):
            with self.assertRaisesRegex(Indeterminate, 'изменилось 0/336'):
                recorder.capture({'kind': 'enter'}, 103.0)

    def test_enter_after_unobserved_click_records_actual_change(self):
        initial, _ = self.observations()
        initial['icons']=[dict(id='glaz.56',x=200,y=190,bbox=[190,180,210,200])]
        initial['features'].append('visible:glaz.56')
        opened = clone(initial)
        opened['features'] = ['focus:', 'selected:', 'visible:window']
        recorder = Recorder(SequenceObserver(initial, initial, opened, opened), 'открой')
        recorder.capture({'kind': 'click'}, 102.0, (200, 190), 101.0, self.target())
        recorder.capture({'kind': 'enter'}, 103.0)
        record = recorder.finish()
        self.assertEqual([r['action']['kind'] for r in record['receipts']], ['move', 'check', 'click', 'enter'])
        self.assertEqual(record['receipts'][-1]['action']['object'], 'glaz.56')

    def test_enter_uses_confirmed_click_when_selection_changes_recognition(self):
        initial, _ = self.observations()
        initial['features'].append('window:Progman|')
        initial['visual_sample']=sample_frame(Image.new('RGB',(240,140),(20,70,120)))
        selected=clone(initial)  # Glaz no longer recognizes the highlighted icon.
        opened=clone(initial)
        opened['features']=['window:CabinetWClass|']
        opened['visual_sample']=sample_frame(Image.new('RGB',(240,140),(240,240,240)))
        recorder=Recorder(SequenceObserver(initial,selected,opened,opened),'o1')
        terminal=Terminal.__new__(Terminal);terminal.recorder=recorder;terminal.record=None
        with patch('builtins.print'):
            terminal._record_event('record-action',({'kind':'click'},102.0,(200,190),101.0,self.target()))
            terminal._record_event('record-action',({'kind':'enter'},103.0,None))
            terminal._record_event('stop-record',None)
        record=terminal.record
        enter=record['receipts'][-1]
        self.assertEqual(enter['action'],dict(kind='enter',object='glaz.56'))
        self.assertEqual(enter['before']['icons'],[])
        self.assertNotIn('visible:glaz.56',enter['before']['features'])
        self.assertEqual(enter['before']['last_clicked'],'glaz.56')
        self.assertFalse(record['receipts'][-2]['effect_observed'])
        self.assertTrue(enter['effect_observed'])
        StateEngine().learn(record)

    def _duplicate_click_observations(self) -> tuple[dict, dict, dict]:
        """Actual duplicate bounds from the user's session, after icon highlighting."""
        initial, _=self.observations()
        initial.update(icons=[dict(id='glaz.56',x=37,y=34,bbox=[14,11,60,56])],
                       features=['visible:glaz.56','window:Progman|'],cursor=dict(x=37,y=37))
        initial['visual_sample']=sample_frame(Image.new('RGB',(240,140),(20,70,120)))
        raw=dict(icons=[dict(id='glaz.43',x=37,y=34,bbox=[14,11,60,56]),
                        dict(id='glaz.56',x=1861,y=134,bbox=[1838,112,1884,157],ambiguous=True),
                        dict(id='glaz.56',x=1861,y=842,bbox=[1838,819,1884,864],ambiguous=True)],
                 cursor=dict(x=37,y=37),captured_at=102.01,frame=2,session='s',monitor={},
                 visual_sample=initial['visual_sample'])
        uia=SimpleNamespace(read=lambda:dict(focus='',output='',readable=False,own=False,
                                            reason='',window='window:Progman|'))
        observer=DesktopObserver(SimpleNamespace(request=lambda **_:raw),uia)
        with patch('kolos_states.desktop.time.time',return_value=102.1):
            highlighted=observer.observe()
        opened=clone(highlighted)
        opened.update(icons=[],features=['window:CabinetWClass|'],captured_at=104.0,observed_at=104.1)
        opened['visual_sample']=sample_frame(Image.new('RGB',(240,140),(240,240,240)))
        return initial,highlighted,opened

    def test_record_enter_keeps_clicked_instance_when_id_matches_elsewhere(self):
        initial,highlighted,opened=self._duplicate_click_observations()
        self.assertNotIn('glaz.56',highlighted['object_issues'])
        self.assertEqual(next(i['bbox'] for i in highlighted['icons'] if i['id']=='glaz.56'),
                         [1838,112,1884,157])
        recorder=Recorder(SequenceObserver(initial,highlighted,opened,opened),'o1')
        terminal=Terminal.__new__(Terminal);terminal.recorder=recorder;terminal.record=None
        target=self.target(bbox=(14,11,60,56))
        with patch('builtins.print'):
            terminal._record_event('record-action',(dict(kind='click'),102.0,(37,37),101.0,target))
            terminal._record_event('record-action',(dict(kind='enter'),103.0,None))
            terminal._record_event('stop-record',None)
        record=terminal.record;enter=record['receipts'][-1]
        self.assertEqual(enter['action'],dict(kind='enter',object='glaz.56'))
        self.assertEqual(enter['before']['last_clicked'],'glaz.56')
        self.assertEqual([i['id'] for i in enter['before']['icons']],['glaz.43','glaz.56'])
        self.assertTrue(guard(enter['before'],dict(kind='click',object='glaz.56')))
        self.assertTrue(guard(enter['before'],dict(kind='check',object='glaz.56')))
        self.assertTrue(enter['effect_observed'])
        StateEngine().learn(record)

    def test_replay_enter_keeps_clicked_instance_through_duplicates_and_visual_noise(self):
        initial,highlighted,opened=self._duplicate_click_observations()
        current=clone(initial)
        def send(a):
            if a['kind']=='click':current.clear();current.update(clone(highlighted))
            elif a['kind']=='enter':current.clear();current.update(clone(opened))
        observer=SimpleNamespace(observe=lambda **_:fresh_copy(current))
        motor=Mock();motor.send.side_effect=send
        adapter=DesktopAdapter(observer,motor,allow=lambda:True)
        clicked=adapter.execute(dict(id='click',action=dict(kind='click',object='glaz.56')),assume_click=True)
        self.assertTrue(clicked['ok'])
        current['features'].append('visible:unrelated')
        current['icons'].append(dict(id='unrelated',x=800,y=500))
        observed=adapter.observe()
        self.assertEqual(observed.get('last_clicked'),'glaz.56')
        self.assertTrue(guard(observed,dict(kind='click',object='glaz.56')))
        receipt=adapter.execute(dict(id='enter',action=dict(kind='enter',object='glaz.56')))
        self.assertTrue(receipt['ok'],receipt['reason'])
        self.assertTrue(receipt['effect_observed'])
        self.assertEqual([c.args[0]['kind'] for c in motor.send.call_args_list],['click','enter'])

    def test_replay_enter_uses_click_trace_without_inventing_visibility(self):
        initial, selected = self.observations()
        initial=clone(selected);initial['selected']=''
        initial['features']=['visible:glaz.56','window:Progman|']
        initial['visual_sample']=sample_frame(Image.new('RGB',(240,140),(20,70,120)))
        current=clone(initial)
        def send(a):
            if a['kind']=='click':
                current['icons']=[];current['features']=['window:Progman|']
            elif a['kind']=='enter':
                current['features']=['window:CabinetWClass|']
                current['visual_sample']=sample_frame(Image.new('RGB',(240,140),(240,240,240)))
        observer=SimpleNamespace(observe=lambda **_:fresh_copy(current))
        motor=Mock();motor.send.side_effect=send
        adapter=DesktopAdapter(observer,motor,allow=lambda:True)
        click=adapter.execute(dict(id='click',action=dict(kind='click',object='glaz.56')),assume_click=True)
        self.assertEqual(click['after']['icons'],[])
        self.assertNotIn('visible:glaz.56',click['after']['features'])
        self.assertEqual(guard(adapter.observe(),dict(kind='click',object='glaz.56')),'Не видна иконка glaz.56')
        enter=adapter.execute(dict(id='enter',action=dict(kind='enter',object='glaz.56')))
        self.assertTrue(enter['ok']);self.assertTrue(enter['effect_observed'])
        self.assertEqual([c.args[0]['kind'] for c in motor.send.call_args_list],['click','enter'])

    def test_click_trace_does_not_allow_enter_after_a_context_change(self):
        initial, _=self.observations()
        initial['features'].append('window:Progman|')
        for change in ('window','focus','selection','image','output'):
            with self.subTest(change=change):
                after=clone(initial)
                if change=='window':after['features']=['window:CabinetWClass|']
                elif change=='focus':after['focus']='other'
                elif change=='selection':
                    after['selected']='other';after['icons']=[dict(id='other',x=200,y=190)]
                elif change=='output':after['output']='changed'
                else:
                    initial['visual_sample']=sample_frame(Image.new('RGB',(240,140),(20,70,120)))
                    after['visual_sample']=sample_frame(Image.new('RGB',(240,140),(240,240,240)))
                recorder=Recorder(SequenceObserver(initial,after),'o1')
                recorder.capture(dict(kind='click'),102.0,(200,190),101.0,self.target())
                self.assertNotIn('last_clicked',recorder.before)
                with self.assertRaisesRegex(ValueError,'другой объект|подтверждённый клик'):
                    recorder.capture(dict(kind='enter'),103.0)
                self.assertEqual(len(recorder.receipts),3)

    def test_inflight_poll_cannot_credit_enter_result_to_click(self):
        initial, _=self.observations()
        initial['features'].append('window:Progman|')
        initial['visual_sample']=sample_frame(Image.new('RGB',(240,140),(20,70,120)))
        opened=clone(initial);opened['captured_at']=104.0
        opened['features']=['window:CabinetWClass|']
        opened['visual_sample']=sample_frame(Image.new('RGB',(240,140),(240,240,240)))
        observer=SequenceObserver(initial,initial,opened,opened)
        recorder=Recorder(observer,'o1')
        recorder.capture(dict(kind='click'),102.0,(200,190),101.0,self.target())
        click_before=clone(recorder.receipts[-1])
        def during_scan(**_kwargs):
            recorder.begin_action(103.0)
            return clone(opened)
        with patch.object(observer,'observe',side_effect=during_scan):
            self.assertFalse(recorder.poll())
        self.assertEqual(recorder.receipts[-1],click_before)
        recorder.capture(dict(kind='enter'),103.2,None,103.0)
        record=recorder.finish()
        self.assertFalse(record['receipts'][-2]['effect_observed'])
        self.assertTrue(record['receipts'][-1]['effect_observed'])
        self.assertEqual(record['receipts'][-1]['before']['features'],['window:Progman|'])

    def test_next_press_before_first_post_click_frame_rejects_demonstration(self):
        initial, _=self.observations()
        observer=SequenceObserver(initial,initial)
        recorder=Recorder(observer,'o1')
        def during_scan(**kwargs):
            recorder.begin_action(102.2)
            result=clone(initial);result['captured_at']=102.3
            return result
        with patch.object(observer,'observe',side_effect=during_scan):
            with self.assertRaisesRegex(ValueError,'до исходного наблюдения'):
                recorder.capture(dict(kind='click'),102.0,(200,190),101.0,self.target())

    def test_poll_rejects_a_pre_press_frame_with_post_press_accessibility(self):
        initial, _=self.observations()
        observer=SequenceObserver(initial,initial)
        recorder=Recorder(observer,'o1')
        recorder.capture(dict(kind='click'),102.0,(200,190),101.0,self.target())
        prior=clone(recorder.receipts[-1])
        raw=dict(icons=[],cursor=dict(x=200,y=190),captured_at=102.5,
                 frame=3,session='s',monitor={})
        def read_uia():
            recorder.begin_action(103.0)
            return dict(focus='',output='',readable=False,own=False,reason='',window='window:CabinetWClass|')
        real_observer=DesktopObserver(SimpleNamespace(request=lambda **_:raw),SimpleNamespace(read=read_uia))
        with patch.object(observer,'observe',side_effect=real_observer.observe), \
             patch('kolos_states.desktop.time.time',return_value=104.0):
            self.assertFalse(recorder.poll())
        self.assertEqual(recorder.receipts[-1],prior)

    def test_guard_failure_names_step_action_and_missing_object(self):
        initial, _=self.observations()
        record=dict(query='o1',receipts=[dict(id='demo:0',ok=True,
            action=dict(kind='enter',object='glaz.56'),before=initial,after=initial)])
        with self.assertRaisesRegex(ValueError,r'Шаг 1 \(enter\): Не видна иконка glaz.56'):
            validate_record(record)

    def test_missing_focus_reports_the_accessibility_cause_without_recording_key(self):
        initial, _=self.observations()
        initial['reason']='UI Automation: не установлена зависимость'
        recorder=Recorder(SequenceObserver(initial),'Впиши 1')
        with self.assertRaisesRegex(ValueError,r'Шаг 1 \(key\): Нет наблюдаемого фокуса ввода: UI Automation'):
            recorder.capture(dict(kind='key',value='1'),103.0)
        self.assertEqual(recorder.receipts,[])

    def test_keyboard_hook_reports_press_before_release_is_queued(self):
        terminal=Terminal.__new__(Terminal)
        terminal.recording=True;terminal.recorder=Mock();terminal.queue=queue.Queue()
        terminal.observer=SimpleNamespace(accessibility=SimpleNamespace(read=lambda:dict(own=False)))
        names=('f9','ctrl','ctrl_l','ctrl_r','alt','alt_l','alt_r','esc','shift','shift_l','shift_r','enter')
        keyboard=SimpleNamespace(Key=SimpleNamespace(**{n:n for n in names}),Listener=Mock())
        terminal._keyboard_listener(keyboard)
        callbacks=keyboard.Listener.call_args.kwargs
        with patch('kolos_states.cli.time.time',side_effect=[103.0,103.2]):
            callbacks['on_press']('enter')
            terminal.recorder.begin_action.assert_called_once_with(103.0)
            self.assertTrue(terminal.queue.empty())
            callbacks['on_release']('enter')
        self.assertEqual(terminal.queue.get_nowait(),('record-action',({'kind':'enter'},103.2,None,103.0)))

    @staticmethod
    def keyboard_callbacks(terminal):
        """Expose listener callbacks without installing a global keyboard hook."""
        names=('f9','ctrl','ctrl_l','ctrl_r','alt','alt_l','alt_r','esc','shift','shift_l','shift_r','enter')
        keyboard=SimpleNamespace(Key=SimpleNamespace(**{n:n for n in names}),Listener=Mock())
        terminal._keyboard_listener(keyboard)
        return keyboard.Listener.call_args.kwargs

    def test_numpad_digits_without_char_are_recorded_with_press_time(self):
        for digit in range(10):
            with self.subTest(digit=digit):
                terminal=Terminal.__new__(Terminal)
                terminal.recording=True;terminal.recorder=Mock();terminal.queue=queue.Queue()
                terminal.observer=SimpleNamespace(accessibility=SimpleNamespace(read=lambda:dict(own=False)))
                callbacks=self.keyboard_callbacks(terminal)
                with patch('kolos_states.cli.time.time',side_effect=[103.0,103.2]):
                    callbacks['on_press'](PhysicalKey(char=None,vk=0x60+digit))
                    callbacks['on_release'](PhysicalKey(char=None,vk=0x60+digit))
                terminal.recorder.begin_action.assert_called_once_with(103.0)
                self.assertEqual(terminal.queue.get_nowait(),
                    ('record-action',({'kind':'key','value':str(digit)},103.2,None,103.0)))

    def test_key_release_uses_the_symbol_and_identity_from_press(self):
        terminal=Terminal.__new__(Terminal)
        terminal.recording=True;terminal.recorder=Mock();terminal.queue=queue.Queue()
        terminal.observer=SimpleNamespace(accessibility=SimpleNamespace(read=lambda:dict(own=False)))
        callbacks=self.keyboard_callbacks(terminal)
        with patch('kolos_states.cli.time.time',side_effect=[103.0,103.2]):
            callbacks['on_press'](PhysicalKey(char='!',vk=0x31))
            callbacks['on_release'](PhysicalKey(char='1',vk=0x31))
        self.assertEqual(terminal.queue.get_nowait(),
            ('record-action',({'kind':'key','value':'!'},103.2,None,103.0)))

    def test_numpad_navigation_and_ctrl_combinations_are_still_rejected(self):
        for key,ctrl in ((PhysicalKey(char=None,vk=0x23),False),
                         (PhysicalKey(char=None,vk=0x61),True)):
            with self.subTest(vk=key.vk,ctrl=ctrl):
                terminal=Terminal.__new__(Terminal)
                terminal.recording=True;terminal.recorder=Mock();terminal.queue=queue.Queue()
                terminal.observer=SimpleNamespace(accessibility=SimpleNamespace(read=lambda:dict(own=False)))
                callbacks=self.keyboard_callbacks(terminal)
                if ctrl:callbacks['on_press']('ctrl')
                callbacks['on_press'](key);callbacks['on_release'](key)
                self.assertEqual(terminal.queue.get_nowait()[0],'bad-record')

    def test_reset_discards_the_recording_and_pending_mouse_press(self):
        terminal=Terminal.__new__(Terminal)
        terminal.abort=threading.Event();terminal.pause=threading.Event()
        terminal.engine=StateEngine();terminal.store=Mock();terminal.receipt=object()
        terminal.running=True;terminal.recording=True;terminal.recorder=Mock()
        terminal.record=object();terminal.staged=object();terminal.schedule=('record',0)
        terminal.language_auto=True;terminal._click_down_at=100;terminal._click_down_target=object()
        terminal.command('/reset')
        self.assertFalse(terminal.recording)
        for attr in ('recorder','record','staged','schedule','_click_down_at','_click_down_target'):
            self.assertIsNone(getattr(terminal,attr),attr)

    def test_release_from_cancelled_recording_does_not_enter_next_recording(self):
        terminal=Terminal.__new__(Terminal)
        terminal.recording=True;terminal.recorder=Mock();terminal.queue=queue.Queue()
        terminal.observer=SimpleNamespace(accessibility=SimpleNamespace(read=lambda:dict(own=False)))
        callbacks=self.keyboard_callbacks(terminal)
        callbacks['on_press']('enter')
        terminal.recorder=Mock()
        callbacks['on_release']('enter')
        self.assertTrue(terminal.queue.empty())

    def test_mouse_hook_closes_previous_interval_at_press_and_keeps_target(self):
        terminal=Terminal.__new__(Terminal)
        terminal.recording=True;terminal.recorder=Mock();terminal.queue=queue.Queue()
        terminal._click_down_at=None;terminal._click_down_target=None
        terminal.observer=SimpleNamespace(accessibility=SimpleNamespace(read=lambda:dict(own=False)))
        mouse=SimpleNamespace(Button=SimpleNamespace(left='left'),Listener=Mock())
        terminal._mouse_listener(mouse)
        clicked=mouse.Listener.call_args.kwargs['on_click'];target=self.target()
        with patch('kolos_states.cli.time.time',side_effect=[101.0,102.0]), \
             patch('kolos_states.cli.read_last_confirmed_target',return_value=target) as read:
            clicked(200,190,'left',True)
            terminal.recorder.begin_action.assert_called_once_with(101.0)
            read.assert_called_once_with(max_age_sec=10,now=101.0)
            self.assertTrue(terminal.queue.empty())
            clicked(200,190,'left',False)
        self.assertEqual(terminal.queue.get_nowait(),
                         ('record-action',({'kind':'click'},102.0,(200,190),101.0,target)))

    def test_replay_click_can_proceed_to_enter_without_selection_change(self):
        initial, _ = self.observations()
        initial['icons'] = [{'id': 'glaz.56', 'x': 200, 'y': 190, 'bbox': [190, 180, 210, 200]}]
        initial['features'].append('visible:glaz.56')
        current = clone(initial)
        class Observer:
            def observe(self, **_kwargs):return fresh_copy(current)
        def send(action):
            if action['kind']=='enter':
                current['features'] = ['focus:', 'selected:', 'visible:window']
        motor = SimpleNamespace(send=Mock(side_effect=send))
        adapter = DesktopAdapter(Observer(), motor, allow=lambda:True)
        click = adapter.execute({'id':'click','action':{'kind':'click','object':'glaz.56'}}, assume_click=True)
        self.assertEqual(click['after']['last_clicked'], 'glaz.56')
        enter = adapter.execute({'id':'enter','action':{'kind':'enter','object':'glaz.56'}})
        self.assertTrue(enter['ok'])
        self.assertEqual(motor.send.call_count, 2)

    def test_replay_enter_without_actual_change_is_not_confirmed(self):
        initial, _ = self.observations()
        initial['visual_sample']=sample_frame(Image.new('RGB',(240,140),(20,70,120)))
        initial['icons'] = [{'id':'glaz.56','x':200,'y':190,'bbox':[190,180,210,200]}]
        initial['features'].append('visible:glaz.56')
        observer=SimpleNamespace(observe=lambda **_kwargs:fresh_copy(initial))
        motor=SimpleNamespace(send=Mock())
        adapter=DesktopAdapter(observer,motor,allow=lambda:True)
        adapter.execute({'id':'click','action':{'kind':'click','object':'glaz.56'}},assume_click=True)
        adapter.timeout=.001
        with self.assertRaises(Indeterminate):
            adapter.execute({'id':'enter','action':{'kind':'enter','object':'glaz.56'}},visual_ack=True)
        self.assertEqual(motor.send.call_count,2)

    def test_unobserved_click_and_observed_enter_can_be_learned_and_replayed(self):
        initial, _ = self.observations()
        initial['icons'] = [{'id':'glaz.56','x':200,'y':190,'bbox':[190,180,210,200]}]
        initial['features'].append('visible:glaz.56')
        initial['visual_sample'] = sample_frame(Image.new('RGB',(240,140),(20,70,120)))
        opened = clone(initial)
        opened['features']=['visible:unrecognized-window'];opened['icons']=[]
        opened['visual_sample'] = sample_frame(Image.new('RGB',(240,140),(240,240,240)))
        recorder = Recorder(SequenceObserver(initial, initial, opened), 'открой')
        recorder.capture({'kind':'click'}, 102.0, (200, 190), 101.0, self.target())
        recorder.capture({'kind':'enter'}, 103.0)
        engine = StateEngine()
        record=recorder.finish()
        self.assertEqual(record['receipts'][-1]['verified_by'],'visual-change')
        engine.learn(record)
        current = clone(initial)
        class Observer:
            def observe(self, **_kwargs):return fresh_copy(current)
        def send(action):
            if action['kind']=='move':current['cursor']={'x':action['x'],'y':action['y']}
            if action['kind']=='enter':
                current['visual_sample']=opened['visual_sample']
                current['features']=['focus:','selected:','visible:unrecognized-window']
        motor = SimpleNamespace(send=Mock(side_effect=send))
        adapter = DesktopAdapter(Observer(), motor, allow=lambda:True)
        engine.start('открой', clone(current))
        for _ in range(300):
            if engine.model['status'] in ('complete','failed','blocked','timeout','unknown'):break
            engine.tick()
            pending=engine.model['pending']
            if not pending:continue
            step=engine.node(pending.get('step'))
            post=engine.node(step['post']) if step and step.get('post') else None
            assumed=bool(post and pending['action']['kind']=='click' and
                         step.get('dispatch_only'))
            visual_ack=bool(step and step.get('visual_ack'))
            expected=post['key'] if post and pending['action']['kind'] in ('click','enter') and not assumed and not visual_ack else None
            receipt=adapter.execute(pending,expected=expected,assume_click=assumed,visual_ack=visual_ack)
            engine.accept_receipt(receipt)
        self.assertEqual(engine.model['status'], 'complete', engine.model['message'])
        self.assertEqual([c.args[0]['kind'] for c in motor.send.call_args_list], ['move','click','enter'])

    def test_visual_enter_requires_two_agreeing_fresh_frames(self):
        initial, _=self.observations()
        initial['icons'] = [{'id':'glaz.56','x':200,'y':190,'bbox':[190,180,210,200]}]
        initial['features'].append('visible:glaz.56')
        initial['visual_sample']=sample_frame(Image.new('RGB',(240,140),(20,70,120)))
        opened=clone(initial)
        opened['visual_sample']=sample_frame(Image.new('RGB',(240,140),(240,240,240)))
        first=clone(opened);first['features']=['focus:','selected:','visible:glaz.9']
        second=clone(opened);second['features']=['visible:glaz.10']
        recorder=Recorder(SequenceObserver(initial,initial,first,second,second),'открой')
        recorder.capture({'kind':'click'},102.0,(200,190),101.0,self.target())
        recorder.capture({'kind':'enter'},103.0)
        self.assertEqual(recorder.finish()['receipts'][-1]['verified_by'],'visual-change')
        self.assertEqual(recorder.receipts[-1]['after']['features'],second['features'])

    def test_terminal_replays_learned_command_after_a_transient_missing_scan(self):
        initial, _ = self.observations()
        initial['icons'] = [{'id':'glaz.56','x':200,'y':190,'bbox':[190,180,210,200]}]
        initial['features'].append('visible:glaz.56')
        initial['visual_sample']=sample_frame(Image.new('RGB',(240,140),(20,70,120)))
        opened=clone(initial)
        opened['visual_sample']=sample_frame(Image.new('RGB',(240,140),(240,240,240)))
        recorder=Recorder(SequenceObserver(initial,initial,opened),'o1')
        recorder.capture({'kind':'click'},102.0,(200,190),101.0,self.target())
        recorder.capture({'kind':'enter'},103.0)
        record=recorder.finish()
        for lose_frame in (False,True):
            with self.subTest(lose_frame=lose_frame):
                engine=StateEngine();engine.learn(record);memory=persistent_graph(engine.model['memory'])
                current=clone(initial)
                current['icons'].append(dict(id='extra',x=700,y=500))
                current['features'].append('visible:extra')
                observer=SimpleNamespace(observe=lambda **_:fresh_copy(current))
                def send(a):
                    if a['kind']=='move':current['cursor']=dict(x=a['x'],y=a['y'])
                    if a['kind']=='enter':current['visual_sample']=opened['visual_sample']
                motor=Mock();motor.send.side_effect=send
                terminal=Terminal.__new__(Terminal)
                terminal.engine=engine;terminal.observer=observer
                terminal.adapter=DesktopAdapter(observer,motor,allow=lambda:True)
                terminal.receipt=None;terminal.store=Mock();terminal.running=True
                terminal.pause=threading.Event();terminal.language_auto=False
                engine.start('o1',current);lost=False
                with patch('builtins.print'):
                    for _ in range(100):
                        if not terminal.running:break
                        step=engine.node(engine.model['entry'])
                        if lose_frame and not lost and not engine.model['pending'] and step['action']['kind']=='check':
                            absent=clone(current)
                            absent['icons']=[i for i in absent['icons'] if i['id']!='glaz.56']
                            absent['features'].remove('visible:glaz.56')
                            with patch.object(observer,'observe',return_value=absent):terminal.tick_once()
                            self.assertIsNotNone(engine.model['plan']);lost=True
                        else:terminal.tick_once()
                self.assertEqual(engine.model['status'],'complete',engine.model['message'])
                self.assertEqual([c.args[0]['kind'] for c in motor.send.call_args_list],['move','click','enter'])
                self.assertEqual(persistent_graph(engine.model['memory']),memory)
                self.assertEqual(lost,lose_frame)

    def test_terminal_observation_keeps_click_evidence_only_while_state_matches(self):
        initial, _ = self.observations()
        initial['icons']=[dict(id='glaz.56',x=200,y=190)]
        initial['features'].extend(['visible:glaz.56','window:Progman|'])
        initial['visual_sample']=sample_frame(Image.new('RGB',(240,140),(20,70,120)))
        for change in ('output','focus','window','selection','image','own_focus'):
            with self.subTest(change=change):
                current=clone(initial)
                observer=SimpleNamespace(observe=lambda **_:fresh_copy(current))
                adapter=DesktopAdapter(observer,Mock(),allow=lambda:True)
                adapter.execute(dict(id='click',action=dict(kind='click',object='glaz.56')),assume_click=True)
                self.assertEqual(adapter.observe()['last_clicked'],'glaz.56')
                if change=='output':current['output']='changed'
                elif change=='focus':
                    current['focus']='other';current['features'].append('focus:other')
                elif change=='window':
                    current['features'].remove('window:Progman|');current['features'].append('window:CabinetWClass|')
                elif change=='selection':current['selected']='other'
                elif change=='image':current['visual_sample']=sample_frame(Image.new('RGB',(240,140),(240,240,240)))
                else:current['own_focus']=True
                self.assertNotIn('last_clicked',adapter.observe())
                current=clone(initial)
                self.assertNotIn('last_clicked',adapter.observe())

    def test_visual_change_requires_a_large_area_and_masks_glaz_window(self):
        base=Image.new('RGB',(240,140),(30,70,110))
        small=base.copy();ImageDraw.Draw(small).rectangle((4,4,12,12),fill=(245,245,245))
        opened=Image.new('RGB',(240,140),(245,245,245))
        before={'monitor':{},'visual_sample':sample_frame(base)}
        self.assertFalse(visual_changed(before,{'monitor':{},'visual_sample':sample_frame(small)}))
        self.assertTrue(visual_changed(before,{'monitor':{},'visual_sample':sample_frame(opened)}))
        monitor={'left':0,'top':0,'width':240,'height':140}
        own=(0,0,240,140)
        self.assertEqual(sample_frame(base,monitor=monitor,own_rect=own),
                         sample_frame(opened,monitor=monitor,own_rect=own))

    def test_foreground_window_change_is_observable_after_enter(self):
        scan=SimpleNamespace(request=lambda **_kwargs:dict(icons=[],cursor={'x':200,'y':190},frame=1,
            captured_at=100.0,monitor={},session='session',
            visual_sample=sample_frame(Image.new('RGB',(240,140),(20,70,120)))))
        state={'window':'window:Progman|'}
        uia=SimpleNamespace(read=lambda:dict(field_bbox=None,selected_bbox=None,focus='',output='',
            readable=False,own=False,reason='',window=state['window']))
        observer=DesktopObserver(scan,uia)
        before=observer.observe()
        self.assertEqual(len(before['visual_sample']), 2016)
        state['window']='window:CabinetWClass|'
        after=observer.observe()
        self.assertNotEqual(before['features'],after['features'])

    def test_queued_actions_after_failed_capture_are_discarded(self):
        terminal = Terminal.__new__(Terminal)
        terminal.recorder = SimpleNamespace(invalid='Клик не подтверждён', capture=Mock(), finish=Mock())
        terminal.record = None
        terminal.recording = False
        terminal._record_event('record-action', ({'kind': 'enter'}, 103.0, None))
        terminal._record_event('stop-record', None)
        terminal.recorder.capture.assert_not_called()
        terminal.recorder.finish.assert_not_called()
        self.assertIsNone(terminal.record)


ROOT = Path(__file__).resolve().parents[2]
spec = spec_from_file_location('states_bridge_recorder_test', ROOT / 'Glaz' / 'states_bridge.py')
assert spec and spec.loader
bridge_module = module_from_spec(spec)
spec.loader.exec_module(bridge_module)
GlazStatesBridge = bridge_module.GlazStatesBridge


class BridgeHoverTests(unittest.TestCase):
    def test_bridge_sends_a_sample_of_its_capture_frame(self):
        bridge=GlazStatesBridge.__new__(GlazStatesBridge)
        bridge.app=SimpleNamespace(_compute_peaks_and_objects=lambda *_args:SimpleNamespace(objects=[]))
        frame=Image.new('RGB',(240,140),(30,70,110))
        job=dict(monitor={'left':0,'top':0,'width':240,'height':140},own_rect=[300,0,500,140])
        result=bridge._compute(frame,30,False,job)
        self.assertEqual(result['visual_sample'],sample_frame(frame))

    def publish(self, rows, recognized=True, running=False, cursor=(50,50), signatures=None, events=None):
        signatures=signatures or {}
        app = SimpleNamespace(
            _states_controls_owned=running,
            _last_hovered_object_id=7,
            _object_id_to_refined={7: 23} if recognized else {},
            _detected_objects=[SimpleNamespace(id=7, bbox=(40, 40, 60, 60))],
            _object_already_recognized=recognized,
            _zoomed_signature_to_ids=signatures,
            _signature_match_max_pct=.2,
            _objects_repo=SimpleNamespace(find_similar=lambda sig, _known, **_: (sig,0) if sig in signatures else None),
            _event_bus=SimpleNamespace(emit=events or Mock()),
        )
        bridge = GlazStatesBridge.__new__(GlazStatesBridge)
        bridge.app = app
        bridge.enabled = True
        bridge.closed = False
        bridge.session = 'session'
        bridge.path = Path('unused')
        result = dict(request='request', captured_at=time.time(), frame=1,
                      monitor=dict(left=0, top=0, width=100, height=100), rows=rows)
        published = []
        with patch.dict(sys.modules, {'utils': SimpleNamespace(get_cursor_pos=lambda: cursor)}), \
             patch.object(bridge_module, 'atomic_json', side_effect=lambda _path, data: published.append(data)):
            bridge._publish(result)
        return published[0]['icons']

    def test_fresh_scan_does_not_substitute_stale_hover_id(self):
        icons = self.publish([((40, 40, 60, 60), ())])
        self.assertEqual(icons, [])

    def test_hover_id_is_not_used_for_ambiguous_fresh_geometry(self):
        icons = self.publish([((40, 40, 60, 60), ()), ((45, 45, 55, 55), ())])
        self.assertEqual(icons, [])

    def test_unconfirmed_hover_does_not_create_known_object(self):
        self.assertEqual(self.publish([((40, 40, 60, 60), ())], recognized=False), [])

    def test_running_scan_does_not_reuse_previous_hover_id(self):
        self.assertEqual(self.publish([((40, 40, 60, 60), ())], running=True), [])

    def test_running_duplicate_56_under_cursor_reaches_executor(self):
        # Actual signature and rectangles from the reported o1 session.
        signature=(7,15,17,18,24,25,31,33,34,38,43,44,45,46)
        rows=[((14,11,60,56),signature),((1838,112,1884,157),signature),
              ((1838,819,1884,864),signature),((0,0,76,104),())]
        icons=self.publish(rows,recognized=False,running=True,cursor=(37,37),signatures={signature:[56]})
        self.assertFalse(icons[0]['ambiguous'])
        self.assertTrue(icons[1]['ambiguous'])
        raw=dict(icons=icons,cursor=dict(x=37,y=37),frame=2,session='s',captured_at=time.time(),
                 monitor=dict(left=0,top=0,width=1920,height=1080))
        scan=SimpleNamespace(request=lambda **_:fresh_copy(raw))
        uia=SimpleNamespace(read=lambda:dict(focus='',output='',readable=False,own=False,reason=''))
        observer=DesktopObserver(scan,uia)
        self.assertEqual([i['id'] for i in observer.observe()['icons']],['glaz.56'])
        motor=Mock();adapter=DesktopAdapter(observer,motor,allow=lambda:True)
        checked=adapter.execute(dict(id='check-56',action=dict(kind='check',object='glaz.56')))
        self.assertTrue(checked['ok']);motor.send.assert_not_called()
        clicked=adapter.execute(dict(id='click-56',action=dict(kind='click',object='glaz.56')),assume_click=True)
        self.assertTrue(clicked['ok']);motor.send.assert_called_once_with(dict(kind='click',object='glaz.56'))

    def test_duplicates_remain_ambiguous_when_cursor_is_elsewhere_or_hits_overlap(self):
        signature=(1,2)
        for cursor, rows in [((80,80),[((14,11,60,56),signature),((100,110,160,156),signature)]),
                             ((37,37),[((14,11,60,56),signature),((35,20,80,50),signature)]),
                             ((37,37),[((14,11,60,56),signature),((100,110,160,156),signature),((35,20,80,50),(3,4))])]:
            with self.subTest(cursor=cursor,rows=rows):
                icons=self.publish(rows,recognized=False,running=True,cursor=cursor,signatures={signature:[56],(3,4):[57]})
                self.assertTrue(all(icon['ambiguous'] for icon in icons))

    def test_unrecognized_contours_do_not_cancel_the_single_recognized_pointer_target(self):
        signature=(1,2)
        for bbox in ((20,20,50,50),(35,20,80,50),(0,0,76,104)):
            with self.subTest(bbox=bbox):
                icons=self.publish([((14,11,60,56),signature),((1838,112,1884,157),signature),(bbox,())],
                    recognized=False,running=True,cursor=(37,37),signatures={signature:[56]})
                self.assertFalse(icons[0]['ambiguous'])
                self.assertTrue(icons[1]['ambiguous'])

    def test_equal_recognized_bounds_do_not_authorize_a_click(self):
        signature=(1,2)
        for extra in (((14,11,60,56),signature),((14,11,60,56),(3,4))):
            with self.subTest(extra=extra):
                icons=self.publish([((14,11,60,56),signature),extra],recognized=False,
                    running=True,cursor=(37,37),signatures={signature:[56],(3,4):[57]})
                self.assertTrue(all(icon['ambiguous'] for icon in icons))

    def test_running_scan_reports_fresh_hover_id_in_the_object_log(self):
        events=Mock()
        self.publish([((14,11,60,56),(1,2))],recognized=False,running=True,cursor=(37,37),
                     signatures={(1,2):[56]},events=events)
        events.assert_called_once_with('object_recognized',refined_id=56,is_new=False)

    def test_duplicate_recognition_selects_nearest_but_requires_pointing_before_click(self):
        signature=(1,2)
        rows=[((14,11,60,56),signature),((1838,112,1884,157),signature),((1838,819,1884,864),signature)]
        for cursor in ((2716,1039),(37,37)):
            with self.subTest(cursor=cursor):
                icons=self.publish(rows,recognized=False,running=True,cursor=cursor,signatures={signature:[56]})
                raw=dict(icons=icons,cursor=dict(zip(('x','y'),cursor)),frame=1,session='s',
                         captured_at=time.time(),monitor={})
                scan=SimpleNamespace(request=lambda **_:fresh_copy(raw))
                uia=SimpleNamespace(read=lambda:dict(focus='',output='',readable=False,own=False,reason=''))
                observer=DesktopObserver(scan,uia);obs=observer.observe()
                action=dict(kind='click',object='glaz.56')
                if cursor==(37,37):
                    self.assertEqual(guard(obs,action),'')
                    self.assertNotIn('glaz.56',obs['object_issues'])
                else:
                    self.assertEqual([(i['x'],i['y']) for i in obs['icons']],[(1861,842)])
                    self.assertNotIn('glaz.56',obs['object_issues'])
                    self.assertEqual(guard(obs,action),'Под курсором не glaz.56')
                    motor=Mock()
                    receipt=DesktopAdapter(observer,motor,allow=lambda:True).execute(dict(id='click',action=action))
                    self.assertFalse(receipt['ok']);motor.send.assert_not_called()

    def test_nearest_selection_excludes_own_window_and_text_field(self):
        """A nearer ineligible hit cannot displace a valid desktop target."""
        signature=(1,2)
        icons=self.publish([((14,11,60,56),signature),((100,110,160,156),signature),
                            ((200,210,260,256),signature)],running=True,cursor=(80,80),
                           signatures={signature:[56]})
        raw=dict(icons=icons,cursor=dict(x=80,y=80),frame=1,session='s',
                 captured_at=time.time(),monitor={},own_rect=[0,0,70,70])
        scan=SimpleNamespace(request=lambda **_:fresh_copy(raw))
        uia=SimpleNamespace(read=lambda:dict(focus='',output='',readable=False,own=False,
                                            reason='',field_bbox=[90,100,170,170]))
        observed=DesktopObserver(scan,uia).observe()
        self.assertEqual([i['bbox'] for i in observed['icons']],[[200,210,260,256]])

    def test_selection_is_observed_even_when_another_copy_is_nearer_to_cursor(self):
        """Selection evidence for Enter remains independent of nearest targeting."""
        signature=(1,2)
        icons=self.publish([((14,11,60,56),signature),((100,110,160,156),signature)],
                           running=True,cursor=(80,80),signatures={signature:[56]})
        raw=dict(icons=icons,cursor=dict(x=80,y=80),frame=1,session='s',
                 captured_at=time.time(),monitor={})
        scan=SimpleNamespace(request=lambda **_:fresh_copy(raw))
        uia=SimpleNamespace(read=lambda:dict(focus='',output='',readable=False,own=False,
                                            reason='',selected_bbox=[100,110,160,156]))
        observed=DesktopObserver(scan,uia).observe()
        self.assertEqual(observed['icons'][0]['bbox'],[14,11,60,56])
        self.assertEqual(observed['selected'],'glaz.56')

    def test_overlapping_targets_still_require_a_confirmed_pointer_instance(self):
        """Interchangeable separated copies do not permit unresolved overlaps."""
        signature=(1,2)
        icons=self.publish([((14,11,60,56),signature),((35,20,80,50),signature)],
                           running=True,cursor=(37,37),signatures={signature:[56]})
        raw=dict(icons=icons,cursor=dict(x=37,y=37),frame=1,session='s',
                 captured_at=time.time(),monitor={})
        scan=SimpleNamespace(request=lambda **_:fresh_copy(raw))
        uia=SimpleNamespace(read=lambda:dict(focus='',output='',readable=False,own=False,reason=''))
        observer=DesktopObserver(scan,uia); motor=Mock()
        receipt=DesktopAdapter(observer,motor,allow=lambda:True).execute(
            dict(id='overlap',action=dict(kind='click',object='glaz.56')))
        self.assertFalse(receipt['ok']);self.assertIn('пересечение',receipt['reason'])
        motor.send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
