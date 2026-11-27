"""Isolated file bridge between supported browser tools and the production Kolos kernel.

No browser/network library or ad-setting motor is present. The tool host performs
browser actions, supplies actual DOM evidence, and checks API readback separately.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

from kolos_states.episode_browser import BrowserEpisodeBridge
from kolos_states.episode_experiment import memory_signature
from kolos_states.episodes import SCHEMA, bind, observe
from kolos_states.protocol import require
from kolos_states.storage import Store
from tests.desktop.experiment_gate import check_gate, directory, write_json

SKU = '11016-70х12'
NM_ID = '1391386148'
QUERIES = dict(search='Найди товар по артикулу XWAY', read='Прочитай артикул и бюджет найденного товара XWAY')
SCOPE = 'XWAY shop 13614 product ' + SKU + ' WB ' + NM_ID


def read_json(path: Path, default: dict | None = None) -> dict:
    """Read an actual local artifact; never synthesize a successful browser result."""
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else (default or {})


def field(identity: str, name: str, value: str, scope: str, writable: bool = False) -> dict:
    """Describe one explicitly selected source or local output field."""
    return dict(id=identity, descriptor=dict(kind='field', name=name, scope=scope, automation_id=''),
                readable=True, writable=writable, enabled=True, protected=False, value=value)


def validate_page(raw: dict, need_product: bool = False) -> None:
    """Check exact shop context and product identity before accepting DOM evidence."""
    url = urlsplit(raw['url'])
    require(url.scheme == 'https' and url.hostname == 'am.xway.ru' and
            url.path.rstrip('/') == '/wb/shop/13614', 'Unexpected XWAY shop/page')
    require(isinstance(raw.get('search'), str) and isinstance(raw.get('epoch'), str), 'Missing DOM evidence')
    if need_product:
        product = raw.get('product') or {}
        require(product.get('sku') == SKU and str(product.get('wb_id')) == NM_ID, 'Wrong or missing product row')
        require(re.fullmatch(r'[0-9][0-9\s]*\s*₽', product.get('budget', '')) is not None,
                'Budget caption is not an unambiguous ruble amount')


def snapshot(path: Path, raw: dict, mode: str) -> dict:
    """Combine independently read DOM fields with the actual local task/report files."""
    require(mode in QUERIES, 'Unknown lesson mode')
    validate_page(raw, mode == 'read')
    prefix = 'browser:' + raw['epoch'] + ':'
    if mode == 'search':
        task = read_json(path / 'task.json')
        require(task.get('sku') == SKU, 'Local task changed')
        objects = [field('local-task:sku', 'Requested SKU', task['sku'], 'Local XWAY task'),
                   field(prefix + 'search', 'Product search', raw['search'], 'XWAY shop 13614 search', True),
                   field(prefix + 'count', 'Result count', str(raw['result_count']), 'XWAY shop 13614 search')]
        button = field(prefix + 'apply', 'Apply search', '', 'XWAY shop 13614 search')
        button['descriptor']['kind'] = 'button'
        button.update(readable=False, value=None)
        require(raw.get('apply_visible') is True, 'Open the search editor before observing its controls')
        objects.append(button)
    else:
        product, report = raw['product'], read_json(path / 'report.json')
        objects = [field(prefix + 'sku', 'Product SKU', product['sku'], SCOPE),
                   field(prefix + 'budget', 'Daily budget', product['budget'], SCOPE),
                   field('local-report:sku', 'Report SKU', report['sku'], 'Local XWAY report', True),
                   field('local-report:budget', 'Report budget', report['budget'], 'Local XWAY report', True)]
    return observe(dict(schema=SCHEMA, session=raw['session'], version=raw['version'],
                        captured_at=raw['captured_at'], objects=objects))


def budget_transition(raw: dict, target: int, completed: int) -> dict:
    """Limit the host's separately authorized experiment to one 100->105->100 cycle."""
    validate_page(raw, True)
    current = int(re.sub(r'\D', '', raw['product']['budget']))
    allowed = [(100, 105), (105, 100)]
    require(type(target) is int and 0 <= completed < 2 and
            (current, target) == allowed[completed], 'Budget transition is outside the approved cycle')
    return dict(sku=SKU, wb_id=NM_ID, before=current, after=target, status='prepared')


def local_write(path: Path, request: dict) -> None:
    """Write only the kernel-selected local report field, then read it from disk later."""
    action = request['action']
    mapping = {'Report SKU': 'sku', 'Report budget': 'budget'}
    name = action['descriptor']['name']
    require(action['kind'] == 'write' and action['descriptor']['scope'] == 'Local XWAY report' and name in mapping,
            'Not a local report write')
    report = read_json(path / 'report.json')
    report[mapping[name]] = action['value']
    write_json(path / 'report.json', report)


