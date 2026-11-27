"""Goal dynamics over StateEngine's existing experience graph.

No simulator import, command parser, BFS/A* or stored complete route. Desired
observations are the external input. New choices use leaky weighted activities,
mutual inhibition of goal occurrences and mismatch-triggered inhibitory traces.
This is an engineering neural analogue, not a biophysical brain simulation.
"""
from . import imagery
from . import dynamics, experience, object_concepts
from .route_selection import route_decision
from .protocol import clone, clamp, compact, require, guard, observation_key, sensory_features, click_continues
from .targeting import motor_action

DEFAULTS = dict(decay=.5, discount=.90, stateCompetition=1, threshold=.70, routeThreshold=.55,
                margin=.04, goalGain=1, goalInhibition=1, errorDecay=.995, errorGain=1, traceDecay=.90,
                maxWaves=100, maxTicks=1800, refractory=2)


def node(m, id):
    return next((n for n in m['memory']['nodes'] if n['id'] == id), None)


def key(obs):
    return observation_key(obs)


def start(m, goals, config=None):
    require(not m['pending'], 'Сначала разрешите неподтверждённое действие')
    cfg = {**DEFAULTS, **{k: m['config'][k] for k in ('decay', 'discount', 'refractory', 'stateCompetition')}, **(config or {})}
    for k, v in cfg.items():
        require(k in DEFAULTS and isinstance(v, (int, float)) and 0 <= v, 'Неверная настройка сети цели')
        if k in ('maxTicks', 'maxWaves', 'refractory'):
            require(int(v) == v and v <= (20 if k == 'refractory' else 5000) and v >= (0 if k == 'refractory' else 1), 'Неверный предел')
        else:
            require(v <= 1, 'Коэффициент вне 0…1')
    require(isinstance(goals, list) and 0 < len(goals) <= 8, 'Нужно 1–8 желаемых результатов')
    encoded = []
    attempt = m['attempt'] + 1
    for i, g in enumerate(goals):
        require(isinstance(g, dict) and g.get('kind') in ('state', 'field'), 'Цель — состояние или поле')
        p = dict(id=f'intent:{attempt}:{i}', kind=g['kind'], held=True, a=0,
                 previous=f'intent:{attempt}:{i-1}' if i else None)
        if g['kind'] == 'state':
            require(isinstance(g.get('features'), list) and g['features'] and all(isinstance(s, str) for s in g['features']), 'Нет признаков цели')
            features = sensory_features(g['features'])
            states = [n for n in m['memory']['nodes'] if n['kind'] == 'state' and sorted(n['features']) == features]
            require(len(states) == 1, 'Желаемое состояние не наблюдалось или неоднозначно')
            p.update(features=clone(states[0]['features']), targets=[states[0]['id']])
        else:
            require(isinstance(g.get('focus'), str) and g['focus'] and isinstance(g.get('value'), str) and len(g['value']) <= 160, 'Нужны поле и строка до 160 символов')
            states = [n for n in m['memory']['nodes'] if n['kind'] == 'state' and 'focus:' + g['focus'] in n['features']]
            require(states, 'Это поле ещё не наблюдалось')
            alphabet = {n['value'] for n in m['memory']['nodes'] if n['kind'] == 'motor'}
            require(all(ch in alphabet for ch in g['value']), 'Нет прежнего опыта запрошенной клавиши')
            p.update(focus=g['focus'], value=g['value'], targets=[n['id'] for n in states])
        encoded.append(p)
    m['attempt'] = attempt
    m['imagery'] = None
    m['intent'] = dict(schema='kolos-goal-network/1', goals=encoded, config=cfg, active=None,
                       episode=None, wave=0, error={}, errorHistory=[], predictions=[],
                       acknowledged=[], goalHistory=[], lastCandidates=[], eligibility={})
    m.update(phase='intent', status='running', tick=0, heldGoal=True, entry=None, plan=None, detour=None,
             goalActivation={}, activation={}, refractory={}, trace={}, occ=[], recoveries=0,
             query=f'Желаемые результаты ({len(encoded)})', message='Цель удерживается. Маршрут заранее не задан.')
    dynamics.clear_transients(m)
    return dict(kind='goal-start', goals=clone(encoded))


def state(m):
    return next((n for n in m['memory']['nodes'] if n['kind'] == 'state' and compact(sorted(n['features'])) == key(m['observed'])), None)


