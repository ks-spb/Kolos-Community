"""Focused-field evidence and dependency failures at the UI Automation boundary."""
import builtins
from contextlib import nullcontext
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from kolos_states.accessibility import Accessibility
from kolos_states.cli import Terminal


class AccessibilityTests(unittest.TestCase):
    def controls(self, value: str = '') -> tuple[SimpleNamespace, SimpleNamespace]:
        """Build an external window and its genuinely focused edit control."""
        rect=SimpleNamespace(left=10,top=20,right=310,bottom=70)
        top=SimpleNamespace(ProcessId=os.getpid()+100,ClassName='Notepad',AutomationId='',
                            NativeWindowHandle=7,ControlTypeName='WindowControl')
        control=SimpleNamespace(ControlTypeName='EditControl',AutomationId='editor',ClassName='EDIT',
            NativeWindowHandle=17,IsPassword=False,BoundingRectangle=rect,GetParentControl=lambda:top,
            GetSelectionItemPattern=lambda:None,GetTextPattern=lambda:None,
            GetValuePattern=lambda:SimpleNamespace(IsReadOnly=False,Value=value))
        return top,control

    def read(self, top: SimpleNamespace, control: SimpleNamespace) -> dict:
        """Exercise the boundary without importing or controlling Windows."""
        reader=Accessibility()
        reader._auto=SimpleNamespace(UIAutomationInitializerInThread=nullcontext,
            GetForegroundControl=lambda:top,GetFocusedControl=lambda:control)
        with patch('kolos_states.accessibility.sys.platform','win32'):
            return reader.read()

    def test_empty_focused_editor_is_readable_and_text_keeps_spaces(self):
        for value in ('','1 2 3 4 5',' 1\n'):
            with self.subTest(value=value):
                result=self.read(*self.controls(value))
                self.assertTrue(result['readable']);self.assertTrue(result['focus'])
                self.assertEqual(result['output'],value);self.assertEqual(result['reason'],'')

    def test_document_text_pattern_is_read_from_the_focused_document(self):
        top,control=self.controls()
        control.ControlTypeName='DocumentControl';control.GetValuePattern=lambda:None
        text=Mock(return_value='1 2 3')
        control.GetTextPattern=lambda:SimpleNamespace(DocumentRange=SimpleNamespace(GetText=text))
        result=self.read(top,control)
        self.assertTrue(result['readable']);self.assertEqual(result['output'],'1 2 3')
        text.assert_called_once_with(20001)

    def test_password_readonly_button_and_own_window_are_not_input_evidence(self):
        for kind in ('password','button','own'):
            with self.subTest(kind=kind):
                top,control=self.controls('123')
                if kind=='password':control.IsPassword=True
                elif kind=='own':top.ProcessId=os.getpid()
                else:
                    control.ControlTypeName='ButtonControl'
                    control.GetValuePattern=lambda:SimpleNamespace(IsReadOnly=True,Value='123')
                result=self.read(top,control)
                self.assertFalse(result['readable']);self.assertEqual(result['focus'],'')
                self.assertEqual(result['output'],'')

    def test_missing_dependency_names_the_installation_fix(self):
        original_import=builtins.__import__
        def missing(name: str, *args, **kwargs):
            if name=='uiautomation':raise ModuleNotFoundError('missing',name='uiautomation')
            return original_import(name,*args,**kwargs)
        with patch('kolos_states.accessibility.sys.platform','win32'),patch('builtins.__import__',side_effect=missing):
            reader=Accessibility()
            with self.assertRaisesRegex(RuntimeError,r'uiautomation.*install_states.bat'):
                reader.ensure_available()
            result=reader.read()
        self.assertFalse(result['readable']);self.assertIn('install_states.bat',result['reason'])

    def test_recording_cannot_arm_without_the_observer_dependency(self):
        terminal=Terminal.__new__(Terminal);terminal.hooks_ready=True
        terminal.allowed=lambda:True;terminal.abort=Mock();terminal.adapter=None
        terminal.observer=SimpleNamespace(accessibility=SimpleNamespace(
            ensure_available=Mock(side_effect=RuntimeError('install_states.bat'))))
        with patch('kolos_states.cli.WindowsMotor') as motor:
            with self.assertRaisesRegex(RuntimeError,'install_states.bat'):terminal._arm()
        motor.assert_not_called();terminal.abort.clear.assert_not_called()


if __name__=='__main__':unittest.main()
