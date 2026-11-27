"""Teach and replay reading an already-visible XWAY product, without browser input.

The teacher locates one exact SKU/nmID row and its unique currency caption under
XWAY AI. The engine then learns read -> local report, using live UIA observations.
Only an owned native report pad receives writes. No XWAY settings or APIs change.
"""
from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import re
import threading

from kolos_states.core import StateEngine
from kolos_states.episode_desktop import EpisodeAdapter, EpisodeRecorder, control_runtime_id
from kolos_states.episode_readonly import ReadOnlySelectionObserver, SourceReportObserver
from kolos_states.episodes import bind, verify_effect
from kolos_states.protocol import require
from kolos_states.storage import Store
from tests.desktop.budget_read_experiment import drive, record_step, save_json, signature
from tests.desktop.test_episode_windows import pad
from tests.desktop.experiment_notice import testing_notice

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = ROOT / 'tests' / 'desktop-output'
QUERY = 'Прочитай артикул и дневной бюджет XWAY в локальный отчёт'
SKU_ROLE = 'Артикул XWAY'
BUDGET_ROLE = 'Дневной бюджет XWAY AI'
MONEY = re.compile(r'[0-9][0-9\s]*(?:[,.][0-9]{1,2})?\s*₽')


def descendants(root: object, max_depth: int, limit: int) -> list:
    """Read a bounded subtree, failing if the requested inspection is incomplete."""
    queue, nodes = deque([(root, 0)]), []
    while queue:
        require(len(nodes) < limit, 'UIA subtree exceeded the bounded inspection')
        control, depth = queue.popleft()
        nodes.append(control)
        if depth < max_depth:
            queue.extend((child, depth + 1) for child in control.GetChildren())
    return nodes


def unique(items: list, label: str) -> object:
    """Never choose an arbitrary candidate when the displayed view is ambiguous."""
    require(len(items) == 1, f'Expected one {label}; found {len(items)}')
    return items[0]


def product_row(top: object, vendor: str, nm_id: str) -> object:
    """Teacher selects a visible row, independently checking SKU and WB ID."""
    queue, visited = deque([(top, 0)]), 0
    while queue:
        require(visited < 3500, 'SKU not found within the bounded page scan')
        control, depth = queue.popleft()
        visited += 1
        if control.ControlTypeName == 'DataItemControl' and control.Name == vendor and not control.IsOffscreen:
            row = control.GetParentControl()
            cells = row.GetChildren()
            if any('WB ID: ' + nm_id in cell.Name for cell in cells):
                return row
        if depth < 24:
            queue.extend((child, depth + 1) for child in control.GetChildren())
    raise ValueError('The selected product is not visible')


def path_to(top: object, control: object) -> list[str]:
    """Record an exact native element path, without coordinates or input actions."""
    top_id, path = control_runtime_id(top), []
    for _ in range(32):
        current = control_runtime_id(control)
        path.append(current)
        if current == top_id:
            return list(reversed(path))
        control = control.GetParentControl()
        require(control is not None, 'Selected element left the bound window')
    raise ValueError('Selected element path is too deep')


def select_sources(hwnd: int, vendor: str, nm_id: str) -> dict:
    """Bind live observed sources; the budget amount is never stored in the selection."""
    import uiautomation as auto
    with auto.UIAutomationInitializerInThread():
        top = auto.ControlFromHandle(hwnd)
        require(top and 'XWAY' in top.Name.upper(), 'Open the selected XWAY product view')
        row = product_row(top, vendor, nm_id)
        cells = row.GetChildren()
        sku = unique([c for c in cells if c.Name == vendor], 'SKU cell')
        identity = unique([c for c in cells if 'WB ID: ' + nm_id in c.Name], 'product identity cell')
        ai = unique([c for c in cells if 'XWAY AI' in c.Name and not c.IsOffscreen], 'XWAY AI cell')
        identity_nodes = descendants(identity, 4, 120)
        nm = unique([c for c in identity_nodes if c.ControlTypeName == 'TextControl' and c.Name == nm_id], 'WB ID')
        ai_nodes = descendants(ai, 6, 150)
        marker = unique([c for c in ai_nodes if c.ControlTypeName == 'ImageControl' and
                         c.Name.startswith('XWAY AI')], 'XWAY AI marker')
        budget = unique([c for c in ai_nodes if c.ControlTypeName == 'ButtonControl' and
                         not c.IsOffscreen and MONEY.fullmatch(c.Name)], 'AI budget caption')
        return dict(hwnd=hwnd, title=top.Name, scope=f'XWAY product {vendor} WB {nm_id}',
                    anchors=[dict(path=path_to(top, c), text=c.Name) for c in (sku, nm, marker)],
                    fields=[dict(name=name, path=path_to(top, c))
                            for name, c in ((SKU_ROLE, sku), (BUDGET_ROLE, budget))])


def source_values(source: ReadOnlySelectionObserver) -> dict:
    """Read only the selected SKU and budget, without the rest of the page."""
    return {o['descriptor']['name']: o['value'] for o in source.observe()['objects']}


def failure_details(engine: StateEngine, observation: dict) -> dict:
    """Record the failed condition without resending a possibly completed action."""
    pending = engine.model['pending']
    if pending is None:
        return {}
    conditions = []
    try:
        verify_effect(pending['action'], pending['before'], observation)
        for item in pending.get('protected', []):
            require(bind(observation, item['descriptor'])['value'] == item['value'],
                    'Protected source changed: ' + item['descriptor']['name'])
    except ValueError as exc:
        conditions.append(str(exc))
    return dict(conditions=conditions, action=pending['action'],
                before=pending['before'], after=observation)


