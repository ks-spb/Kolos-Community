"""Sensory and goal currents on the existing observation/ensemble connections.

No route table or environment semantics. Motor guards remain independent of
these graded currents: recognition is not permission to click.
"""
from .protocol import clamp, sensory_features, guard


def conflict(expected: list[str], actual: list[str]) -> bool:
    """Positive contradictory focus/selection/window evidence inhibits recall."""
    for prefix in ('focus:', 'selected:', 'window:'):
        left = {f for f in expected if f.startswith(prefix)}
        right = {f for f in actual if f.startswith(prefix)}
        if left and right and left.isdisjoint(right):
            return True
    return False


def support(memory: dict, state: dict, observed: dict) -> float:
    """Weighted fraction of learned inputs; unrelated new features do not dilute it."""
    actual = sensory_features(observed['features'])
    if not state or conflict(state['features'], actual):
        return 0.0
    labels = {n['id']: n.get('label') for n in memory['nodes'] if n['kind'] == 'observation'}
    inputs = [e for e in memory['edges'] if e['kind'] == 'observes' and e['to'] == state['id']]
    total = sum(e['weight'] for e in inputs)
    return clamp(sum(e['weight'] for e in inputs if labels.get(e['from']) in actual) / total) if total else 0.0


def sensory_tick(m: dict, flows: list) -> None:
    """Accumulate external evidence only; top-down demand cannot enter this current."""
    cfg = (m.get('intent') or {}).get('config',m['config']); observed = m['observed']
    for n in m['memory']['nodes']:
        if n['kind'] != 'state':
            continue
        drive = support(m['memory'], n, observed)
        n['sensory'] = clamp(cfg['decay'] * n.get('sensory', 0) + (1 - cfg['decay']) * drive)
        inputs = [e for e in m['memory']['edges'] if e['kind']=='observes' and e['to']==n['id']]
        total = sum(e['weight'] for e in inputs)
        labels = {f['id']: f.get('label') for f in m['memory']['nodes'] if f['kind']=='observation'}
        for e in inputs:
            if drive and labels.get(e['from']) in observed['features']:
                flows.append(dict(edge=e['id'],to=n['id'],value=e['weight'],term=(1-cfg['decay'])*e['weight']/total,
                                  aggregation='sensory',**{'from':e['from']}))


def demand_features(m: dict, step: dict) -> list[str]:
    """An interrupted motor step holds its missing sensory prerequisite."""
    a = step['action']
    if a['kind'] == 'drive':
        return ['focus:' + m['selectedCommand']['focus']]
    if a.get('object'):
        return [('selected:' if a['kind'] == 'enter' else 'visible:') + a['object']]
    return []


def seed_demand(m: dict, activity: dict, features: list[str], strength: float = 1) -> None:
    """Read back existing observes connections into experienced result ensembles."""
    needed = set(sensory_features(features))
    if not needed:
        return
    labels = {n['id']: n.get('label') for n in m['memory']['nodes'] if n['kind'] == 'observation'}
    for n in m['memory']['nodes']:
        if n['kind'] != 'state' or not needed.issubset(n['features']):
            continue
        weights = [e['weight'] for e in m['memory']['edges'] if e['kind'] == 'observes'
                   and e['to'] == n['id'] and labels.get(e['from']) in needed]
        if len(weights) == len(needed):
            activity[n['id']] = max(activity.get(n['id'], 0), clamp(strength * min(weights)))


def transition_candidates(m: dict, activity: dict, cfg: dict, threshold: float) -> list[dict]:
    """Combine bottom-up support, backward goal current and inhibitory traces."""
    nodes = {n['id']: n for n in m['memory']['nodes']}
    result = []
    for t in nodes.values():
        if t['kind'] != 'transition':
            continue
        source = nodes[t['from']]
        current = support(m['memory'], source, m['observed'])
        sensory = source.get('sensory', 0)
        first = nodes[t['first']]['action']
        ready = (first['kind'] == 'move' or
                 (any(i['id'] == first.get('object') for i in m['observed']['icons'])
                  if first['kind'] in ('check','click') else not guard(m['observed'], first)))
        allowed = ready and current >= cfg['threshold'] and sensory >= cfg['threshold']
        inhibition = cfg.get('errorGain', 1) * max(t.get('inhibition', 0), (m.get('intent') or {}).get('error', {}).get(t['id'], 0))
        live = .25 * sensory if allowed else 0
        history = .75 * activity.get(t['id'], 0)
        score = clamp(live + history - inhibition) if allowed else 0
        result.append(dict(id=t['id'], label=t['label'], a=score, input=live, history=history,
                           sensory=sensory, inhibition=inhibition if allowed else 1,
                           threshold=threshold, allowed=allowed and not m['refractory'].get(t['id'], 0),
                           reason='' if allowed else 'Недостаточно сенсорного возбуждения'))
    return result


