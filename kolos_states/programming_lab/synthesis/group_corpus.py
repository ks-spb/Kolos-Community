"""Fresh tasks where a filter on group totals cannot be moved to the input rows."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from operator import eq, ge, gt, le, lt, ne

from .corpus import TEACHING
from .grammar import choices, render, semantic_key
from .judge import evaluate
from .spec import Example, Item, Task

_FIELDS = (('sku', 'qty'), ('product', 'change'), ('code', 'units'))
_SUM_CRITERIA = ((gt, 0), (lt, 0), (eq, 0), (ne, 0), (ge, 2), (le, -2))
_COUNT_CRITERIA = ((gt, 2), (lt, 3), (eq, 2), (ne, 3), (ge, 4), (le, 4))


def _rows(groups: Iterable[tuple[str, list[int]]], key: str, amount: str) -> list[Item]:
    """Interleave disjoint groups and include distractor columns."""
    bucket = [[{key: group, amount: value, 'shelf': f'bin-{i}', 'pack': 2}
               for i, value in enumerate(values)] for group, values in groups]
    return [items[index] for index in range(max(map(len, bucket), default=0))
            for items in bucket if index < len(items)]


def _reference(rows: list[Item], key: str, amount: str, reducer: Callable[[list[int]], int],
               include: Callable[[int], bool], *, row_filter: bool = False) -> dict[str, int]:
    """Use a per-key reference calculation independent of the synthesis planner."""
    result = {}
    selected = [row for row in rows if not row_filter or row[amount] > 0]
    for label in sorted({row[key] for row in selected}):
        value = reducer([row[amount] for row in selected if row[key] == label])
        if include(value):
            result[label] = value
    return result


def _ordered_case(index: int, comparison: Callable[[int, int], bool], boundary: int, *, count: bool) -> Task:
    """Use overlapping signed rows or identical positive items to expose order mistakes."""
    key, quantity = _FIELDS[index % len(_FIELDS)]
    totals = ([boundary - 2, boundary - 1, boundary, boundary + 1, boundary + 2],
              [boundary + 3, boundary - 1, boundary + 1, boundary, boundary - 3],
              [boundary + 1, boundary, boundary - 1, 12 + index, -25 - index], [])
    samples = []
    for example, values in enumerate(totals):
        offset = 21 + index + example
        groups = ((f'k{index}-{example}-{j}', [13 + index] * max(1, n) if count else [offset, n - offset])
                  for j, n in enumerate(values))
        rows = _rows(groups, key, quantity)
        outcome = _reference(rows, key, quantity, len if count else sum, lambda n: comparison(n, boundary))
        samples.append(Example(rows, outcome))
    return Task(f'ordered_{index:02d}', 'rows', tuple(samples[:2]), tuple(samples[2:]))


def _control(index: int, reducer: Callable[[list[int]], int], *, row_filter: bool) -> Task:
    """Take the original order when the examples actually call for it."""
    key, quantity = _FIELDS[index]
    groups = ([('A', [8, -10]), ('B', [7, -2]), ('C', [2, -2]), ('D', [-5])],
              [('X', [-1, 4, 4]), ('Y', [0, -2]), ('Z', [2, -2, 1])],
              [('T', [0, 0, 8, -15]), ('U', [-12]), ('V', [6, 8, -2])], [])
    samples = tuple(Example(rows, _reference(rows, key, quantity, reducer, lambda _: True, row_filter=row_filter))
                    for data in groups for rows in [_rows(data, key, quantity)])
    return Task(f'order_control_{index}', 'rows', samples[:2], samples[2:])


SOLO_SUM = Task('learn_plain_sum', 'values', (Example([5, -2], 3), Example([-10, 4, 4], -2)),
                (Example([0, -12, 31], 19), Example([], 0)))
_GROUP_LESSONS = {'learn_group_0', 'learn_group_1', 'learn_group_3', 'learn_group_4'}
LESSONS = tuple(t for t in TEACHING if t.function.startswith('learn_filter_') or t.function in _GROUP_LESSONS)
LESSONS += (SOLO_SUM,)

ORDERED_TASKS = tuple(_ordered_case(i, op, n, count=False) for i, (op, n) in enumerate(_SUM_CRITERIA))
ORDERED_TASKS += tuple(_ordered_case(i, op, n, count=True) for i, (op, n) in enumerate(_COUNT_CRITERIA, 6))
CONTROLS = (_control(0, sum, row_filter=False), _control(1, sum, row_filter=True),
            _control(2, len, row_filter=True))


def baseline_orders(task: Task) -> list[str]:
    """Check every old candidate against both example sets in the independent judge."""
    orders = set()
    for recipe in dict.fromkeys(semantic_key(candidate) for candidate in choices(task.examples)):
        source = render(task, recipe)
        if evaluate(source, task.function, task.parameter, task.examples + task.checks).passed:
            orders.add('before' if recipe.predicate else 'none')
    return sorted(orders)
