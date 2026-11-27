"""Derive exact numeric candidate constraints from open examples without running Python code."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Callable
from dataclasses import dataclass
from itertools import accumulate

from .grammar import CMP, Predicate, Recipe
from .spec import Example


@dataclass(frozen=True)
class Selection:
    """Numbers that a filter must keep and numbers it must drop."""

    keep: set[int]
    drop: set[int]

    def permits(self, recipe: Recipe) -> bool:
        """Compare distinct labels rather than rerunning a program for each rule."""
        return self.matches(recipe.predicate)

    def matches(self, p: Predicate | None) -> bool:
        """Check which observed values an integer predicate keeps."""
        if p is None:
            return not self.drop
        predicate = CMP[p.op]
        return (all(predicate(x, p.threshold) for x in self.keep)
                and not any(predicate(x, p.threshold) for x in self.drop))


def _selection(examples: tuple[Example, ...]) -> Selection | None:
    """Check that examples preserve order and agree on every observed number."""
    keep, drop = set(), set()
    for example in examples:
        selected = set(example.expected)
        if [x for x in example.input if x in selected] != example.expected:
            return None
        keep.update(selected)
        drop.update(x for x in example.input if x not in selected)
    return None if keep & drop else Selection(keep, drop)


@dataclass(frozen=True)
class Totals:
    """A sorted open input with cumulative sums for constant-time range totals."""

    values: list[int]
    prefix: list[int]
    expected: int

    @classmethod
    def from_example(cls, example: Example) -> Totals:
        """Index each example once for every threshold and reducer."""
        values = sorted(example.input)
        return cls(values, list(accumulate(values, initial=0)), example.expected)

    def _range(self, p: Predicate) -> tuple[int, int]:
        """Translate integer comparisons to the matching half-open range."""
        lower = bisect_left(self.values, p.threshold)
        upper = bisect_right(self.values, p.threshold, lo=lower)
        if p.op == '>':
            return upper, len(self.values)
        if p.op == '>=':
            return lower, len(self.values)
        if p.op == '<':
            return 0, lower
        if p.op == '<=':
            return 0, upper
        return lower, upper

    def permits(self, recipe: Recipe) -> bool:
        """Read the implied count or sum, including complements for inequality."""
        p = recipe.predicate
        lo, hi = self._range(p) if p is not None else (0, len(self.values))
        if recipe.reduce == 'count':
            value, total = hi - lo, len(self.values)
        else:
            value, total = self.prefix[hi] - self.prefix[lo], self.prefix[-1]
        if p is not None and p.op == '!=':
            value = total - value
        return value == self.expected


def from_examples(examples: tuple[Example, ...]) -> Callable[[Recipe], bool] | None:
    """Constrain integer lists. Leave record tasks to the original search."""
    first = next(item for e in examples for item in e.input)
    expected = examples[0].expected
    if type(first) is int and type(expected) is list:
        selection = _selection(examples)
        return selection.permits if selection is not None else lambda _: False
    if type(first) is int and type(expected) is int:
        totals = tuple(Totals.from_example(e) for e in examples)
        return lambda recipe: all(total.permits(recipe) for total in totals)
    return None
