"""Verify complete paired evidence and all ten learned symbols in stored snapshots."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from kolos_states.storage import Store
from kolos_states.transfer.runner import fingerprint, run_case
from kolos_states.transfer.suite import source_hashes
from kolos_states.transfer.world import make_lab


def validate_counts(data: dict) -> dict:
    """Reject missing worlds, duplicate trials, altered sources or leaked state."""
    seeds = set(data['protocol']['seeds'])
    expected = {}
    for selector in ('native', 'planner', 'single'):
        expected.update({selector + '_transfer': 5, selector + '_positive': 1})
    for selector in ('native', 'planner'):
        expected.update({selector + '_lesion': 1, selector + '_interference': 5})
        for suffix in ('on', 'off'):
            expected[selector + '_adapt_' + suffix] = 5
            expected[selector + '_post_' + suffix] = 10
        other = 'native' if selector == 'planner' else 'planner'
        expected[selector + '_post_from_' + other] = 10
    if data['protocol']['version'] >= 3:
        expected['early_post_from_native'] = 10
    assert data['sources'] == source_hashes(), 'Source changed after execution'
    assert set(data['groups']) == set(expected)
    for key, count in expected.items():
        rows = data['groups'][key]
        assert len(rows) == count * len(seeds), key
        assert len({(r['seed'], r['case']) for r in rows}) == len(rows), key
        assert {r['seed'] for r in rows} == seeds, key
        assert all(sum(r['seed'] == seed for r in rows) == count for seed in seeds), key
        if '_adapt_on' not in key:
            assert all(r['memory_before'] == r['memory_after'] for r in rows), key
    assert len(data['restarts']) == (7 if data['protocol']['version'] >= 3 else 6) * len(seeds)
    assert all(r['different_pid'] and r['transient_clean'] and r['graph_equal'] for r in data['restarts'])
    return dict(trials=sum(len(rows) for rows in data['groups'].values()),
                restarts=len(data['restarts']), worlds=len(seeds), source_hashes_match=True)


def alphabet_checks(directory: Path) -> list[dict]:
    """Check every learned digit, including six omitted by the shorter 9870 probe."""
    checks = []
    for path in sorted((directory / 'snapshots').glob('*/memory.json')):
        seed = int(path.parent.name.split('-')[0])
        store = Store(path.parent)
        try:
            engine = store.load()
        finally:
            store.close()
        before = fingerprint(engine)
        engine.configure(plasticity=0)
        row = run_case(engine, make_lab(seed), dict(case=0, start='focused', value='0987654321'))
        checks.append(dict(snapshot=path.parent.name, success=row['success'],
                           graph_unchanged=before == fingerprint(engine)))
    return checks


def main() -> None:
    """Write validation evidence beside the original result, without changing it."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, default=Path('tests/desktop-output/transfer-selection-v2'))
    args = parser.parse_args()
    data = json.loads((args.directory / 'results.json').read_text(encoding='utf-8'))
    report = validate_counts(data)
    report['alphabet_checks'] = alphabet_checks(args.directory)
    assert len(report['alphabet_checks']) == report['worlds'] * 4
    assert all(row['success'] and row['graph_unchanged'] for row in report['alphabet_checks'])
    (args.directory / 'validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f"Validated {report['trials']} trials, {report['restarts']} restarts, "
          f"{len(report['alphabet_checks'])} complete-alphabet checks")


if __name__ == '__main__':
    main()
