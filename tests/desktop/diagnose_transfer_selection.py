"""Explain the first desk decision on a fixed learned snapshot; no memory writes."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from unittest.mock import patch

from kolos_states import dynamics
from kolos_states.backward import backward_wave
from kolos_states.storage import Store
from kolos_states.transfer import runner
from kolos_states.transfer.world import make_lab


def compact_candidates(model: dict, candidates: list[dict], names: dict) -> list[dict]:
    """Show only the two genuine desk routes, with numeric source contributions."""
    labels = {'CLICK ' + names['fast']: 'fast', 'CLICK ' + names['panel']: 'detour'}
    return [dict(transition=c['id'], route=labels[c['label']], score=c['a'], sensory=c['sensory'],
                 history=c['history'], inhibition=c['inhibition'], upper=c.get('upper'))
            for c in candidates if c['label'] in labels]


def settled_candidates(model: dict, goal: dict, names: dict) -> list[dict]:
    """Continue only reverse propagation on the same observation, without actions."""
    subject = copy.deepcopy(model)
    cfg = subject['intent']['config']
    nodes = [n for n in subject['memory']['nodes'] if n['kind'] in ('state', 'transition')]
    activity = subject['goalActivation']
    for _ in range(100):
        activity = backward_wave(subject['memory'], nodes, activity, cfg, [])
        dynamics.seed_demand(subject, activity, ['focus:' + goal['focus']])
    # Route selection has just marked the winner refractory; remove that marker
    # to compare evidence scores at the original decision, not after its execution.
    subject['refractory'] = {}
    candidates = dynamics.transition_candidates(subject, activity, cfg, cfg['routeThreshold'])
    return compact_candidates(subject, candidates, names)


def diagnose(path: Path, seed: int) -> dict:
    """Capture the first native decision and let each controller use the same graph."""
    lab = make_lab(seed)
    store = Store(path)
    try:
        engine = store.load()
    finally:
        store.close()
    engine.configure(plasticity=0)
    captured = {}
    original = runner.NATIVE_ROUTE

    def trace(model: dict, goal: dict, event: dict, rehearsal: bool = False) -> dict:
        """Observe selection without changing its inputs or returned result."""
        result = original(model, goal, event, rehearsal)
        candidates = compact_candidates(model, event.get('candidates', []), lab.objects)
        if not captured and result['kind'] == 'route' and any(c['sensory'] > .7 for c in candidates):
            captured.update(at_selection=candidates, after_100_waves=settled_candidates(model, goal, lab.objects))
        return result

    spec = dict(case=0, start='overlay', value='7123')
    with patch.object(runner, 'NATIVE_ROUTE', trace):
        native = runner.run_case(copy.deepcopy(engine), lab, spec, 'native', changed=True)
    planner = runner.run_case(copy.deepcopy(engine), lab, spec, 'planner', changed=True)
    return dict(seed=seed, memory_hash=runner.fingerprint(engine), **captured,
                native_wrong_fast=native['wrong_fast'], planner_wrong_fast=planner['wrong_fast'],
                native_success=native['success'], planner_success=planner['success'])


def main() -> None:
    """Read the stored native-trained graph and print a reproducible diagnostic."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    text = json.dumps(diagnose(args.snapshot, args.seed), indent=2)
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
