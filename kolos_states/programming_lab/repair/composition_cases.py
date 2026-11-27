"""Held-out compositions and controls for the existing Python edit grammar."""
from __future__ import annotations

from .cases import CONTROLS, _task

PAIRS = (
    _task('name-display', '''
        def normalize(name):
            return name.strip()
        def display(name):
            cleaned = normalize(name)
            return cleaned or 'Без имени'
        ''', 'display', ((None, 'Без имени'), ('   ', ''), (' Анна ', 'Анна')),
        (('  Олег ', 'Олег'), ('', ''), ('normalize', None, None))),
    _task('filtered-label', '''
        def capitalize(label):
            marker = str(label)
            token = marker or 'info'
            return label.strip().upper()
        def present(label):
            value = capitalize(label)
            if not value:
                return '[unknown]'
            return value
        ''', 'present', ((None, '[unknown]'), ('  ', ''), (' ab ', 'AB')),
        (('z', 'Z'), ('capitalize', None, None), ('', ''))),
    _task('defaults', '''
        def port(number):
            return number or 80
        def title(text):
            return text or 'untitled'
        def read(pair):
            return port(pair[0]), title(pair[1])
        ''', 'read', (([0, 'ABC'], (0, 'ABC')), ([1, ''], (1, '')), ([None, None], (80, 'untitled'))),
        (([0, ''], (0, '')), ('port', 0, 0), ('title', '', ''))),
    _task('joint-result', '''
        def payable(quantity):
            if not quantity:
                return 42
            return quantity
        def available(quantity):
            return quantity or 99
        def summarize(quantity):
            return payable(quantity), available(quantity)
        ''', 'summarize', ((0, (0, 0)), (None, (42, 99)), (3, (3, 3))),
        (('payable', 0, 0), ('available', 0, 0), ('available', False, False))),
    _task('two-guards', '''
        def trim(value):
            return value.strip()
        def items(value):
            return len(value)
        def field(entry):
            if entry[0] == 'name':
                return trim(entry[1])
            return items(entry[1])
        ''', 'field', ((['name', None], None), (['items', None], None), (['name', ' X '], 'X')),
        ((['items', []], 0), ('trim', None, None), ('items', None, None))),
    _task('decoded-value', '''
        def integer(raw):
            return int(raw)
        def choose(raw):
            value = integer(raw)
            if not value:
                return 4
            return value
        ''', 'choose', ((None, 4), ('0', 0), ('12', 12)),
        (('-1', -1), ('integer', None, None), ('integer', '0', 0))),
)

SINGLE = _task('single-edit', '''
    def temperature(value):
        return value or 21
    ''', 'temperature', ((0, 0), (None, 21)), ((5, 5), (False, False)))

CHECKS = (SINGLE, *CONTROLS)
