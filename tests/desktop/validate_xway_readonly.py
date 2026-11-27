"""Audit real saved XWAY trials, raw frames, graph dependence and source immutability."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path

from kolos_states.xway_readonly.worker import digest

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'tests' / 'desktop-output'
RUNS = {'trained': 'xway-readonly-trained-20261111C', 'cut': 'xway-readonly-cut-20261111B',
        'empty': 'xway-readonly-empty-20261111B', 'restored': 'xway-readonly-restored-20261111B'}
EVIDENCE = OUTPUT / 'xway-readonly-evidence-20261111'


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line]


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_chain(path: Path, *, canonical: bool) -> list[dict]:
    """Hash chains detect alteration relative to their saved digest, not a hostile author."""
    records, previous = lines(path), ''
    for sequence, item in enumerate(records, 1):
        payload = dict(item)
        signature = payload.pop('sha256')
        assert payload['sequence'] == sequence and payload['previous'] == previous, path
        if canonical:
            expected = digest(payload)
        else:
            encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
            expected = hashlib.sha256(encoded.encode('utf-8')).hexdigest()
        assert signature == expected, (path, sequence)
        previous = signature
    return records


def audit_run(name: str, directory: str) -> dict:
    """Pair every actual motor dispatch with a real kernel result and verified receipt."""
    base = OUTPUT / directory
    result = read(base / 'result.json')
    executor = check_chain(base / 'executor.jsonl', canonical=False)
    kernel = check_chain(base / 'kernel.jsonl', canonical=True)
    assert not result['frame_errors'] and result['manual_interventions'] == 0
    assert result['summary']['memory_unchanged'] and result['loaded']['network'] == 'denied'
    assert result['llm_calls_during_replay'] == 0
    assert read(base / 'report.json') == result['summary']['report']
    for filename, expected in result['source_sha256'].items():
        assert sha_file(ROOT / filename) == expected, filename
    assert all(item['event'] not in ('teach-start', 'prepare', 'teach-finish') for item in kernel)
    chosen = [item['result'] for item in kernel if item['event'] == 'next' and 'action' in item['result']]
    dispatched = [item for item in executor if item['event'] == 'dispatch']
    assert len(chosen) == len(dispatched) == result['kernel_dispatches']
    assert len({item['id'] for item in chosen}) == len(chosen)
    for selected, sent in zip(chosen, dispatched):
        assert selected['id'] == sent['id'] and selected['action'] == sent['action']
        assert sent['actor'] == 'kernel' and sent['origin'] == 'learned-graph'
    confirmations = [item for item in kernel if item['event'] == 'confirm']
    assert len(confirmations) == len(chosen)
    frames = lines(base / 'frames.jsonl')
    assert len(frames) == result['frames'] and frames
    for frame in frames:
        assert sha_file(base / 'frames' / frame['file']) == frame['sha256']
    start = next(item for item in executor if item['event'] == 'autonomous-start')
    end = next(item for item in executor if item['event'] in ('autonomous-end', 'stopped'))
    interval = (datetime.fromisoformat(end['utc']) - datetime.fromisoformat(start['utc'])).total_seconds()
    return dict(condition=name, passed=result['passed'], pid=result['loaded']['pid'],
                kernel_dispatches=len(chosen), confirmations=len(confirmations),
                browser_writes=result['browser_writes'], report=result['summary']['report'],
                memory_sha256=result['loaded']['memory_sha256'], frames=len(frames),
                autonomous_seconds=round(interval, 3), source_sha256=result['source_sha256'],
                evidence_directory=directory, journal_sha256=sha_file(base / 'kernel.jsonl'))


def validate() -> dict:
    """Expect success only with connected learned memory, under the identical executor."""
    results = {name: audit_run(name, directory) for name, directory in RUNS.items()}
    trained, restored = results['trained'], results['restored']
    assert trained['passed'] and restored['passed']
    assert trained['kernel_dispatches'] == restored['kernel_dispatches'] == 9
    assert trained['report'] == restored['report']
    assert trained['memory_sha256'] == restored['memory_sha256']
    assert len({r['pid'] for r in results.values()}) == 4
    for name, count in [('cut', 1), ('empty', 0)]:
        result = results[name]
        assert not result['passed'] and result['kernel_dispatches'] == count
        assert not result['browser_writes'] and not any(result['report'].values())
    assert all(r['source_sha256'] == trained['source_sha256'] for r in results.values())
    verification = read(EVIDENCE / 'api-verification.json')
    report = trained['report']
    assert verification['sku'] == report['sku'] and verification['wb_id'] == report['wb_id']
    assert float(report['budget'].replace('\u00a0', '').replace(' ', '').replace('₽', '')) == verification['budget']
    for name in ('trained', 'restored'):
        events = lines(OUTPUT / RUNS[name] / 'executor.jsonl')
        baseline = next(e['baseline'] for e in events if e['event'] == 'ready')
        final = read(OUTPUT / RUNS[name] / 'result.json')['final'][0]
        assert baseline == final and final['ai_enabled'] == verification['ai_enabled']
    teaching = read(OUTPUT / 'xway-readonly-teach-20261111D' / 'lesson.json')
    assert len(teaching['receipts']) == 6
    first = teaching['receipts'][0]['before']['objects']
    assert next(o['value'] for o in first if o['descriptor']['name'] == 'Product SKU') != report['sku']
    assert next(o['value'] for o in first if o['descriptor']['name'] == 'Daily budget') != report['budget']
    failures = {n: read(OUTPUT / n / 'result.json') for n in
                ('xway-readonly-trained-20261111A', 'xway-readonly-trained-20261111B')}
    assert all(not r['passed'] for r in failures.values())
    return dict(validated=True, date='2026-11-11', runs=results, independent_api=verification,
                teaching_steps=6, source_memory='xway-readonly-teach-20261111D/trained-memory/memory.json',
                preliminary_failures={n: dict(error=r['error'], dispatches=r['kernel_dispatches'])
                                      for n, r in failures.items()},
                limitations=['One held-out product, two successful repeats; not a broad reliability estimate',
                             'Fixed search->read mission and DOM adapter, not visual discovery',
                             'Bootstrap and editor reopening are mechanical code, not learned steps',
                             'No ad-setting changes; screenshot sampling, not full-motion video',
                             'Local hash chains are not externally signed attestations'])


if __name__ == '__main__':
    result = validate()
    EVIDENCE.mkdir(exist_ok=True)
    (EVIDENCE / 'validated.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(validated=True, runs={k: {n: v[n] for n in
                     ('passed', 'kernel_dispatches', 'autonomous_seconds', 'frames')} for k, v in result['runs'].items()}),
                     ensure_ascii=False, indent=2))