def predicted(m: dict, state: dict | None, observed: dict) -> bool:
    """Prediction uses the same weighted evidence as recall, never coordinates."""
    return bool(state and support(m['memory'], state, observed) >= m['config']['threshold'])


def _orienting_inputs(memory: dict, step: dict) -> list[tuple[dict, list[dict]]]:
    """Read the shown MOVE -> CHECK -> CLICK associations backwards, without a route table."""
    nodes={n['id']:n for n in memory['nodes']};result=[]
    incoming=[e for e in memory['edges'] if e['kind']=='next' and e['to']==step['id']]
    for edge in incoming:
        previous=nodes[edge['from']];a=previous.get('action',{})
        if a.get('kind')=='move':result.append((previous,[edge]))
        elif step['action']['kind']=='click' and a==dict(kind='check',object=step['action']['object']):
            for before in memory['edges']:
                if before['kind']=='next' and before['to']==previous['id']:
                    move=nodes[before['from']]
                    if move.get('action',{}).get('kind')=='move':result.append((move,[before,edge]))
    return result


def orienting_choice(m: dict, step: dict, cfg: dict, flows: list) -> dict:
    """A blocked verification excites its learned movement; only a fresh check permits a click."""
    obs=m['observed'];a=step['action'];candidates=[];charging=False
    if a['kind'] not in ('check','click') or 'visible:'+a['object'] not in obs['features']:
        return dict(candidates=[])
    nodes={n['id']:n for n in m['memory']['nodes']}
    for move,links in _orienting_inputs(m['memory'],step):
        target=move['action']
        if abs(obs['cursor']['x']-target['x'])<=3 and abs(obs['cursor']['y']-target['y'])<=3:continue
        source=nodes[move['pre']];sensory=source.get('sensory',0);weight=1.0
        for edge in links:weight*=edge['weight']
        allowed=weight>0 and support(m['memory'],source,obs)>=cfg['threshold'] and sensory>=cfg['threshold']
        drive=weight*sensory if allowed else 0
        score=clamp(cfg['decay']*m['activation'].get(move['id'],0)+drive)
        m['activation'][move['id']]=score
        charging |= allowed and (drive>cfg['threshold']*(1-cfg['decay']) or score>=cfg['threshold'])
        inhibition=1 if m['refractory'].get(move['id'],0) or not allowed else 0
        candidates.append(dict(id=move['id'],label=move['label'],a=score,input=sensory,history=weight,
                               inhibition=inhibition,threshold=cfg['threshold'],allowed=allowed and not inhibition))
        for edge in links:
            flows.append(dict(edge=edge['id'],to=edge['from'],value=drive,term=drive,
                              aggregation='motor-demand',**{'from':edge['to']}))
    result=dict(candidates=candidates,charging=charging)
    ranks=sorted((c for c in candidates if c['allowed']),key=lambda c:-c['a'])
    if ranks and ranks[0]['a']>=cfg['threshold']:
        if len(ranks)>1 and ranks[0]['a']-ranks[1]['a']<cfg['margin']:result['ambiguous']=True
        else:result['winner']=nodes[ranks[0]['id']]
    return result


def decay_traces(m: dict) -> None:
    """Transient neuronal values are not restored on process startup."""
    for n in m['memory']['nodes']:
        if 'eligibility' in n:
            n['eligibility'] = clamp(n['eligibility'] * .90)
        if 'inhibition' in n:
            n['inhibition'] = clamp(n['inhibition'] * .995)


def clear_transients(m: dict) -> None:
    """Start a new attempt without carrying sensory evidence from a past screen."""
    from .object_concepts import clear
    clear(m)
    for n in m['memory']['nodes']:
        for key in ('sensory', 'eligibility', 'inhibition'):
            n.pop(key, None)
    m['experienceStart'] = len(m['receipts'])
