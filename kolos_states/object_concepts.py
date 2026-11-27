"""Context-gated common objects, teacher questions and independently guarded input."""
from __future__ import annotations

import math
import time
import uuid
from . import concept_graph as graph
from .ipc import MAX_OBSERVATION_AGE
from .protocol import clone, clamp, compact, require, click_continues

QUESTION_TTL = 120.0


def fresh(obs: dict, *, now: float | None = None) -> bool:
    stamp = obs.get('captured_at'); now = time.time() if now is None else now
    return (type(stamp) in (int, float) and math.isfinite(stamp)
            and -.1 <= now-stamp <= MAX_OBSERVATION_AGE
            and isinstance(obs.get('session'), str) and bool(obs['session'])
            and type(obs.get('version')) is int and bool(obs.get('foreground'))
            and isinstance(obs.get('monitor'), dict) and graph.scope(obs) is not None
            and isinstance(obs.get('window_context'), str) and bool(obs['window_context']))


def clear(model: dict) -> None:
    for key in ('objectQuestion', 'objectCurrents', 'objectBinding', 'objectDeclines'):
        model.pop(key, None)


def same_context(obs: dict, proof: dict) -> bool:
    return (fresh(obs) and graph.scope(obs) == proof['scope']
            and obs['session'] == proof['session'] and obs['foreground'] == proof['foreground']
            and obs['monitor'] == proof['monitor'])


def _candidate(obs: dict, expected: str, *, pointed: bool = True, actual: str | None = None) -> dict | None:
    if not fresh(obs) or not obs.get('recognition_complete'):
        return None
    known = obs.get('object_registry', {}); icons = graph.instances(obs)
    if expected not in known or any(i['id'] == expected for i in icons) or expected in obs.get('object_issues', {}):
        return None
    hits = [i for i in icons if (graph.pointed(obs, i) if pointed else i['id'] == actual)]
    if len(hits) != 1:
        return None
    candidate = hits[0]
    if (candidate['id'] == expected or candidate['id'] not in known
            or sum(i['id'] == candidate['id'] for i in icons) != 1
            or candidate.get('ambiguous') or candidate.get('ambiguous_reason')
            or not candidate.get('in_foreground', True)
            or not graph.valid_box(candidate.get('bbox'))):
        return None
    return candidate


def _current(model: dict, step: dict, identity: str) -> dict:
    current = model.get('objectCurrents')
    if not current or current['key'] != identity or current['step'] != step['id']:
        current = dict(key=identity, step=step['id'], I=0.0, S=0.0, A=0.0, stable=0,
                       frame=None, captured_at=None, flows=[], candidates=[])
        model['objectCurrents'] = current
    return current


def _advance(current: dict, obs: dict, drive: float, cfg: dict) -> None:
    current['I'] = clamp(cfg['decay']*current['I']+(1-cfg['decay']))
    # A repeated cached frame is not a second physical observation.
    if current['frame'] != obs['version'] and current['captured_at'] != obs['captured_at']:
        current['stable'] += 1
        current['S'] = clamp(cfg['decay']*current['S']+(1-cfg['decay'])*drive)
        current.update(frame=obs['version'], captured_at=obs['captured_at'])
    current['A'] = min(current['I'], current['S'], drive)


def _stop(model: dict, event: dict, reason: str) -> bool:
    model.update(status='needs-help', message=reason+'; цель удерживается, действие не отправлено.')
    event.update(kind='object-help', message=model['message'])
    return True


def _question(model: dict, step: dict, obs: dict, candidate: dict, event: dict) -> bool:
    expected = step['action']['object']; context = graph.scope(obs)
    identity = compact([step['id'], candidate['id'], candidate['bbox'], context, obs['foreground'], obs['session']])
    if identity in model.get('objectDeclines', []):
        return _stop(model, event, 'Этот вариант отклонён в текущей попытке. Укажите другую цель или выполните Reset')
    current = _current(model, step, identity)
    _advance(current, obs, 0.0, model['config'])
    event.update(kind='object-mismatch', candidates=[], flows=[])
    model['message'] = 'Ожидаю '+expected+', наблюдаю '+candidate['id']+'. Проверяю расхождение в свежем кадре.'
    if current['stable'] < 2 or current['I'] < model['config']['threshold']:
        return True
    model['objectQuestion'] = dict(id=uuid.uuid4().hex, issued=time.time(), attempt=model['attempt'],
        step=step['id'], query=model['query'], expected=expected, actual=candidate['id'],
        bbox=clone(candidate['bbox']), scope=context, session=obs['session'], foreground=obs['foreground'],
        monitor=clone(obs['monitor']), frame=obs['version'], captured_at=obs['captured_at'], key=identity,
        registry={key: obs['object_registry'][key] for key in (expected, candidate['id'])})
    model.update(status='needs-help', message='Ожидался '+expected+', но в выбранной области виден '+candidate['id']+
                 '. Это нужный объект для текущего действия?')
    event.update(kind='object-question', question=clone(model['objectQuestion']), message=model['message'])
    return True


