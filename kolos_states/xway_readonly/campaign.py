"""Teach and replay a campaign read from paired XWAY connector responses on Windows."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
import sys
import time

from ..episode_browser import BrowserEpisodeBridge
from ..episodes import SCHEMA, bind
from ..ipc import MAX_BYTES, atomic_json, read_json
from ..protocol import persistent_graph, require
from ..storage import Store
from .protocol import field
from .worker import OUTPUT, digest

QUERY = 'Прочитай кампанию XWAY по данным коннектора'
FIELDS = ('id', 'name', 'type', 'status', 'budget', 'currency')
TASK_FIELDS = {'shop_id', 'nm_id', 'campaign_id'}
SOURCE = 'XWAY list_campaigns'
SCOPE = 'XWAY campaign observed through list_campaigns'
REPORT = 'Local XWAY campaign report'
FOLLOW_UP = ('campaign_status_label', 'campaign_nm_ids', 'other_pause_reasons',
             'campaign_status_changed_at', 'manual_status_control')
ROOT = OUTPUT / 'xway-campaign-pilot'


def run_name(value: object) -> str:
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', value),
            'Invalid run ID')
    return value


def campaign_observation(raw: dict, task: dict, now: datetime) -> tuple[datetime, dict]:
    """Check the exact query binding and accept one complete, unambiguous response."""
    args = raw['query']
    require(args == dict(shop_id=task['shop_id'], product_id=[task['nm_id']], id=[task['campaign_id']]),
            'XWAY query does not match the requested shop, product and campaign')
    observed_at = datetime.fromisoformat(raw['observed_at'])
    require(observed_at.utcoffset() is not None, 'XWAY observation must have a time zone')
    require(timedelta(seconds=-10) <= now - observed_at <= timedelta(minutes=5),
            'XWAY observation is outside the freshness window')
    response = raw['response']
    pagination = response['pagination']
    require(pagination.get('offset') == 0 and pagination.get('count') == 1 and
            'next_offset' in pagination and pagination['next_offset'] is None,
            'XWAY campaign selection is incomplete or ambiguous')
    rows = response['items']
    require(isinstance(rows, list) and len(rows) == 1, 'Expected one XWAY campaign')
    row = rows[0]
    require(type(row['id']) is int and row['id'] == task['campaign_id'], 'Wrong XWAY campaign ID')
    for key in ('name', 'type', 'status', 'currency'):
        require(isinstance(row.get(key), str) and 0 < len(row[key].strip()) <= 500,
                'Missing XWAY campaign field: ' + key)
    require(re.fullmatch(r'[0-9]+', row['status']), 'Missing XWAY status code')
    budget = row['budget']
    require(budget is None or (type(budget) in (int, float) and math.isfinite(budget) and budget >= 0),
            'Invalid XWAY campaign budget')
    return observed_at, {key: row[key] for key in FIELDS}


class CampaignEpisode:
    """Present observed XWAY fields as sources and permit writes only to the local draft."""

    def __init__(self, bridge: BrowserEpisodeBridge, run_id: str, observations: list[tuple]) -> None:
        self.bridge = bridge
        self.run_id = run_id
        self.observations = observations
        self.version = 0
        self.draft = {key: '' for key in FIELDS}
        self.dispatches = []

    def observe(self, index: int = 0) -> dict:
        _, campaign = self.observations[index]
        self.version += 1
        objects = []
        for key in FIELDS:
            objects.append(field('source:' + key, key, json.dumps(campaign[key], ensure_ascii=False), SCOPE))
            objects.append(field('report:' + key, 'Report ' + key, self.draft[key], REPORT, writable=True))
        return dict(schema=SCHEMA, session=self.run_id, version=self.version,
                    captured_at=time.time(), objects=objects)

    def perform(self, request: dict) -> None:
        action = request['action']
        target = bind(self.observe(), action['descriptor'])
        require(target['id'] == action['object'], 'Stale campaign role')
        if action['kind'] == 'read':
            require(target['id'] in {'source:' + key for key in FIELDS}, 'Read outside XWAY campaign fields')
        else:
            key = target['id'].removeprefix('report:')
            require(action['kind'] == 'write' and target['writable'] and key in self.draft,
                    'Only local report writes are supported')
            self.draft[key] = action['value']
        self.bridge.confirm(self.observe(0), self.observe(1), verified_by='two-XWAY-connector-responses')
        self.dispatches.append(dict(kind=action['kind'], role=target['descriptor']['name']))

    def teach(self) -> None:
        self.bridge.begin_teaching(QUERY)
        for index, key in enumerate(FIELDS):
            self.perform(self.bridge.prepare(self.observe(), 'read', key))
            self.perform(self.bridge.prepare(self.observe(), 'write', 'Report ' + key, source=f'v{index}'))
        self.bridge.finish_teaching()

    def replay(self) -> None:
        self.bridge.start(QUERY, self.observe())
        for _ in range(2 * len(FIELDS) + 1):
            request = self.bridge.next(self.observe())
            if request.get('status') == 'complete':
                return
            require('action' in request, 'Campaign episode did not complete')
            self.perform(request)
        raise ValueError('Campaign episode exceeded its step limit')


def learned_signature(bridge: BrowserEpisodeBridge) -> str:
    model = bridge.engine.model
    return digest(dict(graph=persistent_graph(model['memory']), commands=model.get('episodeCommands', [])))


def load_memory(bridge: BrowserEpisodeBridge, path: Path) -> str:
    file = path / 'memory.json'
    require(file.is_file(), 'No campaign training memory at this run ID')
    raw = read_json(file)
    bridge.engine = Store.restore_snapshot(raw)
    return digest(raw)


def run(payload: dict, root: Path, *, teach: bool, memory_run: str | None = None,
        memory_root: Path | None = None) -> dict:
    run_id = run_name(payload['run_id'])
    directory = root / run_id
    directory.mkdir(parents=True, exist_ok=False)
    result = dict(schema='kolos-xway-campaign-handoff/1', run_id=run_id, status='blocked',
                  mode='teach' if teach else 'read', source=SOURCE, campaign=None, may_execute=False,
                  missing_for_stock_rule=list(FOLLOW_UP))

    try:
        task = payload['task']
        require(set(task) == TASK_FIELDS and all(type(value) is int and value > 0 for value in task.values()),
                'Expected exact positive shop, product and campaign IDs')
        result['task'] = task
        now = datetime.now(timezone.utc)
        captures = payload['observations']
        require(isinstance(captures, list) and len(captures) == 2, 'Expected exactly two XWAY responses')
        observations = [campaign_observation(raw, task, now) for raw in captures]
        require(observations[0][0] < observations[1][0],
                'Expected two distinct ordered XWAY observations')
        require(observations[0][1] == observations[1][1], 'XWAY campaign values changed during verification')
        result['observed_at'] = [time.isoformat() for time, _ in observations]

        bridge = BrowserEpisodeBridge()
        memory = (memory_root or root) / run_name(memory_run) / 'memory' if memory_run else None
        if memory is not None:
            require(not teach, 'Teaching starts with isolated memory')
            result['memory_sha256'] = load_memory(bridge, memory)
        episode = CampaignEpisode(bridge, run_id, observations)
        if teach:
            episode.teach()
        else:
            learned_before = learned_signature(bridge)
            episode.replay()
            require(learned_before == learned_signature(bridge), 'Campaign replay changed the learned memory')
            result['memory_unchanged'] = True

        campaign = {key: json.loads(value) for key, value in episode.draft.items()}
        require(campaign == observations[1][1], 'Local draft does not match the XWAY readback')
        if teach:
            store = Store(directory / 'memory')
            try:
                store.save(bridge.engine)
            finally:
                store.close()
        result.update(status='taught' if teach else 'observed', campaign=campaign,
                      dispatches=episode.dispatches)
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError) as error:
        result['reason'] = str(error)

    atomic_json(directory / 'handoff.json', result)
    return result


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('mode', choices=('teach', 'read'))
    cli.add_argument('--memory-run', help='Run ID of a saved teaching episode')
    cli.add_argument('--output-root', type=Path, default=ROOT,
                     help='Writable report directory for a scheduled read in another project')
    args = cli.parse_args()
    if args.mode == 'teach' and args.output_root != ROOT:
        cli.error('--output-root is available for read only')
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    text = sys.stdin.read(MAX_BYTES + 1)
    require(len(text) <= MAX_BYTES, 'Oversized XWAY handoff input')
    result = run(json.loads(text), args.output_root, teach=args.mode == 'teach',
                 memory_run=args.memory_run, memory_root=ROOT)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return int(result['status'] == 'blocked')


if __name__ == '__main__':
    raise SystemExit(main())
