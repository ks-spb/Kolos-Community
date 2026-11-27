"""Select the most specific fresh object at a cursor, including hover outlines."""
from __future__ import annotations

from collections.abc import Sequence


def bbox_contains_point(bbox: Sequence[float], point: tuple[float, float]) -> bool:
    """Use the detector's half-open bounds when testing cursor coordinates."""
    left, top, right, bottom = bbox
    x, y = point
    return left <= x < right and top <= y < bottom


def pointed_bbox_index(
    bboxes: Sequence[Sequence[float]], point: tuple[float, float] | None,
) -> int | None:
    """Pick an inner bbox only when every other hit strictly encloses it.

    A surrounding outline is not a second pointer target. Equal or partially
    overlapping bounds remain unresolved. Callers decide which bboxes represent
    recognized objects rather than unrecognized contours.
    """
    if point is None:
        return None
    hits = [index for index, bbox in enumerate(bboxes) if bbox_contains_point(bbox, point)]
    for index in hits:
        left, top, right, bottom = bboxes[index]
        if all(other == index or (
            bboxes[other][0] <= left and bboxes[other][1] <= top
            and bboxes[other][2] >= right and bboxes[other][3] >= bottom
            and tuple(bboxes[other]) != tuple(bboxes[index])
        ) for other in hits):
            return index
    return None
