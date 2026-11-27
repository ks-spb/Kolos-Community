"""Run held-out transfer, interference, causal lesions and true process restarts."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..storage import Store
from ..core import StateEngine
from .report import build_summary, markdown
from .restart import retention
from .runner import fingerprint, remove_focus_links, run_case
from .world import Lab, cases, make_lab, teach


def protocol(seeds: list[int]) -> dict:
    """Freeze experimental design before executing any held-out world."""
    return dict(version=3, seeds=seeds, development_seed=0, topology_families=1,
                teaching='7 independent transition demonstrations + alphabet exposure',
                transfer_trials_per_world=5, adaptation_trials=5, post_restart_trials=10,
                cross_evaluation='Each learned snapshot also evaluated by the other selector after a fresh process restart',
                transfer_target=.9, false_success_target=0, error_reduction_target=.5,
                controller='native goal runtime; only route_wave replaced for graph-search baseline',
                native_selection='Certify lower winner score > all rival upper scores + 1e-8; same monotone backward operator from 0 and 1; no fixed route margin',
                selection_ablation='Replay pre-fix first-threshold + .04 margin on each native-trained snapshot in a new process, with learning off',
                planner='Dijkstra: maximize discounted product of learned weights; same sensory/motor guards and plasticity; no activation/margin threshold; exclude failed transitions for current attempt',
                reset_policy='Each transfer starts from original memory; adaptation retains graph only; post trials reload a fixed snapshot',
                interpretation='Single-fragment is a weak ablation, not a proxy for Hermes/Grok. No weights tuned on held-out seeds.')


def _add(data: dict, key: str, row: dict) -> None:
    """Keep full per-trial actions and graph fingerprints in the evidence."""
    data['groups'].setdefault(key, []).append(row)


def static_trials(data: dict, lab: Lab, base: StateEngine) -> None:
    """Use paired starting memories for clean transfer and interventions."""
    order = ('native', 'planner', 'single') if lab.seed % 2 == 0 else ('single', 'planner', 'native')
    for selector in order:
        for spec in cases(lab.seed):
            _add(data, selector + '_transfer', run_case(copy.deepcopy(base), lab, spec, selector))
        positive = dict(case=99, start='form', value='3521')
        _add(data, selector + '_positive', run_case(copy.deepcopy(base), lab, positive, selector))
    for selector in ('native', 'planner'):
        subject = copy.deepcopy(base)
        remove_focus_links(subject, lab.field)
        _add(data, selector + '_lesion', run_case(subject, lab, cases(lab.seed)[0], selector))
        subject = copy.deepcopy(base)
        for lesson in lab.extra_lessons:
            subject.learn(lesson)
        for spec in cases(lab.seed):
            _add(data, selector + '_interference', run_case(copy.deepcopy(subject), lab, spec, selector))


def adaptation(data: dict, lab: Lab, base: StateEngine, output: Path, selector: str, plasticity: int) -> None:
    """Adapt for five attempts, then invoke a fresh interpreter with only disk memory."""
    subject = copy.deepcopy(base)
    subject.configure(plasticity=plasticity)
    suffix = 'on' if plasticity else 'off'
    for i in range(5):
        spec = dict(case=i, start='overlay', value=str(4000 + (lab.seed * 13 + i) % 1000))
        _add(data, selector + '_adapt_' + suffix, run_case(subject, lab, spec, selector, changed=True))
    path = output / 'snapshots' / f'{lab.seed}-{selector}-{suffix}'
    store = Store(path)
    try:
        store.save(subject)
    finally:
        store.close()
    expected = fingerprint(subject)
    _restart(data, lab, path, selector, selector, suffix, expected)
    if plasticity:
        other = 'planner' if selector == 'native' else 'native'
        _restart(data, lab, path, selector, other, suffix, expected)
        if selector == 'native':
            _restart(data, lab, path, selector, 'early', suffix, expected)


def _restart(data: dict, lab: Lab, path: Path, trained_by: str, selector: str,
             suffix: str, expected: str) -> None:
    """Test a stored graph with either selector, leaving the snapshot untouched."""
    worker_file = path / ('worker-' + selector + '.json')
    command = [sys.executable, '-B', '-m', 'kolos_states.transfer.restart', '--path', str(path.resolve()),
               '--seed', str(lab.seed), '--selector', selector, '--hash', expected, '--output', str(worker_file.resolve())]
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=90)
    worker = json.loads(worker_file.read_text(encoding='utf-8'))
    for row in worker.pop('trials'):
        key = selector + '_post_' + suffix if trained_by == selector else selector + '_post_from_' + trained_by
        _add(data, key, row)
    worker.update(seed=lab.seed, selector=selector, trained_by=trained_by, plasticity=int(suffix == 'on'),
                  different_pid=worker['pid'] != os.getpid(), graph_equal=worker['memory_hash'] == expected)
    data['restarts'].append(worker)


def source_hashes() -> dict:
    """Pin the benchmark and production implementation used for this execution."""
    root = Path(__file__).resolve().parents[1]
    files = list((root / 'transfer').glob('*.py'))
    files += [root / name for name in ('core.py', 'goal_network.py', 'backward.py', 'route_selection.py', 'dynamics.py',
                                      'experience.py', 'protocol.py', 'simulator.py', 'storage.py', 'memory.py')]
    return {str(path.relative_to(root.parent)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(files)}


def run_suite(output: Path, seeds: list[int]) -> dict:
    """Execute and save results; poor algorithm outcomes never masquerade as harness errors."""
    if not seeds or len(seeds) != len(set(seeds)):
        raise ValueError('Nonempty unique world seeds required')
    if (output / 'protocol.json').exists():
        raise FileExistsError('Use a fresh output directory; previous evidence must not be overwritten')
    output.mkdir(parents=True, exist_ok=True)
    data = dict(protocol=protocol(seeds), groups={}, restarts=[], initial_retention=[],
                started_utc=datetime.now(timezone.utc).isoformat(), python=platform.python_version(),
                platform=platform.platform(), sources=source_hashes())
    (output / 'protocol.json').write_text(json.dumps(data['protocol'], indent=2), encoding='utf-8')
    for seed in seeds:
        lab = make_lab(seed)
        base = teach(lab)
        data['initial_retention'].append(dict(seed=seed, **retention(base, lab)))
        static_trials(data, lab, base)
        order = ('native', 'planner') if seed % 2 == 0 else ('planner', 'native')
        for selector in order:
            for plasticity in (0, 1):
                adaptation(data, lab, base, output, selector, plasticity)
        print(f'world {seed}: complete', flush=True)
    data['summary'] = build_summary(data)
    data['finished_utc'] = datetime.now(timezone.utc).isoformat()
    (output / 'results.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
    (output / 'summary.json').write_text(json.dumps(data['summary'], indent=2), encoding='utf-8')
    (output / 'report.md').write_text(markdown(data), encoding='utf-8')
    return data
