"""Native design-02 checks. GUI tests use fake capture/motor boundaries.
Windows smoke in test_windows.py separately boots the real default application.
"""
import ast
import contextlib
import copy
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Glaz'))


class StudioSourceTests(unittest.TestCase):
    def test_default_is_native_studio_and_rollback_available(self):
        source=(ROOT/'Glaz/main.py').read_text(encoding='utf-8')
        self.assertIn('else NeuralStudioApp',source);self.assertIn('GLAZ_UI',source)
        self.assertNotIn('webview',source)
    def test_presentation_components_do_not_import_or_run_engine(self):
        for path in ('Glaz/studio_canvas.py','Glaz/studio_theme.py'):
            tree=ast.parse((ROOT/path).read_text(encoding='utf-8'))
            imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
            self.assertFalse(any(n.endswith(('.core','.simulator','.desktop')) for n in imports))
            self.assertFalse(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in ('tick','learn','start_language','send_line') for n in ast.walk(tree)))

    @staticmethod
    def running_hover_app():
        from states_app import IntegratedScreenCaptureApp
        from image_processor import DetectedObject
        from recognition_state import RecognitionIdle
        app=IntegratedScreenCaptureApp.__new__(IntegratedScreenCaptureApp)
        app._recognition_state=RecognitionIdle()
        app._states_controls_owned=True
        app._states_hover_bbox=None
        app.capture=types.SimpleNamespace(is_capturing=True,monitor_info=dict(left=0,top=0,width=100,height=100))
        app._detected_objects=[DetectedObject(7,(40,40,60,60),(50,50))]
        app._mouse_to_peaks_coords=Mock(return_value=(50,50))
        app._last_hovered_object_id=None;app._last_cursor_pos=None;app._cursor_stable_since=None
        app._object_already_recognized=False;app._cursor_stable_delay=0
        app._zoomed_signature_to_ids={(1,2):[23]};app._object_id_to_refined={}
        app._signature_match_max_pct=.2
        app.current_image=object()
        app.peaks_threshold=Mock(get=lambda:40);app.peaks_invert=Mock(get=lambda:False)
        app.segment_peak_threshold=Mock(get=lambda:3)
        app.loupe_controller=types.SimpleNamespace(loupe_size=50)
        app._signature_for_object_center=Mock(return_value=(1,2))
        app._objects_repo=types.SimpleNamespace(find_similar=Mock(return_value=((1,2),0)))
        app._event_bus=types.SimpleNamespace(emit=Mock())
        return app

    def test_running_hover_recognizes_known_object_without_moving_cursor(self):
        app=self.running_hover_app()
        with patch('states_app.get_cursor_pos',return_value=(50,50),create=True),patch('app.set_cursor_pos') as move:
            app._process_mouse_over_object((100,100))
            app._process_mouse_over_object((100,100))
        self.assertEqual(app._object_id_to_refined.get(7),23)
        self.assertTrue(app._object_already_recognized)
        move.assert_not_called()
        app._zoomed_signature_to_ids[(1,2)]=[23,24]
        with patch('states_app.get_cursor_pos',return_value=(50,50)):
            app._process_mouse_over_object((100,100))
        self.assertFalse(app._object_already_recognized)
        self.assertNotIn(7,app._object_id_to_refined)

    def test_running_hover_survives_detector_renumbering(self):
        from image_processor import DetectedObject
        app=self.running_hover_app();app._cursor_stable_delay=.5
        with patch('states_app.get_cursor_pos',return_value=(50,50)), \
             patch('states_app.time.time',side_effect=[10,10.2,10.6]),patch('app.set_cursor_pos') as move:
            for obj_id in (7,8,9):
                app._detected_objects=[DetectedObject(obj_id,(40,40,60,60),(50,50))]
                app._process_mouse_over_object((100,100))
        self.assertTrue(app._object_already_recognized)
        self.assertEqual(app._object_id_to_refined.get(9),23)
        move.assert_not_called()

    def test_running_hover_selects_the_icon_inside_a_larger_hover_outline(self):
        from image_processor import DetectedObject
        app=self.running_hover_app()
        app._detected_objects.append(DetectedObject(8,(30,30,70,80),(50,55)))
        with patch('states_app.get_cursor_pos',return_value=(50,50)),patch('app.set_cursor_pos') as move:
            app._process_mouse_over_object((100,100))
            app._process_mouse_over_object((100,100))
        self.assertTrue(app._object_already_recognized)
        self.assertEqual(app._object_id_to_refined,{7:23})
        move.assert_not_called()

    def test_running_hover_ignores_unrecognized_contours_under_cursor(self):
        from image_processor import DetectedObject
        for bbox in ((45,45,55,55),(45,45,70,70),(30,30,70,80)):
            with self.subTest(bbox=bbox):
                app=self.running_hover_app()
                app._detected_objects.append(DetectedObject(8,bbox,(50,50)))
                app._signature_for_object_center.side_effect=lambda **kw: (1,2) if kw['obj'].id==7 else ()
                with patch('states_app.get_cursor_pos',return_value=(50,50)),patch('app.set_cursor_pos') as move:
                    app._process_mouse_over_object((100,100))
                    app._process_mouse_over_object((100,100))
                self.assertEqual(app._object_id_to_refined,{7:23})
                self.assertTrue(app._object_already_recognized)
                move.assert_not_called()

    def test_running_hover_revokes_id_when_cursor_moves_or_match_disappears(self):
        app=self.running_hover_app()
        with patch('states_app.get_cursor_pos',return_value=(50,50)):
            app._process_mouse_over_object((100,100))
            app._process_mouse_over_object((100,100))
        self.assertTrue(app._object_already_recognized)
        with patch('states_app.get_cursor_pos',return_value=(51,50)):
            app._process_mouse_over_object((100,100))
        self.assertFalse(app._object_already_recognized)
        self.assertNotIn(7,app._object_id_to_refined)
        app._signature_for_object_center.return_value=()
        with patch('states_app.get_cursor_pos',return_value=(51,50)):
            app._process_mouse_over_object((100,100))
        self.assertFalse(app._object_already_recognized)
        self.assertNotIn(7,app._object_id_to_refined)

    def test_running_hover_rejects_multiple_objects_and_stopped_capture(self):
        app=self.running_hover_app()
        app._detected_objects*=2
        app._process_mouse_over_object((100,100))
        self.assertFalse(app._object_already_recognized)
        app._signature_for_object_center.reset_mock()
        app._detected_objects=app._detected_objects[:1];app.capture.is_capturing=False
        app._process_mouse_over_object((100,100))
        app._signature_for_object_center.assert_not_called()

    @classmethod
    def pending_hover_app(cls):
        """Create a centered recognition attempt without native mouse or database I/O."""
        from recognition_state import RecognitionStep1
        app=cls.running_hover_app();app._states_controls_owned=False
        app._recognition_state=RecognitionStep1();app._last_hovered_object_id=7
        app._cursor_center_target=(50,50);app._cursor_centered_confirmed=True
        app._cursor_hold_position=(50,50);app._cursor_hold_until=0
        app._cursor_hold_after_center=1;app._cursor_center_tolerance_px=2
        app._hold_cursor_if_active=Mock();app._set_performance_mode_idle=Mock()
        app._set_performance_mode_step1=Mock();app._update_loupe=Mock()
        app._do_screenshots_var=Mock(get=lambda:False)
        app.current_peaks_image=types.SimpleNamespace(size=(100,100))
        app._zoomed_signature_temp=(1,2);app._object_id_to_refined={7:23}
        return app

    def test_failed_recognition_returns_to_idle_and_allows_another_hover(self):
        from image_processor import DetectedObject
        for failure in ('missing','empty','ambiguous','stopped','uncentered','no-frame'):
            with self.subTest(failure=failure):
                app=self.pending_hover_app()
                if failure=='missing':app._detected_objects=[]
                elif failure=='empty':app._signature_for_object_center.return_value=()
                elif failure=='ambiguous':app._zoomed_signature_to_ids={(1,2):[23,24]}
                elif failure=='stopped':app.capture.is_capturing=False
                elif failure=='no-frame':app.current_image=None
                else:
                    app._cursor_centered_confirmed=False;app._cursor_center_target=None
                app._process_signature_if_pending()
                self.assertTrue(app._recognition_state.is_idle,failure)
                self.assertIsNone(app._cursor_hold_position)
                self.assertIsNone(app._cursor_center_target)
                self.assertFalse(app._object_already_recognized)
                self.assertEqual(app._zoomed_signature_temp,())
                self.assertNotIn(7,app._object_id_to_refined)
                app._detected_objects=[DetectedObject(8,(40,40,60,60),(50,50))]
                app._signature_for_object_center.return_value=(1,2)
                app._zoomed_signature_to_ids={(1,2):[23]}
                app.capture.is_capturing=True;app.current_image=object()
                with patch('app.get_cursor_pos',return_value=(50,50)), \
                     patch('app.set_cursor_pos') as move,patch('app.write_last_confirmed_target') as confirm:
                    app._process_mouse_over_object((100,100))
                    app._process_mouse_over_object((100,100))
                    self.assertTrue(app._recognition_state.is_step1)
                    move.assert_called_once_with(50,50)
                    app._process_signature_if_pending()
                self.assertTrue(app._recognition_state.is_idle)
                self.assertEqual(app._object_id_to_refined.get(8),23)
                confirm.assert_called_once_with(23,center_xy=(50,50),bbox_ltrb=(40,40,60,60))

    def test_reset_and_record_button_release_stale_recognition(self):
        for command in ('/reset','3','/record','/stop'):
            with self.subTest(command=command):
                app=self.pending_hover_app();app._states_controls_owned=True
                app._states_bridge=types.SimpleNamespace(enabled=True)
                app._engine_var=Mock(get=lambda:'Состояния и цели (ПК)')
                app._states_allow=Mock();app._states_permission=Mock();app._kolos_controller=Mock()
                app._kolos_append_main_thread=Mock()
                app._states_send(command)
                self.assertTrue(app._recognition_state.is_idle)
                self.assertFalse(app._states_controls_owned)
                self.assertIsNone(app._cursor_hold_position)
                app._kolos_controller.send_line.assert_called_once_with(command)

    def test_return_from_execution_to_recording_centers_and_confirms_again(self):
        app=self.pending_hover_app()
        app._states_bridge=types.SimpleNamespace(closed=False,path=Path('unused'),session='s')
        app._image_table=None;app._state_table=None;app.root=Mock()
        with patch('states_app.read_json',return_value=dict(session='s',running=True,recording=False)):
            app._states_status()
        with patch('states_app.get_cursor_pos',return_value=(50,50)):
            app._process_mouse_over_object((100,100));app._process_mouse_over_object((100,100))
        self.assertTrue(app._object_already_recognized)
        with patch('states_app.read_json',return_value=dict(session='s',running=False,recording=True)):
            app._states_status()
        self.assertFalse(app._object_already_recognized)
        with patch('app.get_cursor_pos',return_value=(50,50)),patch('app.set_cursor_pos') as move, \
             patch('app.write_last_confirmed_target') as confirm:
            app._process_mouse_over_object((100,100));app._process_mouse_over_object((100,100))
            app._process_signature_if_pending()
        move.assert_called_once_with(50,50);confirm.assert_called_once()

    def test_changed_context_after_click_keeps_mouse_owned_until_enter(self):
        from tests.desktop.test_click_enter import ordinary_terminal
        from image_processor import DetectedObject
        for goals in (False,True):
            with self.subTest(goals=goals):
                terminal,screen=ordinary_terminal()
                if goals:
                    terminal.engine.start_goals([dict(kind='state',features=['visible:OPEN'])],terminal.observer.observe())
                with contextlib.redirect_stdout(io.StringIO()):
                    for _ in range(100):
                        terminal.tick_once()
                        if screen.clicked and terminal.receipt is None:break
                self.assertTrue(screen.clicked)
                screen.focus='tooltip';screen.own=True;screen.foreground=200;screen.context_valid=False
                app=self.running_hover_app()
                app._states_bridge=types.SimpleNamespace(closed=False,path=Path('unused'),session='s')
                app._image_table=None;app._state_table=None;app.root=Mock()
                app._detected_objects=[DetectedObject(43,(40,40,65,65),(52,52))]
                with contextlib.redirect_stdout(io.StringIO()), \
                     patch('states_app.read_json',side_effect=lambda _:dict(session='s',running=terminal.running,recording=False)), \
                     patch('states_app.get_cursor_pos',return_value=(50,50)),patch('app.set_cursor_pos') as move:
                    for _ in range(100):
                        app._hold_cursor_if_active()
                        app._process_mouse_over_object((100,100))
                        terminal.tick_once()
                        app._states_status()
                        self.assertTrue(app._states_controls_owned)
                        if screen.sent[-1]['kind']=='enter':break
                    move.assert_not_called()
                self.assertEqual([a['kind'] for a in screen.sent],['move','click','enter'])


