#!/usr/bin/env python3
"""
build_below_market_seed.py — find Miami-Dade properties bought far below
local market value.

Output: ~/dealmatcher/data/below_market_seed.csv — used as:
  - Sprint Day 4: input to the Sell Score Phase 1 scoring engine.
  - Sprint Day 6: hashed CSV uploaded to Facebook Ads as a Custom
    Audience seed. The 1% Lookalike built off these "savvy buyer"
    profiles is the targeting layer for the seller-side ad campaign.

Algorithm (matches sprint Day 3 spec):
  1. Load Miami-Dade Comparable Sales (deed transfers w/ price + geo).
  2. Filter to sales within the last 24 months.
  3. For each recent sale, find comparable sales within 0.25 mi sold
     in the 6 months PRIOR to that sale's date (fresh comps only).
  4. Compute median price-per-sqft of comps; multiply by subject sqft
     to get expected value.
  5. Flag if sale_price <= 60% of expected value (sprint threshold).
  6. Emit one row per below-market sale, sorted by ratio ascending.

Two input modes:
  --csv  PATH       (default) Read a CSV downloaded from the MD Open Data
                    Hub Comparable Sales dataset. Free download — visit
                    https://gis-mdc.opendata.arcgis.com and search for
                    "Comparable Sales", then click Download → CSV.
  --api  BASE_URL   Query the ArcGIS REST FeatureServer directly. Slower
                    and rate-limited, but always fresh.

Run on your Mac (sandbox can't reach the MD ArcGIS host):
  cd ~/dealmatcher

  # First time — download the CSV from gis-mdc.opendata.arcgis.com
  # Save as data/miami_dade_comparable_sales.csv
  python3 tools/build_below_market_seed.py

  # Or with explicit args:
  python3 tools/build_below_market_seed.py \\
      --csv data/miami_dade_comparable_sales.csv \\
      --radius-mi 0.25 \\
      --comp-window-months 6 \\
      --max-ratio 0.60 \\
      --lookback-months 24
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Iterable, Optional

SCRIPT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CSV = SCRIPT_DIR / "data" / "miami_dade_comparable_sales.csv"
DEFAULT_OUTPUT = SCRIPT_DIR / "data" / "below_market_seed.csv"


# ---------------------------------------------------------------------------
# Schema mapping
# ---------------------------------------------------------------------------
#
# The MD Open Data Hub Comparable Sales export uses ArcGIS field names
# which are case-sensitive and sometimes differ from the friendly UI
# labels. We accept multiple synonyms per logical field and map them to
# our internal Sale dataclass. If your CSV uses different headers, edit
# this table — no code changes needed below.

FIELD_SYNONYMS = {
    "parcel_id":      ("PARCEL_ID", "FOLIO", "Folio", "PARCELID", "PARCEL", "ParcelID"),
    "sale_date":      ("SALE_DATE", "SaleDate", "DATE_OF_SALE", "DateOfSale", "SALEDATE"),
    "sale_price":     ("SALE_AMT", "SALE_PRICE", "SalePrice", "PRICE", "SaleAmt", "AMOUNT"),
    "sqft":           ("ADJ_BLD_SQ_FT", "BLD_SQ_FOOTAGE", "TOTAL_LIV_SQ_FT", "SQFT",
                       "BUILDING_SQFT", "LIV_SQ_FT", "SqFt", "TotalLiv"),
    "lat":            ("LATITUDE", "Lat", "Y", "POINT_Y"),
    "lon":            ("LONGITUDE", "Lon", "Long", "X", "POINT_X"),
    "address":        ("ADDRESS", "Address", "SITE_ADDRESS", "PROPERTY_ADDRESS"),
    "city":           ("CITY", "City", "MUNICIPALITY"),
    "zip":            ("ZIP", "Zip", "ZIPCODE", "PostalCode", "ZIP_CODE"),
    "owner":          ("OWNER", "Owner", "OWNER_NAME", "OWNER1"),
    "property_type":  ("DOR_CODE_DESC", "PROP_TYPE", "PropertyType", "USE_DESC"),
    "year_built":     ("YEAR_BUILT", "YearBuilt", "YEAR_BLT"),
}


def _resolve_columns(headers: list[str]) -> dict[str, str]:
    """Map our logical fields to whichever real column name is present."""
    norm = {h.strip(): h for h in headers}
    resolved = {}
    for logical, candidates in FIELD_SYNONYMS.items():
        for c in candidates:
            if c in norm:
                resolved[logical] = norm[c]
                break
    return resolved


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class Sale:
    parcel_id: str
    sale_date: date
    sale_price: int
    sqft: Optional[int]
    lat: float
    lon: float
    address: str = ""
    city: str = ""
    zip_code: str = ""
    owner: str = ""
    property_type: str = ""
    year_built: Optional[int] = None

    @property
    def price_per_sqft(self) -> Optional[float]:
        if not self.sqft or self.sqft <= 0:
            return None
        return self.sale_price / self.sqft


# ---------------------------------------------------------------------------
# CSV ingest
# ---------------------------------------------------------------------------

def _parse_date(s: str) -> Optional[date]:
    if not s:
        return None
    s = s.strip()
    # ArcGIS dates often come as ISO 8601 or epoch milliseconds
    if s.isdigit() and len(s) >= 10:
        try:
            ms = int(s)
            # If it's > 10 digits assume milliseconds since epoch
            ts = ms / 1000 if len(s) > 10 else ms
            return datetime.utcfromtimestamp(ts).date()
        except (ValueError, OSError):
            pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s.split(".")[0], fmt).date()
        except ValueError:
            continue
    return None


def _parse_int(s) -> Optional[int]:
    if s is None or s == "":
        return None
    if isinstance(s, (int, float)):
        return int(s)
    s = str(s).replace("$", "").replace(",", "").strip()
    try:
        return int(float(s))
    except ValueError:
        return None


def _parse_float(s) -> Optional[float]:
    if s is None or s == "":
        return None
    try:
        return float(str(s).replace(",", "").strip())
    except ValueError:
        return None


def load_sales_from_csv(path: Path) -> list[Sale]:
    """Load Miami-Dade comparable sales from a CSV download."""
    if not path.exists():
        raise FileNotFoundError(
            f"CSV not found: {path}\n\n"
            "Download Miami-Dade Comparable Sales:\n"
            "  1. Visit https://gis-mdc.opendata.arcgis.com\n"
            "  2. Search 'Comparable Sales' and open the dataset\n"
            "  3. Click Download → CSV\n"
            f"  4. Save as: {path}"
        )

    sales: list[Sale] = []
    skipped = 0
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols = _resolve_columns(reader.fieldnames or [])
        missing = [k for k in ("parcel_id", "sale_date", "sale_price", "lat", "lon") if k not in cols]
        if missing:
            raise ValueError(
                f"CSV missing required columns: {missing}\n"
                f"Detected columns: {reader.fieldnames}\n"
                f"Edit FIELD_SYNONYMS in this script to map your columns."
            )
        for row in reader:
            sd = _parse_date(row.get(cols["sale_date"], ""))
            sp = _parse_int(row.get(cols["sale_price"], ""))
            la = _parse_float(row.get(cols["lat"], ""))
            lo = _parse_float(row.get(cols["lon"], ""))
            if not (sd and sp and la and lo and sp > 0):
                skipped += 1
                continue
            sales.append(Sale(
                parcel_id=row.get(cols["parcel_id"], "").strip(),
                sale_date=sd,
                sale_price=sp,
                sqft=_parse_int(row.get(cols.get("sqft", ""), "")) if "sqft" in cols else None,
                lat=la, lon=lo,
                address=row.get(cols.get("address", ""), "").strip() if "address" in cols else "",
                city=row.get(cols.get("city", ""), "").strip() if "city" in cols else "",
                zip_code=row.get(cols.get("zip", ""), "").strip() if "zip" in cols else "",
                owner=row.get(cols.get("owner", ""), "").strip() if "owner" in cols else "",
                property_type=row.get(cols.get("property_type", ""), "").strip() if "property_type" in cols else "",
                year_built=_parse_int(row.get(cols.get("year_built", ""), "")) if "year_built" in cols else None,
            ))
    print(f"  Loaded {len(sales)} valid sales from {path.name}  (skipped {skipped} rows missing required fields)")
    return sales


# ---------------------------------------------------------------------------
# Geodesic distance — haversine, no scipy/geopy dep
# ---------------------------------------------------------------------------

EARTH_RADIUS_MI = 3958.7613


def haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in miles between two lat/lon points."""
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Below-market detection
# ---------------------------------------------------------------------------

