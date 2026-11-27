"""Demonstrate and replay a budget-reading report in disposable native windows.

Uses the production recorder, kernel, adapter and Store. No browser, network,
existing user window or main Kolos memory is accessed. Source 1 is a synthetic
SKU; Source 2 is a synthetic budget. Targets/Saved are the local report only.
Run from the repository root with ``py -3 -m tests.desktop.budget_read_experiment``.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from kolos_states.core import StateEngine
from kolos_states.desktop import Indeterminate
from kolos_states.episode_desktop import EpisodeAdapter, EpisodeRecorder
from kolos_states.episode_experiment import memory_signature
from kolos_states.episodes import bind
from kolos_states.protocol import clone
from kolos_states.storage import Store
from tests.desktop.test_episode_windows import by_name, pad

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = ROOT / 'tests' / 'desktop-output'
QUERY = 'Read the product and daily budget into the local report'
ALLOWED = {'read': {'Source 1', 'Source 2'},
           'write': {'Target 1', 'Target 2'}, 'activate': {'Save'}}


class LabAdapter(EpisodeAdapter):
    """Limit even a malformed learned action to this experiment's report fields."""

    def execute(self, request: dict, *, teaching: bool = False) -> dict:
        """Reject operations outside the disposable pad before calling the motor."""
        action = request['action']
        desc = action['descriptor']
        if desc['name'] not in ALLOWED.get(action['kind'], set()):
            raise PermissionError('Operation is outside the budget-reading lab')
        if not desc['scope'].startswith('KolosWorkingEpisodePad|'):
            raise PermissionError('Target is not the disposable Kolos pad')
        return super().execute(request, teaching=teaching)


def save_json(path: Path, data: Any) -> None:
    """Save evidence containing only synthetic data inside the experiment folder."""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def signature(engine: StateEngine) -> str:
    """Hash learned content, excluding transient execution state."""
    return hashlib.sha256(memory_signature(engine).encode('utf-8')).hexdigest()


def record_step(recorder: EpisodeRecorder, operation: str, name: str,
                slot: str | None = None) -> None:
    """Teacher explicitly selects a currently observed role for one demonstration."""
    objects = recorder.adapter.observer.observe()
    recorder.capture(operation, by_name(objects, name)['id'], source=slot)


def teach(engine: StateEngine, output: Path) -> dict:
    """Show one sequence on real native controls; teach only verified receipts."""
    with pad('DEMO-01', source2='100') as observer:
        before = observer.observe()
        try:
            engine.start_episode(QUERY, before)
        except ValueError as exc:
            untrained = {'refused': True, 'reason': str(exc), 'actions_sent': 0}
        else:
            raise AssertionError('The untrained engine unexpectedly knew the command')
        recorder = EpisodeRecorder(LabAdapter(observer, allow=lambda: True), QUERY)
        for index in (1, 2):
            record_step(recorder, 'read', f'Source {index}')
            record_step(recorder, 'write', f'Target {index}', f'v{index-1}')
        record_step(recorder, 'activate', 'Save')
        record = recorder.finish()
        read_only = clone(record)
        read_only['receipts'] = read_only['receipts'][:1]
        try:
            StateEngine().learn_episode(read_only)
        except ValueError as exc:
            read_only_check = {'supported': False, 'reason': str(exc)}
        else:
            raise AssertionError('Read-only episode support changed; review the experiment')
        engine.learn_episode(record)
        save_json(output / 'demonstration.json', record)
        return {'untrained': untrained, 'read_only_episode': read_only_check,
                'demonstrations': len(engine.model['learningLog']),
                'training_sku': 'DEMO-01', 'training_budget': '100',
                'operations': [r['action']['kind'] for r in record['receipts']],
                'source_bounds': by_name(before, 'Source 2')['bbox'],
                'memory_sha256': signature(engine)}


def drive(engine: StateEngine, adapter: LabAdapter) -> dict:
    """Run only kernel-selected actions, with no expected SKU or budget argument."""
    trace: list[dict] = []
    error = None
    for _ in range(80):
        if engine.model['status'] not in ('running', 'waiting'):
            break
        engine.observe(adapter.observer.observe())
        event = engine.tick()
        if event['kind'] != 'dispatch':
            continue
        request = clone(engine.model['pending'])
        action = request['action']
        step = {'kind': action['kind'], 'role': action['descriptor']['name']}
        if action['kind'] == 'write':
            step['value'] = action['value']
        trace.append(step)
        try:
            receipt = adapter.execute(request)
        except Indeterminate as exc:
            error = str(exc)
            break
        if action['kind'] == 'read':
            step['observed_value'] = bind(receipt['after'], action['descriptor'])['value']
        step['verified_by'] = receipt['verified_by']
        engine.accept_receipt(receipt)
    return {'trace': trace, 'error': error, 'status': engine.model['status']}


def retry_is_refused(engine: StateEngine, adapter: LabAdapter) -> bool:
    """Confirm an uncertain Save is never sent to the native window twice."""
    pending = clone(engine.model['pending'])
    count = len(adapter.sent)
    try:
        adapter.execute(pending)
    except Indeterminate:
        return len(adapter.sent) == count
    return False


