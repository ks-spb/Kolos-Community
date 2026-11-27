"""Own-window UI smoke. No physical input is sent to other applications."""
import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from test_object_concepts import waiting

@unittest.skipUnless(os.environ.get('KOLOS_CONCEPT_UI_SMOKE')=='1','Opt-in own Tk dialog only')
class DialogTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.root=tk.Tk();self.root.title('Kolos · проверка диалога');self.root.geometry('720x560+60+60')
        self.app=SimpleNamespace(root=self.root,_states_bridge=SimpleNamespace(session='session'),_states_send=Mock(),
                                 _screenshots_dir=Path(__file__).resolve().parents[2]/'Glaz'/'object_screenshots')
        e,w,a=waiting();self.q=e.model['objectQuestion']
        from PIL import Image, ImageDraw
        import tempfile
        self.images_dir=tempfile.TemporaryDirectory();self.app._screenshots_dir=Path(self.images_dir.name)
        image=Image.new('RGB',(50,50),'white');draw=ImageDraw.Draw(image)
        draw.line((15,15,35,35),fill='black',width=3);draw.line((15,35,35,15),fill='black',width=3)
        image.save(self.app._screenshots_dir/'object_63_zoomed.png')
        source=Image.new('RGB',(1000,800),'white');draw=ImageDraw.Draw(source)
        draw.rectangle((90,90,110,110),fill='#eeeeee');draw.line((94,94,106,106),fill='black',width=2);draw.line((94,106,106,94),fill='black',width=2)
        self.app._states_bridge._preview_frame=(source,self.q['captured_at'],self.q['monitor'])
    def tearDown(self):
        self.root.destroy();self.images_dir.cleanup()
    def test_window_layout_single_question_and_yes(self):
        from Glaz.concept_dialog import poll_question
        raw=dict(session='session',objectQuestion=self.q)
        poll_question(self.app,raw);self.root.update();window=self.app._object_question_dialog
        window.geometry('660x490+80+80');self.root.update()
        self.assertTrue(window.winfo_viewable());self.assertGreater(window.yes.winfo_width(),80)
        self.assertEqual(len(window.images),2)
        self.assertLess(window.yes.winfo_rooty()+window.yes.winfo_height(),window.winfo_rooty()+window.winfo_height())
        poll_question(self.app,raw);self.assertIs(self.app._object_question_dialog,window)
        destination=os.environ.get('KOLOS_CONCEPT_SCREENSHOT')
        if destination:
            from PIL import ImageGrab
            self.root.update();box=(window.winfo_rootx(),window.winfo_rooty(),window.winfo_rootx()+window.winfo_width(),window.winfo_rooty()+window.winfo_height())
            ImageGrab.grab(bbox=box).save(destination)
        with patch('Glaz.concept_dialog.restore_window',return_value=True):
            window.reply('yes');window.reply('yes')
        self.app._states_send.assert_called_once()
        payload=json.loads(self.app._states_send.call_args.args[0].split(' ',1)[1])
        self.assertEqual(payload,dict(id=self.q['id'],choice='yes'))
    def test_cancellation_closes_without_positive_answer(self):
        from Glaz.concept_dialog import poll_question
        poll_question(self.app,dict(session='session',objectQuestion=self.q));self.root.update()
        window=self.app._object_question_dialog
        poll_question(self.app,dict(session='session',objectQuestion=None))
        self.assertFalse(window.winfo_exists());self.app._states_send.assert_not_called()

if __name__=='__main__':unittest.main()
