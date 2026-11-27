"""Confirmed demonstrations form visual ensembles in StateEngine.memory."""
from __future__ import annotations

from ..protocol import clone, require
from .types import TILE, raster, rectangle, variants


def teach(engine: object, lesson: dict) -> str:
    """Commit a paired icon/label example atomically; inference never calls this."""
    model = engine.model
    require(not model['pending'] and model['status'] not in ('running', 'waiting'),
            'Остановите исполнение перед обучением образу')
    require(len(model.get('visualLessons', [])) < 240, 'Лимит подтверждённых зрительных показов: 240')
    backup = clone(model)
    try:
        target, variant = _teach(engine, lesson)
        model.setdefault('visualLessons', []).append(dict(clone(lesson), target=target, variant=variant))
        model.pop('perception', None)
        model['message'] = 'Значок и подпись связаны подтверждённым показом.'
        engine._event(dict(kind='visual-teach', target=target))
        return target
    except Exception:
        engine.model = backup
        raise


def _teach(engine: object, lesson: dict) -> tuple[str, str]:
    """Build only observed variants, preserving their independent layouts."""
    require(isinstance(lesson, dict), 'Нет показа объекта')
    name = lesson.get('name', '')
    require(isinstance(name, str) and 0 < len(name) <= 160, 'Задайте имя образа')
    icon, label = raster(lesson.get('icon')), raster(lesson.get('label'))
    size = lesson.get('source_size')
    if size is not None:
        require(isinstance(size, list) and len(size) == 2, 'Нет размера показанного значка')
        rectangle([0, 0, *size])
    relative = rectangle(lesson.get('relative'))
    require(all(abs(v) <= 32 for v in relative), 'Подпись слишком далеко от значка')
    clipped = lesson.get('clipped', 'none')
    require(clipped in ('none', 'left', 'right', 'top', 'bottom'), 'Неверная сторона обрезания')
    target = engine.node(lesson.get('target'))
    if lesson.get('target'):
        require(target and target['kind'] == 'visual_object', 'Неизвестный составной образ')
    else:
        require(clipped == 'none', 'Первый показ должен содержать полную подпись')
        target = engine._node(kind='visual_object', label=name)
    repeated = next((old for old in engine.model.get('visualLessons', []) if all(old.get(k, 'none' if k == 'clipped' else None) == lesson.get(k, 'none' if k == 'clipped' else None)
                       for k in ('icon', 'label', 'relative', 'clipped', 'source_size')) and old['target'] == target['id']
                   ), None)
    if repeated:
        _reinforce(engine, target['id'], repeated['variant'])
        return target['id'], repeated['variant']
    require(len(variants(engine.model['memory'], target['id'])) < 12, 'Лимит вариантов образа: 12')
    variant = _variant(engine, target, icon, label, relative, clipped, size)
    return target['id'], variant


def _reinforce(engine: object, target: str, variant: str) -> None:
    """Only a teacher's repeated confirmation increases visual synaptic weights."""
    memory = engine.model['memory']; included = {variant}
    for _ in range(5):
        included.update(e['from'] for e in memory['edges']
                        if e['kind'].startswith('visual_') and e['kind'] != 'visual_ground'
                        and e['to'] in included and e['from'] != target)
    included.add(target)
    rate = engine.model['config']['learningRate']
    for edge in memory['edges']:
        if edge['from'] in included and edge['to'] in included:
            edge['weight'] += rate*(1-edge['weight'])


def _variant(engine: object, target: dict, icon: dict, label: dict,
             relative: list, clipped: str, size: list | None) -> str:
    """Spatial and part links are all required for sensory confirmation."""
    variant = engine._node(kind='visual_variant', label=target['label']+' · вид',
                           relative=relative, clipped=clipped, source_size=size,
                           shapes={k: [v['width'], v['height']] for k, v in [('icon', icon), ('label', label)]})
    engine._edge(variant['id'], target['id'], 'visual_contains')
    relation = engine._node(kind='visual_relation', label='Расположение подписи', relative=relative)
    engine._edge(relation['id'], variant['id'], 'visual_spatial')
    for role, sample in [('icon', icon), ('label', label)]:
        _part(engine, variant, role, sample)
    for detail, weight in [(0, .9), (1, .8)]:
        look = engine._node(kind='visual_look', label='Обзор' if detail == 0 else 'Подробный осмотр',
                            variant=variant['id'], detail=detail)
        engine._edge(target['id'], look['id'], 'visual_attention', weight)
        engine._edge(look['id'], variant['id'], 'visual_attention', 1)
    return variant['id']


def _part(engine: object, variant: dict, role: str, sample: dict) -> None:
    """Local fragments keep their positions, including repeated strokes."""
    part = engine._node(kind='visual_part', role=role, label='Значок' if role == 'icon' else 'Подпись')
    engine._edge(part['id'], variant['id'], 'visual_contains')
    pixels = bytes.fromhex(sample['data']); width, height = sample['width'], sample['height']
    for y in range(0, height, TILE):
        for x in range(0, width, TILE):
            w, h = min(TILE, width-x), min(TILE, height-y)
            data = bytes(pixels[(y+j)*width+x+i] for j in range(h) for i in range(w))
            fragment = engine._node(kind='visual_fragment', label=f'{role} {x}:{y}',
                                    rect=[x, y, x+w, y+h], data=data.hex())
            engine._edge(fragment['id'], part['id'], 'visual_contains')


def bind(engine: object, query: str, object_id: str, target: str) -> int:
    """Attach one command's motor target, never globally rename a Glaz class."""
    require(not engine.model['pending'] and engine.model['status'] not in ('running', 'waiting'),
            'Остановите исполнение перед привязкой')
    node = engine.node(target)
    require(node and node['kind'] == 'visual_object', 'Нет составного образа')
    from ..commands import command_signature
    command = engine.inspect(query)['command']; signature = command_signature(engine.model, command)
    equivalent = [c for c in engine.model['commands'] if command_signature(engine.model, c) == signature]
    paths = [_path(engine, c['first']) for c in equivalent]
    for path in paths:
        require(sum(s['action'].get('object') == object_id and s['action']['kind'] == 'click' for s in path) <= 1,
                'В команде несколько кликов по этому классу значков. Покажите отдельную команду для выбранного объекта.')
    steps = list({s['id']: s for path in paths for s in path}.values())
    selected = [s for s in steps if s['action'].get('object') == object_id]
    require(selected, 'У команды нет действий над выбранным объектом')
    for index, step in enumerate(steps[:-1]):
        if step['action']['kind'] == 'move' and steps[index+1] in selected:
            selected.append(step)
    for step in selected:
        step['action']['visual'] = target
        step['action']['visual_object'] = object_id
        engine.model['memory']['edges'] = [e for e in engine.model['memory']['edges']
            if not (e['kind'] == 'visual_ground' and e['from'] == step['id'])]
        engine._edge(step['id'], target, 'visual_ground', 1)
    engine.model.pop('perception', None)
    engine._event(dict(kind='visual-bind', target=target, command=query))
    return len(selected)


def _path(engine: object, first: str) -> list[dict]:
    """Read the existing learned sequence; do not invent a motor recipe."""
    result, seen, current = [], set(), first
    while current not in seen:
        seen.add(current); step = engine.node(current)
        require(step and step['kind'] == 'step', 'Повреждён путь команды')
        result.append(step)
        if step['action']['kind'] in ('finish', 'drive'):
            return result
        following = engine.edges(current)
        require(len(following) == 1, 'Неоднозначный путь команды')
        current = following[0]['to']
    raise ValueError('Цикл в пути команды')
