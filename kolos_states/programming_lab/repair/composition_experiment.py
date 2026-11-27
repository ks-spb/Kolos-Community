"""Compare multi-edit policies and verify that held-out tasks actually need two edits."""
from __future__ import annotations

from pathlib import Path

from ...core import StateEngine
from ..transform import GuardRule
from .cases import Task
from .compose import compose
from .composition_cases import CHECKS, PAIRS, SINGLE
from .evaluation import evaluate
from .patches import candidates
from .policy import Ranker, learned_order, recent_order, trace_order
from .search import score

DEFAULT_BUDGET = 12


def minimum_edits(task: Task, rule: GuardRule) -> dict:
    """Use all tests in a separate breadth-first audit to certify the minimum up to two."""
    probes = task.visible + task.hidden
    tested = {task.source}
    counts = [1, 0, 0]
    if all(check.passed for check in evaluate(task.source, probes)):
        return dict(minimum=0, checks_by_depth=counts)
    frontier = [task.source]
    for depth in (1, 2):
        following = []
        for source in frontier:
            for patch in candidates(source, rule):
                if patch.source not in tested:
                    tested.add(patch.source)
                    following.append(patch.source)
        for source in following:
            counts[depth] += 1
            if all(check.passed for check in evaluate(source, probes)):
                return dict(minimum=depth, checks_by_depth=counts)
        frontier = following
    return dict(minimum=None, checks_by_depth=counts)


def _trial(folder: Path, label: str, task: Task, rule: GuardRule, rank: Ranker,
           feedback: bool, budget: int) -> dict:
    """Run the policy without access to the oracle and save only verified final source."""
    search = compose(task.source, task.visible, rule, rank, budget, feedback=feedback)
    row, verified = score(task, search)
    lineage = search.attempts[-1]['path'] if search.proposal else ()
    chain = [search.attempts[i - 1] for i in lineage]
    row['edits'] = [{k: attempt[k] for k in ('path', 'kind', 'function', 'line', 'failed_before', 'failed_after')}
                    for attempt in chain]
    if verified is not None:
        (folder / f'{label}.after.py').write_text(verified, encoding='utf-8', newline='')
    return row


def compare_composed(path: Path, engine: StateEngine, rule: GuardRule, budget: int) -> dict:
    """Isolate the effects of feedback and learned rankings under a shared search budget."""
    policies = {'kolos': (learned_order(engine), True), 'enumeration': (trace_order, False),
                'trace-recency': (recent_order, True), 'no-memory': (learned_order(StateEngine()), True)}
    results = {}
    for task in PAIRS + CHECKS:
        folder = path / task.name
        folder.mkdir()
        (folder / 'before.py').write_text(task.source, encoding='utf-8', newline='')
        trials = {label: _trial(folder, label, task, rule, rank, feedback, budget)
                  for label, (rank, feedback) in policies.items()}
        audit = minimum_edits(task, rule)
        primary = task in PAIRS
        expected = 2 if primary else {SINGLE.name: 1, 'already-correct': 0, 'hidden-failure': 2}.get(task.name)
        results[task.name] = dict(expected=task.outcome, primary=primary, trials=trials, oracle=audit,
                                  oracle_passed=audit['minimum'] == expected)
    return results
