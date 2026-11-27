"""Native teacher widget contract; all clicks are synthetic events on a test image."""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from Glaz.image_processor import ImageProcessor, LineBasedDetector
from kolos_states.core import StateEngine
from kolos_states.cli import Terminal
from kolos_states.ipc import atomic_json, read_json
from kolos_states.perception.console import _commit, configure_query
from tests.perception.fixtures import scene, learned
from tests.perception.test_integration import motor_lesson


class TeacherContractTests(unittest.TestCase):
    def test_failed_binding_rolls_back_the_entire_teaching_transaction(self) -> None:
        engine=StateEngine(); _,shown=learned(engine)
        terminal=SimpleNamespace(engine=engine,running=False,recording=False,schedule=None,store=Mock())
        from kolos_states.protocol import clone
        before=clone(engine.model)
        with self.assertRaises(ValueError):
            _commit(terminal,dict(id='bad',lesson=shown,query='not learned',object='A'))
        self.assertEqual(engine.model,before)
        terminal.store.save.assert_not_called()
        self.assertFalse(terminal.visual_teaching['ok'])

    def test_busy_teacher_gets_an_explicit_failure_ack(self) -> None:
        terminal=SimpleNamespace(engine=StateEngine(),running=True,recording=False,schedule=None,store=Mock())
        with self.assertRaises(ValueError):_commit(terminal,dict(id='busy'))
        self.assertEqual(terminal.visual_teaching['id'],'busy')
        self.assertFalse(terminal.visual_teaching['ok'])

    def test_save_failure_rolls_back_memory_and_never_reports_success(self) -> None:
        from kolos_states.protocol import clone
        engine=StateEngine();_,shown=learned(engine);before=clone(engine.model)
        terminal=SimpleNamespace(engine=engine,running=False,recording=False,schedule=None,store=Mock())
        terminal.store.save.side_effect=PermissionError('memory.json is locked')
        with self.assertRaises(PermissionError):_commit(terminal,dict(id='locked',lesson=shown))
        self.assertEqual(engine.model,before);self.assertFalse(terminal.visual_teaching['ok'])
        terminal.store.save.assert_called_once_with(engine,preserve_attempt=True)

    def test_bound_query_switches_to_visual_observer_without_loading_uia(self) -> None:
        from kolos_states.perception.learning import bind
        engine=StateEngine();engine.learn(motor_lesson());target,_=learned(engine);bind(engine,'o1','A',target)
        inaccessible=Mock();inaccessible.ensure_available.side_effect=AssertionError('UIA called')
        terminal=SimpleNamespace(engine=engine,observer=SimpleNamespace(accessibility=inaccessible),args=SimpleNamespace(glaz_pid=0))
        configure_query(terminal,'o1')
        terminal.observer.accessibility.ensure_available()
        self.assertTrue(terminal.visual_only)
        inaccessible.ensure_available.assert_not_called()


@unittest.skipUnless(sys.platform=='win32' and os.environ.get('KOLOS_VISUAL_UI_SMOKE')=='1',
                     'Opt-in own Tk teacher window; no physical mouse actions')
class TeacherWindowTests(unittest.TestCase):
    def test_snapshot_selection_teaches_through_real_terminal_and_ack(self) -> None:
        import tkinter as tk
        from Glaz.perception.dialog import VisualTeacher
        root=tk.Tk();root.withdraw()
        try:
            with tempfile.TemporaryDirectory() as directory:
                self._exercise(root,Path(directory),VisualTeacher)
        finally:root.destroy()

    def _exercise(self, root: object, directory: Path, teacher_type: object) -> None:
        terminal=Terminal(SimpleNamespace(ipc=str(directory),session='teacher',memory=str(directory/'memory'),glaz_pid=os.getpid()))
        try:
            terminal.engine.learn(motor_lesson());terminal.publish()
            frame,boxes,labels=scene();sent=[]
            def send(text):
                sent.append(text);terminal.command(text);terminal.publish()
            def detect(image,threshold,invert):
                return SimpleNamespace(objects=LineBasedDetector().detect(ImageProcessor.detect_color_peaks(image,threshold,invert)))
            app=SimpleNamespace(root=root,_states_bridge=SimpleNamespace(path=directory,session='teacher'),
                _states_frame=(frame,time.time(),{}),capture=SimpleNamespace(is_capturing=True),
                peaks_threshold=SimpleNamespace(get=lambda:40),peaks_invert=SimpleNamespace(get=lambda:False),
                _compute_peaks_and_objects=detect,_states_send=send)
            win=teacher_type(app);win.win.withdraw();win._snapshot();root.update()
            from kolos_states.perception.help import VISUAL_HELP
            with patch('Glaz.perception.dialog.messagebox.showinfo') as help_box:
                win._help()
                help_box.assert_called_once_with('Как обучить значок и подпись',VISUAL_HELP,parent=win.win)
            win._press(SimpleNamespace(x=45*win.scale,y=50*win.scale))
            self.assertIn('Обведите его подпись',win.message.get())
            l,t,r,b=labels[0];win._press(SimpleNamespace(x=l*win.scale,y=t*win.scale))
            win._release(SimpleNamespace(x=r*win.scale,y=b*win.scale))
            win.query.set('o1');win._query_changed();win._save();win._ack()
            self.assertTrue(terminal.visual_teaching['ok']);self.assertEqual(len(sent),1)
            self.assertTrue(sent[0].startswith('/visual-teach-file visual-lesson-'))
            self.assertIsNone(terminal.adapter);self.assertFalse(terminal.running)
            self.assertFalse(win.pending);self.assertTrue(win.target.get().startswith('n'))
            win._target_changed();self.assertIn('Дополнительный вид',win.message.get())
            win.win.destroy()
        finally:terminal.store.close()


if __name__=='__main__':unittest.main()
