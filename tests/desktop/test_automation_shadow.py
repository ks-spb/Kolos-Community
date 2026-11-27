"""Frozen coverage lessons and read-only handoffs on the scheduled entry point."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from kolos_states import automation_coverage as coverage, automation_shadow as shadow
from kolos_states.core import StateEngine
from kolos_states.storage import Store

ROOT = Path(__file__).resolve().parents[1] / 'desktop-output' / 'shadow-tests'
NOW = datetime.fromisoformat('2026-11-27T09:00:00+03:00')


def packet(automation_id, run_id, **data):
    return dict(automation_id=automation_id, run_id=run_id,
                input=dict(observed_at=NOW.isoformat(), source_ref='fixture', **data))


class ShadowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ROOT / uuid4().hex
        cls.empty = cls.root / 'empty'
        cls.memory = cls.root / 'frozen'
        store = Store(cls.empty)
        try:
            store.save(StateEngine())
        finally:
            store.close()
        cls.teaching = coverage.teach(cls.memory, cls.empty)

    def run_packet(self, value):
        return shadow.run(value, self.root / 'reports', snapshot=self.memory, now=NOW)

    def test_learned_filter_and_empty_memory_control(self):
        counts = dict(new=9, okay=1, missing=0, duplicate=2)
        self.assertEqual(self.teaching['checks'], 4)
        self.assertEqual(coverage.exceptions(counts, self.memory)[0], ['new', 'missing', 'duplicate'])
        (self.empty / 'recipe.json').write_bytes((self.memory / 'recipe.json').read_bytes())
        with self.assertRaisesRegex(ValueError, 'no learned evidence'):
            coverage.exceptions(counts, self.empty)

    def test_wb_reports_missing_count_and_preserves_a_measured_zero(self):
        data = packet('wb', 'manifest', manifest=dict(expected_promotions=5, unique_products=0,
            collected=[dict(promotion_id=i, observed_at=stamp) for i, stamp in (
                (11, NOW.isoformat()), (11, NOW.isoformat()), (12, '2026-11-26T09:00:00+03:00'))],
            failed=[dict(promotion_id=13, message='report not available')]))
        result = self.run_packet(data)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['result']['missing_or_ambiguous'], ['11', '12', '13'])
        self.assertEqual(result['result']['duplicate_ids'], ['11'])
        self.assertEqual(result['result']['stale_ids'], ['12'])
        self.assertEqual(result['result']['failed_ids'], ['13'])
        self.assertEqual(result['result']['unidentified_missing_count'], 2)
        self.assertEqual(result['result']['unique_products'], 0)
        self.assertFalse(result['may_execute'])

    def test_wb_zero_and_unavailable_inputs_are_distinct(self):
        empty_manifest = dict(expected_promotions=0, unique_products=0, collected=[], failed=[])
        self.assertEqual(self.run_packet(packet('wb', 'none-expected', manifest=empty_manifest))['status'],
                         'completed')
        unavailable = self.run_packet(dict(automation_id='wb', run_id='manifest-absent'))
        self.assertEqual(unavailable['status'], 'failed')
        self.assertTrue(unavailable['notify_exception'])
        stale = packet('wb', 'manifest-stale', manifest=empty_manifest)
        stale['input']['observed_at'] = '2026-11-25T09:00:00+03:00'
        self.assertEqual(self.run_packet(stale)['reason'], 'Stale coverage input')

    def test_ozon_held_out_week_missing_days_and_cost_markers(self):
        payload = packet('ozon', 'fresh-week', account_id='default', date_from='2026-11-16',
            date_to='2026-11-22', missing_dates=['2026-11-18'], missing_ad_dates=['2026-11-21'],
            cost_rows=[dict(marketplace_sku=55001, roi_cost_incomplete=None),
                       dict(marketplace_sku=55002, roi_cost_incomplete=True),
                       dict(marketplace_sku=55003, roi_cost_incomplete=False)])
        result = self.run_packet(payload)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(set(result['result']['missing_or_unconfirmed']),
                         {'finance/2026-11-18', 'cpc_cpo/2026-11-21', 'cost/55001', 'cost/55002'})
        payload['run_id'] = 'wrong-week'
        payload['input']['date_from'] = '2026-11-15'
        self.assertEqual(self.run_packet(payload)['status'], 'failed')

    def test_repeat_and_quiet_skip_keep_reports_separate(self):
        left, right = (dict(automation_id=i, run_id='same-slot') for i in ('automation-4', 'automation-6'))
        with ThreadPoolExecutor(2) as pool:
            before, after = pool.map(self.run_packet, (left, right))
        self.assertEqual(before['status'], 'skipped')
        self.assertEqual(before, self.run_packet(left))
        self.assertNotEqual(before['automation_id'], after['automation_id'])
        changed = dict(left, input={'new': True})
        self.assertEqual(self.run_packet(changed)['status'], 'failed')
        root = self.root / 'reports'
        with self.assertRaisesRegex(ValueError, 'another handoff'):
            shadow.review(dict(left, input_sha256='wrong', verdict='not_needed'), root)
        review = shadow.review(dict(left, input_sha256=before['input_sha256'], verdict='not_needed'), root)
        self.assertFalse(review['notify_exception'])
        self.assertEqual(json.loads((root / 'automation-4' / 'same-slot' / 'review.json').read_bytes()), review)

    def test_review_requires_evidence_and_cannot_confirm_mismatched_target(self):
        report = self.run_packet(packet('wb', 'review', manifest=dict(
            expected_promotions=0, unique_products=0, collected=[], failed=[])))
        root = self.root / 'reports'
        data = dict(automation_id='wb', run_id=report['run_id'], input_sha256=report['input_sha256'],
                    verdict='confirmed', confirmed=['0 promotions expected'])
        with self.assertRaisesRegex(ValueError, 'independent evidence'):
            shadow.review(data, root)
        with self.assertRaisesRegex(ValueError, 'valid handoff'):
            shadow.review(dict(data, run_id='other'), root)
        review = shadow.review(dict(data, verdict='corrected', corrected=['example correction'],
                                    sources=['reference check']), root)
        self.assertTrue(review['notify_exception'])
        self.assertFalse(review['may_execute'])

    def test_xway_rejects_another_campaign_before_executing_the_reader(self):
        binding = self.root / 'xway-profile.json'
        binding.write_text(json.dumps(dict(task=dict(shop_id=1, nm_id=2, campaign_id=3),
                                           memory_run='fixture')), encoding='utf-8')
        task = dict(shop_id=1, nm_id=2, campaign_id=4)
        with patch.object(shadow, 'STOCK_PROFILE', binding), patch.object(shadow.campaign, 'run') as reader:
            report = self.run_packet(dict(automation_id='wb-2', run_id='wrong-xway', input={'task': task}))
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['reason'], 'Wrong stock-pilot campaign')
        self.assertFalse(report['may_execute'])
        reader.assert_not_called()


if __name__ == '__main__':
    unittest.main()
