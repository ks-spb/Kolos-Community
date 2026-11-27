"""Check assembled calculator candidates by invoking actual Python processes."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from ...core import StateEngine
from .components import assemble, plans, teach_components
from .intent import Intent, teach_words


@dataclass(frozen=True)
class Case:
    """One public or held-out command and its expected exit status and streams."""

    name: str
    arguments: tuple[str, ...]
    expected: str
    exit_code: int = 0


VISIBLE = (
    Case('fractional-division', ('7', '/', '2'), '3.5'),
    Case('decimal-spelling', ('0,1', '+', '0.2'), '0.3'),
    Case('display-number', ('4.50', '+', '1.50'), '6'),
    Case('division-by-zero', ('2', '/', '0'), 'Ошибка: деление на ноль', 2),
)
CHECKS = (
    Case('negative-product', ('-9.75', '*', '2'), '-19.5'),
    Case('subtraction', ('13', '-', '2.50'), '10.5'),
    Case('division-alias', ('-24', '÷', '8'), '-3'),
    Case('multiplication-alias', ('6', '×', '-4'), '-24'),
    Case('small-fractions', ('0.0000001', '+', '0.0000002'), '0.0000003'),
    Case('zero-format', ('0', '-', '-0'), '0'),
    Case('invalid-number', ('пять', '+', '2'), "Ошибка: неверное число 'пять'", 2),
    Case('unknown-operator', ('2', '**', '5'), "Ошибка: неизвестная операция '**'", 2),
    Case('non-finite', ('NaN', '+', '1'), "Ошибка: неверное число 'NaN'", 2),
    Case('wrong-arity', ('1', '+'), 'Ошибка: ожидались число, операция и число. Используйте --help', 2),
)


def train() -> tuple[StateEngine, dict]:
    """Teach word meanings and fragment behavior independently of complete requests."""
    engine = StateEngine()
    return engine, dict(word_count=teach_words(engine), components=teach_components(engine))


def _check(path: Path, case: Case) -> dict:
    """Score stdout, stderr and the exit code of a real calculator invocation."""
    command = [sys.executable, '-I', '-B', '-X', 'utf8', str(path.resolve()), *case.arguments]
    try:
        result = subprocess.run(command, cwd=path.parent, encoding='utf-8', capture_output=True, timeout=5)
    except subprocess.TimeoutExpired:
        return dict(case=asdict(case), passed=False, error='time_limit')
    out, err = result.stdout.rstrip('\r\n'), result.stderr.rstrip('\r\n')
    streams = ('', case.expected) if case.exit_code else (case.expected, '')
    return dict(case=asdict(case), status=result.returncode, stdout=out, stderr=err,
                passed=result.returncode == case.exit_code and (out, err) == streams)


def verify(path: Path, cases: tuple[Case, ...], *, stop_on_failure: bool = False) -> list[dict]:
    """Run the selected case set without feeding independent failures into search."""
    rows = []
    for case in cases:
        result = _check(path, case)
        rows.append(result)
        if stop_on_failure and not result['passed']:
            break
    return rows


def generate(intent: Intent, engine: StateEngine, output: Path, *, budget: int = 16) -> dict:
    """Publish the first publicly correct program only once independent tests pass."""
    if (intent.interface, intent.numbers, intent.operations) != ('console', 'decimal', ('+', '-', '*', '/')):
        raise ValueError('Генератор поддерживает консольный калькулятор с четырьмя действиями.')
    if budget < 1:
        raise ValueError('Лимит кандидатов должен быть положительным.')
    attempts: list[dict] = []
    evidence = dict(intent=asdict(intent), attempts=attempts, generator_pid=os.getpid())
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / f'.calculator-{uuid4().hex}.py'
    try:
        for recipe in plans(engine)[:budget]:
            temporary.write_text(assemble(recipe), encoding='utf-8', newline='\n')
            visible = verify(temporary, VISIBLE, stop_on_failure=True)
            attempts.append(dict(components=[c.name for c in recipe], visible=visible))
            if not all(row['passed'] for row in visible):
                continue
            independent = verify(temporary, CHECKS)
            if not all(row['passed'] for row in independent):
                return dict(status='check_failed', checks=independent, **evidence)
            os.replace(temporary, output)
            return dict(status='generated', output=str(output.resolve()), checks=independent, **evidence)
        return dict(status='no_solution', **evidence)
    finally:
        temporary.unlink(missing_ok=True)
