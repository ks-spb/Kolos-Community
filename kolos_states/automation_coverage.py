"""Teach a bounded coverage check, then use its frozen recipe on observed counts."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from time import monotonic

from .ipc import atomic_json, read_json
from .programming_lab.repair.policy import _activation, _remember
from .programming_lab.synthesis.grammar import Predicate, Recipe, render
from .programming_lab.synthesis.judge import apply, evaluate
from .programming_lab.synthesis.solver import solve, train
from .programming_lab.synthesis.spec import Example, Task
from .protocol import require
from .storage import Store
from .xway_readonly.worker import digest

PROJECT = Path(__file__).resolve().parents[1]
LAB = PROJECT / '.local-data' / 'programming-lab'
SNAPSHOT = LAB / 'snapshots' / 'automation-coverage-v1'
MSK = timezone(timedelta(hours=3))
TASK = Task('coverage_exceptions', 'counts', (
    Example([1, 0, 1, 2], [0, 2]),
    Example([3, 1, 0], [3, 0]),
), (
    Example([], []),
    Example([0, 0, 1, 12], [0, 0, 12]),
    Example([1, 1, 1], []),
    Example([4, 9, 2], [4, 9, 2]),
))


def teach(destination: Path, base: Path) -> dict:
    """Continue the laboratory graph in a separately versioned snapshot."""
    original = read_json(base / 'memory.json')
    engine = Store.restore_snapshot(original)
    _, associations = train((TASK,))
    result = solve(TASK, engine, budget=24, deadline=monotonic() + 10)
    require(result['status'] == 'solved', 'Coverage lesson did not pass its independent checks')
    recipe = result['attempts'][-1]['recipe']
    predicate = recipe['predicate']
    require(recipe['reduce'] == 'filter' and predicate and predicate['column'] is None,
            'Coverage lesson must select individual counts')
    operation = f"synthesis/list/filter/{predicate['op']}"
    feature = f'automation-coverage-v1/{operation}'
    passed, failed = associations.get(operation, (0, 0))
    require(passed > 0, 'Coverage lesson did not verify this operation')
    _remember(engine, feature, passed, failed, exact=True)
    require(_activation(engine, feature) > 0,
            'Coverage recipe is missing learned confirmation')
    destination.mkdir(parents=True, exist_ok=False)
    atomic_json(destination / 'before.json', original)
    store = Store(destination)
    try:
        store.save(engine)
    finally:
        store.close()
    summary = dict(recipe=predicate, feature=feature, checks=len(TASK.checks),
                   training_examples=len(TASK.examples), before_sha256=digest(original))
    atomic_json(destination / 'recipe.json', summary)
    return summary


def exceptions(counts: dict[str, int], snapshot: Path = SNAPSHOT) -> tuple[list[str], str]:
    raw = read_json(snapshot / 'memory.json')
    engine = Store.restore_snapshot(raw)
    metadata = read_json(snapshot / 'recipe.json')
    require(isinstance(metadata, dict), 'Coverage recipe is unavailable')
    predicate = Predicate(**metadata['recipe'])
    feature = f'automation-coverage-v1/synthesis/list/filter/{predicate.op}'
    require(metadata['feature'] == feature and predicate.column is None and _activation(engine, feature) > 0,
            'Coverage recipe has no learned evidence')
    code = render(TASK, Recipe('filter', predicate=predicate))
    require(evaluate(code, TASK.function, TASK.parameter, TASK.checks).passed,
            'Frozen coverage recipe failed its reference cases')
    selected = set(apply(code, TASK.function, TASK.parameter, list(counts.values())))
    return [key for key, value in counts.items() if value in selected], digest(raw)


def identifier(value: object) -> str:
    require((type(value) is int and value > 0) or
            (type(value) is str and 0 < len(value) <= 64 and value.isascii() and value.isalnum()),
            'Invalid source identifier')
    return str(value)


def timezone_stamp(value: str) -> datetime:
    stamp = datetime.fromisoformat(value)
    require(stamp.utcoffset() is not None, 'Source timestamp has no timezone')
    return stamp


def promotion_observation(data: dict, observed: datetime) -> tuple[dict[str, int], dict]:
    """Collect fresh counts and diagnostics before applying a coverage rule."""
    manifest = data['manifest']
    expected = manifest['expected_promotions']
    unique_products = manifest['unique_products']
    require(all(type(n) is int and n >= 0 for n in (expected, unique_products)),
            'Invalid promotion counters')
    counts, stale, failures = Counter(), set(), set()
    collected = manifest['collected']
    require(isinstance(collected, list) and isinstance(manifest['failed'], list), 'Missing manifest rows')
    all_attempted = Counter()
    for row in collected:
        key = identifier(row['promotion_id'])
        all_attempted[key] += 1
        stamp = timezone_stamp(row['observed_at'])
        if stamp.astimezone(MSK).date() == observed.astimezone(MSK).date() and stamp <= observed:
            counts[key] += 1
        else:
            stale.add(key)
    for row in manifest['failed']:
        key = identifier(row['promotion_id'])
        all_attempted[key] += 1
        failures.add(key)

    raw_ids = data.get('expected_ids')
    expected_ids = None if raw_ids is None else {identifier(key) for key in raw_ids}
    if expected_ids is not None:
        require(isinstance(raw_ids, list) and len(raw_ids) == len(expected_ids) == expected,
                'Calendar IDs disagree with the manifest count')
    keys = sorted(expected_ids if expected_ids is not None else all_attempted)
    labels = {key: counts[key] for key in keys}
    unknown_ids = max(expected - len(all_attempted), 0) if expected_ids is None else 0
    extras = (sorted(all_attempted.keys() - expected_ids) if expected_ids is not None else [])
    duplicates = sorted(key for key, count in all_attempted.items() if count > 1)
    facts = dict(expected=expected, fresh_exports=sum(counts.values()), unique_products=unique_products,
                 missing_or_ambiguous=[], failed_ids=sorted(failures), stale_ids=sorted(stale),
                 duplicate_ids=duplicates, unexpected_ids=extras, unidentified_missing_count=unknown_ids,
                 reported_ids=len(all_attempted))
    return labels, facts


def promotions(data: dict, observed: datetime, snapshot: Path) -> tuple[dict, list[str], str]:
    labels, facts = promotion_observation(data, observed)
    gaps, sha = exceptions(labels, snapshot)
    facts['missing_or_ambiguous'] = gaps
    issues = [key for key, values in facts.items() if isinstance(values, list) and values]
    if facts['unidentified_missing_count'] or facts['reported_ids'] > facts['expected']:
        issues.append('coverage_count')
    return facts, issues, sha


def ozon(data: dict, observed: datetime, snapshot: Path) -> tuple[dict, list[str], str]:
    start, end = date.fromisoformat(data['date_from']), date.fromisoformat(data['date_to'])
    today = observed.astimezone(MSK).date()
    expected_end = today - timedelta(days=today.weekday() + 1)
    require(start == expected_end - timedelta(days=6) and end == expected_end,
            'Ozon period is not the last completed Moscow week')
    require(isinstance(data['account_id'], str) and 0 < len(data['account_id']) <= 80,
            'Missing Ozon account')
    days = [(start + timedelta(days=index)).isoformat() for index in range(7)]
    counts = {}
    for source, field in (('finance', 'missing_dates'), ('cpc_cpo', 'missing_ad_dates')):
        missing = data[field]
        require(isinstance(missing, list) and all(day in days for day in missing),
                'Invalid Ozon source coverage dates')
        require(len(set(missing)) == len(missing), 'Duplicate source coverage dates')
        counts.update({f'{source}/{day}': int(day not in missing) for day in days})
    products = data['cost_rows']
    require(isinstance(products, list), 'Missing Ozon cost coverage')
    for row in products:
        key = 'cost/' + identifier(row['marketplace_sku'])
        incomplete = row['roi_cost_incomplete']
        require(type(incomplete) is bool or incomplete is None, 'Invalid Ozon cost marker')
        require(key not in counts, 'Duplicate Ozon SKU in account coverage')
        counts[key] = int(incomplete is False)
    gaps, sha = exceptions(counts, snapshot)
    return dict(account_id=data['account_id'], date_from=start.isoformat(), date_to=end.isoformat(),
                observed_cost_rows=len(products), missing_or_unconfirmed=gaps), gaps, sha


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, default=SNAPSHOT)
    options = parser.parse_args()
    summary = teach(options.snapshot, LAB / 'shared-memory')
    print(f"Coverage recipe frozen after {summary['checks']} independent checks.")
