"""Run the frozen learning curve, archive persistence and score every issued program."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from ...core import StateEngine
from ...ipc import atomic_json
from ..calculator.intent import Clarification
from ..reconcile.cli import MEMORY, SNAPSHOTS, _load, _record, _restore, _snapshot
from ..reconcile.intent import REQUEST as RECONCILE_REQUEST, recognize as reconcile_intent
from ..reconcile.lab import generate as reconcile
from ..retention import measure
from .cli import metadata, policy_of, save_policy
from .corpus import SEED, STAGES, Request, corpora
from .judge import evaluate
from .routing import Policy, Router, Trainer, calibrate, choose_lexicon, keywords

REPORTS = Path('tests/desktop-output/programming-lab/catalog')
CALIBRATION = 'observed-score-v1'


def _jsonl(path: Path, rows: list[dict] | tuple[Request, ...]) -> str:
    """Record all source cases and results while keeping the report compact."""
    digest = sha256()
    with path.open('wb') as stream:
        for row in rows:
            data = row if isinstance(row, dict) else asdict(row)
            line = (json.dumps(data, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')
            stream.write(line)
            digest.update(line)
    return digest.hexdigest()


def _retention(engine: StateEngine, output: Path) -> dict:
    """Run the previous 51 tasks plus both complete CLI judge sets."""
    result = measure(engine, output)
    try:
        intent = reconcile_intent(RECONCILE_REQUEST, engine)
        csv = reconcile(intent, engine, output / 'reconcile.py')
        result['reconcile'] = dict(status=csv['status'], attempts=len(csv['attempts']),
                                   checks_passed=sum(row['passed'] for row in csv['checks']))
    except Clarification:
        result['reconcile'] = dict(status='needs_clarification', attempts=0, checks_passed=0)
    return result


def _signature(result: dict) -> tuple:
    """Compare success and attempts without making elapsed time a retention verdict."""
    return result['tasks'], result['calculator'], result['reconcile']


def _prove_preserved(before: Path, after: Path) -> dict:
    """Check every preexisting native node and edge against the archived trained state."""
    first, last = (json.loads((p / 'memory.json').read_text(encoding='utf-8'))['memory'] for p in (before, after))
    result = {}
    for kind in ('nodes', 'edges'):
        old = first[kind]
        current = {row['id']: row for row in last[kind]}
        result[kind] = dict(before=len(old), after=len(current), retained=sum(current.get(row['id']) == row for row in old))
    return result


def _startup(memory: Path, snapshots: Path, archive: Path, train_hash: str) -> tuple[StateEngine, bytes, dict]:
    """Use the active starting graph or replay the original series without double training."""
    recovered = _restore(memory, snapshots)
    current = (memory / 'memory.json').read_bytes()
    active = _load(memory)
    previous = metadata(active)
    origin = archive / 'stage-0'
    if previous:
        if previous.get('train_sha256') != train_hash or previous.get('lessons') != STAGES[-1]:
            raise ValueError('Активная память содержит другой каталог. Выберите сохранённый исходный снимок.')
        saved = Path(previous['origin']) / 'memory.json'
        _snapshot(origin, saved.read_bytes())
    else:
        _snapshot(origin, current)
    recalibrated = bool(previous) and previous.get('calibration_version') != CALIBRATION
    return _load(origin), current, dict(recovered=recovered, repeated=bool(previous),
                                       recalibrated=recalibrated, origin=str(origin))


def _stage(archive: Path, folder: Path, target: int, trainer: Trainer, lexicon: tuple[str, ...],
           train: tuple[Request, ...], calibration: tuple[Request, ...], train_hash: str) -> tuple[StateEngine, dict]:
    """Teach a disjoint suffix, calibrate on the development split and reload the saved graph."""
    print(f'catalog: checkpoint {target}', file=sys.stderr, flush=True)
    if target == 0:
        snapshot = archive / 'stage-0'
        limits, calibration_result = Policy(), None
    else:
        trainer.learn(train[trainer.total:target])
        limits, calibration_result = calibrate(Router(trainer.engine, Policy(lexicon)), calibration)
        snapshot = archive / ('after' if target == STAGES[-1] else f'stage-{target}')
        save_policy(trainer.engine, limits, lessons=target, train_sha256=train_hash, origin=str(archive / 'stage-0'),
                    calibration_version=CALIBRATION)
        _record(snapshot, trainer.engine)
        atomic_json(folder / f'counts-{target}.json', trainer.counts)
    engine = _load(snapshot)
    return engine, dict(snapshot=str(snapshot), lessons=target, policy=asdict(limits),
                        calibration=calibration_result, bytes=(snapshot / 'memory.json').stat().st_size,
                        nodes=len(engine.model['memory']['nodes']), edges=len(engine.model['memory']['edges']))


def _score(folder: Path, label: str, closed: tuple[Request, ...], pick, builder: StateEngine,
           workers: int) -> tuple[list[dict], dict]:
    """Save per-request outcomes and keep comparisons conditional on the same fixtures."""
    report, metrics = evaluate(closed, pick, builder, folder / label, workers)
    _jsonl(folder / f'{label}.jsonl', report)
    metrics['by_program'] = {kind: sum(row['passed'] and request.expected is not None and request.expected.kind == kind
                                     for request, row in zip(closed, report, strict=True))
                             for kind in sorted({item.expected.kind for item in closed if item.expected is not None})}
    print(f"catalog: {label} {metrics['solved']}/{metrics['total']} executable programs, "
          f"{metrics['python_executions']} Python executions", file=sys.stderr, flush=True)
    return report, metrics


def _restart(folder: Path, snapshot: Path, closed: tuple[Request, ...], rows: list[dict]) -> dict:
    """Exercise the normal public command in one fresh process from the archived policy."""
    request = next((r for r, row in zip(closed, rows, strict=True) if r.expected is not None and row['passed']), None)
    text = request.text if request is not None else 'сделай мне программу-калькулятор'
    output = folder / 'restart.py'
    command = [sys.executable, '-B', '-m', 'kolos_states.programming_lab', 'catalog', '--request', text,
               '--memory', str(snapshot), '--output', str(output)]
    result = subprocess.run(command, capture_output=True, encoding='utf-8', timeout=60)
    data = json.loads(result.stdout) if result.stdout else dict(error=result.stderr.strip())
    expected = asdict(request.expected) if request is not None else {'kind': 'calculator'}
    return dict(passed=result.returncode == 0 and output.is_file() and all(data['spec'][k] == v for k, v in expected.items()),
                request=text, result=data)


def _publish(memory: Path, trained: StateEngine, original: bytes, context: dict) -> bool:
    """On a recalibration, update only routing metadata and retain every live learned weight."""
    if not context['repeated']:
        return _record(memory, trained, expected=original)
    if not context['recalibrated']:
        return False
    active = _load(memory)
    working, replayed = Router(active, policy_of(active)), Router(trained, policy_of(trained))
    if working.weights != replayed.weights:
        return False
    info = {key: value for key, value in metadata(trained).items() if key not in ('scope', 'policy')}
    save_policy(active, replayed.policy, **info)
    return _record(memory, active, expected=original)


def run(output: Path, memory: Path, snapshots: Path, workers: int) -> tuple[Path, dict]:
    """Keep every checkpoint and publish the final validated graph without losing prior experience."""
    identifier = f'catalog-{uuid4().hex}'
    folder, archive = output.resolve() / identifier, snapshots.resolve() / identifier
    folder.mkdir(parents=True)
    train, calibration, closed = corpora()
    hashes = {name: _jsonl(folder / f'{name}.jsonl', rows)
              for name, rows in (('train', train), ('calibration', calibration), ('closed', closed))}
    builder, original, context = _startup(memory.resolve(), snapshots.resolve(), archive, hashes['train'])
    lexicon = choose_lexicon(train[:100])
    trainer = Trainer(_load(archive / 'stage-0'), lexicon)
    stages, prior_signature, last_rows = {}, None, []
    for target in STAGES:
        label = f'lessons-{target}'
        graph, stage = _stage(archive, folder, target, trainer, lexicon, train, calibration, hashes['train'])
        retained = _retention(graph, folder / 'retention' / label)
        signature = _signature(retained)
        if prior_signature is None:
            prior_signature = signature
        retained['same_prior_results'] = signature == prior_signature
        stage['retention'] = retained
        last_rows, stage['metrics'] = _score(folder, label, closed, Router(graph, policy_of(graph)).pick, builder, workers)
        stages[str(target)] = stage
        atomic_json(folder / f'{label}.summary.json', stage)
    controls = {}
    for name, pick in (('empty_graph', Router(StateEngine(), Policy()).pick), ('keywords', keywords)):
        _, controls[name] = _score(folder, name, closed, pick, builder, workers)
    restart = _restart(folder, archive / 'after', closed, last_rows)
    preservation = _prove_preserved(archive / 'stage-0', archive / 'after')
    promoted = restart['passed'] and _publish(memory, graph, original, context)
    needs_publication = not context['repeated'] or context['recalibrated']
    report = dict(schema='kolos-catalog-scale/1', seed=SEED, corpus_hashes=hashes, stages=stages, controls=controls,
                  memory=dict(**context, active=str(memory.resolve()), promoted=promoted, preserved=preservation),
                  restart=restart, checks=dict(closed_requests=len(closed), probes_per_supported_output=2), llm_calls=0,
                  calibration_version=CALIBRATION, passed=restart['passed'] and (promoted or not needs_publication))
    atomic_json(folder / 'report.json', report)
    return folder, report


def main(argv: list[str]) -> int:
    """Run all preregistered checks and print the final learning curve."""
    parser = argparse.ArgumentParser(prog='python -m kolos_states.programming_lab catalog-benchmark')
    parser.add_argument('--memory', type=Path, default=MEMORY)
    parser.add_argument('--snapshots', type=Path, default=SNAPSHOTS)
    parser.add_argument('--output', type=Path, default=REPORTS)
    parser.add_argument('--workers', type=int, default=6)
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error('Число процессов проверки должно быть положительным.')
    try:
        folder, report = run(args.output, args.memory, args.snapshots, args.workers)
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(dict(passed=report['passed'], report=str(folder / 'report.json'),
                          stages={key: row['metrics'] for key, row in report['stages'].items()},
                          controls=report['controls'], active_saved=report['memory']['promoted'])))
    return int(not report['passed'])