def demonstrate(source: ReadOnlySelectionObserver, engine: StateEngine, output: Path,
                stop: threading.Event | None = None) -> dict:
    """Teacher shows one verified read/copy/report sequence on real windows."""
    with pad('local placeholder', source2='local placeholder') as report:
        observer = SourceReportObserver(source, report)
        adapter = EpisodeAdapter(observer, allow=lambda: True, stop=stop, timeout=30)
        try:
            engine.start_episode(QUERY, observer.observe())
        except ValueError as exc:
            untrained = str(exc)
        else:
            raise AssertionError('Command must be unknown before its first demonstration')
        recorder = EpisodeRecorder(adapter, QUERY)
        try:
            for index, role in enumerate((SKU_ROLE, BUDGET_ROLE), 1):
                record_step(recorder, 'read', role)
                record_step(recorder, 'write', f'Target {index}', f'v{index-1}')
                print('Taught source/report pair: ' + role, flush=True)
            record_step(recorder, 'activate', 'Save')
        except Exception:
            save_json(output / 'incomplete-demonstration.json',
                      dict(receipts=recorder.receipts, sent=list(adapter.sent.values()),
                           last_observation=source.latest))
            raise
        record = recorder.finish()
        engine.learn_episode(record)
        save_json(output / 'demonstration.json', record)
        return dict(untrained_reason=untrained, demonstrations=len(engine.model['learningLog']),
                    operations=[r['action']['kind'] for r in record['receipts']],
                    source_values=source_values(source))


def repeat(source: ReadOnlySelectionObserver, engine: StateEngine, layout: int,
           stop: threading.Event | None = None) -> dict:
    """Kernel chooses the learned sequence; observations supply the current amount."""
    engine.reset()
    frozen, before = signature(engine), source_values(source)
    with pad('local placeholder', source2='local placeholder', layout=layout) as report:
        observer = SourceReportObserver(source, report)
        adapter = EpisodeAdapter(observer, allow=lambda: True, stop=stop, timeout=30)
        engine.start_episode(QUERY, observer.observe())
        result = drive(engine, adapter)
        if result['error']:
            result['diagnostic'] = failure_details(engine, observer.observe())
        fields = {o['descriptor']['name']: o['value'] for o in report.observe()['objects'] if o['readable']}
        source_actions = [a for a in adapter.sent.values() if a['descriptor']['scope'] == source.selection['scope']]
        checks = dict(complete=result['status'] == 'complete' and result['error'] is None,
                      source_unchanged=source_values(source) == before,
                      sku_exact=fields['Saved 1'] == before[SKU_ROLE],
                      budget_exact=fields['Saved 2'] == before[BUDGET_ROLE],
                      browser_read_only=len(source_actions) == 2 and all(a['kind'] == 'read' for a in source_actions),
                      local_unrelated_unchanged=fields['Unrelated'] == 'do not touch',
                      no_relearning=signature(engine) == frozen)
        return dict(result, checks=checks, passed=all(checks.values()),
                    reported_sku=fields['Saved 1'], reported_budget=fields['Saved 2'],
                    browser_input_actions=sum(a['kind'] != 'read' for a in source_actions))


def run(args: argparse.Namespace, output: Path, result: dict,
        stop: threading.Event | None = None) -> None:
    """Teach once, repeat with a new report window, then reload the same lab memory."""
    selection = select_sources(args.hwnd, args.vendor, args.nm_id)
    save_json(output / 'selection.json', selection)
    source = ReadOnlySelectionObserver(selection)
    result['before'] = source_values(source)
    print('Live source selected: ' + str(result['before']), flush=True)
    engine = StateEngine()
    result['teaching'] = demonstrate(source, engine, output, stop)
    print('Demonstration learned; browser received no input.', flush=True)
    result['repeat'] = repeat(source, engine, 1, stop)
    print('First repeat: ' + str(result['repeat']['passed']), flush=True)
    engine.reset()
    store = Store(output / 'memory')
    try:
        store.save(engine)
    finally:
        store.close()
    store = Store(output / 'memory')
    try:
        loaded = store.load()
    finally:
        store.close()
    result['after_reload'] = repeat(source, loaded, 0, stop)
    result['after'] = source_values(source)
    result['passed'] = result['repeat']['passed'] and result['after_reload']['passed']


def main() -> int:
    """Save bounded evidence and the selected learned episode inside the project."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hwnd', type=int, required=True)
    parser.add_argument('--vendor', required=True)
    parser.add_argument('--nm-id', required=True)
    args = parser.parse_args()
    output = OUTPUT_ROOT / ('xway-reading-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    output.mkdir(parents=True, exist_ok=False)
    result = dict(passed=False, started_utc=datetime.now(timezone.utc).isoformat(),
                  scope='Live UIA text of explicitly selected XWAY row -> isolated native report',
                  teacher='Codex through production EpisodeRecorder',
                  limitations=['Already-open view only', 'Runtime paths need reselection after page rebuild',
                               'No learned catalogue navigation', 'Budget never deliberately changed'])
    try:
        with testing_notice() as stop:
            run(args, output, result, stop)
    except Exception as exc:
        result['error'] = dict(type=type(exc).__name__, message=str(exc))
    result['finished_utc'] = datetime.now(timezone.utc).isoformat()
    save_json(output / 'result.json', result)
    print(str(output / 'result.json'), flush=True)
    print('PASS' if result['passed'] else 'BLOCKED: ' + str(result.get('error')), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