def before_step(model: dict, step: dict | None, event: dict) -> bool:
    """A human answer never skips this fresh, current-instance decision."""
    model.pop('objectBinding', None)
    if not step or step['action'].get('visual') or not model.get('heldGoal') or model.get('pending'):
        return False
    a = step['action']; obs = model['observed']; memory = model['memory']; cfg = model['config']
    if a['kind'] not in ('move', 'check', 'click', 'enter'):
        return False
    grounds = graph.incoming(memory, step['id'], 'object_ground')
    follow = obs.get('concept_followup')
    if a['kind'] == 'enter' and follow and grounds:
        physical = dict(a, object=follow['actual'])
        eligible = graph.grounded(memory, step['id'], obs)
        if (click_continues(obs, physical) and same_context(obs, follow) and len(eligible) == 1
                and eligible[0][0]['id'] == follow['concept']
                and min(eligible[0][1]['weight'], eligible[0][2]['weight'],
                        next((e['weight'] for e in memory['edges'] if e['id'] == follow['member']), 0)) > 0
                and min(eligible[0][1]['weight'], eligible[0][2]['weight'],
                        next((e['weight'] for e in memory['edges'] if e['id'] == follow['member']), 0)) >= cfg['threshold']):
            model['objectBinding'] = dict(clone(follow), step=step['id'], continuation=True)
            return False
        return _stop(model, event, 'Контекст подтверждённого выбора изменился перед Enter')
    if not obs.get('object_registry'):
        return _stop(model, event, 'Нет свежего реестра зрительных образов') if grounds else False
    if grounds and (not fresh(obs) or not obs.get('recognition_complete')):
        return _stop(model, event, 'Нет свежего полного наблюдения общего объекта')
    scored = graph.evaluate(memory, step['id'], obs, cfg['threshold']) if grounds else {}
    chosen = scored.get('winner')
    if chosen:
        identity = compact([scored['concept'], chosen['id'], chosen['bbox'], graph.scope(obs), obs['foreground'], obs['session']])
        current = _current(model, step, identity)
        _advance(current, obs, chosen['sensory'], cfg)
        current.update(concept=scored['concept'], view=chosen['view'], candidates=clone(scored['candidates']))
        current['flows'] = [dict(edge=chosen['member'], **{'from': chosen['view']}, to=scored['concept'],
                                value=chosen['sensory'], term=chosen['sensory'], aggregation='object-or'),
                           dict(edge=scored['ground'], **{'from': scored['concept']}, to=step['id'],
                                value=current['A'], term=current['A'], aggregation='object-gate')]
        event.update(kind='object-charge', flows=clone(current['flows']), candidates=clone(scored['candidates']))
        if current['stable'] < 2 or current['A'] < cfg['threshold'] or current['A'] <= 0:
            model['message'] = 'Зрительный вид возбуждает общий ансамбль; проверяю устойчивость.'
            return True
        concept = graph.node(memory, scored['concept'])
        model['objectBinding'] = dict(concept=scored['concept'], step=step['id'], expected=concept['expected'],
            actual=chosen['id'], member=chosen['member'], prototype=obs['object_registry'][chosen['id']],
            bbox=clone(chosen['bbox']), scope=graph.scope(obs), session=obs['session'], foreground=obs['foreground'],
            monitor=clone(obs['monitor']), frame=obs['version'], captured_at=obs['captured_at'])
        if model.get('plan') and not model.get('detour') and model['plan']['suspended'] == step['id']:
            model.update(entry=step['id'], plan=None, goalActivation={}, activation={})
        return False
    if len(scored.get('candidates', [])) > 1:
        return _stop(model, event, 'Общему ансамблю соответствуют несколько объектов')
    if a['kind'] == 'move' and grounds and abs(obs['cursor']['x']-a['x']) <= 3 and abs(obs['cursor']['y']-a['y']) <= 3:
        links = [e for e in memory['edges'] if e['kind'] == 'next' and e['from'] == step['id']]
        following = graph.node(memory, links[0]['to']) if len(links) == 1 else None
        if following and following['action']['kind'] in ('check', 'click'):
            candidate = _candidate(obs, following['action']['object'])
            if candidate:
                return _question(model, following, obs, candidate, event)
    if a['kind'] in ('check', 'click'):
        candidate = _candidate(obs, a['object'])
        if candidate:
            return _question(model, step, obs, candidate, event)
    if grounds and scored.get('concept'):
        return _stop(model, event, scored.get('reason', 'Общий объект не подтверждён'))
    return False


