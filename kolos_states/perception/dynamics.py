"""Leaky visual activation and learned attention on the existing graph."""
from __future__ import annotations

from ..protocol import clamp, clone, click_continues
from .matching import evaluate, winner
from .types import views
from .help import RETRAINING_HINT


def runtime(model: dict, target: str) -> dict:
    """Each attempt keeps separate currents for the live candidate instances."""
    current = model.get('perception')
    if not current or current['target'] != target:
        current = dict(target=target, I=0.0, ticks=0, seen=[], requests=[],
                       charges={}, candidates=[], neurons={}, flows=[], winner=None)
        model['perception'] = current
    return current


def attention(model: dict, target: str, current: dict) -> list[dict]:
    """Novel views compete through learned weights; equally driven views are all inspected."""
    memory, cfg = model['memory'], model['config']; proposals = []
    incoming = {e['to']: e['weight'] for e in memory['edges']
                if e['from'] == target and e['kind'] == 'visual_attention'}
    for view in views(memory, target):
        score = current['I']*incoming.get(view['id'], 0)
        visited = view['id'] in current['seen']
        proposals.append(dict(**view, a=0.0 if visited else score, input=score,
                              inhibition=score if visited else 0.0, allowed=score >= cfg['threshold']))
    eligible = [v for v in proposals if v['allowed'] and v['id'] not in current['seen']]
    best = max((v['a'] for v in eligible), default=0)
    selected = {v['id'] for v in eligible if best-v['a'] < cfg['margin']}
    selected.update(v['id'] for v in proposals if v['detail'] == 1 and v['id'] in current['seen'])
    current['attention'] = proposals
    return [v for v in views(memory, target) if v['id'] in selected]


def advance(model: dict, step: dict) -> dict:
    """Demand can direct attention but never substitute for missing sensory evidence."""
    target = step['action']['visual']; current = runtime(model, target); cfg = model['config']
    grounding = [e['weight'] for e in model['memory']['edges']
                 if e['kind'] == 'visual_ground' and e['from'] == step['id'] and e['to'] == target]
    drive = min(grounding) if grounding and model.get('heldGoal') else 0.0
    current['I'] = clamp(cfg['decay']*current['I']+(1-cfg['decay'])*drive)
    current['ticks'] += 1
    observed = model['observed']; evidence = observed.get('perception_samples', {})
    current['seen'] = sorted(set(current['seen']) | set(evidence.get('views', {})))
    current['requests'] = attention(model, target, current)
    scored = evaluate(model['memory'], target, evidence)
    _accumulate(model, current, scored)
    # A previous location's charge cannot break a tie in the current pixels.
    sensory = [dict(c, a=c['sensory']) for c in current['candidates']]
    chosen = winner(sensory, cfg) if scored['complete'] and drive > 0 else None
    mature = chosen and current['charges'].get(chosen['id'], 0) >= cfg['threshold']
    current['winner'] = chosen['id'] if mature and current['I'] >= cfg['threshold'] else None
    if current['winner']:
        return dict(ready=True, binding=dict(target=target, bbox=chosen['bbox'], score=chosen['a'],
                    frame=observed.get('version'), session=observed.get('session'),
                    captured_at=observed.get('captured_at'), view=chosen['view']))
    settled = scored['complete'] and all(abs(c['a']-c['sensory']) < .01 for c in current['candidates'])
    return dict(ready=False, help=settled or bool(evidence.get('reason')) or current['ticks'] >= cfg['timeout'],
                reason=evidence.get('reason', ''))


def _accumulate(model: dict, current: dict, scored: dict) -> None:
    """Past activity loses evidential force immediately when current support disappears."""
    cfg = model['config']; charges = {}; candidates = []; neurons = {}; flows = []
    for candidate in scored['candidates']:
        key = candidate['id']; sensory = candidate['sensory']
        a = clamp(cfg['decay']*current['charges'].get(key, 0)+(1-cfg['decay'])*sensory)
        charges[key] = a
        candidate.update(a=min(a, sensory), label='Объект '+key, allowed=sensory >= cfg['threshold'],
                         threshold=cfg['threshold'], inhibition=1-sensory)
        candidates.append(candidate)
        for node, signal in candidate['trace'].items():
            neurons[node+'@'+key] = dict(memoryRef=node, instance=key, S=signal, I=current['I'],
                                        present=signal > 0, inhibition=1-signal)
    for edge in model['memory']['edges']:
        if not edge['kind'].startswith('visual_'):
            continue
        for c in candidates:
            if edge['from'] in c['trace'] and edge['to'] in c['trace']:
                flows.append(dict(edge=edge['id'], **{'from': edge['from']}, to=edge['to'],
                                  value=min(edge['weight'], c['trace'][edge['from']]), instance=c['id']))
    for candidate in candidates:
        candidate.pop('trace', None)
    current.update(charges=charges, candidates=candidates, neurons=neurons, flows=flows)


def apply_binding(observed: dict, action: dict, proof: dict) -> dict:
    """Expose only this command's resolved instance to the existing motor protocol."""
    result = clone(observed); obj = action.get('object', action.get('visual_object', ''))
    l, t, r, b = proof['bbox']
    icon = dict(id=obj, x=round((l+r)/2), y=round((t+b)/2), bbox=proof['bbox'], visual=proof['target'])
    result['icons'] = [i for i in result['icons'] if i['id'] != obj]+[icon]
    result.setdefault('visual_bindings', {})[proof['target']] = clone(proof)
    result.setdefault('object_issues', {}).pop(obj, None)
    return result


def before_step(model: dict, step: dict, event: dict) -> bool:
    """Suspend the same motor step for attention or help, without invoking old-coordinate recovery."""
    if step and step['action']['kind'] == 'enter':
        if model['observed'].get('click_followup_invalid'):
            model.update(status='needs-help', message=model['observed']['click_followup_invalid']+
                         '. Автоматического повторного клика нет.')
            event['kind']='click-continuation-lost'
            return True
        if click_continues(model['observed'], step['action']):
            if model.get('perception'):
                model['perception']['requests']=[]
            return False
    if not step or not step['action'].get('visual'):
        return False
    result = advance(model, step); current = model['perception']
    event.update(kind='visual-attention', candidates=clone(current['candidates']), flows=clone(current['flows']))
    if result['ready']:
        model['observed'] = apply_binding(model['observed'], step['action'], result['binding'])
        if step['action']['kind'] == 'enter':
            from .guard import visual_guard
            if visual_guard(model['observed'], step['action']):
                model.update(status='needs-help', message='Клик уже выполнен, но выбор этого экземпляра больше не подтверждён. '
                             'Проверьте экран; автоматического повторного клика нет.')
                event['kind'] = 'visual-help'
                return True
        return False
    model['message'] = 'Рассматриваю значок и подпись; цель удерживается.'
    if result.get('help'):
        model.update(status='needs-help', message=RETRAINING_HINT)
        if result.get('reason'):
            model['message'] = result['reason']+'. Цель удерживается; действия не отправлены.'
        event['kind'] = 'visual-help'
    return True
