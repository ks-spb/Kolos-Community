"""Frozen synthetic requests and an independent judge for the ten known programs."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal
from io import StringIO
import json
from operator import eq, ge, gt, le, lt, ne, add, sub, mul, truediv
import random

from .spec import CONDITIONAL, KINDS, Spec, normalized

SEED = 20261125
STAGES = (0, 100, 1000, 10000)
_OPS = (('>', 'больше'), ('<', 'меньше'), ('>=', 'не меньше'), ('<=', 'не больше'),
        ('==', 'равно'), ('!=', 'не равно'))
_COMPARE = dict(zip((op for op, _ in _OPS), (gt, lt, ge, le, eq, ne), strict=True))

# Surface groups stay disjoint. They may share words and the actual program families.
_TRAIN = (
    ('создай консольный калькулятор', 'напиши калькулятор для четырех действий', 'собери обычный калькулятор', 'нужен калькулятор с дробями', 'подготовь калькулятор в терминале'),
    ('сверь два csv с остатками', 'сравни остатки между двумя csv', 'выведи расхождения в двух таблицах csv', 'сделай сверку двух csv по sku', 'сопоставь два файла остатков и покажи разницу'),
    ('сложи qty по артикулам', 'суммируй запасы по sku', 'собери итоги количеств на артикул', 'сгруппируй csv и получи сумму qty', 'суммируй остатки для каждого артикула'),
    ('оставь артикулы с суммой qty {condition}', 'сгруппируй остатки и оставь итоги {condition}', 'фильтруй итоги по sku после суммы, их значение {condition}', 'покажи группы остатков где итог {condition}', 'оставь только итоги по артикулам {condition}'),
    ('отфильтруй список чисел и оставь числа {condition}', 'из списка целых оставь числа {condition}', 'верни числа со значением {condition}', 'отбери целые числа {condition} из списка', 'в списке чисел убери все кроме тех где значение {condition}'),
    ('посчитай числа со значением {condition}', 'сколько чисел в списке {condition}', 'подсчитай количество целых чисел {condition}', 'верни количество чисел где значение {condition}', 'сосчитай элементы числового списка {condition}'),
    ('отфильтруй строки csv где qty {condition}', 'оставь строки csv с количеством {condition}', 'выбери записи из csv где qty {condition}', 'по строкам csv отфильтруй количество {condition}', 'верни записи csv с остатком {condition}'),
    ('отсортируй csv по {column} {direction}', 'упорядочи строки csv по {column} {direction}', 'сделай сортировку csv по {column} {direction}', 'расположи записи csv по {column} {direction}', 'отсортируй таблицу остатков по {column} {direction}'),
    ('посчитай строки по артикулам в csv', 'сколько строк приходится на каждый sku', 'подсчитай число записей по каждому артикулу', 'сгруппируй csv и посчитай строки', 'покажи количество строк на артикул'),
    ('убери одинаковые строки csv', 'удали точные дубликаты sku и qty', 'оставь уникальные пары sku и qty в csv', 'удали повторяющиеся строки таблицы остатков', 'сохрани по одной копии каждой строки csv'),
)
_CALIBRATE = (
    ('мне нужен калькулятор с десятичными числами', 'калькулятор для сложения и деления в консоли'),
    ('сделай сравнение пары csv остатков', 'покажи отличия старого и нового csv по артикулам'),
    ('сложи количества одинаковых sku', 'выгрузи по одному итогу qty на каждый артикул'),
    ('выведи суммы по sku где итог {condition}', 'из итогов остатков отбери группы со значением {condition}'),
    ('нужны числа из списка где значение {condition}', 'верни отфильтрованный список чисел {condition}'),
    ('подсчитай целые элементы списка со значением {condition}', 'дай число подходящих чисел {condition}'),
    ('из таблицы csv верни записи где остаток {condition}', 'пропусти только строки csv с qty {condition}'),
    ('расставь строки файла csv по {column} {direction}', 'нужен упорядоченный csv по {column} {direction}'),
    ('покажи частоту строк для каждого sku', 'выведи число повторов артикулов в csv'),
    ('удали одинаковые пары из таблицы csv', 'сохрани первое вхождение каждой пары qty и sku'),
)
_HOLDOUT = (
    ('сделай мне программу калькулятор', 'хочу вводить два числа и знак в калькулятор', 'посчитай базовые операции через консольный калькулятор', 'нужен калькулятор с десятичными дробями', 'сгенерируй арифметический калькулятор для терминала'),
    ('проведи сверку остатков по старому и новому csv', 'где разошлись количества в паре csv', 'сравни две выгрузки склада и покажи только отличия', 'найди разницу остатков между файлами csv', 'посчитай изменения для sku по двум таблицам csv'),
    ('подбей суммы qty отдельно на каждый sku', 'получи суммарное количество для каждого артикула', 'сложи повторы артикулов и выдай полный список остатков', 'объедини количества одинаковых артикулов в итог', 'выведи общие остатки по каждому sku'),
    ('покажи артикулы где суммарный остаток {condition}', 'сначала сложи qty по sku потом оставь значения {condition}', 'итог после группировки должен быть {condition}', 'верни группы по артикулу с суммой {condition}', 'после суммирования отбери остатки {condition}'),
    ('оставь из числового списка только значения {condition}', 'нужно отобрать числа {condition} и вернуть список', 'сохрани ровно числа {condition}', 'из массива целых выведи каждое число {condition}', 'забери из ряда чисел только элементы {condition}'),
    ('скажи сколько значений в числовом списке {condition}', 'сколько элементов списка удовлетворяют тому что значение {condition}', 'возьми числовой список и выведи число элементов {condition}', 'определи количество значений {condition} среди целых чисел', 'нужен счетчик чисел у которых значение {condition}'),
    ('из выгрузки csv оставь записи когда количество {condition}', 'отбери из csv строки у которых qty {condition}', 'отсей записи csv и верни только с qty {condition}', 'верни строки таблицы csv при условии что qty {condition}', 'отфильтруй каждую строку склада по условию qty {condition}'),
    ('выстрой таблицу csv по {column} {direction}', 'отсортируй записи в выгрузке по {column} {direction}', 'сделай порядок строк в csv по {column} {direction}', 'расставь записи CSV по полю {column} {direction}', 'выведи csv отсортированный по {column} {direction}'),
    ('посчитай сколько записей приходится на артикул в csv', 'дай частоты появления sku по строкам', 'сколько раз каждый артикул встречается в таблице', 'выведи число строк отдельно для каждого sku', 'для каждого артикула верни число записей из csv'),
    ('оставь первое вхождение каждой одинаковой строки csv', 'в csv убери повтор каждой пары артикул и количество', 'удали копии записей с одинаковыми sku и qty', 'убери дубликаты строк из складской таблицы', 'выведи csv с уникальными строками по паре sku и qty'),
)
_PREFIX = ('', 'пожалуйста ', 'можешь ', 'для локальной работы ', 'для проверки примера ', 'по этому заданию ',
           'для небольшой утилиты ', 'в этой задаче ', 'для работы с данными ', 'хочу попросить ', 'помоги ')
_SUFFIX = ('', ' пожалуйста', ' для терминала', ' на python', ' для запуска локально', ' отдельной программой',
           ' сохрани в python', ' для проекта', ' для примера', ' для автоматизации', ' как скрипт', ' для проверки',
           ' в виде утилиты', ' одним файлом', ' с выводом результата', ' для практики', ' в обычном python',
           ' для локального запуска', ' и покажи результат', ' чтобы можно было запустить')
_CONTROL_MISSING = ('отфильтруй список чисел', 'посчитай числа по условию', 'оставь нужные итоги по артикулам',
                    'из csv оставь подходящие строки', 'отсортируй csv')
_CONTROL_UNKNOWN = ('вычисли логарифм числа', 'посчитай медиану списка чисел', 'сделай графический калькулятор с окном',
                    'соедини два csv в один', 'восстанови удаленные строки csv', 'раздели csv по складам',
                    'посчитай уникальные числа из списка', 'выгрузи контакты из csv', 'построй график остатков csv',
                    'отправь отчет сверки csv на почту')


@dataclass(frozen=True)
class Probe:
    """One independent file or argument input for an actual Python process."""

    args: tuple[str, ...]
    files: tuple[tuple[str, str], ...]
    output: str


@dataclass(frozen=True)
class Request:
    """The request and its private expected interpretation and behavior."""

    id: str
    text: str
    expected: Spec | None
    probes: tuple[Probe, ...] = ()
    category: str = 'supported'


def _csv(header: tuple[str, str], rows: list[tuple]) -> str:
    """Produce fixtures and reference results without using the generated program."""
    stream = StringIO()
    writer = csv.writer(stream, lineterminator='\n')
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue()


def _rows(spec: Spec, dataset: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """Reference behavior for the seven single-file CSV recipes."""
    if spec.kind == 'csv_filter':
        return [(key, qty) for key, qty in dataset if _COMPARE[spec.op](qty, spec.threshold)]
    if spec.kind == 'csv_sort':
        return sorted(dataset, key=lambda row: row[0 if spec.column == 'sku' else 1], reverse=spec.descending)
    if spec.kind == 'csv_unique':
        return [row for i, row in enumerate(dataset) if row not in dataset[:i]]
    groups = sorted({key for key, _ in dataset})
    result = []
    for key in groups:
        qty = [quantity for sku, quantity in dataset if sku == key]
        value = len(qty) if spec.kind == 'csv_count' else sum(qty)
        if spec.kind != 'group_filter' or _COMPARE[spec.op](value, spec.threshold):
            result.append((key, value))
    return result


def _calc(index: int, variation: int) -> Probe:
    """Check arithmetic with exact fractional and signed inputs."""
    ops = {'+': add, '-': sub, '*': mul, '/': truediv}
    op = tuple(ops)[(index + variation) % len(ops)]
    left = Decimal(index % 17 - 8) + Decimal('0.5')
    right = Decimal((index % 5 + 1) if op != '/' else 2 ** (variation + 1))
    raw = format(ops[op](left, right), 'f')
    result = (raw.rstrip('0').rstrip('.') if '.' in raw else raw) if Decimal(raw) != 0 else '0'
    return Probe((str(left), op, str(right)), (), result + '\n')


def probe(spec: Spec, index: int, variation: int) -> Probe:
    """Use unrelated data and explicit boundary values on every scored request."""
    if spec.kind == 'calculator':
        return _calc(index, variation)
    n = spec.threshold if spec.threshold is not None else (index % 17 - 5)
    if spec.kind in ('number_filter', 'number_count'):
        data = [n + 2, n, n - 1 - variation, n, n + 4 + variation, n - 2, 0]
        result = [value for value in data if _COMPARE[spec.op](value, n)]
        expected = result if spec.kind == 'number_filter' else len(result)
        return Probe(('numbers.json',), (('numbers.json', json.dumps(data)),), json.dumps(expected) + '\n')
    a, b, c = (f'{key}{index % 101}' for key in ('A', 'B', 'C'))
    data = [(c, n), (b, n + 2), (a, n - 2), (b, n + 2), (b, -variation), (a, variation + 2)]
    if variation:
        data.reverse()
    csv_text = _csv(('sku', 'qty'), data)
    if spec.kind == 'reconcile':
        changed = [(b, 2), (b, -1), ('new', variation + 4), (a, n + variation)]
        before, after = dict(_rows(Spec('totals'), data)), dict(_rows(Spec('totals'), changed))
        difference = [(k, before.get(k, 0), after.get(k, 0), after.get(k, 0) - before.get(k, 0))
                      for k in sorted(before.keys() | after.keys()) if before.get(k, 0) != after.get(k, 0)]
        return Probe(('before.csv', 'after.csv'), (('before.csv', csv_text), ('after.csv', _csv(('sku', 'qty'), changed))),
                     _csv(('sku', 'before', 'after', 'delta'), difference))
    header = ('sku', 'count' if spec.kind == 'csv_count' else 'qty')
    return Probe(('rows.csv',), (('rows.csv', csv_text),), _csv(header, _rows(spec, data)))


def _parameters(kind: str, i: int, salt: int) -> tuple[Spec, dict]:
    """Create the structured lesson label separately from its natural-language text."""
    if kind in CONDITIONAL:
        op, word = _OPS[(i + salt) % len(_OPS)]
        value = ((i * 3 + salt) % 29) - 14
        return Spec(kind, op, value), {'condition': f'{word} {value}'}
    if kind == 'csv_sort':
        column, descending = ('qty' if i % 2 else 'sku'), bool((i // 2) % 2)
        return Spec(kind, column=column, descending=descending), dict(column=column,
                        direction='по убыванию' if descending else 'по возрастанию')
    return Spec(kind), {}


def _dataset(templates: tuple, count: int, partition: str, salter: int, probes_per_request: int) -> tuple[Request, ...]:
    """Interleave labels so every prefix at a checkpoint has exactly balanced lessons."""
    batches = []
    for n, (kind, stems) in enumerate(zip(KINDS, templates, strict=True)):
        rng = random.Random(SEED + salter + n)
        combinations = [(x, y, z) for x in stems for y in _PREFIX for z in _SUFFIX]
        rng.shuffle(combinations)
        rows, seen = [], set()
        for i, (stem, first, last) in enumerate(combinations):
            spec, fill = _parameters(kind, i, salter)
            text = first + stem.format(**fill) + last
            if normalized(text) in seen:
                continue
            seen.add(normalized(text))
            test = tuple(probe(spec, i + salter + n * 79, j) for j in range(probes_per_request))
            rows.append(Request(f'{partition}-{n}-{len(rows)}', text, spec, test))
            if len(rows) == count:
                break
        if len(rows) != count:
            raise ValueError(f'Недостаточно уникальных запросов для {kind}.')
        batches.append(rows)
    return tuple(entry for level in zip(*batches, strict=True) for entry in level)


def _controls(partition: str, each: int) -> tuple[Request, ...]:
    """Use different carriers for incomplete and out-of-catalog requests on each split."""
    rows = []
    for category, stems in (('ambiguous', _CONTROL_MISSING), ('unknown', _CONTROL_UNKNOWN)):
        for i in range(each):
            suffix = _SUFFIX[(i // len(stems)) + (8 if partition == 'closed' else 0)]
            phrase = _PREFIX[i % len(_PREFIX)] + stems[i % len(stems)] + suffix
            rows.append(Request(f'{partition}-{category}-{i}', phrase, None, category=category))
    return tuple(rows)


def corpora() -> tuple[tuple[Request, ...], tuple[Request, ...], tuple[Request, ...]]:
    """Freeze all examples before training and reject overlapping request strings."""
    train = _dataset(_TRAIN, 1000, 'train', 0, 1)
    calibration = _dataset(_CALIBRATE, 10, 'calibrate', 100_000, 0) + _controls('calibrate', 20)
    closed = _dataset(_HOLDOUT, 30, 'closed', 200_000, 2) + _controls('closed', 40)
    keys = [normalized(row.text) for batch in (train, calibration, closed) for row in batch]
    if len(set(keys)) != len(keys):
        raise ValueError('Формулировки в корпусе пересекаются.')
    return train, calibration, closed
