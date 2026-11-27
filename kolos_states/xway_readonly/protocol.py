"""Observed role contracts and deny-by-default actions for a live read-only trial."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from ..episodes import SCHEMA, bind, observe
from ..protocol import require

SEARCH = 'Найди товар по артикулу XWAY'
READ = 'Прочитай найденный товар XWAY в локальный отчёт v2'
QUERIES = {'search': SEARCH, 'read': READ}
SCOPES = {'task': 'Local XWAY task', 'report': 'Local XWAY report'}
REPORT_FIELDS = {'Report SKU': 'sku', 'Report WB ID': 'wb_id', 'Report budget': 'budget'}


def validate_task(task: dict) -> None:
    """Allow only one explicit product identity, never a URL or executable payload."""
    require(set(task) == {'sku', 'wb_id', 'shop_id', 'shop_name'}, 'Expected product and shop binding')
    require(isinstance(task['shop_id'], str) and re.fullmatch(r'[1-9][0-9]{0,11}', task['shop_id']) is not None,
            'Invalid shop ID')
    require(isinstance(task['shop_name'], str) and 0 < len(task['shop_name'].strip()) <= 160,
            'Invalid shop heading')
    require(isinstance(task['sku'], str) and 0 < len(task['sku']) <= 160 and
            not any(c in task['sku'] for c in '\r\n\x00'), 'Invalid SKU')
    require(isinstance(task['wb_id'], str) and task['wb_id'].isdigit(), 'Invalid WB ID')


def shop_scope(task: dict, role: str) -> str:
    """Keep learned roles tied to the explicitly configured shop."""
    suffix = {'search': 'search', 'product': 'selected product'}[role]
    return f"XWAY shop {task['shop_id']} {suffix}"


def validate_dom(raw: dict, task: dict, *, product: bool) -> None:
    """Reject other shops, ambiguous products, hidden editors and missing captions."""
    validate_task(task)
    url = urlsplit(raw['url'])
    require(url.scheme == 'https' and url.hostname == 'am.xway.ru' and
            url.path.rstrip('/') == f"/wb/shop/{task['shop_id']}", 'Unexpected XWAY page')
    require(raw.get('shop') == task['shop_name'], 'Wrong shop heading')
    require(type(raw.get('result_count')) is int and 0 <= raw['result_count'] <= 200,
            'Missing or oversized result count')
    require(raw.get('exact') is True and raw.get('editor_visible') is True and
            raw.get('apply_count') == 1 and isinstance(raw.get('search'), str),
            'Exact SKU filter must be open and unambiguous')
    if product:
        rows = raw.get('rows', [])
        require(len(rows) == 1 and raw['result_count'] == 1, 'Expected one filtered product')
        row = rows[0]
        require(row['sku'] == task['sku'] and row['wb_id'] == task['wb_id'], 'Wrong product identity')
        require(re.fullmatch(r'[0-9][0-9\s]*(?:[,.][0-9]{1,2})?\s*₽', row['budget']) is not None,
                'Missing or ambiguous XWAY AI budget caption')
        require(type(row.get('ai_enabled')) is bool, 'Missing observed AI switch')


def field(identity: str, name: str, value: str, scope: str, *, writable: bool = False) -> dict:
    """Describe only a live observed field or the actual local task/report file."""
    return dict(id=identity, descriptor=dict(kind='field', name=name, scope=scope, automation_id=''),
                value=value, readable=True, writable=writable, enabled=True, protected=False)


def snapshot(raw: dict, task: dict, report: dict, stage: str) -> dict:
    """Use the same learned search roles and product-independent reading roles."""
    require(stage in QUERIES, 'Unknown stage')
    validate_dom(raw, task, product=stage == 'read')
    prefix = raw['session'] + ':'
    if stage == 'search':
        objects = [field('task:sku', 'Requested SKU', task['sku'], SCOPES['task']),
                   field(prefix + 'search', 'Product search', raw['search'], shop_scope(task, 'search'), writable=True),
                   field(prefix + 'count', 'Result count', str(raw['result_count']), shop_scope(task, 'search'))]
        button = field(prefix + 'apply', 'Apply search', '', shop_scope(task, 'search'))
        button.update(readable=False, value=None)
        button['descriptor']['kind'] = 'button'
        objects.append(button)
    else:
        row = raw['rows'][0]
        objects = []
        for name, key, output in [('Product SKU', 'sku', 'Report SKU'),
                                  ('Product WB ID', 'wb_id', 'Report WB ID'),
                                  ('Daily budget', 'budget', 'Report budget')]:
            objects.append(field(prefix + key, name, row[key], shop_scope(task, 'product')))
            objects.append(field('report:' + key, output, report[key], SCOPES['report'], writable=True))
    return observe(dict(schema=SCHEMA, session=raw['session'], version=raw['version'],
                        captured_at=raw['captured_at'], objects=objects))


def authorize(action: dict, observation: dict, task: dict) -> str:
    """No ad-setting primitive exists; the motor cannot broaden a kernel request."""
    obj = bind(observation, action['descriptor'])
    require(obj['id'] == action['object'], 'Stale target ID')
    kind, desc = action['kind'], obj['descriptor']
    if kind == 'read':
        require(obj['readable'], 'Unreadable source')
        return 'read'
    if kind == 'write' and desc['scope'] == SCOPES['report'] and desc['name'] in REPORT_FIELDS:
        require(obj['writable'] and isinstance(action.get('value'), str), 'Invalid report write')
        return 'local-report'
    if kind == 'write' and desc['scope'] == shop_scope(task, 'search') and desc['name'] == 'Product search':
        require(action.get('value') == task['sku'], 'Search must equal the current task SKU')
        return 'search-fill'
    if kind == 'activate' and desc['scope'] == shop_scope(task, 'search') and desc['name'] == 'Apply search':
        require(next(o['value'] for o in observation['objects']
                     if o['descriptor']['name'] == 'Product search') == task['sku'], 'Wrong search value')
        return 'search-apply'
    raise ValueError('Action outside read-only XWAY contract')
