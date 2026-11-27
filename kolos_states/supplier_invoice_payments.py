"""Find related 1C documents and possible repeat payments from a read-only projection."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
import re
from uuid import UUID

from .protocol import require

KINDS = ('payment_orders', 'bank_expenses', 'expense_requests')
SCOPE = ('order_ref', 'supplier_ref', 'buyer_ref', 'currency_ref', 'invoice_number', 'invoice_date', 'proposed_amount')
DOCUMENT = ('ref', 'number', 'supplier_ref', 'buyer_ref', 'currency_ref', 'order_refs', 'invoice_number',
            'invoice_date', 'invoice_hint', 'amount', 'deleted', 'posted', 'paid')
AMOUNT = re.compile(r'[0-9]{1,14}(?:\.[0-9]{1,2})?')


def reference(value: str) -> str:
    require(type(value) is str and len(value) == 36, 'Expected a 1C reference')
    parsed = UUID(value)
    require(bool(parsed.int), 'Empty 1C reference')
    return str(parsed)


def document_number(value: str) -> str:
    require(type(value) is str and 0 < len(value.strip()) <= 80 and value.isprintable(), 'Invalid document number')
    return value.strip()


def document_date(value: str) -> str:
    require(type(value) is str and len(value) == 10, 'Expected an ISO invoice date')
    return date.fromisoformat(value).isoformat()


def amount(value: str) -> str:
    require(type(value) is str and bool(AMOUNT.fullmatch(value)), 'Expected a decimal amount in document currency')
    return f'{Decimal(value):.2f}'


def project(payload: dict) -> tuple[dict, dict, dict]:
    fields, excluded = Counter(), Counter()

    def pick(value: dict, keys: tuple, group: str) -> dict:
        require(isinstance(value, dict) and set(keys) <= value.keys(), 'Incomplete payment projection')
        fields.update(f'{group}.{key}' for key in keys)
        excluded[group] += len(value.keys() - set(keys))
        return {key: value[key] for key in keys}

    scope = pick(payload['scope'], SCOPE, 'scope')
    for key in ('order_ref', 'supplier_ref', 'buyer_ref', 'currency_ref'):
        scope[key] = reference(scope[key])
    scope['invoice_number'] = document_number(scope['invoice_number'])
    scope['invoice_date'] = document_date(scope['invoice_date'])
    if scope['proposed_amount'] is not None:
        scope['proposed_amount'] = amount(scope['proposed_amount'])
        require(scope['proposed_amount'] != '0.00', 'A proposed payment must be positive')

    source = payload['documents']
    require(isinstance(source, dict) and set(KINDS) <= source.keys(), 'Missing payment document collection')
    excluded['root'] += len(payload.keys() - {'run_id', 'scope', 'documents', 'snapshot'})
    excluded['documents'] += len(source.keys() - set(KINDS))
    records = {}
    for kind in KINDS:
        collection = source[kind]
        require(isinstance(collection, list) and len(collection) <= 1000, 'Invalid payment document collection')
        unique = {}
        for raw in collection:
            row = pick(raw, DOCUMENT, kind)
            for key in ('ref', 'supplier_ref', 'buyer_ref', 'currency_ref'):
                row[key] = reference(row[key])
            require(isinstance(row['order_refs'], list) and len(row['order_refs']) <= 200, 'Invalid order references')
            row['order_refs'] = sorted({reference(value) for value in row['order_refs']})
            row['number'] = document_number(row['number'])
            if row['invoice_number'] is not None:
                row['invoice_number'] = document_number(row['invoice_number'])
            if row['invoice_date'] is not None:
                require(row['invoice_number'] is not None, 'Invoice date without number')
                row['invoice_date'] = document_date(row['invoice_date'])
            require(all(type(row[key]) is bool for key in ('deleted', 'posted', 'invoice_hint')), 'Invalid payment flags')
            require(type(row['paid']) is bool if kind == 'payment_orders' else row['paid'] is None, 'Invalid 1C paid flag')
            row['amount'] = amount(row['amount'])
            previous = unique.setdefault(row['ref'], row)
            require(previous == row, 'Inconsistent copies of a 1C document')
            if previous is not row:
                fields.subtract(f'{kind}.{key}' for key in DOCUMENT)
        records[kind] = list(unique.values())
    snapshot = pick(payload['snapshot'], ('kind', 'observed_at', 'complete'), 'snapshot')
    require(isinstance(snapshot['kind'], str) and isinstance(snapshot['observed_at'], str) and
            type(snapshot['complete']) is bool, 'Invalid snapshot metadata')
    return dict(scope=scope, documents=records), snapshot, dict(
        fields={key: count for key, count in sorted(fields.items()) if count and not key.startswith('snapshot.')},
        filtered_counts={key: count for key, count in sorted(excluded.items()) if count},
        missing_fields={'scope.proposed_amount': 1} if scope['proposed_amount'] is None else {},
        counts={kind: len(records[kind]) for kind in KINDS})


def scan(body: dict, run_id: str) -> dict:
    scope = body['scope']
    documents, unlinked, matching_amounts = [], [], defaultdict(list)
    for kind, records in body['documents'].items():
        for row in records:
            same_order = scope['order_ref'] in row['order_refs']
            same_parties = all(row[key] == scope[key] for key in ('supplier_ref', 'buyer_ref'))
            if row['deleted'] or not (same_order or same_parties):
                continue
            invoice = row['invoice_number']
            exact_number = invoice is not None and invoice.casefold() == scope['invoice_number'].casefold()
            exact_invoice = exact_number and row['invoice_date'] == scope['invoice_date']
            invoice_number_only = exact_number and row['invoice_date'] is None
            linked = same_order or exact_invoice or invoice_number_only or row['invoice_hint']
            same_currency = row['currency_ref'] == scope['currency_ref']
            same_amount = row['amount'] == scope['proposed_amount']
            if not linked and not (same_parties and same_currency and same_amount):
                continue
            conflicts = []
            if not same_parties:
                conflicts.append('parties')
            if not same_currency:
                conflicts.append('currency')
            if invoice is not None and not (exact_invoice or invoice_number_only):
                conflicts.append('invoice')
            if row['order_refs'] and not same_order:
                conflicts.append('order')
            facts = [key for key, matched in (('order_ref', same_order), ('invoice_number_and_date', exact_invoice),
                     ('invoice_number_only', invoice_number_only), ('payment_purpose_hint', row['invoice_hint'])) if matched]
            doc = dict(kind=kind, ref=row['ref'], number=row['number'], amount=row['amount'], facts=facts,
                       conflicts=conflicts, posted_1c=row['posted'], marked_paid_1c=row['paid'],
                       allocates_to_multiple_orders=len(row['order_refs']) > 1)
            if not linked:
                unlinked.append(doc)
                continue
            documents.append(doc)
            if not conflicts and row['amount'] != '0.00':
                matching_amounts[kind, row['amount']].append(doc)
    candidates = []
    for (kind, total), group in matching_amounts.items():
        reasons = []
        if total == scope['proposed_amount']:
            reasons.append('matches_proposed_amount')
        if len(group) > 1:
            reasons.append('same_kind_and_amount')
        if reasons:
            candidates.append(dict(kind=kind, amount=total, refs=[doc['ref'] for doc in group], reasons=reasons))
    return dict(schema='kolos-supplier-invoice-payments/1', run_id=run_id, status='scanned', may_write=False,
                related=documents, possible_duplicates=candidates, unlinked_same_amount=unlinked, bank_execution='not_checked',
                steps=['match_order_and_invoice_references', 'separate_1c_document_roles', 'flag_possible_repeats'])
