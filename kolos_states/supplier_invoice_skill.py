"""Read-only skill adapter with a receipt for the input and a separate reviewer verdict."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter

from . import supplier_invoice, supplier_invoice_payments
from .ipc import MAX_BYTES, atomic_json, read_json
from .protocol import require
from .xway_readonly.campaign import run_name
from .xway_readonly.worker import digest

PROFILE = Path(__file__).resolve().parents[1] / '.local-data' / 'skill-memory' / 'supplier-invoice'
RECEIPT = 'kolos-skill-receipt/1'
CAPABILITY = 'supplier_invoice.reconcile_snapshot'
PAYMENTS_CAPABILITY = 'supplier_invoice.scan_related_payments'
INVOICE = (*supplier_invoice.IDENTITY, 'number', 'date', 'tax_mode', 'subtotal', 'vat', 'total')
INVOICE_LINE = ('article', 'unit', 'quantity', 'price', 'amount', 'vat_rate', 'variant')
ORDER = (*supplier_invoice.IDENTITY, 'number', 'state', 'total', 'price_includes_vat')
ORDER_LINE = ('code', 'name', 'supplier_article', 'unit', 'variant', 'quantity', 'amount', 'vat')
LINK = ('number', 'date', *supplier_invoice.IDENTITY, 'article', 'unit', 'code', 'variant', 'evidence')
SNAPSHOT = ('kind', 'observed_at', 'complete')
SKIP = {'invoice_unreadable', 'snapshot_unavailable', 'snapshot_incomplete', 'unsupported_case'}
CHECKS = {'invoice_source', 'order_source', 'live_order_readback', 'article_confirmation',
          'payment_snapshot', 'live_payment_readback'}
FINDINGS = {'invoice_values', 'snapshot_coverage', 'order_selection', 'line_mapping', 'arithmetic', 'other',
            'payment_link', 'payment_status', 'possible_duplicate'}
IMPROVEMENTS = {
    'invoice_unreadable': 'Добавить контрольные примеры нечитаемого счёта или пропущенного поля.',
    'snapshot_unavailable': 'Проверить сбор снимка 1С и явное сообщение об отсутствии доступа.',
    'snapshot_incomplete': 'Проверить пагинацию и комплектность строк снимка 1С.',
    'stale_snapshot': 'Перечитать 1С и добавить проверку времени снимка в адаптер навыка.',
    'unsupported_case': 'Сохранить обезличенный пример неподдерживаемого случая для отдельного теста.',
    'no_unambiguous_article_match': 'Добавить пример с новым артикулом и подтверждением в границах одного счёта.',
    'multiple_matching_orders': 'Проверить два одинаково подходящих заказа, включая отличие по договору.',
    'worker_blocked': 'Разобрать причину остановки и добавить обезличенный воспроизводимый тест.',
    'execution_unavailable': 'Проверить локальный запуск и доступность утверждённой версии памяти.',
    'input_invalid': 'Проверить схему входа и подготовку полей в навыке.',
}


def project(payload: dict) -> tuple[dict, dict, dict]:
    """Project allowed scalar fields and count dropped keys without echoing their names or values."""
    fields, excluded, missing = Counter(), Counter(), Counter()

    def pick(value: dict, allowed: tuple, group: str, children: tuple = ()) -> dict:
        require(isinstance(value, dict), 'Expected a record in ' + group)
        excluded[group] += len(value.keys() - set(allowed) - set(children))
        missing.update(group + '.' + key for key in set(allowed) - value.keys())
        result = {key: value[key] for key in allowed if key in value}
        for key, item in result.items():
            require(item is None or type(item) is bool or (type(item) is str and len(item) <= 650),
                    'Expected a scalar in ' + group + '.' + key)
            fields[group + '.' + key] += 1
        return result

    def rows(value: list, allowed: tuple, group: str) -> list:
        require(isinstance(value, list) and len(value) <= 200, 'Invalid row collection in ' + group)
        return [pick(row, allowed, group) for row in value]

    invoice = pick(payload['invoice'], INVOICE, 'invoice', ('lines', 'delivery'))
    raw_invoice = payload['invoice']
    if 'delivery' in raw_invoice:
        delivery = raw_invoice['delivery']
        invoice['delivery'] = None if delivery is None else pick(delivery, ('included', 'amount', 'vat'), 'invoice.delivery')
        fields['invoice.delivery'] += 1
    invoice['lines'] = rows(raw_invoice['lines'], INVOICE_LINE, 'invoice.lines')
    orders = payload['orders']
    require(isinstance(orders, list) and len(orders) <= 200, 'Invalid order collection')
    projected_orders = []
    for order in orders:
        result = pick(order, ORDER, 'orders', ('lines',))
        result['lines'] = rows(order['lines'], ORDER_LINE, 'orders.lines')
        projected_orders.append(result)
    links = rows(payload.get('confirmed_links', []), LINK, 'confirmed_links')
    excluded['root'] += len(payload.keys() - {'run_id', 'invoice', 'orders', 'confirmed_links', 'snapshot'})
    snapshot = pick(payload['snapshot'], SNAPSHOT, 'snapshot')
    for key in SNAPSHOT:
        fields.pop('snapshot.' + key, None)
    if 'delivery' not in invoice:
        missing['invoice.delivery'] += 1
    return dict(invoice=invoice, orders=projected_orders, confirmed_links=links), snapshot, dict(
        fields=dict(sorted(fields.items())), filtered_counts={key: count for key, count in sorted(excluded.items()) if count},
        missing_fields=dict(sorted(missing.items())),
        counts=dict(invoice_lines=len(invoice['lines']), orders=len(projected_orders),
                    order_lines=sum(len(order['lines']) for order in projected_orders), confirmed_links=len(links)),
        delivery_value='missing' if 'delivery' not in invoice else 'unknown' if invoice['delivery'] is None else 'provided')


def snapshot_status(snapshot: dict, now: datetime) -> str | None:
    require(snapshot.get('kind') in ('1c_odata', 'historical'), 'Unknown snapshot origin')
    observed = datetime.fromisoformat(snapshot['observed_at'])
    require(observed.utcoffset() is not None, 'Snapshot must have a time zone')
    if snapshot.get('complete') is not True:
        return 'snapshot_incomplete'
    if snapshot['kind'] == '1c_odata' and not timedelta(seconds=-10) <= now - observed <= timedelta(minutes=10):
        return 'stale_snapshot'
    return None


def active_memory(profile: Path) -> tuple[Path, dict]:
    binding = read_json(profile / 'active.json')
    require(isinstance(binding, dict) and set(binding) == {'version', 'sha256'}, 'No approved invoice memory')
    version = run_name(binding['version'])
    memory = profile / version / 'memory.json'
    checksum = sha256(memory.read_bytes()).hexdigest()
    require(checksum == binding['sha256'], 'Invoice memory checksum changed')
    return memory, dict(version=version, sha256=checksum)


def directory_for(root: Path, run_id: str) -> Path:
    root = root.resolve()
    directory = (root / run_name(run_id)).resolve()
    require(directory.is_relative_to(root), 'Receipt path outside the output directory')
    return directory


def run(payload: dict, root: Path, *, profile: Path = PROFILE, now: datetime | None = None,
        payments: bool = False) -> dict:
    run_id = run_name(payload['run_id'])
    directory = directory_for(root, run_id)
    started = perf_counter()
    now = now or datetime.now(timezone.utc)
    scope_limit = 'банковские выписки и полные платёжные документы' if payments else 'оплаты и выписки'
    report = dict(schema=RECEIPT, capability=PAYMENTS_CAPABILITY if payments else CAPABILITY,
                  run_id=run_id, status='not_sent',
                  created_at=now.isoformat(), snapshot=None, memory=None, executed_steps=[],
                  transmitted_fields={}, filtered_counts={}, counts={}, may_write=False,
                  outside_scope=['PDF и изображения', 'банковские реквизиты', scope_limit,
                                 'запись в 1С, таблицу и Т-Бизнес'])
    projected = snapshot = manifest = None
    issue = payload.get('skip_reason')
    try:
        if issue is not None:
            require(set(payload) == {'run_id', 'skip_reason'} and issue in SKIP, 'Invalid skip request')
        else:
            project_input = supplier_invoice_payments.project if payments else project
            projected, snapshot, manifest = project_input(payload)
            issue = snapshot_status(snapshot, now)
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        issue = 'input_invalid'
    input_binding = dict(input=projected, snapshot=snapshot, manifest=manifest,
                         skip_reason=payload.get('skip_reason') if issue in SKIP else None)
    if payments:
        input_binding['capability'] = PAYMENTS_CAPABILITY
    report['input_sha256'] = digest(input_binding)
    file = directory / 'receipt.json'
    try:
        directory.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        old = read_json(file)
        require(isinstance(old, dict) and old.get('schema') == RECEIPT and old.get('run_id') == run_id and
                old.get('input_sha256') == report['input_sha256'], 'Run ID is busy or bound to other input')
        return old
    if manifest:
        report.update(snapshot=snapshot, filtered_counts=manifest['filtered_counts'], missing_fields=manifest['missing_fields'])
        if not payments:
            report['delivery_value'] = manifest['delivery_value']
    if issue is None:
        try:
            if not payments:
                memory, reference = active_memory(profile)
                report['memory'] = reference
            report.update(transmitted_fields=manifest['fields'], counts=manifest['counts'], status='execution_started')
            handoff_path = f'execution/{run_id}/handoff.json'
            if payments:
                result = supplier_invoice_payments.scan(projected, run_id)
                atomic_json(directory / handoff_path, result)
                report['work'] = dict(related=len(result['related']), duplicate_groups=len(result['possible_duplicates']),
                                      unlinked_same_amount=len(result['unlinked_same_amount']),
                                      conflicting_documents=sum(bool(doc['conflicts']) for doc in result['related']))
            else:
                result = supplier_invoice.run(dict(projected, run_id=run_id), directory / 'execution', memory=memory)
                require(sha256(memory.read_bytes()).hexdigest() == reference['sha256'], 'Memory changed during run')
                report.update(candidates=len(result.get('scoped_orders', [])), unresolved=len(result.get('unresolved_articles', [])))
                report['work'] = dict(invoice_arithmetic_checked='invoice' in result, matched_lines=len(result.get('lines', [])))
            report.update(status=result['status'], handoff=handoff_path, handoff_sha256=digest(result),
                          executed_steps=result.get('steps', []))
            issue = result.get('reason') if result['status'] == 'needs_review' else None
            if result['status'] == 'blocked':
                issue = 'worker_blocked'
        except (AttributeError, KeyError, TypeError, ValueError, OSError):
            if report['status'] == 'execution_started':
                report['status'] = 'failed'
            issue = 'execution_unavailable'
    improvement = 'Повторить на новом счёте и сравнить время и расхождения с обычной сверкой.'
    if payments and report['status'] == 'scanned':
        improvement = ('Проверить найденные связи, назначение и роль каждого документа по источнику.'
                       if any(report['work'][key] for key in ('duplicate_groups', 'unlinked_same_amount', 'conflicting_documents')) else
                       'Проверить на счёте с частичной оплатой и несколькими назначениями.')
    report.update(issue=issue, elapsed_ms=round((perf_counter() - started) * 1000),
                  improvement=IMPROVEMENTS.get(issue, IMPROVEMENTS['worker_blocked']) if issue else improvement,
                  proposed_next=['Распределение подтверждённой доставки с проверкой округления и НДС.'])
    atomic_json(file, report)
    return report


def review(payload: dict, root: Path) -> dict:
    require(set(payload) == {'run_id', 'receipt_sha256', 'verdict', 'checks', 'findings'}, 'Invalid review fields')
    directory = directory_for(root, payload['run_id'])
    receipt = read_json(directory / 'receipt.json')
    require(isinstance(receipt, dict) and receipt.get('schema') == RECEIPT and receipt.get('run_id') == payload['run_id'] and
            receipt.get('may_write') is False and digest(receipt) == payload['receipt_sha256'], 'Review describes another run')
    if 'handoff' in receipt:
        require(receipt['handoff'] == f"execution/{receipt['run_id']}/handoff.json", 'Unexpected handoff path')
        handoff = read_json(directory / receipt['handoff'])
        require(isinstance(handoff, dict) and handoff.get('run_id') == receipt['run_id'] and
                handoff.get('may_write') is False and digest(handoff) == receipt['handoff_sha256'],
                'The reported handoff is missing or changed')
    checks, findings = payload['checks'], payload['findings']
    require(isinstance(checks, list) and all(check in CHECKS for check in checks) and len(set(checks)) == len(checks),
            'Invalid verification checks')
    require(isinstance(findings, list) and all(item in FINDINGS for item in findings) and len(set(findings)) == len(findings),
            'Invalid verification findings')
    verdict = payload['verdict']
    require(verdict in ('confirmed', 'correct_stop', 'discrepancy', 'not_verified'), 'Invalid review verdict')
    payments = receipt.get('capability') == PAYMENTS_CAPABILITY
    if verdict in ('confirmed', 'correct_stop', 'discrepancy'):
        require({'invoice_source', 'order_source'} <= set(checks), 'Invoice and order evidence are both required')
    if verdict == 'confirmed':
        require(receipt['status'] == ('scanned' if payments else 'reconciled'),
                'Only a completed payment scan can be confirmed' if payments else 'Only a reconciled result can be confirmed')
    if payments and verdict in ('confirmed', 'discrepancy'):
        require('payment_snapshot' in checks, 'Payment snapshot evidence is missing')
    require(verdict != 'correct_stop' or receipt['status'] in ('needs_review', 'blocked', 'not_sent'), 'No stop to confirm')
    if verdict == 'confirmed' and receipt['snapshot']['kind'] == '1c_odata':
        required = 'live_payment_readback' if payments else 'live_order_readback'
        require(required in checks, 'Live payment readback is missing' if payments else 'Live order readback is missing')
    require(bool(findings) == (verdict == 'discrepancy'), 'Discrepancies need a classified finding')
    result = dict(schema='kolos-skill-review/1', run_id=receipt['run_id'], receipt_sha256=digest(receipt),
                  verdict=verdict, checks=checks, findings=findings, may_write=False,
                  improvement=('Воспроизвести расхождение на обезличенном примере перед обучением.' if findings else receipt['improvement']))
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
    parser.add_argument('mode', choices=('run', 'payments', 'review'))
    parser.add_argument('--output-root', required=True, type=Path)
    args = parser.parse_args()
    sys.stdin.reconfigure(encoding='utf-8-sig')
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raw = sys.stdin.read(MAX_BYTES + 1)
        require(len(raw.encode()) <= MAX_BYTES, 'Oversized skill input')
        payload = json.loads(raw)
        if args.mode == 'review':
            result = review(payload, args.output_root)
        else:
            result = run(payload, args.output_root, payments=args.mode == 'payments')
            result = dict(result, receipt_sha256=digest(result))
    except (AttributeError, KeyError, TypeError, ValueError, OSError, OverflowError):
        print(json.dumps(dict(status='failed', reason='invalid_input_or_output_unavailable', may_write=False)))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return int(result.get('status') in ('failed', 'blocked'))


if __name__ == '__main__':
    raise SystemExit(main())
