"""Build a standalone program from independently exercised Python components."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from decimal import Decimal
from io import StringIO
from itertools import product
from textwrap import dedent

from ...core import StateEngine
from ..repair.policy import _activation, _remember

IMPORTS = '''import re
import sys
from decimal import Decimal, DecimalException
from operator import add, floordiv, mul, sub, truediv
'''
ENTRY = dedent('''\
    def main(args):
        if args == ['--help']:
            print('Использование: python calculator.py ЧИСЛО ОПЕРАЦИЯ ЧИСЛО')
            print('Операции: + - * /. Десятичный разделитель: точка или запятая.')
            return 0
        try:
            left, operation, right = read_args(args)
            result = calculate(number(left), operation, number(right))
            print(display(result))
        except (ValueError, DecimalException, OverflowError) as error:
            emit_error(str(error))
            return 2
        return 0


    if __name__ == '__main__':
        raise SystemExit(main(sys.argv[1:]))
    ''')


@dataclass(frozen=True)
class Component:
    """A callable fragment that can be assessed without an application entry point."""

    name: str
    source: str


@dataclass(frozen=True)
class Role:
    """A program role and implementations meeting the same calling convention."""

    function: str
    options: tuple[Component, ...]


def _read_number(constructor: str) -> str:
    """Share decimal token syntax while varying the numeric representation."""
    return dedent('''\
        def number(text):
            if re.fullmatch(r'[+-]?(?:[0-9]+(?:[.,][0-9]*)?|[.,][0-9]+)', text) is None:
                raise ValueError(f'неверное число {text!r}')
            return CONSTRUCTOR(text.replace(',', '.'))
        ''').replace('CONSTRUCTOR', constructor)


def _calculate(divide: str) -> str:
    """Use explicit arithmetic operators with either division convention."""
    return dedent('''\
        def calculate(left, operation, right):
            operations = {'+': add, '-': sub, '*': mul, '/': DIVIDE}
            aliases = {'×': '*', '÷': '/', '−': '-'}
            operation = aliases.get(operation, operation)
            if operation not in operations:
                raise ValueError(f'неизвестная операция {operation!r}')
            if operation == '/' and right == 0:
                raise ValueError('деление на ноль')
            return operations[operation](left, right)
        ''').replace('DIVIDE', divide)


ROLES = (
    Role('read_args', (Component('three_arguments', dedent('''\
        def read_args(args):
            if len(args) != 3:
                raise ValueError('ожидались число, операция и число. Используйте --help')
            return tuple(args)
        ''')),)),
    Role('number', (Component('decimal', _read_number('Decimal')), Component('float', _read_number('float')))),
    Role('calculate', (Component('floor', _calculate('floordiv')), Component('quotient', _calculate('truediv')))),
    Role('display', (Component('raw', 'def display(value):\n    return str(value)\n'),
                     Component('plain_decimal', dedent('''\
        def display(value):
            if value == 0:
                return '0'
            text = format(value, 'f')
            return text.rstrip('0').rstrip('.') if '.' in text else text
        ''')))),
    Role('emit_error', (Component('stderr', "def emit_error(message):\n    print('Ошибка:', message, file=sys.stderr)\n"),
                        Component('stdout', "def emit_error(message):\n    print('Ошибка:', message)\n"))),
)


def _probe(role: Role, component: Component) -> bool:
    """Exercise only a single fragment under a role-specific example."""
    namespace: dict = {}
    exec(compile(IMPORTS + '\n' + component.source, '<calculator teaching fragment>', 'exec'), namespace)
    run = namespace[role.function]
    if role.function == 'read_args':
        return run(['9', '-', '4']) == ('9', '-', '4')
    if role.function == 'number':
        return run('0,1') + run('0.2') == Decimal('0.3')
    if role.function == 'calculate':
        return run(Decimal(5), '/', Decimal(2)) == Decimal('2.5')
    if role.function == 'display':
        return run(Decimal('12.500')) == '12.5'
    output, errors = StringIO(), StringIO()
    with redirect_stdout(output), redirect_stderr(errors):
        run('проверка')
    return not output.getvalue() and errors.getvalue() == 'Ошибка: проверка\n'


def teach_components(engine: StateEngine) -> list[dict]:
    """Learn which implementations satisfy independent input, arithmetic and output examples."""
    report = []
    for role in ROLES:
        for component in role.options:
            passed = _probe(role, component)
            _remember(engine, f'calculator/role/{role.function}/{component.name}', int(passed), int(not passed))
            report.append(dict(role=role.function, component=component.name, passed=passed))
    return report


def plans(engine: StateEngine) -> list[tuple[Component, ...]]:
    """Rank all compatible compositions by the sum of their learned role scores."""
    scores = {component.name: _activation(engine, f'calculator/role/{role.function}/{component.name}')
              for role in ROLES for component in role.options}
    options = product(*(role.options for role in ROLES))
    return sorted(options, key=lambda recipe: -sum(scores[component.name] for component in recipe))


def assemble(recipe: tuple[Component, ...]) -> str:
    """Wire the selected fragments to an application entry point."""
    used_imports = IMPORTS
    if not any(component.name == 'floor' for component in recipe):
        used_imports = used_imports.replace('floordiv, ', '')
    if not any(component.name == 'quotient' for component in recipe):
        used_imports = used_imports.replace(', truediv', '')
    return '\n\n'.join([used_imports.rstrip(), *(c.source.rstrip() for c in recipe), ENTRY.rstrip()]) + '\n'
