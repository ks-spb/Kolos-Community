"""Python port of web/states/core.mjs @ ef97a1cf (math and graph topology).

World physics are deliberately absent. The host supplies fresh observations and
separate receipts. Prediction never calls a simulator or desktop-control API.
The demonstrated segment still follows explicit `next` edges; goal recovery is
weighted backward spreading activation. This is not a biophysical neuron model.
"""
from __future__ import annotations
from .route_selection import route_decision
from . import commands, dynamics, experience, object_concepts
from .protocol import clone, clamp, require, observation, observation_key, action, guard, validate_record
from .targeting import motor_action

DEFAULTS = dict(decay=.5, weight=.9, threshold=.70, planThreshold=.65, margin=.04,
                discount=.90, stateCompetition=1, refractory=2, inputDrive=.65, inhibition=.95,
                historyGain=.04, timeout=40, plasticity=1, learningRate=.05)
STOP = {'idle', 'trained', 'complete', 'unknown', 'failed', 'timeout', 'ambiguous', 'blocked', 'limit', 'needs-help'}


def action_text(a: dict) -> str:
    kind = a['kind']
    if kind == 'move': return f"MOVE {a['x']}×{a['y']}"
    if kind == 'key': return 'KEY ' + ('␣' if a['value'] == ' ' else a['value'])
    if kind == 'gui': return 'GUI ' + a['binding']
    if kind == 'drive': return 'Символы текущего запроса'
    if kind == 'finish': return 'Подтверждённый конец'
    return kind.upper() + ' ' + a.get('object', '')


