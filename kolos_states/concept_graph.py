"""Learned many-view object ensembles. No aliases, OS input or screen mutation."""
from __future__ import annotations

import hashlib
import math
import re
from .protocol import clone, compact, require

KINDS = {'object_view', 'object_concept', 'object_scope'}
EDGES = {
    'object_member': {('object_view', 'object_concept')},
    'object_context': {('object_scope', 'object_concept')},
    'object_ground': {('object_concept', 'step')},
}


def node(memory: dict, identifier: str | None) -> dict | None:
    return next((n for n in memory['nodes'] if n['id'] == identifier), None)


def incoming(memory: dict, target: str, kind: str) -> list[dict]:
    return [e for e in memory['edges'] if e['to'] == target and e['kind'] == kind]


def registry(signatures: dict) -> dict[str, str]:
    """A reused numeric ID after a database clear is not the same sensory unit."""
    groups: dict[str, list] = {}
    for signature, ids in signatures.items():
        for identifier in ids:
            groups.setdefault('glaz.'+str(identifier), []).append(list(signature))
    return {key: hashlib.sha256(compact(sorted(value)).encode()).hexdigest()
            for key, value in groups.items()}


def scope(observed: dict) -> dict | None:
    """Stable context, not absolute coordinates, transient HWND or a desired goal."""
    if observed.get('own_focus') or not observed.get('context_valid', False):
        return None
    windows = sorted(f for f in observed['features'] if f.startswith('window:'))
    identity = observed.get('window_context', '')
    if not windows and not identity:
        return None
    return dict(windows=windows, window=identity, focus=observed['focus'])


def instances(observed: dict) -> list[dict]:
    """Use the complete instance list, before the old nearest-copy reduction."""
    return observed.get('object_instances', observed['icons'])


def valid_box(box: object) -> bool:
    return (isinstance(box, (list, tuple)) and len(box) == 4
            and all(type(x) in (int, float) and math.isfinite(x) and abs(x) < 100000 for x in box)
            and box[0] < box[2] and box[1] < box[3])


def pointed(observed: dict, icon: dict) -> bool:
    box = icon.get('bbox')
    return bool(valid_box(box) and box[0] <= observed['cursor']['x'] < box[2]
                and box[1] <= observed['cursor']['y'] < box[3])


def local_steps(memory: dict, step: dict) -> list[dict]:
    """Share only one contiguous shown MOVE/CHECK/CLICK/ENTER target segment."""
    expected = step['action']['object']; result = [step]; seen = {step['id']}
    for direction in ('back', 'forward'):
        current = step
        while True:
            links = [e for e in memory['edges'] if e['kind'] == 'next'
                     and e['to' if direction == 'back' else 'from'] == current['id']]
            if len(links) != 1:
                break
            other = node(memory, links[0]['from' if direction == 'back' else 'to'])
            if not other or other['id'] in seen or other['kind'] != 'step':
                break
            a = other['action']
            is_move = direction == 'back' and a['kind'] == 'move'
            if a.get('visual') or not (is_move or (a['kind'] in ('check', 'click', 'enter') and a['object'] == expected)):
                break
            result.append(other); seen.add(other['id']); current = other
            if is_move:
                break
    return result


def grounded(memory: dict, step_id: str, observed: dict) -> list[tuple[dict, dict, dict]]:
    context = scope(observed); result = []
    if context is None:
        return result
    for ground in incoming(memory, step_id, 'object_ground'):
        concept = node(memory, ground['from'])
        for gate in incoming(memory, concept['id'], 'object_context'):
            if node(memory, gate['from'])['scope'] == context:
                result.append((concept, gate, ground))
    return result


def evaluate(memory: dict, step_id: str, observed: dict, threshold: float) -> dict:
    """OR across alternative views; context and motor synapses are AND gates."""
    choices = grounded(memory, step_id, observed)
    if len(choices) != 1:
        return dict(candidates=[], reason='Контекст не изучен' if not choices else 'Неоднозначные ансамбли')
    concept, gate, ground = choices[0]; candidates = []
    catalogue = observed.get('object_registry', {})
    members = incoming(memory, concept['id'], 'object_member')
    for icon in instances(observed):
        for edge in members:
            view = node(memory, edge['from'])
            if view['object'] != icon['id'] or catalogue.get(icon['id']) != view['prototype']:
                continue
            usable = (valid_box(icon.get('bbox')) and not icon.get('ambiguous')
                      and not icon.get('ambiguous_reason') and icon.get('in_foreground', True))
            signal = min(edge['weight'], gate['weight'], ground['weight']) if usable else 0.0
            candidates.append(dict(id=icon['id'], bbox=clone(icon.get('bbox')), sensory=signal,
                                   member=edge['id'], view=view['id'], allowed=signal >= threshold and signal > 0))
    eligible = [c for c in candidates if c['allowed']]
    # Even a weaker second accepted appearance is still a second physical object.
    winner = eligible[0] if len(eligible) == 1 and len(candidates) == 1 else None
    return dict(concept=concept['id'], gate=gate['id'], ground=ground['id'],
                candidates=candidates, winner=winner,
                reason='Несколько экземпляров общего объекта' if len(candidates) > 1 else 'Нет достаточного сенсорного подтверждения')


