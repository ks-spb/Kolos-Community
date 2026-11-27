"""Read-only learned selection, invoice arithmetic, and explicit article approval."""
from __future__ import annotations

import copy
from pathlib import Path
import unittest
from uuid import uuid4

from kolos_states.supplier_invoice import ROOT, run


def example():
    scope = dict(supplier_inn='1111111111', buyer_inn='222222222222', currency='RUB')
    line = dict(article='PRODUCT-A', unit='m2', quantity='3.2', price='10.12', amount='32.38', vat_rate='20')
    invoice = dict(scope, number='TEST1', date='2026-01-05', tax_mode='added',
                   subtotal='32.38', vat='6.48', total='38.86', delivery=None, lines=[line])
    order_line = dict(code='SKU-A', name='Позиция 1С', supplier_article='PRODUCT-OLD',
                      unit='m2', variant=None, quantity='3', amount='36', vat='6')
    order = dict(scope, number='ORDER1', state='in_progress', total='36', price_includes_vat=True,
                 lines=[order_line])
    confirmation = dict(scope, number=invoice['number'], date=invoice['date'], article=line['article'],
                        code=order_line['code'], unit=line['unit'], variant=None, evidence='fixture confirmation')
    return dict(run_id='lesson', invoice=invoice, orders=[order], confirmed_links=[confirmation])


class SupplierInvoiceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(ROOT) / ('unit-' + uuid4().hex)
        result = run(example(), self.root, teach=True)
        self.assertEqual(result['status'], 'reconciled', result)
        self.memory = self.root / 'lesson' / 'memory' / 'memory.json'
        persisted = self.memory.read_text(encoding='utf-8')
        self.assertNotIn(example()['invoice']['supplier_inn'], persisted)
        self.assertNotIn(example()['invoice']['buyer_inn'], persisted)

    def test_requires_case_specific_confirmation_then_uses_it(self):
        payload = example()
        missing = run(dict(payload, run_id='unconfirmed', confirmed_links=[]), self.root, memory=self.memory)
        self.assertEqual(missing['possible_orders'], ['ORDER1'])
        self.assertIsNone(missing['order'])
        self.assertEqual(missing['unresolved_articles'], ['PRODUCT-A'])
        self.assertEqual(missing['status'], 'needs_review')
        taught = run(dict(payload, run_id='confirmed'), self.root, memory=self.memory)
        self.assertEqual(taught['order'], 'ORDER1')
        self.assertEqual(taught['lines'][0]['order_unit_price_without_vat'], '10.00')
        self.assertEqual(taught['lines'][0]['invoice_unit_price_without_vat'], '10.12')
        self.assertTrue(taught['memory_unchanged'])
        self.assertFalse(taught['may_write'])
        payload['invoice']['number'] = 'another'
        stale = run(dict(payload, run_id='stale-approval'), self.root, memory=self.memory)
        self.assertEqual(stale['status'], 'blocked')
        self.assertIn('another invoice', stale['reason'])

    def test_new_supplier_scope_and_multiple_equivalent_orders(self):
        payload = example()
        payload['confirmed_links'] = []
        payload['invoice'].update(supplier_inn='3333333333', buyer_inn='444444444444')
        order = copy.deepcopy(payload['orders'][0])
        order.update(supplier_inn='3333333333', buyer_inn='444444444444', number='ORDER2')
        order['lines'][0]['supplier_article'] = 'PRODUCT-A'
        payload['orders'].append(order)
        result = run(dict(payload, run_id='held-out'), self.root, memory=self.memory)
        self.assertEqual(result['order'], 'ORDER2')
        self.assertEqual(result['lines'][0]['match'], 'exact')
        payload['orders'].append(dict(order, number='ORDER3'))
        result = run(dict(payload, run_id='ambiguous'), self.root, memory=self.memory)
        self.assertEqual(result['reason'], 'multiple_matching_orders')
        self.assertIsNone(result['order'])

    def test_incomplete_scope_and_empty_memory_do_not_choose_order(self):
        payload = example()
        payload['orders'][0]['currency'] = 'EUR'
        scoped = run(dict(payload, run_id='currency'), self.root, memory=self.memory)
        self.assertEqual(scoped['status'], 'needs_review')
        self.assertEqual(scoped['scoped_orders'], [])
        empty = run(dict(payload, run_id='empty'), self.root)
        self.assertEqual(empty['status'], 'blocked')
        self.assertIn('Unknown or ambiguous episode', empty['reason'])

    def test_vat_and_delivery_are_explicit_and_amounts_reconcile_exactly(self):
        payload = example()
        invoice = payload['invoice']
        invoice.update(tax_mode='included', subtotal='26.98', vat='5.40', total='32.38',
                       delivery=dict(included=False, amount='10', vat='1.67'))
        report = run(dict(payload, run_id='vat-included'), self.root, memory=self.memory)
        self.assertEqual(report['status'], 'reconciled')
        self.assertEqual(report['invoice']['total'], '32.38')
        invoice['total'] = '32.39'
        report = run(dict(payload, run_id='one-cent'), self.root, memory=self.memory)
        self.assertEqual(report['status'], 'blocked')
        self.assertIn('Invoice totals disagree: total', report['reason'])


if __name__ == '__main__':
    unittest.main()
