"""Render standalone programs with the same components for every router."""
from __future__ import annotations

from textwrap import dedent

from ...core import StateEngine
from ..calculator.components import assemble as calculator, plans as calculator_plans
from ..reconcile.components import READER, assemble as reconciliation, plans as reconciliation_plans
from ..synthesis.grammar import Predicate, Recipe, render
from ..synthesis.spec import Task
from .spec import Spec

_RUN_JSON = dedent('''\
    if __name__ == '__main__':
        import json
        import sys

        try:
            if len(sys.argv) != 2:
                raise ValueError('Укажите путь к JSON со списком целых чисел')
            with open(sys.argv[1], encoding='utf-8-sig') as file:
                values = json.load(file)
            if not isinstance(values, list) or any(type(value) is not int for value in values):
                raise ValueError('Ожидался JSON-список целых чисел')
            print(json.dumps(apply(values)))
        except (OSError, ValueError) as error:
            print('Ошибка:', error, file=sys.stderr)
            raise SystemExit(2)
    ''')
_RUN_CSV = dedent('''\
    if __name__ == '__main__':
        import sys
        from pathlib import Path

        try:
            if len(sys.argv) != 2:
                raise ValueError('Укажите путь к CSV со столбцами sku и qty')
            data = read_rows(Path(sys.argv[1]))
            writer = csv.writer(sys.stdout, lineterminator='\\n')
            writer.writerow(('sku', HEADER))
            writer.writerows(apply(data))
        except (OSError, ValueError, csv.Error) as error:
            print('Ошибка:', error, file=sys.stderr)
            raise SystemExit(2)
    ''')
_ROWS = "def apply(rows):\n    return [(row['sku'], row['qty']) for row in select(rows)]\n"
_GROUP_ROWS = 'def apply(rows):\n    return sorted(tally(rows).items())\n'


def _function(name: str, recipe: Recipe) -> str:
    """Reuse the already verified synthesis grammar for numeric functions."""
    return render(Task(name, 'rows', (), ()), recipe)


def _csv(spec: Spec, p: Predicate | None) -> str:
    """Adapt a known CSV selection to the normal CLI with standard-library I/O."""
    if spec.kind in ('totals', 'group_filter', 'csv_count'):
        count = spec.kind == 'csv_count'
        recipe = Recipe('count' if count else 'sum', None if count else 'qty', 'sku', result_predicate=p)
        return _function('tally', recipe) + '\n' + _GROUP_ROWS
    if spec.kind == 'csv_filter':
        p = Predicate('qty', spec.op, spec.threshold)
        return _function('select', Recipe('filter', predicate=p)) + '\n' + _ROWS
    if spec.kind == 'csv_sort':
        selector = ('def select(rows):\n'
                    f'    return sorted(rows, key=lambda row: row[{spec.column!r}], reverse={spec.descending!r})\n')
        return selector + '\n' + _ROWS
    return dedent('''\
        def apply(rows):
            return dict.fromkeys((row['sku'], row['qty']) for row in rows)
        ''')


def compile_program(spec: Spec, graph: StateEngine) -> str:
    """Emit one bounded program from its validated specification."""
    if spec.kind == 'calculator':
        return calculator(calculator_plans(graph)[0])
    if spec.kind == 'reconcile':
        return reconciliation(reconciliation_plans(graph)[0])
    predicate = Predicate(None, spec.op, spec.threshold) if spec.op is not None else None
    if spec.kind in ('number_filter', 'number_count'):
        recipe = Recipe('filter' if spec.kind == 'number_filter' else 'count', predicate=predicate)
        return _function('apply', recipe) + '\n' + _RUN_JSON
    header = 'count' if spec.kind == 'csv_count' else 'qty'
    return ('import csv\nimport re\n\n' + READER + '\n' + _csv(spec, predicate) + '\n'
            + _RUN_CSV.replace('HEADER', repr(header)))
