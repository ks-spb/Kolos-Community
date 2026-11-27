"""Opt-in recording and recombination in a separate temporary Notepad document."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest

from kolos_states.accessibility import Accessibility
from kolos_states.core import StateEngine
from kolos_states.desktop import DesktopAdapter, WindowsMotor
from kolos_states.protocol import persistent_graph
from kolos_states.recorder import Recorder


class NotepadObserver:
    """Supply real UIA observations; this test has no desktop icon recognition."""
    def __init__(self, window_handle: int):
        self.accessibility=Accessibility();self.window_handle=window_handle;self.version=0

    def observe(self, **_kwargs) -> dict:
        """Keep every key constrained to the test document's focused editor."""
        import uiautomation as auto
        value=self.accessibility.read();top=auto.GetForegroundControl()
        if top is None or top.NativeWindowHandle!=self.window_handle:
            raise RuntimeError('Фокус покинул тестовый Блокнот; ввод отменён')
        self.version+=1;stamp=time.time()
        return dict(icons=[],features=['focus:'+value['focus'],value['window']],selected='',
            focus=value['focus'],output=value['output'],readable=value['readable'],own_focus=value['own'],
            reason=value['reason'],cursor=dict(x=0,y=0),version=self.version,captured_at=stamp,observed_at=stamp)


@unittest.skipUnless(sys.platform=='win32' and os.environ.get('KOLOS_NOTEPAD_SMOKE')=='1',
                     'Opt-in native Notepad recording smoke')
class NotepadSmoke(unittest.TestCase):
    def record(self, observer: NotepadObserver, motor: WindowsMotor, value: str) -> dict:
        """Record actual keys and their independently read effects one at a time."""
        recorder=Recorder(observer,'Впиши '+value)
        self.assertTrue(recorder.before['readable'],recorder.before['reason'])
        for char in value:
            action=dict(kind='key',value=char);pressed=time.time()
            motor.send(action);recorder.capture(action,time.time(),pressed_at=pressed)
        return recorder.finish()

    def replay(self, engine: StateEngine, observer: NotepadObserver, value: str) -> None:
        """Let the engine choose keys of a new query in the observed document."""
        adapter=DesktopAdapter(observer,WindowsMotor(),allow=lambda:True)
        engine.start('Впиши '+value,observer.observe())
        for _ in range(400):
            if engine.model['status']=='complete':break
            engine.tick()
            pending=engine.model['pending']
            if pending:
                receipt=adapter.execute(pending,target_focus=engine.model['selectedCommand']['focus'])
                engine.accept_receipt(receipt)
        self.assertEqual(engine.model['status'],'complete',engine.model['message'])
        self.assertEqual(observer.observe()['output'],value)

    def test_real_notepad_records_two_lessons_and_types_new_order(self):
        import uiautomation as auto
        with tempfile.TemporaryDirectory(prefix='kolos-notepad-') as directory:
            document=Path(directory)/('kolos-focus-'+Path(directory).name+'.txt')
            document.write_text('',encoding='utf-8')
            launcher=subprocess.Popen(['notepad.exe',str(document)])
            window=auto.WindowControl(searchDepth=1,RegexName='.*'+re.escape(document.stem)+'.*')
            try:
                self.assertTrue(window.Exists(10,.2),'Тестовый документ не открылся')
                window.SetActive();editor=window.EditControl(searchDepth=8)
                self.assertTrue(editor.Exists(3,.2),'Не найден редактор Блокнота')
                editor.SetFocus();observer=NotepadObserver(window.NativeWindowHandle);motor=WindowsMotor()
                engine=StateEngine();engine.configure(plasticity=0)
                for value in ('12345','6789'):
                    editor.SendKeys('{Ctrl}a{Back}',waitTime=.1)
                    self.assertEqual(observer.observe()['output'],'')
                    engine.learn(self.record(observer,motor,value))
                learned=persistent_graph(engine.model['memory'])
                for target in ('4532','1346'):
                    editor.SendKeys('{Ctrl}a{Back}',waitTime=.1)
                    self.replay(engine,observer,target)
                self.assertEqual(len(engine.model['lessons']),2)
                self.assertEqual(persistent_graph(engine.model['memory']),learned)
            finally:
                if window.Exists(0):
                    window.SetActive();window.SendKeys('{Ctrl}s',waitTime=.3)
                    window.GetWindowPattern().Close()
                launcher.wait(timeout=5)


if __name__=='__main__':unittest.main()
