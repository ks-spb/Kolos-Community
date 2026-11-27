"""Compare native waves with an ordinary Dijkstra policy cached by goal and graph."""
from __future__ import annotations

import math
from time import perf_counter_ns

from .. import dynamics, goal_network
from ..transfer import planner

NATIVE_ROUTE = goal_network.route_wave
SELECTORS = ('native', 'native_low_threshold', 'dijkstra_cached')
LOW_THRESHOLD = .250001


class Selector:
    """Instrument route boundaries, including cache invalidation and rebuild costs."""

    def __init__(self, name: str) -> None:
        """Start with an empty policy for every independent trial."""
        if name not in SELECTORS:
            raise ValueError('Unknown selector: ' + name)
        self.name = name
        self.signature: tuple | None = None
        self.activity: dict = {}
        self.stats = dict(route_ns=0, route_calls=0, builds=0, cache_hits=0, build_ns=0)

    def route(self, model: dict, goal: dict, event: dict, rehearsal: bool = False) -> dict:
        """Use the identical native executor, sensory checks and action receipts."""
        start = perf_counter_ns()
        try:
            if self.name != 'dijkstra_cached':
                return NATIVE_ROUTE(model, goal, event, rehearsal)
            if rehearsal:
                raise ValueError('Rehearsal is outside this experiment')
            return self._dijkstra(model, goal, event)
        finally:
            self.stats['route_calls'] += 1
            self.stats['route_ns'] += perf_counter_ns() - start

    def _dijkstra(self, m: dict, goal: dict, event: dict) -> dict:
        """Rebuild on changed goals/weights, then choose from currently permitted transitions."""
        cfg = m['intent']['config']
        signature = (goal['kind'], tuple(goal.get('features', [goal.get('focus')])), cfg['discount'],
                     [(n['id'], n['kind'], n.get('from'), n.get('to'), tuple(n.get('features', []))) for n in m['memory']['nodes']],
                     [(e['from'], e['to'], e['weight']) for e in m['memory']['edges'] if e['kind'] == 'backward'])
        if signature != self.signature:
            self._build(m, goal, signature)
        else:
            self.stats['cache_hits'] += 1
        m['intent']['wave'] += 1
        event.update(kind='search', candidates=dynamics.transition_candidates(m, self.activity, cfg, cfg['routeThreshold']))
        candidates = [c for c in event['candidates'] if c['allowed'] and self.activity.get(c['id'], 0) > 0
                      and c['id'] not in m['intent']['error']]
        if candidates:
            planner._select(m, min(candidates, key=lambda c: (-self.activity[c['id']], c['label'])), event)
        elif m['intent']['wave'] >= cfg['maxWaves']:
            m.update(status='blocked', message='No learned route to the active goal')
        return event

    def _build(self, model: dict, goal: dict, signature: tuple) -> None:
        """Keep the complete goal policy, allowing free lookup after every acknowledged step."""
        start = perf_counter_ns()
        costs, transitions = planner.distances(model, goal)
        self.activity = {id: weight * math.exp(-costs.get(node['to'], math.inf))
                         for id, (node, weight, _) in transitions.items()}
        self.signature = signature
        self.stats['builds'] += 1
        self.stats['build_ns'] += perf_counter_ns() - start
