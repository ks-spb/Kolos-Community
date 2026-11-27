"""Native inline projection/telemetry checks: no OS motor operations."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from kolos_states.neuron_projection import project_neurons, group_edges
from kolos_states.neuron_trace import NeuronTraceWriter
from kolos_states.ipc import atomic_json
from kolos_states.capabilities import prepare
from kolos_states.simulator import observe
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'Glaz'))
from neuron_feed import InlineNeuronFeed


def example():
    e,w,req=prepare(9);e.imagine(req['goals'],observe(w))
    before=copy.deepcopy(e.model)
    e.tick()
    return e,before


class InlineNeuronsTests(unittest.TestCase):
    def test_projection_does_not_mutate_engine_and_keeps_exact_channels(self):
        e,before=example();original=copy.deepcopy(e.model)
        f=project_neurons(e.model,e.events[-1],before)
        self.assertEqual(original,e.model)
        for n in e.model['imagery']['nodes']:
            drawn=next(v for v in f['nodes'] if v['id']==n['id'])
            self.assertEqual((drawn['I'],drawn['S']),(n['I'],n['S']))
        self.assertTrue(any(n['I'] and n['S']==0 for n in f['nodes']))
    def test_no_pulses_on_structural_image_order_edges(self):
        e,before=example();f=project_neurons(e.model,e.events[-1],before)
        order=[x for x in f['edges'] if x['kind']=='order'];self.assertTrue(order)
        self.assertTrue(all(x['flow'] is None and x['provenance']=='structure' for x in order))
    def test_recorded_flow_and_effective_term_are_exact(self):
        e,before=example()
        for _ in range(10):
            before=copy.deepcopy(e.model);e.tick()
        f=project_neurons(e.model,e.events[-1],before)
        self.assertTrue(e.events[-1]['flows'])
        for flow in e.events[-1]['flows']:
            edge=next(x for x in f['edges'] if x['id']==flow['edge'])
            self.assertEqual(edge['flow'],flow['value'])
            if 'term' in flow:self.assertEqual(edge['term'],flow['term'])
    def test_grouping_respects_direction_and_kind(self):
        edges=[dict(id=str(i),source=a,target=b,kind=k,provenance='recorded',flow=.2,term=.1) for i,(a,b,k) in enumerate([('a','b','x'),('a','b','x'),('b','a','x'),('a','b','y')])]
        g=group_edges(edges);self.assertEqual(len(g),3);self.assertEqual(g[0]['ids'],['0','1']);self.assertEqual(g[0]['flow'],.4)
    def test_inline_marker_independent_of_browser_marker(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);e,_=example();w=NeuronTraceWriter(p,'s')
            atomic_json(p/'neuron-inline-watch.json',dict(session='s',enabled=True))
            atomic_json(p/'neuron-watch.json',dict(session='s',enabled=False))
            self.assertTrue(w.capture(e))
            e.tick();atomic_json(p/'neuron-inline-watch.json',dict(session='s',enabled=False))
            atomic_json(p/'neuron-watch.json',dict(session='s',enabled=True))
            self.assertTrue(w.capture(e))
    def test_feed_is_latest_wins_and_reports_skipped_frames(self):
        with tempfile.TemporaryDirectory() as d:
            e,_=example();p=Path(d);feed=InlineNeuronFeed(p,'s');feed.set_enabled(True)
            try:
                w=NeuronTraceWriter(p,'s')
                for _ in range(8):e.tick();w.capture(e)
                r=feed._read(1,None,0);self.assertEqual(r['sequence'],8);self.assertEqual(r['skipped'],6)
                self.assertEqual(r['frame']['tick'],e.model['tick'])
                self.assertTrue(all(x.get('oldI') is None for x in r['frame']['nodes'] if x['I'] is not None))
            finally:feed.close()
    def test_feed_reset_does_not_replay_previous_process(self):
        with tempfile.TemporaryDirectory() as d:
            e,_=example();p=Path(d);feed=InlineNeuronFeed(p,'s');feed.set_enabled(True)
            try:
                w=NeuronTraceWriter(p,'s');w.capture(e);feed.reset()
                self.assertIsNone(feed._read(feed.sequence,None,feed.generation))
                e.tick();w.capture(e);self.assertEqual(feed._read(feed.sequence,None,feed.generation)['sequence'],2)
            finally:feed.close()
    def test_foreign_session_and_malformed_json_not_displayed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);e,_=example();atomic_json(p/'neuron-frames/000000001.json',dict(session='old',model=e.model))
            feed=InlineNeuronFeed(p,'new')
            try:self.assertIsNone(feed._read(0,None,0))
            finally:feed.close()
    def test_no_engine_or_motor_imports_in_view_components(self):
        for name in ['Glaz/neuron_canvas.py','Glaz/neuron_feed.py','kolos_states/neuron_projection.py']:
            import ast
            root=ast.parse((ROOT/name).read_text(encoding='utf-8'))
            imports=[x.module or '' for x in ast.walk(root) if isinstance(x,ast.ImportFrom)]
            self.assertFalse(any(x.endswith(('.core','.simulator','.desktop')) for x in imports))


@unittest.skipUnless(os.environ.get('KOLOS_INLINE_GUI_SMOKE')=='1','Opt-in actual Tk window (no real mouse actions)')
class InlineTkTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.tk=tk;self.root=tk.Tk();self.root.geometry('1366x900+0+0')
        self.errors=[];self.root.report_callback_exception=lambda *args:self.errors.append(str(args))
    def tearDown(self):
        self.root.destroy();self.assertEqual(self.errors,[])
    def pump(self,seconds=.12):
        end=time.monotonic()+seconds
        while time.monotonic()<end:self.root.update();time.sleep(.005)
    def test_real_canvas_draw_freeze_and_read_only_inspection(self):
        from neuron_canvas import NeuronCanvas
        v=NeuronCanvas(self.root);v.pack(fill='both',expand=True);v.set_visible(True);self.pump()
        e,before=example();original=copy.deepcopy(e.model);f=project_neurons(e.model,e.events[-1],before)
        v.set_frame(f,running=True);v.set_runtime(running=True);self.pump();self.assertGreater(len(v.canvas.find_all()),20)
        frozen=v.frame;v.frozen.set(True);v.freeze_changed();e.tick();v.set_frame(project_neurons(e.model,e.events[-1]));self.pump()
        self.assertIs(v.frame,frozen);self.assertIsNone(v.anim_job)
        v.frozen.set(False);v.freeze_changed();self.assertEqual(v.frame['tick'],e.model['tick'])
        self.assertIn('РАБОТАЕТ',v.banner.get())
        v.set_runtime(running=False, connected=False)
        self.assertIn('Нет связи',v.banner.get())
        v.layer.set('Образ I / S');v.refit();v.selection=('node',next(n['id'] for n in v.frame['nodes'] if n['I'] is not None));v.details()
        self.assertIn('I и S',v.inspector.get('1.0','end'))
        v.set_visible(False);self.assertIsNone(v.anim_job);v.close()
    def test_switch_preserves_terminal_capture_recording_and_child(self):
        # Real Tk widgets, fake OS boundaries. Windows CI also boots the real child.
        try:import mss
        except ImportError:
            import types
            fake_mss=types.ModuleType('mss');fake_mss.mss=Mock()
            self._mss_patch=patch.dict(sys.modules,{'mss':fake_mss});self._mss_patch.start();self.addCleanup(self._mss_patch.stop)
        from states_app import IntegratedScreenCaptureApp
        from app import ScreenCaptureApp
        capture=Mock();capture.selected_monitor=1;capture.monitor_info={'left':0,'top':0,'width':1200,'height':800}
        capture.get_monitors.return_value=['Monitor 1'];capture.is_capturing=True
        repo=Mock();repo.load.return_value=({}, {}, 1)
        with tempfile.TemporaryDirectory() as d,patch('app.ScreenCapture',return_value=capture),patch('app.ObjectsRepository',return_value=repo),patch.object(ScreenCaptureApp,'_setup_window_position'),patch.object(IntegratedScreenCaptureApp,'_start_kolos_embedded'),patch('states_bridge.Path.home',return_value=Path(d)):
            app=IntegratedScreenCaptureApp(self.root);app._states_bridge.enabled=True;app._engine_var.set("Состояния и цели (ПК)")
            app._kolos_controller=Mock();app._kolos_controller.is_running=True
            self.pump();entry=app._kolos_entry;controller=app._kolos_controller
            app._kolos_input_var.set('добавь траты 2345')
            for _ in range(5):
                app._select_workspace('neurons');self.pump(.02)
                self.assertTrue(entry.winfo_ismapped());self.assertFalse(app.peaks_canvas.winfo_ismapped())
                app._select_workspace('vision');self.pump(.02)
                self.assertTrue(app.peaks_canvas.winfo_ismapped());self.assertTrue(entry.winfo_ismapped())
            self.assertEqual(app._kolos_input_var.get(),'добавь траты 2345')
            self.assertIs(app._kolos_controller,controller);controller.send_line.assert_not_called()
            capture.stop.assert_not_called();capture.start.assert_not_called()
            app._select_workspace('neurons')
            e,before=example();writer=NeuronTraceWriter(app._states_bridge.path,app._states_bridge.session)
            for _ in range(7):e.tick()
            app._kolos_append_main_thread('Проверка интерфейса: снимки Python-ядра, синтетический опыт 11.\nТакт 8: образ FIELD=2345 активен; реальные действия выключены.\n')
            writer.capture(e);self.pump(.4)
            self.assertEqual(app._neuron_canvas.frame['tick'],e.model['tick'])
            # Incoming real capture callback still schedules recognition in neuron mode.
            from PIL import Image,ImageGrab
            image=Image.new('RGB',(300,200))
            with patch.object(ScreenCaptureApp,'_on_frame_captured') as original:
                app._on_frame_captured(image);original.assert_called_once_with(image)
            app.current_image=image
            with patch.object(app,'_process_mouse_over_object') as hover,patch.object(app,'_hold_cursor_if_active'):
                app._update_display();hover.assert_called_once_with(image.size)
            app._neuron_canvas.layer.set('Образ I / S');app._neuron_canvas.refit();self.pump()
            out=ROOT/'tests/desktop-output';out.mkdir(exist_ok=True)
            ImageGrab.grab(bbox=(self.root.winfo_rootx(),self.root.winfo_rooty(),self.root.winfo_rootx()+self.root.winfo_width(),self.root.winfo_rooty()+self.root.winfo_height())).save(out/'glaz-inline-neurons.png')
            app._closing=True;app._inline_feed.close();app._neuron_canvas.close();app._states_bridge.close()
            app._processing_executor.shutdown(wait=False);app._scan_executor.shutdown(wait=False)
            # Root is destroyed by tearDown; no persistent or legacy DB is written.

if __name__=='__main__':unittest.main()
