"""Receipt-gated plasticity and new experience in the existing graph types."""
from .protocol import clone, clamp, compact, observation_key, sensory_features, click_continues
from .dynamics import predicted
from .targeting import click_followup
from .visual import changed as visual_changed


def node(m: dict, id: str) -> dict | None:
    return next((n for n in m['memory']['nodes'] if n['id'] == id), None)


def new_node(m: dict, **spec) -> dict:
    mem = m['memory']; n = dict(id='n' + str(mem['serial']), **spec)
    mem['serial'] += 1; mem['nodes'].append(n)
    return n


def edge(m: dict, source: str, target: str, kind: str, weight: float) -> dict:
    mem = m['memory']
    old = next((e for e in mem['edges'] if e['from'] == source and e['to'] == target and e['kind'] == kind), None)
    if old:
        return old
    e = dict(id='e' + str(mem['serial']), to=target, kind=kind, weight=weight, **{'from': source})
    mem['serial'] += 1; mem['edges'].append(e)
    return e


def state(m: dict, obs: dict) -> dict:
    key = observation_key(obs)
    found = next((n for n in m['memory']['nodes'] if n['kind'] == 'state' and n['key'] == key), None)
    if found:
        return found
    features = sensory_features(obs['features'])
    s = new_node(m, kind='state', key=key, label='S' + str(sum(n['kind'] == 'state' for n in m['memory']['nodes'])), features=features)
    for feature in features:
        f = next((n for n in m['memory']['nodes'] if n['kind'] == 'observation' and n['label'] == feature), None)
        if f is None:
            f = new_node(m, kind='observation', label=feature)
        edge(m, f['id'], s['id'], 'observes', 1)
    return s


def effect_observed(r: dict) -> bool:
    """Movement, checks and a mere dispatch are never world-transition evidence."""
    return (r.get('ok') is True and r['action']['kind'] in ('click', 'enter', 'gui')
            and r.get('effect_observed', True)
            and bool(sensory_features(r['before']['features'])) and bool(sensory_features(r['after']['features']))
            and observation_key(r['before']) != observation_key(r['after']))


def unconfirmed_result(m: dict, p: dict, r: dict) -> bool:
    """A successful send with neither predicted nor observed result is still pending."""
    step=node(m,p.get('step'))
    followup=click_followup(m['memory'], step)
    if (r['ok'] and r.get('verified_by') == 'verified-target-click'
            and r.get('effect_observed') is False and not p.get('relocate')
            and followup is not None and followup == r['after'].get('click_followup')):
        return False
    if (r['ok'] and r.get('effect_observed') is True and click_continues(r['before'], r['action'])
            and visual_changed(r['before'], r['after'])):
        # Image-only input has no UIA/window features in the frame-only baseline.
        # A witnessed Enter effect still completes its motor step; learning a
        # new state transition continues to require informative external features.
        return False
    return bool(r['ok'] and step and r['action']['kind'] in ('click','enter','gui')
                and not step.get('dispatch_only') and not effect_observed(r)
                and not predicted(m,node(m,step.get('post')),r['after']))


def actions(m: dict, t: dict) -> list[dict]:
    result = []; current = t['first']; seen = set()
    while current not in seen:
        seen.add(current); step = node(m, current)
        if not step:
            return []
        result.append(step['action'])
        if current == t['last']:
            return result
        links = [e for e in m['memory']['edges'] if e['kind'] == 'next' and e['from'] == current]
        if len(links) != 1:
            return []
        current = links[0]['to']
    return []


