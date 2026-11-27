"""Teach a repair policy and compare it with fixed search in a fresh process."""
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

from ...core import StateEngine
from ...protocol import persistent_graph
from ...storage import Store
from ..fixtures import DEMO, DEMO_AFTER
from ..transform import GuardRule, learn_guard
from .cases import CONTROLS, HELD_OUT, TEACHING
from .compose import MAX_EDITS
from .composition_experiment import DEFAULT_BUDGET as COMPOSE_BUDGET, compare_composed
from .patches import candidates
from .policy import learned_order, recent_order, teach, trace_order
from .search import score, solve

DEFAULT_OUTPUT = Path('tests/desktop-output/programming-lab/repair')
DEFAULT_BUDGET = 3


def _write(path: Path, payload: dict) -> None:
    """Write portable evidence in readable JSON."""
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def _snapshot(path: Path) -> dict[str, str]:
    """Fingerprint both inputs used after the restart."""
    names = ('memory/memory.json', 'rule.json')
    return {name: sha256((path / name).read_bytes()).hexdigest() for name in names}


def _compare(path: Path, engine: StateEngine, rule: GuardRule, budget: int) -> dict:
    """Give every policy the same source, visible tests, candidate pool and budget."""
    policies = {'kolos': learned_order(engine), 'enumeration': trace_order, 'trace-recency': recent_order}
    no_memory = learned_order(StateEngine())
    results = {}
    for task in HELD_OUT + CONTROLS:
        folder = path / task.name
        folder.mkdir()
        (folder / 'before.py').write_text(task.source, encoding='utf-8', newline='')
        patches = candidates(task.source, rule)
        trials = {}
        for label, rank in policies.items():
            search = solve(task.source, task.visible, patches, rank, budget)
            row, verified = score(task, search)
            if verified is not None:
                (folder / f'{label}.after.py').write_text(verified, encoding='utf-8', newline='')
            trials[label] = row
        cold = solve(task.source, task.visible, patches, no_memory, budget)
        results[task.name] = dict(expected=task.outcome, candidate_count=len(patches), trials=trials,
                                  cold_matches_enumeration=score(task, cold)[0] == trials['enumeration'])
    return results


def _control_passed(control: dict, label: str, budget: int) -> bool:
    """A one-attempt run may never submit the decoy used by the hidden-test control."""
    trial = control['trials'][label]
    status = trial['status']
    expected = control['expected']
    if expected == 'solved':
        if budget == 1 and status == 'no-solution':
            return len(trial['attempts']) == budget
        return status == 'solved' and len(trial['edits']) == 1
    return status == expected or (budget == 1 and expected == 'hidden-failed' and status == 'no-solution')


def _summary(results: dict, budget: int) -> dict:
    """Count verified tasks and attempts without averaging only successful runs."""
    eligible = [row['trials'] for row in results.values() if row.get('primary', row['expected'] == 'solved')]
    controls = [row for row in results.values() if not row.get('primary', row['expected'] == 'solved')]
    summary = {}
    for label in eligible[0]:
        rows = [task[label] for task in eligible]
        solved = [row for row in rows if row['status'] == 'solved']
        summary[label] = dict(solved=len(solved), total=len(rows),
                              first_attempt=sum(len(row['attempts']) == 1 for row in solved),
                              attempts=sum(len(row['attempts']) for row in rows),
                              controls_passed=sum(_control_passed(c, label, budget) for c in controls),
                              controls_total=len(controls))
    return summary


def _worker(path: Path, budget: int, composition: bool) -> None:
    """Reload the native graph and evaluate only on the held-out tasks and controls."""
    snapshot = _snapshot(path)
    rule = GuardRule(**json.loads((path / 'rule.json').read_text(encoding='utf-8')))
    store = Store(path / 'memory')
    try:
        engine = store.load()
        graph = persistent_graph(engine.model['memory'])
        compare = compare_composed if composition else _compare
        results = compare(path, engine, rule, budget)
        frozen = graph == persistent_graph(engine.model['memory'])
    finally:
        store.close()
    _write(path / 'worker.json', dict(pid=os.getpid(), frozen=frozen, snapshot=snapshot,
                                     results=results, summary=_summary(results, budget)))


def run(output: Path, budget: int | None = None, *, composition: bool = False) -> tuple[Path, dict]:
    """Train once, restore in a new interpreter, and save a reproducible report."""
    if budget is None:
        budget = COMPOSE_BUDGET if composition else DEFAULT_BUDGET
    path = output.resolve() / f'run-{uuid4().hex}'
    path.mkdir(parents=True)
    engine = StateEngine()
    rule = learn_guard(DEMO.source, DEMO_AFTER, DEMO.name)
    teaching = teach(engine, TEACHING, rule)
    store = Store(path / 'memory')
    try:
        store.save(engine)
    finally:
        store.close()
    _write(path / 'rule.json', asdict(rule))
    snapshot = _snapshot(path)
    argv = [sys.executable, '-B', '-m', __package__, '--worker', str(path), '--budget', str(budget)]
    if composition:
        argv.append('--compose')
    subprocess.run(argv, check=True, timeout=30)
    report = json.loads((path / 'worker.json').read_text(encoding='utf-8'))
    fresh = os.getpid() != report['pid']
    intact = snapshot == report['snapshot'] == _snapshot(path)
    controls = all(row['controls_passed'] == row['controls_total'] for row in report['summary'].values())
    confirmation = 'oracle_passed' if composition else 'cold_matches_enumeration'
    verified = all(row[confirmation] for row in report['results'].values())
    report.update(schema='kolos-programming-repair/1', budget=budget, teaching=teaching, llm_calls=0,
                  fresh_process=fresh, snapshots_match=intact, training_pid=os.getpid(),
                  passed=fresh and intact and report['frozen'] and verified and controls)
    if composition:
        report.update(schema='kolos-programming-composition/1', max_edits=MAX_EDITS)
    _write(path / 'report.json', report)
    return path, report


def main() -> int:
    """Run the repair experiment and print verification counts and evidence location."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--budget', type=int)
    parser.add_argument('--compose', action='store_true', help='search multiple edits using partial test results')
    parser.add_argument('--worker', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    budget = args.budget if args.budget is not None else (COMPOSE_BUDGET if args.compose else DEFAULT_BUDGET)
    if budget < 1:
        parser.error('--budget must be positive')
    if args.worker:
        _worker(args.worker, budget, args.compose)
        return 0
    output = args.output or (DEFAULT_OUTPUT / 'compose' if args.compose else DEFAULT_OUTPUT)
    path, report = run(output, budget, composition=args.compose)
    print(json.dumps(dict(passed=report['passed'], summary=report['summary'], report=str(path / 'report.json'))))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
