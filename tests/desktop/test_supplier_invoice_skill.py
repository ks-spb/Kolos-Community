"""Skill receipts report actual delivery, and reviews never authorize a write."""
from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
import json
import unittest
from uuid import UUID, uuid4

from kolos_states import supplier_invoice, supplier_invoice_skill as skill
from kolos_states.ipc import atomic_json
from kolos_states.xway_readonly.worker import digest
from test_supplier_invoice import example

NOW = datetime.fromisoformat('2026-01-05T10:00:00+03:00')


class SupplierInvoiceSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = supplier_invoice.ROOT / ('skill-tests-' + uuid4().hex)
        lesson = supplier_invoice.run(example(), cls.root / 'training', teach=True)
        assert lesson['status'] == 'reconciled'
        cls.profile = cls.root / 'profile'
        content = (cls.root / 'training' / 'lesson' / 'memory' / 'memory.json').read_bytes()
        version = cls.profile / 'v1'
        version.mkdir(parents=True)
        (version / 'memory.json').write_bytes(content)
        atomic_json(cls.profile / 'active.json', dict(version='v1', sha256=sha256(content).hexdigest()))

    def packet(self, name, *, kind='historical', complete=True):
        return dict(example(), run_id=name,
                    snapshot=dict(kind=kind, observed_at=NOW.isoformat(), complete=complete))

    def execute(self, payload):
        return skill.run(payload, self.root / 'runs', profile=self.profile, now=NOW)

    def test_receipt_is_based_on_projected_input_and_has_no_raw_values(self):
        data = self.packet('projection')
        data['invoice']['bank_details'] = 'SENSITIVE-BANK-EXAMPLE'
        data['orders'][0]['lines'][0]['extra'] = 'SENSITIVE-ORDER-EXAMPLE'
        result = self.execute(data)
        self.assertEqual(result['status'], 'reconciled')
        self.assertEqual(result['filtered_counts'], {'invoice': 1, 'orders.lines': 1})
        self.assertEqual(result['transmitted_fields']['invoice.supplier_inn'], 1)
        self.assertEqual(result['counts']['orders'], 1)
        self.assertEqual(result['memory']['version'], 'v1')
        self.assertFalse(result['may_write'])
        self.assertEqual(result, self.execute(data))
        root = self.root / 'runs' / result['run_id']
        for content in ((root / 'receipt.json').read_text(encoding='utf-8'),
                        (root / result['handoff']).read_text(encoding='utf-8')):
            self.assertNotIn('SENSITIVE-', content)
            self.assertNotIn(data['invoice']['supplier_inn'], content)
        data['invoice']['number'] = 'different'
        with self.assertRaisesRegex(ValueError, 'bound to other input'):
            self.execute(data)

    def test_partial_and_stale_snapshots_are_not_sent(self):
        incomplete = self.execute(self.packet('incomplete', complete=False))
        self.assertEqual(incomplete['issue'], 'snapshot_incomplete')
        data = self.packet('stale', kind='1c_odata')
        data['snapshot']['observed_at'] = '2026-01-05T09:49:59+03:00'
        stale = self.execute(data)
        self.assertEqual(stale['issue'], 'stale_snapshot')
        for result in (incomplete, stale):
            self.assertEqual(result['status'], 'not_sent')
            self.assertFalse(result['transmitted_fields'])
            self.assertNotIn('handoff', result)

    def test_verdict_is_tied_to_receipt_and_requires_independent_evidence(self):
        result = self.execute(self.packet('live-verified', kind='1c_odata'))
        body = dict(run_id=result['run_id'], receipt_sha256=digest(result), verdict='confirmed',
                    checks=['invoice_source', 'order_source'], findings=[])
        with self.assertRaisesRegex(ValueError, 'readback'):
            skill.review(body, self.root / 'runs')
        body['checks'].append('live_order_readback')
        with self.assertRaisesRegex(ValueError, 'another run'):
            skill.review(dict(body, receipt_sha256='wrong'), self.root / 'runs')
        saved = skill.review(body, self.root / 'runs')
        self.assertEqual(saved['verdict'], 'confirmed')
        self.assertFalse(saved['may_write'])
        self.assertEqual(json.loads((self.root / 'runs' / result['run_id'] / 'review.json').read_bytes()), saved)

    def test_expired_retry_and_changed_handoff(self):
        packet = self.packet('retry', kind='1c_odata')
        result = self.execute(packet)
        original = skill.run(packet, self.root / 'runs', profile=self.profile, now=NOW + timedelta(minutes=11))
        self.assertEqual(result, original)
        path = self.root / 'runs' / result['run_id'] / result['handoff']
        changed = json.loads(path.read_bytes())
        changed['order'] = 'another order'
        atomic_json(path, changed)
        body = dict(run_id=result['run_id'], receipt_sha256=digest(result), verdict='confirmed',
                    checks=['invoice_source', 'order_source', 'live_order_readback'], findings=[])
        with self.assertRaisesRegex(ValueError, 'missing or changed'):
            skill.review(body, self.root / 'runs')

    def test_ambiguity_can_be_checked_but_not_approved(self):
        data = self.packet('ambiguous')
        data['orders'].append(dict(data['orders'][0], number='ORDER2'))
        result = self.execute(data)
        self.assertEqual(result['issue'], 'multiple_matching_orders')
        claim = dict(run_id=result['run_id'], receipt_sha256=digest(result),
                     checks=['invoice_source', 'order_source'], findings=[])
        with self.assertRaisesRegex(ValueError, 'reconciled'):
            skill.review(dict(claim, verdict='confirmed'), self.root / 'runs')
        stop = skill.review(dict(claim, verdict='correct_stop'), self.root / 'runs')
        self.assertEqual(stop['verdict'], 'correct_stop')
        self.assertFalse(stop['may_write'])

    def test_worker_stop_keeps_completed_steps(self):
        data = self.packet('blocked-order')
        data['orders'][0]['lines'][0]['quantity'] = '0'
        result = self.execute(data)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['issue'], 'worker_blocked')
        self.assertTrue(result['work']['invoice_arithmetic_checked'])
        self.assertEqual(result['work']['matched_lines'], 0)
        self.assertEqual(len(result['executed_steps']), 6)

    def test_corrupted_memory_records_a_failure_without_transferring_fields(self):
        wrong = self.root / 'bad-profile'
        atomic_json(wrong / 'v1' / 'memory.json', {})
        atomic_json(wrong / 'active.json', dict(version='v1', sha256='wrong'))
        result = skill.run(self.packet('invalid-memory'), self.root / 'runs', profile=wrong, now=NOW)
        self.assertEqual(result['status'], 'not_sent')
        self.assertEqual(result['issue'], 'execution_unavailable')
        self.assertEqual(result['transmitted_fields'], {})


