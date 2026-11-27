"""Data boundary between the graph and a simulator/desktop observer.

An observation is evidence. A command to the OS is not evidence of success.
State identity excludes coordinates, output text, transient handles and timestamps.
"""
from __future__ import annotations
import copy
import json
import math
from typing import Any

SCHEMA = 'kolos-desktop-states/4'


def clone(value: Any) -> Any:
    return copy.deepcopy(value)


def persistent_graph(memory: dict) -> dict:
    """Persist learned topology/weights, never currents from a previous screen."""
    result = clone(memory)
    for node in result['nodes']:
        for key in ('sensory', 'eligibility', 'inhibition'):
            node.pop(key, None)
    return result


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def clamp(value: float) -> float:
    # JS Math.round (values here are nonnegative except before clipping).
    return max(0.0, min(1.0, math.floor(value * 1e9 + 0.5) / 1e9))


def require(condition: Any, message: str) -> None:
    if not condition:
        raise ValueError(message)


def action(raw: dict) -> dict:
    require(isinstance(raw, dict), 'Нет действия')
    kind = raw.get('kind')
    extra = {}
    if 'visual' in raw:
        require(kind in ('move', 'check', 'click', 'enter') and isinstance(raw['visual'], str)
                and 0 < len(raw['visual']) < 64, 'Неверная зрительная цель')
        require(isinstance(raw.get('visual_object'), str) and 0 < len(raw['visual_object']) <= 512,
                'Нет исходного объекта зрительной цели')
        extra = dict(visual=raw['visual'], visual_object=raw['visual_object'])
    if kind == 'move':
        x, y = raw.get('x'), raw.get('y')
        require(all(isinstance(v, (int, float)) and math.isfinite(v) and abs(v) <= 100000 for v in (x, y)), 'Координаты вне диапазона')
        return dict(kind=kind, x=round(x), y=round(y), **extra)
    if kind in ('check', 'click', 'enter'):
        obj = raw.get('object')
        require(isinstance(obj, str) and 0 < len(obj) <= 512, 'Нет идентификатора объекта')
        return dict(kind=kind, object=obj, **extra)
    if kind == 'key':
        value = raw.get('value')
        require(isinstance(value, str) and len(value) == 1 and value.isprintable(), 'Нужен один печатный символ')
        return dict(kind=kind, value=value)
    if kind == 'gui':
        binding = raw.get('binding')
        require(isinstance(binding, str) and 0 < len(binding) <= 100 and binding.isascii()
                and all(part.isidentifier() for part in binding.split('.')), 'Неверная привязка GUI')
        return dict(kind=kind, binding=binding)
    raise ValueError('Неизвестное действие')


def observation(raw: dict) -> dict:
    require(isinstance(raw, dict), 'Нет наблюдения')
    icons = raw.get('icons')
    require(isinstance(icons, list) and len(icons) <= 2000, 'Неверный список объектов')
    ids = set()
    for icon in icons:
        require(isinstance(icon, dict) and isinstance(icon.get('id'), str) and icon['id'] not in ids, 'Неоднозначный идентификатор объекта')
        ids.add(icon['id'])
        require(all(isinstance(icon.get(k), (float, int)) and math.isfinite(icon[k]) for k in ('x', 'y')), 'Нет координат объекта')
    for key in ('selected', 'focus', 'output'):
        require(isinstance(raw.get(key), str) and len(raw[key]) <= 20000, 'Неверное наблюдение: ' + key)
    cursor = raw.get('cursor', {})
    require(all(isinstance(cursor.get(k), (float, int)) and math.isfinite(cursor[k]) for k in ('x', 'y')), 'Нет наблюдаемого курсора')
    features = raw.get('features')
    require(isinstance(features, list) and all(isinstance(x, str) for x in features) and len(features) <= 4000, 'Нет признаков состояния')
    if 'gui_actions' in raw:
        gui_actions = raw['gui_actions']
        require(isinstance(gui_actions, list) and len(gui_actions) <= 200
                and all(isinstance(binding, str) for binding in gui_actions), 'Неверные доступные действия GUI')
    result = clone(raw)
    result['features'] = sorted(set(features))
    return result


def sensory_features(features: list[str]) -> list[str]:
    """Only external, informative inputs participate in ensemble identity."""
    return sorted({f for f in features if f not in ('focus:', 'selected:')
                   and not f.startswith('clicked:')})


