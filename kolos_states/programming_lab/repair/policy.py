"""Learn from observed patch outcomes and rank new sites using native graph memory."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from statistics import mean

from ... import experience
from ...core import StateEngine
from ..transform import GuardRule
from .cases import Task
from .evaluation import Check, evaluate
from .patches import Patch, candidates

VERIFIED = 'repair-outcome:passed'
REJECTED = 'repair-outcome:failed'


def locality(patch: Patch, failure: Check) -> tuple[int, str]:
    """Describe a proposed site using only the observed failing call."""
    calls = [visit for visit in failure.trace if visit.function == patch.function]
    if not calls:
        return 0, 'unseen-function'
    position = 'unseen-line'
    for distance, call in enumerate(reversed(calls)):
        if call.line == patch.line:
            position = ('last-line', 'previous-line', 'earlier-line')[min(distance, 2)]
            break
    return max(visit.depth for visit in calls), position


def _features(patch: Patch, failure: Check) -> tuple[str, ...]:
    """Reuse context across tasks without retaining file, function or fixture identifiers."""
    _, position = locality(patch, failure)
    symptom = 'exception' if failure.error else 'wrong-result'
    return (f'{symptom}/{patch.kind}', f'{patch.kind}/{position}',
            f'{symptom}/{patch.kind}/{position}')


def _remember(engine: StateEngine, key: str, passed: int, failed: int, *, exact: bool = False) -> None:
    """Store test-backed associations as native state transitions with smoothed weights."""
    before = dict(features=[f'repair-feature:{key}'])
    for outcome, count in ((VERIFIED, passed), (REJECTED, failed)):
        if count:
            after = dict(features=[outcome])
            receipt = dict(id=key, ok=True, action=dict(kind='click', object='evaluate-candidate'),
                           before=before, after=after)
            transition, _ = experience.remember(engine.model, [receipt], exact=exact)
            if transition is None:
                raise ValueError(f'Память не приняла учебную связь {key}.')
            link = next(edge for edge in engine.edges(transition['from'], 'applicable')
                        if edge['to'] == transition['id'])
            engine.set_weight(link['id'], count / (passed + failed + 2))


def teach(engine: StateEngine, tasks: tuple[Task, ...], rule: GuardRule) -> dict:
    """Observe successes and failures in training sources before freezing the graph."""
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    rows = []
    for task in tasks:
        probes = task.visible + task.hidden
        observed = evaluate(task.source, probes, tracing=True)
        failure = next(check for check in observed if not check.passed)
        labels = []
        for patch in candidates(task.source, rule):
            passes = all(check.passed for check in evaluate(patch.source, probes))
            for key in _features(patch, failure):
                counts[key][0 if passes else 1] += 1
            labels.append(dict(kind=patch.kind, function=patch.function, line=patch.line, passed=passes))
        if not any(row['passed'] for row in labels):
            raise ValueError(f'Teaching case {task.name} has no verified patch')
        rows.append(dict(task=task.name, candidates=labels))
    for key, (passed, failed) in sorted(counts.items()):
        _remember(engine, key, passed, failed)
    return dict(tasks=rows, feature_counts=dict(sorted(counts.items())))


def _activation(engine: StateEngine, key: str) -> float:
    """Read success minus failure evidence directly from the restored graph."""
    state = engine.state(dict(features=[f'repair-feature:{key}']))
    if state is None:
        return 0.0
    total = 0.0
    for link in engine.edges(state['id'], 'applicable'):
        transition = engine.node(link['to'])
        result = engine.node(transition['to'])
        total += link['weight'] if result['features'] == [VERIFIED] else -link['weight']
    return total


Ranker = Callable[[Patch, Check], tuple[int, float]]


def trace_order(patch: Patch, failure: Check) -> tuple[int, float]:
    """Enumerate deepest observed functions first, with source-order ties."""
    depth, _ = locality(patch, failure)
    return -depth, 0.0


def recent_order(patch: Patch, failure: Check) -> tuple[int, float]:
    """Use a stronger fixed baseline that also prioritizes the last executed lines."""
    depth, position = locality(patch, failure)
    positions = ('last-line', 'previous-line', 'earlier-line', 'unseen-line', 'unseen-function')
    return -depth, float(positions.index(position))


def learned_order(engine: StateEngine) -> Ranker:
    """Keep the shared depth ordering and rank same-depth edits by learned outcomes."""
    def rank(patch: Patch, failure: Check) -> tuple[int, float]:
        priority = mean(_activation(engine, key) for key in _features(patch, failure))
        return trace_order(patch, failure)[0], -priority

    return rank
