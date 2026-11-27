"""Late full recognition must refresh evidence without replaying desktop input."""
from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock

from PIL import Image
from Glaz.states_bridge import GlazStatesBridge
from kolos_states.ipc import ScanClient


class ScanFreshnessTests(unittest.TestCase):
    def _request(self, *, always_stale: bool = False, stop: bool = False,
                 retryable_error: bool = False, mode=None, wrong_mode=False) -> tuple:
        """A complete first response arrives just beyond the three-second limit."""
        clock = {'time': 1000.0}; sent = []; stopped = threading.Event()

        def publish(_path: Path, payload: dict) -> None:
            sent.append(dict(payload))

        def read(_path: Path) -> dict:
            request = sent[-1]
            late = always_stale or len(sent) == 1
            stamp = request['after'] + .15
            clock['time'] = max(clock['time'], stamp + (3.05 if late else .05))
            if stop:
                stopped.set()
            if retryable_error and len(sent) == 1:
                return dict(session='s', request=request['id'], retryable=True,
                            error='Распознавание кадра заняло слишком долго; нужен новый кадр.')
            return dict(session='s', request=request['id'], captured_at=stamp,
                        complete=True, frame=len(sent), mode=None if wrong_mode else request.get('mode'))

        def sleep(seconds: float) -> None:
            clock['time'] += seconds

        with patch('kolos_states.ipc.atomic_json', side_effect=publish), \
             patch('kolos_states.ipc.read_json', side_effect=read), \
             patch('kolos_states.ipc.time.time', side_effect=lambda: clock['time']), \
             patch('kolos_states.ipc.time.monotonic', side_effect=lambda: clock['time']-1000), \
             patch('kolos_states.ipc.time.sleep', side_effect=sleep):
            result = ScanClient(Path('unused'), 's', stop=stopped, timeout=8).request(
                after=1000.1, visual_requests=[dict(id='look')], mode=mode)
        return result, sent

    def test_expired_complete_reply_requests_a_new_fresh_frame(self) -> None:
        """An expired matching reply cannot trap the client on the same nonce."""
        result, sent = self._request()
        self.assertEqual(len(sent), 2)
        self.assertNotEqual(sent[0]['id'], sent[1]['id'])
        self.assertGreater(sent[1]['after'], sent[0]['after'])
        self.assertEqual(result['request'], sent[1]['id'])
        self.assertEqual(result['frame'], 2)
        self.assertEqual(sent[1]['visual_requests'], sent[0]['visual_requests'])

    def test_bridge_expiration_error_requests_another_scan(self) -> None:
        """Only the bridge's explicit stale-frame error permits a new nonce."""
        result, sent = self._request(retryable_error=True)
        self.assertEqual(len(sent), 2)
        self.assertEqual(result['request'], sent[1]['id'])

    def test_repeated_late_frames_keep_the_original_timeout(self) -> None:
        """Refreshing evidence is bounded and cannot run indefinitely."""
        with self.assertRaises(TimeoutError):
            self._request(always_stale=True)

    def test_stop_prevents_a_refresh_after_a_late_frame(self) -> None:
        """A stop during reading wins over an automatic observation retry."""
        with self.assertRaises(InterruptedError):
            self._request(stop=True)

    def test_frame_only_retry_preserves_mode_without_requesting_visual_recognition(self):
        result,sent=self._request(mode='frame-only')
        self.assertEqual(result['mode'],'frame-only')
        self.assertEqual(len(sent),2)
        self.assertTrue(all(r['mode']=='frame-only' and 'visual_requests' not in r for r in sent))

    def test_frame_only_cannot_accept_a_full_scan_from_an_old_bridge(self):
        with self.assertRaisesRegex(RuntimeError,'режим наблюдения'):
            self._request(mode='frame-only',wrong_mode=True)