def observation_key(obs: dict) -> str:
    return compact(sensory_features(obs['features']))


def mark_clicked(obs: dict, obj: str, icon: dict) -> dict:
    """Remember a motor event without inventing a visible or selected object."""
    result = clone(obs)
    result['features'] = sensory_features(result['features'])
    result['last_clicked'] = obj
    if icon.get('visual'):
        result['last_clicked_visual'] = dict(target=icon['visual'], bbox=clone(icon['bbox']))
    else:
        result.pop('last_clicked_visual', None)
    return result


def under(obs: dict, obj: dict) -> bool:
    x, y = obs['cursor']['x'], obs['cursor']['y']
    bounds = obj.get('bbox')
    if bounds:
        return bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]
    return abs(obj['x'] - x) <= 65 and abs(obj['y'] - y) <= 42


def click_continues(obs: dict, a: dict) -> bool:
    """A one-use motor selection is evidence for its exact following Enter only."""
    return (a['kind'] == 'enter' and obs.get('click_followup') == a
            and obs.get('last_clicked') == a.get('object')
            and not obs.get('click_followup_invalid'))


def guard(obs: dict, a: dict) -> str:
    if a['kind'] == 'enter' and obs.get('click_followup_invalid'):
        return obs['click_followup_invalid']
    if click_continues(obs, a):
        return ''
    if a.get('visual'):
        from .perception.guard import visual_guard
        return visual_guard(obs, a)
    if a['kind'] == 'move':
        return ''
    if a['kind'] == 'key':
        return '' if obs['focus'] else 'Нет наблюдаемого фокуса ввода'
    if a['kind'] == 'gui':
        return '' if a['binding'] in obs.get('gui_actions', ()) else 'Нет однозначной привязки GUI'
    # A confirmed click chose an instance already. Other visual matches of
    # its ID cannot undo that choice; Enter follows selection, not the pointer.
    if (a['kind'] == 'enter' and obs['selected'] in ('', a['object'])
            and obs.get('last_clicked') == a['object']):
        return ''
    icon = next((i for i in obs['icons'] if i['id'] == a.get('object')), None)
    if not icon:
        return obs.get('object_issues',{}).get(a.get('object')) or 'Не видна иконка ' + str(a.get('object'))
    if a['kind'] == 'enter':
        return '' if obs['selected'] == a['object'] or (not obs['selected'] and obs.get('last_clicked') == a['object']) else 'Не выделена иконка ' + a['object']
    hits = [i for i in obs['icons'] if under(obs, i)]
    return '' if len(hits) == 1 and hits[0]['id'] == a['object'] else 'Под курсором не ' + a['object']


def validate_record(record: dict) -> dict:
    require(isinstance(record, dict), 'Нет демонстрации')
    query = record.get('query')
    require(isinstance(query, str) and 0 < len(query) <= 160, 'Запрос: 1–160 символов')
    receipts = record.get('receipts')
    require(isinstance(receipts, list) and 0 < len(receipts) <= 100, 'Демонстрация: 1–100 действий')
    result = clone(record)
    seen = set()
    previous = None
    for index, r in enumerate(result['receipts'], 1):
        require(isinstance(r.get('id'), str) and r['id'] not in seen and r.get('ok') is True, 'Нужны уникальные успешные подтверждения')
        require('effect_observed' not in r or isinstance(r['effect_observed'], bool), 'Неверное подтверждение результата')
        seen.add(r['id'])
        r['action'] = action(r['action'])
        r['before'], r['after'] = observation(r['before']), observation(r['after'])
        reason = guard(r['before'], r['action'])
        require(not reason, f"Шаг {index} ({r['action']['kind']}): {reason}")
        if previous is not None:
            require(observation_key(previous) == observation_key(r['before']) and previous['output'] == r['before']['output'], 'Разрыв наблюдений демонстрации')
        if r['action']['kind'] == 'key':
            require(r['after']['focus'] == r['before']['focus'] and r['after']['output'] == r['before']['output'] + r['action']['value'], 'Наблюдение не подтверждает клавишу')
        if r['action']['kind'] == 'move':
            require(abs(r['after']['cursor']['x'] - r['action']['x']) <= 3 and abs(r['after']['cursor']['y'] - r['action']['y']) <= 3, 'Перемещение не подтверждено')
        previous = r['after']
    return result
