"""Compact visual evidence from the same Glaz frame used for object detection."""
from __future__ import annotations

from PIL import Image, ImageDraw


SAMPLE_SIZE = (24, 14)
SAMPLE_BYTES = SAMPLE_SIZE[0] * SAMPLE_SIZE[1] * 3


def sample_frame(frame: Image.Image, *, monitor: dict | None = None, own_rect=None, own_rects=None) -> str:
    """Mask each owned window separately, including a teaching screenshot preview."""
    image = frame.convert('RGB')
    for rect in (own_rects if own_rects is not None else [own_rect] if own_rect else []):
        if not monitor:
            continue
        left, top = monitor.get('left', 0), monitor.get('top', 0)
        bounds = (max(0, rect[0] - left), max(0, rect[1] - top),
                  min(image.width, rect[2] - left), min(image.height, rect[3] - top))
        if bounds[0] < bounds[2] and bounds[1] < bounds[3]:
            ImageDraw.Draw(image).rectangle(bounds, fill=(128, 128, 128))
    return image.resize(SAMPLE_SIZE, Image.Resampling.BOX).tobytes().hex()


def measure(before: dict, after: dict) -> tuple[int, float] | None:
    """Return changed sample cells and mean channel difference, if comparable."""
    a, b = before.get('visual_sample'), after.get('visual_sample')
    if not isinstance(a, str) or not isinstance(b, str) or len(a) != SAMPLE_BYTES * 2 or len(b) != len(a):
        return None
    first, second = before.get('monitor') or {}, after.get('monitor') or {}
    if any(first.get(k) != second.get(k) for k in ('left', 'top', 'width', 'height')):
        return None
    try:
        left, right = bytes.fromhex(a), bytes.fromhex(b)
    except ValueError:
        return None
    deltas = [abs(x - y) for x, y in zip(left, right)]
    changed_cells = sum(max(deltas[i:i + 3]) >= 32 for i in range(0, SAMPLE_BYTES, 3))
    return changed_cells, sum(deltas) / SAMPLE_BYTES


def changed(before: dict, after: dict) -> bool:
    """Require a broad visual change; cursor motion and a small highlight do not count."""
    result = measure(before, after)
    return result is not None and result[0] >= 40 and result[1] >= 7
