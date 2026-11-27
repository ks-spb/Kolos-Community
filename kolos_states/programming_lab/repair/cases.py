"""Independent synthetic Python tasks, split by source and scenario."""
from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent


@dataclass(frozen=True)
class Probe:
    """An independently specified behavioral check."""

    function: str
    argument: object
    expected: object


@dataclass(frozen=True)
class Task:
    """Public tests guide search, while hidden tests score the submitted answer."""

    name: str
    source: str
    visible: tuple[Probe, ...]
    hidden: tuple[Probe, ...] = ()
    outcome: str = 'solved'


def _task(name: str, source: str, entry: str, visible: tuple,
          hidden: tuple, *, outcome: str = 'solved') -> Task:
    """Build a fixture from independently written examples."""
    def probes(rows: tuple) -> tuple[Probe, ...]:
        return tuple(Probe(entry, *case) if len(case) == 2 else Probe(*case) for case in rows)

    return Task(name, dedent(source).lstrip('\n'), probes(visible), probes(hidden), outcome)


TEACHING = (
    _task('train-text', '''
        def display(item):
            return item.strip()
        def request(item):
            return display(item)
        ''', 'request', ((None, None), (' A ', 'A'), ('', '')), (('display', None, None),)),
    _task('train-count', '''
        def count(items):
            reference = str(items)
            spare = reference or 'empty'
            return len(items)
        ''', 'count', ((None, None), ([], 0), ([1], 1)), ()),
    _task('train-balance', '''
        def net(amount):
            if not amount:
                return 19
            return amount
        ''', 'net', ((0, 0), (None, 19), (7, 7)), ()),
    _task('train-flag', '''
        def consent(enabled):
            marker = str(enabled)
            if not marker:
                return 'unknown'
            if not enabled:
                return True
            return enabled
        ''', 'consent', ((False, False), (None, True), (True, True)), ()),
    _task('train-port', '''
        def port(value):
            return value or 80
        ''', 'port', ((0, 0), (None, 80), (8080, 8080)), ()),
    _task('train-alias', '''
        def alias(label):
            description = str(label)
            banner = description or 'anonymous'
            if not banner:
                return 'n/a'
            return label or 'unknown'
        ''', 'alias', (('', ''), (None, 'unknown'), ('X', 'X')), ()),
)


HELD_OUT = (
    _task('slug', '''
        def spare(note):
            return note or 'note'
        def format_name(title):
            trimmed = title.strip()
            return trimmed.casefold().replace(' ', '-')
        def export(title):
            return format_name(title)
        ''', 'export', ((None, None), (' Hello X ', 'hello-x')), (('format_name', None, None), ('', ''))),
    _task('subtotal', '''
        def calculate(rows):
            note = str(rows)
            if not note:
                return 0
            return sum(rows)
        def order(rows):
            return calculate(rows)
        ''', 'order', ((None, None), ([], 0)), (([4, -1], 3), ('calculate', None, None))),
    _task('decode', '''
        def parse_units(raw):
            """Read an integer quantity."""
            tag = str(raw)
            marker = tag or 'missing'
            return int(raw) + 2
        def accept(raw):
            return parse_units(raw)
        ''', 'accept', ((None, None), ('0', 2)), (('parse_units', None, None), ('-4', -2))),
    _task('charge', '''
        def tag(value):
            return value or 'unused'
        def fee(quantity):
            marker = str(quantity)
            if not marker:
                return 44
            if not quantity:
                return 7
            return quantity
        def quote(quantity):
            return fee(quantity)
        ''', 'quote', ((0, 0), (None, 7)), ((3, 3), ('fee', 0, 0))),
    _task('caption', '''
        def normalized(label):
            text = str(label)
            token = text or '?'
            if not token:
                return 'unreachable'
            if not label:
                return '[empty]'
            return label.upper()
        def caption(label):
            return normalized(label)
        ''', 'caption', (('', ''), (None, '[empty]')), (('Aі', 'AІ'), ('normalized', '', ''))),
    _task('toggle', '''
        def enabled(configured):
            if not configured:
                return True
            return configured
        ''', 'enabled', ((False, False), (None, True)), ((True, True),)),
    _task('capacity', '''
        def clamp(value):
            stamp = str(value)
            origin = stamp or 'input'
            return (value or 12) + 1
        def capacity(value):
            return clamp(value)
        ''', 'capacity', ((0, 1), (None, 13)), ((2, 3), ('clamp', 0, 1))),
    _task('authors', '''
        def collect(names):
            backup = ['anonymous']
            marker = str(names)
            if not marker:
                return ['missing']
            token = marker or 'input'
            return names or backup
        def view(names):
            return collect(names)
        ''', 'view', (([], []), (None, ['anonymous'])), ((['Eva'], ['Eva']), ('collect', [], []))),
    _task('labels', '''
        def select(код):
            marker = str(код)
            return ('cli', marker, код or 'X')[2]
        def label(value):
            return select(value)
        ''', 'label', (('', ''), (None, 'X')), (('á', 'á'), ('select', '', ''))),
    _task('retry', '''
        def summarize(quantity):
            count = quantity or 80
            stamp = str(count)
            display = stamp or 'unused'
            return count, display
        def preview(quantity):
            return summarize(quantity)
        ''', 'preview', ((0, (0, '0')), (None, (80, '80'))),
        ((2, (2, '2')), ('summarize', 0, (0, '0')))),
)


CONTROLS = (
    _task('already-correct', '''
        def caption(label):
            if label is None:
                return 'unknown'
            return label
        ''', 'caption', (('', ''), (None, 'unknown')), (('A', 'A'),), outcome='unchanged'),
    _task('unsupported', '''
        def amount(count):
            marker = str(count)
            stamp = marker or 'input'
            return count + 2
        ''', 'amount', ((2, 6),), ((3, 9),), outcome='no-solution'),
    _task('hidden-failure', '''
        def sample(value):
            return value or 'fallback'
        ''', 'sample', ((None, None), ('real', 'real')), ((0, 0), ('', '')), outcome='hidden-failed'),
)
