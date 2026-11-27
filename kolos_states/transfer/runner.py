"""Common observation/receipt loop and independent result oracle for all selectors."""
from __future__ import annotations

import hashlib
import json
from time import perf_counter_ns
from unittest.mock import patch

from .. import goal_network
from ..core import StateEngine, STOP
from ..protocol import persistent_graph
from ..simulator import apply, observe
from . import planner
from .selection_controls import early_decision
from .world import Lab

NATIVE_ROUTE = goal_network.route_wave


def fingerprint(engine: StateEngine) -> str:
    """Hash persistent graph only, excluding transient currents and inhibition."""
    raw = json.dumps(persistent_graph(engine.model['memory']), sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()


def _shift(world: dict) -> None:
    """Move known objects and add a new unrelated observation without hiding any."""
    for surface in world['surfaces'].values():
        for icon in surface['icons']:
            icon['x'] += 25
            icon['y'] += 20
        surface['icons'].append(dict(id='untrained-distractor', x=1100, y=850))


def _route(selector: str, model: dict, target: dict, event: dict, rehearsal: bool) -> dict:
    """Switch only route selection; all arms keep the production executor."""
    if selector == 'native':
        return NATIVE_ROUTE(model, target, event, rehearsal)
    if selector == 'early':
        with patch.object(goal_network, 'route_decision', early_decision):
            return NATIVE_ROUTE(model, target, event, rehearsal)
    return planner.route(model, target, event, rehearsal, single=selector == 'single')


def run_case(engine: StateEngine, lab: Lab, spec: dict, selector: str = 'native', changed: bool = False) -> dict:
    """Run a goal without exposing world transitions or the oracle to a selector."""
    if selector not in ('native', 'early', 'planner', 'single'):
        raise ValueError('Unknown selector: ' + selector)
    engine.reset()
    engine.events.clear()
    world = lab.at(spec['start'], changed)
    if spec.get('shifted'):
        _shift(world)
    before = fingerprint(engine)
    goal = dict(kind='field', focus=lab.field, value=spec['value'])
    engine.start_goals([goal], observe(world))
    timing = dict(route_ns=0, route_calls=0)

    def choose(model: dict, target: dict, event: dict, rehearsal: bool = False) -> dict:
        """Instrument identical route boundaries for both implementations."""
        start = perf_counter_ns()
        try:
            return _route(selector, model, target, event, rehearsal)
        finally:
            timing['route_ns'] += perf_counter_ns() - start
            timing['route_calls'] += 1

    start = perf_counter_ns()
    with patch.object(goal_network, 'route_wave', choose):
        injected = _execute(engine, world, spec)
    elapsed = perf_counter_ns() - start
    return _result(engine, lab, spec, world, before, timing, elapsed, injected)


def _execute(engine: StateEngine, world: dict, spec: dict) -> bool:
    """Host owns effects; an intervention happens only between acknowledged actions."""
    injected = False
    for _ in range(1805):
        if engine.model['status'] in STOP:
            break
        if spec.get('interrupt') and not injected and world['surface'] == 'form' and not engine.model['pending']:
            world.update(surface='overlay', focus='', output='', selected='', version=world['version'] + 1)
            engine.observe(observe(world))
            injected = True
        engine.tick()
        if engine.model['pending']:
            receipt = apply(world, engine.model['pending'])
            engine.tick()  # An effect and its acknowledgement are distinct ticks.
            engine.accept_receipt(receipt)
    return injected


def _result(engine: StateEngine, lab: Lab, spec: dict, world: dict, before: str,
            timing: dict, elapsed: int, injected: bool) -> dict:
    """Success is measured in environment state, independent of agent self-report."""
    declared = engine.model['status'] == 'complete'
    actual = world['surface'] == 'focused' and world['focus'] == lab.field and world['output'] == spec['value']
    bad_keys = sum(r['action']['kind'] == 'key' and r['before']['focus'] != lab.field for r in world['effects'])
    errors = sum(r['ok'] and r['action'].get('object') == lab.objects['fast'] and
                 lab.objects['return'] in [i['id'] for i in r['after']['icons']] for r in world['effects'])
    return dict(seed=lab.seed, case=spec['case'], value=spec['value'], status=engine.model['status'],
                success=declared and actual and not bad_keys and (injected or not spec.get('interrupt')),
                false_success=declared and not actual, bad_keys=bad_keys, wrong_fast=errors,
                ticks=engine.model['tick'], actions=[r['action'] for r in world['effects']],
                errors=len(engine.model['intent']['errorHistory']), injected=injected,
                prediction_errors=engine.model['intent']['errorHistory'],
                weight_updates=[change for ev in engine.events
                                for change in ev.get('plasticity', {}).get('changes', [])],
                memory_before=before, memory_after=fingerprint(engine), elapsed_ns=elapsed, **timing)


def remove_focus_links(engine: StateEngine, field: str) -> None:
    """A causal lesion removes outcome edges of every learned route into the field."""
    nodes = {n['id']: n for n in engine.model['memory']['nodes']}
    doomed = {n['id'] for n in nodes.values() if n['kind'] == 'transition'
              and 'focus:' + field in nodes[n['to']]['features']}
    for edge in engine.model['memory']['edges']:
        if edge['kind'] == 'backward' and edge['to'] in doomed:
            edge['weight'] = 0