class SupplierPaymentScanTests(unittest.TestCase):
    def setUp(self):
        self.root = supplier_invoice.ROOT / ('payment-tests-' + uuid4().hex)
        self.scope = dict(order_ref=str(UUID(int=1)), supplier_ref=str(UUID(int=2)), buyer_ref=str(UUID(int=3)),
                          currency_ref=str(UUID(int=4)), invoice_number='706', invoice_date='2026-01-05',
                          proposed_amount='10.00')
        self.packet = dict(run_id='payments', scope=self.scope,
                           documents=dict(payment_orders=[], bank_expenses=[], expense_requests=[]),
                           snapshot=dict(kind='1c_odata', observed_at=NOW.isoformat(), complete=True))

    def document(self, ref, **overrides):
        row = dict(ref=str(UUID(int=ref)), number=f'DOC-{ref}', supplier_ref=self.scope['supplier_ref'],
                   buyer_ref=self.scope['buyer_ref'], currency_ref=self.scope['currency_ref'],
                   order_refs=[self.scope['order_ref']], invoice_number=None, invoice_date=None,
                   invoice_hint=False, amount='10', deleted=False, posted=False, paid=False)
        return dict(row, **overrides)

    def execute(self):
        return skill.run(self.packet, self.root, now=NOW, payments=True)

    def handoff(self, result):
        return json.loads((self.root / result['run_id'] / result['handoff']).read_bytes())

    def test_empty_snapshot_runs_and_review_requires_independent_payment_read(self):
        result = self.execute()
        self.assertEqual(result['status'], 'scanned')
        self.assertEqual(self.handoff(result)['related'], [])
        self.assertEqual(result, self.execute())
        body = dict(run_id=result['run_id'], receipt_sha256=digest(result), verdict='confirmed',
                    checks=['invoice_source', 'order_source'], findings=[])
        with self.assertRaisesRegex(ValueError, 'snapshot evidence'):
            skill.review(body, self.root)
        body['checks'].append('payment_snapshot')
        with self.assertRaisesRegex(ValueError, 'payment readback'):
            skill.review(body, self.root)
        body['checks'].append('live_payment_readback')
        self.assertFalse(skill.review(body, self.root)['may_write'])

    def test_payment_roles_and_identical_odata_rows_do_not_create_duplicate_groups(self):
        order = self.document(10, bank_account='SENSITIVE')
        expense = self.document(11, posted=True, paid=None)
        self.scope['proposed_amount'] = None
        self.packet['documents'].update(payment_orders=[order, dict(order)], bank_expenses=[expense])
        result = self.execute()
        report = self.handoff(result)
        self.assertEqual(result['counts']['payment_orders'], 1)
        self.assertEqual(result['filtered_counts'], {'payment_orders': 2})
        self.assertEqual(result['missing_fields'], {'scope.proposed_amount': 1})
        self.assertEqual(result['work']['related'], 2)
        self.assertEqual(report['related'][0]['facts'], ['order_ref'])
        self.assertFalse(report['related'][0]['marked_paid_1c'])
        self.assertTrue(report['related'][1]['posted_1c'])
        self.assertEqual(report['possible_duplicates'], [])
        self.assertEqual(report['bank_execution'], 'not_checked')
        self.assertNotIn('SENSITIVE', json.dumps([result, report]))

    def test_repeat_candidates_keep_roles_and_weak_or_conflicting_links_separate(self):
        self.packet['documents']['payment_orders'] = [
            self.document(10), self.document(11, order_refs=[], invoice_number='706', invoice_date='2026-01-05'),
            self.document(12, order_refs=[]), self.document(13, invoice_number='706', invoice_date='2025-01-05'),
            self.document(14, currency_ref=str(UUID(int=5))), self.document(15, deleted=True),
            self.document(16, amount='0'), self.document(17, buyer_ref=str(UUID(int=6))),
        ]
        self.packet['documents']['bank_expenses'] = [self.document(30, posted=True, paid=None)]
        result = self.execute()
        report = self.handoff(result)
        related = {row['number']: row for row in report['related']}
        self.assertEqual(related['DOC-11']['facts'], ['invoice_number_and_date'])
        self.assertEqual(related['DOC-13']['conflicts'], ['invoice'])
        self.assertEqual(related['DOC-14']['conflicts'], ['currency'])
        self.assertEqual(related['DOC-17']['conflicts'], ['parties'])
        self.assertEqual([row['number'] for row in report['unlinked_same_amount']], ['DOC-12'])
        self.assertNotIn('DOC-15', related)
        self.assertEqual(report['possible_duplicates'], [
            dict(kind='payment_orders', amount='10.00', refs=[str(UUID(int=10)), str(UUID(int=11))],
                 reasons=['matches_proposed_amount', 'same_kind_and_amount']),
            dict(kind='bank_expenses', amount='10.00', refs=[str(UUID(int=30))], reasons=['matches_proposed_amount']),
        ])

    def test_incomplete_stale_and_conflicting_snapshots_stop_before_work(self):
        self.packet['snapshot']['complete'] = False
        result = self.execute()
        self.assertEqual(result['issue'], 'snapshot_incomplete')
        self.packet.update(run_id='stale')
        self.packet['snapshot'].update(complete=True, observed_at=(NOW - timedelta(minutes=11)).isoformat())
        self.assertEqual(self.execute()['issue'], 'stale_snapshot')
        self.packet.update(run_id='inconsistent')
        self.packet['snapshot']['observed_at'] = NOW.isoformat()
        self.packet['documents']['payment_orders'] = [self.document(10), self.document(10, amount='9.00')]
        result = self.execute()
        self.assertEqual(result['status'], 'not_sent')
        self.assertEqual(result['issue'], 'input_invalid')
        self.assertEqual(result['transmitted_fields'], {})
        self.assertNotIn('handoff', result)


if __name__ == '__main__':
    unittest.main()