def remember(m: dict, seq: list[dict], *, exact: bool = False) -> tuple[dict | None, bool]:
    """Connect an observed context/result using only already executed motor steps."""
    before, after = seq[0]['before'], seq[-1]['after']
    if not sensory_features(before['features']) or not sensory_features(after['features']):
        return None, False
    if any(r['action'].get('visual') and not _visual_ground(m, r) for r in seq):
        return None, False
    signature = compact([r['action'] for r in seq if r['action']['kind'] not in ('move','check')])
    endpoints = None
    if exact:
        # Symbolic lessons have exact endpoint identities and need no perceptual similarity scan.
        keys = observation_key(before), observation_key(after)
        states = {n['key']: n['id'] for n in m['memory']['nodes'] if n['kind'] == 'state' and n['key'] in keys}
        endpoints = tuple(states.get(key) for key in keys)
    for t in m['memory']['nodes']:
        if t['kind'] != 'transition':
            continue
        matched = ((t['from'], t['to']) == endpoints if endpoints is not None else
                   predicted(m, node(m, t['from']), before) and predicted(m, node(m, t['to']), after))
        if matched and compact([a for a in actions(m, t) if a['kind'] not in ('move','check')]) == signature:
            return t, False
    # Reserve room transactionally. A full graph does not undo the physical receipt.
    required = len(seq) + 1 + sum(1 + len(sensory_features(r[k]['features'])) for r in seq for k in ('before', 'after'))
    if len(m['memory']['nodes']) + required > 5000:
        m['audit'].append(dict(kind='learning-limit', request=seq[-1]['id']))
        return None, False
    source, target = state(m, before), state(m, after)
    first = previous = None
    for r in seq:
        a = r['action']; pre, post = state(m, r['before']), state(m, r['after'])
        step = new_node(m, kind='step', label=a['kind'].upper() + ' ' + a.get('object', ''),
                        action=clone(a), pre=pre['id'], post=post['id'],
                        dispatch_only=r.get('effect_observed') is False, visual_ack=r.get('verified_by') == 'visual-change')
        ground = _visual_ground(m, r)
        if ground:
            edge(m, step['id'], a['visual'], 'visual_ground', ground['weight'])
        if previous:
            edge(m, previous, step['id'], 'next', m['config']['weight'])
        first = first or step['id']; previous = step['id']
    t = new_node(m, kind='transition', label=seq[-1]['action']['kind'].upper() + ' ' + seq[-1]['action'].get('object', ''),
                 first=first, last=previous, to=target['id'], **{'from': source['id']})
    edge(m, target['id'], t['id'], 'backward', m['config']['weight'])
    edge(m, t['id'], source['id'], 'backward', 1)
    edge(m, source['id'], t['id'], 'applicable', 1)
    edge(m, t['id'], previous, 'experienced', 1)
    edge(m, t['id'], first, 'starts', m['config']['weight'])
    return t, True


def _visual_ground(m: dict, receipt: dict) -> dict | None:
    """Copy only the executed step's learned grounding into a new experience."""
    return next((e for e in m['memory']['edges'] if e['kind'] == 'visual_ground'
                 and e['from'] == receipt.get('step') and e['to'] == receipt['action'].get('visual')), None)


def acknowledge(m: dict, p: dict, receipt: dict) -> dict:
    """Called exactly once after guard/delta validation, in both execution modes."""
    r = clone(receipt); r['step'] = p.get('step'); r['concept_used'] = bool(p.get('object_concept')); m['receipts'].append(r)
    step = node(m, p.get('step')); result = dict(changes=[], learned=None)
    if not r['ok']:
        m['experienceStart'] = len(m['receipts']); return result
    if p.get('relocate') or p.get('source'):
        if p.get('source'):
            m['experienceStart'] = len(m['receipts'])
        return result
    if not step or not effect_observed(r):
        return result
    expected = node(m, step.get('post'))
    from .object_concepts import result_matches, outcome
    matched = (result_matches(m, expected, r['after'], p['object_concept'])
               if p.get('object_concept') else predicted(m, expected, r['after']))
    if p.get('object_concept'): result['conceptMatched'] = matched
    result['changes'] = adjust_links(m, step, matched)
    result['changes'].extend(outcome(m, p, r, matched))
    start = m.get('experienceStart', 0); seq = m['receipts'][start:]
    # A changed outside observation breaks temporal credit assignment.
    for i in range(len(seq) - 1, 0, -1):
        if observation_key(seq[i-1]['after']) != observation_key(seq[i]['before']):
            seq = seq[i:]; break
    if (m['config'].get('plasticity', 1) and seq and all(x.get('step') for x in seq)
            and not any(x.get('concept_used') for x in seq)):
        t, created = remember(m, seq)
        if created:
            result['learned'] = t['id']
    m['experienceStart'] = len(m['receipts'])
    evidence=clone(r)
    for key in ('before','after'):evidence[key].pop('visual_sample',None)
    m['audit'].append(dict(kind='experience', request=r['id'], receipt=evidence, matched=matched, **clone(result)))
    return result


def adjust_links(m: dict, step: dict, matched: bool) -> list[dict]:
    """The third factor changes causal outcome links, never command ordering."""
    changes = []
    transitions = [n for n in m['memory']['nodes'] if n['kind'] == 'transition' and n['last'] == step['id']]
    for t in transitions:
        if not matched:
            t['inhibition'] = 1
        if not m['config'].get('plasticity', 1):
            continue
        e = next(e for e in m['memory']['edges'] if e['kind'] == 'backward' and e['to'] == t['id'])
        old = e['weight']; eligibility = step.get('eligibility', 0)
        delta = m['config'].get('learningRate', .05) * eligibility * ((1 - old) if matched else -old)
        e['weight'] = clamp(old + delta)
        changes.append(dict(edge=e['id'], before=old, after=e['weight'], eligibility=eligibility))
    return changes
