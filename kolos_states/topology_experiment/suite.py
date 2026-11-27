"""Freeze design and source provenance before paired held-out execution."""
from __future__ import annotations

import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

from ..transfer.suite import source_hashes as core_hashes
from .report import build_summary, markdown
from .selectors import LOW_THRESHOLD, SELECTORS
from .topologies import FAMILIES
from .trial import SCENARIOS, Trial
from .world import make_lab, teach


def source_hashes() -> dict:
    """Pin new harness and all production modules already tracked by the transfer experiment."""
    result = core_hashes()
    for path in Path(__file__).parent.glob('*.py'):
        result['kolos_states/topology_experiment/' + path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def protocol(seeds: list[int]) -> dict:
    """Record hypotheses, ablation and negative controls before reading held-out results."""
    return dict(version=1, seeds=seeds, development_seed=0, families=list(FAMILIES), selectors=list(SELECTORS),
                scenarios=list(SCENARIOS), training='One separate MOVE-CHECK-CLICK demonstration per edge; no full route',
                capacity='At most 20 demonstrated edges: production learner limit of 20 lessons; no bypass',
                weights='Controlled initial backward confidence .84..98; equal_diamond .9; same memory for all arms',
                learning='Off throughout; tests composition and goal replacement, not adaptation',
                config='Production defaults, except native_low_threshold routeThreshold=' + str(LOW_THRESHOLD),
                low_threshold_reason='Pure sensory contribution is at most .25; 1e-6 extra still requires goal history',
                dijkstra='Existing weighted Dijkstra criterion, policy cached across fragments; invalidated on goal/graph edits',
                goal_change='Public start_goals API resets current episode and waves for every selector',
                delivery='during_spread: after 2 selector calls, A->B; after_click: initial vertex 2 -> vertex 0 after first acknowledged click; pending_click: initial vertex 2 -> A, queued at click dispatch and delivered after its receipt',
                scoring='Oracle uses private world graph; success and correct unreachable refusal reported separately; unreachable assessed at actual goal delivery location',
                advantage='Higher paired correctness, fewer off-goal/failed actions, or lower latency at equal correctness; report every family and scenario, no tuning on held-out results',
                tie_policy='Both equal-cost routes are valid; native ambiguity is a refusal, not a correctness advantage',
                limits='Same 100 waves, 1800 ticks per goal; host cap 1900 iterations; no OS, LLM or perception-noise test')


def _write(path: Path, data: dict) -> None:
    """Save structured evidence with readable stable newlines."""
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def _world_trials(output: Path, family: str, seed: int) -> tuple[list[dict], dict]:
    """Checkpoint each complete graph so slow or interrupted runs retain evidence."""
    lab = make_lab(family, seed)
    base = teach(lab)
    meta = dict(family=family, seed=seed, vertices=len(lab.labels), edges=lab.edges,
                labels=lab.labels, goals=lab.goals, objects=lab.objects,
                memory_nodes=len(base.model['memory']['nodes']), memory_edges=len(base.model['memory']['edges']))
    rows = []
    order = SELECTORS if seed % 2 == 0 else tuple(reversed(SELECTORS))
    for scenario in SCENARIOS:
        for selector in order:
            rows.append(Trial(base, lab, selector, scenario).run())
    _write(output / 'worlds' / f'{family}-{seed}.json', dict(meta=meta, trials=rows))
    return rows, meta


def run_suite(output: Path, seeds: list[int]) -> dict:
    """Execute a complete paired matrix; failed algorithms remain recorded results."""
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError('Nonempty unique seeds required')
    if (output / 'protocol.json').exists():
        raise FileExistsError('Choose a fresh output directory to preserve previous evidence')
    (output / 'worlds').mkdir(parents=True, exist_ok=True)
    data = dict(protocol=protocol(seeds), sources=source_hashes(), python=platform.python_version(),
                platform=platform.platform(), started_utc=datetime.now(timezone.utc).isoformat(), trials=[], worlds=[])
    _write(output / 'protocol.json', dict(protocol=data['protocol'], sources=data['sources']))
    for family in FAMILIES:
        for seed in seeds:
            rows, meta = _world_trials(output, family, seed)
            data['trials'].extend(rows)
            data['worlds'].append(meta)
            print(f'{family} {seed}: complete', flush=True)
    data['summary'] = build_summary(data['trials'])
    data['finished_utc'] = datetime.now(timezone.utc).isoformat()
    if data['sources'] != source_hashes():
        raise RuntimeError('Source changed while the experiment was running')
    _write(output / 'results.json', data)
    _write(output / 'summary.json', data['summary'])
    (output / 'report.md').write_text(markdown(data['summary']), encoding='utf-8')
    return data