def clear_wave(m):
    m['goalActivation'] = {}
    m['intent']['wave'] = 0
    m['intent'].pop('routeBounds', None)


def suspend(m, reason):
    m['intent']['episode'] = None
    m['entry'] = None
    m['activation'] = {}
    clear_wave(m)
    m['message'] = reason + '; цель остаётся активной.'


def satisfied(g, o):
    if g['kind'] == 'state':
        return bool(g['features']) and set(g['features']).issubset(sensory_features(o['features']))
    return o['focus'] == g['focus'] and o['output'] == g['value']


def choose(candidates, threshold, margin):
    ranks = sorted((c for c in candidates if c['allowed']), key=lambda c: -c['a'])
    if not ranks or ranks[0]['a'] < threshold:
        return {}
    if len(ranks) > 1 and ranks[0]['a'] - ranks[1]['a'] < margin:
        return dict(ambiguous=True)
    return dict(winner=ranks[0])


def dispatch(m, action, **details):
    m['serial'] += 1
    id = f"{m['attempt']}:{m['serial']}"
    step = node(m, details.get('step'))
    if step and not details.get('relocate'):
        step['eligibility'] = 1
    m['pending'] = dict(id=id, action=clone(action), sent=m['tick'], applied=False, receipt=None, network=True, **details)
    object_concepts.attach_request(m, m['pending'])
    m['status'] = 'waiting'
    prediction = dict(id=id, action=clone(action), goal=m['intent']['active'],
                      expected=clone(details.get('prediction')), before=key(m['observed']))
    m['intent']['predictions'].append(prediction)
    m['message'] = 'Выбрано действие, но его результат ещё не подтверждён.'
    return dict(kind='dispatch', winner=details.get('candidate') or details.get('source') or details.get('step'), action=clone(action), request=id, prediction=prediction)


def error(m, transition, reason, expected, actual, request):
    if transition:
        m['intent']['error'][transition] = 1
        node(m, transition)['inhibition'] = 1
    fact = dict(request=request, transition=transition, expected=expected, actual=actual, reason=reason, tick=m['tick'])
    m['intent']['errorHistory'].append(fact)
    suspend(m, reason)
    m['status'] = 'running'
    return dict(kind='prediction-error', error=fact, heldGoal=True)


def digits(m, g, event):
    o = m['observed']
    if not g['value'].startswith(o['output']):
        m.update(status='blocked', message='Неподходящее содержимое поля. Стирание не обучалось, перезаписи нет.')
        event['kind'] = 'content-conflict'
        return event
    if not m['occ'] or m['occ'][0].get('goal') != g['id']:
        n = len(o['output'])
        m['occ'] = [dict(id=f"{g['id']}:symbol:{i}", goal=g['id'], value=ch, held=i >= n, a=0,
                        next=f"{g['id']}:symbol:{i+1}" if i+1 < len(g['value']) else None,
                        consumedBy='observed-existing' if i < n else None) for i, ch in enumerate(g['value'])]
    consumed = ''.join(q['value'] for q in m['occ'] if not q['held'])
    if consumed != o['output']:
        m.update(status='blocked', message='Поле изменилось вне подтверждений; цель удерживается.')
        event['kind'] = 'content-conflict'
        return event
    cfg = m['intent']['config']
    for q in [q for q in m['occ'] if q['held']]:
        pred = next((n for n in m['occ'] if n['next'] == q['id']), None)
        blocked = bool(pred and pred['held'])
        symbol = next((n for n in m['memory']['nodes'] if n['kind'] == 'symbol' and n['value'] == q['value']), None)
        edge = next((e for e in m['memory']['edges'] if symbol and e['kind'] == 'corresponds' and e['from'] == symbol['id']), None)
        live = m['config']['inputDrive'] * edge['weight'] if edge else 0
        history = m['config']['historyGain'] if edge else 0
        inhibition = m['config']['inhibition'] if blocked else 0
        q['a'] = clamp(cfg['decay'] * q['a'] + live + history - inhibition)
        event['candidates'].append(dict(id=q['id'], label='KEY '+q['value'], a=q['a'], input=live, history=history,
                                        inhibition=inhibition, threshold=cfg['threshold'], allowed=bool(edge),
                                        reason='Предыдущее вхождение не подтверждено' if blocked else ''))
    decision = choose(event['candidates'], cfg['threshold'], cfg['margin'])
    if decision.get('ambiguous'):
        m['status'] = 'ambiguous'
        event['kind'] = 'ambiguous'
    elif decision.get('winner'):
        q = next(q for q in m['occ'] if q['id'] == decision['winner']['id'])
        event.update(dispatch(m, dict(kind='key', value=q['value']), source=q['id'],
                              prediction=dict(focus=g['focus'], output=o['output']+q['value']), target_focus=g['focus']))
    elif not any(c['allowed'] and c['input'] > 0 for c in event['candidates']):
        m.update(status='blocked', message='Нет возбуждающей моторной связи для остатка.')
    return event


