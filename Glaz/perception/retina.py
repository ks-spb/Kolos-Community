"""Spatial peak fragments from source pixels; no OCR, UIA or object selection."""
from __future__ import annotations

import math
from PIL import Image
from Glaz.image_processor import ImageProcessor
from kolos_states.perception.types import HEIGHT, MAX_WIDTH, MAX_CANDIDATES, rectangle
from kolos_states.protocol import require


def encode(peaks: Image.Image, bbox: list, shape: list | None = None, detail: int = 1) -> dict:
    """Keep the aspect ratio at teaching time and sample the same geometry later."""
    l, t, r, b = [round(v) for v in rectangle(bbox)]
    require(r > l and b > t, 'Область меньше пикселя')
    valid = 0 <= l < r <= peaks.width and 0 <= t < b <= peaks.height
    width, height = shape or [max(1, min(MAX_WIDTH, round((r-l)*HEIGHT/(b-t)))), HEIGHT]
    require(1 <= width <= MAX_WIDTH and height == HEIGHT, 'Неверный размер осмотра')
    patch = peaks.crop((l, t, r, b))
    if not detail:
        patch = patch.resize((max(1, width//2), height//2), Image.Resampling.BOX)
    patch = patch.resize((width, height), Image.Resampling.BOX)
    return dict(width=width, height=height, data=patch.tobytes().hex(), valid=valid)


def peak_map(frame: Image.Image, threshold: int) -> Image.Image:
    """Peaks always have positive intensity independent of display inversion."""
    return ImageProcessor.detect_color_peaks(frame.convert('RGB'), threshold, invert=True)


def lesson(frame: Image.Image, icon_bbox: list, label_bbox: list, threshold: int) -> dict:
    """Encode a human-confirmed pair from a single frozen source frame."""
    icon_bbox, label_bbox = rectangle(icon_bbox), rectangle(label_bbox)
    l, t, r, b = icon_bbox; w, h = r-l, b-t
    peaks = peak_map(frame, threshold)
    icon, label = encode(peaks, icon_bbox), encode(peaks, label_bbox)
    require(icon['valid'] and label['valid'], 'Показывайте области внутри снимка')
    return dict(icon=icon, label=label, source_size=[w, h],
                relative=[(label_bbox[0]-l)/w, (label_bbox[1]-t)/h,
                          (label_bbox[2]-l)/w, (label_bbox[3]-t)/h])


def collect(frame: Image.Image, boxes: list, requests: list, threshold: int,
            monitor: dict, own_rect: list | None = None, *, own_rects: list | None = None) -> dict:
    """Return all candidate evidence, or fail closed if the budget is exceeded."""
    if not requests:
        return dict(views={}, complete=True)
    require(isinstance(requests, list) and len(requests) <= 24, 'Слишком много областей внимания')
    unique = sorted(set(tuple(round(v) for v in box) for box in boxes))
    unique = [box for box in unique if box[2]-box[0] >= 6 and box[3]-box[1] >= 6]
    unique = [box for box in unique if any(_plausible_size(box, req) for req in requests)]
    if len(unique) > MAX_CANDIDATES:
        return dict(views={}, complete=False, reason='Слишком много зрительных кандидатов; нужен более простой экран')
    volume = len(unique)*sum(sum(v[0]*v[1]*2 for v in req['shapes'].values())+800 for req in requests)
    if volume > 2_000_000:
        return dict(views={}, complete=False, reason='Лимит подробного осмотра; уменьшите число вариантов или объектов')
    peaks = peak_map(frame, threshold); result = {}
    excluded = own_rects if own_rects is not None else [own_rect] if own_rect else []
    for request in requests:
        result[request['id']] = _view(peaks, unique, request, monitor, excluded)
    return dict(views=result, complete=True)


def _view(peaks: Image.Image, boxes: list, request: dict, monitor: dict,
          own_rects: list) -> list[dict]:
    """An icon and its label are sampled from one instance in one frame."""
    relative = rectangle(request['relative']); result = []
    ox, oy = monitor.get('left', 0), monitor.get('top', 0)
    for l, t, r, b in boxes:
        if not _plausible_size([l, t, r, b], request):
            continue
        bbox = [l+ox, t+oy, r+ox, b+oy]
        label = [l+relative[0]*(r-l), t+relative[1]*(b-t),
                 l+relative[2]*(r-l), t+relative[3]*(b-t)]
        label_screen = [label[0]+ox, label[1]+oy, label[2]+ox, label[3]+oy]
        if any(_intersects(bbox, rect) or _intersects(label_screen, rect) for rect in own_rects):
            continue
        if any(not math.isfinite(v) for v in label):
            continue
        parts = {role: encode(peaks, box, request['shapes'][role], request['detail'])
                 for role, box in [('icon', [l, t, r, b]), ('label', label)]}
        result.append(dict(bbox=bbox, label_bbox=label_screen, parts=parts))
    return result


def _intersects(a: list, b: list) -> bool:
    """Exclude the application's own pixels, including its teaching window."""
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _plausible_size(box: list, request: dict) -> bool:
    """Bound proposal geometry around the shown scale, without selecting any instance."""
    size = request.get('source_size')
    if not size:
        return True
    sx, sy = (box[2]-box[0])/size[0], (box[3]-box[1])/size[1]
    return .5 <= sx <= 2 and .5 <= sy <= 2 and .75 <= sx/sy <= 1.333334