def action_for(model: dict, step: dict, action: dict) -> dict:
    proof = model.get('objectBinding')
    if not proof or proof['step'] != step['id']:
        return action
    result = clone(action)
    if result['kind'] == 'move':
        l, t, r, b = proof['bbox']; result.update(x=round((l+r)/2), y=round((t+b)/2))
    else:
        result['object'] = proof['actual']
    return result


def attach_request(model: dict, request: dict) -> None:
    proof = model.get('objectBinding')
    if proof and proof['step'] == request.get('step'):
        request['object_concept'] = clone(proof)


def motor_reason(model: dict | None, observed: dict, request: dict) -> str:
    """Recompute graph evidence at the real motor boundary, not from a UI boolean."""
    proof = request.get('object_concept')
    if not proof:
        return ''
    if not model or not same_context(observed, proof):
        return 'Контекст общего объекта изменился перед действием'
    if observed['captured_at'] < proof['captured_at']:
        return 'Наблюдение общего объекта устарело'
    a = request['action']; cfg = model['config']
    if proof.get('continuation'):
        eligible = graph.grounded(model['memory'], proof['step'], observed)
        latched = observed.get('concept_followup')
        if (click_continues(observed, a) and latched and latched['concept'] == proof['concept']
                and latched['actual'] == proof['actual'] and len(eligible) == 1
                and eligible[0][0]['id'] == proof['concept']
                and min(eligible[0][1]['weight'], eligible[0][2]['weight'],
                        next((e['weight'] for e in model['memory']['edges'] if e['id'] == proof['member']), 0)) > 0
                and min(eligible[0][1]['weight'], eligible[0][2]['weight'],
                        next((e['weight'] for e in model['memory']['edges'] if e['id'] == proof['member']), 0)) >= cfg['threshold']):
            return ''
        return 'Нет подтверждённого продолжения общего объекта'
    if not observed.get('recognition_complete'):
        return 'Нет полного повторного сканирования'
    result = graph.evaluate(model['memory'], proof['step'], observed, cfg['threshold'])
    chosen = result.get('winner')
    if (not chosen or result['concept'] != proof['concept'] or chosen['member'] != proof['member']
            or chosen['id'] != proof['actual'] or chosen['bbox'] != proof['bbox']):
        return 'Объект изменился или стал неоднозначным перед действием'
    if a['kind'] == 'move':
        l, t, r, b = chosen['bbox']
        if not (l <= a['x'] < r and t <= a['y'] < b):
            return 'Наведение не связано с подтверждённым экземпляром'
    elif a.get('object') != chosen['id']:
        return 'Моторный ID не соответствует общему объекту'
    return ''


def answer(engine: object, identifier: str, choice: str, observed: dict | None = None) -> dict:
    m = engine.model; q = m.get('objectQuestion')
    require(choice in ('yes', 'no', 'unsure'), 'Неизвестный ответ')
    require(q and q['id'] == identifier and q['attempt'] == m['attempt']
            and not m['pending'] and m['heldGoal'] and m['status'] == 'needs-help', 'Вопрос уже не активен')
    require(0 <= time.time()-q['issued'] <= QUESTION_TTL, 'Вопрос устарел; повторите наблюдение через Пуск')
    if choice != 'yes':
        m.setdefault('objectDeclines', []).append(q['key'])
        m.pop('objectQuestion', None)
        m['message'] = 'Соответствие не обучено. Укажите другую цель или выполните Reset.'
        return engine._event(dict(kind='object-declined', choice=choice))
    require(observed is not None and same_context(observed, q)
            and observed['captured_at'] > q['captured_at'] and observed['version'] > q['frame'],
            'Вернитесь в исходное окно: нужен новый кадр того же контекста')
    candidate = _candidate(observed, q['expected'], pointed=False, actual=q['actual'])
    if candidate is None and observed.get('recognition_complete'):
        alternatives = [i for i in graph.instances(observed) if i['id'] in (q['expected'], q['actual'])]
        if (len(alternatives) == 1 and alternatives[0]['id'] == q['expected']
                and not alternatives[0].get('ambiguous') and not alternatives[0].get('ambiguous_reason')
                and alternatives[0].get('in_foreground', True)):
            candidate = alternatives[0]
    require(candidate and candidate['bbox'] == q['bbox']
            and all(observed['object_registry'].get(k) == v for k, v in q['registry'].items()),
            'Экземпляр или зрительная база изменились после вопроса')
    backup = clone(m); count = len(engine.events)
    try:
        concept = graph.teach(engine, q, observed)
        from .memory import validate_graph
        validate_graph(m['memory'], m['commands'], m.get('episodeCommands', []))
        m['audit'].append(dict(kind='object-teacher', question=q['id'], expected=q['expected'],
                               actual=q['actual'], scope=clone(q['scope']), concept=concept, choice='yes'))
        m.update(observed=clone(observed), status='running', entry=q['step'], plan=None,
                 goalActivation={}, activation={}, message='Соответствие сохранено. Результат действия ещё не подтверждён.')
        m.pop('objectQuestion', None); m.pop('objectCurrents', None); m.pop('objectBinding', None)
        return engine._event(dict(kind='object-taught', concept=concept))
    except Exception:
        engine.model = backup; del engine.events[count:]
        raise


