"""Recognize a bounded calculator request by recalling individual learned words."""
from __future__ import annotations

from dataclasses import dataclass
import re

from ...core import StateEngine
from ..repair.policy import _activation, _remember

VOCABULARY = {
    'calculator': ('калькулятор', 'калькулятора', 'calculator'),
    'console': ('консоль', 'консоли', 'консольный', 'терминал', 'терминале', 'console', 'cli'),
    'window': ('окно', 'окном', 'графический', 'графическим', 'window', 'gui'),
    'decimal': ('десятичные', 'десятичными', 'дробные', 'дробными', 'decimal'),
    'arithmetic': ('4', 'четыре', 'четырьмя', 'действия', 'действиями', 'операции', 'операциями'),
}
COMMAND_WORDS = frozenset('сделай создай напиши мне программу программа программку пожалуйста '
                          'нужен нужна с со в на и числа числами create make a me program with in'.split())
WORD = re.compile(r'[^\W_]+')


@dataclass(frozen=True)
class Intent:
    """The executable contract and which parts came from defaults."""

    interface: str = 'console'
    numbers: str = 'decimal'
    operations: tuple[str, ...] = ('+', '-', '*', '/')
    defaults: tuple[str, ...] = ()


class Clarification(ValueError):
    """The words point to a format or feature the local generator cannot choose."""


def teach_words(engine: StateEngine) -> int:
    """Associate independent concepts with example words in native graph memory."""
    for meaning, words in VOCABULARY.items():
        for word in words:
            _remember(engine, f'calculator/word/{word}/{meaning}', 1, 0)
    return sum(map(len, VOCABULARY.values()))


def recognize(request: str, engine: StateEngine) -> Intent:
    """Combine observed concepts without looking up any full request."""
    words = set(WORD.findall(request.casefold()))
    signals, unknown = set(), set()
    for word in words - COMMAND_WORDS:
        meaning = {kind for kind in VOCABULARY
                   if _activation(engine, f'calculator/word/{word}/{kind}') > 0}
        if not meaning:
            unknown.add(word)
        signals.update(meaning)
    if 'calculator' not in signals:
        raise Clarification('Укажите, нужна ли программа-калькулятор.')
    if 'window' in signals:
        raise Clarification('Доступен консольный калькулятор. Подойдёт запуск через командную строку?')
    if unknown:
        raise Clarification('Уточните требования к калькулятору. Не распознано: ' + ', '.join(sorted(unknown)))
    defaults = tuple(field for field in ('console', 'decimal', 'arithmetic') if field not in signals)
    return Intent(defaults=defaults)
