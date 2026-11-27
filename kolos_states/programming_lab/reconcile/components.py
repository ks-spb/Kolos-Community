"""Reuse aggregation and error handling while composing a standalone CSV utility."""
from __future__ import annotations

from dataclasses import dataclass, fields
from itertools import product
from textwrap import dedent

from ...core import StateEngine
from ..calculator.components import ROLES as CALCULATOR_ROLES
from ..repair.policy import _activation, _remember
from ..synthesis.grammar import Recipe, render
from ..synthesis.spec import Task

IMPORTS = '''import argparse
import csv
import os
import re
import sys
from pathlib import Path
from uuid import uuid4
'''
READER = dedent('''\
    def read_rows(path):
        with path.open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream, strict=True)
            header = reader.fieldnames
            if header is None:
                return []
            if not {'sku', 'qty'} <= set(header) or len(header) != len(set(header)):
                raise ValueError(f'{path.name}: нужны уникальные столбцы sku и qty')
            rows = []
            for record in reader:
                sku = (record['sku'] or '').strip()
                qty = (record['qty'] or '').strip()
                if None in record or not sku or re.fullmatch(r'[+-]?[0-9]+', qty) is None:
                    raise ValueError(f'{path.name}, строка {reader.line_num}: ожидались артикул и целое qty')
                rows.append({'sku': sku, 'qty': int(qty)})
            return rows
    ''')
OUTPUT = dedent('''\
    def write_rows(stream, rows):
        writer = csv.writer(stream, lineterminator='\\n')
        writer.writerow(('sku', 'before', 'after', 'delta'))
        writer.writerows(rows)


    def emit(target, rows):
        if target is None:
            write_rows(sys.stdout, rows)
            return
        temporary = target.parent / f'.{target.name}.{uuid4().hex}'
        try:
            with temporary.open('x', encoding='utf-8', newline='') as stream:
                write_rows(stream, rows)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    ''')
ENTRY = dedent('''\
    def differences(before, after):
        rows = []
        for sku in keys(before, after):
            old, new = before.get(sku, 0), after.get(sku, 0)
            if include(old, new):
                rows.append((sku, old, new, new - old))
        return rows


    def main(args):
        parser = argparse.ArgumentParser(description='Сверка двух CSV с остатками')
        parser.add_argument('before', type=Path)
        parser.add_argument('after', type=Path)
        parser.add_argument('--output', type=Path)
        options = parser.parse_args(args)
        try:
            if options.output is not None and options.output.resolve() in (
                options.before.resolve(), options.after.resolve()
            ):
                raise ValueError('файл результата должен отличаться от входных файлов')
            before = totals(read_rows(options.before))
            after = totals(read_rows(options.after))
            emit(options.output, differences(before, after))
        except (OSError, ValueError, csv.Error) as error:
            emit_error(str(error))
            return 2
        return 0


    if __name__ == '__main__':
        raise SystemExit(main(sys.argv[1:]))
    ''')

GROUPS = {kind: render(Task('totals', 'rows', (), ()), Recipe(kind, 'qty' if kind == 'sum' else None, 'sku'))
          for kind in ('sum', 'count')}
GROUPS['last'] = 'def totals(rows):\n    return {row["sku"]: row["qty"] for row in rows}\n'
KEYS = {kind: f'def keys(before, after):\n    return sorted(before.keys() {op} after.keys())\n'
        for kind, op in (('union', '|'), ('intersection', '&'))}
FILTERS = {kind: f'def include(before, after):\n    return {expression}\n'
           for kind, expression in (('different', 'before != after'), ('all', 'True'))}
ERRORS = {c.name: c.source for role in CALCULATOR_ROLES if role.function == 'emit_error' for c in role.options}


@dataclass(frozen=True)
class Plan:
    """Named choices for the four independently replaceable program parts."""

    group: str
    keys: str
    filter: str
    errors: str


def _key(role: str, kind: str) -> str:
    """Address an outcome for one reconciliation role in native memory."""
    return f'reconcile/role/{role}/{kind}'


def _weight(engine: StateEngine, role: str, kind: str) -> float:
    """Use task-specific evidence first, with older compatible experience as fallback."""
    weight = _activation(engine, _key(role, kind))
    if weight:
        return weight
    if role == 'group' and kind in ('count', 'sum'):
        return _activation(engine, f'synthesis/mapping/{kind}/all')
    if role == 'errors':
        return _activation(engine, f'calculator/role/emit_error/{kind}')
    return 0.0


def plans(engine: StateEngine) -> list[Plan]:
    """Rank equal candidate pools using the requested memory and stable defaults."""
    order = product(GROUPS, KEYS, FILTERS, ('stdout', 'stderr'))
    return sorted((Plan(*options) for options in order),
                  key=lambda p: -sum(_weight(engine, role.name, getattr(p, role.name)) for role in fields(p)))


def assemble(plan: Plan) -> str:
    """Render ordinary Python using only verified local fragments."""
    parts = (IMPORTS, READER, GROUPS[plan.group], KEYS[plan.keys], FILTERS[plan.filter],
             ERRORS[plan.errors], OUTPUT, ENTRY)
    return '\n\n'.join(part.rstrip() for part in parts) + '\n'


def teach_components(engine: StateEngine) -> list[dict]:
    """Run independent exercises with no full reconciliation program in training."""
    examples = (
        ('group', GROUPS, 'totals', ([{'sku': 'K', 'qty': 8}, {'sku': 'K', 'qty': -3}],), {'K': 5}),
        ('keys', KEYS, 'keys', ({'old': 3}, {'new': 2}), ['new', 'old']),
        ('filter', FILTERS, 'include', (3, 3), False),
    )
    report = []
    for role, options, call, arguments, expected in examples:
        for kind, source in options.items():
            namespace: dict = {}
            exec(compile(source, '<reconciliation fragment>', 'exec'), namespace)
            passed = namespace[call](*arguments) == expected
            _remember(engine, _key(role, kind), int(passed), int(not passed))
            report.append(dict(role=role, component=kind, passed=passed))
    return report
