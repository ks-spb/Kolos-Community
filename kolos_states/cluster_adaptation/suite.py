"""Freeze an explicit procedure change, then compare before/after and retention."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from datetime import datetime, timezone

from ..cluster_replay.controllers import teach
from ..cluster_replay.corpus import digest, save, split
from ..cluster_replay.isolation import offline_host
from ..cluster_replay.model import Model
from ..cluster_replay.suite import source_hashes as original_sources
from . import model_trial, report
from .controllers import NEW_QUERY, teach_revision, trial
from .world import VARIANTS, NEW_FAULTS, variants

PHASES = ('frozen_v2', 'adapted_v2', 'retention_v1')


def source_hashes() -> dict:
    """Pin new modules plus the unchanged original replay and production learner."""
    root = Path(__file__).resolve().parents[1]
    files = list((root / 'cluster_adaptation').glob('*.py')) + [root / 'cluster_adaptation/skill-v2.md']
    return {**original_sources(), **{str(p.relative_to(root.parent)).replace('\\', '/'):
            hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}}


def protocol(corpus: dict, teaching: dict, heldout: list[dict], with_model: bool) -> dict:
    """Commit the split, phases and allowed adaptation before any held-out inference."""
    return dict(version=1, corpus_hash=digest(corpus), teaching_case=teaching['id'],
        heldout_cases=[c['id'] for c in heldout], phases=list(PHASES),
        selectors=['script', 'kolos'] + (['model_skill'] if with_model else []),
        variants=list(VARIANTS), restoration_only_faults=list(NEW_FAULTS),
        change='For restoration only, review the exact prepared preview before Save; exclusion stays v1',
        frozen='Original script, memory and skill are run once without new instructions on the changed form',
        adaptation=dict(script='One explicitly inserted restoration-only operation',
            kolos='One full revised nine-step episode under a new command; preserve original command',
            model='One appended v2 instruction; no case-specific examples or automatic response repair'),
        retention='Adapted controllers also run old v1 tasks; new process reloads the revised Kolos memory',
        model='gpt-6.1-sol, inference-only Hermes provider SDK, temperature 0, one batched plan per trial',
        privacy='Base anonymizer; only demo aliases, roles and boolean/status values leave the host',
        isolation='Host socket connections denied, no business connectors, text-only worker tools=[]',
        scope='Same 5 historical held-out contracts as before; 4 restorations from 3 products and 1 exclusion',
        caveat='Synthetic procedure change; human authoring costs are not inferred from machine teaching time')


def run(output: Path, corpus_path: Path, with_model: bool, install: Path | None, *,
        teaching_product_id: int | None = None) -> dict:
    """Enforce an offline host; write a fresh experiment directory only."""
    with offline_host():
        return _run(output, corpus_path, with_model, install, teaching_product_id=teaching_product_id)


def _run(output: Path, corpus_path: Path, with_model: bool, install: Path | None, *,
        teaching_product_id: int | None = None) -> dict:
    """Prepare all adaptation artifacts before accessing held-out cases."""
    if with_model and install is None:
        raise ValueError('Supply an inference installation when enabling the model')
    if (output / 'protocol.json').exists():
        raise FileExistsError('Use a fresh output directory')
    output.mkdir(parents=True, exist_ok=True)
    corpus = json.loads(corpus_path.read_text(encoding='utf-8'))
    teaching, heldout = split(corpus, teaching_product_id=teaching_product_id)
    data = dict(protocol=protocol(corpus, teaching, heldout, with_model), sources=source_hashes(),
                started_utc=datetime.now(timezone.utc).isoformat(), python=platform.python_version(), rows=[])
    save(output / 'corpus.json', corpus)
    save(output / 'heldout.json', heldout)
    save(output / 'protocol.json', data['protocol'])
    original, old_cost = teach(teaching)
    revised, new_cost = teach_revision(original, teaching)
    data['adaptation'] = dict(original_teaching=old_cost, kolos=new_cost,
        script=dict(inserted_operations=1, human_effort_measured=False),
        model=dict(added_skill_chars=len(Path(__file__).with_name('skill-v2.md').read_text(encoding='utf-8')),
                   human_effort_measured=False))
    save(output / 'learned-v1.json', original)
    save(output / 'learned-v2.json', revised)
    _phases(data, output, heldout, original, revised, with_model, install)
    data['restart'] = _restart(output, revised)
    data['lesion'] = _lesion(heldout, revised)
    if data['sources'] != source_hashes():
        raise RuntimeError('Source changed during experiment')
    data.update(summary=report.build(data), finished_utc=datetime.now(timezone.utc).isoformat())
    save(output / 'results.json', data)
    save(output / 'summary.json', data['summary'])
    (output / 'report.md').write_text(report.markdown(data), encoding='utf-8')
    return data


def _phases(data: dict, output: Path, cases: list[dict], original: dict, revised: dict,
            with_model: bool, install: Path | None) -> None:
    """Reuse one inference client, but switch skills only at the preregistered boundary."""
    model = Model(output, install) if with_model else None
    old_skill = model.skill if model else ''
    if model:
        data['model_startup_ns'] = model.startup_ns
    try:
        for phase in PHASES:
            adapted, revision = phase != 'frozen_v2', 1 if phase == 'retention_v1' else 2
            learned = revised if adapted else original
            if model:
                model.skill = old_skill + (Path(__file__).with_name('skill-v2.md').read_text(encoding='utf-8') if adapted else '')
            for index, case in enumerate(cases):
                faults = variants(case) if phase == 'adapted_v2' else ('clean',)
                for variant in faults:
                    _paired(data, output, case, variant, learned, adapted, revision, index, phase, model)
                print(f'{phase} {index+1}/{len(cases)} {case["id"][:10]}: complete', flush=True)
    finally:
        if model:
            model.close()


def _paired(data: dict, output: Path, case: dict, variant: str, learned: dict, adapted: bool,
            revision: int, layout: int, phase: str, model: Model | None) -> None:
    """All arms use the same world contract, with rotated execution order."""
    selectors = data['protocol']['selectors']
    offset = layout % len(selectors)
    for selector in selectors[offset:] + selectors[:offset]:
        if selector == 'model_skill':
            row, envelope = model_trial.run(model, case, variant, learned, adapted, revision, layout + 1, phase)
            save(output / f'model-{phase}-{case["id"][:10]}-{variant}.json', envelope)
        else:
            row = trial(case, variant, selector, learned, adapted, revision, layout + 1)
            row.update(llm_calls=0, input_tokens=0, output_tokens=0, cache_read_tokens=0, elapsed_ns=row['execute_ns'])
        row['phase'] = phase
        data['rows'].append(row)
    save(output / 'checkpoint.json', data)


def _restart(output: Path, learned: dict) -> dict:
    """A new process must use exactly the saved revised graph, not its parent's transients."""
    subprocess.run([sys.executable, '-B', '-m', 'kolos_states.cluster_adaptation.restart', str(output.resolve())],
                   check=True, capture_output=True, timeout=45)
    result = json.loads((output / 'restart.json').read_text(encoding='utf-8'))
    result.update(different_pid=result['pid'] != os.getpid(), graph_equal=result['learned_hash'] == digest(learned))
    return result


def _lesion(cases: list[dict], learned: dict) -> dict:
    """Disable the new command path; the old exclusion command must still work."""
    damaged = copy.deepcopy(learned)
    command = next(c for c in damaged['model']['episodeCommands'] if c['query'] == NEW_QUERY)
    edge = next(e for e in damaged['model']['memory']['edges'] if e['from'] == command['node'] and e['kind'] == 'episode_next')
    edge['weight'] = 0
    rows = [trial(c, 'clean', 'kolos', damaged, True) for c in cases]
    return dict(rows=rows, restorations_blocked=sum(r['restoration'] and r['status'] == 'blocked' for r in rows),
                exclusions_completed=sum(not r['restoration'] and r['completed'] for r in rows))
