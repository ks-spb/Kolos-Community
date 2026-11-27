"""The same desktop icon must keep its loupe signature at screen edges."""

from __future__ import annotations

import sys
import time
import unittest
from itertools import permutations, product
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "Glaz"))

from app import ScreenCaptureApp  # noqa: E402
from image_processor import DetectedObject, LineBasedDetector  # noqa: E402
from loupe import LoupeController  # noqa: E402
from loupe_signature import LoupeSignatureAnalyzer  # noqa: E402
from objects_repository import ObjectsRepository  # noqa: E402
from states_bridge import GlazStatesBridge  # noqa: E402
import loupe  # noqa: E402
from Glaz.cursor_target import pointed_bbox_index  # noqa: E402
from kolos_states.desktop import DesktopAdapter, DesktopObserver  # noqa: E402
from kolos_states.protocol import clone  # noqa: E402


def icon_frame(cx: int, cy: int, background: str = "white") -> Image.Image:
    frame = Image.new("RGB", (240, 160), background)
    draw = ImageDraw.Draw(frame)
    ink = "black" if background == "white" else "white"
    draw.rectangle((cx - 6, cy - 6, cx + 6, cy + 6), outline=ink, width=2)
    draw.line((cx - 4, cy + 4, cx + 4, cy - 4), fill=ink, width=2)
    return frame