class StateEngine:
    def __init__(self):
        self.model = dict(memory=dict(nodes=[dict(id='n0', kind='context', label='Начало запроса')], edges=[], root='n0', serial=1),
            config=clone(DEFAULTS), lessons=[], exposures=[], learningLog=[], commands=[], audit=[], tick=0, revision=0, attempt=0, serial=0,
            query='', occ=[], heldGoal=False, phase='idle', status='idle', message='Движок готов. Требуются наблюдения Glaz.',
            context='n0', entry=None, recognitionLeft=0, pending=None, receipts=[], received=[], plan=None, detour=None,
            blockedTransitions=[], recoveries=0, activation={}, goalActivation={}, refractory={}, trace={}, last=None, observed=None)
        self.events = []

    def node(self, id):
        return next((n for n in self.model['memory']['nodes'] if n['id'] == id), None)

    def edges(self, id, kind='next'):
        return [e for e in self.model['memory']['edges'] if e['from'] == id and e['kind'] == kind]

    def _node(self, **spec):
        mem = self.model['memory']; n = dict(id='n' + str(mem['serial']), **spec)
        require(len(mem['nodes']) < 5000, 'Лимит 5000 вершин')
        mem['serial'] += 1; mem['nodes'].append(n); return n

    def _edge(self, source, target, kind, weight=None):
        m = self.model; mem = m['memory']
        e = next((e for e in mem['edges'] if e['from'] == source and e['to'] == target and e['kind'] == kind), None)
        if e: return e
        e = dict(id='e' + str(mem['serial']), to=target, kind=kind, weight=m['config']['weight'] if weight is None else weight)
        e['from'] = source; mem['serial'] += 1; mem['edges'].append(e); return e

    def state(self, obs, create=False):
        if create:
            return experience.state(self.model, obs)
        key = observation_key(obs); nodes = self.model['memory']['nodes']
        n = next((n for n in nodes if n['kind'] == 'state' and n['key'] == key), None)
        return n

    def _keys(self, receipts, origin):
        for r in receipts:
            if r['action']['kind'] != 'key' or not r['ok']: continue
            value = r['action']['value']; nodes = self.model['memory']['nodes']
            require(r['after']['output'] == r['before']['output'] + value and r['after']['focus'] == r['before']['focus'], 'Нет наблюдаемого ввода символа')
            symbol = next((n for n in nodes if n['kind'] == 'symbol' and n['value'] == value), None)
            motor = next((n for n in nodes if n['kind'] == 'motor' and n['value'] == value), None)
            if symbol is None: symbol = self._node(kind='symbol', label=value, value=value)
            if motor is None: motor = self._node(kind='motor', label='KEY ' + value, value=value, evidence=[])
            if origin not in motor['evidence']: motor['evidence'].append(origin)
            self._edge(symbol['id'], motor['id'], 'corresponds', 1)

    def learn(self, record, *, exposure=False):
        require(not self.model['pending'], 'Сначала завершите ожидающее действие')
        require(not (self.model.get('episode') and self.model['status'] in ('running', 'waiting')), 'Reset the working episode before changing its memory')
        checked = validate_record(record)
        # Validate on a copy, then commit learning transactionally.
        backup = clone(self.model)
        try:
            self._learn(checked, exposure)
        except Exception:
            self.model = backup
            raise
        self.model['learningLog'].append(dict(exposure=bool(exposure), record=clone(checked)))
        self._event(dict(kind='expose' if exposure else 'teach'))

    def _learn(self, record, exposure):
        m = self.model; seq = record['receipts']
        require(len(m['lessons']) < 20 and len(m['exposures']) < 20, 'Лимит демонстраций')
        if exposure:
            require(all(r['action']['kind'] == 'key' for r in seq), 'Прежний ввод содержит только клавиши')
            self._keys(seq, 'Прежний ввод №' + str(len(m['exposures']) + 1))
            m['exposures'].append(clone(record)); m['status'] = 'trained'; return
        first_key = next((i for i, r in enumerate(seq) if r['action']['kind'] == 'key'), -1)
        prefix = record['query']; data = False; setup = seq; alignment = []
        if first_key >= 0:
            require(all(r['action']['kind'] == 'key' for r in seq[first_key:]), 'Поддерживается один заключительный блок клавиш')
            values = [r['action']['value'] for r in seq[first_key:]]; chars = list(record['query'])
            offsets = [i for i in range(len(chars) - len(values) + 1) if chars[i:i+len(values)] == values]
            require(len(offsets) == 1 and offsets[0] > 0 and offsets[0] + len(values) == len(chars), 'Неоднозначное соответствие клавиш запросу')
            prefix = ''.join(chars[:offsets[0]]); data = True; setup = seq[:first_key]
            alignment = [dict(symbol=v, input=offsets[0]+j, receipt=seq[first_key+j]['id']) for j,v in enumerate(values)]
        context = m['memory']['root']
        for ch in prefix:
            e = next((e for e in self.edges(context, 'recognize') if self.node(e['to'])['symbol'] == ch), None)
            if e is None:
                n = self._node(kind='context', symbol=ch, label='␣' if ch == ' ' else ch)
                e = self._edge(context, n['id'], 'recognize')
            context = e['to']
        focus = seq[first_key]['before']['focus'] if data else ''
        signature = commands.demonstration_signature(context,data,focus,setup,seq[-1]['after'])
        if any(commands.command_signature(m,c) == signature for c in m['commands']):
            self._keys(seq, 'Повторная демонстрация: ' + record['query']); m['lessons'].append(clone(record)); return
        previous = context; first = None; segment_first = None; boundary = None
        for r in setup:
            source = self.state(r['before'], True); target = self.state(r['after'], True)
            step = self._node(kind='step', label=action_text(r['action']), action=clone(r['action']), pre=source['id'], post=target['id'],
                              visual_ack=r['action']['kind']=='enter' and r.get('verified_by')=='visual-change',
                              dispatch_only=r.get('effect_observed') is False)
            if r['action'].get('visual'):
                visual = self.node(r['action']['visual'])
                require(visual and visual['kind'] == 'visual_object', 'Нет выученного зрительного образа')
                self._edge(step['id'], visual['id'], 'visual_ground', 1)
            self._edge(previous, step['id'], 'starts' if previous == context else 'next'); previous = step['id']
            if first is None: first = step['id']
            if segment_first is None: segment_first = step['id']; boundary = source['id']
            if experience.effect_observed(r):
                trans = self._node(kind='transition', label=r['action']['kind'].upper()+' '+r['action'].get('object',''), to=target['id'], first=segment_first, last=step['id'], **{'from':boundary})
                self._edge(target['id'], trans['id'], 'backward'); self._edge(trans['id'], boundary, 'backward', 1)
                self._edge(boundary, trans['id'], 'applicable', 1); self._edge(trans['id'], step['id'], 'experienced', 1)
                segment_first = None
        finish = self._node(kind='step', label='Символы текущего запроса' if data else 'Конец команды', action=dict(kind='drive' if data else 'finish'), pre=self.state(seq[-1]['after'], True)['id'], post=None)
        self._edge(previous, finish['id'], 'starts' if previous == context else 'next')
        m['commands'].append(dict(context=context, first=first or finish['id'], data=data, signature=signature, label=record['query'], focus=focus))
        self._keys(seq, 'Демонстрация команды: ' + record['query']); m['lessons'].append(clone(record))
        m['audit'].append(dict(query=record['query'], data=data, prefix=prefix, alignment=alignment))
        m.update(context=m['memory']['root'], entry=None, phase='idle', status='trained', message='Демонстрация сохранена. Обучение продолжается по подтверждённым результатам известных действий.')

    def inspect(self, query):
        m = self.model; cur = m['memory']['root']; index = 0; chars = list(query); matches = []
        alphabet = {n['value'] for n in m['memory']['nodes'] if n['kind'] == 'motor'}
        while True:
            for c in m['commands']:
                if c['context'] != cur: continue
                if not c['data'] and index == len(chars): matches.append(dict(command=c, recognized=index))
                if c['data'] and index < len(chars) and all(ch in alphabet for ch in chars[index:]): matches.append(dict(command=c, recognized=index))
            if index >= len(chars): break
            edges = [e for e in self.edges(cur, 'recognize') if self.node(e['to'])['symbol'] == chars[index]]
            if len(edges) != 1: break
            cur = edges[0]['to']; index += 1
        require(matches, 'Нет полного согласованного запроса; нужен прежний опыт символов. Регистр и пробелы значимы.')
        return commands.select_match(m,matches)

    def start(self, query, observed):
        m = self.model; require(not m['pending'], 'Есть неподтверждённое действие; нужен явный сброс')
        require(isinstance(query, str) and 0 < len(query) <= 160, 'Запрос: 1–160 символов')
        obs = observation(observed)
        m['intent'] = None; m['imagery'] = None
        m.pop('perception', None)
        try: result = self.inspect(query)
        except ValueError as exc:
            m.update(status='unknown', phase='idle', entry=None, plan=None, detour=None, message=str(exc), query=query, heldGoal=False)
            return self._event(dict(kind='start'))
        m.pop('episode', None)
        m['language']=None
        m['attempt'] += 1; attempt = m['attempt']
        m.update(tick=0, query=query, heldGoal=True, observed=obs, context=m['memory']['root'], entry=result['command']['first'], selectedCommand=clone(result['command']), recognitionLeft=result['recognized'])
        m['occ'] = [dict(id=f'q{attempt}:{i}', value=ch, next=f'q{attempt}:{i+1}' if i+1 < len(query) else None, held=True, a=0, consumedBy=None) for i,ch in enumerate(query)]
        m.update(phase='recognize', status='running', plan=None, detour=None, blockedTransitions=[], recoveries=0, activation={}, trace={}, refractory={}, goalActivation={}, message='Запрос удерживается; обучение только по наблюдённым результатам.')
        dynamics.clear_transients(m)
        return self._event(dict(kind='start'))

    def learn_episode(self, record):
        from .episodes import teach
        return teach(self, record)

    def start_episode(self, query, observed):
        from .episodes import start
        return start(self, query, observed)

    def observe(self, raw):
        if self.model.get('phase') == 'episode' and self.model.get('episode'):
            from .episodes import update_observation
            return update_observation(self, raw)
        self.model['observed'] = observation(raw)

    def _goal(self, step, reason):
        m = self.model
        if m.get('plan') and m['plan']['goal'] == step['pre']: return
        m['experienceStart'] = len(m['receipts'])
        m.update(plan=dict(goal=step['pre'], suspended=step['id'], round=0), goalActivation={}, activation={}, message=reason + '. Исходная цель удерживается.')

    def _resume_observed_step(self) -> bool:
        """Release an unsent suspended step when current evidence permits it."""
        m = self.model
        if not m['plan'] or m['detour'] or m['pending']:
            return False
        step = self.node(m['plan']['suspended'])
        a = step['action']; obs = m['observed']
        if a['kind'] == 'drive':
            ready = bool(obs['focus']) and obs['focus'] == m['selectedCommand']['focus']
        elif a['kind'] in ('check', 'click'):
            # The normal dispatch path relocates to this fresh icon if needed.
            ready = any(i['id'] == a['object'] for i in obs['icons'])
        elif a['kind'] == 'enter':
            ready = not guard(obs, a)
        else:
            return False
        if not ready:
            reason = 'Нет нужного фокуса ввода' if a['kind'] == 'drive' else guard(obs, a)
            m['message'] = reason + '. Исходная цель удерживается.'
            return False
        m.update(entry=step['id'], plan=None, goalActivation={}, activation={},
                 message='Нужный объект или фокус снова наблюдается; продолжаем исходный шаг.')
        return True

    def _plan_tick(self, event):
        m = self.model; g = m['plan']; g['round'] += 1; cfg = m['config']
        choice = route_decision(m, g, cfg, dynamics.demand_features(m, self.node(g['suspended'])),
                                cfg['planThreshold'], event, g['round'] >= 60)
        current = self.state(m['observed'])
        event.update(kind='spread', goal=g['goal'], current=current['id'] if current else None)
        if choice.get('ambiguous'):
            m.update(status='ambiguous', message='Границы оценок переходов пересекаются; победитель не подтверждён.'); return
        if choice.get('winner'):
            best = choice['winner']
            t = self.node(best['id']); m['detour'] = dict(transition=t['id'], last=t['last'], target=t['to']); m['entry'] = t['first']; m['recoveries'] += 1; g['active'] = True
            m['refractory'][t['id']] = cfg['refractory']; m['trace'][t['id']] = 1; event.update(kind='route', winner=t['id'])
            m['message'] = f"Выбран переход {t['label']}: A={best['a']:.3f}. Исходная цель удерживается."
        elif choice.get('blocked'): m.update(status='blocked', message='За лимит волн не подтверждён путь выше порога.')

    def _orient_step(self, step: dict, event: dict) -> bool:
        """Recall a weighted motor predecessor while retaining the unverified step."""
        m=self.model;choice=dynamics.orienting_choice(m,step,m['config'],event['flows'])
        event['candidates'].extend(choice['candidates'])
        if choice.get('ambiguous'):
            m.update(status='ambiguous',message='Два близких изученных наведения; экземпляр ещё не подтверждён.')
            event['kind']='ambiguous';return True
        move=choice.get('winner')
        if not move:
            if choice.get('charging'):m['message']='Изученное наведение набирает возбуждение; проверяемый шаг удерживается.'
            return choice.get('charging',False)
        m['activation'][move['id']]=0;m['refractory'][move['id']]=m['config']['refractory']
        event.update(self._request(move['action'],relocate=True,step=step['id'],candidate=move['id']))
        m['message']='Возбуждён изученный '+move['label']+'; после наведения заново проверяем объект.'
        return True

    def _request(self, a, **details):
        m = self.model; m['serial'] += 1
        step = self.node(details.get('step'))
        if step and not details.get('relocate'):
            step['eligibility'] = 1
        m['pending'] = dict(id=f"{m['attempt']}:{m['serial']}", action=clone(a), sent=m['tick'], **details)
        object_concepts.attach_request(m, m['pending'])
        m['status'] = 'waiting'; m['message'] = 'Выбрано ' + action_text(a) + '; ждём наблюдение результата.'
        return dict(kind='dispatch', winner=details.get('candidate') or details.get('step'), action=clone(a), request=m['pending']['id'])

    def imagine(self, goals, observed, options=None):
        from . import imagery
        backup = clone(self.model)
        events = len(self.events)
        try:
            self.start_goals(goals, observed)
            imagery.start(self.model, options)
        except Exception:
            self.model = backup; del self.events[events:]; raise
        return self._event(dict(kind='image-start'))

    def control_image(self, command):
        from . import imagery
        imagery.control(self.model, command)
        return self._event(dict(kind='image-control'))

    def start_goals(self, goals, observed, config=None):
        from . import goal_network
        previous = clone(self.model)
        try:
            require(not self.model['pending'], 'Resolve the pending effect before changing task')
            self.model.pop('episode', None)
            self.observe(observed)
            event = goal_network.start(self.model, goals, config)
            self.model['language']=None
        except Exception:
            self.model = previous
            raise
        return self._event(event)

    def teach_language(self, phrase, goal):
        from . import language
        backup = clone(self.model)
        try: event = language.teach(self.model, phrase, goal)
        except Exception:
            self.model = backup
            raise
        return self._event(event)

    def start_language(self, phrase, observed, config=None):
        from . import language
        backup = clone(self.model)
        try:
            require(not self.model['pending'], 'Resolve the pending effect before changing task')
            self.model.pop('episode', None)
            self.observe(observed)
            event = language.start(self.model, phrase, config)
        except Exception:
            self.model = backup
            raise
        return self._event(event)

    def set_language_weight(self, id, value):
        from . import language
        language.weight(self.model, id, value)

    def tick(self):
        if self.model.get('phase') == 'episode' and self.model.get('episode'):
            from .episodes import tick
            return tick(self)
        if self.model['phase']=='language' and self.model.get('language',{}).get('status')=='reading':
            from . import language, goal_network, imagery
            event = language.tick(self.model)
            if event['kind']=='language-image':
                ticks, text = self.model['tick'], self.model['query']
                goal_network.start(self.model,[event['goal']])
                imagery.start(self.model)
                self.model.update(tick=ticks,query=text)
                self.model['language']['status']='imagined'
                self.model['language']['handoffTick']=ticks
                self.model['imagery']['source']=dict(kind='language',readout=clone(event['readout']))
            return self._event(event)
        if self.model.get("intent") and self.model["phase"] == "intent":
            from . import goal_network
            return self._event(goal_network.tick(self.model))
        m = self.model; m['tick'] += 1
        dynamics.decay_traces(m)
        for key in m['refractory']: m['refractory'][key] = max(0, m['refractory'][key]-1)
        for key in m['trace']: m['trace'][key] = clamp(m['trace'][key]*.9)
        event = dict(kind='charge', candidates=[], flows=[], winner=None)
        if m['status'] in STOP: return self._event(dict(kind='stopped'))
        if m['tick'] > 1800 or m['recoveries'] > 12:
            m.update(status='limit', message='Ограничитель циклов; цель не погашена'); return self._event(dict(kind='limit'))
        if m['pending']:
            if m['tick']-m['pending']['sent'] >= m['config']['timeout']:
                m.update(status='timeout', message='Нет подтверждения; автоматического повтора нет.')
            return self._event(dict(kind='waiting'))
        if m['phase'] == 'recognize':
            q = next(n for n in m['occ'] if n['held']); links = [e for e in self.edges(m['context'],'recognize') if self.node(e['to'])['symbol'] == q['value']]
            require(len(links)==1, 'Нарушен контекст'); e = links[0]; q['a'] = clamp(q['a']*m['config']['decay']+m['config']['inputDrive']+.2*e['weight'])
            event['candidates'] = [dict(id=q['id'], label=q['value'], a=q['a'], input=m['config']['inputDrive'], history=.2*e['weight'], inhibition=0, allowed=True, threshold=m['config']['threshold'])]
            if q['a'] >= m['config']['threshold']:
                q.update(held=False, a=0, consumedBy='internal:recognition'); m['context']=e['to']; m['recognitionLeft']-=1; event.update(winner=q['id'], kind='recognized')
                if m['recognitionLeft']==0: m['phase']='execute'
            return self._event(event)
        dynamics.sensory_tick(m, event['flows'])
        from .perception.dynamics import before_step
        visual_step = self.node(m['plan']['suspended'] if m['plan'] and not m['detour'] else m['entry'])
        if object_concepts.before_step(m, visual_step, event):
            return self._event(event)
        if before_step(m, visual_step, event):
            return self._event(event)
        if m['plan'] and not m['detour'] and not self._resume_observed_step():
            if self._orient_step(self.node(m['plan']['suspended']),event):return self._event(event)
            self._plan_tick(event); return self._event(event)
        step = self.node(m['entry']); require(step, 'Нет активного шага')
        a = object_concepts.action_for(m, step, motor_action(m['memory'], step, m['observed']))
        if a['kind'] == 'move' and a.get('visual'):
            box = m['observed']['visual_bindings'][a['visual']]['bbox']
            a.update(x=round((box[0]+box[2])/2), y=round((box[1]+box[3])/2))
        if a['kind'] == 'finish':
            m.update(heldGoal=False,status='complete',message='Исходная команда подтверждена.'); return self._event(dict(kind='complete', winner=step['id']))
        if a['kind'] == 'drive':
            remain = [q for q in m['occ'] if q['held']]
            if not remain:
                m.update(heldGoal=False,status='complete',message='Все символы подтверждены.'); return self._event(dict(kind='complete'))
            if m['observed']['focus'] != m['selectedCommand']['focus']:
                self._goal(step, 'Нет нужного фокуса ввода'); return self._event(dict(kind='need-state', goal=step['pre']))
            for q in remain:
                pred = next((n for n in m['occ'] if n['next']==q['id']), None); blocked = bool(pred and pred['held'])
                symbol = next((n for n in m['memory']['nodes'] if n['kind']=='symbol' and n['value']==q['value']),None)
                edge = next((e for e in m['memory']['edges'] if e['kind']=='corresponds' and symbol and e['from']==symbol['id']), None)
                live = m['config']['inputDrive']*edge['weight'] if edge else 0; history=m['config']['historyGain'] if edge else 0; inhibition=m['config']['inhibition'] if blocked else 0
                q['a']=clamp(m['config']['decay']*q['a']+live+history-inhibition)
                event['candidates'].append(dict(id=q['id'],label='KEY '+q['value'],a=q['a'],input=live,history=history,inhibition=inhibition,allowed=bool(edge) and not blocked,threshold=m['config']['threshold']))
            ranks=sorted((c for c in event['candidates'] if c['allowed']),key=lambda c:-c['a'])
            if ranks and ranks[0]['a']>=m['config']['threshold']:
                if len(ranks)>1 and ranks[0]['a']-ranks[1]['a']<m['config']['margin']: m['status']='ambiguous'; return self._event(event)
                q=next(q for q in remain if q['id']==ranks[0]['id']); event.update(self._request(dict(kind='key',value=q['value']),source=q['id'],step=step['id'],candidate=q['id']))
            return self._event(event)
        reason=guard(m['observed'],a)
        if reason:
            visible=next((i for i in m['observed']['icons'] if i['id']==a.get('object')),None)
            if visible and a['kind'] in ('check','click'):
                movement = dict(kind='move',x=visible['x'],y=visible['y'])
                if a.get('visual'):
                    movement.update(visual=a['visual'], visual_object=a['visual_object'])
                event.update(self._request(movement,relocate=True,step=step['id']));return self._event(event)
            if self._orient_step(step,event):return self._event(event)
            if m['detour']:
                self.node(m['detour']['transition'])['inhibition']=1
                m['detour']=None;m['entry']=m['plan']['suspended'];m['plan']=None
            self._goal(self.node(m['entry']),reason);return self._event(dict(kind='need-state',goal=m['plan']['goal']))
        edge=next((e for e in m['memory']['edges'] if e['to']==step['id'] and e['kind'] in ('starts','next')),None)
        history=edge['weight'] if edge else 0;score=clamp(m['activation'].get(step['id'],0)*m['config']['decay']+history);m['activation'][step['id']]=score
        event['candidates']=[dict(id=step['id'],label=step['label'],a=score,input=0,history=history,inhibition=0,allowed=not m['refractory'].get(step['id'],0),threshold=m['config']['threshold'])]
        if score>=m['config']['threshold'] and not m['refractory'].get(step['id'],0):event.update(self._request(a,step=step['id']))
        return self._event(event)

    def accept_receipt(self, raw):
        if self.model.get('phase') == 'episode' and self.model.get('episode'):
            from .episodes import accept
            return accept(self, raw)
        if self.model.get("intent"):
            from . import goal_network
            return self._event(goal_network.accept(self.model, raw))
        m=self.model;r=clone(raw);p=m['pending']
        if r.get('id') in m['received']:return self._event(dict(kind='duplicate'))
        if not p or r.get('id')!=p['id'] or r.get('action')!=p['action']:return self._event(dict(kind='ignored'))
        r['before']=observation(r['before']);r['after']=observation(r['after'])
        require(isinstance(r.get('ok'), bool), 'Некорректное подтверждение')
        # The adapter supplies independent observations; a successful receipt must
        # satisfy the physical guard and the exact before/after key delta.
        if r['ok']:
            require(not guard(r['before'],p['action']), 'Результат нарушает предусловие')
            if p.get('source'):
                require(r['after']['focus']==r['before']['focus'] and r['after']['output']==r['before']['output']+p['action']['value'], 'Нет подтверждённого изменения поля')
            if p.get('step') and p['action']['kind']=='enter' and self.node(p['step']).get('visual_ack'):
                from .visual import changed as visual_changed
                require(visual_changed(r['before'],r['after']), 'Enter не подтверждён изменением кадра Glaz')
        if experience.unconfirmed_result(m,p,r):
            return self._event(dict(kind='unconfirmed',message='Отправка зарегистрирована, результат ещё не подтверждён.'))
        learned=experience.acknowledge(m,p,r)
        m['received'].append(r['id']);m['pending']=None
        if not r['ok']:
            m.update(status='failed',message='Действие не подтверждено: '+r.get('reason',''));return self._event(dict(kind='failed',receipt=r))
        m.update(observed=clone(r['after']),status='running')
        if p.get('source'):
            q=next(q for q in m['occ'] if q['id']==p['source']);require(q['held'],'Вхождение уже погашено');q.update(held=False,a=0,consumedBy=r['id'])
        elif not p.get('relocate'):
            step=self.node(p['step'])
            if (experience.effect_observed(r) and not step.get('dispatch_only') and step.get('post')
                    and not learned.get('conceptMatched', dynamics.predicted(m,self.node(step['post']),m['observed']))):
                if m['detour']:
                    self.node(m['detour']['transition'])['inhibition']=1
                    m['entry']=m['plan']['suspended'];m['detour']=None;m['plan']=None
                self._goal(self.node(m['entry']),'Наблюдён другой результат; ошибочный переход заторможен')
                return self._event(dict(kind='prediction-error',receipt=r,plasticity=learned))
            m['activation'][p['step']]=0;m['trace'][p['step']]=1;m['refractory'][p['step']]=m['config']['refractory']
            if m['detour'] and step['id']==m['detour']['last']:
                m['entry']=m['plan']['suspended'];m.update(detour=None,plan=None,goalActivation={})
            else:
                following=self.edges(step['id']);require(len(following)==1,'Нарушена последовательность');m['entry']=following[0]['to']
        m['message']=('Клик отправлен; продолжаем с выбранным объектом.'
                      if r.get('verified_by')=='verified-target-click' else
                      'Подтверждено: '+action_text(p['action']))
        return self._event(dict(kind='ack',receipt=r,source=p.get('source'),plasticity=learned))

    def reset(self):
        dynamics.clear_transients(self.model)
        self.model.pop('episode', None)
        self.model.pop('perception', None)
        self.model['language']=None
        self.model.update(intent=None,imagery=None,pending=None,heldGoal=False,plan=None,detour=None,entry=None,occ=[],status='idle',tick=0)
        return self._event(dict(kind='reset'))

    def configure(self, **values):
        require(not self.model['pending'],'Ожидается подтверждение')
        for k,v in values.items():
            require(k in DEFAULTS and isinstance(v,(float,int)) and 0<=v<=(200 if k=='timeout' else 10 if k=='refractory' else 1), 'Неверный параметр')
            if k in ('timeout','refractory'):require(int(v)==v,'Нужен целый такт')
        self.model['config'].update(values)
        if self.model.get('intent') and self.model['phase'] == 'intent':
            for k, v in values.items():
                key = 'routeThreshold' if k == 'planThreshold' else k
                if key in self.model['intent']['config']: self.model['intent']['config'][key] = v

    def set_weight(self, id, value):
        require(not self.model['pending'] and isinstance(value,(float,int)) and 0<=value<=1,'Неверный вес')
        edge=next(e for e in self.model['memory']['edges'] if e['id']==id);edge['weight']=value

    def preview(self):
        other=StateEngine();other.model=clone(self.model);ev=other.tick();return dict(base=self.model['revision'],next=other.model,event=ev)

    def commit(self, proposal):
        require(proposal['base']==self.model['revision'],'Расчёт устарел')
        self.model=clone(proposal['next']);self.events.append(clone(proposal['event']));return proposal['event']

    def _event(self, event):
        self.model['revision']+=1;event.setdefault('message',self.model['message']);event['tick']=self.model['tick'];self.events.append(clone(event));return event
