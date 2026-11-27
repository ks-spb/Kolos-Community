"""Frozen versus explicitly adapted policies; the production learner is unchanged."""
from __future__ import annotations

import json
from time import perf_counter_ns

from ..episode_browser import BrowserEpisodeBridge
from ..cluster_replay.controllers import Host as OriginalHost, InvalidPlan, validate_plan as old_validate
from ..cluster_replay.corpus import digest
from ..cluster_replay.world import Blocked, UnknownOutcome
from ..protocol import persistent_graph
from .world import PREVIEW_ROLE, REVIEW, REVIEW_ROLE, World, operations

OLD_QUERY = 'Apply an approved cluster change'
NEW_QUERY = 'Apply an approved restoration with preview v2'


def validate_plan(plan: object) -> None:
    """Extend the finite local vocabulary with exactly one button, not arbitrary commands."""
    if not isinstance(plan, dict) or not isinstance(plan.get('operations'), list):
        old_validate(plan)
    if len(plan['operations']) > 16:
        raise InvalidPlan('Invalid operation count')
    checked = dict(plan, operations=[op for op in plan['operations'] if op != REVIEW])
    old_validate(checked)


class Host(OriginalHost):
    """Script and model share one exact additional primitive and its receipt check."""

    def perform(self, operation: dict) -> dict:
        """Reuse old operations; require a confirmed effect for the new review button."""
        if operation != REVIEW:
            return super().perform(operation)
        matches = [o for o in self.world.observe()['objects'] if o['descriptor']['name'] == REVIEW_ROLE]
        if len(matches) != 1:
            raise Blocked('Missing or ambiguous restoration review')
        self.serial += 1
        request = dict(id=f'local:{self.serial}', action=dict(kind='activate', object=matches[0]['id']))
        result = self.world.execute(request)
        observed = [o for o in result['after']['objects'] if o['descriptor']['name'] == PREVIEW_ROLE]
        if len(observed) != 1 or observed[0]['value'] != 'confirmed':
            raise Blocked('Restoration preview effect not observed')
        return result


def teach_revision(original: dict, case: dict) -> tuple[dict, dict]:
    """Add one full v2 demonstration as a separate command, preserving v1 experience."""
    start = perf_counter_ns()
    bridge, world = BrowserEpisodeBridge(json.loads(json.dumps(original))), World(case)
    old_graph = persistent_graph(bridge.engine.model['memory'])
    bridge.begin_teaching(NEW_QUERY)
    for operation in operations(True):
        kind, role = operation['kind'], operation['role']
        request = bridge.prepare(world.observe(), kind, role, 'v0' if kind == 'write' else None)
        receipt = world.execute(request)
        bridge.confirm(receipt['after'], world.observe())
    record = bridge.finish_teaching()
    graph = persistent_graph(bridge.engine.model['memory'])
    preserved = all(item in graph[key] for key in ('nodes', 'edges') for item in old_graph[key])
    return bridge.dump(), dict(elapsed_ns=perf_counter_ns() - start, demonstrations=1,
        demonstrated_operations=len(record['receipts']), llm_calls=0, input_tokens=0, output_tokens=0,
        old_graph_preserved=preserved, new_nodes=len(graph['nodes']) - len(old_graph['nodes']),
        commands=len(bridge.engine.model['episodeCommands']), incremental_splice=False,
        note='Full revised episode demonstrated; v1 command retained, no automatic single-step patching')


def run_script(world: World, adapted: bool, plan: dict | None = None) -> str:
    """Only the adapted script contains the explicit restoration-only insertion."""
    plan = plan if plan is not None else dict(operations=operations(adapted and world.review_required), outcome='complete')
    validate_plan(plan)
    host = Host(world)
    for operation in plan['operations']:
        host.perform(operation)
    return plan['outcome']


def run_kolos(world: World, learned: dict, adapted: bool) -> str:
    """Select the known command revision explicitly; never infer a graph repair secretly."""
    bridge = BrowserEpisodeBridge(json.loads(json.dumps(learned)))
    before = digest(persistent_graph(bridge.engine.model['memory']))
    query = NEW_QUERY if adapted and world.review_required else OLD_QUERY
    bridge.start(query, world.observe())
    for _ in range(20):
        request = bridge.next(world.observe())
        if request.get('status'):
            if digest(persistent_graph(bridge.engine.model['memory'])) != before:
                raise RuntimeError('Inference changed the learned graph')
            return request['status']
        receipt = world.execute(request)
        bridge.confirm(receipt['after'], world.observe())
    raise Blocked('Operation budget exhausted')


def trial(case: dict, variant: str, selector: str, learned: dict, adapted: bool,
          revision: int = 2, layout: int = 0, plan: dict | None = None) -> dict:
    """Keep completion, safe refusals and procedure-change failures separate."""
    world = World(case, variant, layout, revision)
    start, reason, protocol_error = perf_counter_ns(), '', False
    try:
        status = run_kolos(world, learned, adapted) if selector == 'kolos' else run_script(world, adapted, plan)
    except UnknownOutcome:
        status, reason = 'pending', 'lost_receipt_no_retry'
    except (ValueError, KeyError, TypeError) as error:
        status, reason = 'blocked', type(error).__name__ + ': ' + str(error)[:200]
        protocol_error = isinstance(error, InvalidPlan)
    result = dict(case=case['id'], variant=variant, selector=selector, status=status, reason=reason,
                  execute_ns=perf_counter_ns() - start, operations=world.operations,
                  protocol_error=protocol_error, **world.oracle(status))
    if protocol_error:
        result['correct_outcome'] = False
    return result
