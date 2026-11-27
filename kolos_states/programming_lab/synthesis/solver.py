"""Search with learned graph weights, then independently check the selected program."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from time import monotonic

from ...core import StateEngine
from ..repair.policy import _activation, _remember
from .constraints import from_examples
from .corpus import TEACHING
from .grammar import CMP, Recipe, choices, render, semantic_key
from .grouped import compose_choices
from .judge import Check, evaluate
from .spec import Example, Task, result_kind


def _count_possible(recipe: Recipe, examples: tuple[Example, ...]) -> bool:
    """Rule out counts that violate a structural upper or lower bound."""
    if recipe.reduce != 'count':
        return True
    if recipe.group is None:
        return all(0 <= e.expected <= len(e.input) for e in examples)
    return all(0 <= value <= sum(item[recipe.group] == key for item in e.input)
               for e in examples for key, value in e.expected.items())


def _order(recipe: Recipe) -> tuple:
    """Use a deterministic simplicity tie-breaker shared with the empty graph."""
    p = recipe.predicate or recipe.result_predicate
    return (p is not None, abs(p.threshold) if p else 0, tuple(CMP).index(p.op) if p else 0,
            recipe.reduce, recipe.value or '', recipe.group or '', (p.column or '') if p else '',
            recipe.result_predicate is not None)


def _feature(recipe: Recipe, examples: tuple[Example, ...]) -> str:
    """Remember an operation family independent of task name, columns and held-out examples."""
    p = recipe.predicate
    operation = f'{recipe.reduce}/{p.op if p else "all"}'
    return f'synthesis/{result_kind(examples[0].expected)}/{operation}'


def _features(recipe: Recipe, examples: tuple[Example, ...]) -> tuple[str, ...]:
    """Retrieve known aggregation and filter experience separately for a new composition."""
    known = _feature(recipe, examples)
    if recipe.result_predicate is None:
        return (known,)
    return known, f'synthesis/list/filter/{recipe.result_predicate.op}'


def train(tasks: tuple[Task, ...] = TEACHING) -> tuple[StateEngine, dict[str, list[int]]]:
    """Learn from independently checked teaching solutions on this separate corpus."""
    engine = StateEngine()
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for task in tasks:
        features: dict[str, bool] = {}
        for recipe in choices(task.examples):
            if not _count_possible(recipe, task.examples):
                continue
            key = _feature(recipe, task.examples)
            if not features.get(key):
                source = render(task, recipe)
                features[key] = evaluate(source, task.function, task.parameter, task.examples + task.checks).passed
        if not any(features.values()):
            raise ValueError(f'В учебной задаче {task.function} нет подтверждённого решения.')
        for key, passed in features.items():
            counts[key][0 if passed else 1] += 1
    for key, (passed, failed) in sorted(counts.items()):
        _remember(engine, key, passed, failed)
    return engine, dict(counts)


def _candidates(examples: tuple[Example, ...], engine: StateEngine, *, compose: bool
                ) -> tuple[list[Recipe], dict[str, int]]:
    """Deduplicate and rank the same task-visible candidate pool with either graph."""
    recipes = [r for r in choices(examples) if _count_possible(r, examples)]
    permitted = from_examples(examples)
    if compose and result_kind(examples[0].expected) == 'mapping':
        recipes, permitted = compose_choices(examples, recipes)
    distinct: dict[Recipe, list[Recipe]] = defaultdict(list)
    for recipe in recipes:
        distinct[semantic_key(recipe)].append(recipe)
    compatible = [variants for key, variants in distinct.items() if permitted is None or permitted(key)]
    features = {key for variants in compatible for r in variants for key in _features(r, examples)}
    weights = {key: _activation(engine, key) for key in features}

    def rank(recipe: Recipe) -> tuple:
        order = _order(recipe)
        keys = _features(recipe, examples)
        learned = -sum(weights[key] for key in keys) / len(keys)
        if permitted is not None:
            # Several exact matches can remain. Keep simpler rules ahead of a learned syntax preference.
            return (*order[:2], learned, *order[2:])
        return (learned, *order)

    candidates = sorted((min(variants, key=rank) for variants in compatible), key=rank)
    return candidates, dict(considered=len(recipes), equivalent=len(recipes) - len(distinct),
                            rejected_by_examples=len(distinct) - len(candidates), eligible=len(candidates))


def check(task: Task, source: str, *, independent: bool = False) -> Check:
    """Use the common evaluator and explicitly choose the public or independent set."""
    return evaluate(source, task.function, task.parameter, task.checks if independent else task.examples)


def finish(task: Task, source: str, attempts: list[dict]) -> dict:
    """The independent judge gets one submission after search ends."""
    result = check(task, source, independent=True)
    return dict(status='solved' if result.passed else 'check_failed', attempts=attempts,
                verification=asdict(result), source=source if result.passed else None)


def solve(task: Task, engine: StateEngine, budget: int, deadline: float, *, compose: bool = False) -> dict:
    """Submit the first publicly correct program within the shared attempt limit."""
    attempts = []
    candidates, screening = _candidates(task.examples, engine, compose=compose)
    evidence = dict(attempts=attempts, screening=screening, source=None)
    for recipe in candidates[:budget]:
        if monotonic() >= deadline:
            return dict(status='time_limit', **evidence)
        source = render(task, recipe)
        observed = check(task, source)
        attempts.append(dict(recipe=asdict(recipe), feedback=asdict(observed)))
        if observed.passed:
            return dict(screening=screening, **finish(task, source, attempts))
    return dict(status='no_solution', **evidence)