class TestGlazLoupeEdges(unittest.TestCase):
    def test_real_detector_and_hover_outline_keep_duplicate_icon_clickable(self) -> None:
        app=ScreenCaptureApp.__new__(ScreenCaptureApp)
        app._object_detector=LineBasedDetector()
        app._objects_repo=ObjectsRepository()
        app._signature_match_max_pct=.2
        app._states_controls_owned=True
        app._event_bus=SimpleNamespace(emit=Mock())
        frame=icon_frame(120,80)
        target=app._compute_peaks_and_objects(frame,40,False).objects[0]
        known=app._signature_for_object_center(frame=frame,obj=target,loupe_size=100,
            threshold=40,invert=False,segment_threshold=3)
        self.assertTrue(known)
        app._zoomed_signature_to_ids={known:[56]}
        frame.paste(frame.crop((100,60,140,100)),(180,60))
        ImageDraw.Draw(frame).rectangle((92,52,148,108),outline='black',width=1)
        bridge=GlazStatesBridge.__new__(GlazStatesBridge)
        bridge.app=app;bridge.enabled=True;bridge.closed=False;bridge.session='s';bridge.path=Path('unused')
        job=dict(request='r',captured_at=time.time(),frame=1,
            monitor=dict(left=0,top=0,width=240,height=160),own_rect=[300,0,500,160],
            loupe_size=100,segment_threshold=3)
        result=bridge._compute(frame,40,False,job)
        hits=[bbox for bbox,_ in result['rows'] if bbox[0]<=120<bbox[2] and bbox[1]<=80<bbox[3]]
        self.assertGreaterEqual(len(hits),2)
        published=[]
        with patch('utils.get_cursor_pos',return_value=(120,80)), \
             patch('states_bridge.atomic_json',side_effect=lambda _path,data:published.append(data)):
            bridge._publish(result)
        pointed=[i for i in published[0]['icons'] if i['id']=='glaz.56' and not i['ambiguous']]
        self.assertEqual(len(pointed),1)
        self.assertLess(pointed[0]['bbox'][2]-pointed[0]['bbox'][0],30)
        self.assertEqual(len(published[0]['pointer_bboxes']),len(hits))
        self.assert_pointer_clicks_once(published[0])

    def assert_pointer_clicks_once(self, raw: dict) -> None:
        """Exercise observation filtering and physical dispatch after real recognition."""
        def fresh_scan(**kwargs):
            frame=clone(raw);frame['captured_at']=max(time.time(),kwargs.get('after',0)+.00001)
            return frame
        scan=SimpleNamespace(request=fresh_scan)
        uia=SimpleNamespace(read=lambda:dict(focus='',output='',readable=False,own=False,reason=''))
        observer=DesktopObserver(scan,uia)
        self.assertEqual([i['id'] for i in observer.observe()['icons']],['glaz.56'])
        motor=Mock();adapter=DesktopAdapter(observer,motor,allow=lambda:True)
        check=adapter.execute(dict(id='check',action=dict(kind='check',object='glaz.56')))
        self.assertTrue(check['ok']);motor.send.assert_not_called()
        request=dict(id='click',action=dict(kind='click',object='glaz.56'))
        receipt=adapter.execute(request,assume_click=True)
        self.assertTrue(receipt['ok'])
        self.assertEqual(adapter.execute(request),receipt)
        motor.send.assert_called_once_with(request['action'])

    def test_pointed_bounds_are_order_independent_and_half_open(self) -> None:
        small=(14,11,60,56);outline=(0,0,76,104);other=(100,100,160,160)
        for boxes in permutations((small,outline,other)):
            index=pointed_bbox_index(boxes,(37,37))
            self.assertIsNotNone(index)
            self.assertEqual(boxes[index],small)
        self.assertEqual(pointed_bbox_index([small],(14,11)),0)
        for point in (None,(60,37),(37,56),(0,0)):
            self.assertIsNone(pointed_bbox_index([small],point))
        self.assertIsNone(pointed_bbox_index([], (0,0)))
        self.assertIsNone(pointed_bbox_index([small,small],(37,37)))
        self.assertIsNone(pointed_bbox_index([small,(35,20,80,50)],(37,37)))

    def test_states_scan_recognizes_hover_signature_without_ui_hover(self) -> None:
        canvas = Mock()
        canvas.winfo_width.return_value = 240
        canvas.winfo_height.return_value = 160
        cases = product(((120, 80), (11, 11)), ((0, 0), (-200, -100)), (1, 3), (False, True))
        for (cx, cy), (left, top), segment_threshold, invert in cases:
            with self.subTest(center=(cx, cy), origin=(left, top), segments=segment_threshold, invert=invert):
                frame = icon_frame(cx, cy)
                monitor = dict(left=left, top=top, width=240, height=160)
                obj = DetectedObject(7, (cx - 6, cy - 6, cx + 7, cy + 7), (cx + .7, cy + .7))
                app = ScreenCaptureApp.__new__(ScreenCaptureApp)
                app.capture = SimpleNamespace(monitor_info=monitor)
                app.current_peaks_image = frame
                cursor = app._object_center_to_monitor_coords(*obj.center_peaks)
                controller = LoupeController(None, canvas, loupe_size=50)
                controller.peaks_loupe.config.peak_sequence_threshold = segment_threshold
                controller.peaks_loupe.config.peak_sequence_threshold_arc = segment_threshold
                with (
                    patch.object(loupe, "get_cursor_pos", return_value=cursor),
                    patch.object(loupe.ImageTk, "PhotoImage", return_value=object()),
                ):
                    controller.update(frame, monitor, 1.0, 100, 40, invert, loupe_size_override=100)
                learned = tuple(sorted(controller.get_last_highlighted_segment_ids()))
                self.assertTrue(learned)
                app._compute_peaks_and_objects = Mock(return_value=SimpleNamespace(objects=[obj]))
                app._objects_repo = ObjectsRepository()
                app._zoomed_signature_to_ids = {learned: [23]}
                app._signature_match_max_pct = .2
                app._scan_signature_analyzer = LoupeSignatureAnalyzer()
                bridge = GlazStatesBridge.__new__(GlazStatesBridge)
                bridge.app = app
                bridge.enabled = True
                bridge.closed = False
                bridge.session = 'session'
                bridge.path = Path('unused')
                job = dict(request='request', captured_at=time.time(), frame=1,
                           monitor=monitor, own_rect=[300, 0, 500, 160],
                           loupe_size=50, segment_threshold=segment_threshold)
                result = bridge._compute(frame, 40, invert, job)
                published = []
                # No current UI hover or stored object mapping is available.
                with patch('utils.get_cursor_pos', return_value=(left + 200, top + 120)), \
                     patch('states_bridge.atomic_json', side_effect=lambda _path, data: published.append(data)):
                    bridge._publish(result)
                self.assertEqual([icon['id'] for icon in published[0]['icons']], ['glaz.23'])
                self.assertFalse(published[0]['icons'][0]['ambiguous'])
                self.assertNotIn('loupe_size', published[0])
                self.assertNotIn('segment_threshold', published[0])

    def test_hover_loupe_keeps_icon_centered_at_all_corners(self) -> None:
        canvas = Mock()
        canvas.winfo_width.return_value = 240
        canvas.winfo_height.return_value = 160
        for background in ("white", "black"):
            with self.subTest(background=background):
                controller = LoupeController(None, canvas, loupe_size=50)
                signatures = []
                peak_images = []
                for cx, cy in ((120, 80), (11, 11), (229, 11), (11, 149), (229, 149)):
                    with (
                        patch.object(loupe, "get_cursor_pos", return_value=(cx, cy)),
                        patch.object(loupe.ImageTk, "PhotoImage", return_value=object()),
                    ):
                        controller.update(
                            icon_frame(cx, cy, background),
                            {"left": 0, "top": 0, "width": 240, "height": 160},
                            1.0, 100, 40, False, loupe_size_override=100,
                        )
                    data = controller.peaks_loupe_data
                    self.assertEqual(data.crop_bbox_source, (cx - 50, cy - 50, cx + 50, cy + 50))
                    self.assertEqual(data.image.size, (50, 50))
                    self.assertGreaterEqual(data.x, 0)
                    self.assertGreaterEqual(data.y, 0)
                    self.assertLessEqual(data.x + data.width, 240)
                    self.assertLessEqual(data.y + data.height, 160)
                    signatures.append(controller.get_last_highlighted_segment_ids())
                    peak_images.append(data.image.tobytes())

                self.assertTrue(signatures[0])
                self.assertEqual(signatures, [signatures[0]] * len(signatures))
                self.assertEqual(peak_images, [peak_images[0]] * len(peak_images))

    def test_prescan_uses_same_full_crop_for_edge_object(self) -> None:
        app = ScreenCaptureApp.__new__(ScreenCaptureApp)
        images = []
        analyzer = Mock()

        def capture(image: Image.Image, **_kwargs):
            images.append(image.tobytes())
            return SimpleNamespace(highlighted_segment_ids=(1,))

        analyzer.compute.side_effect = capture
        app._scan_signature_analyzer = analyzer
        for cx, cy in ((120, 80), (6, 6)):
            obj = DetectedObject(
                id=1,
                bbox=(cx - 6, cy - 6, cx + 7, cy + 7),
                center_peaks=(cx, cy),
            )
            signature = app._signature_for_object_bbox(
                frame=icon_frame(cx, cy), obj=obj, loupe_size=50,
                threshold=40, invert=False,
            )
            self.assertEqual(signature, (1,))

        self.assertEqual(images[0], images[1])


if __name__ == "__main__":
    unittest.main()
