"""Persist learned evidence, not repeated high-volume working retina samples."""
from __future__ import annotations

from ..protocol import require
from .types import raster, rectangle


def without_samples(value: object) -> object:
    """Keep frame provenance and binding proofs while omitting temporary scan tensors."""
    if isinstance(value, dict):
        return {k: without_samples(v) for k, v in value.items() if k not in ('perception_samples', 'object_registry', 'object_instances')}
    if isinstance(value, list):
        return [without_samples(v) for v in value]
    return value


def validate_lessons(lessons: object, memory: dict) -> list:
    """A damaged prototype journal must not be silently overwritten on load."""
    require(isinstance(lessons, list) and len(lessons) <= 240, 'Повреждён журнал зрительных показов')
    targets = {n['id'] for n in memory['nodes'] if n['kind'] == 'visual_object'}
    variants = {n['id'] for n in memory['nodes'] if n['kind'] == 'visual_variant'}
    for entry in lessons:
        require(isinstance(entry, dict) and entry.get('target') in targets, 'Нет образа для зрительного показа')
        require(entry.get('variant') in variants, 'Нет показанного вида для зрительного показа')
        require(any(e['kind'] == 'visual_contains' and e['from'] == entry['variant']
                    and e['to'] == entry['target'] for e in memory['edges']), 'Показ связан с другим образом')
        raster(entry.get('icon')); raster(entry.get('label')); rectangle(entry.get('relative'))
    return lessons
