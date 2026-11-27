"""Read-only invoice reconciliation against an observed supplier-order snapshot."""
from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
from pathlib import Path
import re
import sys
import time

from .episode_browser import BrowserEpisodeBridge
from .episodes import SCHEMA, bind
from .ipc import MAX_BYTES, atomic_json, read_json
from .protocol import require
from .storage import Store
from .xway_readonly.campaign import learned_signature, run_name
from .xway_readonly.protocol import field

ROOT = Path(__file__).resolve().parents[1] / 'tests' / 'desktop-output' / 'supplier-invoice'
QUERY = 'Сверь счёт поставщика с открытым заказом'
IDENTITY = ('supplier_inn', 'buyer_inn', 'currency')
SOURCE = 'Supplier invoice identity'
SELECTION = 'Local order selection'
CENT = Decimal('0.01')


def number(value: object) -> Decimal:
    require(type(value) is str and re.fullmatch(r'[0-9]{1,14}(?:\.[0-9]{1,6})?', value),
            'Expected an exact nonnegative decimal string')
    return Decimal(value)


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def identity(invoice: dict) -> dict:
    selected = {key: invoice[key] for key in IDENTITY}
    require(all(re.fullmatch(r'[0-9]{10}|[0-9]{12}', selected[key]) for key in IDENTITY[:2]),
            'Invalid supplier or buyer INN')
    require(re.fullmatch(r'[A-Z]{3}', selected['currency']), 'Invalid invoice currency')
    return selected


def verify_invoice(invoice: dict) -> dict:
    """Use the invoice base and verify line extensions and tax before considering any order."""
    require(isinstance(invoice['number'], str) and 0 < len(invoice['number']) <= 80, 'Missing invoice number')
    date.fromisoformat(invoice['date'])
    mode = invoice['tax_mode']
    require(mode in ('added', 'included'), 'Invoice VAT mode is not confirmed')
    lines = invoice['lines']
    require(isinstance(lines, list) and 0 < len(lines) <= 200, 'Missing invoice lines')
    require(all(line.get('article') and line.get('unit') for line in lines), 'Missing invoice article or unit')
    base, tax = Decimal(0), Decimal(0)
    for line in lines:
        quantity, price, amount, rate = (number(line[key]) for key in ('quantity', 'price', 'amount', 'vat_rate'))
        require(quantity > 0 and rate <= 100, 'Invalid quantity or VAT rate')
        require(money(quantity * price) == amount, 'Invoice line amount disagrees with quantity and price')
        base += amount
        tax += money(amount * rate / (100 + rate if mode == 'included' else 100))
    delivery = invoice['delivery']
    if delivery is not None:
        require(type(delivery['included']) is bool, 'Delivery coverage is unconfirmed')
        amount, vat = (number(delivery[key]) for key in ('amount', 'vat'))
        require(money(amount) == amount and money(vat) == vat and vat <= amount, 'Invalid delivery amounts')
        if delivery['included']:
            base += amount
            tax += vat
    total = base + tax if mode == 'added' else base
    subtotal = base if mode == 'added' else base - tax
    for key, actual in (('subtotal', subtotal), ('vat', tax), ('total', total)):
        require(number(invoice[key]) == actual, 'Invoice totals disagree: ' + key)
    return dict(subtotal=str(money(subtotal)), vat=str(money(tax)), total=str(money(total)),
                tax_mode=mode, delivery=delivery)


