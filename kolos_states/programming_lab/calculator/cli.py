"""Expose the calculator generator and the two independent end-to-end trials."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from ...core import StateEngine
from ...ipc import atomic_json
from ...storage import Store
from .intent import Clarification, recognize
from .lab import generate, train

DEFAULT_ROOT = Path('tests/desktop-output/programming-lab/calculator')
SHORT_REQUEST = 'сделай мне программу-калькулятор'
EXPLICIT_REQUEST = 'создай консольный калькулятор с десятичными числами и четырьмя действиями'


def _saved_memory(path: Path) -> StateEngine:
    """Restore a calculator lesson snapshot through the standard graph store."""
    if not (path / 'memory.json').is_file():
        raise ValueError('В указанном каталоге нет файла memory.json.')
    store = Store(path)
    try:
        return store.load()
    finally:
        store.close()


def main(argv: list[str]) -> int:
    """Generate a standalone calculator from the public command."""
    parser = argparse.ArgumentParser(prog='python -m kolos_states.programming_lab calculator')
    parser.add_argument('--request', required=True)
    parser.add_argument('--output', type=Path, default=Path('calculator.py'))
    parser.add_argument('--memory', type=Path)
    parser.add_argument('--budget', type=int, default=16)
    parser.add_argument('--details', action='store_true', help='include the test transcript')
    args = parser.parse_args(argv)
    if args.output.suffix.lower() != '.py' or args.budget < 1:
        parser.error('Укажите выходной файл .py и положительное число попыток.')
    try:
        engine = _saved_memory(args.memory) if args.memory is not None else train()[0]
        intent = recognize(args.request, engine)
        result = generate(intent, engine, args.output, budget=args.budget)
    except Clarification as error:
        print(json.dumps(dict(status='needs_clarification', question=str(error)), ensure_ascii=True))
        return 2
    except (ValueError, OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 2
    public = result if args.details else dict(status=result['status'], output=result.get('output'),
                                               intent=result['intent'], attempts=len(result['attempts']),
                                               checks_passed=sum(c['passed'] for c in result.get('checks', ())))
    print(json.dumps(public, ensure_ascii=True))
    return int(result['status'] != 'generated')


def _public_trial(request: str, memory: Path, output: Path) -> dict:
    """Invoke the documented command in a fresh process with saved lessons."""
    command = [sys.executable, '-B', '-m', 'kolos_states.programming_lab', 'calculator', '--details',
               '--request', request, '--memory', str(memory), '--output', str(output)]
    try:
        child = subprocess.run(command, capture_output=True, encoding='utf-8', timeout=60)
    except subprocess.TimeoutExpired:
        return dict(request=request, status='time_limit')
    try:
        result = json.loads(child.stdout)
    except ValueError:
        result = dict(status='process_failed', error=child.stderr.strip())
    return dict(request=request, returncode=child.returncode, **result)


def benchmark(argv: list[str]) -> int:
    """Verify explicit and minimal wording, plus a bounded unsupported-format control."""
    parser = argparse.ArgumentParser(prog='python -m kolos_states.programming_lab calculator-benchmark')
    parser.add_argument('--output', type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    folder = args.output.resolve() / f'run-{uuid4().hex}'
    folder.mkdir(parents=True)
    learned, teaching = train()
    memory = folder / 'memory'
    store = Store(memory)
    try:
        store.save(learned)
    finally:
        store.close()
    snapshot = sha256((memory / 'memory.json').read_bytes()).hexdigest()
    trials = {kind: _public_trial(request, memory, folder / kind / 'calculator.py')
              for kind, request in (('explicit', EXPLICIT_REQUEST), ('short', SHORT_REQUEST))}
    control_file = folder / 'window.py'
    marker = b'# Original file\n'
    control_file.write_bytes(marker)
    controls = _public_trial('сделай калькулятор с окном', memory, control_file)
    controls['original_preserved'] = control_file.read_bytes() == marker
    typed = recognize(SHORT_REQUEST, learned)
    baseline = generate(typed, StateEngine(), folder / 'empty_memory' / 'calculator.py')
    intact = snapshot == sha256((memory / 'memory.json').read_bytes()).hexdigest()
    fresh = all(t.get('generator_pid') not in (None, os.getpid()) for t in trials.values())
    passed = (intact and fresh and controls['status'] == 'needs_clarification' and controls['original_preserved']
              and all(t['status'] == 'generated' and t['returncode'] == 0 for t in trials.values()))
    report = dict(schema='kolos-text-calculator/1', passed=passed, teaching=teaching, trials=trials,
                  empty_program_memory=baseline, window_control=controls, snapshots_match=intact,
                  fresh_generation_processes=fresh, llm_calls=0)
    atomic_json(folder / 'report.json', report)
    print(json.dumps(dict(passed=passed, attempts={key: len(t.get('attempts', ())) for key, t in trials.items()},
                          empty_program_memory_attempts=len(baseline['attempts']), report=str(folder / 'report.json'))))
    return int(not passed)
