"""Issue one verified Python file from a sentence and the active graph."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

from ...core import StateEngine
from ..reconcile.cli import MEMORY, _load
from .corpus import probe
from .judge import run_probe
from .program import compile_program
from .routing import Policy, Router, decide

AUDIT = 'programming-catalog-policy/1'


def metadata(engine: StateEngine) -> dict:
    """Keep the catalog policy in the native persisted graph's audit metadata."""
    return next((row for row in reversed(engine.model['audit'])
                 if isinstance(row, dict) and row.get('scope') == AUDIT), {})


def policy_of(engine: StateEngine) -> Policy:
    """Restore the policy paired with the currently loaded graph."""
    raw = metadata(engine).get('policy')
    return Policy(tuple(raw['lexicon']), raw['floor'], raw['margin']) if raw else Policy()


def save_policy(engine: StateEngine, policy: Policy, **details: object) -> None:
    """Update catalog metadata without changing existing audit entries."""
    log = engine.model['audit']
    log[:] = [row for row in log if not isinstance(row, dict) or row.get('scope') != AUDIT]
    log.append(dict(scope=AUDIT, policy=asdict(policy), **details))


def create(request: str, output: Path, engine: StateEngine) -> dict:
    """Keep the requested output intact until both independent smoke tests pass."""
    decision = decide(request, Router(engine, policy_of(engine)).pick)
    if decision.spec is None:
        return dict(status='needs_clarification', question=decision.question, kind=decision.kind)
    source = compile_program(decision.spec, engine)
    compile(source, str(output), 'exec')
    output = output.absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / f'.catalog-{uuid4().hex}.py'
    try:
        temporary.write_text(source, encoding='utf-8', newline='\n')
        results = [run_probe(temporary, probe(decision.spec, 17, index),
                             temporary.parent / f'{temporary.stem}-{index}') for index in range(2)]
        if not all(row['passed'] for row in results):
            return dict(status='verification_failed', spec=asdict(decision.spec), checks=results)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return dict(status='generated', spec=asdict(decision.spec), output=str(output), python_executions=len(results))


def main(argv: list[str]) -> int:
    """Create a program with the learned catalog router and no external model."""
    parser = argparse.ArgumentParser(prog='python -m kolos_states.programming_lab catalog')
    parser.add_argument('--request', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--memory', type=Path, default=MEMORY)
    args = parser.parse_args(argv)
    if args.output.suffix.lower() != '.py':
        parser.error('Укажите выходной файл .py.')
    try:
        result = create(args.request, args.output, _load(args.memory))
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result['status'] == 'generated' else 2 if result['status'] == 'needs_clarification' else 1