class BridgeFreshnessTests(unittest.TestCase):
    def test_frame_only_poll_never_runs_detector_worker_or_hover_confirmation(self):
        image=Image.new('RGB',(100,100),'#334455');published=[]
        bridge=GlazStatesBridge.__new__(GlazStatesBridge)
        bridge.enabled=True;bridge.closed=False;bridge.session='s';bridge.path=Path('unused')
        bridge.last='';bridge.frame=0;bridge.future=None;bridge.worker=Mock();bridge.permission=Mock();bridge.allow_live=False
        bridge._reported_hover=('glaz.56',(14,11,60,56))
        root=Mock();root.winfo_children.return_value=[];root.winfo_viewable.return_value=True
        root.winfo_rootx.return_value=200;root.winfo_rooty.return_value=200
        root.winfo_width.return_value=100;root.winfo_height.return_value=100
        detector=Mock(side_effect=AssertionError('Frame-only must not recognize objects'))
        bridge.app=SimpleNamespace(root=root,capture=SimpleNamespace(is_capturing=True),current_image=image,
            _states_frame=(image,1000.1,dict(left=0,top=0,width=100,height=100)),
            loupe_controller=SimpleNamespace(loupe_size=50),segment_peak_threshold=SimpleNamespace(get=lambda:3),
            _compute_peaks_and_objects=detector,_event_bus=Mock(),log_message=Mock())
        request=dict(id='frame',session='s',issued=1000.0,after=1000.0,mode='frame-only')
        with patch.dict(sys.modules,{'utils':SimpleNamespace(get_cursor_pos=lambda:(37,37))}), \
             patch('Glaz.states_bridge.read_json',return_value=request), \
             patch('Glaz.states_bridge.time.time',return_value=1000.2), \
             patch('Glaz.states_bridge.atomic_json',side_effect=lambda _,r:published.append(r)):
            bridge.poll()
        self.assertEqual(len(published),1)
        self.assertEqual(published[0]['mode'],'frame-only')
        self.assertTrue(published[0]['complete']);self.assertIn('visual_sample',published[0])
        self.assertNotIn('icons',published[0]);self.assertNotIn('perception_samples',published[0])
        bridge.worker.submit.assert_not_called();detector.assert_not_called()
        bridge.app._event_bus.emit.assert_not_called();bridge.app.log_message.assert_not_called()
        self.assertEqual(bridge._reported_hover,('glaz.56',(14,11,60,56)))
        root.after.assert_called_once()

    def _publish(self, *, changed: bool = False, monitor_changed: bool = False,
                 capturing: bool = True, report_hover: bool = False) -> list[dict]:
        """Publish a four-second computation against a newer actual capture."""
        source = Image.new('RGB', (100, 100), '#223344'); current = source.copy()
        if changed:
            current.putpixel((37, 37), (255, 255, 255))
        monitor = dict(left=0, top=0, width=100, height=100)
        latest_monitor = dict(monitor, left=100) if monitor_changed else dict(monitor)
        signature = (1, 2)
        bridge = GlazStatesBridge.__new__(GlazStatesBridge)
        bridge.enabled = True; bridge.closed = False; bridge.session = 's'; bridge.path = Path('unused')
        bridge.request = dict(id='scan'); bridge._reported_hover = None
        published = []

        def report(*_args, **_kwargs) -> None:
            self.assertTrue(published, 'Publish the complete frame before updating the journal')

        bridge.app = SimpleNamespace(
            capture=SimpleNamespace(is_capturing=capturing),
            _states_frame=(current, 999.9, latest_monitor),
            _zoomed_signature_to_ids={signature: [56]}, _signature_match_max_pct=.2,
            _objects_repo=SimpleNamespace(find_similar=lambda *_args, **_kwargs: (signature, 0)),
            _states_controls_owned=report_hover, _event_bus=SimpleNamespace(emit=report),
        )
        result = dict(request='scan', captured_at=996.0, frame=1, monitor=monitor,
                      rows=[((14, 11, 60, 56), signature)], source_frame=source)
        with patch.dict(sys.modules, {'utils': SimpleNamespace(get_cursor_pos=lambda: (37, 37))}), \
             patch('Glaz.states_bridge.time.time', return_value=1000.0), \
             patch('Glaz.states_bridge.atomic_json', side_effect=lambda _path, data: published.append(data)):
            bridge._publish(result)
        return published

    def test_identical_fresh_pixels_refresh_a_slow_complete_scan(self) -> None:
        """Exact fresh pixels prove the computed target is still observed."""
        published = self._publish()
        self.assertEqual(len(published), 1)
        self.assertTrue(published[0]['complete'])
        self.assertEqual(published[0]['captured_at'], 999.9)
        self.assertEqual(published[0]['icons'][0]['id'], 'glaz.56')
        self.assertNotIn('source_frame', published[0])

    def test_complete_frame_is_published_before_hover_journal(self) -> None:
        """A slow journal handler cannot delay delivery of complete evidence."""
        self.assertTrue(self._publish(report_hover=True)[0]['complete'])

    def test_changed_pixels_cannot_refresh_a_stale_scan(self) -> None:
        """Even one changed target pixel requires new recognition."""
        published = self._publish(changed=True)[0]
        self.assertIn('слишком долго', published['error'])
        self.assertTrue(published['retryable'])

    def test_another_monitor_cannot_refresh_identical_pixels(self) -> None:
        """Screen coordinate identity matters even when the image is identical."""
        self.assertIn('слишком долго', self._publish(monitor_changed=True)[0]['error'])

    def test_stopped_capture_cannot_refresh_identical_pixels(self) -> None:
        """A stopped source cannot provide current evidence."""
        self.assertIn('слишком долго', self._publish(capturing=False)[0]['error'])


if __name__ == '__main__':
    unittest.main()
