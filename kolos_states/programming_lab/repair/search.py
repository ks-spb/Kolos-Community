"""Shared candidate search and independent acceptance scoring."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .cases import Probe, Task
from .evaluation import Check, evaluate
from .patches import Patch
from .policy import Ranker


@dataclass
class Search:
    """Return the first proposal that passes visible tests and its attempt history."""

    initial: list[Check]
    attempts: list[dict]
    proposal: Patch | None = None


def solve(source: str, visible: tuple[Probe, ...], patches: list[Patch],
          rank: Ranker, budget: int) -> Search:
    """Try candidates only from the original source and use only visible feedback."""
    initial = evaluate(source, visible, tracing=True)
    search = Search(initial, [])
    failure = next((check for check in initial if not check.passed), None)
    if failure is None:
        return search
    ordered = sorted(patches, key=lambda patch: rank(patch, failure))
    for patch in ordered[:budget]:
        checks = evaluate(patch.source, visible)
        search.attempts.append(dict(kind=patch.kind, function=patch.function, line=patch.line,
                                    rank=rank(patch, failure), visible=[asdict(check) for check in checks]))
        if all(check.passed for check in checks):
            search.proposal = patch
            break
    return search


def score(task: Task, search: Search) -> tuple[dict, str | None]:
    """Run hidden checks once on the final answer and return only independently verified edits."""
    patch = search.proposal
    clean = all(check.passed for check in search.initial)
    checks = evaluate(patch.source if patch else task.source, task.hidden) if patch or clean else []
    if patch or clean:
        passed = all(check.passed for check in checks)
        outcome = ('solved' if patch else 'unchanged') if passed else 'hidden-failed'
    else:
        outcome = 'no-solution'
    row = dict(task=task.name, status=outcome, attempts=search.attempts,
               initial=[asdict(check) for check in search.initial], hidden=[asdict(check) for check in checks])
    if patch:
        row['proposal'] = dict(kind=patch.kind, function=patch.function, line=patch.line)
    return row, patch.source if patch and outcome == 'solved' else None
