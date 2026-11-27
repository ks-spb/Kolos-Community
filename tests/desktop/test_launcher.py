import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch,MagicMock
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('controller',ROOT/'Glaz/kolos_subprocess.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

class LauncherTests(unittest.TestCase):
    def test_run_main_remains_glaz_entry(self):
        text=(ROOT/'run_main.bat').read_text(encoding='utf-8');self.assertIn('Glaz\\main.py',text);self.assertNotIn('node',text)
        self.assertIn('IntegratedScreenCaptureApp', (ROOT/'Glaz/main.py').read_text(encoding='utf-8'))
    def test_legacy_command_is_disabled(self):
        c=mod.KolosSubprocessController(ROOT,lambda *args:None)
        with patch.object(mod.subprocess,'Popen') as p,patch.object(mod.threading.Thread,'start'):
            p.return_value.poll.return_value=None
            self.assertIn('Legacy',c.start(engine='legacy'))
            p.assert_not_called()
    def test_states_child_is_native_python(self):
        c=mod.KolosSubprocessController(ROOT,lambda *args:None)
        with patch.object(mod.subprocess,'Popen') as p,patch.object(mod.threading.Thread,'start'):
            p.return_value.poll.return_value=None
            self.assertEqual(c.start(engine='states',ipc_dir='/session',session='abc',glaz_pid=123),'')
            command=p.call_args.args[0];self.assertEqual(command[:3],[sys.executable,'-m','kolos_states.cli']);self.assertIn('--session',command)
            self.assertEqual(p.call_args.kwargs['env']['PYTHONIOENCODING'],'utf-8')
    def test_invalid_mode_never_spawns(self):
        c=mod.KolosSubprocessController(ROOT,lambda *args:None)
        with patch.object(mod.subprocess,'Popen') as p:
            self.assertTrue(c.start(engine='wrong'));p.assert_not_called()
    def test_legacy_shutdown_does_not_send_text_as_command(self):
        c=mod.KolosSubprocessController(ROOT,lambda *args:None);c._proc=MagicMock();c._proc.poll.return_value=None;c._engine='legacy'
        c.stop();self.assertEqual(c._threads,[])
    def test_native_cli_selftest_has_no_gui_import(self):
        p=subprocess.run([sys.executable,'-m','kolos_states.cli','--selftest'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(p.stdout.count('"passed": true'),4)

if __name__=='__main__':unittest.main()