def route_wave(m, goal, event, rehearsal=False):
    b = m['intent']; cfg = b['config']; b['wave'] += 1
    needed = goal['features'] if goal['kind'] == 'state' else ['focus:' + goal['focus']]
    choice = route_decision(m, b, cfg, needed, cfg['routeThreshold'], event,
                            b['wave'] >= cfg['maxWaves'], imagery.demand(m, goal))
    actual = state(m)
    event.update(kind='spread', goal=goal['targets'][0], current=actual['id'] if actual else None, wave=b['wave'])
    if rehearsal:
        event.update(kind='imagery-wave', candidate=choice.get('winner', {}).get('id'))
        m['message'] = 'Образ возбуждает переходы; моторика выключена.'
        return event
    if choice.get('ambiguous'):
        m.update(status='ambiguous', message='Границы оценок переходов пересекаются; победитель не подтверждён.')
    elif choice.get('winner'):
        n = node(m, choice['winner']['id'])
        b['episode'] = dict(transition=n['id'], step=n['first'], last=n['last'], source=n['from'], target=n['to'])
        m['entry'] = n['first']; m['recoveries'] += 1
        m['refractory'][n['id']] = cfg['refractory']; m['trace'][n['id']] = 1; b['eligibility'][n['id']] = 1
        event.update(kind='route', winner=n['id'])
        m['message'] = f"Выбран {n['label']}, A={choice['winner']['a']:.3f}; будущий маршрут не сохранён."
    elif choice.get('blocked'):
        m.update(status='blocked', message='За лимит волн не подтверждён переход выше порога. Цель не достигнута.')
    return event


def orient_step(m: dict, step: dict, event: dict) -> bool:
    """Use the same learned motor feedback as command execution, within this episode."""
    b=m['intent'];choice=dynamics.orienting_choice(m,step,b['config'],event['flows'])
    event['candidates'].extend(choice['candidates'])
    if choice.get('ambiguous'):
        m.update(status='ambiguous',message='Два близких изученных наведения; экземпляр ещё не подтверждён.')
        event['kind']='ambiguous';return True
    move=choice.get('winner')
    if not move:
        if choice.get('charging'):m['message']='Изученное наведение набирает возбуждение; проверяемый шаг удерживается.'
        return choice.get('charging',False)
    m['activation'][move['id']]=0;m['refractory'][move['id']]=b['config']['refractory']
    event.update(dispatch(m,move['action'],step=step['id'],transition=b['episode']['transition'],
                          relocate=True,candidate=move['id'],prediction=dict(cursor=dict(x=move['action']['x'],y=move['action']['y']))))
    m['message']='Возбуждён изученный '+move['label']+'; после наведения заново проверяем объект.'
    return True


