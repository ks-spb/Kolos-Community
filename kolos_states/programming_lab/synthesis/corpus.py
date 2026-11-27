"""Independent reference tasks for learning and reproducible evaluation."""
from __future__ import annotations

from collections.abc import Callable
from operator import eq, ge, gt, le, lt, ne

from .spec import Example, Item, Result, Task


def _case(name: str, datasets: list[list[Item]], expected: Callable[[list[Item]], Result]) -> Task:
    """Reserve the last two inputs for the independent judge."""
    cases = tuple(Example(data, expected(data)) for data in datasets)
    return Task(name, 'items', cases[:-2], cases[-2:])


def _numeric(seed: int) -> list[list[Item]]:
    """Vary visible order and duplicates while holding out numbers at longer distances."""
    return [list(range(-4, 5))[seed:] + list(range(-4, 5))[:seed],
            [seed, -seed, 0, 0, 1, -1, seed],
            [20 + seed, -20 - seed, 0, 1, -1, seed], []]


def _rows(seed: int, key: str, value: str, distractor: str) -> list[list[Item]]:
    """Use unrelated text fields and different column names across the split."""
    return [
        [{key: k, value: v, distractor: f'line{i}'} for i, (k, v) in enumerate(data)]
        for data in ([('A', 2 + seed), ('B', -1), ('A', 3), ('B', 0)],
                     [('B', 7), ('C', 0), ('B', -2), ('C', 6 + seed)],
                     [('new', -9), ('A', 2), ('new', -3)], [])
    ]


def _group(data: list[Item], key: str, value: str, mode: str) -> dict[str, int]:
    """Reference behavior for grouping, independent from the candidate renderer."""
    keys = sorted({row[key] for row in data})
    result = {}
    for group in keys:
        values = [row[value] for row in data if row[key] == group]
        if mode == 'positive':
            values = [v for v in values if v > 0]
        if values:
            result[group] = len(values) if mode == 'count' else sum(values)
    return result


def _filter_case(prefix: str, i: int, predicates: tuple) -> Task:
    """Make one ordered filter with an independent predicate."""
    predicate, boundary = predicates[i]
    return _case(f'{prefix}_filter_{i}', _numeric(i + 1), lambda xs: [x for x in xs if predicate(x, boundary)])


def _count_case(prefix: str, i: int, predicates: tuple) -> Task:
    """Make one filtered count with a separate dataset."""
    predicate, boundary = predicates[i]
    return _case(f'{prefix}_count_{i}', _numeric(i + 2), lambda xs: sum(predicate(x, boundary) for x in xs))


def _group_case(prefix: str, i: int, mode: str) -> Task:
    """Check aggregation with repeated keys and a distractor column."""
    fields = ('region', 'amount', 'note') if prefix == 'learn' else ('sku', 'qty', 'warehouse')
    key, value, distractor = fields
    return _case(f'{prefix}_group_{i}', _rows(i, *fields), lambda xs: _group(xs, key, value, mode))


_TRAIN_FILTER = ((gt, 0), (lt, 0), (eq, 0), (ne, 0), (ge, 0), (le, 0))
_TRAIN_COUNT = ((gt, 0), (lt, 0), (ge, 0), (eq, 0), (ne, 0), (le, 0))
_FILTER = ((gt, 1), (lt, -1), (ge, 0), (le, 0), (eq, 1), (ne, -1))
_COUNT = ((gt, 0), (lt, 0), (ge, 2), (eq, -1), (ne, 0), (le, -1))
_GROUP_MODES = ('sum', 'count', 'positive', 'sum', 'count', 'positive')

TEACHING = tuple([*(_filter_case('learn', i, _TRAIN_FILTER) for i in range(6)),
                  *(_count_case('learn', i, _TRAIN_COUNT) for i in range(6)),
                  *(_group_case('learn', i, mode) for i, mode in enumerate(_GROUP_MODES))])
HELD_OUT = tuple([*(_filter_case('trial', i, _FILTER) for i in range(6)),
                  *(_count_case('trial', i, _COUNT) for i in range(6)),
                  *(_group_case('trial', i + 6, mode) for i, mode in enumerate(_GROUP_MODES))])
