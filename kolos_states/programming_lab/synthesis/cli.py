"""Deliver a verified, standalone Python file from a user-owned JSON task."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic
from uuid import uuid4

from ...core import StateEngine
from ...storage import Store
from .solver import solve, train
from .spec import Task, load_task

_IMPORT_CHECK = '''
import importlib.util, json, sys
path, name = sys.argv[1:]
spec = importlib.util.spec_from_file_location('kolos_generated', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
for case in json.load(sys.stdin):
    stable = lambda value: json.dumps(value, sort_keys=True, allow_nan=False)
    if stable(getattr(module, name)(case['input'])) != stable(case['expected']):
        raise SystemExit(1)
'''


def publish(task: Task, source: str, output: Path) -> None:
    """Import generated local code before atomically installing it at the requested path."""
    output.parent.mkdir(parents=True, exist_ok=True)
    tentative = output.parent / f'.kolos-{uuid4().hex}.py'
    try:
        with tentative.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(source)
        cases = json.dumps([asdict(case) for case in (*task.examples, *task.checks)], ensure_ascii=True)
        completed = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', '-c', _IMPORT_CHECK,
                                    str(tentative.resolve()), task.function],
                                   input=cases, text=True, encoding='utf-8', capture_output=True, timeout=15)
        if completed.returncode:
            raise ValueError('Готовая функция не прошла проверку импорта в отдельном Python.')
        os.replace(tentative, output)
    finally:
        tentative.unlink(missing_ok=True)


def _load_memory(path: Path | None, *, compose: bool = False) -> StateEngine:
    """Use the built-in training unless the caller selected an existing snapshot."""
    if path is None:
        if compose:
            from .group_corpus import LESSONS
            return train(LESSONS)[0]
        return train()[0]
    if not (path / 'memory.json').is_file():
        raise ValueError('В указанном каталоге нет memory.json. Сначала выполните synthesize-learn.')
    store = Store(path)
    try:
        return store.load()
    finally:
        store.close()


def synthesize(argv: list[str]) -> int:
    """Generate and verify one function, returning a diagnostic on failure."""
    parser = argparse.ArgumentParser(prog='python -m kolos_states.programming_lab synthesize')
    parser.add_argument('--task', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--memory', type=Path)
    parser.add_argument('--budget', type=int, default=512)
    parser.add_argument('--compose', action='store_true', help='infer whether to filter rows or grouped totals')
    args = parser.parse_args(argv)
    if args.budget < 1 or args.output.suffix.lower() != '.py' or args.output.resolve() == args.task.resolve():
        parser.error('Нужны положительный --budget и выходной .py, отличный от входного файла.')
    try:
        task = load_task(args.task)
        result = solve(task, _load_memory(args.memory, compose=args.compose), args.budget, monotonic() + 120,
                       compose=args.compose)
        if result['status'] != 'solved':
            details = result.get('verification') or (result['attempts'][-1]['feedback'] if result['attempts'] else None)
            print(json.dumps(dict(status=result['status'], attempts=len(result['attempts']), feedback=details,
                                  screening=result['screening']),
                             ensure_ascii=True))
            return 1
        publish(task, result['source'], args.output)
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(dict(status='solved', output=str(args.output.resolve()), attempts=len(result['attempts']),
                          checked=len(task.examples) + len(task.checks), screening=result['screening']), ensure_ascii=True))
    return 0


def learn(argv: list[str]) -> int:
    """Persist a native graph trained only from teaching tasks whose examples all pass."""
    from .corpus import TEACHING

    parser = argparse.ArgumentParser(prog='python -m kolos_states.programming_lab synthesize-learn')
    parser.add_argument('--memory', required=True, type=Path)
    parser.add_argument('--task', action='append', type=Path, default=[])
    args = parser.parse_args(argv)
    try:
        lessons = (*TEACHING, *(load_task(path) for path in args.task))
        engine, counts = train(lessons)
        store = Store(args.memory)
        try:
            if (args.memory / 'memory.json').exists():
                raise ValueError('Для новой памяти выберите другой каталог.')
            store.save(engine)
        finally:
            store.close()
    except (ValueError, OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(dict(status='trained', memory=str(args.memory.resolve()), lessons=len(lessons), features=len(counts))))
    return 0
