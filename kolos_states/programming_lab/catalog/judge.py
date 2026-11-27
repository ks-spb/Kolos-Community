"""Run each issued program on independent inputs in ordinary Python processes."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from typing import Callable

from ...core import StateEngine
from .corpus import Probe, Request
from .program import compile_program
from .routing import decide
from .spec import Spec


def run_probe(program: Path, probe: Probe, directory: Path) -> dict:
    """Use a separate data directory for each process and preserve the source artifact."""
    started = perf_counter()
    directory.mkdir()
    files = [directory / name for name, _ in probe.files]
    try:
        for path, (_, content) in zip(files, probe.files, strict=True):
            path.write_text(content, encoding='utf-8', newline='')
        result = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', str(program.resolve()), *probe.args],
                                cwd=directory, capture_output=True, encoding='utf-8', timeout=5)
        intact = all(path.read_bytes() == text.encode('utf-8') for path, (_, text) in zip(files, probe.files, strict=True))
        passed = result.returncode == 0 and not result.stderr and result.stdout == probe.output and intact
        return dict(passed=passed, status=result.returncode, files_preserved=intact,
                    error=(result.stderr or None) if not passed else None,
                    actual=None if passed else result.stdout, seconds=round(perf_counter() - started, 5))
    except subprocess.TimeoutExpired:
        return dict(passed=False, error='time_limit', seconds=round(perf_counter() - started, 5))
    finally:
        for path in files:
            path.unlink(missing_ok=True)
        directory.rmdir()


def _check_program(job: tuple[dict, Path, tuple[Probe, ...]]) -> dict:
    """Run both independent probes even if the first one fails."""
    row, program, probes = job
    checks = [run_probe(program, probe, program.parent / f'check-{i}') for i, probe in enumerate(probes)]
    row.update(checks=checks, passed=row['parameters_correct'] and all(check['passed'] for check in checks))
    return row


def evaluate(corpus: tuple[Request, ...], pick: Callable[[str], str | None], builder: StateEngine,
             directory: Path, workers: int = 6) -> tuple[list[dict], dict]:
    """Resolve one request per row, run two probes for every supported issued artifact."""
    started = perf_counter()
    results, jobs = [], []
    sources: dict[Spec, str] = {}
    for request in corpus:
        marked = perf_counter()
        decision = decide(request.text, pick)
        spec = decision.spec
        row = dict(id=request.id, category=request.category, kind=decision.kind, issued=spec is not None,
                   spec=asdict(spec) if spec else None, question=decision.question,
                   intent_correct=request.expected is not None and decision.kind == request.expected.kind,
                   parameters_correct=spec is not None and spec == request.expected,
                   routing_seconds=round(perf_counter() - marked, 6), attempts=int(spec is not None),
                   passed=request.expected is None and spec is None, checks=[])
        results.append(row)
        if spec is not None:
            if spec not in sources:
                sources[spec] = compile_program(spec, builder)
            program = directory / request.id / 'program.py'
            program.parent.mkdir(parents=True)
            program.write_text(sources[spec], encoding='utf-8', newline='\n')
            if request.probes:
                jobs.append((row, program, request.probes))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for _ in pool.map(_check_program, jobs):
            pass
    return results, summary(results, perf_counter() - started)


def summary(rows: list[dict], elapsed: float) -> dict:
    """Separate semantic success, false delivery, abstention and actual executions."""
    supported = [row for row in rows if row['category'] == 'supported']
    controls = [row for row in rows if row['category'] != 'supported']
    return dict(total=len(supported), solved=sum(row['passed'] for row in supported),
                intended_programs=sum(row['intent_correct'] for row in supported),
                exact_specifications=sum(row['parameters_correct'] for row in supported),
                wrong_deliveries=sum(row['issued'] and not row['passed'] for row in supported),
                supported_clarifications=sum(not row['issued'] for row in supported),
                controls_clarified=sum(not row['issued'] for row in controls), controls_total=len(controls),
                false_accepts={name: sum(row['category'] == name and row['issued'] for row in controls)
                               for name in ('ambiguous', 'unknown')},
                attempts=sum(row['attempts'] for row in rows),
                python_executions=sum(len(row['checks']) for row in rows),
                routing_seconds=round(sum(row['routing_seconds'] for row in rows), 4),
                elapsed_seconds=round(elapsed, 4))