class SelectionEpisode:
    """Bind the observed invoice identity through the learned sequence before searching orders."""

    def __init__(self, bridge: BrowserEpisodeBridge, values: dict, run_id: str) -> None:
        self.bridge, self.values, self.run_id = bridge, values, run_id
        self.selection = {key: '' for key in IDENTITY}
        self.steps = []
        self.version = 0

    def observe(self) -> dict:
        self.version += 1
        objects = []
        for key in IDENTITY:
            objects.append(field('source:' + key, key, self.values[key], SOURCE))
            objects.append(field('selection:' + key, 'Selection ' + key, self.selection[key], SELECTION, writable=True))
        return dict(schema=SCHEMA, session=self.run_id, version=self.version,
                    captured_at=time.monotonic(), objects=objects)

    def perform(self, request: dict) -> None:
        action = request['action']
        target = bind(self.observe(), action['descriptor'])
        require(action['object'] == target['id'], 'Stale selection target')
        if action['kind'] == 'read':
            require(target['descriptor']['scope'] == SOURCE, 'Read outside the invoice identity')
        else:
            key = target['id'].removeprefix('selection:')
            require(action['kind'] == 'write' and target['writable'] and self.values[key] == action['value'],
                    'Selection write does not match the source')
            self.selection[key] = action['value']
        self.bridge.confirm(self.observe(), self.observe(), verified_by='local-invoice-snapshot')
        self.steps.append(dict(kind=action['kind'], role=target['descriptor']['name']))

    def teach(self) -> None:
        self.bridge.begin_teaching(QUERY)
        for index, key in enumerate(IDENTITY):
            self.perform(self.bridge.prepare(self.observe(), 'read', key))
            self.perform(self.bridge.prepare(self.observe(), 'write', 'Selection ' + key, source=f'v{index}'))
        self.bridge.finish_teaching()

    def replay(self) -> None:
        self.bridge.start(QUERY, self.observe())
        for _ in range(2 * len(IDENTITY) + 1):
            request = self.bridge.next(self.observe())
            if request.get('status') == 'complete':
                return
            require('action' in request, 'Invoice selection did not complete')
            self.perform(request)
        raise ValueError('Invoice selection exceeded its step limit')


def confirmed_links(invoice: dict, supplied: list) -> dict:
    """An explicit match belongs to this invoice identity and line, including characteristic when applicable."""
    require(isinstance(supplied, list), 'Missing article confirmation list')
    links = {}
    for link in supplied:
        require(all(link[key] == invoice[key] for key in ('number', 'date', *IDENTITY)),
                'Article confirmation belongs to another invoice')
        key = (link['article'], link['unit'])
        require(key not in links and link.get('code') and 'variant' in link and link.get('evidence'),
                'Incomplete or duplicate article confirmation')
        links[key] = link
    return links


def line_matches(invoice_line: dict, order_line: dict, link: dict | None) -> bool:
    if invoice_line['unit'] != order_line['unit']:
        return False
    if link:
        return order_line['code'] == link['code'] and order_line.get('variant') == link['variant']
    return (invoice_line['article'] == order_line.get('supplier_article') and
            invoice_line.get('variant') == order_line.get('variant'))