def replay(engine: StateEngine, sku: str, budget: str, *, layout: int = 0,
           fail_save: bool = False) -> dict:
    """Supply new data to the independent window and assess observed results."""
    engine.reset()
    frozen = signature(engine)
    with pad(sku, source2=budget, layout=layout, fail_save=fail_save) as observer:
        before = observer.observe()
        adapter = LabAdapter(observer, allow=lambda: True, timeout=1)
        engine.start_episode(QUERY, before)
        result = drive(engine, adapter)
        after = observer.observe()
        fields = {o['descriptor']['name']: o['value'] for o in after['objects'] if o['readable']}
        checks = {'sources_unchanged': fields['Source 1'] == sku and fields['Source 2'] == budget,
                  'report_exact': fields['Target 1'] == sku and fields['Target 2'] == budget,
                  'unrelated_unchanged': fields['Unrelated'] == 'do not touch',
                  'memory_unchanged': signature(engine) == frozen,
                  'five_operations_only': len(adapter.sent) == 5}
        if fail_save:
            checks.update(no_false_success=result['status'] != 'complete' and bool(result['error']),
                          saved_unchanged=fields['Saved 1'] == fields['Saved 2'] == '<not saved>',
                          retry_refused=retry_is_refused(engine, adapter))
        else:
            checks.update(complete=result['status'] == 'complete' and result['error'] is None,
                          saved_exact=fields['Saved 1'] == sku and fields['Saved 2'] == budget,
                          working_memory_cleared=not engine.model['episode']['working'])
        return dict(result, sku=sku, budget=budget, layout=layout, fail_save=fail_save,
                    fields=fields, checks=checks, passed=all(checks.values()),
                    source_runtime_id=by_name(before, 'Source 2')['id'],
                    source_bounds=by_name(before, 'Source 2')['bbox'])


def missing_budget(engine: StateEngine) -> dict:
    """A window without the learned second source must be rejected before input."""
    engine.reset()
    with pad('DEMO-NO-BUDGET') as observer:
        adapter = LabAdapter(observer, allow=lambda: True)
        try:
            engine.start_episode(QUERY, observer.observe())
        except ValueError as exc:
            return {'passed': not adapter.sent, 'reason': str(exc), 'actions_sent': len(adapter.sent)}
        return {'passed': False, 'reason': 'Missing role was not rejected'}


def reload_in_child(output: Path) -> dict:
    """Verify persistence in a new Python process using only the lab memory."""
    result = subprocess.run([sys.executable, '-B', '-m', 'tests.desktop.budget_read_experiment',
                             '--reload-from', str(output)], cwd=ROOT, capture_output=True,
                            text=True, encoding='utf-8', timeout=45)
    if result.returncode:
        raise RuntimeError('Reload process failed: ' + result.stderr[-2000:] + result.stdout[-2000:])
    return json.loads((output / 'reload-result.json').read_text(encoding='utf-8'))


def experiment(output: Path, report: dict) -> None:
    """Run one demonstration, three repeats, a process restart and two failures."""
    engine = StateEngine()
    report['teaching'] = teach(engine, output)
    print('One demonstration recorded and learned.', flush=True)
    report['replays'] = []
    for sku, budget, layout in [('DEMO-01', '175', 0), ('DEMO-02', '0', 1), ('DEMO-03', '260', 1)]:
        row = replay(engine, sku, budget, layout=layout)
        report['replays'].append(row)
        print(json.dumps({'sku': sku, 'budget': budget, 'passed': row['passed']}), flush=True)
    engine.reset()
    store = Store(output / 'memory')
    try:
        store.save(engine)
    finally:
        store.close()
    report['reload'] = reload_in_child(output)
    report['missing_budget'] = missing_budget(engine)
    report['failed_save'] = replay(engine, 'DEMO-05', '310', layout=1, fail_save=True)
    report['passed'] = (all(row['passed'] for row in report['replays']) and
                        report['reload']['passed'] and report['missing_budget']['passed'] and
                        report['failed_save']['passed'])


def main() -> int:
    """Keep all generated evidence and memory under the ignored test-output root."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--reload-from', type=Path)
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output = (args.reload_from or args.output or OUTPUT_ROOT / f'budget-reading-{stamp}').resolve()
    if not output.is_relative_to(OUTPUT_ROOT.resolve()) or output == OUTPUT_ROOT.resolve():
        parser.error('Output must be a child of tests/desktop-output')
    if args.reload_from:
        store = Store(output / 'memory')
        try:
            engine = store.load()
        finally:
            store.close()
        row = replay(engine, 'DEMO-04', '430', layout=1)
        row['loaded_demonstrations'] = len(engine.model['learningLog'])
        row['new_process'] = True
        save_json(output / 'reload-result.json', row)
        return 0 if row['passed'] else 1
    output.mkdir(parents=True, exist_ok=False)
    report = {'scope': 'Native disposable Win32 controls; production Kolos engine; isolated lab memory',
              'query': QUERY, 'started_utc': datetime.now(timezone.utc).isoformat(), 'passed': False,
              'limitations': ['No browser navigation', 'No real product selection', 'No XWAY access',
                              'Named UIA roles, not visual recognition', 'Source 1 = SKU; Source 2 = budget']}
    try:
        experiment(output, report)
    except Exception as exc:
        report['error'] = {'type': type(exc).__name__, 'message': str(exc)}
    report['finished_utc'] = datetime.now(timezone.utc).isoformat()
    save_json(output / 'result.json', report)
    print(json.dumps({'passed': report['passed'], 'evidence': str(output / 'result.json'),
                      'error': report.get('error')}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