def teach(engine: object, question: dict, observed: dict) -> str:
    """Called only after a validated answer; does not dispatch or complete a step."""
    memory = engine.model['memory']; step = engine.node(question['step'])
    choices = grounded(memory, step['id'], observed)
    require(len(choices) <= 1, 'Несколько ансамблей одного шага')
    if choices:
        concept = choices[0][0]
    else:
        require(sum(n['kind'] == 'object_concept' for n in memory['nodes']) < 128, 'Лимит общих объектов: 128')
        concept = engine._node(kind='object_concept', label='Объект '+question['expected']+' · '+question['query'],
                               expected=question['expected'])
        context = engine._node(kind='object_scope', label='Контекст объекта', scope=clone(question['scope']))
        engine._edge(context['id'], concept['id'], 'object_context', 1.0)
        for target in local_steps(memory, step):
            engine._edge(concept['id'], target['id'], 'object_ground', 1.0)
    require(len(incoming(memory, concept['id'], 'object_member')) < 32
            or any(node(memory, e['from'])['object'] == question['actual']
                   for e in incoming(memory, concept['id'], 'object_member')), 'Лимит видов общего объекта: 32')
    for identifier in (question['expected'], question['actual']):
        prototype = question['registry'][identifier]
        view = next((n for n in memory['nodes'] if n['kind'] == 'object_view'
                     and n['object'] == identifier and n['prototype'] == prototype), None)
        if view is None:
            view = engine._node(kind='object_view', label=identifier, object=identifier, prototype=prototype)
        edge = engine._edge(view['id'], concept['id'], 'object_member', 1.0 if identifier == question['expected'] else .9)
        if identifier == question['actual']:
            edge['weight'] = max(.9, edge['weight'])
    return concept['id']


def validate_node(n: dict, nodes: dict) -> None:
    require(isinstance(n.get('label'), str) and len(n['label']) <= 1024, 'Нет имени общего объекта')
    if n['kind'] in ('object_view', 'object_concept'):
        identifier = n.get('object' if n['kind'] == 'object_view' else 'expected')
        require(isinstance(identifier, str) and re.fullmatch(r'glaz\.\d+', identifier), 'Неверный зрительный ID')
    if n['kind'] == 'object_view':
        require(isinstance(n.get('prototype'), str) and re.fullmatch('[a-f0-9]{64}', n['prototype']), 'Нет отпечатка зрительного прототипа')
    if n['kind'] == 'object_scope':
        s = n.get('scope')
        require(isinstance(s, dict) and set(s) == {'windows', 'window', 'focus'}, 'Неверный контекст объекта')
        require(isinstance(s['windows'], list) and len(s['windows']) <= 16
                and all(isinstance(w, str) and w.startswith('window:') and len(w) <= 2048 for w in s['windows'])
                and isinstance(s['window'], str) and len(s['window']) <= 256
                and isinstance(s['focus'], str) and len(s['focus']) <= 2048
                and bool(s['window'] or s['windows']), 'Пустой или повреждённый контекст объекта')


def validate_topology(nodes: dict, edges: list[dict]) -> None:
    memory = dict(nodes=list(nodes.values()), edges=edges)
    for concept in nodes.values():
        if concept['kind'] != 'object_concept':
            continue
        members = incoming(memory, concept['id'], 'object_member')
        require(2 <= len(members) <= 32, 'Нужны независимые виды общего объекта')
        require(sum(nodes[e['from']]['object'] == concept['expected'] for e in members) == 1, 'Нет исходного вида общего объекта')
        require(len({nodes[e['from']]['object'] for e in members}) == len(members), 'Повтор зрительного ID в ансамбле')
        require(len(incoming(memory, concept['id'], 'object_context')) == 1, 'Нет однозначного контекста объекта')
        grounds = [e for e in edges if e['from'] == concept['id'] and e['kind'] == 'object_ground']
        require(bool(grounds), 'Ансамбль не связан с моторными шагами')
        for edge in grounds:
            step = nodes[edge['to']]; a = step['action']
            if a['kind'] == 'move':
                following = [e for e in edges if e['from'] == step['id'] and e['kind'] == 'next']
                require(len(following) == 1, 'Нет проверки после наведения на общий объект')
                a = nodes[following[0]['to']]['action']
            require(a['kind'] in ('check', 'click', 'enter') and a.get('object') == concept['expected']
                    and not a.get('visual'), 'Ансамбль связан с другим моторным объектом')
