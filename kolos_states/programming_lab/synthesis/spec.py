"""Read the public synthesis task and keep independent checks out of search."""
from __future__ import annotations

from dataclasses import dataclass
import json
import keyword
from pathlib import Path
from typing import TypeAlias

Item: TypeAlias = int | dict[str, int | str]
Result: TypeAlias = int | list[Item] | dict[str, int]


@dataclass(frozen=True)
class Example:
    """One positional list argument and its expected return value."""

    input: list[Item]
    expected: Result


@dataclass(frozen=True)
class Task:
    """A task with open examples for search and separate checks for acceptance."""

    function: str
    parameter: str
    examples: tuple[Example, ...]
    checks: tuple[Example, ...]


def _examples(raw: object, section: str) -> tuple[Example, ...]:
    """Decode examples without requiring a Python harness from the user."""
    if not isinstance(raw, list) or not raw:
        raise ValueError(f'Поле {section} должно содержать хотя бы один пример.')
    examples = []
    for row in raw:
        if not isinstance(row, dict) or set(row) != {'input', 'expected'} or not isinstance(row['input'], list):
            raise ValueError(f'Каждый элемент {section} должен содержать список input и значение expected.')
        examples.append(Example(**row))
    return tuple(examples)


def item_shape(value: object) -> tuple[tuple[str, type], ...]:
    """Return a stable schema for a number or a flat record."""
    if type(value) is int:
        return ()
    if (type(value) is dict and value and
            all(type(k) is str and type(v) in (str, int) for k, v in value.items())):
        return tuple(sorted((k, type(v)) for k, v in value.items()))
    raise ValueError('Элементы input должны быть целыми числами или записями с текстовыми и целочисленными полями.')


def result_kind(value: object) -> str:
    """Recognize aggregation and filtering results without accepting bool as int."""
    if type(value) is int:
        return 'number'
    if type(value) is list:
        return 'list'
    if type(value) is dict and all(type(k) is str and type(v) is int for k, v in value.items()):
        return 'mapping'
    raise ValueError('Поле expected должно быть целым числом, списком или словарём строковых ключей и целых чисел.')


def parse_task(raw: object) -> Task:
    """Check the complete file while leaving training and independent examples distinct."""
    if not isinstance(raw, dict) or set(raw) != {'function', 'parameter', 'examples', 'checks'}:
        raise ValueError('Файл должен содержать function, parameter, examples и checks.')
    names = (raw['function'], raw['parameter'])
    if any(not isinstance(n, str) or not n.isascii() or not n.isidentifier() or keyword.iskeyword(n)
           for n in names):
        raise ValueError('Имена function и parameter должны быть допустимыми английскими идентификаторами Python.')
    task = Task(*names, _examples(raw['examples'], 'examples'), _examples(raw['checks'], 'checks'))
    rows = (item for e in task.examples for item in e.input)
    first = next(rows, None)
    if first is None:
        raise ValueError('Добавьте непустой input в examples, чтобы определить тип входа.')
    shape = item_shape(first)
    kind = result_kind(task.examples[0].expected)
    for e in (*task.examples, *task.checks):
        if any(item_shape(item) != shape for item in e.input):
            raise ValueError('Записи должны иметь одинаковый набор полей и типы значений во всех примерах.')
        if result_kind(e.expected) != kind:
            raise ValueError('Тип expected должен быть одинаковым во всех примерах.')
        if kind == 'list' and any(item_shape(item) != shape for item in e.expected):
            raise ValueError('При фильтрации элементы expected должны иметь тот же тип, что и input.')
    return task


def load_task(path: Path) -> Task:
    """Load a UTF-8 JSON task, including files with a Windows UTF-8 BOM."""
    return parse_task(json.loads(path.read_text(encoding='utf-8-sig')))
