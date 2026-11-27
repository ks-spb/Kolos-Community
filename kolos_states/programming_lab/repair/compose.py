"""Search sequences of single Python edits using visible test feedback."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from heapq import heappop, heappush
from itertools import count

from ..transform import GuardRule
from .cases import Probe
from .evaluation import Check, evaluate
from .patches import Patch, candidates
from .policy import Ranker
from .search import Search

MAX_EDITS = 3


@dataclass(frozen=True)
class Revision:
    """The visible results of a tested source and its sequence of edits."""

    source: str
    checks: list[Check]
    path: tuple[int, ...] = ()


class Frontier:
    """Track candidate revisions with one common priority queue and deduplication rule."""

    def __init__(self, initial: list[Check], rule: GuardRule, rank: Ranker, *, feedback: bool) -> None:
        """Use the same original checks as the reference for each branch."""
        self.initial, self.rule, self.rank, self.feedback = initial, rule, rank, feedback
        self.serial = count()
        self.pending: list[tuple[tuple[float, ...], int, Revision, Patch]] = []

    def add(self, parent: Revision) -> None:
        """Queue every next edit and rank it against the current failing trace."""
        if len(parent.path) >= MAX_EDITS:
            return
        failure = next((check for check in parent.checks if not check.passed), None)
        if failure is None:
            return
        priority = (len(parent.path),)
        if self.feedback:
            regressions = sum(base.passed and not now.passed
                              for base, now in zip(self.initial, parent.checks, strict=True))
            failing = sum(not check.passed for check in parent.checks)
            priority = (regressions, failing, *priority)
        for patch in candidates(parent.source, self.rule):
            key = (*priority, *self.rank(patch, failure))
            heappush(self.pending, (key, next(self.serial), parent, patch))


def _record(result: Search, parent: Revision, patch: Patch, checks: list[Check]) -> Revision:
    """Make the tested revision and record its lineage and behavioral progress."""
    path = (*parent.path, len(result.attempts) + 1)
    result.attempts.append(dict(path=path, kind=patch.kind, function=patch.function, line=patch.line,
                                failed_before=sum(not check.passed for check in parent.checks),
                                failed_after=sum(not check.passed for check in checks),
                                visible=[asdict(check) for check in checks]))
    return Revision(patch.source, checks, path)


def compose(source: str, visible: tuple[Probe, ...], rule: GuardRule, rank: Ranker,
            budget: int, *, feedback: bool) -> Search:
    """Give every policy the same edit grammar, test budget and maximum depth."""
    initial = evaluate(source, visible, tracing=True)
    result = Search(initial, [])
    queue = Frontier(initial, rule, rank, feedback=feedback)
    queue.add(Revision(source, initial))
    tested = {source}
    while queue.pending and len(result.attempts) < budget:
        _, _, parent, patch = heappop(queue.pending)
        if patch.source in tested:
            continue
        tested.add(patch.source)
        checks = evaluate(patch.source, visible, tracing=True)
        current = _record(result, parent, patch, checks)
        if all(check.passed for check in checks):
            result.proposal = patch
            break
        queue.add(current)
    return result
