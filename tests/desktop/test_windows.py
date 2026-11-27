"""Opt-in Windows checks. These are not proof of arbitrary application support."""
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
ROOT=Path(__file__).resolve().parents[2]

@unittest.skipUnless(sys.platform=='win32' and os.environ.get('KOLOS_WINDOWS_SMOKE')=='1','Opt-in native Windows desktop smoke')
class WindowsSmoke(unittest.TestCase):
    def test_real_focused_field_can_be_observed_after_native_key(self):
        import uiautomation as auto
        from kolos_states.accessibility import Accessibility
        from kolos_states.desktop import WindowsMotor
        proc=subprocess.Popen([sys.executable,'-m','kolos_states.test_pad'],cwd=ROOT)
        try:
            window=auto.WindowControl(searchDepth=1,ClassName='KolosStatesNativeTestPad')
            self.assertTrue(window.Exists(10,.2))
            window.ButtonControl(Name='CALC').Click()
            reader=Accessibility();before=reader.read();self.assertTrue(before['readable'],before);self.assertEqual(before['output'],'')
            WindowsMotor().send(dict(kind='key',value='1'))
            end=time.monotonic()+3;after=reader.read()
            while after['output']!='1' and time.monotonic()<end:time.sleep(.05);after=reader.read()
            self.assertEqual(after['focus'],before['focus']);self.assertEqual(after['output'],'1')
            from PIL import ImageGrab
            out=ROOT/'tests/desktop-output';out.mkdir(exist_ok=True)
            ImageGrab.grab().save(out/'win32-observed-key.png')
        finally:
            proc.terminate();proc.wait(timeout=5)
    def test_glaz_bootstrap_starts_native_child_with_permission_on(self):
        # A subprocess with a real Tk mainloop exercises run_main's Python target.
        script=r'''
import os,sys,tkinter as tk
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
sys.path.insert(0,str(Path.cwd()/'Glaz'))
os.environ.pop('KOLOS_ENGINE',None)
os.environ.pop('GLAZ_AUTOSTART',None)
from studio_app import NeuralStudioApp as IntegratedScreenCaptureApp
ipc_home=TemporaryDirectory()
os.environ['USERPROFILE']=ipc_home.name
assert Path.home()==Path(ipc_home.name)
root=tk.Tk()
app=IntegratedScreenCaptureApp(root)
ok=[]
assert 'Neural Studio' in root.title()
def send():
    assert app._states_bridge.enabled
    assert app._states_allow.get() and app._states_bridge.allow_live
    ratio=app._terminal_host.winfo_height()/app._vertical_pane.winfo_height()
    assert .45<ratio<.55,ratio
    assert app._kolos_controller.is_running
    child=app._kolos_controller
    entry=app._kolos_entry
    for _ in range(3):
        app._select_workspace('neurons');root.update_idletasks()
        assert entry.winfo_ismapped() and not app.peaks_canvas.winfo_ismapped()
        app._select_workspace('vision');root.update_idletasks()
        assert entry.winfo_ismapped() and app.peaks_canvas.winfo_ismapped()
    assert app._kolos_controller is child and child.is_running
    app._select_workspace('neurons')
    app._states_send('/stop')
    assert not app._states_allow.get() and not app._states_bridge.allow_live
    app._show_language_dialog()
    for child in root.winfo_children():
        if isinstance(child,tk.Toplevel) and child.title()=='Kolos: язык возбуждает образ':child.destroy()
    from urllib.request import urlopen
    with patch('webbrowser.open') as opened:
        app._show_shared_lab()
        assert opened.called
        address=opened.call_args.args[0]
        assert address.endswith('/web/shared/index.html')
        with urlopen(address) as response:
            assert response.status==200
            assert b'shared-app' in response.read()
    assert not app._states_allow.get()
    app._kolos_controller.send_line('/selftest')
def check():
    text=app._kolos_text.get('1.0','end')
    if text.count('"passed": true')>=4 and app._neuron_canvas.frame is not None:
        from PIL import ImageGrab
        out=Path('tests/desktop-output');out.mkdir(exist_ok=True)
        ImageGrab.grab().save(out/'glaz-startup.png')
        assert app._kolos_entry.winfo_ismapped()
        assert app._neuron_canvas.frame['nodes']
        assert not app._states_allow.get()
        ok.append(True);app._on_root_close()
    else:root.after(200,check)
def timeout():
    print(app._kolos_text.get('1.0','end'));app._on_root_close()
root.after(500,send);root.after(1000,check);root.after(25000,timeout);root.mainloop()
ipc_home.cleanup()
assert ok,'Native child did not complete four safe selftests'
'''
        result=subprocess.run([sys.executable,'-c',script],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=35)
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
if __name__=='__main__':unittest.main()
