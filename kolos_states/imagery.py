"""Experiment 11: one content representation, independent internal/sensory drives.

A rate-based engineering abstraction, not a claim about exact human physiology.
No OS, language parser, simulator, or motor operation is imported here.
"""
import math
from .protocol import sensory_features, clone, compact, clamp, require

DEFAULTS = dict(decay=.5, internalGain=1, sensoryGain=1, threshold=.7)


def vertex(image, id, kind, label, **extra):
    if not any(n['id'] == id for n in image['nodes']):
        require(len(image['nodes']) < 6000, 'Лимит вершин образа')
        image['nodes'].append(dict(id=id, kind=kind, label=label, I=0, S=0, present=False, target=False, **extra))
    return id


def field_pattern(image, focus, value, memory):
    ids = [vertex(image, compact(['field', focus]), 'field', 'Поле '+focus, focus=focus)]
    previous = ids[0]
    for index, char in enumerate(value):
        symbol = next((n for n in memory['nodes'] if n['kind'] == 'symbol' and n['value'] == char), None)
        id = vertex(image, compact(['slot', focus, index, char]), 'slot', f"{index+1}: {'␣' if char == ' ' else char}",
                    focus=focus, index=index, char=char, memoryRef=symbol['id'] if symbol else None)
        if not any(e['from'] == previous and e['to'] == id for e in image['edges']):
            image['edges'].append(dict(to=id, kind='order', weight=1, **{'from': previous}))
        ids.append(id); previous = id
    end = vertex(image, compact(['end', focus, len(value)]), 'end', 'Конец: '+str(len(value)), focus=focus, length=len(value))
    if not any(e['from'] == previous and e['to'] == end for e in image['edges']):
        image['edges'].append(dict(to=end, kind='order', weight=1, **{'from': previous}))
    return ids+[end]


def pattern(image, goal, memory):
    if goal['kind'] == 'field':
        return field_pattern(image, goal['focus'], goal['value'], memory)
    n = next((n for n in memory['nodes'] if n['kind'] == 'state' and sorted(n['features']) == sorted(goal['features'])), None)
    require(n, 'Состояние образа ещё не наблюдалось')
    return [vertex(image, n['id'], 'state', n['label'], memoryRef=n['id'])]


def start(m, options=None):
    require(m.get('intent') and not m['pending'], 'Образу нужна цель без ожидающего действия')
    cfg = {**DEFAULTS, 'decay': m['config']['decay'], **(options or {})}
    for k, v in cfg.items():
        require(k in DEFAULTS and isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 1, 'Неверная настройка образа')
    require(cfg['threshold'] > 0 and cfg['decay'] < 1, 'Нужны положительный порог и затухание < 1')
    m['imagery'] = dict(schema='kolos-imagery/1', config=cfg, nodes=[], edges=[], patterns={}, mode='imagine', drive=True,
                         active=None, ready=0, match=0, gap=0, evidence=None, confirmations=[])
    for goal in m['intent']['goals']:
        m['imagery']['patterns'][goal['id']] = pattern(m['imagery'], goal, m['memory'])
    m['message'] = 'Образ задан. Моторика выключена: внутренний сигнал не подтверждает реальность.'


def control(m, command):
    image = m.get('imagery')
    require(image and m.get('intent'), 'Сначала создайте образ')
    require(not m['pending'], 'Сначала разрешите ожидающее действие')
    require(command in ('act', 'rest'), 'Неизвестное управление образом')
    image.update(mode='act' if command == 'act' else 'imagine', drive=command == 'act')
    m['intent'].update(episode=None, wave=0)
    m.update(entry=None, goalActivation={}, activation={}, status='running')
    m['message'] = 'Образ направляет действия. Подтверждение — только от среды.' if command == 'act' else 'Поддержка образа снята. I затухает; мир не меняется.'


def update(m, goal):
    image = m.get('imagery')
    if not image: return
    cfg = image['config']; desired = set(image['patterns'][goal['id']] if goal and goal['held'] else []); actual = set()
    obs = m.get('observed')
    if cfg['sensoryGain'] > 0 and obs and isinstance(obs.get('features'), list):
        n = next((n for n in m['memory']['nodes'] if n['kind'] == 'state' and sorted(n['features']) == sensory_features(obs['features'])), None)
        if n: actual.add(vertex(image, n['id'], 'state', n['label'], memoryRef=n['id']))
        if obs.get('focus') and isinstance(obs.get('output'), str) and len(obs['output']) <= 160:
            actual.update(field_pattern(image, obs['focus'], obs['output'], m['memory']))
        image['evidence'] = dict(source='external', version=obs.get('version'), focus=obs.get('focus'), output=obs.get('output'))
    else:
        image['evidence'] = None
    for n in image['nodes']:
        n.update(target=n['id'] in desired, present=n['id'] in actual)
        n['I'] = clamp(cfg['decay']*n['I']+(1-cfg['decay'])*(cfg['internalGain'] if n['target'] and image['drive'] else 0))
        n['S'] = clamp(cfg['decay']*n['S']+(1-cfg['decay'])*(cfg['sensoryGain'] if n['present'] else 0))
    relevant = [n for n in image['nodes'] if n['id'] in desired]
    image['active'] = goal['id'] if goal else None
    image['ready'] = min(n['I'] for n in relevant) if relevant else 0
    image['match'] = min(n['S'] if n['present'] else 0 for n in relevant) if relevant else 0
    image['gap'] = clamp(sum(max(0, n['I']-(n['S'] if n['present'] else 0)) for n in relevant)/len(relevant)) if relevant else 0


def satisfied(m):
    i = m.get('imagery')
    return bool(i and i['evidence'] and i['ready'] >= i['config']['threshold'] and i['match'] >= i['config']['threshold'])


def demand(m, goal):
    i = m.get('imagery')
    if not i: return 1
    ids = i['patterns'].get(goal['id'], [])
    return min(next((n['I'] for n in i['nodes'] if n['id'] == id), 0) for id in ids) if ids else 0


def confirmation(m, goal):
    i = m.get('imagery')
    if not i: return
    require(i['mode'] == 'act' and not m['pending'] and satisfied(m), 'Образ не является подтверждением')
    i['confirmations'].append(dict(goal=goal['id'], tick=m['tick'], evidence=clone(i['evidence']), vertices=clone(i['patterns'][goal['id']]), source='external'))
