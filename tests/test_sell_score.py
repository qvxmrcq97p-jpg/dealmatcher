"""Unit tests for sell_score scoring engine.

Run from ~/dealmatcher/:
    python3 tests/test_sell_score.py
"""
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

from sell_score import (  # noqa: E402
    Parcel,
    score_parcel,
    score_all,
    synthetic_dataset,
    WEIGHT_FORECLOSURE,
    WEIGHT_TAX_DELINQUENT,
    WEIGHT_CODE_VIOLATIONS,
    WEIGHT_HOLD_TIME,
    WEIGHT_EQUITY,
    WEIGHT_OUT_OF_STATE_MAILING,
    WEIGHT_NO_HOMESTEAD,
)


def make_parcel(**overrides) -> Parcel:
    base = dict(
        parcel_id="TEST-1",
        owner_name="Owner",
        owner_state="FL",
        property_address="123 Main St",
        city="Miami",
        zip_code="33125",
        year_built=1990,
        total_living_area=1500,
        just_value=300_000,
        assessed_value=300_000,
        sale_date=date(2020, 1, 1),
        sale_price=200_000,
        homestead_exempt=True,
    )
    base.update(overrides)
    return Parcel(**base)


TODAY = date(2026, 4, 30)


class TestSignalScoring(unittest.TestCase):

    def test_clean_parcel_scores_zero_or_minimal(self):
        # In-state, homesteaded, recent sale at fair value, no distress
        p = make_parcel(
            owner_state="FL",
            homestead_exempt=True,
            sale_date=date(2024, 1, 1),
            sale_price=300_000,
            assessed_value=300_000,
        )
        s = score_parcel(p, today=TODAY,
                         has_active_lis_pendens=False,
                         tax_years_delinq=None,
                         code_violation_count=None)
        self.assertEqual(s.total_score, 0)

    def test_foreclosure_signal(self):
        p = make_parcel()
        s = score_parcel(p, today=TODAY,
                         has_active_lis_pendens=True,
                         tax_years_delinq=None,
                         code_violation_count=None)
        self.assertEqual(s.signals.get("foreclosure"), WEIGHT_FORECLOSURE)

    def test_tax_delinquent_signal(self):
        p = make_parcel()
        s = score_parcel(p, today=TODAY,
                         has_active_lis_pendens=False,
                         tax_years_delinq=2,
                         code_violation_count=None)
        self.assertEqual(s.signals.get("tax_delinquent"), WEIGHT_TAX_DELINQUENT)

    def test_code_violations_threshold(self):
        p = make_parcel()
        # Below threshold — no points
        s2 = score_parcel(p, today=TODAY,
                          has_active_lis_pendens=False,
                          tax_years_delinq=None,
                          code_violation_count=2)
        self.assertNotIn("code_violations", s2.signals)
        # At threshold — points awarded
        s3 = score_parcel(p, today=TODAY,
                          has_active_lis_pendens=False,
                          tax_years_delinq=None,
                          code_violation_count=3)
        self.assertEqual(s3.signals.get("code_violations"), WEIGHT_CODE_VIOLATIONS)

    def test_hold_time_signal(self):
        # Owned 12 years (sale_date 2014)
        p = make_parcel(sale_date=date(2014, 1, 1))
        s = score_parcel(p, today=TODAY,
                         has_active_lis_pendens=False,
                         tax_years_delinq=None,
                         code_violation_count=None)
        self.assertEqual(s.signals.get("hold_time"), WEIGHT_HOLD_TIME)

    def test_hold_time_not_long_enough(self):
        p = make_parcel(sale_date=date(2020, 1, 1))  # 6 years held
        s = score_parcel(p, today=TODAY,
                         has_active_lis_pendens=False,
                         tax_years_delinq=None,
                         code_violation_count=None)
        self.assertNotIn("hold_time", s.signals)

    def test_equity_signal(self):
        # Bought $100K, now assessed at $200K — 2x ratio (above 1.5 threshold)
        p = make_parcel(sale_price=100_000, assessed_value=200_000)
        s = score_parcel(p, today=TODAY,
                         has_active_lis_pendens=False,
                         tax_years_delinq=None,
                         code_violation_count=None)
        self.assertEqual(s.signals.get("equity"), WEIGHT_EQUITY)

    def test_out_of_state_signal(self):
        p = make_parcel(owner_state="NY")
        s = score_parcel(p, today=TODAY,
                         has_active_lis_pendens=False,
                         tax_years_delinq=None,
                         code_violation_count=None)
        self.assertEqual(s.signals.get("out_of_state_mailing"), WEIGHT_OUT_OF_STATE_MAILING)

    def test_no_homestead_signal(self):
        p = make_parcel(homestead_exempt=False)
        s = score_parcel(p, today=TODAY,
                         has_active_lis_pendens=False,
                         tax_years_delinq=None,
                         code_violation_count=None)
        self.assertEqual(s.signals.get("no_homestead"), WEIGHT_NO_HOMESTEAD)


class TestMaxScore(unittest.TestCase):
    """A parcel with every signal hot should score the maximum."""

    def test_kitchen_sink(self):
        # Long-held, out-of-state owner, no homestead, high equity, foreclosed,
        # tax-delinquent, multiple code violations
        p = make_parcel(
            sale_date=date(2010, 1, 1),    # 16 years held
            sale_price=80_000,
            assessed_value=300_000,         # 3.75x equity
            owner_state="NY",
            homestead_exempt=False,
        )
        s = score_parcel(p, today=TODAY,
                         has_active_lis_pendens=True,
                         tax_years_delinq=3,
                         code_violation_count=5)
        expected = (WEIGHT_FORECLOSURE + WEIGHT_TAX_DELINQUENT
                    + WEIGHT_CODE_VIOLATIONS + WEIGHT_HOLD_TIME
                    + WEIGHT_EQUITY + WEIGHT_OUT_OF_STATE_MAILING
                    + WEIGHT_NO_HOMESTEAD)
        self.assertEqual(s.total_score, expected)
        self.assertEqual(expected, 105)


class TestScoreAll(unittest.TestCase):
    """End-to-end on the synthetic dataset — confirm the pipeline runs."""

    def test_synthetic_run(self):
        parcels, tax_idx, lp_idx, code_idx = synthetic_dataset(500, seed=42)
        scored = score_all(parcels, tax_idx, lp_idx, code_idx, today=TODAY)
        self.assertEqual(len(scored), 500)
        # Should be sorted desc by score
        for i in range(len(scored) - 1):
            self.assertGreaterEqual(scored[i].total_score, scored[i + 1].total_score)
        # Some parcels should score above 50 (the default min_score threshold)
        self.assertGreater(sum(1 for s in scored if s.total_score >= 50), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
