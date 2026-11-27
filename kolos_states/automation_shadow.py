"""Read-only Kolos handoff and independent reviewer receipt for Codex schedules."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

from . import automation_coverage as coverage
from .ipc import MAX_BYTES, atomic_json, read_json
from .protocol import require
from .xway_readonly import campaign
from .xway_readonly.worker import digest

SCHEMA = 'kolos-automation-handoff/1'
REVIEW_SCHEMA = 'kolos-automation-review/1'
STOCK_PROFILE = coverage.PROJECT / '.local-data' / 'automation-shadow' / 'xway-profile.json'
PROFILES = {
    'wb-2': 'xway-campaign-v1',
    'ozon': 'ozon-coverage-v1',
    'wb': 'wb-promotion-coverage-v1',
    '1': None, 'automation': None, 'automation-2': None, 'automation-3': None,
    'automation-4': None, 'automation-6': None, 'projects': None, 'push-16': None,
    'wb-ctr-xway': None, '11295-70-12': None, 'wildberries': None,
    'fbs-wb-ozon-1': None,
}


def location(root: Path, payload: dict) -> tuple[str, str, Path]:
    automation = payload['automation_id']
    require(automation in PROFILES, 'Unknown automation ID')
    run_id = campaign.run_name(payload['run_id'])
    root = root.resolve()
    directory = (root / automation / run_id).resolve()
    require(directory.is_relative_to(root), 'Report outside the requested output root')
    return automation, run_id, directory


def _xway(data: dict, directory: Path) -> dict:
    binding = read_json(STOCK_PROFILE)
    require(isinstance(binding, dict) and set(binding) == {'task', 'memory_run'},
            'Local stock-pilot profile is unavailable')
    require(data['task'] == binding['task'], 'Wrong stock-pilot campaign')
    original = campaign.run(dict(run_id='xway', task=data['task'], observations=data['observations']),
                            directory, teach=False, memory_run=campaign.run_name(binding['memory_run']),
                            memory_root=campaign.ROOT)
    require(original['status'] == 'observed' and original['memory_unchanged'] and not original['may_execute'],
            'XWAY campaign blocked: ' + original.get('reason', 'unconfirmed read'))
    return dict(status='completed', verification_required=original['missing_for_stock_rule'],
                result=dict(task=original['task'], campaign=original['campaign']),
                observed_at=original['observed_at'], source=original['source'],
                memory_sha256=original['memory_sha256'])


def _coverage(automation: str, data: dict, now: datetime, snapshot: Path) -> dict:
    stamp = coverage.timezone_stamp(data['observed_at'])
    require(timedelta(seconds=-10) <= now - stamp <= timedelta(minutes=15), 'Stale coverage input')
    source = data['source_ref']
    require(type(source) is str and 0 < len(source.strip()) <= 500, 'Missing coverage source reference')
    adapter = coverage.ozon if automation == 'ozon' else coverage.promotions
    result, gaps, sha = adapter(data, stamp, snapshot)
    return dict(status='partial' if gaps else 'completed', source=source, observed_at=[stamp.isoformat()],
                verification_required=gaps, result=result, memory_sha256=sha, notify_exception=bool(gaps))


def run(payload: dict, root: Path, *, snapshot: Path = coverage.SNAPSHOT,
        now: datetime | None = None) -> dict:
    automation, run_id, directory = location(root, payload)
    require(set(payload) <= {'automation_id', 'run_id', 'input'}, 'Unexpected handoff fields')
    checksum = digest(payload.get('input'))
    handoff = directory / 'handoff.json'
    now = now or datetime.now(timezone.utc)
    profile = PROFILES[automation]
    report = dict(schema=SCHEMA, automation_id=automation, run_id=run_id, capability=profile,
                  created_at=now.isoformat(), input_sha256=checksum, may_execute=False,
                  notify_exception=False, verification_required=[], result=None)
    try:
        directory.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        saved = read_json(handoff)
        if (isinstance(saved, dict) and saved.get('schema') == SCHEMA and saved.get('automation_id') == automation
                and saved.get('run_id') == run_id and saved.get('input_sha256') == checksum
                and saved.get('may_execute') is False):
            return saved
        return dict(report, status='failed', reason='run_in_progress_or_input_conflict', notify_exception=True)

    if profile is None:
        report.update(status='skipped', reason='no_verified_capability')
    else:
        try:
            data = payload.get('input')
            require(isinstance(data, dict), 'Source data unavailable for this run')
            result = _xway(data, directory) if automation == 'wb-2' else _coverage(automation, data, now, snapshot)
            report.update(result)
        except (AttributeError, KeyError, TypeError, ValueError, OSError, OverflowError) as error:
            report.update(status='failed', reason=str(error)[:450], notify_exception=True)
    atomic_json(handoff, report)
    return report


def review(payload: dict, root: Path) -> dict:
    automation, run_id, directory = location(root, payload)
    handoff = read_json(directory / 'handoff.json')
    require(isinstance(handoff, dict) and handoff.get('schema') == SCHEMA and
            handoff.get('automation_id') == automation and handoff.get('run_id') == run_id and
            handoff.get('may_execute') is False, 'No valid handoff for this run')
    require(payload['input_sha256'] == handoff['input_sha256'], 'Review describes another handoff')
    verdict = payload['verdict']
    require(verdict in ('confirmed', 'corrected', 'not_confirmed', 'not_needed'), 'Invalid review verdict')
    require((verdict == 'not_needed') == (handoff['status'] == 'skipped'), 'Review contradicts the handoff status')
    require(handoff['status'] != 'failed' or verdict == 'not_confirmed', 'Failed handoff cannot be confirmed')
    fields = {key: payload.get(key, []) for key in ('confirmed', 'corrected', 'unknown', 'sources')}
    for values in fields.values():
        require(isinstance(values, list) and len(values) <= 100 and
                all(type(value) is str and 0 < len(value) <= 650 for value in values),
                'Review entries must be short text observations')
    require(bool(fields['corrected']) == (verdict == 'corrected'), 'Corrections require the corrected verdict')
    require(not (fields['confirmed'] or fields['corrected']) or fields['sources'], 'Review needs independent evidence')
    require(verdict != 'confirmed' or fields['confirmed'], 'Review needs a confirmed observation')
    result = dict(schema=REVIEW_SCHEMA, automation_id=automation, run_id=run_id, verdict=verdict,
                  handoff_sha256=digest(handoff), may_execute=False, **fields,
                  notify_exception=(handoff['notify_exception'] or verdict in ('corrected', 'not_confirmed')))
    file = directory / 'review.json'
    guard = directory / 'review.pending'
    try:
        guard.mkdir()
    except FileExistsError:
        require(read_json(file) == result, 'Another review for this run is in progress')
        return result
    try:
        if file.exists():
            require(read_json(file) == result, 'Review for this run already exists')
        else:
            atomic_json(file, result)
    finally:
        guard.rmdir()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('run', 'review'))
    parser.add_argument('--output-root', required=True, type=Path)
    args = parser.parse_args()
    sys.stdin.reconfigure(encoding='utf-8-sig')
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raw = sys.stdin.read(MAX_BYTES + 1)
        require(len(raw.encode('utf-8')) <= MAX_BYTES, 'Oversized handoff input')
        result = (run if args.mode == 'run' else review)(json.loads(raw), args.output_root)
    except (AttributeError, KeyError, TypeError, ValueError, OSError, OverflowError) as error:
        result = dict(status='failed', reason=str(error)[:450], notify_exception=True, may_execute=False)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return int(result.get('status') == 'failed')


if __name__ == '__main__':
    raise SystemExit(main())
