"""Teach once, then verify held-out Python edits in a fresh process."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from ..core import StateEngine
from ..storage import Store
from .episode import run_episode, teach_episode
from .fixtures import ALTERNATE, ALTERNATE_DEMO_AFTER, DEMO, DEMO_AFTER, HELD_OUT, REFUSALS, Case, behavior
from .transform import GuardRule, learn_guard

SCHEMA = 'kolos-programming-lab/1'
DEFAULT_OUTPUT = Path('tests/desktop-output/programming-lab')


def _write_json(path: Path, payload: dict) -> None:
    """Keep reports and the independent AST rules readable."""
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def _trial(path: Path, engine: StateEngine, case: Case, rule: GuardRule, *,
           label: str | None = None, expected: str = 'complete') -> dict:
    """Save verified generated source and compare against an unedited behavioral baseline."""
    folder = path / (label or case.key)
    folder.mkdir()
    row, candidate = run_episode(engine, case, rule)
    (folder / 'before.py').write_text(case.source, encoding='utf-8', newline='')
    if candidate is not None:
        (folder / 'after.py').write_text(candidate, encoding='utf-8', newline='')
    row.update(trial=folder.name, expected_status=expected, generated=candidate is not None,
               unedited_checks=behavior(case, case.source) if case.examples else [])
    expected_edit = candidate is not None and row['preserved'] and bool(row['checks'])
    if expected == 'complete':
        verified = expected_edit and any(not check['passed'] for check in row['unedited_checks'])
    else:
        verified = candidate is None and bool(row['reason'])
    row['passed'] = row['memory_unchanged'] and row['status'] == expected and verified
    return row


def _controls(path: Path, store: Store, rule: GuardRule, alternate: GuardRule) -> list[dict]:
    """Prove the graph is used and that failed verification never publishes an edit."""
    disabled = store.load()
    command = disabled.model['episodeCommands'][0]['node']
    read = disabled.edges(command, 'episode_next')[0]['to']
    disabled.set_weight(disabled.edges(read, 'episode_next')[0]['id'], 0)
    edge = _trial(path, disabled, HELD_OUT[0], rule, label='disabled-edge', expected='blocked')
    cold = _trial(path, StateEngine(), HELD_OUT[0], rule, label='untrained', expected='idle')
    rejected = _trial(path, store.load(), HELD_OUT[2], alternate,
                      label='failed-verification', expected='failed')
    edge['passed'] &= [a['kind'] for a in edge['actions']] == ['read']
    cold['passed'] &= not cold['actions']
    rejected['passed'] &= any(not check['passed'] for check in rejected['checks'])
    refusals = [_trial(path, store.load(), case, rule, expected='failed') for case in REFUSALS]
    for row in refusals:
        row['passed'] &= not row['checks'] and row['actions'][-1:] == [dict(kind='activate', control='Verify', ok=False)]
    return [edge, cold, rejected, *refusals]


def _snapshots(path: Path) -> dict[str, str]:
    """Fingerprint both layers of persisted learning."""
    names = ('memory/memory.json', 'rules.json')
    return {name: sha256((path / name).read_bytes()).hexdigest() for name in names}


def _worker(path: Path) -> None:
    """Reload the Store and rules without teaching in the verification process."""
    snapshots = _snapshots(path)
    rules = json.loads((path / 'rules.json').read_text(encoding='utf-8'))
    primary, alternate = (GuardRule(**rules[name]) for name in ('primary', 'alternate'))
    store = Store(path / 'memory')
    try:
        trials = [_trial(path, store.load(), case, primary) for case in HELD_OUT]
        alternative = _trial(path, store.load(), ALTERNATE, alternate)
        controls = _controls(path, store, primary, alternate)
    finally:
        store.close()
    _write_json(path / 'worker.json', dict(pid=os.getpid(), snapshots=snapshots, trials=trials,
                alternate=alternative, controls=controls))


def run(output: Path) -> tuple[Path, dict]:
    """Train in this process, launch a verification worker and record the full result."""
    path = output.resolve() / f'run-{uuid4().hex}'
    path.mkdir(parents=True)
    primary = learn_guard(DEMO.source, DEMO_AFTER, DEMO.name)
    alternate = learn_guard(DEMO.source, ALTERNATE_DEMO_AFTER, DEMO.name)
    engine = StateEngine()
    teaching = teach_episode(engine, primary)
    store = Store(path / 'memory')
    try:
        store.save(engine)
    finally:
        store.close()
    _write_json(path / 'rules.json', dict(primary=asdict(primary), alternate=asdict(alternate)))
    demo = path / DEMO.key
    demo.mkdir()
    (demo / 'before.py').write_text(DEMO.source, encoding='utf-8')
    (demo / 'after.py').write_text(DEMO_AFTER, encoding='utf-8')
    snapshots = _snapshots(path)
    subprocess.run([sys.executable, '-B', '-m', __package__, '--worker', str(path)], check=True, timeout=30)
    result = json.loads((path / 'worker.json').read_text(encoding='utf-8'))
    rows = result['trials'] + result['controls'] + [result['alternate']]
    teaching.update(primary_rule=asdict(primary), alternate_rule=asdict(alternate))
    result.update(schema=SCHEMA, teaching_pid=os.getpid(), teaching=teaching, llm_calls=0,
                  fresh_process=result['pid'] != os.getpid(), snapshots_match=snapshots == result['snapshots'] == _snapshots(path))
    result['passed'] = (result['fresh_process'] and result['snapshots_match']
                        and all(row['passed'] and row['runtime_session'] != teaching['runtime_session'] for row in rows))
    _write_json(path / 'report.json', result)
    return path, result


def main() -> int:
    """Print reproducible counts and the evidence path."""
    command = sys.argv[1:2]
    if command == ['synthesize']:
        from .synthesis.cli import synthesize
        return synthesize(sys.argv[2:])
    if command == ['synthesize-learn']:
        from .synthesis.cli import learn
        return learn(sys.argv[2:])
    if command == ['synthesis-benchmark']:
        from .synthesis.benchmark import main as benchmark
        return benchmark(sys.argv[2:])
    if command == ['calculator']:
        from .calculator.cli import main as calculator
        return calculator(sys.argv[2:])
    if command == ['calculator-benchmark']:
        from .calculator.cli import benchmark as calculator_benchmark
        return calculator_benchmark(sys.argv[2:])
    if command == ['reconcile']:
        from .reconcile.cli import main as reconcile
        return reconcile(sys.argv[2:])
    if command == ['reconcile-benchmark']:
        from .reconcile.cli import benchmark as reconcile_benchmark
        return reconcile_benchmark(sys.argv[2:])
    if command == ['catalog']:
        from .catalog.cli import main as catalog
        return catalog(sys.argv[2:])
    if command == ['catalog-benchmark']:
        from .catalog.benchmark import main as catalog_benchmark
        return catalog_benchmark(sys.argv[2:])
    parser = argparse.ArgumentParser(description=__doc__,
                                     epilog='Use synthesize, synthesize-learn, synthesis-benchmark, calculator, '
                                            'calculator-benchmark, reconcile, reconcile-benchmark, catalog, '
                                            'or catalog-benchmark with --help.')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--worker', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        _worker(args.worker)
        return 0
    path, result = run(args.output)
    summary = {key: f"{sum(row['passed'] for row in result[key])}/{len(result[key])}"
               for key in ('trials', 'controls')}
    print(json.dumps(dict(passed=result['passed'], **summary, alternate=result['alternate']['passed'],
                          report=str(path / 'report.json')), ensure_ascii=True))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
