"""Controller strategies share the same local host and permitted primitives."""
from __future__ import annotations

import copy
import json
from time import perf_counter_ns

from ..episode_browser import BrowserEpisodeBridge
from .corpus import digest
from .world import Blocked, STEPS, UnknownOutcome, World


class InvalidPlan(Blocked):
    """Malformed output is a controller error, not a correct safety refusal."""


def validate_plan(plan: object) -> None:
    """Validate the closed data schema before dispatching any part of a model plan."""
    if not isinstance(plan, dict) or set(plan) != {'operations', 'outcome'}:
        raise InvalidPlan('Invalid plan envelope')
    if plan['outcome'] not in ('complete', 'blocked', 'pending'):
        raise InvalidPlan('Invalid outcome')
    operations = plan['operations']
    if not isinstance(operations, list) or len(operations) > 16:
        raise InvalidPlan('Invalid operation count')
    for operation in operations:
        if (not isinstance(operation, dict) or set(operation) != {'kind', 'role'}
                or (operation['kind'], operation['role']) not in STEPS):
            raise InvalidPlan('Unknown operation or parameters')


class Host:
    """Convert explicit semantic operations to the same typed local actions."""

    def __init__(self, world: World):
        """Keep per-attempt dataflow slots outside long-term controller memory."""
        self.world, self.slots, self.serial = world, {}, 0

    def perform(self, operation: dict) -> dict:
        """Reject unknown instructions; no Python, URLs, connectors or shell evaluation."""
        if set(operation) != {'kind', 'role'}:
            raise Blocked('Only kind and role are accepted')
        kind, role = operation['kind'], operation['role']
        if (kind, role) not in STEPS:
            raise Blocked('Unknown operation')
        obs = self.world.observe()
        matches = [o for o in obs['objects'] if o['descriptor']['name'] == role]
        if len(matches) != 1:
            raise Blocked('Missing or ambiguous role')
        self.serial += 1
        action = dict(kind=kind, object=matches[0]['id'])
        if kind == 'read':
            action['slot'] = 'target'
        elif kind == 'write':
            if 'target' not in self.slots:
                raise Blocked('Write has no observed source value')
            action.update(source='target', value=self.slots['target'])
        result = self.world.execute(dict(id='local:' + str(self.serial), action=action))
        if kind == 'read':
            self.slots['target'] = next(o['value'] for o in result['after']['objects']
                                        if o['id'] == action['object'])
        return result


def teach(case: dict) -> tuple[dict, dict]:
    """Teach one completed reconstruction using the actual production episode learner."""
    start = perf_counter_ns()
    world, bridge = World(case), BrowserEpisodeBridge()
    bridge.begin_teaching('Apply an approved cluster change')
    for kind, role in STEPS:
        request = bridge.prepare(world.observe(), kind, role, 'v0' if kind == 'write' else None)
        receipt = world.execute(request)
        bridge.confirm(receipt['after'], world.observe())
    record = bridge.finish_teaching()
    return bridge.dump(), dict(elapsed_ns=perf_counter_ns() - start, operations=len(record['receipts']),
                               llm_calls=0, tokens=0, note='Human-authored teaching sequence; annotation labor not priced')


def run_script(world: World, plan: dict | None = None) -> str:
    """Execute a hand-authored fixed recipe, or an LLM's batched recipe through the same host."""
    host = Host(world)
    plan = plan if plan is not None else dict(operations=[dict(kind=k, role=r) for k, r in STEPS], outcome='complete')
    validate_plan(plan)
    for operation in plan['operations']:
        host.perform(operation)
    return plan['outcome']


def run_kolos(world: World, learned: dict) -> str:
    """Reload only learned memory; values and runtime IDs are from the new case."""
    bridge = BrowserEpisodeBridge(json.loads(json.dumps(learned)))
    before = digest(bridge.engine.model['memory'])
    bridge.start('Apply an approved cluster change', world.observe())
    for _ in range(20):
        request = bridge.next(world.observe())
        if request.get('status'):
            if digest(bridge.engine.model['memory']) != before:
                raise RuntimeError('Inference changed learned graph')
            return request['status']
        receipt = world.execute(request)
        bridge.confirm(receipt['after'], world.observe())
    raise Blocked('Operation budget exhausted')


def trial(case: dict, variant: str, selector: str, learned: dict, plan: dict | None = None,
          layout: int = 0) -> dict:
    """Time actual execution, preserve errors, and ask the independent host oracle."""
    world, start = World(case, variant, layout), perf_counter_ns()
    reason, protocol_error = '', False
    try:
        status = run_kolos(world, learned) if selector == 'kolos' else run_script(world, plan)
    except UnknownOutcome:
        status, reason = 'pending', 'lost_receipt_no_retry'
    except (ValueError, KeyError, TypeError) as error:
        status, reason = 'blocked', type(error).__name__ + ': ' + str(error)[:200]
        protocol_error = isinstance(error, InvalidPlan)
    result = dict(case=case['id'], variant=variant, selector=selector, status=status, reason=reason,
                protocol_error=protocol_error,
                execute_ns=perf_counter_ns() - start, operations=copy.deepcopy(world.operations),
                **world.oracle(status))
    if protocol_error:
        result['correct_outcome'] = False
    return result