def select(invoice: dict, selection: dict, orders: list, confirmations: list) -> dict:
    require(isinstance(orders, list) and len(orders) <= 200, 'Missing or oversized order snapshot')
    links = confirmed_links(invoice, confirmations)
    scoped = [order for order in orders if order['state'] == 'in_progress' and
              all(order[key] == selection[key] for key in IDENTITY)]
    require(len({o['number'] for o in scoped}) == len(scoped), 'Repeated order in the snapshot')
    reference = invoice['lines']
    plausible = [order for order in scoped if sorted(i['unit'] for i in order['lines']) ==
                 sorted(i['unit'] for i in reference)]
    matched, unresolved = [], set()
    for order in plausible:
        positions = []
        for line in reference:
            link = links.get((line['article'], line['unit']))
            candidates = [i for i, row in enumerate(order['lines']) if line_matches(line, row, link)]
            if len(candidates) != 1 or candidates[0] in positions:
                unresolved.add(line['article'])
                continue
            positions.append(candidates[0])
        if len(positions) == len(reference):
            matched.append((order, positions))
    common = dict(scoped_orders=[order['number'] for order in scoped],
                  possible_orders=[order['number'] for order in plausible], order=None)
    if len(matched) != 1:
        reason = 'multiple_matching_orders' if matched else 'no_unambiguous_article_match'
        return dict(common, status='needs_review', reason=reason,
                    matching_orders=[order['number'] for order, _ in matched],
                    unresolved_articles=sorted(unresolved))
    order, positions = matched[0]
    require(type(order['price_includes_vat']) is bool, 'Order VAT treatment is unconfirmed')
    rows = []
    for line, index in zip(reference, positions, strict=True):
        old = order['lines'][index]
        quantity, amount, vat = (number(old[key]) for key in ('quantity', 'amount', 'vat'))
        require(quantity > 0 and (not order['price_includes_vat'] or vat <= amount),
                'Invalid order quantity or VAT base')
        old_net = (amount - vat if order['price_includes_vat'] else amount) / quantity
        line_amount, rate, listed_price = (number(line[key]) for key in ('amount', 'vat_rate', 'price'))
        tax_divisor = 100 + rate if invoice['tax_mode'] == 'included' else 100
        line_vat = money(line_amount * rate / tax_divisor)
        new_net = listed_price * 100 / tax_divisor
        rows.append(dict(article=line['article'], code=old['code'], name=old['name'], unit=line['unit'],
                         match='confirmed' if (line['article'], line['unit']) in links else 'exact',
                         order_quantity=old['quantity'], invoice_quantity=line['quantity'],
                         order_unit_price_without_vat=str(money(old_net)),
                         invoice_unit_price_without_vat=str(money(new_net)),
                         invoice_amount=str(money(line_amount)), invoice_vat=str(line_vat)))
    common['order'] = order['number']
    return dict(common, status='reconciled', order_total=str(money(number(order['total']))),
                order_price_includes_vat=order['price_includes_vat'], lines=rows)


def run(payload: dict, root: Path, *, teach: bool = False, memory: Path | None = None) -> dict:
    run_id = run_name(payload['run_id'])
    directory = root / run_id
    directory.mkdir(parents=True, exist_ok=False)
    report = dict(schema='kolos-supplier-invoice-review/1', run_id=run_id, status='blocked', may_write=False)
    episode = None
    try:
        invoice = payload['invoice']
        invoice_identity = identity(invoice)
        report['invoice'] = dict(number=invoice['number'], date=invoice['date'], **verify_invoice(invoice))
        bridge = BrowserEpisodeBridge()
        if memory is not None:
            require(not teach, 'Teaching starts with isolated memory')
            bridge.engine = Store.restore_snapshot(read_json(memory))
        episode = SelectionEpisode(bridge, invoice_identity, run_id)
        if teach:
            episode.teach()
        else:
            before = learned_signature(bridge)
            episode.replay()
            report['memory_unchanged'] = before == learned_signature(bridge)
            require(report['memory_unchanged'], 'Learned memory changed during replay')
        require(episode.selection == invoice_identity, 'Incomplete learned selection')
        report.update(select(invoice, episode.selection, payload['orders'], payload.get('confirmed_links', [])))
        if teach:
            # Keep the learned role graph. Demonstration receipts contain the invoice's actual identity.
            bridge.engine.model['learningLog'] = []
            store = Store(directory / 'memory')
            try:
                store.save(bridge.engine)
            finally:
                store.close()
    except (AttributeError, KeyError, TypeError, ValueError, InvalidOperation, OverflowError) as error:
        report.update(status='blocked', reason=str(error))
    finally:
        if episode is not None:
            report.update(steps=episode.steps, mode='teach' if teach else 'read')
    atomic_json(directory / 'handoff.json', report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('teach', 'read'))
    parser.add_argument('--memory', type=Path)
    parser.add_argument('--output-root', type=Path, default=ROOT)
    args = parser.parse_args()
    sys.stdin.reconfigure(encoding='utf-8-sig')
    sys.stdout.reconfigure(encoding='utf-8')
    raw = sys.stdin.read(MAX_BYTES + 1)
    require(len(raw.encode()) <= MAX_BYTES, 'Oversized invoice input')
    result = run(json.loads(raw), args.output_root, teach=args.mode == 'teach', memory=args.memory)
    print(json.dumps(result, ensure_ascii=False))
    return int(result['status'] == 'blocked')


if __name__ == '__main__':
    raise SystemExit(main())
