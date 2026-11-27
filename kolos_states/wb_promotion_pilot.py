"""Run the synthetic WB coverage lesson and compare it with direct Codex checks."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic
from uuid import uuid4

from . import automation_coverage as coverage
from .core import StateEngine
from .ipc import MAX_BYTES, atomic_json
from .programming_lab.synthesis.grammar import CMP, Predicate
from .protocol import require
from .storage import Store
from .wb_promotion_codex import Codex, CodexUnavailable, USAGE_KEYS, strict_json
from .xway_readonly.worker import digest

DATA = coverage.PROJECT / 'examples' / 'wb_promotion_pilot'
OUTPUT = coverage.PROJECT / 'tests' / 'desktop-output' / 'wb-promotion-pilot'
COMPARE_OUTPUT = coverage.PROJECT / '.local-data' / 'wb-promotion-pilot'
DEFAULT_BASE = coverage.LAB / 'shared-memory' / 'memory.json'
STEPS = ('A', 'B', 'C', 'D')
LESSON = 'Для каждой ожидаемой акции требуется ровно две свежие выгрузки.'
OPERATION = 'exact_fresh_exports'
SCHEMA = 'kolos-wb-promotion-pilot/1'
RESULT_FIELDS = ('missing_ids', 'complete_ids', 'excess_fresh_ids', 'duplicate_ids',
                 'failed_ids', 'stale_ids', 'unexpected_ids')


def object_schema(properties: dict) -> dict:
    return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)


RULE_SCHEMA = object_schema(dict(rule_version=dict(type='string', enum=['v2']),
                                 operation=dict(type='string', enum=[OPERATION]),
                                 fresh_exports=dict(type='integer')))
RESULT_SCHEMA = object_schema({key: dict(type='array', items=dict(type='string')) for key in RESULT_FIELDS})


def read(path: Path) -> object:
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES, 'Размер файла превышает 4 МБ')
    return strict_json(raw.decode('utf-8'))


def fields(value: object, names: tuple[str, ...], context: str) -> dict:
    require(type(value) is dict and set(value) == set(names), f'Неверные поля: {context}')
    return value


def timestamp(value: object):
    require(type(value) is str and 0 < len(value) <= 64, 'Некорректное поле observed_at')
    return coverage.timezone_stamp(value)


def validate_manifest(raw: object) -> dict:
    data = fields(raw, ('rule_version', 'observed_at', 'expected_ids', 'manifest'), 'манифест')
    require(data['rule_version'] in ('v1', 'v2'), 'Неподдерживаемая версия правила')
    timestamp(data['observed_at'])
    manifest = fields(data['manifest'], ('expected_promotions', 'unique_products', 'collected', 'failed'), 'manifest')
    for key in ('expected_promotions', 'unique_products'):
        require(type(manifest[key]) is int and manifest[key] >= 0, f'Некорректное поле {key}')
    expected = data['expected_ids']
    require(type(expected) is list, 'Поле expected_ids должно быть списком')
    ids = [coverage.identifier(key) for key in expected]
    require(len(ids) == len(set(ids)) == manifest['expected_promotions'], 'Список expected_ids не совпадает с календарём')
    projected = dict(expected_promotions=len(ids), unique_products=manifest['unique_products'])
    for key in ('collected', 'failed'):
        require(type(manifest[key]) is list, f'Поле {key} должно быть списком')
        rows = []
        for value in manifest[key]:
            names = ('promotion_id', 'observed_at') if key == 'collected' else ('promotion_id',)
            fields(value, names, key)
            row = dict(promotion_id=coverage.identifier(value['promotion_id']))
            if key == 'collected':
                timestamp(value['observed_at'])
                row['observed_at'] = value['observed_at']
            rows.append(row)
        projected[key] = rows
    return dict(rule_version=data['rule_version'], observed_at=data['observed_at'],
                expected_ids=ids, manifest=projected)


def validate_answer(raw: object) -> dict:
    result = fields(raw, RESULT_FIELDS, 'результат проверки')
    canonical = {}
    for key, values in result.items():
        require(type(values) is list and all(type(value) is str for value in values), f'Поле {key} должно быть списком ID')
        ids = [coverage.identifier(value) for value in values]
        require(len(ids) == len(set(ids)), f'Повтор ID в поле {key}')
        canonical[key] = sorted(ids)
    return canonical


def validate_rule(raw: object) -> dict:
    rule = fields(raw, ('rule_version', 'operation', 'fresh_exports'), 'правило')
    require(rule['rule_version'] == 'v2' and rule['operation'] == OPERATION, 'Неподдерживаемая операция урока')
    limit = rule['fresh_exports']
    require(type(limit) is int and 0 < limit <= MAX_BYTES, 'fresh_exports должен быть допустимым положительным целым')
    return rule


def classify(data: dict, threshold: int, snapshot: Path | None = None) -> tuple[dict, str | None]:
    counts, facts = coverage.promotion_observation(data, timestamp(data['observed_at']))
    if data['rule_version'] == 'v1':
        require(snapshot is not None, 'Необходимо исходное правило v1')
        gaps, memory_hash = coverage.exceptions(counts, snapshot)
        incomplete = set(gaps)
    else:
        predicate = Predicate(None, '!=', threshold)
        incomplete = {key for key, count in counts.items() if CMP[predicate.op](count, predicate.threshold)}
        memory_hash = None
    result = dict(missing_ids=[key for key in counts if key in incomplete and counts[key] < threshold],
                  complete_ids=[key for key in counts if key not in incomplete],
                  excess_fresh_ids=[key for key in counts if key in incomplete and counts[key] > threshold],
                  duplicate_ids=facts['duplicate_ids'] if data['rule_version'] == 'v1' else [],
                  failed_ids=facts['failed_ids'], stale_ids=facts['stale_ids'], unexpected_ids=facts['unexpected_ids'])
    return result, memory_hash


def _remember_rule(engine: StateEngine, rule: dict, checks: int) -> None:
    coverage._remember(engine, f'wb-promotion/{rule["rule_version"]}/{digest(rule)}', checks, 0, exact=True)


def _metadata(rule: dict, memory: dict) -> dict:
    return dict(schema=SCHEMA, rule_version=rule['rule_version'], rule_sha256=digest(rule), memory_sha256=digest(memory))


def publish_rule(folder: Path, rule: dict, original: dict, controls: tuple[tuple[dict, dict], ...]) -> dict:
    validate_rule(rule)
    require(len(controls) > 0, 'Нет независимых проверок правила')
    for manifest, expected in controls:
        actual, _ = classify(manifest, rule['fresh_exports'])
        require(actual == expected, 'Кандидат расходится с эталоном манифеста')
    engine = Store.restore_snapshot(original)
    _remember_rule(engine, rule, len(controls))
    folder.mkdir(exist_ok=False)
    store = Store(folder)
    try:
        store.save(engine, preserve_attempt=True)
    finally:
        store.close()
    atomic_json(folder / 'rule.json', rule)
    metadata = _metadata(rule, read(folder / 'memory.json'))
    _verify_rule(folder, metadata)
    atomic_json(folder / 'published.json', metadata)
    return metadata


def _verify_rule(folder: Path, metadata: dict) -> dict:
    rule = validate_rule(read(folder / 'rule.json'))
    memory = read(folder / 'memory.json')
    require(metadata == _metadata(rule, memory), 'Отпечатки снимка или правила не совпадают')
    engine = Store.restore_snapshot(memory)
    require(coverage._activation(engine, f'wb-promotion/{rule["rule_version"]}/{digest(rule)}') > 0,
            'В снимке нет подтверждения этого урока')
    return rule


def load_rule(folder: Path) -> tuple[dict, dict]:
    require((folder / 'published.json').is_file(), 'Версия не опубликована. Требуется урок или новая серия')
    metadata = read(folder / 'published.json')
    return _verify_rule(folder, metadata), metadata


def _offline(event: str, _: tuple) -> None:
    if event.startswith(('socket.', 'subprocess.', 'os.spawn', 'os.exec')) or event in ('os.system', 'os.startfile'):
        raise PermissionError('В повторном процессе выключены сеть и внешние вызовы')


def replay(folder: Path, data: dict) -> dict:
    require(data['rule_version'] == 'v2', 'Повтор поддерживает только учебную версию')
    rule, evidence = load_rule(folder)
    result, _ = classify(data, rule['fresh_exports'])
    return dict(result=result, pid=os.getpid(), run_id=uuid4().hex, codex_exec_count=0,
                input_sha256=digest(data), **evidence)


def replay_process(folder: Path, data: dict) -> dict:
    run = subprocess.run([sys.executable, '-B', '-m', __spec__.name, '_repeat', str(folder)],
                         input=json.dumps(data, ensure_ascii=False), capture_output=True,
                         encoding='utf-8', timeout=30, cwd=coverage.PROJECT)
    require(run.returncode == 0, 'Проверьте журнал повторного процесса: ' + run.stderr.strip()[:250])
    receipt = json.loads(run.stdout)
    require(receipt['pid'] != os.getpid() and receipt['codex_exec_count'] == 0
            and receipt['input_sha256'] == digest(data), 'Неверная квитанция повтора')
    return receipt


def _base(folder: Path, source: Path | None) -> dict:
    base = folder / 'base'
    if source is None:
        store = Store(base)
        try:
            store.save(StateEngine(), preserve_attempt=True)
        finally:
            store.close()
    else:
        original = read(source)
        Store.restore_snapshot(original)
        atomic_json(base / 'memory.json', original)
    coverage.teach(folder / 'v1', base)
    return read(folder / 'v1' / 'memory.json')


def _prompt(data: dict, *, teach: bool) -> str:
    if teach:
        instruction = ('Преобразуй данную инструкцию в декларативное правило JSON. '
                       f'rule_version=v2, operation={OPERATION}, fresh_exports — число свежих файлов на акцию. '
                       f'Инструкция владельца: {LESSON}')
    else:
        instruction = ('Проверь синтетический манифест и выдай JSON строго по схеме. '
                       'Нужна ровно одна свежая выгрузка для v1 или ровно две для v2. '
                       'Для каждого expected_ids сравни количество свежих строк collected с нормой. '
                       'Свежая строка имеет ту же календарную дату в МСК и время не позже observed_at. '
                       'Другие строки collected дают stale_ids, строки failed дают failed_ids. '
                       'В v1 duplicate_ids — ID с более чем одной попыткой среди всех строк collected и failed. '
                       'В v2 duplicate_ids — пустой список, излишек показывается в excess_fresh_ids. '
                       'missing_ids — ожидаемые ID с меньшим числом свежих строк, complete_ids — с равным, '
                       'excess_fresh_ids — с большим. unexpected_ids — замеченные ID вне expected_ids. '
                       'ID без строк имеет число 0. Возвращай массивы уникальных строк ID.')
    return ('Работай только с этим синтетическим входом. Инструменты не нужны. '
            + instruction + '\n' + json.dumps(data, ensure_ascii=False, sort_keys=True))


def _usage(value: int | None) -> dict:
    return dict.fromkeys(USAGE_KEYS, value)


def _totals(records: dict, steps: str) -> dict:
    rows = [records[step] for step in steps]
    partial = {key: sum(row['usage'][key] or 0 for row in rows) for key in USAGE_KEYS}
    complete = all(row['status'] != 'not_run' and all(v is not None for v in row['usage'].values()) for row in rows)
    return dict(known=partial, complete=complete,
                total_tokens=partial['input_tokens'] + partial['output_tokens'] if complete else None,
                codex_exec_count=sum(row['codex_exec_count'] for row in rows),
                correct=all(row['status'] == 'passed' for row in rows))


def _summary(report: dict) -> dict:
    result = {}
    for name, steps in (('cycle', 'ABCD'), ('lesson_and_repeat', 'BC')):
        kolos = _totals(report['kolos'], steps)
        direct = _totals(report['direct_codex'], steps)
        comparable = report['mode'] == 'compare' and all(row['correct'] and row['complete'] for row in (kolos, direct))
        result[name] = dict(kolos=kolos, direct_codex=direct,
                            saved_tokens=direct['total_tokens'] - kolos['total_tokens'] if comparable else None)
    return result


def _step(data: dict, data_source: str) -> dict:
    return dict(status='not_run', rule_version=data['rule_version'], input_sha256=digest(data),
                observed_at=data['observed_at'], mode=data_source, codex_exec_count=0, usage=_usage(None))


def _call(folder: Path, record: dict, data: dict, adapter: Codex, *, teach: bool) -> dict:
    # Keep evidence that the one allowed attempt was reserved, even after interruption.
    folder.mkdir(exist_ok=False)
    record.update(status='pending', usage=_usage(None))
    atomic_json(folder / 'attempt.json', record)
    reply = adapter(_prompt(data, teach=teach), RULE_SCHEMA if teach else RESULT_SCHEMA)
    record.update({key: reply[key] for key in ('usage', 'codex_exec_count', 'completed_turns', 'failure', 'seconds')})
    record['status'] = 'received' if reply['failure'] is None else 'failed'
    atomic_json(folder / 'attempt.json', record)
    require(reply['failure'] is None, f"{reply['failure']}: проверьте доступ и профиль Codex. Квитанция сохранена")
    return reply['answer']


def _lesson(folder: Path, record: dict, data: dict, adapter: Codex | None, original: dict,
            controls: tuple[tuple[dict, dict], ...]) -> tuple[dict, dict]:
    if adapter is None:
        candidate = dict(rule_version='v2', operation=OPERATION, fresh_exports=2)
        record.update(mode='simulated_lesson', usage=_usage(0))
    else:
        candidate = _call(folder / 'lesson', record, data, adapter, teach=True)
    metadata = publish_rule(folder / 'v2', candidate, original, controls)
    rule, _ = load_rule(folder / 'v2')
    result, _ = classify(data, rule['fresh_exports'])
    return result, metadata


def run_series(folder: Path, model: str | None = None, source: Path | None = None) -> dict:
    fixtures = fields(read(DATA / 'manifests.json'), STEPS, 'набор манифестов')
    truth = fields(read(DATA / 'expected.json'), STEPS, 'эталоны')
    data = {key: validate_manifest(value) for key, value in fixtures.items()}
    expected = {key: validate_answer(value) for key, value in truth.items()}
    require(tuple(data[key]['rule_version'] for key in STEPS) == ('v1', 'v2', 'v2', 'v1'), 'Неверный порядок версий')
    require(len({key for row in data.values() for key in row['expected_ids']}) == sum(len(row['expected_ids']) for row in data.values()),
            'Манифесты должны иметь разные ожидаемые ID')
    folder.mkdir(parents=True, exist_ok=False)
    report = dict(schema=SCHEMA, series_id=folder.name, mode='compare' if model else 'local', status='running',
                  model=model, kolos={key: _step(data[key], 'kolos') for key in STEPS},
                  direct_codex={key: _step(data[key], 'direct_codex') for key in STEPS})
    report_path = folder / 'report.json'
    active = None
    started = monotonic()
    atomic_json(report_path, report)
    try:
        require(model is None or source is not None, 'Для живого замера нужен исходный memory.json')
        original = _base(folder, source)
        report.update(initial_memory_sha256=digest(original), memory_source='local_snapshot' if source else 'test_store')
        with TemporaryDirectory(prefix='kolos-wb-codex-') if model else nullcontext() as scratch:
            adapter = Codex(model, Path(scratch).resolve()) if model else None
            if adapter:
                report['codex_version'] = adapter.version
            lesson_evidence = None
            for key in STEPS:
                active = report['kolos'][key]
                active.update(run_id=uuid4().hex, usage=_usage(0), pid=os.getpid())
                if key == 'B':
                    result, lesson_evidence = _lesson(folder, active, data[key], adapter, original,
                                                      tuple((data[name], expected[name]) for name in ('B', 'C')))
                    active.update(lesson_evidence)
                elif key == 'C':
                    receipt = replay_process(folder / 'v2', data[key])
                    require(all(receipt[name] == value for name, value in lesson_evidence.items()),
                            'Повтор загрузил другой снимок или правило')
                    active.update(receipt)
                    result = receipt['result']
                else:
                    result, sha = classify(data[key], 1, folder / 'v1')
                    active['memory_sha256'] = sha
                active.update(result=result, status='passed' if result == expected[key] else 'failed')
                atomic_json(report_path, report)
                require(active['status'] == 'passed', f'Колос: эталон манифеста {key} не совпал')
            if adapter:
                for key in STEPS:
                    active = report['direct_codex'][key]
                    active['run_id'] = uuid4().hex
                    answer = _call(folder / f'direct-{key}', active, data[key], adapter, teach=False)
                    result = validate_answer(answer)
                    active.update(result=result, status='passed' if result == expected[key] else 'failed')
                    atomic_json(report_path, report)
                require(all(row['status'] == 'passed' for row in report['direct_codex'].values()),
                        'Одна или несколько прямых проверок не совпали с эталоном')
        report['status'] = 'passed'
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        if active is not None and active['status'] != 'passed':
            active.update(status='failed', reason=str(error))
        report.update(status='unavailable' if isinstance(error, CodexUnavailable) else 'failed', reason=str(error))
    report.update(seconds=round(monotonic() - started, 3), summary=_summary(report))
    if model and report['status'] == 'passed' and report['summary']['cycle']['saved_tokens'] is None:
        report.update(status='incomplete_usage', reason='Доступна только часть usage. Откройте квитанцию серии')
    atomic_json(report_path, report)
    return report


def _worker(folder: Path) -> int:
    sys.addaudithook(_offline)
    for event in ('socket.connect', 'subprocess.Popen'):
        try:
            sys.audit(event)
        except PermissionError:
            continue
        raise ValueError('Повтор не защищён от внешнего вызова')
    raw = sys.stdin.read(MAX_BYTES + 1)
    require(len(raw.encode('utf-8')) <= MAX_BYTES, 'Размер манифеста превышает 4 МБ')
    data = validate_manifest(strict_json(raw))
    print(json.dumps(replay(folder, data), ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    if len(args) == 2 and args[0] == '_repeat':
        try:
            return _worker(Path(args[1]))
        except (OSError, ValueError) as error:
            print(str(error), file=sys.stderr)
            return 1
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest='mode', required=True)
    subcommands.add_parser('local', help='Тестовый урок и новый процесс без Codex и без рабочей памяти')
    compare = subcommands.add_parser('compare', help='Один урок Codex и четыре прямые проверки при успешной серии')
    compare.add_argument('--model', required=True, help='Модель Codex для обеих веток')
    compare.add_argument('--base-snapshot', type=Path, default=DEFAULT_BASE,
                         help='Локальный исходный memory.json. Файл копируется в серию, в Codex передаются только фикстуры')
    options = parser.parse_args(args)
    output = COMPARE_OUTPUT if options.mode == 'compare' else OUTPUT
    folder = output / f'run-{uuid4().hex}'
    try:
        model = options.model if options.mode == 'compare' else None
        if options.mode == 'compare':
            require(isinstance(model, str) and bool(model.strip()), 'Укажите непустое имя модели')
        result = run_series(folder, model, options.base_snapshot if model else None)
    except (OSError, ValueError) as error:
        result = dict(status='failed', reason=str(error))
    receipt = folder / 'report.json'
    if receipt.is_file():
        result['report_path'] = str(receipt)
    print(json.dumps(result, ensure_ascii=False))
    return int(result['status'] != 'passed')


if __name__ == '__main__':
    raise SystemExit(main())
