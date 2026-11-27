"""Check candidate programs on real pairs of files before publishing them."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from uuid import uuid4

from ...core import StateEngine
from .components import assemble, plans
from .intent import Intent

HEADER = 'sku,before,after,delta\n'
UNCHANGED = 'existing-report\n'


@dataclass(frozen=True)
class Case:
    """One public or held-out test against the generated Python command."""

    name: str
    before: str
    after: str | None
    rows: str = ''
    error: str | None = None
    destination: str = 'stdout'


VISIBLE = (
    Case('duplicates-and-missing', 'sku,qty\nA,2\nA,3\nD,2\nS,1\n',
         'sku,qty\nA,4\nB,3\nS,1\n', 'A,5,4,-1\nB,0,3,3\nD,2,0,-2\n'),
    Case('invalid-quantity', 'sku,qty\nA,2\n', 'sku,qty\nA,1.5\n',
         error='ожидались артикул и целое qty', destination='file'),
)
CHECKS = (
    Case('quoting-and-bom', '\ufeffqty,sku,note\r\n2,"M,1",x\r\n-3,"M,1",y\r\n',
         'sku,qty\n"M,1",3\n', '"M,1",-1,3,4\n'),
    Case('net-zero-and-negative', 'sku,qty\nA,4\nA,-4\nN,-5\n',
         'sku,qty\nA,0\nN,-3\n', 'N,-5,-3,2\n'),
    Case('empty-before', '', 'sku,qty\nT,7\n', 'T,0,7,7\n'),
    Case('empty-after', 'sku,qty\nZ,-4\n', 'sku,qty\n', 'Z,-4,0,4\n'),
    Case('no-changes-file', 'sku,qty\nA,2\nA,3\n', 'sku,qty\nA,5\n', destination='file'),
    Case('missing-column', 'sku,quantity\nA,2\n', 'sku,qty\n',
         error='нужны уникальные столбцы sku и qty', destination='file'),
    Case('missing-file', 'sku,qty\n', None, error='Ошибка:', destination='file'),
    Case('protect-input', 'sku,qty\nA,2\n', 'sku,qty\nA,3\n',
         error='файл результата должен отличаться от входных файлов', destination='input'),
)


def _check(program: Path, case: Case) -> dict:
    """Launch an ordinary Python process and verify output and preservation of inputs."""
    work = program.parent / f'.csv-case-{uuid4().hex}'
    work.mkdir()
    before, after, output = (work / name for name in ('before.csv', 'after.csv', 'report.csv'))
    try:
        before.write_bytes(case.before.encode('utf-8'))
        if case.after is not None:
            after.write_bytes(case.after.encode('utf-8'))
        if case.destination == 'file':
            output.write_text(UNCHANGED, encoding='utf-8')
        command = [sys.executable, '-I', '-B', '-X', 'utf8', str(program.resolve()), str(before), str(after)]
        targets = {'file': output, 'input': before}
        if case.destination in targets:
            command.extend(('--output', str(targets[case.destination])))
        result = subprocess.run(command, cwd=work, capture_output=True, encoding='utf-8', timeout=8)
        intact = before.read_bytes() == case.before.encode('utf-8')
        intact &= (not after.exists()) if case.after is None else after.read_bytes() == case.after.encode('utf-8')
        report = output.read_text(encoding='utf-8') if output.is_file() else None
        if case.error:
            matched = (result.returncode == 2 and not result.stdout and case.error in result.stderr
                       and report == (UNCHANGED if case.destination == 'file' else None))
        else:
            streams = (HEADER + case.rows, None) if case.destination == 'stdout' else ('', HEADER + case.rows)
            matched = result.returncode == 0 and not result.stderr and (result.stdout, report) == streams
        return dict(case=case.name, passed=bool(matched and intact), status=result.returncode, inputs_preserved=intact,
                    stdout=result.stdout, stderr=result.stderr, report=report)
    except subprocess.TimeoutExpired:
        return dict(case=case.name, passed=False, failure='time_limit')
    finally:
        for path in (before, after, output):
            path.unlink(missing_ok=True)
        work.rmdir()


def _visible(program: Path) -> list[dict]:
    """Stop public verification at the first incorrect result for each candidate."""
    rows = []
    for case in VISIBLE:
        rows.append(_check(program, case))
        if not rows[-1]['passed']:
            break
    return rows


def generate(intent: Intent, engine: StateEngine, output: Path, *, budget: int = 24) -> dict:
    """Publish the first publicly correct program only if all independent checks also pass."""
    if budget < 1:
        raise ValueError('Лимит кандидатов должен быть положительным.')
    start = perf_counter()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / f'.reconcile-{uuid4().hex}.py'
    attempts: list[dict] = []
    result = dict(status='no_solution', intent=asdict(intent), attempts=attempts, checks=[], output=None)
    try:
        for plan in plans(engine)[:budget]:
            temporary.write_text(assemble(plan), encoding='utf-8', newline='\n')
            visible = _visible(temporary)
            attempts.append(dict(plan=asdict(plan), visible=visible))
            if not all(row['passed'] for row in visible):
                continue
            independent = [_check(temporary, case) for case in CHECKS]
            result.update(status='check_failed', checks=independent)
            if all(row['passed'] for row in independent):
                os.replace(temporary, output)
                result.update(status='generated', output=str(output))
            break
    finally:
        temporary.unlink(missing_ok=True)
    result['seconds'] = round(perf_counter() - start, 4)
    return result
