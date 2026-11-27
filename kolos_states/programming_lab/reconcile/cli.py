"""Generate and benchmark a reconciliation utility on the continuing graph."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from uuid import uuid4

from ...core import StateEngine
from ...ipc import atomic_json
from ...storage import Store
from ..calculator.intent import Clarification
from ..retention import measure
from .components import teach_components
from .intent import REQUEST, recognize, teach_words
from .lab import generate

LOCAL = Path('.local-data/programming-lab')
MEMORY = LOCAL / 'shared-memory'
SNAPSHOTS = LOCAL / 'snapshots'
REPORTS = Path('tests/desktop-output/programming-lab/reconcile')


def _snapshot(path: Path, data: bytes) -> None:
    """Write a new snapshot without replacing a previous experiment's file."""
    path.mkdir(parents=True)
    with (path / 'memory.json').open('xb') as stream:
        stream.write(data)


def _load(path: Path) -> StateEngine:
    """Load exactly the requested persisted graph through native Store validation."""
    if not (path / 'memory.json').is_file():
        raise ValueError(f'Отсутствует memory.json в {path}')
    store = Store(path)
    try:
        return store.load()
    finally:
        store.close()


def _train(engine: StateEngine) -> dict:
    """Add independent vocabulary and tentative fragment choices to the supplied graph."""
    return dict(words=teach_words(engine), components=teach_components(engine))


def _record(path: Path, engine: StateEngine, *, expected: bytes | None = None) -> bool:
    """Save using the native lock and preserve any concurrent update of active memory."""
    store = Store(path)
    try:
        if expected is not None and (path / 'memory.json').read_bytes() != expected:
            return False
        store.save(engine)
        return True
    finally:
        store.close()


def _restore(memory: Path, snapshots: Path) -> str | None:
    """Recover the working copy from the latest retained version if it is missing."""
    target = memory / 'memory.json'
    if target.is_file():
        return None
    available = list(snapshots.glob('*/after/memory.json'))
    available += list(snapshots.glob('initial/memory.json'))
    if not available:
        raise ValueError(f'Накопленная память отсутствует в {memory}, снимки отсутствуют в {snapshots}.')
    source = max(available, key=lambda p: p.stat().st_mtime_ns)
    memory.mkdir(parents=True, exist_ok=True)
    lock = Store(memory)
    try:
        with target.open('xb') as stream:
            stream.write(source.read_bytes())
    finally:
        lock.close()
    return str(source)


def main(argv: list[str]) -> int:
    """Create a standalone reconciliation script from a text request and loaded memory."""
    parser = argparse.ArgumentParser(prog='python -m kolos_states.programming_lab reconcile')
    parser.add_argument('--request', required=True)
    parser.add_argument('--memory', type=Path, default=MEMORY)
    parser.add_argument('--output', type=Path, default=Path('reconcile.py'))
    args = parser.parse_args(argv)
    if args.output.suffix.lower() != '.py':
        parser.error('Укажите выходной файл .py.')
    try:
        engine = _load(args.memory)
        intent = recognize(args.request, engine)
        result = generate(intent, engine, args.output)
    except Clarification as error:
        print(json.dumps(dict(status='needs_clarification', question=str(error)), ensure_ascii=True))
        return 2
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(dict(status=result['status'], output=result['output'], attempts=len(result['attempts']),
                          checks_passed=sum(row['passed'] for row in result['checks'])), ensure_ascii=True))
    return int(result['status'] != 'generated')


def _compare(folder: Path, prior: StateEngine, learned: StateEngine) -> dict:
    """Isolate the effect of inherited memory before and after the same domain lessons."""
    fresh = StateEngine()
    _train(fresh)
    intent = recognize(REQUEST, learned)
    graphs = {'empty': StateEngine(), 'prior': prior, 'new_lessons_only': fresh, 'cumulative': learned}
    return {name: generate(intent, engine, folder / name / 'reconcile.py') for name, engine in graphs.items()}


def run(output: Path, memory: Path, snapshots: Path) -> tuple[Path, dict]:
    """Preserve both graph versions, repeat prior tests and retain the new experience."""
    run_id = f'reconcile-{uuid4().hex}'
    folder = output.resolve() / run_id
    folder.mkdir(parents=True)
    memory, archive = memory.resolve(), snapshots.resolve() / run_id
    recovered = _restore(memory, snapshots.resolve())
    original = (memory / 'memory.json').read_bytes()
    _snapshot(archive / 'before', original)
    prior = _load(archive / 'before')
    learned = _load(archive / 'before')
    lessons = _train(learned)
    _record(archive / 'after', learned)
    learned = _load(archive / 'after')
    before = measure(prior, folder / 'retention' / 'before')
    after = measure(learned, folder / 'retention' / 'after')
    trials = _compare(folder, prior, learned)
    identical = before['tasks'] == after['tasks'] and before['calculator'] == after['calculator']
    promoted = _record(memory, learned, expected=original)
    saved = (archive / 'after' / 'memory.json').read_bytes()
    report = dict(schema='kolos-reconcile/1', request=REQUEST, lessons=lessons, trials=trials,
                  retention=dict(before=before, after=after, identical_results=identical),
                  memory=dict(before=str(archive / 'before'), after=str(archive / 'after'), active=str(memory),
                              before_sha256=sha256(original).hexdigest(), after_sha256=sha256(saved).hexdigest(),
                              recovered_from=recovered, active_saved=promoted,
                              active_matches_after=(memory / 'memory.json').read_bytes() == saved),
                  passed=promoted and trials['cumulative']['status'] == 'generated', llm_calls=0)
    atomic_json(folder / 'report.json', report)
    return folder, report


def benchmark(argv: list[str]) -> int:
    """Run the memory-controlled experiment using the documented working graph."""
    parser = argparse.ArgumentParser(prog='python -m kolos_states.programming_lab reconcile-benchmark')
    parser.add_argument('--memory', type=Path, default=MEMORY)
    parser.add_argument('--snapshots', type=Path, default=SNAPSHOTS)
    parser.add_argument('--output', type=Path, default=REPORTS)
    args = parser.parse_args(argv)
    try:
        folder, report = run(args.output, args.memory, args.snapshots)
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 2
    summary = {name: dict(status=row['status'], attempts=len(row['attempts']), seconds=row['seconds'],
                          checks_passed=sum(c['passed'] for c in row['checks']))
               for name, row in report['trials'].items()}
    print(json.dumps(dict(passed=report['passed'], trials=summary, report=str(folder / 'report.json'),
                          active_saved=report['memory']['active_saved'],
                          identical_old_results=report['retention']['identical_results'])))
    return int(not report['passed'])