def episode_tick(m, event):
    b = m['intent']; ep = b['episode']; step = node(m, ep['step'])
    require(step and step.get('action'), 'Нет показанного шага')
    from .perception.dynamics import before_step
    if object_concepts.before_step(m, step, event):
        return event
    if before_step(m, step, event):
        return event
    a = object_concepts.action_for(m, step, motor_action(m['memory'], step, m['observed']))
    if a['kind'] == 'move' and a.get('visual'):
        box = m['observed']['visual_bindings'][a['visual']]['bbox']
        a.update(x=round((box[0]+box[2])/2), y=round((box[1]+box[3])/2))
    supported = (object_concepts.result_matches(m, node(m, step['pre']), m['observed'], m['objectBinding'])
                 if m.get('objectBinding') else dynamics.predicted(m, node(m, step['pre']), m['observed']))
    if not click_continues(m['observed'], a) and not supported:
        previous = ep['transition']
        suspend(m, 'Состояние изменилось до следующего действия')
        event.update(kind='reobserve', transition=previous)
        return event
    reason = guard(m['observed'], a)
    if reason:
        icon = next((i for i in m['observed']['icons'] if i['id'] == a.get('object')), None)
        if icon and a['kind'] in ('check', 'click'):
            movement = dict(kind='move', x=icon['x'], y=icon['y'])
            if a.get('visual'):
                movement.update(visual=a['visual'], visual_object=a['visual_object'])
            event.update(dispatch(m, movement, step=step['id'], transition=ep['transition'],
                                  relocate=True, prediction=dict(cursor=dict(x=icon['x'], y=icon['y']))))
        elif orient_step(m,step,event):pass
        else:
            event.update(error(m, ep['transition'], reason, node(m, step['pre'])['key'], key(m['observed']), None))
        return event
    edge = next((e for e in m['memory']['edges'] if e['to'] == step['id'] and e['kind'] in ('next', 'starts')), None)
    weight = edge['weight'] if edge else 0
    new = clamp(b['config']['decay']*m['activation'].get(step['id'], 0)+weight)
    m['activation'][step['id']] = new
    event['candidates'].append(dict(id=step['id'], label=step['label'], a=new, input=0, history=weight, inhibition=0,
                                    threshold=b['config']['threshold'], allowed=not m['refractory'].get(step['id'])))
    if new >= b['config']['threshold'] and not m['refractory'].get(step['id']):
        post = node(m, step['post'])
        event.update(dispatch(m, a, step=step['id'], transition=ep['transition'], prediction=dict(state=post['key'] if post else None)))
    return event


def tick(m):
    b = m['intent']; cfg = b['config']; m['tick'] += 1
    dynamics.decay_traces(m)
    for id in m['refractory']: m['refractory'][id] = max(0, m['refractory'][id]-1)
    for id in m['trace']: m['trace'][id] = clamp(m['trace'][id]*cfg['traceDecay'])
    for id in b['error']: b['error'][id] = clamp(b['error'][id]*cfg['errorDecay'])
    for id in b['eligibility']: b['eligibility'][id] = clamp(b['eligibility'][id]*cfg['traceDecay'])
    if m['status'] in ('complete', 'blocked', 'failed', 'unknown', 'ambiguous', 'timeout', 'limit', 'idle', 'needs-help'):
        return dict(kind='stopped')
    if m['tick'] > cfg['maxTicks']:
        m.update(status='limit', message='Лимит тактов; незавершённая цель удерживается.')
        return dict(kind='limit')
    if m['pending']:
        if m.get('imagery'): imagery.update(m, next((g for g in b['goals'] if g['id'] == b['active']), None))
        if m['tick']-m['pending']['sent'] >= m['config']['timeout']:
            m.update(status='timeout', message='Нет квитанции. Повтор запрещён.')
        return dict(kind='waiting')
    event = dict(kind='charge', candidates=[], flows=[], winner=None)
    dynamics.sensory_tick(m, event['flows'])
    remaining = [g for g in b['goals'] if g['held']]
    if not remaining:
        if m.get("imagery"): imagery.update(m, None)
        m.update(heldGoal=False, status='complete', message='Все желаемые результаты подтверждены.')
        return dict(kind='complete')
    candidates = []
    for g in remaining:
        prior = next((p for p in b['goals'] if p['id'] == g['previous']), None)
        blocked = bool(prior and prior['held'])
        g['a'] = clamp(cfg['decay']*g['a']+cfg['goalGain']-(1.5*cfg['goalInhibition'] if blocked else 0))
        candidates.append(dict(id=g['id'], a=g['a'], allowed=True))
    goal_decision = choose(candidates, cfg['threshold'], cfg['margin'])
    if goal_decision.get('ambiguous'):
        m.update(status='ambiguous', message='Цели конкурируют без достаточного торможения.')
        return dict(kind='ambiguous', candidates=candidates)
    chosen = goal_decision.get('winner')
    if not chosen:
        return event
    goal = next(g for g in b['goals'] if g['id'] == chosen['id'])
    if b['active'] != goal['id']:
        b['active'] = goal['id']; m['occ'] = []
        suspend(m, 'Активирован следующий удерживаемый результат')
    if m.get('imagery'):
        imagery.update(m, goal)
        if m['imagery']['mode'] != 'act': return route_wave(m, goal, event, rehearsal=True)
        if m['imagery']['ready'] < m['imagery']['config']['threshold']:
            event['kind'] = 'imagery-charge'; return event
        if not m['imagery']['evidence']:
            m['message'] = 'Нет внешнего наблюдения; образ не разрешает действие.'
            event['kind'] = 'imagery-no-evidence'; return event
    if imagery.satisfied(m) if m.get('imagery') else satisfied(goal, m['observed']):
        if m.get('imagery'): imagery.confirmation(m, goal)
        goal.update(held=False, a=0, confirmedAt=m['tick'])
        b['goalHistory'].append(dict(id=goal['id'], tick=m['tick'], observed=clone(m['observed']),
                                    receipt=b['acknowledged'][-1] if b['acknowledged'] else None))
        suspend(m, 'Желаемый результат наблюдается')
        event.update(kind='goal-confirmed', winner=goal['id'])
        return event
    if m.get('imagery') and satisfied(goal, m['observed']):
        event['kind'] = 'imagery-confirming'; m['message'] = 'Совпадение наблюдается; накапливается сенсорное подтверждение.'; return event
    if goal['kind'] == 'field' and m['observed']['focus'] == goal['focus']:
        return digits(m, goal, event)
    if b['episode']:
        return episode_tick(m, event)
    return route_wave(m, goal, event)


