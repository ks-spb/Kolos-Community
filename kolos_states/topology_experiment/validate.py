"""Validate paired completeness, source provenance and independent receipt replay."""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

from ..simulator import apply, observe
from . import oracle
from .report import build_summary
from .suite import source_hashes
from .world import make_lab


def _trial(row: dict, lab: object) -> None:
    """Rebuild actual effects and independently check the declared terminal outcome."""
    world = lab.at()
    identifiers = []
    for action in row['actions']:
        raw = action['receipt']
        identifiers.append(raw['id'])
        assert raw['before'] == observe(world)
        replay = apply(world, dict(id=raw['id'], action=raw['action']))
        assert replay == raw
        regret = oracle.click_regret(lab, action['goal'], raw['action'])
        assert action['off_goal'] == (regret > 1e-7)
    assert len(identifiers) == len(set(identifiers)), 'Repeated physical effect ID'
    static = row['scenario'] == 'static'
    assert row['changed'] == (not static), 'Missing requested intervention'
    target = lab.goals[0] if static or row['scenario'] == 'pending_click' else (0 if row['scenario'] == 'after_click' else lab.goals[1])
    origin = 0 if static else lab.labels.index(row['changes'][0]['delivered_surface'])
    reachable = origin in oracle.costs(lab, target)
    actual = world['surface'] == lab.labels[target]
    assert row['reachable'] == reachable
    assert row['success'] == (reachable and row['status'] == 'complete' and actual)
    assert row['false_success'] == (row['status'] == 'complete' and not actual)
    after = [a for a in row['actions'] if a['after_change'] or static]
    safe = not reachable and row['status'] == 'blocked' and not after
    assert row['correct'] == (row['success'] or safe)
    assert row['off_goal_after_change'] == sum(a['off_goal'] for a in after)
    assert row['memory_before'] == row['memory_after']


def _change(row: dict) -> None:
    """Audit delivery timing, cleared state and baseline cache invalidation."""
    if row['scenario'] == 'static':
        assert not row['changes']
    else:
        assert len(row['changes']) == 1
        change = row['changes'][0]
        assert change['activation_cleared'] and change['old_episode_cleared']
        assert change['deliver_tick'] >= change['request_tick']
        prefix = row['actions'][:change['delivered_action_index']]
        assert sum(a['receipt']['action']['kind'] == 'click' for a in prefix) == (0 if row['scenario'] == 'during_spread' else 1)
        if row['scenario'] == 'pending_click':
            assert change['pending']
            assert change['deliver_tick'] == change['request_tick'] + 1
            assert change['delivered_action_index'] == change['action_index'] + 1
        else:
            assert not change['pending']
        assert all(a['after_change'] == (i >= change['delivered_action_index']) for i, a in enumerate(row['actions']))
    if row['selector'] == 'dijkstra_cached':
        assert row['builds'] == (1 if row['scenario'] == 'static' else 2)


def validate(data: dict) -> dict:
    """Reject incomplete cells, unpaired memories, stale sources and inconsistent traces."""
    p = data['protocol']
    assert data['sources'] == source_hashes(), 'Sources changed after execution'
    expected = set(itertools.product(p['families'], p['seeds'], p['selectors'], p['scenarios']))
    keys = [(r['family'], r['seed'], r['selector'], r['scenario']) for r in data['trials']]
    assert len(keys) == len(expected) and set(keys) == expected
    assert len(data['worlds']) == len(p['families']) * len(p['seeds'])
    paired: dict = {}
    for row in data['trials']:
        key = (row['family'], row['seed'])
        if key not in paired:
            paired[key] = (row['memory_before'], make_lab(*key))
        before, lab = paired[key]
        assert row['memory_before'] == before, 'Unpaired starting memory'
        _trial(row, lab)
        _change(row)
    assert data['summary'] == build_summary(data['trials'])
    return dict(trials=len(keys), graphs=len(paired), source_hashes_match=True, paired_memories=True,
                receipt_replays=sum(len(r['actions']) for r in data['trials']),
                goal_changes=sum(r['changed'] for r in data['trials']), frozen_memory=True)


def main() -> None:
    """Save an explicit validation artifact next to the complete run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path('tests/desktop-output/topology-20261110'))
    args = parser.parse_args()
    data = json.loads((args.directory / 'results.json').read_text(encoding='utf-8'))
    report = validate(data)
    envelope = json.loads((args.directory / 'protocol.json').read_text(encoding='utf-8'))
    assert envelope == dict(protocol=data['protocol'], sources=data['sources'])
    (args.directory / 'validation.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