@dataclass
class BelowMarketHit:
    sale: Sale
    n_comps: int
    median_psf: float
    expected_value: int
    ratio: float


def find_below_market(
    sales: Iterable[Sale],
    *,
    today: Optional[date] = None,
    lookback_months: int = 24,
    radius_mi: float = 0.25,
    comp_window_months: int = 6,
    max_ratio: float = 0.60,
    min_comps: int = 3,
) -> list[BelowMarketHit]:
    """Find sales whose price ≤ max_ratio × median local comps."""
    today = today or date.today()
    lookback_cutoff = today - timedelta(days=lookback_months * 30)
    comp_window_days = comp_window_months * 30

    sales_list = [s for s in sales if s.sqft and s.sqft > 0 and s.price_per_sqft]
    recent = [s for s in sales_list if s.sale_date >= lookback_cutoff]

    print(f"  {len(sales_list)} sales w/ sqft, of which {len(recent)} are within last {lookback_months} months")

    hits: list[BelowMarketHit] = []
    for i, subject in enumerate(recent):
        if i and i % 1000 == 0:
            print(f"    scanning {i}/{len(recent)} ({len(hits)} below-market so far)")
        comp_start = subject.sale_date - timedelta(days=comp_window_days)
        comp_end = subject.sale_date  # strictly prior

        comps_psf: list[float] = []
        for c in sales_list:
            if c.parcel_id == subject.parcel_id:
                continue
            if not (comp_start <= c.sale_date < comp_end):
                continue
            if c.price_per_sqft is None:
                continue
            d = haversine_mi(subject.lat, subject.lon, c.lat, c.lon)
            if d > radius_mi:
                continue
            comps_psf.append(c.price_per_sqft)

        if len(comps_psf) < min_comps:
            continue

        # Trim outliers (5th-95th pct) before median to dampen flips
        comps_psf.sort()
        lo = max(1, len(comps_psf) // 20)
        hi = len(comps_psf) - lo
        trimmed = comps_psf[lo:hi] if hi > lo else comps_psf
        med_psf = median(trimmed)
        expected = int(med_psf * subject.sqft)
        if expected <= 0:
            continue

        ratio = subject.sale_price / expected
        if ratio <= max_ratio:
            hits.append(BelowMarketHit(
                sale=subject,
                n_comps=len(comps_psf),
                median_psf=med_psf,
                expected_value=expected,
                ratio=ratio,
            ))

    hits.sort(key=lambda h: h.ratio)
    return hits


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

OUTPUT_FIELDS = [
    "parcel_id", "address", "city", "zip", "owner", "property_type", "year_built",
    "sale_date", "sale_price", "sqft", "n_comps", "median_psf",
    "expected_value", "ratio_to_market", "lat", "lon",
]


def write_seed_csv(hits: list[BelowMarketHit], path: Path) -> None:
    path.parent.mkdir(exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        w.writeheader()
        for h in hits:
            s = h.sale
            w.writerow({
                "parcel_id": s.parcel_id,
                "address": s.address,
                "city": s.city,
                "zip": s.zip_code,
                "owner": s.owner,
                "property_type": s.property_type,
                "year_built": s.year_built or "",
                "sale_date": s.sale_date.isoformat(),
                "sale_price": s.sale_price,
                "sqft": s.sqft,
                "n_comps": h.n_comps,
                "median_psf": f"{h.median_psf:.2f}",
                "expected_value": h.expected_value,
                "ratio_to_market": f"{h.ratio:.3f}",
                "lat": s.lat,
                "lon": s.lon,
            })


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", type=Path, default=DEFAULT_CSV,
                   help="Path to MD Comparable Sales CSV download")
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                   help="Output below_market_seed.csv path")
    p.add_argument("--lookback-months", type=int, default=24)
    p.add_argument("--radius-mi", type=float, default=0.25)
    p.add_argument("--comp-window-months", type=int, default=6)
    p.add_argument("--max-ratio", type=float, default=0.60)
    p.add_argument("--min-comps", type=int, default=3)
    args = p.parse_args()

    print(f"Loading sales from {args.csv} ...")
    sales = load_sales_from_csv(args.csv)
    print()
    print(f"Scanning for below-market sales:")
    print(f"  lookback:        {args.lookback_months} months")
    print(f"  comp radius:     {args.radius_mi} miles")
    print(f"  comp window:     {args.comp_window_months} months prior to subject sale")
    print(f"  threshold:       sale_price ≤ {args.max_ratio*100:.0f}% of expected")
    print(f"  min comps:       {args.min_comps}")
    print()
    hits = find_below_market(
        sales,
        lookback_months=args.lookback_months,
        radius_mi=args.radius_mi,
        comp_window_months=args.comp_window_months,
        max_ratio=args.max_ratio,
        min_comps=args.min_comps,
    )
    print()
    print(f"Found {len(hits)} below-market sales.")
    if hits:
        ratios = [h.ratio for h in hits]
        print(f"  ratio distribution:  min={min(ratios):.2f}  median={median(ratios):.2f}  max={max(ratios):.2f}")
        print(f"  top 5 deals:")
        for h in hits[:5]:
            s = h.sale
            print(f"    {s.address[:50]:<50} {s.sale_date}  ${s.sale_price:>10,}  ratio={h.ratio:.2f}  ({h.n_comps} comps)")
    write_seed_csv(hits, args.output)
    print(f"\n→ Saved: {args.output}")


if __name__ == "__main__":
    main()
