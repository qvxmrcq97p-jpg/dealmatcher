"""Unit tests for the below-market seed builder.

Run from ~/dealmatcher/:
    python3 tests/test_below_market_seed.py
"""
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

from build_below_market_seed import (  # noqa: E402
    Sale,
    haversine_mi,
    find_below_market,
)


def make_sale(
    parcel: str,
    price: int,
    sqft: int,
    sale_date: date,
    lat: float = 25.7617,   # Miami centroid
    lon: float = -80.1918,
) -> Sale:
    return Sale(
        parcel_id=parcel,
        sale_date=sale_date,
        sale_price=price,
        sqft=sqft,
        lat=lat,
        lon=lon,
    )


class TestHaversine(unittest.TestCase):

    def test_zero_distance(self):
        self.assertAlmostEqual(haversine_mi(25.7617, -80.1918, 25.7617, -80.1918), 0.0, places=4)

    def test_known_distance(self):
        # Miami → Fort Lauderdale roughly 22-25 miles
        d = haversine_mi(25.7617, -80.1918, 26.1224, -80.1373)
        self.assertGreater(d, 20)
        self.assertLess(d, 30)

    def test_sub_quarter_mile(self):
        # 0.001 deg of latitude ≈ 0.069 miles — well under 0.25
        d = haversine_mi(25.7617, -80.1918, 25.7627, -80.1918)
        self.assertLess(d, 0.25)


class TestBelowMarketDetection(unittest.TestCase):
    """Build a synthetic neighborhood and verify a known steal is flagged."""

    def setUp(self):
        # Anchor: Miami at $300/sqft typical. Subject is $100/sqft (33%).
        self.today = date(2026, 4, 30)
        self.subject_date = self.today - timedelta(days=60)
        comp_start = self.subject_date - timedelta(days=180)
        # 5 comparable sales in the 6 months prior, all at ~$300/sqft, all within 0.25mi
        self.sales = []
        for i in range(5):
            self.sales.append(make_sale(
                parcel=f"COMP-{i}",
                price=600_000,    # 2000 sqft × $300
                sqft=2000,
                sale_date=comp_start + timedelta(days=i * 20),
                lat=25.7617 + (i * 0.0005),  # ~30ft apart each
                lon=-80.1918 + (i * 0.0005),
            ))
        # The subject — bought at $200K for 2000 sqft = $100/sqft (33% of comp median)
        self.steal = make_sale(
            parcel="STEAL-1",
            price=200_000,
            sqft=2000,
            sale_date=self.subject_date,
        )
        self.sales.append(self.steal)

    def test_steal_is_flagged(self):
        hits = find_below_market(
            self.sales,
            today=self.today,
            lookback_months=24,
            radius_mi=0.25,
            comp_window_months=6,
            max_ratio=0.60,
            min_comps=3,
        )
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].sale.parcel_id, "STEAL-1")
        self.assertAlmostEqual(hits[0].ratio, 200_000 / 600_000, places=3)
        self.assertEqual(hits[0].n_comps, 5)

    def test_market_rate_not_flagged(self):
        # Add another sale at exactly market rate
        sales = list(self.sales)
        sales.append(make_sale(
            parcel="NORMAL-1",
            price=600_000,
            sqft=2000,
            sale_date=self.subject_date,
        ))
        hits = find_below_market(sales, today=self.today, max_ratio=0.60)
        # Only the steal should remain
        flagged = [h.sale.parcel_id for h in hits]
        self.assertIn("STEAL-1", flagged)
        self.assertNotIn("NORMAL-1", flagged)

    def test_too_few_comps_not_flagged(self):
        # Only 2 comps + the subject — below min_comps=3 threshold
        sparse = [
            make_sale("C1", 600_000, 2000, self.subject_date - timedelta(days=30)),
            make_sale("C2", 600_000, 2000, self.subject_date - timedelta(days=60)),
            self.steal,
        ]
        hits = find_below_market(sparse, today=self.today, min_comps=3)
        self.assertEqual(hits, [])

    def test_too_far_comps_not_used(self):
        # Move all comps 1+ mile away — outside 0.25mi radius
        sales = []
        for i in range(5):
            sales.append(make_sale(
                parcel=f"FAR-{i}",
                price=600_000,
                sqft=2000,
                sale_date=self.subject_date - timedelta(days=30 + i * 20),
                lat=25.7617 + 0.05,    # ~3.5 miles north
                lon=-80.1918,
            ))
        sales.append(self.steal)
        hits = find_below_market(sales, today=self.today)
        self.assertEqual(hits, [])

    def test_old_comps_not_used(self):
        # All comps from MORE than 6 months prior
        sales = []
        for i in range(5):
            sales.append(make_sale(
                parcel=f"OLD-{i}",
                price=600_000,
                sqft=2000,
                sale_date=self.subject_date - timedelta(days=300 + i * 10),
            ))
        sales.append(self.steal)
        hits = find_below_market(sales, today=self.today)
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