def accept(m, raw):
    require(not m.get('imagery') or not raw.get('source') or raw['source']=='external', 'Воображаемая квитанция не принимается')
    r = clone(raw); b = m['intent']; p = m['pending']
    if r.get('id') in b['acknowledged']: return dict(kind='duplicate')
    if not p or r.get('id') != p['id'] or r.get('action') != p['action']: return dict(kind='ignored')
    require(r.get('before') and r.get('after') and isinstance(r['after'].get('features'), list) and isinstance(r.get('ok'), bool), 'Некорректная квитанция')
    if r['ok']:
        require(not guard(r['before'], p['action']), 'Квитанция нарушает предусловие')
        if p['action']['kind'] == 'move':
            require(abs(r['after']['cursor']['x']-p['action']['x']) <= 3 and abs(r['after']['cursor']['y']-p['action']['y']) <= 3, 'Нет наблюдаемого перемещения')
        if p['action']['kind'] == 'check':
            require(not guard(r['after'], p['action']), 'Проверка объекта не подтверждена')
    if p.get('source') and r['ok']:
        require(r['after']['focus'] == p['prediction']['focus'] and r['before']['focus'] == p['prediction']['focus']
                and r['after']['output'] == p['prediction']['output'] and r['before']['output'] + p['action']['value'] == r['after']['output'], 'Не подтверждён именно запрошенный ввод')
    if experience.unconfirmed_result(m,p,r):return dict(kind='unconfirmed')
    m['pending'] = None; m['observed'] = clone(r['after']); m['status'] = 'running'
    learned = experience.acknowledge(m, p, r)
    b['acknowledged'].append(r['id'])
    if not r['ok']:
        return error(m, p.get('transition'), r.get('reason') or 'Действие отклонено', p.get('prediction'), key(r['after']), r['id'])
    if p.get('source'):
        source = next(q for q in m['occ'] if q['id'] == p['source']); require(source['held'], 'Вхождение погашено')
        source.update(held=False, a=0, consumedBy=r['id'])
        m['message'] = 'Одно вхождение подтверждено; снято торможение следующего.'
    elif p.get('relocate'):
        require(abs(r['after']['cursor']['x']-p['action']['x']) <= 3 and abs(r['after']['cursor']['y']-p['action']['y']) <= 3, 'Курсор не достиг цели')
    else:
        step = node(m, p['step'])
        if (experience.effect_observed(r) and not step.get('dispatch_only')
                and not learned.get('conceptMatched', dynamics.predicted(m, node(m, step['post']), r['after']))):
            return error(m, p.get('transition'), 'Ожидание и наблюдение расходятся', p['prediction']['state'], key(r['after']), r['id'])
        m['activation'][p['step']] = 0; m['refractory'][p['step']] = b['config']['refractory']; m['trace'][p['step']] = 1
        if step['id'] == b['episode']['last']:
            b['episode'] = None; m['entry'] = None; clear_wave(m)
        else:
            links = [e for e in m['memory']['edges'] if e['from'] == step['id'] and e['kind'] == 'next']
            require(len(links) == 1, 'Неоднозначный следующий контекст фрагмента')
            b['episode']['step'] = links[0]['to']; m['entry'] = links[0]['to']
    return dict(kind='ack', receipt=r, source=p.get('source'), predictionMatch=True, plasticity=learned)
