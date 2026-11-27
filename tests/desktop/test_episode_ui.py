import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


class EpisodeIntegrationSourceTests(unittest.TestCase):
    def test_optional_dialog_and_commands_use_existing_memory_and_permission(self):
        cli = (ROOT/'kolos_states/cli.py').read_text(encoding='utf-8')
        ui = (ROOT/'Glaz/states_app.py').read_text(encoding='utf-8')
        self.assertIn('episode_command(self, text)', cli)
        self.assertIn('from .episode_console import tick_once', cli)
        self.assertIn('Рабочий эпизод и роли', ui)
        console = (ROOT/'kolos_states/episode_console.py').read_text(encoding='utf-8')
        self.assertIn('t.store.save(t.engine)', console)
        self.assertIn('stop=t.abort', console)
        self.assertNotIn('StateEngine()', console)
        self.assertNotIn('FormWorld', console)


@unittest.skipUnless(sys.platform == 'win32' and os.environ.get('KOLOS_EPISODE_WINDOWS_SMOKE') == '1',
                     'Opt-in native episode dialog smoke')
class EpisodeDialogWindowsTests(unittest.TestCase):
    def test_dialog_renders_observed_fields_slots_and_sends_only_explicit_command(self):
        import tkinter as tk
        from PIL import ImageGrab
        from Glaz.episode_dialog import show
        from kolos_states.episode_experiment import FormWorld
        from kolos_states.ipc import atomic_json
        root = tk.Tk()
        root.withdraw()
        commands = []
        try:
            with tempfile.TemporaryDirectory() as directory:
                world = FormWorld()
                atomic_json(Path(directory)/'status.json', dict(session='dialog-test', episodeObjects=world.observe()['objects'],
                            episodeRecording=True, episodeRecordedCount=1, episodeSlots=['v0']))
                app = SimpleNamespace(root=root, _engine_var=tk.StringVar(value='Состояния и цели (ПК)'),
                                      _states_bridge=SimpleNamespace(path=Path(directory),session='dialog-test'),
                                      _states_send=commands.append)
                with patch('uiautomation.GetRootControl', return_value=SimpleNamespace(GetChildren=lambda: [])):
                    win = show(app)
                deadline = time.monotonic() + .7
                while time.monotonic() < deadline:
                    root.update()
                    time.sleep(.02)
                def widgets(parent):
                    for child in parent.winfo_children():
                        yield child
                        yield from widgets(child)
                all_widgets = list(widgets(win))
                tree = next(w for w in all_widgets if w.winfo_class() == 'Treeview')
                self.assertEqual(len(tree.get_children()), 5)
                tree.selection_set(world.ids['Source 1'])
                button = next(w for w in all_widgets if w.winfo_class() == 'TButton' and w.cget('text') == 'Прочитать → значение')
                self.assertEqual(commands, [])
                button.invoke()
                self.assertEqual(commands, ['/episode-read ' + world.ids['Source 1']])
                self.assertFalse(world.actions)
                output = ROOT/'tests/desktop-output/episode-dialog.png'
                output.parent.mkdir(parents=True, exist_ok=True)
                x, y = win.winfo_rootx(), win.winfo_rooty()
                ImageGrab.grab(bbox=(x,y,x+win.winfo_width(),y+win.winfo_height())).save(output)
                win.destroy()
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