def result_matches(model: dict, expected: dict | None, after: dict, proof: dict) -> bool:
    """Use learned sensory weights, without rewriting external observations."""
    if not expected or not expected.get('features'):
        return False
    from .protocol import sensory_features
    from .dynamics import conflict
    actual = set(sensory_features(after['features']))
    same = graph.scope(after) == proof['scope']
    def counterpart(feature: str) -> str:
        if same and feature in ('visible:'+proof['expected'], 'selected:'+proof['expected']):
            return feature.split(':', 1)[0]+':'+proof['actual']
        return feature
    compared = [counterpart(f) for f in expected['features']]
    if conflict(compared, list(actual)):
        return False
    labels = {n['id']: n.get('label') for n in model['memory']['nodes'] if n['kind'] == 'observation'}
    inputs = graph.incoming(model['memory'], expected['id'], 'observes')
    total = sum(e['weight'] for e in inputs)
    support = sum(e['weight'] for e in inputs
                  if labels.get(e['from']) in actual or counterpart(labels.get(e['from'], '')) in actual)
    return bool(total > 0 and support > 0 and support/total >= model['config']['threshold'])


def outcome(model: dict, pending: dict, receipt: dict, matched: bool) -> list[dict]:
    proof = pending.get('object_concept')
    if not proof or not receipt.get('ok') or not receipt.get('effect_observed') or not model['config'].get('plasticity', 1):
        return []
    edge = next((e for e in model['memory']['edges'] if e['id'] == proof['member']), None)
    if edge is None:
        return []
    old = edge['weight']; rate = model['config']['learningRate']
    edge['weight'] = clamp(old+rate*(1-old)) if matched else clamp(old*.5)
    record = dict(kind='object-outcome', concept=proof['concept'], actual=proof['actual'],
                  request=receipt['id'], matched=matched, edge=edge['id'], before=old, after=edge['weight'])
    model['audit'].append(record)
    return [record]


def refresh_request(model: dict | None, observed: dict, request: dict) -> None:
    """Resolve a hover-induced view change before input, within the same ensemble.

    The physical instance, context and operation remain fixed. Both the pending
    request and receipt name the newly observed ID; raw observation is untouched.
    """
    proof = request.get('object_concept')
    if (not model or not proof or proof.get('continuation')
            or request['action']['kind'] not in ('move', 'check', 'click')
            or not same_context(observed, proof) or not observed.get('recognition_complete')
            or observed['captured_at'] < proof['captured_at']):
        return
    pending = model.get('pending')
    if not pending or pending['id'] != request['id'] or pending['action'] != request['action']:
        return
    scored = graph.evaluate(model['memory'], proof['step'], observed, model['config']['threshold'])
    candidate = scored.get('winner')
    if (not candidate or scored['concept'] != proof['concept'] or candidate['bbox'] != proof['bbox']
            or candidate['id'] == proof['actual']):
        return
    old = proof['actual']
    proof.update(actual=candidate['id'], member=candidate['member'],
                 prototype=observed['object_registry'][candidate['id']],
                 captured_at=observed['captured_at'], frame=observed['version'])
    if request['action']['kind'] != 'move':
        request['action']['object'] = candidate['id']
    if pending is not request:
        pending['action'] = clone(request['action']); pending['object_concept'] = clone(proof)
    model['audit'].append(dict(kind='object-rebind-before-input', request=request['id'],
                              concept=proof['concept'], before=old, actual=candidate['id']))
