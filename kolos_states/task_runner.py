"""Run a checked, versioned task locally and teach it once on a cache miss."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from uuid import uuid4

from . import automation_coverage as coverage
from . import runner_providers
from .ipc import MAX_BYTES, atomic_json
from .programming_lab.synthesis.grammar import CMP, Predicate, Recipe, render
from .programming_lab.synthesis.judge import apply, same
from .programming_lab.synthesis.spec import Task, item_shape, result_kind
from .protocol import require
from .storage import Store
from .wb_promotion_codex import USAGE_KEYS, strict_json
from .wb_promotion_pilot import RULE_SCHEMA, classify, fields, object_schema, validate_answer, validate_manifest, validate_rule
from .xway_readonly.worker import digest

SCHEMA = 'kolos-task-runner/1'
SAMPLES = Path(__file__).resolve().parents[1] / 'examples' / 'task_runner'
TABLE = Task('run_rule', 'rows', (), ())
COLUMN_TYPES = {'integer': int, 'text': str}
KINDS = ('wb-promotions', 'table')
PROVIDERS = (*runner_providers.PROVIDERS, 'none')
INTEGER = {'type': 'integer'}
COLUMN = {'type': ['string', 'null']}
PREDICATE_SCHEMA = object_schema(dict(column={'type': 'string'}, op={'enum': list(CMP), 'type': 'string'},
                                      threshold=INTEGER))
TABLE_SCHEMA = object_schema(dict(reduce={'type': 'string', 'enum': ['filter', 'count', 'sum']},
                                  value=COLUMN, group=COLUMN, predicate={'anyOf': [PREDICATE_SCHEMA, {'type': 'null'}]}))


def default_state() -> Path:
    local = os.environ.get('LOCALAPPDATA')
    return Path(local) / 'Kolos' / 'Runner' if local else Path.home() / '.kolos' / 'runner'


def read_json(path: Path) -> object:
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES, 'Размер JSON превышает 4 МБ.')
    return strict_json(raw.decode('utf-8-sig'))


def _rows(task: dict, data: object) -> list:
    require(type(data) is list, 'Вход таблицы должен быть массивом записей.')
    shape = tuple(sorted((name, COLUMN_TYPES[kind]) for name, kind in task['columns'].items()))
    for row in data:
        require(type(row) is dict and item_shape(row) == shape, 'Запись не соответствует полям таблицы.')
    return data


def _input(task: dict, raw: object) -> dict | list:
    if task['kind'] == 'wb-promotions':
        data = validate_manifest(raw)
        require(data['rule_version'] == 'v2', 'Для задачи WB используйте манифест v2.')
        return data
    return _rows(task, raw)


def _definition(raw: object) -> dict:
    require(type(raw) is dict and raw.get('kind') in KINDS, 'Доступные типы задачи: wb-promotions и table.')
    columns = ('columns', 'result') if raw['kind'] == 'table' else ()
    task = fields(raw, ('id', 'kind', 'instruction', 'checks', *columns), 'описание задачи')
    name = task['id']
    require(type(name) is str and re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,63}', name), 'Неверный ID задачи.')
    instruction = task['instruction']
    require(type(instruction) is str and 0 < len(instruction.strip()) <= 2000, 'Укажите инструкцию до 2000 символов.')
    if columns:
        schema = task['columns']
        require(type(schema) is dict and 0 < len(schema) <= 24 and all(
            name.strip() and len(name) <= 64 and type(kind) is str and kind in COLUMN_TYPES for name, kind in schema.items()),
            'Укажите поля таблицы с типами integer или text.')
        require(task['result'] in ('number', 'mapping', 'list'), 'Укажите результат number, mapping или list.')
    checks = task['checks']
    require(type(checks) is list and 2 <= len(checks) <= 20, 'Нужны от двух до двадцати проверочных примеров.')
    normalized = []
    for raw_case in checks:
        case = fields(raw_case, ('input', 'expected'), 'проверочный пример')
        data = _input(task, case['input'])
        expected = case['expected']
        if columns:
            require(result_kind(expected) == task['result'], 'Результат примера не соответствует типу задачи.')
            if task['result'] == 'list':
                _rows(task, expected)
        else:
            expected = validate_answer(expected)
        normalized.append(dict(input=data, expected=expected))
    require(len({digest(case['input']) for case in normalized}) == len(checks), 'Проверочные входы должны различаться.')
    return dict(task, instruction=instruction.strip(), checks=normalized)


def _recipe(task: dict, raw: object) -> Recipe:
    rule = fields(raw, ('reduce', 'value', 'group', 'predicate'), 'табличное правило')
    reduce, value, group = (rule[key] for key in ('reduce', 'value', 'group'))
    numbers = {name for name, kind in task['columns'].items() if kind == 'integer'}
    texts = {name for name, kind in task['columns'].items() if kind == 'text'}
    require(reduce in ('filter', 'count', 'sum'), 'Неизвестная табличная операция.')
    require((type(value) is str and value in numbers) if reduce == 'sum' else value is None,
            'Для суммы требуется целочисленное поле, для остальных операций value должен быть null.')
    kind = task['result']
    require((reduce == 'filter') == (kind == 'list'), 'Операция не соответствует типу результата.')
    require((type(group) is str and group in texts) if kind == 'mapping' else group is None,
            'Группировка требует текстового поля и результата mapping.')
    predicate = rule['predicate']
    if predicate is not None:
        condition = fields(predicate, ('column', 'op', 'threshold'), 'условие')
        require(type(condition['column']) is str and condition['column'] in numbers and type(condition['op']) is str
                and condition['op'] in CMP and type(condition['threshold']) is int,
                'Условие должно сравнивать целочисленное поле с целым порогом.')
        predicate = Predicate(**condition)
    return Recipe(reduce, value, group, predicate)


def _executor(task: dict, rule: object):
    if task['kind'] == 'wb-promotions':
        limit = validate_rule(rule)['fresh_exports']
        return lambda data: classify(data, limit)[0]
    source = render(TABLE, _recipe(task, rule))
    return lambda data: apply(source, TABLE.function, TABLE.parameter, data)


def _lesson(task: dict) -> tuple[str, dict]:
    if task['kind'] == 'wb-promotions':
        guidance = ('Выведи v2 exact_fresh_exports. fresh_exports — ровно столько свежих файлов нужно на акцию.', RULE_SCHEMA)
    else:
        columns = json.dumps(task['columns'], ensure_ascii=False)
        guidance = (f'Поля таблицы: {columns}. Тип результата: {task["result"]}. '
                    'Фильтр возвращает выбранные записи. count считает записи, sum суммирует поле value. '
                    'group — текстовое поле группировки. predicate — одно сравнение целочисленного поля, '
                    'применяется до операции. Для отсутствующих value, group и predicate укажи null.', TABLE_SCHEMA)
    return (f'Преобразуй инструкцию в структурированное правило. Инструменты не нужны. {guidance[0]}\n'
            f'Инструкция: {task["instruction"]}', guidance[1])


def _feature(definition_hash: str, rule_hash: str) -> str:
    return f'runner/{definition_hash}/{rule_hash}'


def _load(store: Store, path: Path, definition_hash: str) -> dict:
    receipt = fields(read_json(path), ('schema', 'task_sha256', 'rule_sha256', 'memory_sha256', 'rule'), 'сохранённое правило')
    rule_hash = digest(receipt['rule'])
    require(receipt['schema'] == SCHEMA and receipt['task_sha256'] == definition_hash
            and receipt['rule_sha256'] == rule_hash, 'Сохранённое правило повреждено.')
    memory = read_json(store.path / 'memory.json')
    require(digest(memory) == receipt['memory_sha256'], 'Снимок памяти правила повреждён.')
    engine = Store.restore_snapshot(memory)
    require(coverage._activation(engine, _feature(definition_hash, rule_hash)) > 0, 'В памяти нет подтверждения правила.')
    return receipt


def _publish(store: Store, path: Path, definition_hash: str, rule: dict, checks: int) -> dict:
    rule_hash = digest(rule)
    engine = store.load()
    coverage._remember(engine, _feature(definition_hash, rule_hash), checks, 0, exact=True)
    store.save(engine, preserve_attempt=True)
    publication = dict(schema=SCHEMA, task_sha256=definition_hash, rule_sha256=rule_hash, rule=rule,
                       memory_sha256=digest(read_json(store.path / 'memory.json')))
    atomic_json(path, publication)
    return publication


def _execute(task: dict, data: dict | list, state: Path, model: str | None, report: dict, report_path: Path) -> None:
    definition_hash = digest({'schema': SCHEMA, 'task': task})
    report.update(task_id=task['id'], task_sha256=definition_hash, input_sha256=digest(data))
    folder = state / 'rules' / definition_hash
    path = folder / 'published.json'
    store = Store(folder)
    try:
        if path.exists():
            saved = _load(store, path, definition_hash)
            result = _executor(task, saved['rule'])(data)
            report.update(mode='local', result=result, rule_sha256=saved['rule_sha256'])
            return
        provider = report['provider']
        if provider == 'none':
            report.update(status='needs_lesson', reason='Для этой задачи нужен первый урок. Выберите Codex или Claude Code.')
            return
        if (folder / 'memory.json').exists():
            store.load()  # Validate an interrupted publication before paying for another lesson.
        report.update(mode='lesson', status='learning', model_calls=None, usage=dict.fromkeys(USAGE_KEYS))
        atomic_json(report_path, report)
        prompt, schema = _lesson(task)
        try:
            reply = runner_providers.teach(provider, model, prompt, schema)
        except (OSError, ValueError):
            report.update(model_calls=0, usage=dict.fromkeys(USAGE_KEYS, 0))
            raise
        report.update(model_calls=reply['codex_exec_count'], usage=reply['usage'])
        atomic_json(report_path, report)
        require(reply['failure'] is None, str(reply['failure']))
        rule = reply['answer']
        execute = _executor(task, rule)
        for index, case in enumerate(task['checks'], start=1):
            require(same(execute(case['input']), case['expected']),
                    f'Правило не прошло проверочный пример {index}. Урок не сохранён.')
        result = execute(data)
        saved = _publish(store, path, definition_hash, rule, len(task['checks']))
        report.update(status='ok', result=result, rule_sha256=saved['rule_sha256'])
    finally:
        store.close()


def run(task_file: Path, input_file: Path, *, state: Path, provider: str = 'codex', model: str | None = None) -> dict:
    run_id = uuid4().hex
    path = state / 'runs' / (run_id + '.json')
    report = dict(schema=SCHEMA, status='ok', run_id=run_id, pid=os.getpid(), model=model, provider=provider,
                  mode=None, model_calls=0, usage=dict.fromkeys(USAGE_KEYS, 0), report_path=str(path))
    try:
        require(provider in PROVIDERS, 'Неизвестный провайдер обучения.')
        task = _definition(read_json(task_file))
        data = _input(task, read_json(input_file))
        _execute(task, data, state, model, report, path)
    except (OSError, ValueError, RuntimeError) as error:
        report.update(status='error', reason=str(error))
    atomic_json(path, report)
    return report


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Колос — сохранённые правила и обучение через модель.')
    commands = parser.add_subparsers(dest='command', required=True)
    cli = commands.add_parser('run', help='Проверить задание, при первом запуске запросить урок')
    cli.add_argument('task', type=Path, help='JSON с инструкцией и проверочными примерами')
    cli.add_argument('input', type=Path, help='JSON текущего входа')
    cli.add_argument('--provider', choices=PROVIDERS, default='codex')
    cli.add_argument('--model', help='Имя модели. По умолчанию модель определяет CLI провайдера.')
    cli.add_argument('--state-dir', type=Path, default=default_state())
    gui = commands.add_parser('gui', help='Открыть Колос')
    gui.add_argument('--state-dir', type=Path, default=default_state())
    args = parser.parse_args(argv)
    if args.command == 'gui':
        from .task_runner_gui import launch
        return launch(args.state_dir)
    try:
        receipt = run(args.task, args.input, state=args.state_dir, provider=args.provider, model=args.model)
    except OSError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(receipt, ensure_ascii=False))
    return {'ok': 0, 'needs_lesson': 2, 'error': 1}[receipt['status']]


if __name__ == '__main__':
    raise SystemExit(main())
