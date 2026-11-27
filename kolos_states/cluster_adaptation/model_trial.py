"""Measure actual model output using either the frozen or revised skill."""
from __future__ import annotations

import json
from time import perf_counter_ns

from ..cluster_replay.model import Model
from .controllers import trial
from .world import World


def run(model: Model, case: dict, variant: str, learned: dict, adapted: bool,
        revision: int, layout: int, phase: str) -> tuple[dict, dict]:
    """One plan per case; invalid responses remain failures and never trigger scripted repair."""
    start = perf_counter_ns()
    envelope = model.plan(World(case, variant, layout, revision), phase + ':' + case['id'] + ':' + variant)
    response = envelope['response']
    if not response.get('ok'):
        row = trial(case, variant, 'model_skill', learned, adapted, revision, layout,
                    dict(operations=[], outcome='blocked'))
        row.update(status='unavailable', correct_outcome=False, reason=response.get('error_type'),
                   llm_calls=1, input_tokens=None, output_tokens=None, cache_read_tokens=None)
    else:
        try:
            plan = json.loads(response['text'])
            row = trial(case, variant, 'model_skill', learned, adapted, revision, layout, plan)
        except (ValueError, TypeError):
            row = trial(case, variant, 'model_skill', learned, adapted, revision, layout,
                        dict(operations=[], outcome='blocked'))
            row.update(correct_outcome=False, protocol_error=True, reason='invalid_model_json')
        row.update(llm_calls=1, input_tokens=response['input_tokens'], output_tokens=response['output_tokens'],
                   cache_read_tokens=response['cache_read_tokens'], infer_ns=response['infer_ns'], model=response['model'])
    row['elapsed_ns'] = perf_counter_ns() - start
    return row, envelope