@unittest.skipUnless(os.environ.get('KOLOS_STUDIO_GUI_SMOKE')=='1','Opt-in actual native Neural Studio widgets')
class StudioTkTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        if importlib.util.find_spec('mss') is None:
            m=types.ModuleType('mss');m.mss=Mock();self.mss_patch=patch.dict(sys.modules,{'mss':m});self.mss_patch.start();self.addCleanup(self.mss_patch.stop)
        from studio_app import NeuralStudioApp
        from app import ScreenCaptureApp
        self.root=tk.Tk();self.root.geometry('1440x940+0+0');self.errors=[]
        self.root.report_callback_exception=lambda *args:self.errors.append(str(args))
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.capture=Mock();self.capture.selected_monitor=1;self.capture.get_monitors.return_value=['Монитор 1 · 1920 × 1080'];self.capture.monitor_info=dict(left=0,top=0,width=1920,height=1080);self.capture.is_capturing=False
        repo=Mock();repo.load.return_value=({}, {}, 1)
        self.controller=Mock();self.controller.start.return_value='';self.controller.is_running=True
        self.patches=[patch('app.ScreenCapture',return_value=self.capture),patch('app.ObjectsRepository',return_value=repo),
                      patch.object(ScreenCaptureApp,'_setup_window_position'),patch('states_app.KolosSubprocessController',return_value=self.controller),
                      patch('states_bridge.Path.home',return_value=Path(self.tmp.name)),patch.dict(os.environ)]
        for p in self.patches:p.start()
        os.environ.pop('KOLOS_ENGINE',None);os.environ.pop('GLAZ_AUTOSTART',None)
        self.app=NeuralStudioApp(self.root)
        self.pump()
    def tearDown(self):
        a=self.app;a._closing=True;a._inline_feed.close();a._neuron_canvas.close();a._states_bridge.close()
        a._processing_executor.shutdown(wait=False);a._scan_executor.shutdown(wait=False)
        for task in self.root.tk.call('after','info'):
            self.root.after_cancel(task)
        self.root.destroy()
        for p in reversed(self.patches):p.stop()
        self.assertEqual(self.errors,[])
    def pump(self,seconds=.16):
        until=time.monotonic()+seconds
        while time.monotonic()<until:self.root.update();time.sleep(.005)
    def frame(self):
        from kolos_states.capabilities import prepare
        from kolos_states.simulator import observe
        from kolos_states.neuron_projection import project_neurons
        e,w,req=prepare(9);e.imagine(req['goals'],observe(w))
        for _ in range(8):e.tick()
        return e,project_neurons(e.model,e.events[-1])
    def screenshot(self,name):
        from PIL import ImageGrab
        self.pump(.2);r=self.root;out=ROOT/'tests/desktop-output';out.mkdir(exist_ok=True)
        ImageGrab.grab(bbox=(r.winfo_rootx(),r.winfo_rooty(),r.winfo_rootx()+r.winfo_width(),r.winfo_rooty()+r.winfo_height())).save(out/name)
    def test_default_start_grants_states_permission_and_raises_terminal(self):
        from kolos_states.ipc import read_json
        a=self.app
        self.assertEqual(a._engine_var.get(),'Состояния и цели (ПК)')
        self.assertEqual(self.controller.start.call_args.kwargs['engine'],'states')
        self.assertTrue(a._states_bridge.enabled);self.assertTrue(a._states_allow.get());self.assertTrue(a._states_bridge.allow_live)
        permission=read_json(a._states_bridge.path/'permission.json')
        self.assertEqual(permission['session'],a._states_bridge.session);self.assertTrue(permission['live'])
        self.assertEqual(a._workspace_mode,'vision');self.assertTrue(a.peaks_canvas.winfo_ismapped())
        ratio=a._terminal_host.winfo_height()/a._vertical_pane.winfo_height()
        self.assertGreater(ratio,.45);self.assertLess(ratio,.55)
        self.controller.send_line.assert_not_called();self.capture.start.assert_not_called()
    def test_engine_switch_revokes_startup_permission(self):
        a=self.app
        a._engine_var.set('Legacy v4');a._switch_engine()
        self.controller.stop.assert_called_once();self.assertEqual(self.controller.start.call_args.kwargs['engine'],'legacy')
        self.assertFalse(a._states_allow.get());self.assertFalse(a._states_bridge.allow_live)
        a._engine_var.set('Состояния и цели (ПК)');a._switch_engine()
        self.assertEqual(self.controller.start.call_args.kwargs['engine'],'states')
        self.assertFalse(a._states_allow.get());self.assertFalse(a._states_bridge.allow_live)

    def test_active_tools_menu_opens_visual_teacher_and_its_help(self) -> None:
        """Exercise the actual Studio menu, not the overridden classic builder."""
        from kolos_states.perception.help import VISUAL_HELP
        a=self.app;menu=a._tools_menu
        entries={menu.entrycget(i,'label'):i for i in range(menu.index('end')+1) if menu.type(i)=='command'}
        self.assertIn('Обучить составной объект',entries)
        self.assertIn('Подсказки по зрительному обучению',entries)
        menu.invoke(entries['Обучить составной объект']);self.pump(.05)
        import tkinter as tk
        windows=[w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel)
                 and w.title()=='Колос · Обучить составной объект']
        self.assertEqual(len(windows),1);self.assertTrue(windows[0].winfo_viewable())
        with patch('states_app.messagebox.showinfo') as show:
            menu.invoke(entries['Подсказки по зрительному обучению'])
            show.assert_called_once_with('Как обучить значок и подпись',VISUAL_HELP,parent=self.root)
        self.controller.send_line.assert_not_called();self.capture.start.assert_not_called()
        windows[0].destroy()

    def test_training_panel_exposes_visual_teaching_and_help_buttons(self) -> None:
        """The visible Learn panel gives a second route to the same teacher."""
        import tkinter as tk
        from tkinter import ttk
        from kolos_states.perception.help import VISUAL_HELP
        a=self.app;a._show_training();self.pump(.05);window=a._dialogs['learn']
        pending=[window];buttons={}
        while pending:
            item=pending.pop();pending.extend(item.winfo_children())
            if isinstance(item,ttk.Button):buttons[item.cget('text')]=item
        self.assertTrue(buttons['Обучить составной объект'].winfo_viewable())
        with patch('states_app.messagebox.showinfo') as show:
            buttons['Подсказки'].invoke()
            show.assert_called_once_with('Как обучить значок и подпись',VISUAL_HELP,parent=self.root)
        buttons['Обучить составной объект'].invoke();self.pump(.05)
        self.assertFalse(window.winfo_exists())
        teacher=next(w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel)
                     and w.title()=='Колос · Обучить составной объект')
        self.assertTrue(teacher.winfo_viewable());teacher.destroy()
        self.controller.send_line.assert_not_called()
    def test_layout_send_and_switch_keep_one_terminal_and_engine(self):
        a=self.app;entry=a._kolos_entry;controller=a._kolos_controller
        a._kolos_input_var.set('добавь траты 2345')
        for _ in range(3):
            for mode in ('vision','neurons','capabilities'):
                a._select_workspace(mode);self.pump(.02);self.assertTrue(entry.winfo_ismapped())
        self.assertIs(a._kolos_entry,entry);self.assertIs(a._kolos_controller,controller)
        controller.send_line.assert_not_called();self.capture.stop.assert_not_called();self.capture.start.assert_not_called()
        a._send_button.invoke();controller.send_line.assert_called_once_with('добавь траты 2345')
        controller.reset_mock();a._command_buttons['3'].invoke();controller.send_line.assert_called_once_with('3')
        self.assertTrue(a._states_allow.get())
        controller.reset_mock();a._command_buttons['/reset'].invoke();controller.send_line.assert_called_once_with('/reset')

    def test_enter_and_send_button_echo_exact_input_in_green(self):
        from studio_theme import P
        a=self.app;query='впиши 1 2 3 4 5'
        self.controller.send_line.return_value=True
        a._kolos_input_var.set(query);a._kolos_entry.focus_force();self.pump(.02)
        a._kolos_entry.event_generate('<Return>');self.pump(.02)
        self.controller.send_line.assert_called_once_with(query)
        self.assertEqual(a._kolos_input_var.get(),'')
        a._kolos_append_main_thread('Ответ движка\n')
        self.assertEqual(a._kolos_text.get('1.0','end').count('> '+query+'\n'),1)
        self.assertEqual(a._kolos_text.tag_cget('kolos_user_input','foreground'),P['good'])
        index=a._kolos_text.search('> '+query,'1.0')
        self.assertIn('kolos_user_input',a._kolos_text.tag_names(index))
        self.controller.reset_mock()
        a._kolos_input_var.set('1');a._send_button.invoke()
        self.controller.send_line.assert_called_once_with('1')
        self.assertIn('> 1\n',a._kolos_text.get('1.0','end'))

    def test_failed_send_preserves_the_input_without_a_success_echo(self):
        a=self.app;query='не потерять команду'
        self.controller.send_line.return_value=False
        a._kolos_input_var.set(query);a._send_button.invoke()
        self.assertEqual(a._kolos_input_var.get(),query)
        self.assertNotIn('> '+query,a._kolos_text.get('1.0','end'))
        self.assertIn('Не удалось отправить',a._kolos_text.get('1.0','end'))
        self.controller.send_line.reset_mock();self.controller.is_running=False
        a._send_button.invoke();self.controller.send_line.assert_not_called()
        self.assertEqual(a._kolos_input_var.get(),query)

    def test_pinned_task_survives_output_controls_and_workspace_switches(self):
        from studio_theme import P
        a=self.app;query='впиши 1 2 3 4 5'
        a._kolos_input_var.set(query);a._send_button.invoke();self.pump(.02)
        self.assertEqual(a._kolos_task_var.get(),'Задача: '+query)
        self.assertEqual(str(a._kolos_task_label.cget('foreground')),P['good'])
        top=a._kolos_task_label.winfo_rooty()
        a._kolos_max_lines=15
        a._kolos_append_main_thread('Новый вывод\n'*100);self.pump(.02)
        self.assertNotIn(query,a._kolos_text.get('1.0','end'))
        self.assertEqual(a._kolos_task_var.get(),'Задача: '+query)
        self.assertEqual(a._kolos_task_label.winfo_rooty(),top)
        self.assertLessEqual(top+a._kolos_task_label.winfo_height(),a._kolos_text.winfo_rooty())
        for command in ('3','5','1','/pause','/stop','/reset','/end','/speed 0.5','/help',''):
            a._kolos_input_var.set(command);a._send_button.invoke()
            self.assertEqual(a._kolos_task_var.get(),'Задача: '+query)
        for button in a._command_buttons.values():
            button.invoke()
            self.assertEqual(a._kolos_task_var.get(),'Задача: '+query)
        for mode in ('neurons','capabilities','vision'):
            a._select_workspace(mode);self.pump(.02)
            self.assertTrue(a._kolos_task_label.winfo_ismapped())
            self.assertEqual(a._kolos_task_var.get(),'Задача: '+query)
        self.controller.send_line.return_value=False
        a._kolos_input_var.set('другая задача');a._send_button.invoke()
        self.assertEqual(a._kolos_task_var.get(),'Задача: '+query)
        self.controller.send_line.return_value=True;a._send_button.invoke()
        self.assertEqual(a._kolos_task_var.get(),'Задача: другая задача')

    def test_pinned_task_wraps_and_keeps_controls_visible_at_768p(self):
        a=self.app;self.root.geometry('1100x768+0+0');self.pump();a._initial_workspace_size()
        before=a._kolos_task_label.winfo_height()
        query='впиши '+'1 2 3 4 5 '*15
        a._kolos_input_var.set(query);a._send_button.invoke();self.pump(.05)
        self.assertEqual(a._kolos_task_var.get(),'Задача: '+query)
        self.assertGreater(a._kolos_task_label.winfo_height(),before)
        self.assertGreater(a._kolos_text.winfo_height(),30)
        for widget in (a._kolos_task_label,a._kolos_entry,a._send_button,a._command_buttons['/stop']):
            self.assertTrue(widget.winfo_ismapped())
            self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),self.root.winfo_rootx()+self.root.winfo_width())
            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),self.root.winfo_rooty()+self.root.winfo_height())

    def test_text_query_aliases_update_the_pinned_task(self):
        a=self.app
        for command in ('/query','/say','/say-run'):
            a._kolos_input_var.set(command+' открой окно');a._send_button.invoke()
            self.assertEqual(a._kolos_task_var.get(),'Задача: открой окно')
        a._kolos_input_var.set('12345');a._send_button.invoke()
        self.assertEqual(a._kolos_task_var.get(),'Задача: 12345')

    def test_confirmed_tasks_tab_updates_from_current_session_and_keeps_selection(self):
        from kolos_states.ipc import atomic_json
        a=self.app;bridge=a._states_bridge
        raw=dict(session=bridge.session,confirmedTasks=[])
        atomic_json(bridge.path/'status.json',raw)
        a._select_workspace('capabilities');self.pump(.03)
        self.assertTrue(a._tasks_host.winfo_ismapped());self.assertTrue(a._kolos_entry.winfo_ismapped())
        self.assertEqual(a._tasks_table.get_children(),())
        self.assertIn('пока нет',a._tasks_summary.get())
        raw['confirmedTasks']=[dict(query='впиши 1 2 3 4 5',demonstrations=1,actions=['KEY 1','KEY 2','KEY 3','KEY 4','KEY 5'])]
        atomic_json(bridge.path/'status.json',raw);self.pump(.4)
        self.assertEqual(a._tasks_table.item('0','values'),('впиши 1 2 3 4 5','1 · Правильно','1','5'))
        a._tasks_table.selection_set('0');self.pump(.02)
        self.assertIn('5. KEY 5',a._tasks_details.get('1.0','end'))
        raw['confirmedTasks'][0]['demonstrations']=2
        atomic_json(bridge.path/'status.json',raw);self.pump(.4)
        self.assertEqual(a._tasks_table.selection(),('0',))
        self.assertEqual(a._tasks_table.item('0','values')[2],'2')
        self.screenshot('neural-studio-confirmed-tasks.png')
        self.controller.send_line.assert_not_called();self.capture.stop.assert_not_called()
        raw['session']='different-session';a._refresh_learned_tasks(raw)
        self.assertEqual(a._tasks_table.get_children(),())
        raw['session']=bridge.session;a._refresh_learned_tasks(raw)
        self.assertEqual(len(a._tasks_table.get_children()),1)
        bridge.enabled=False;a._refresh_learned_tasks(raw)
        self.assertEqual(a._tasks_table.get_children(),())
        self.assertIn('Выберите движок',a._tasks_summary.get())
    def test_inspector_minimap_and_filter_are_read_only(self):
        from studio_theme import P
        e,f=self.frame();snapshot=copy.deepcopy(e.model);v=self.app._neuron_canvas
        self.app._select_workspace('neurons')
        v.set_frame(f,running=True);self.pump();self.assertTrue(v._mini.find_all());self.assertEqual(v.canvas.cget('background'),P['canvas'])
        v.selection=('node',next(n['id'] for n in f['nodes'] if n['I'] is not None));v.details();self.assertIn('I и S',v.inspector.get('1.0','end'))
        v._minimap_click(types.SimpleNamespace(x=50,y=40));v.layer.set('Образ I / S');v.refit()
        self.assertEqual(snapshot,e.model);self.app._kolos_controller.send_line.assert_not_called()
        self.app._kolos_append_main_thread('Снимок Python-ядра: опыт 11. Захват и действия ОС в этом интерфейсном тесте заменены заглушками.\n')
        self.screenshot('neural-studio-neurons.png')
    def test_dialogs_are_themed_without_changing_motor_permissions(self):
        from studio_theme import P
        a=self.app;allowed=a._states_allow.get()
        for name in ('_show_training','_show_experiments','_show_memory','_show_settings','_show_goal_dialog','_show_language_dialog'):
            # No goal choices -> informational OS dialog; do not block this test.
            with patch('states_app.messagebox.showinfo'):
                getattr(a,name)();self.pump(.03)
        for window in a._dialogs.values():self.assertEqual(window.cget('background'),P['bg'])
        a._kolos_controller.send_line.assert_not_called();self.assertEqual(a._states_allow.get(),allowed)
        self.assertEqual(a._settings_window.cget('background'),P['bg'])
    def test_768p_commands_are_visible_and_return_to_peaks(self):
        a=self.app;self.root.geometry('1100x768+0+0');self.pump();a._initial_workspace_size();self.pump()
        ratio=a._terminal_host.winfo_height()/a._vertical_pane.winfo_height()
        self.assertGreater(ratio,.45);self.assertLess(ratio,.55)
        for w in (a._send_button,a._command_buttons['/stop'],a._command_buttons['/reset'],a._kolos_entry):
            self.assertTrue(w.winfo_ismapped());self.assertLessEqual(w.winfo_rootx()+w.winfo_width(),self.root.winfo_rootx()+self.root.winfo_width())
            self.assertLessEqual(w.winfo_rooty()+w.winfo_height(),self.root.winfo_rooty()+self.root.winfo_height())
        self.assertGreater(a._command_buttons['/reset'].winfo_rootx(),a._command_buttons['/stop'].winfo_rootx())
        a._select_workspace('vision');self.pump();self.assertTrue(a.peaks_canvas.winfo_ismapped());self.screenshot('neural-studio-vision.png')
    def test_freeze_cannot_pause_engine_and_stop_revokes_permission(self):
        a=self.app;_,f=self.frame();v=a._neuron_canvas;v.set_frame(f);v.frozen.set(True);v.freeze_changed()
        a._kolos_controller.send_line.assert_not_called()
        a._states_allow.set(True);a._command_buttons['/stop'].invoke()
        self.assertFalse(a._states_allow.get());a._kolos_controller.send_line.assert_called_once_with('/stop')
        self.assertFalse(a._states_bridge.allow_live)
        from kolos_states.ipc import read_json
        self.assertFalse(read_json(a._states_bridge.path/'permission.json')['live'])
    def test_database_cleanup_requires_stop_and_explicit_confirmation(self):
        from app import ScreenCaptureApp
        a=self.app
        with patch.object(ScreenCaptureApp,'_clear_objects_db') as deleted,patch('studio_app.messagebox.askyesno',return_value=False) as confirm,patch('studio_app.messagebox.showinfo'):
            a.capture.is_capturing=True;a._confirm_clear_objects();confirm.assert_not_called();deleted.assert_not_called()
            a.capture.is_capturing=False;a._confirm_clear_objects();confirm.assert_called_once();deleted.assert_not_called()
        with patch.object(ScreenCaptureApp,'_clear_objects_db') as deleted,patch('studio_app.messagebox.askyesno',return_value=True):
            a._confirm_clear_objects();deleted.assert_called_once()

    def test_same_tuning_variables_and_hidden_capture_still_processes(self):
        from PIL import Image
        from app import ScreenCaptureApp
        a=self.app;a._select_workspace('neurons');a.current_image=Image.new('RGB',(320,240))
        with patch.object(a,'_process_mouse_over_object') as hover,patch.object(a,'_hold_cursor_if_active'):
            a._update_display();hover.assert_called_once_with((320,240))
        with patch.object(ScreenCaptureApp,'_on_frame_captured') as original:
            a._on_frame_captured(a.current_image);original.assert_called_once_with(a.current_image)
        self.assertEqual(str(a.threshold_scale.cget('variable')),str(a.peaks_threshold))
        self.assertEqual(str(a.scale_combo.cget('textvariable')),str(a.peaks_scale))
        a._speed_value.set(.5);a._apply_speed();a._kolos_controller.send_line.assert_called_once_with('/speed 0.5')

if __name__=='__main__':unittest.main()
