"""Fresh-process persistence probe using the production Store and isolated files."""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path

from ..protocol import observation_key
from ..simulator import observe
from ..storage import Store
from ..core import StateEngine
from .runner import _execute, fingerprint, run_case
from .world import Lab, make_lab


def retention(engine: StateEngine, lab: Lab) -> dict:
    """Replay all old lessons in the original environment with learning disabled."""
    checks = []
    for lesson in lab.lessons:
        subject = copy.deepcopy(engine)
        subject.reset()
        subject.configure(plasticity=0)
        world = copy.deepcopy(lesson['initial'])
        subject.start(lesson['query'], observe(world))
        _execute(subject, world, {})
        expected = lesson['receipts'][-1]['after']
        checks.append(subject.model['status'] == 'complete' and
                      observation_key(observe(world)) == observation_key(expected))
    subject = copy.deepcopy(engine)
    subject.configure(plasticity=0)
    checks.append(run_case(subject, lab, dict(case=8, start='focused', value='9870'))['success'])
    return dict(passed=sum(checks), total=len(checks))


def probe(path: Path, seed: int, selector: str, expected_hash: str) -> dict:
    """Each held-out trial reloads the same snapshot, never the preceding trial."""
    lab = make_lab(seed)
    store = Store(path)
    try:
        restored = store.load()
        actual_hash = fingerprint(restored)
        if actual_hash != expected_hash:
            raise ValueError('Persisted graph differs from the saved graph')
        transient_clean = not restored.model['pending'] and not restored.model.get('intent')
        transient_clean &= all(not n.get(k) for n in restored.model['memory']['nodes']
                               for k in ('inhibition', 'eligibility', 'sensory'))
        rows = []
        for i in range(10):
            subject = store.load()
            subject.configure(plasticity=0)
            spec = dict(case=i, start='overlay', value=str(6000 + (seed * 17 + i) % 1000))
            rows.append(run_case(subject, lab, spec, selector, changed=True))
        return dict(pid=os.getpid(), memory_hash=actual_hash, transient_clean=transient_clean,
                    retention=retention(restored, lab), trials=rows)
    finally:
        store.close()


def main() -> None:
    """Write a compact worker envelope for the parent process to validate."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--path', type=Path, required=True)
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--selector', choices=('native', 'planner', 'early'), required=True)
    parser.add_argument('--hash', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = probe(args.path, args.seed, args.selector, args.hash)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
