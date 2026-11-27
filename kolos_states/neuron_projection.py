"""Read-only presentation of real engine snapshots; no engine/motor imports.

A/C and I/S stay distinct. Only recorded flows and explicitly labelled equation
terms animate. Image order edges are structure, never an invented pulse path.
"""
from __future__ import annotations
from copy import deepcopy
import json
import math
from .protocol import sensory_features


def number(value):
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else 0.0


def project_neurons(model: dict, event: dict | None = None, previous: dict | None = None) -> dict:
    m = model; ev = event or {}; before = previous or {}
    memory = m.get('memory') or {'nodes': [], 'edges': []}
    image = m.get('imagery') or {}; intent = m.get('intent') or {}
    cfg = intent.get('config') or m.get('config') or {}
    nodes = {}; edges = []
    candidates = {c['id']: c for c in ev.get('candidates', []) if 'id' in c}
    old_images = {n['id']: n for n in (before.get('imagery') or {}).get('nodes', [])}
    old_occ = {q['id']: q for q in before.get('occ', [])}

    def node(id, **values):
        if id not in nodes:
            nodes[id] = dict(id=id, label=id, kind='', group='memory', A=None,
                             C=None, I=None, S=None, T=0, R=0, threshold=None,
                             current=False, winner=False, held=None)
        nodes[id].update(values)
        return nodes[id]

    def edge(id, source, target, **values):
        edges.append(dict(id=id, source=source, target=target,
                          kind=values.pop('kind', ''), weight=values.pop('weight', None),
                          flow=values.pop('flow', None), term=values.pop('term', None),
                          provenance=values.pop('provenance', 'structure'), **values))

    observed = m.get('observed') or {}
    for n in memory.get('nodes', []):
        id = n['id']; c = candidates.get(id, {})
        group = ('world' if n['kind'] in ('state', 'transition') else
                 'actions' if n['kind'] in ('step','episode_step','episode_finish') else
                 'input' if n['kind'] in ('symbol', 'motor') else 'memory')
        a = m.get('goalActivation', {}).get(id, m.get('activation', {}).get(id))
        node(id, label=n.get('label', n.get('value', id)), kind=n['kind'], group=group,
             A=a, S=n.get('sensory'), C=c.get('a'), threshold=c.get('threshold'),
             current=n['kind'] == 'state' and n.get('features', []) == sensory_features(observed.get('features', [])),
             winner=ev.get('winner') == id, T=m.get('trace', {}).get(id, 0),
             R=m.get('refractory', {}).get(id, 0), inhibition=c.get('inhibition',n.get('inhibition',0)),
             eligibility=n.get('eligibility',0), calculation=deepcopy(c), stored=deepcopy(n))
    episode = m.get('episode') or {}
    for rid, runtime_id in episode.get('bindings', {}).items():
        if rid in nodes:nodes[rid].update(current=True, runtime_id=runtime_id)
    for slot_id, value in episode.get('working', {}).items():
        if slot_id in nodes:nodes[slot_id].update(current=True, working=deepcopy(value))
    for n in image.get('nodes', []):
        old = old_images.get(n['id'], {})
        node(n['id'], label=n['label'], kind=n['kind'], group='world' if n['kind'] == 'state' else 'image',
             I=n['I'], S=n['S'], oldI=old.get('I'), oldS=old.get('S'),
             threshold=image['config']['threshold'], present=n['present'], target=n['target'],
             decay=image['config']['decay'], stored=deepcopy(n))
    changed = bool(previous and m.get('tick') == before.get('tick', -1) + 1 and m.get('attempt') == before.get('attempt'))
    if image:
        ic = image['config']
        node('view:internal', label='Образ · источник I', kind='source', group='image', A=ic['internalGain'] if image['drive'] else 0)
        node('view:external', label='Среда · источник S', kind='source', group='image', A=ic['sensoryGain'] if image.get('evidence') else 0)
        for n in image['nodes']:
            for channel, active, gain in [('I', n['target'] and image['drive'], ic['internalGain']), ('S', n['present'], ic['sensoryGain'])]:
                if (channel == 'I' and n['target']) or (channel == 'S' and (n['present'] or n['S'] > 0)):
                    edge('view:' + channel + ':' + n['id'], 'view:internal' if channel == 'I' else 'view:external', n['id'],
                         kind=channel, weight=1-ic['decay'], flow=gain*(1-ic['decay']) if changed and active and m.get('phase') == 'intent' else None,
                         provenance='equation', note='Прямой вход из уравнения, не выученный синапс.')
        for i, e in enumerate(image.get('edges', [])):
            edge('view:order:' + str(i), e['from'], e['to'], kind='order', weight=e['weight'], note='Только порядок. Импульс I/S по этой связи не вычисляется.')
    for g in intent.get('goals', []):
        node(g['id'], label='Цель: ' + g.get('value', 'состояние'), kind='goal', group='goals', A=g.get('a'),
             held=g['held'], current=intent.get('active') == g['id'], stored=deepcopy(g))
        for target in g.get('targets', []):
            edge('view:goal:' + g['id'] + ':' + target, g['id'], target, kind='goal-drive',
                 flow=(image.get('ready', 1) if intent.get('active') == g['id'] and ev.get('kind') in ('spread', 'route', 'imagery-wave') else None),
                 provenance='equation', note='Поддержка состояния целью.')
        if g.get('previous'):
            edge('view:goal-inhibition:' + g['id'], g['previous'], g['id'], kind='inhibition',
                 flow=1.5*cfg.get('goalInhibition', 1) if changed and any(x['id']==g['previous'] and x['held'] for x in intent['goals']) else None,
                 provenance='equation', note='Незавершённая цель тормозит следующую.')
    for id, a in intent.get('error', {}).items():
        node('view:error:' + id, label='Ошибка ' + id, kind='error', group='world', A=a)
        edge('view:error-edge:' + id, 'view:error:' + id, id, kind='inhibition', flow=candidates.get(id, {}).get('inhibition'), provenance='equation')
    for i, q in enumerate(m.get('occ', [])):
        c = candidates.get(q['id'], {})
        node(q['id'], label=f"{i+1}: {q['value']}", kind='occurrence', group='input', A=q.get('a'), C=c.get('a'),
             held=q['held'], threshold=c.get('threshold', cfg.get('threshold')), winner=ev.get('winner') == q['id'],
             calculation=deepcopy(c), stored=deepcopy(q))
        symbol = next((n for n in memory['nodes'] if n['kind']=='symbol' and n.get('value')==q['value']), None)
        motor = next((e for e in memory['edges'] if e['kind']=='corresponds' and symbol and e['from']==symbol['id']), None)
        if motor:
            edge('view:bind:' + q['id'], motor['to'], q['id'], kind='motor-drive', weight=motor['weight'],
                 flow=number(c.get('input'))+number(c.get('history')) if c else None, provenance='equation', note='Вход и опыт из расчёта кандидата.')
        prior = next((x for x in m.get('occ', []) if x.get('next')==q['id']), None)
        if prior:
            edge('view:inhibit:' + q['id'], prior['id'], q['id'], kind='inhibition', flow=c.get('inhibition'), provenance='equation')
    for e in memory.get('edges', []):
        flows = [f for f in ev.get('flows', []) if f.get('edge') == e['id']]
        c = candidates.get(e['to'], {})
        flow = sum(number(f.get('value')) for f in flows) if flows else None
        term = sum(number(f['term']) for f in flows) if flows and all('term' in f for f in flows) else None
        origin = 'recorded' if flows else 'structure'
        if flow is None and e['kind'] in ('starts','next') and 'history' in c:
            flow=c['history']; origin='equation'
        edge(e['id'], e['from'], e['to'], kind=e['kind'], weight=e['weight'], flow=flow, term=term, provenance=origin,
             note='Передача из журнала; term — вклад после конкуренции/затухания.' if flows else 'Связь памяти; без записанной передачи не анимируется.')
    lm = m.get('languageMemory') or {}
    for n in lm.get('nodes', []):
        node(n['id'], label=n.get('label', n.get('char', n['kind'])), kind=n['kind'], group='language', stored=deepcopy(n), T=(m.get('language') or {}).get('trace', {}).get(n['id'], 0))
    for e in lm.get('edges', []):
        edge(e['id'], e['from'], e['to'], kind=e['kind'], weight=e['weight'])
    if m.get('phase')=='language' or str(ev.get('kind','')).startswith('language-'):
        for c in candidates.values():
            if not c.get('edge'): continue
            node(c['id'], label=c.get('label','Чтение'), kind='language-candidate', group='language', A=c['a'], C=c['a'], threshold=c.get('threshold'), winner=ev.get('winner')==c['id'], calculation=deepcopy(c))
            e = next((e for e in lm.get('edges', []) if e['id']==c['edge']), None)
            if e: edge('view:language:' + c['id'], e['from'], c['id'], kind='language-charge', weight=e['weight'], flow=c['a'], provenance='equation', note='Накопленная активация кандидата, не синаптический ток.')
    from .perception.projection import project as project_visual
    project_visual(m, node, edge)
    current = m.get('objectCurrents') or {}
    for original in memory.get('nodes', []):
        if original['kind'].startswith('object_'):
            identifier = original['id']
            active = identifier == current.get('concept')
            node(identifier, group='visual', I=current.get('I') if active else None,
                 S=current.get('S') if active else (1.0 if identifier == current.get('view') else 0.0),
                 A=current.get('A') if active else None,
                 threshold=m['config']['threshold'], current=active)
    if m.get('objectQuestion'):
        q=m['objectQuestion']
        node('view:object-question', label=q['expected']+' → '+q['actual']+' · нужен ответ',
             kind='object-question',group='visual',I=current.get('I'),S=0.0,
             held=True,stored=deepcopy(q))
    for n in nodes.values():
        n['energy'] = max(number(n[k]) for k in ('A', 'C', 'I', 'S'))
    return dict(tick=m.get('tick',0), revision=m.get('revision'), attempt=m.get('attempt'),
                status=m.get('status',''), message=m.get('message',''), event=deepcopy(ev), query=m.get('query',''),
                nodes=list(nodes.values()), edges=[e for e in edges if e['source'] in nodes and e['target'] in nodes],
                observed=deepcopy(observed), pending=deepcopy(m.get('pending')), ready=image.get('ready'), match=image.get('match'))


def group_edges(edges):
    groups = {}
    for e in edges:
        key = (e['source'], e['target'], e['kind'], e['provenance'])
        if key not in groups:
            groups[key] = dict(e, ids=[], members=[], flow=None, term=None)
        g = groups[key]; g['ids'].append(e['id']); g['members'].append(e)
        for k in ('flow','term'):
            if e.get(k) is not None: g[k] = (g[k] or 0) + e[k]
    return list(groups.values())
