"""Bounded, image-only contracts shared by the retina and neural graph."""
from __future__ import annotations

import math
from ..protocol import require

HEIGHT = 24
TILE = 6
MAX_WIDTH = 384
MAX_CANDIDATES = 200
KINDS = {'visual_object', 'visual_variant', 'visual_part', 'visual_fragment',
         'visual_relation', 'visual_look'}
EDGES = {
    'visual_contains': {('visual_fragment', 'visual_part'), ('visual_part', 'visual_variant'),
                        ('visual_variant', 'visual_object')},
    'visual_spatial': {('visual_relation', 'visual_variant')},
    'visual_attention': {('visual_object', 'visual_look'), ('visual_look', 'visual_variant')},
    'visual_ground': {('step', 'visual_object')},
}


def rectangle(value: object) -> list[float]:
    """Reject empty, reversed, nonfinite and unbounded rectangles."""
    require(isinstance(value, (list, tuple)) and len(value) == 4, 'Нужна область из четырёх координат')
    require(all(isinstance(x, (int, float)) and math.isfinite(x) and abs(x) <= 100000
                for x in value), 'Неверные координаты области')
    require(value[2] > value[0] and value[3] > value[1], 'Пустая область')
    return list(value)


def raster(value: dict) -> dict:
    """A bounded density image, never Unicode or accessibility metadata."""
    require(isinstance(value, dict), 'Нет зрительного образца')
    w, h = value.get('width'), value.get('height')
    require(type(w) is int and type(h) is int and 1 <= w <= MAX_WIDTH and h == HEIGHT,
            'Неверный размер зрительного образца')
    data = value.get('data')
    require(isinstance(data, str) and len(data) == 2*w*h, 'Повреждён зрительный образец')
    try:
        pixels = bytes.fromhex(data)
    except ValueError as exc:
        raise ValueError('Повреждён зрительный образец') from exc
    require(len(pixels) == w*h and any(pixels), 'В образце нет зрительных признаков')
    return dict(width=w, height=h, data=data)


def variants(memory: dict, target: str) -> list[dict]:
    """Only a learned assembly edge establishes membership."""
    ids = {e['from'] for e in memory['edges']
           if e['kind'] == 'visual_contains' and e['to'] == target}
    return [n for n in memory['nodes'] if n['kind'] == 'visual_variant' and n['id'] in ids]


def views(memory: dict, target: str, *, fine_only: bool = False) -> list[dict]:
    """Describe sensor requests; no decision or recognition occurs here."""
    result = []
    for variant in variants(memory, target):
        for look in memory['nodes']:
            if look['kind'] != 'visual_look' or look['variant'] != variant['id']:
                continue
            if fine_only and look['detail'] != 1:
                continue
            result.append(dict(id=look['id'], target=target, variant=variant['id'],
                               detail=look['detail'], relative=variant['relative'],
                               shapes=variant['shapes'], source_size=variant.get('source_size')))
    return result