def compact_pending(bridge: BrowserEpisodeBridge) -> dict:
    """Return an instruction, never a claim that its effect has already occurred."""
    if bridge.pending is None:
        return dict(status=bridge.engine.model['status'])
    return dict(id=bridge.pending['id'], action=bridge.pending['action'])


def handle_lesson(path: Path, state: dict, bridge: BrowserEpisodeBridge, request: dict) -> dict:
    """Drive one teaching or repeat step with no hardcoded route inside the kernel."""
    op, mode = request['op'], state['mode']
    if op == 'teach-start':
        bridge.begin_teaching(QUERIES[mode])
    elif op == 'prepare':
        bridge.prepare(snapshot(path, request['dom'], mode), request['kind'], request['role'], request.get('source'))
    elif op == 'confirm':
        receipt = bridge.confirm(snapshot(path, request['first'], mode), snapshot(path, request['second'], mode))
        state['trace'].append(dict(action=receipt['action'], after=receipt['after'], verified_by=receipt['verified_by']))
    elif op == 'teach-finish':
        record = bridge.finish_teaching()
        write_json(path / ('lesson-' + mode + '.json'), record)
    elif op == 'run-start':
        bridge.start(QUERIES[mode], snapshot(path, request['dom'], mode))
    elif op == 'next':
        bridge.next(snapshot(path, request['dom'], mode))
    elif op == 'local-write':
        require(bridge.pending is not None, 'No pending output action')
        require(not state.get('local_sent'), 'Local write was already sent; confirm it before continuing')
        local_write(path, bridge.pending)
        state['local_sent'] = True
    else:
        raise ValueError('Unknown lesson operation')
    if op == 'confirm':
        state['local_sent'] = False
    return compact_pending(bridge)


def handle_budget(path: Path, state: dict, request: dict) -> dict:
    """Record the allowed external change and require fresh DOM plus API readback."""
    if request['op'] == 'budget-prepare':
        require(state.get('budget_pending') is None, 'Budget effect is unconfirmed; do not resend')
        pending = budget_transition(request['dom'], request['target'], len(state['budget_log']))
        api = request['api']
        require(api['budget'] == pending['before'] and str(api['wb_id']) == NM_ID and
                api['sku'] == SKU and api['grouped_ai'] is False, 'Initial DOM/API budget or identity mismatch')
        state['budget_pending'] = pending
        return state['budget_pending']
    pending = state.get('budget_pending')
    require(pending is not None, 'No budget change to confirm')
    validate_page(request['dom'], True)
    actual = int(re.sub(r'\D', '', request['dom']['product']['budget']))
    api = request['api']
    require(actual == pending['after'] and api['budget'] == actual and
            str(api['wb_id']) == NM_ID and api['sku'] == SKU and api['grouped_ai'] is False,
            'Budget change is not confirmed by DOM and XWAY API')
    state['budget_log'].append(dict(pending, status='confirmed', api=api, dom=request['dom']))
    state['budget_pending'] = None
    return dict(confirmed=actual)


def operate(path: Path, request: dict) -> dict:
    """Check the human gate before every step and save a recoverable audit."""
    check_gate(path)
    state = read_json(path / 'bridge.json', dict(mode='search', trace=[], budget_log=[], bridge=None))
    bridge = BrowserEpisodeBridge(state['bridge'])
    op = request['op']
    if op == 'init':
        require(not (path / 'task.json').exists(), 'Experiment has already been initialized')
        write_json(path / 'task.json', dict(sku=SKU, wb_id=NM_ID, budget_cycle=[100, 105, 100]))
        write_json(path / 'report.json', dict(sku='', budget=''))
        result = dict(initialized=True)
    elif op == 'mode':
        require(bridge.pending is None, 'Cannot switch with an unconfirmed action')
        require(request['mode'] in QUERIES, 'Unknown mode')
        state['mode'] = request['mode']
        if request.get('clear_report'):
            write_json(path / 'report.json', dict(sku='', budget=''))
        result = dict(mode=state['mode'])
    elif op.startswith('budget-'):
        result = handle_budget(path, state, request)
    elif op == 'checkpoint':
        store = Store(path / 'memory')
        try:
            store.save(bridge.engine)
        finally:
            store.close()
        result = dict(memory_saved=True)
    elif op == 'status':
        result = dict(mode=state['mode'], report=read_json(path / 'report.json'), budget_log=state['budget_log'])
    else:
        result = handle_lesson(path, state, bridge, request)
    state['bridge'] = bridge.dump()
    write_json(path / 'bridge.json', state)
    result.update(lessons=len(bridge.engine.model['learningLog']),
                  memory_sha256=hashlib.sha256(memory_signature(bridge.engine).encode()).hexdigest())
    return result


def main() -> None:
    """Consume JSON from stdin; never evaluate page text or arbitrary commands."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True)
    args = parser.parse_args()
    path = directory(args.directory)
    request = json.load(sys.stdin)
    result = operate(path, request)
    with (path / 'events.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(), request=request,
                                     response=result), ensure_ascii=False) + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
