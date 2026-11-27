"""Freeze a local corpus and protocol before comparing three controller strategies."""
from __future__ import annotations

import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter_ns

from . import report
from .controllers import teach, trial
from .corpus import digest, extract, save, split
from .model import Model
from .isolation import offline_host
from .world import VARIANTS, World


def source_hashes() -> dict:
    """Pin both the harness and production learner; preserve provenance on replay."""
    root = Path(__file__).resolve().parents[1]
    paths = list((root / 'cluster_replay').glob('*.py')) + [root / 'cluster_replay/skill.md']
    paths += [root / name for name in ('episodes.py', 'episode_browser.py', 'core.py', 'protocol.py')]
    return {str(p.relative_to(root.parent)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)}


def protocol(corpus: dict, teaching: dict, heldout: list[dict], model: bool) -> dict:
    """Record scope, development split and acceptance criteria before executing cases."""
    return dict(version=1, corpus_hash=digest(corpus), teaching_case=teaching['id'],
        heldout_cases=[c['id'] for c in heldout], variants=list(VARIANTS),
        reconstruction='Historical verified before/after contracts; semantic local host, not recorded full DOM replay',
        controls=['script', 'kolos'] + (['model_skill'] if model else []),
        model='openai-codex/gpt-6.1-sol; inference-only installed Hermes provider SDK; no agent tools',
        model_policy='One batched plan per case, max 16 local operations, temperature 0; no retry on invalid output',
        privacy='Only demo identifiers and boolean state transitions leave the machine; no source business strings',
        oracle='Clean: verified+recorded; invalid conditions/readback: blocked; lost receipt: pending with no retry',
        targets=dict(clean_completion=1, correct_fault_outcome=1, false_success=0, repeated_save=0),
        teaching='One reconstructed restoration demonstrated through BrowserEpisodeBridge; no held-out teaching',
        tokens='Provider-reported counts only; cached input is a subset of input; no price assumptions',
        execution='Host sockets denied; text-only worker has no tools and allows only OpenAI provider hosts.')


def model_trial(model: Model, case: dict, variant: str, learned: dict, layout: int) -> tuple[dict, dict]:
    """Keep bad JSON and provider failures visible, never replace them with a scripted answer."""
    start = perf_counter_ns()
    envelope = model.plan(World(case, variant, layout), case['id'] + ':' + variant)
    response = envelope['response']
    if not response.get('ok'):
        return _model_failure(case, variant, response, start), envelope
    try:
        plan = json.loads(response['text'])
        row = trial(case, variant, 'model_skill', learned, plan, layout)
    except (ValueError, KeyError, TypeError):
        row = trial(case, variant, 'model_skill', learned, dict(operations=[], outcome='blocked'), layout)
        row.update(correct_outcome=False, protocol_error=True, reason='invalid_model_json')
    row.update(llm_calls=1, input_tokens=response['input_tokens'], output_tokens=response['output_tokens'],
               cache_read_tokens=response['cache_read_tokens'], infer_ns=response['infer_ns'],
               elapsed_ns=perf_counter_ns() - start, model=response['model'])
    return row, envelope


def _model_failure(case: dict, variant: str, response: dict, start: int) -> dict:
    """Unavailable inference is missing evidence, not a free successful operation."""
    row = trial(case, variant, 'model_skill', {}, dict(operations=[], outcome='blocked'))
    row.update(status='unavailable', correct_outcome=False, reason=response.get('error_type', 'provider_error'),
               llm_calls=1, input_tokens=None, output_tokens=None, cache_read_tokens=None,
               elapsed_ns=perf_counter_ns() - start)
    return row


def run(output: Path, source: Path | None, with_model: bool = False,
        install: Path | None = None, frozen_corpus: Path | None = None, *,
        teaching_product_id: int | None = None) -> dict:
    """Enforce an offline host even when imported directly instead of using the CLI."""
    with offline_host():
        return _run(output, source, with_model, install, frozen_corpus,
                    teaching_product_id=teaching_product_id)


def _run(output: Path, source: Path | None, with_model: bool = False,
        install: Path | None = None, frozen_corpus: Path | None = None, *,
        teaching_product_id: int | None = None) -> dict:
    """Write only a fresh experiment directory; the business source is read once."""
    if frozen_corpus is None and source is None:
        raise ValueError('Supply a source or frozen corpus')
    if with_model and install is None:
        raise ValueError('Supply an inference installation when enabling the model')
    if (output / 'protocol.json').exists():
        raise FileExistsError('Use a fresh output directory')
    output.mkdir(parents=True, exist_ok=True)
    corpus = json.loads(frozen_corpus.read_text(encoding='utf-8')) if frozen_corpus else extract(source)
    teaching, heldout = split(corpus, teaching_product_id=teaching_product_id)
    data = dict(protocol=protocol(corpus, teaching, heldout, with_model), sources=source_hashes(),
                started_utc=datetime.now(timezone.utc).isoformat(), python=platform.python_version(), rows=[])
    save(output / 'corpus.json', corpus)
    save(output / 'protocol.json', data['protocol'])
    learned, data['teaching'] = teach(teaching)
    save(output / 'learned.json', learned)
    model = Model(output, install) if with_model else None
    if model:
        data['model_startup_ns'] = model.startup_ns
    try:
        _trials(data, heldout, learned, output, model)
    finally:
        if model:
            model.close()
    if data['sources'] != source_hashes():
        raise RuntimeError('Source changed during the experiment')
    data.update(summary=report.build(data), finished_utc=datetime.now(timezone.utc).isoformat())
    save(output / 'results.json', data)
    save(output / 'summary.json', data['summary'])
    (output / 'report.md').write_text(report.markdown(data), encoding='utf-8')
    return data


def _trials(data: dict, cases: list[dict], learned: dict, output: Path, model: Model | None) -> None:
    """All arms see the same task/fault; fixed rotations reduce execution-order bias."""
    for index, case in enumerate(cases):
        for variant in VARIANTS:
            selectors = ['script', 'kolos'] + (['model_skill'] if model else [])
            selectors = selectors[index % len(selectors):] + selectors[:index % len(selectors)]
            for selector in selectors:
                if selector == 'model_skill':
                    row, envelope = model_trial(model, case, variant, learned, index + 1)
                    save(output / f'model-{case["id"][:10]}-{variant}.json', envelope)
                else:
                    row = trial(case, variant, selector, learned, layout=index + 1)
                    row.update(llm_calls=0, input_tokens=0, output_tokens=0, cache_read_tokens=0,
                               elapsed_ns=row['execute_ns'])
                data['rows'].append(row)
            save(output / 'checkpoint.json', data)
            print(f'{index+1}/{len(cases)} {case["id"][:10]} {variant}: complete', flush=True)
