"""Ten algorithmic capability checks. Test worlds are isolated from live Glaz.

The first four remain on the original command-mode kernel. The six added tests
use the same memory graph with optional goal dynamics; no plan is in the input.
"""
import json
from pathlib import Path
from .protocol import persistent_graph, clone
from .core import StateEngine
from .simulator import default_world, observe, apply, run_case, prepare_case

NAMES = ['Рабочий стол → окно', 'Окно → рабочий стол', 'Составной обход', 'Новые цифры',
         'Два результата по очереди', 'Конкуренция маршрутов', 'Изменение среды',
         'Три перехода', 'Цель — значение поля', 'Ошибка предсказания']
STOP = {'complete', 'blocked', 'failed', 'unknown', 'ambiguous', 'timeout', 'limit'}


def _teach_at(e, w, surface, query, id, enter=False):
    from .simulator import demonstrate, icon_actions
    before = clone(w); before.update(surface=surface, selected='', focus=before['surfaces'][surface]['field'] or '', output='')
    actions = icon_actions(before, id) + ([dict(kind='enter', object=id)] if enter else [])
    e.learn(demonstrate(query, before, actions))


def _state_goal(w, surface):
    before = clone(w); before.update(surface=surface, selected='', focus=before['surfaces'][surface]['field'] or '')
    return dict(kind='state', features=observe(before)['features'])


def _route_world():
    return dict(surface='junction', version=0, selected='', focus='', output='', cursor=dict(x=500, y=300), effects=[], surfaces={
        'junction': dict(field=None, icons=[dict(id='FAST', x=240, y=170, click='target'), dict(id='VIA', x=700, y=170, click='middle')]),
        'middle': dict(field=None, icons=[dict(id='NEXT', x=480, y=160, click='target')]),
        'target': dict(field=None, icons=[dict(id='TARGET', x=500, y=300)]),
        'trap': dict(field=None, icons=[dict(id='RETURN', x=450, y=170, click='junction')])})


def prepare(number):
    from .simulator import demonstrate, icon_actions
    if number <= 4:
        e, w, query = prepare_case(number)
        return e, w, dict(kind='start', query=query)
    if number in (5, 7, 9):
        e, w, _ = prepare_case(1)
        prior = default_world(); prior.update(surface='calculator', focus='FIELD')
        e.learn(demonstrate('Прежний ввод символов', prior, [dict(kind='key', value=v) for v in '5432']), exposure=True)
        e.learn(demonstrate('добавь траты 1700', w, icon_actions(w, 'CALC') + [dict(kind='key', value=v) for v in '1700']))
        goals = [dict(kind='field', focus='FIELD', value='3521' if number == 5 else '2345')]
        if number == 5: goals.insert(0, _state_goal(w, 'window'))
        if number == 9: w['surface'] = 'window'
    elif number in (6, 10):
        e = StateEngine(); w = _route_world()
        _teach_at(e, w, 'junction', 'первый отдельный показ', 'FAST')
        _teach_at(e, w, 'junction', 'второй отдельный показ', 'VIA')
        _teach_at(e, w, 'middle', 'третий отдельный показ', 'NEXT')
        if number == 10: _teach_at(e, w, 'trap', 'независимый возврат', 'RETURN')
        if number == 6:
            transition = next(n for n in e.model['memory']['nodes'] if n['kind'] == 'transition' and n['label'] == 'CLICK FAST')
            edge = next(x for x in e.model['memory']['edges'] if x['kind'] == 'backward' and x['to'] == transition['id'])
            e.set_weight(edge['id'], .35)
        goals = [_state_goal(w, 'target')]
    elif number == 8:
        e = StateEngine(); w = dict(surface='L0', version=0, selected='', focus='', output='', cursor=dict(x=500, y=300), effects=[], surfaces={})
        for i in range(4):
            w['surfaces']['L'+str(i)] = dict(field=None, icons=[dict(id='DONE' if i == 3 else 'GO'+str(i), x=300+i*100, y=150, **(dict(click='L'+str(i+1)) if i < 3 else {}))])
        for i in range(3): _teach_at(e, w, 'L'+str(i), 'отдельный переход '+str(i), 'GO'+str(i))
        goals = [_state_goal(w, 'L3')]
    else:
        raise ValueError('Неизвестный тест')
    e.configure(plasticity=0)
    e.observe(observe(w))
    return e, w, dict(kind='goal', goals=goals)


