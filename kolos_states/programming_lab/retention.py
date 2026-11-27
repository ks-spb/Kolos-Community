"""Run the previous programming tasks against a supplied, frozen graph."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from time import monotonic, perf_counter

from ..core import StateEngine
from . import fixtures
from .calculator.cli import SHORT_REQUEST
from .calculator.intent import Clarification, recognize
from .calculator.lab import generate as calculator
from .episode import run_episode
from .repair.cases import HELD_OUT as BUGS
from .repair.compose import compose
from .repair.composition_cases import PAIRS
from .repair.patches import candidates
from .repair.policy import learned_order
from .repair.search import score, solve as repair
from .synthesis.corpus import HELD_OUT as FUNCTIONS
from .synthesis.group_corpus import ORDERED_TASKS
from .synthesis.solver import solve as synthesize
from .transform import GuardRule, learn_guard


def _repairs(engine: StateEngine, rule: GuardRule) -> dict:
    """Use the original repair budgets for the existing primary cohorts."""
    rank = learned_order(engine)
    result = {}
    for label, tasks in (('single_repairs', BUGS), ('compound_repairs', PAIRS)):
        rows = []
        for task in tasks:
            if label == 'single_repairs':
                attempt = repair(task.source, task.visible, candidates(task.source, rule), rank, 3)
            else:
                attempt = compose(task.source, task.visible, rule, rank, 12, feedback=True)
            row, _ = score(task, attempt)
            rows.append(dict(task=task.name, status=row['status'], attempts=len(row['attempts'])))
        result[label] = rows
    return result


def _functions(engine: StateEngine) -> dict:
    """Score the same fixed held-out functions and group-order cohorts."""
    result = {}
    for label, tasks in (('synthesis', FUNCTIONS), ('group_order', ORDERED_TASKS)):
        rows = []
        for task in tasks:
            row = synthesize(task, engine, 8, monotonic() + 120, compose=label == 'group_order')
            rows.append(dict(task=task.function, status=row['status'], attempts=len(row['attempts'])))
        result[label] = rows
    return result


def _calculator(engine: StateEngine, output: Path) -> dict:
    """Exercise the previous full calculator with its own independent CLI checks."""
    try:
        intent = recognize(SHORT_REQUEST, engine)
    except Clarification:
        return dict(status='needs_clarification', attempts=0, checks_passed=0)
    result = calculator(intent, engine, output)
    return dict(status=result['status'], attempts=len(result['attempts']),
                checks_passed=sum(row['passed'] for row in result.get('checks', ())))


def measure(engine: StateEngine, directory: Path) -> dict:
    """Return comparable per-task results without modifying the loaded graph."""
    start = perf_counter()
    rule = learn_guard(fixtures.DEMO.source, fixtures.DEMO_AFTER, fixtures.DEMO.name)
    guards = []
    for case in fixtures.HELD_OUT:
        trial, code = run_episode(deepcopy(engine), case, rule)
        guards.append(dict(task=case.key, status='solved' if code is not None else trial['status']))
    tasks = dict(guard_transfer=guards, **_repairs(engine, rule), **_functions(engine))
    summary = {label: dict(total=len(rows), solved=sum(row['status'] == 'solved' for row in rows),
                           attempts=sum(row.get('attempts', 0) for row in rows)) for label, rows in tasks.items()}
    calc = _calculator(engine, directory / 'calculator.py')
    return dict(tasks=tasks, summary=summary, calculator=calc, elapsed_seconds=round(perf_counter() - start, 4))
