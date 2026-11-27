"""Combine filters, counts and sums into standalone Python source."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from itertools import product
from operator import eq, ge, gt, le, lt, ne

from .spec import Example, Task, item_shape, result_kind

CMP = {'>': gt, '<': lt, '>=': ge, '<=': le, '==': eq, '!=': ne}


@dataclass(frozen=True)
class Predicate:
    """Select items by testing one number, or one numeric field, against an integer."""

    column: str | None
    op: str
    threshold: int


@dataclass(frozen=True)
class Recipe:
    """Describe filtering and aggregation as a sequence of reusable operations."""

    reduce: str
    value: str | None = None
    group: str | None = None
    predicate: Predicate | None = None
    result_predicate: Predicate | None = None


def _predicate_key(p: Predicate | None) -> Predicate | None:
    """Normalize inclusive comparison of integers to a strict neighbour."""
    if p is not None and p.op == '>=':
        return Predicate(p.column, '>', p.threshold - 1)
    if p is not None and p.op == '<=':
        return Predicate(p.column, '<', p.threshold + 1)
    return p


def semantic_key(recipe: Recipe) -> Recipe:
    """Use one key for integer comparisons that agree on every possible input."""
    return replace(recipe, predicate=_predicate_key(recipe.predicate),
                   result_predicate=_predicate_key(recipe.result_predicate))


def _term(variable: str, column: str | None) -> str:
    """Construct an expression using a validated variable and escaped JSON field."""
    return variable if column is None else f'{variable}[{column!r}]'


def render(task: Task, recipe: Recipe) -> str:
    """Generate ordinary Python with no runtime dependency on Kolos."""
    item, output, key, selected = (name if name != task.parameter else f'_{name}'
                                   for name in ('item', 'result', 'key', 'selected'))
    initial = '{}' if recipe.group is not None else '[]' if recipe.reduce == 'filter' else '0'
    code = [f'def {task.function}({task.parameter}):', f'    {output} = {initial}',
            f'    for {item} in {task.parameter}:']
    indent = '        '
    if recipe.predicate:
        p = recipe.predicate
        code.append(f'{indent}if {_term(item, p.column)} {p.op} {p.threshold}:')
        indent += '    '
    amount = '1' if recipe.reduce == 'count' else _term(item, recipe.value)
    if recipe.reduce == 'filter':
        code.append(f'{indent}{output}.append({item})')
    elif recipe.group is not None:
        code += [f'{indent}{key} = {_term(item, recipe.group)}',
                 f'{indent}{output}[{key}] = {output}.get({key}, 0) + {amount}']
    else:
        code.append(f'{indent}{output} += {amount}')
    if recipe.result_predicate:
        p = recipe.result_predicate
        code += [f'    {selected} = {{}}', f'    for {key} in {output}:',
                 f'        if {output}[{key}] {p.op} {p.threshold}:',
                 f'            {selected}[{key}] = {output}[{key}]']
        output = selected
    return '\n'.join([*code, f'    return {output}', ''])


def integer_thresholds(numbers: Iterable[int]) -> list[int]:
    """Take literals from visible numbers and include zero as a common boundary."""
    values = sorted(set(numbers))
    if len(values) > 24:
        values = [values[i * (len(values) - 1) // 23] for i in range(24)]
    return sorted({0, *values}, key=lambda v: (abs(v), v))


def _thresholds(examples: tuple[Example, ...], field: str | None) -> list[int]:
    """Observe the selected numeric column across the open examples."""
    return integer_thresholds(item if field is None else item[field] for e in examples for item in e.input)


def choices(examples: tuple[Example, ...]) -> list[Recipe]:
    """Create the common candidate pool from observable types and field names."""
    shape = item_shape(next(item for e in examples for item in e.input))
    numbers = [key for key, kind in shape if kind is int] if shape else [None]
    output = result_kind(examples[0].expected)
    predicates = [None]
    predicates.extend(Predicate(key, op, n) for key in numbers
                      for n in _thresholds(examples, key) for op in CMP)
    if output == 'list':
        return [Recipe('filter', predicate=p) for p in predicates]
    reducers = [('count', None), *(('sum', key) for key in numbers)]
    if output == 'number':
        groups = [None]
    else:
        groups = [key for key, kind in shape if kind is str and all(
            set(e.expected) <= {item[key] for item in e.input} for e in examples)]
    return [Recipe(reduce, key, group, p) for (reduce, key), group, p in product(reducers, groups, predicates)]
