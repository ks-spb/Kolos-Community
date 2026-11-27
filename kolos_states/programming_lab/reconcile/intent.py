"""Recall the terms of a supported CSV reconciliation request from graph memory."""
from __future__ import annotations

from dataclasses import dataclass

from ...core import StateEngine
from ..calculator.intent import COMMAND_WORDS, WORD, Clarification
from ..repair.policy import _activation, _remember

TERMS = {
    'compare': ('сверь', 'сверку', 'сравни', 'сравнить', 'сравнивает'),
    'csv': ('csv',),
    'two_inputs': ('2', 'два', 'двух'),
    'sum_duplicates': ('сложи', 'суммируй'),
    'changed_only': ('расхождения', 'отличия', 'разницу'),
}
FILLER = COMMAND_WORDS | frozenset('которая остатки остатков остатками складских складскими каждом '
                                    'есть артикул sku количество qty дубли дубликаты внутри '
                                    'каждого файлах файле файла файлов файл выведи покажи только'.split())
REQUEST = ('Сделай программу, которая сравнивает два CSV с остатками. В каждом есть артикул sku и '
           'количество qty. Сложи дубликаты внутри каждого файла и выведи только расхождения.')


@dataclass(frozen=True)
class Intent:
    """The file and result contract chosen for this bounded task."""

    inputs: int = 2
    sku: str = 'sku'
    qty: str = 'qty'
    duplicates: str = 'sum'
    output: str = 'changed_only'
    defaults: tuple[str, ...] = ()


def teach_words(engine: StateEngine) -> int:
    """Associate independent Russian terms with the corresponding task concepts."""
    for meaning, terms in TERMS.items():
        for word in terms:
            _remember(engine, f'reconcile/word/{word}/{meaning}', 1, 0)
    return sum(map(len, TERMS.values()))


def recognize(request: str, engine: StateEngine) -> Intent:
    """Require the learned task terms while blocking unrecognized requirements."""
    meanings, unknown = set(), set()
    for word in set(WORD.findall(request.casefold())) - FILLER:
        matched = {kind for kind in TERMS if _activation(engine, f'reconcile/word/{word}/{kind}') > 0}
        if not matched:
            unknown.add(word)
        meanings.update(matched)
    if not {'compare', 'csv'} <= meanings:
        raise Clarification('Укажите, нужна ли сверка двух CSV. Если навык ещё не обучен, запустите reconcile-benchmark.')
    if unknown:
        raise Clarification('Уточните требования к сверке. Не распознано: ' + ', '.join(sorted(unknown)))
    defaults = tuple(field for field in ('two_inputs', 'sum_duplicates', 'changed_only') if field not in meanings)
    return Intent(defaults=defaults)
