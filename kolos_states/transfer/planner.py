"""Weighted Dijkstra selector on learned edges; shares the native motor executor."""
from __future__ import annotations

import heapq
import math

from .. import dynamics, goal_network


def distances(model: dict, goal: dict) -> tuple[dict, dict]:
    """Maximize discounted weight product; weights are not calibrated probabilities."""
    nodes = {node['id']: node for node in model['memory']['nodes']}
    weights = {(e['from'], e['to']): e['weight'] for e in model['memory']['edges'] if e['kind'] == 'backward'}
    incoming: dict[str, list] = {}
    transitions = {}
    discount = model['intent']['config']['discount']
    for node in nodes.values():
        if node['kind'] != 'transition':
            continue
        weight = weights.get((node['to'], node['id']), 0) * discount
        back = weights.get((node['id'], node['from']), 0)
        if weight > 0 and back > 0:
            transitions[node['id']] = (node, weight, back)
            incoming.setdefault(node['to'], []).append((node['from'], -math.log(weight * back)))
    targets = [n['id'] for n in nodes.values() if n['kind'] == 'state' and
               ((goal['kind'] == 'field' and 'focus:' + goal['focus'] in n['features']) or
                (goal['kind'] == 'state' and set(goal['features']).issubset(n['features'])))]
    result = {target: 0.0 for target in targets}
    queue = [(0.0, target) for target in targets]
    heapq.heapify(queue)
    while queue:
        cost, target = heapq.heappop(queue)
        if cost > result[target]:
            continue
        for source, step_cost in incoming.get(target, []):
            value = cost + step_cost
            if value < result.get(source, math.inf):
                result[source] = value
                heapq.heappush(queue, (value, source))
    return result, transitions


def route(model: dict, goal: dict, event: dict, rehearsal: bool = False, single: bool = False) -> dict:
    """Use ordinary shortest-path selection and the common sensory/motor guards."""
    if rehearsal:
        raise ValueError('Rehearsal is outside this benchmark')
    intent = model['intent']
    cfg = intent['config']
    intent['wave'] += 1
    costs, transitions = distances(model, goal)
    activity = {}
    for identifier, (node, weight, _) in transitions.items():
        cost = costs.get(node['to'], math.inf)
        if not single or cost == 0:
            activity[identifier] = weight * math.exp(-cost)
    event.update(kind='search', candidates=dynamics.transition_candidates(model, activity, cfg, cfg['routeThreshold']))
    eligible = [c for c in event['candidates'] if c['allowed'] and activity.get(c['id'], 0) > 0
                and c['id'] not in intent['error']]
    # Equal-cost routes with individually unambiguous motor targets are both valid.
    # Unlike activation dynamics, graph search needs no convergence/margin gate.
    if eligible:
        winner = min(eligible, key=lambda c: (-activity[c['id']], c['label']))
        _select(model, winner, event)
    elif intent['wave'] >= cfg['maxWaves']:
        model.update(status='blocked', message='No learned route above the shared threshold')
    return event


def _select(model: dict, winner: dict, event: dict) -> None:
    """Populate the documented episode contract consumed by the native executor."""
    node = goal_network.node(model, winner['id'])
    model['intent']['episode'] = dict(transition=node['id'], step=node['first'], last=node['last'],
                                     source=node['from'], target=node['to'])
    model['entry'] = node['first']
    model['recoveries'] += 1
    model['refractory'][node['id']] = model['intent']['config']['refractory']
    model['trace'][node['id']] = 1
    model['intent']['eligibility'][node['id']] = 1
    event.update(kind='route', winner=node['id'])
