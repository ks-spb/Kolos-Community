"""Parse the explicit parameters of a selected catalog entry."""
from __future__ import annotations

from dataclasses import dataclass
import re

KINDS = ('calculator', 'reconcile', 'totals', 'group_filter', 'number_filter', 'number_count',
         'csv_filter', 'csv_sort', 'csv_count', 'csv_unique')
NAMES = dict(zip(KINDS, ('калькулятор', 'сверка двух CSV', 'сумма по артикулам', 'фильтр итогов по артикулам',
                        'фильтр чисел', 'подсчёт чисел', 'фильтр строк CSV', 'сортировка CSV',
                        'число строк по артикулам', 'удаление одинаковых строк CSV'), strict=True))
CONDITIONAL = frozenset(('group_filter', 'number_filter', 'number_count', 'csv_filter'))
_WORDS = {'не меньше': '>=', 'не больше': '<=', 'как минимум': '>=', 'как максимум': '<=',
          'не равных': '!=', 'не равно': '!=', 'равное': '==', 'равных': '==', 'равно': '==',
          'более': '>', 'выше': '>', 'больше': '>', 'меньше': '<', 'ниже': '<',
          '>=': '>=', '<=': '<=', '!=': '!=', '==': '==', '>': '>', '<': '<'}
_CONDITION = re.compile(r'(?<!\w)(' + '|'.join(map(re.escape, _WORDS)) + r')\s*([+\-−]?\d+)(?!\d|[.,]\d)')
_EXCLUDED = re.compile(r'\b(медиан\w*|средне\w*|логарифм\w*|картин\w*|курс\w*|'
                       r'отправ\w*|окном|графическ\w*|процент\w*|дельт\w*\s+по\s+месяц\w*)\b')


@dataclass(frozen=True)
class Spec:
    """The known program and the parameters embedded in the generated Python."""

    kind: str
    op: str | None = None
    threshold: int | None = None
    column: str | None = None
    descending: bool = False


class Clarify(ValueError):
    """The requested program or a required parameter is ambiguous."""


def normalized(text: str) -> str:
    """Normalize case, ё and spacing while keeping operator and number syntax."""
    return ' '.join(text.casefold().replace('ё', 'е').split())


def unsupported(text: str) -> bool:
    """Reject explicit operations outside the catalog in every comparison branch."""
    return bool(_EXCLUDED.search(text))


def parse(kind: str, request: str) -> Spec:
    """Extract common parameters after routing has selected one program."""
    text = normalized(request)
    if kind not in KINDS:
        raise ValueError(f'Неизвестный тип программы {kind}.')
    if kind in CONDITIONAL:
        matches = {(_WORDS[op], int(value.replace('−', '-'))) for op, value in _CONDITION.findall(text)}
        if len(matches) != 1:
            raise Clarify('Укажите одно сравнение и целый порог, например «больше 7».')
        op, value = matches.pop()
        return Spec(kind, op, value)
    if kind == 'csv_sort':
        sku = bool(re.search(r'\b(?:по\s+(?:полю\s+)?(?:sku|артикулу)|ключ\s+sku)\b', text))
        qty = bool(re.search(r'\b(?:по\s+(?:полю\s+)?(?:qty|количеству|остатку)|ключ\s+qty)\b', text))
        if sku == qty:
            raise Clarify('По какому столбцу сортировать, sku или qty?')
        return Spec(kind, column='sku' if sku else 'qty', descending='по убыванию' in text or 'обратном порядке' in text)
    return Spec(kind)