def intervene(number, engine, world, state):
    if state.get('injected'): return False
    m = engine.model; last = engine.events[-1] if engine.events else {}
    if number == 7 and last['kind'] == 'ack' and last['receipt']['action']['kind'] == 'click' and last['receipt']['action'].get('object') == 'CALC':
        world.update(surface='window', selected='', focus='', output=''); world['version'] += 1
        engine.observe(observe(world)); state['injected'] = True; return True
    if number == 10 and m['pending'] and m['pending']['action'].get('object') == 'FAST' and m['pending']['action']['kind'] == 'click':
        next(i for i in world['surfaces']['junction']['icons'] if i['id'] == 'FAST')['click'] = 'trap'
        world['version'] += 1; engine.observe(observe(world)); state['injected'] = True; return True
    return False


def run(number):
    if number <= 4:
        result, e, w = run_case(number)
        result['pass'] = result['passed']; return result, e, w
    e, w, req = prepare(number); frozen = persistent_graph(e.model['memory']); change = {}; physical = {}
    e.start_goals(req['goals'], observe(w), req.get('config'))
    for _ in range(1700):
        if e.model['status'] in STOP: break
        intervene(number, e, w, change)
        event = e.tick()
        if event['kind'] == 'waiting' and e.model['status'] != 'timeout':
            p = e.model['pending']
            if p['id'] not in physical:
                physical[p['id']] = apply(w, p)
            else:
                e.accept_receipt(physical[p['id']])
    m = e.model; b = m['intent']; clicks = [r['action']['object'] for r in w['effects'] if r['ok'] and r['action']['kind'] == 'click']
    expected = {5: ['A', 'X', 'CALC'], 6: ['VIA', 'NEXT'], 7: ['CALC', 'X', 'CALC'],
                8: ['GO0', 'GO1', 'GO2'], 9: ['X', 'CALC'], 10: ['FAST', 'RETURN', 'VIA', 'NEXT']}[number]
    passed = m['status'] == 'complete' and frozen == persistent_graph(m['memory']) and clicks == expected
    if number in (5, 7, 9): passed = passed and w['output'] == ('3521' if number == 5 else '2345')
    if number == 5: passed = passed and len(b['goalHistory']) == 2 and b['goalHistory'][0]['tick'] < b['goalHistory'][1]['tick']
    if number in (7, 10): passed = passed and change.get('injected', False)
    if number == 10: passed = passed and len(b['errorHistory']) == 1
    passed = passed and all(not g['held'] for g in b['goals']) and any(ev['kind'] == 'spread' and ev['flows'] for ev in e.events)
    result = dict(number=number, name=NAMES[number-1], passed=passed, **{'pass': passed}, status=m['status'],
                  ticks=m['tick'], clicks=clicks, output=w['output'], predictions=len(b['predictions']),
                  errors=len(b['errorHistory']), memoryUnchanged=frozen == persistent_graph(m['memory']))
    return result, e, w


def main():
    from .console import configure_console
    configure_console()
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument('--evidence', type=Path)
    args = parser.parse_args(); results = []
    if args.evidence: args.evidence.mkdir(parents=True, exist_ok=True)
    for number in range(1, 11):
        result, e, w = run(number); results.append(result)
        if args.evidence:
            (args.evidence/f'case-{number:02d}.json').write_text(json.dumps(dict(result=result, events=e.events), ensure_ascii=False, indent=2), encoding='utf-8')
    report = dict(schema='kolos-ten-capabilities/1', scope='native Python kernel + isolated observed environment; not live-PC acceptance', cases=results)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.evidence: (args.evidence/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if all(r['passed'] for r in results) else 1

if __name__ == '__main__': raise SystemExit(main())
