"""Infer whether a filter belongs before or after grouping from open examples."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from .constraints import Selection
from .grammar import CMP, Predicate, Recipe, integer_thresholds, semantic_key
from .spec import Example


def _totals(recipe: Recipe, example: Example) -> dict[str, int]:
    """Calculate an abstract grouped result without running any generated code."""
    result: dict[str, int] = {}
    p = recipe.predicate
    predicate = CMP[p.op] if p is not None else None
    for row in example.input:
        if p is not None and not predicate(row[p.column], p.threshold):
            continue
        key = row[recipe.group]
        amount = 1 if recipe.reduce == 'count' else row[recipe.value]
        result[key] = result.get(key, 0) + amount
    return result


def _observed(totals: tuple[dict[str, int], ...], examples: tuple[Example, ...]) -> Selection | None:
    """An after-group filter may remove keys but must preserve exact totals for retained keys."""
    keep, drop = set(), set()
    for actual, example in zip(totals, examples, strict=True):
        if any(actual.get(key) != value for key, value in example.expected.items()):
            return None
        keep.update(example.expected.values())
        drop.update(actual[key] for key in actual.keys() - example.expected.keys())
    return None if keep & drop else Selection(keep, drop)


def compose_choices(examples: tuple[Example, ...], raw: list[Recipe]
                    ) -> tuple[list[Recipe], Callable[[Recipe], bool]]:
    """Reuse each unfiltered aggregation to propose filters on its output totals."""
    observations: dict[Recipe, Selection | None] = {}
    extended = raw.copy()
    for recipe in raw:
        if recipe.predicate is not None:
            continue
        totals = tuple(_totals(recipe, example) for example in examples)
        observations[recipe] = _observed(totals, examples)
        thresholds = integer_thresholds(number for result in totals for number in result.values())
        extended.extend(replace(recipe, result_predicate=Predicate(None, op, threshold))
                        for threshold in thresholds for op in CMP)

    def permitted(recipe: Recipe) -> bool:
        p = recipe.result_predicate
        if recipe.predicate is not None:
            return all(_totals(recipe, e) == e.expected for e in examples)
        facts = observations[replace(recipe, result_predicate=None)] if p is not None else observations[recipe]
        return facts is not None and facts.matches(p)

    return extended, permitted
