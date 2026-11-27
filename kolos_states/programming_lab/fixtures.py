"""Synthetic sources and independent expected behavior for the lab."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from textwrap import dedent


@dataclass(frozen=True)
class Case:
    """One named Python function and its behavioral checks."""

    key: str
    name: str
    source: str
    examples: tuple[tuple[object, object], ...]


DEMO = Case('demonstration', 'name_length', dedent('''\
    def name_length(value):
        normalized = value.strip()
        return len(normalized)
    '''), ((None, None), ('', 0), (' ab ', 2)))

DEMO_AFTER = dedent('''\
    def name_length(value):
        if value is None:
            return None
        normalized = value.strip()
        return len(normalized)
    ''')

ALTERNATE_DEMO_AFTER = dedent('''\
    def name_length(value):
        normalized = value.strip()
        if value == 'skip':
            return 99
        return len(normalized)
    ''')

HELD_OUT = (
    Case('text', 'shout', dedent('''\
        def untouched(text):
            return text


        def shout(text):
            """Normalize a label."""
            return text.strip().upper()  # keep inline comment
        '''), ((None, None), ('', ''), (' ab ', 'AB'))),
    Case('list', 'total', dedent('''\
        def total(
            entries: list[int],
        ) -> int | None:
            return sum(
                entries,
                0,
            )
        '''), ((None, None), ([], 0), ([1, 2, -3], 0), ([2, 4], 6))),
    Case('number', 'with_fee', dedent('''\
        def with_fee(quantity):
            fee = 7
            return quantity + fee
        '''), ((None, None), (0, 7), (-2, 5), (8, 15))),
    Case('unicode', 'annotate', dedent('''\
        def annotate(метка, /):
          """Retain the original label.

          The prefix may be the only output.
          """
          метка_префикс = '№'
          return метка_префикс + метка
        '''), ((None, None), ('', '№'), ('А', '№А'))),
    Case('branch', 'first_label', dedent('''\
        def first_label(labels):
            if not labels:
                return 'empty'
            return labels[0]
        '''), ((None, None), ([], 'empty'), (['A', 'B'], 'A'))),
)

ALTERNATE = Case('alternate-rule', 'clean_label', dedent('''\
    def clean_label(label):
        trimmed = label.strip()
        return trimmed.upper()
    '''), (('skip', 99), (' skip ', 'SKIP'), ('', ''), ('Ab', 'AB')))

REFUSALS = (
    Case('ambiguous-parameter', 'join_parts', dedent('''\
        def join_parts(left, right):
            return left + right
        '''), ()),
    Case('already-guarded', DEMO.name, DEMO_AFTER, ()),
)


def behavior(case: Case, source: str) -> list[dict]:
    """Run bundled functions and compare exact result types and values."""
    namespace: dict = {'__name__': '__programming_lab_fixture__'}
    exec(compile(source, f'<{case.key}>', 'exec', dont_inherit=True), namespace)
    results = []
    for argument, expected in case.examples:
        row = dict(argument=argument, expected=expected)
        try:
            actual = namespace[case.name](deepcopy(argument))
        except Exception as error:
            row.update(passed=False, error=type(error).__name__)
        else:
            row.update(passed=type(actual) is type(expected) and actual == expected, actual=actual)
        results.append(row)
    return results
