#!/usr/bin/env python3
"""
sell_score.py — Phase 1 motivated-seller scoring for Miami-Dade homeowners.

Score every Miami-Dade homeowner on likelihood of being a motivated seller.
The top N (default 5,000 with score ≥ 50) become:

  - The seed for direct-mail letter campaigns (Handwrytten / Lob)
  - Hashed → uploaded to Facebook Ads as a Custom Audience
  - The 1% Lookalike from this audience targets the seller-side ads

Phase 1 uses ONLY public Miami-Dade data sources (no MLS, no paid skip-trace):

  parcels.csv             — Miami-Dade Property Appraiser bulk export
  tax_delinquent.csv      — Miami-Dade Tax Collector
  lis_pendens.csv         — Miami-Dade Clerk of Courts (foreclosure filings)
  code_violations.csv     — Miami-Dade Code Compliance

Each homeowner's score is the sum of independent signals (per the sprint Day
4 weights):

  Foreclosure (active lis pendens)         30 pts
  Tax-delinquent 1+ years                  25 pts
  Long hold-time 10+ years                 10 pts
  Equity (assessed_val ≥ 1.5× sale_price)  15 pts
  Code violations 3+ active                15 pts
  Out-of-state mailing address              5 pts
  No homestead exemption                    5 pts
                                          ----
  Maximum total                           105 pts

Output: ~/dealmatcher/data/sell_score_YYYYMMDD.csv with one row per scored
parcel, sorted by total score desc. Includes per-signal contributions so you
can see WHY a property scored — invaluable for letter-copy personalization.

Run on your Mac:
    cd ~/dealmatcher
    python3 tools/sell_score.py

Run on a synthetic test dataset to verify the engine works without real CSVs:
    python3 tools/sell_score.py --synthetic
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = SCRIPT_DIR / "data"

# ---------------------------------------------------------------------------
# Default input paths — user can override via CLI flags. All optional;
# scoring degrades gracefully when a source is missing (just no points
# from that signal).
# ---------------------------------------------------------------------------

DEFAULT_PARCELS  = DATA_DIR / "parcels.csv"
DEFAULT_TAX      = DATA_DIR / "tax_delinquent.csv"
DEFAULT_LP       = DATA_DIR / "lis_pendens.csv"
DEFAULT_CODE     = DATA_DIR / "code_violations.csv"


# ---------------------------------------------------------------------------
# Score weights — per sprint Day 4 spec
# ---------------------------------------------------------------------------

WEIGHT_FORECLOSURE          = 30
WEIGHT_TAX_DELINQUENT       = 25
WEIGHT_CODE_VIOLATIONS      = 15
WEIGHT_HOLD_TIME            = 10
WEIGHT_EQUITY               = 15
WEIGHT_OUT_OF_STATE_MAILING = 5
WEIGHT_NO_HOMESTEAD         = 5

HOLD_TIME_THRESHOLD_YEARS   = 10
EQUITY_RATIO_THRESHOLD      = 1.5     # assessed_value >= 1.5 × original sale_price
CODE_VIOLATIONS_THRESHOLD   = 3
TAX_DELINQUENT_MIN_YEARS    = 1
DEFAULT_TOP_N               = 5000
DEFAULT_MIN_SCORE           = 50

FL_STATE_TOKENS = ("FL", "FLA", "FLORIDA")


# ---------------------------------------------------------------------------
# Schema synonyms — match common ArcGIS / public-data column names so a
# downloaded CSV "just works" without renaming columns
# ---------------------------------------------------------------------------

SYNONYMS = {
    # parcels.csv
    "parcel_id":         ("PARCEL_ID", "FOLIO", "Folio", "PARCELID", "FOLIO_NUMBER"),
    "owner_name":        ("OWNER1", "OWNER", "OWNER_NAME", "Owner", "OwnerName"),
    "owner_state":       ("OWNER_STATE", "OwnerState", "OWNER_ST", "MAIL_STATE"),
    "property_address":  ("ADDRESS", "SITE_ADDRESS", "PROPERTY_ADDRESS", "Address"),
    "city":              ("CITY", "City", "MUNICIPALITY"),
    "zip":               ("ZIP", "ZIPCODE", "ZIP_CODE", "Zip", "PostalCode"),
    "year_built":        ("YEAR_BUILT", "YearBuilt", "YEAR_BLT"),
    "total_living_area": ("ADJ_BLD_SQ_FT", "BLD_SQ_FOOTAGE", "TOTAL_LIV_SQ_FT", "SQFT"),
    "just_value":        ("JV", "JUST_VALUE", "JustValue", "MARKET_VALUE"),
    "assessed_value":    ("AV", "ASSESSED_VALUE", "AssessedValue"),
    "sale_date":         ("SALE_DATE", "LAST_SALE_DATE", "SaleDate"),
    "sale_price":        ("SALE_AMT", "SALE_PRICE", "LAST_SALE_PRICE", "SalePrice"),
    "homestead_exempt":  ("HOMESTEAD", "HOMESTEAD_EXEMPT", "HX"),
    # tax_delinquent.csv
    "tax_years_delinq":  ("YEARS_DELINQUENT", "DELINQ_YEARS", "TAX_YEARS"),
    "tax_amount_owed":   ("AMOUNT_OWED", "BALANCE_DUE", "TAX_BALANCE"),
    # lis_pendens.csv
    "lp_filing_date":    ("FILING_DATE", "DATE_FILED", "FILED_DATE"),
    "lp_case_number":    ("CASE_NUMBER", "CASE_NO", "DOCKET"),
    # code_violations.csv
    "violation_count":   ("VIOLATION_COUNT", "ACTIVE_VIOLATIONS"),
    "total_fines":       ("TOTAL_FINES", "FINES", "PENALTY_AMOUNT"),
    "latest_violation":  ("LATEST_VIOLATION_DATE", "LAST_VIOLATION", "VIOLATION_DATE"),
}


def _resolve(headers: list[str], keys: tuple[str, ...]) -> dict[str, str]:
    """Map our logical names to whatever real column names are in the CSV."""
    norm = {h.strip(): h for h in headers}
    out: dict[str, str] = {}
    for logical in keys:
        for candidate in SYNONYMS.get(logical, ()):
            if candidate in norm:
                out[logical] = norm[candidate]
                break
    return out


def _to_int(s) -> Optional[int]:
    if s is None or s == "":
        return None
    s = str(s).replace(",", "").replace("$", "").strip()
    try:
        return int(float(s))
    except ValueError:
        return None


def _to_float(s) -> Optional[float]:
    if s is None or s == "":
        return None
    try:
        return float(str(s).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


def _to_date(s) -> Optional[date]:
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%m-%d-%Y", "%Y%m%d"):
        try:
            return datetime.strptime(s.split("T")[0], fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Parcel:
    parcel_id: str
    owner_name: str = ""
    owner_state: str = ""
    property_address: str = ""
    city: str = ""
    zip_code: str = ""
    year_built: Optional[int] = None
    total_living_area: Optional[int] = None
    just_value: Optional[int] = None
    assessed_value: Optional[int] = None
    sale_date: Optional[date] = None
    sale_price: Optional[int] = None
    homestead_exempt: bool = False


@dataclass
class ScoredParcel:
    parcel: Parcel
    total_score: int = 0
    signals: dict[str, int] = field(default_factory=dict)
    explanations: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# CSV loaders
# ---------------------------------------------------------------------------

def load_parcels(path: Path) -> dict[str, Parcel]:
    if not path.exists():
        raise FileNotFoundError(f"Parcels file not found: {path}")
    parcels: dict[str, Parcel] = {}
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols = _resolve(reader.fieldnames or [], (
            "parcel_id", "owner_name", "owner_state", "property_address",
            "city", "zip", "year_built", "total_living_area",
            "just_value", "assessed_value", "sale_date", "sale_price",
            "homestead_exempt",
        ))
        if "parcel_id" not in cols:
            raise ValueError(f"parcels.csv missing parcel_id column. Headers: {reader.fieldnames}")
        for row in reader:
            pid = (row.get(cols["parcel_id"]) or "").strip()
            if not pid:
                continue
            hx_raw = (row.get(cols.get("homestead_exempt", ""), "") or "").strip().lower()
            parcels[pid] = Parcel(
                parcel_id=pid,
                owner_name=(row.get(cols.get("owner_name", ""), "") or "").strip(),
                owner_state=(row.get(cols.get("owner_state", ""), "") or "").strip().upper(),
                property_address=(row.get(cols.get("property_address", ""), "") or "").strip(),
                city=(row.get(cols.get("city", ""), "") or "").strip(),
                zip_code=(row.get(cols.get("zip", ""), "") or "").strip(),
                year_built=_to_int(row.get(cols.get("year_built", ""), "")) if "year_built" in cols else None,
                total_living_area=_to_int(row.get(cols.get("total_living_area", ""), "")) if "total_living_area" in cols else None,
                just_value=_to_int(row.get(cols.get("just_value", ""), "")) if "just_value" in cols else None,
                assessed_value=_to_int(row.get(cols.get("assessed_value", ""), "")) if "assessed_value" in cols else None,
                sale_date=_to_date(row.get(cols.get("sale_date", ""), "")) if "sale_date" in cols else None,
                sale_price=_to_int(row.get(cols.get("sale_price", ""), "")) if "sale_price" in cols else None,
                homestead_exempt=hx_raw in ("y", "yes", "true", "1", "hx"),
            )
    return parcels


def load_index(path: Path, key_field: str, value_fields: tuple[str, ...]) -> dict[str, dict]:
    """Load a parcel-keyed CSV → {parcel_id: {logical_field: value, ...}}."""
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols = _resolve(reader.fieldnames or [], (key_field,) + value_fields)
        if key_field not in cols:
            return out
        for row in reader:
            k = (row.get(cols[key_field]) or "").strip()
            if not k:
                continue
            entry: dict = {}
            for vf in value_fields:
                if vf in cols:
                    entry[vf] = row.get(cols[vf])
            # If multiple rows per key, accumulate (e.g. multiple lis pendens)
            if k in out:
                if isinstance(out[k], list):
                    out[k].append(entry)
                else:
                    out[k] = [out[k], entry]
            else:
                out[k] = entry
    return out


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_parcel(
    parcel: Parcel,
    *,
    today: date,
    has_active_lis_pendens: bool,
    tax_years_delinq: Optional[int],
    code_violation_count: Optional[int],
) -> ScoredParcel:
    sp = ScoredParcel(parcel=parcel)

    # 1. Foreclosure (active lis pendens)
    if has_active_lis_pendens:
        sp.signals["foreclosure"] = WEIGHT_FORECLOSURE
        sp.explanations.append(f"Active foreclosure filing (+{WEIGHT_FORECLOSURE})")

    # 2. Tax delinquent
    if tax_years_delinq and tax_years_delinq >= TAX_DELINQUENT_MIN_YEARS:
        sp.signals["tax_delinquent"] = WEIGHT_TAX_DELINQUENT
        sp.explanations.append(
            f"Tax-delinquent {tax_years_delinq}y (+{WEIGHT_TAX_DELINQUENT})"
        )

    # 3. Code violations
    if code_violation_count and code_violation_count >= CODE_VIOLATIONS_THRESHOLD:
        sp.signals["code_violations"] = WEIGHT_CODE_VIOLATIONS
        sp.explanations.append(
            f"{code_violation_count} active code violations (+{WEIGHT_CODE_VIOLATIONS})"
        )

    # 4. Long hold-time
    if parcel.sale_date:
        years_held = (today - parcel.sale_date).days / 365.25
        if years_held >= HOLD_TIME_THRESHOLD_YEARS:
            sp.signals["hold_time"] = WEIGHT_HOLD_TIME
            sp.explanations.append(f"Held {years_held:.0f}y (+{WEIGHT_HOLD_TIME})")

    # 5. High equity (assessed value much greater than original sale price)
    if (parcel.assessed_value and parcel.sale_price
            and parcel.sale_price > 0
            and parcel.assessed_value / parcel.sale_price >= EQUITY_RATIO_THRESHOLD):
        sp.signals["equity"] = WEIGHT_EQUITY
        sp.explanations.append(
            f"High equity: assessed ${parcel.assessed_value:,} vs sale ${parcel.sale_price:,} "
            f"(+{WEIGHT_EQUITY})"
        )

    # 6. Out-of-state mailing address (vacancy / absentee proxy)
    if parcel.owner_state and parcel.owner_state not in FL_STATE_TOKENS:
        sp.signals["out_of_state_mailing"] = WEIGHT_OUT_OF_STATE_MAILING
        sp.explanations.append(
            f"Out-of-state mailing ({parcel.owner_state}) (+{WEIGHT_OUT_OF_STATE_MAILING})"
        )

    # 7. No homestead exemption (rental / abandoned proxy)
    if not parcel.homestead_exempt:
        sp.signals["no_homestead"] = WEIGHT_NO_HOMESTEAD
        sp.explanations.append(f"No homestead exemption (+{WEIGHT_NO_HOMESTEAD})")

    sp.total_score = sum(sp.signals.values())
    return sp


def score_all(
    parcels: dict[str, Parcel],
    tax_idx: dict,
    lp_idx: dict,
    code_idx: dict,
    *,
    today: Optional[date] = None,
) -> list[ScoredParcel]:
    today = today or date.today()
    results: list[ScoredParcel] = []
    for pid, parcel in parcels.items():
        # Lis pendens — active = filed in last 2 years (rough heuristic, since we
        # don't always have a "case_resolved" date in public records)
        has_lp = False
        lp_entry = lp_idx.get(pid)
        if lp_entry:
            entries = lp_entry if isinstance(lp_entry, list) else [lp_entry]
            for e in entries:
                d = _to_date(e.get("lp_filing_date"))
                if d and (today - d).days <= 365 * 2:
                    has_lp = True
                    break

        # Tax — most recent record per parcel
        tax_entry = tax_idx.get(pid)
        if isinstance(tax_entry, list):
            tax_entry = tax_entry[-1]
        tax_years = _to_int(tax_entry.get("tax_years_delinq")) if tax_entry else None

        # Code violations — count
        code_entry = code_idx.get(pid)
        if isinstance(code_entry, list):
            cv_count = len(code_entry)
        elif code_entry:
            cv_count = _to_int(code_entry.get("violation_count")) or 1
        else:
            cv_count = None

        results.append(score_parcel(
            parcel,
            today=today,
            has_active_lis_pendens=has_lp,
            tax_years_delinq=tax_years,
            code_violation_count=cv_count,
        ))

    results.sort(key=lambda s: s.total_score, reverse=True)
    return results


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

OUTPUT_FIELDS = [
    "parcel_id", "owner_name", "property_address", "city", "zip",
    "owner_state", "homestead_exempt",
    "year_built", "total_living_area",
    "sale_date", "sale_price", "assessed_value",
    "total_score",
    "score_foreclosure", "score_tax_delinquent", "score_code_violations",
    "score_hold_time", "score_equity",
    "score_out_of_state_mailing", "score_no_homestead",
    "explanations",
]


def write_csv(scored: list[ScoredParcel], path: Path, top_n: int, min_score: int) -> int:
    path.parent.mkdir(exist_ok=True)
    written = 0
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        w.writeheader()
        for s in scored:
            if s.total_score < min_score:
                continue
            if written >= top_n:
                break
            p = s.parcel
            w.writerow({
                "parcel_id": p.parcel_id,
                "owner_name": p.owner_name,
                "property_address": p.property_address,
                "city": p.city,
                "zip": p.zip_code,
                "owner_state": p.owner_state,
                "homestead_exempt": "Y" if p.homestead_exempt else "N",
                "year_built": p.year_built or "",
                "total_living_area": p.total_living_area or "",
                "sale_date": p.sale_date.isoformat() if p.sale_date else "",
                "sale_price": p.sale_price or "",
                "assessed_value": p.assessed_value or "",
                "total_score": s.total_score,
                "score_foreclosure":          s.signals.get("foreclosure", 0),
                "score_tax_delinquent":       s.signals.get("tax_delinquent", 0),
                "score_code_violations":      s.signals.get("code_violations", 0),
                "score_hold_time":            s.signals.get("hold_time", 0),
                "score_equity":               s.signals.get("equity", 0),
                "score_out_of_state_mailing": s.signals.get("out_of_state_mailing", 0),
                "score_no_homestead":         s.signals.get("no_homestead", 0),
                "explanations": " | ".join(s.explanations),
            })
            written += 1
    return written


# ---------------------------------------------------------------------------
# Synthetic test data — for verifying the engine without real CSVs
# ---------------------------------------------------------------------------

def synthetic_dataset(n: int = 1000, seed: int = 42) -> tuple[dict[str, Parcel], dict, dict, dict]:
    rng = random.Random(seed)
    today = date.today()
    parcels: dict[str, Parcel] = {}
    tax: dict = {}
    lp: dict = {}
    code: dict = {}

    for i in range(n):
        pid = f"FOLIO{i:08d}"
        sale_year_offset = rng.randint(0, 20)
        sale_d = today - timedelta(days=sale_year_offset * 365)
        base_price = rng.randint(80_000, 600_000)
        # ~25% appreciation per year on average for kicks
        assessed = int(base_price * (1 + 0.05 * sale_year_offset))
        homestead = rng.random() > 0.4
        owner_state = rng.choices(["FL", "NY", "NJ", "CA", "TX"], weights=[80, 5, 5, 5, 5])[0]

        parcels[pid] = Parcel(
            parcel_id=pid,
            owner_name=f"Owner {i}",
            owner_state=owner_state,
            property_address=f"{1000 + i} Test St",
            city=rng.choice(["Miami", "Hialeah", "Homestead", "Doral"]),
            zip_code=rng.choice(["33125", "33142", "33147", "33168", "33034"]),
            year_built=rng.randint(1950, 2020),
            total_living_area=rng.randint(900, 3500),
            just_value=assessed,
            assessed_value=assessed,
            sale_date=sale_d,
            sale_price=base_price,
            homestead_exempt=homestead,
        )

        # Sprinkle distress signals at realistic rates
        if rng.random() < 0.05:  # 5% in foreclosure
            lp[pid] = {"lp_filing_date": (today - timedelta(days=rng.randint(30, 700))).isoformat(),
                       "lp_case_number": f"2026-CA-{rng.randint(1000,9999)}"}
        if rng.random() < 0.08:  # 8% tax-delinquent
            tax[pid] = {"tax_years_delinq": str(rng.randint(1, 5)),
                        "tax_amount_owed": str(rng.randint(2000, 25000))}
        if rng.random() < 0.04:  # 4% code violation hotspots
            code[pid] = [{"violation_count": "1"} for _ in range(rng.randint(3, 8))]

    return parcels, tax, lp, code


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--parcels",  type=Path, default=DEFAULT_PARCELS)
    p.add_argument("--tax",      type=Path, default=DEFAULT_TAX)
    p.add_argument("--lp",       type=Path, default=DEFAULT_LP)
    p.add_argument("--code",     type=Path, default=DEFAULT_CODE)
    p.add_argument("--top-n",    type=int,  default=DEFAULT_TOP_N)
    p.add_argument("--min-score",type=int,  default=DEFAULT_MIN_SCORE)
    p.add_argument("--output",   type=Path, default=None,
                   help="Output path (default: data/sell_score_YYYYMMDD.csv)")
    p.add_argument("--synthetic",action="store_true",
                   help="Run with a 1000-parcel synthetic dataset (no CSVs needed)")
    args = p.parse_args()

    if args.synthetic:
        print("Generating 1000 synthetic parcels for engine verification...")
        parcels, tax_idx, lp_idx, code_idx = synthetic_dataset(1000)
    else:
        if not args.parcels.exists():
            print(f"ERROR: parcels file not found: {args.parcels}")
            print("Download Miami-Dade Property Appraiser bulk data from:")
            print("  https://gis-mdc.opendata.arcgis.com (search 'Parcel') OR")
            print("  https://bbs.miamidade.gov/  ($50/file, weekly refresh)")
            print()
            print("Or test the engine without real data:")
            print("  python3 tools/sell_score.py --synthetic")
            sys.exit(2)
        print(f"Loading parcels from {args.parcels}...")
        parcels = load_parcels(args.parcels)
        print(f"  {len(parcels):,} parcels loaded")
        print(f"Loading tax-delinquent index from {args.tax}...")
        tax_idx = load_index(args.tax, "parcel_id", ("tax_years_delinq", "tax_amount_owed"))
        print(f"  {len(tax_idx):,} tax-delinquent parcels")
        print(f"Loading lis pendens index from {args.lp}...")
        lp_idx = load_index(args.lp, "parcel_id", ("lp_filing_date", "lp_case_number"))
        print(f"  {len(lp_idx):,} lis pendens parcels")
        print(f"Loading code violations index from {args.code}...")
        code_idx = load_index(args.code, "parcel_id", ("violation_count", "total_fines"))
        print(f"  {len(code_idx):,} code-violation parcels")

    print()
    print(f"Scoring {len(parcels):,} parcels...")
    scored = score_all(parcels, tax_idx, lp_idx, code_idx)

    by_score: dict[int, int] = {}
    for s in scored:
        by_score[s.total_score] = by_score.get(s.total_score, 0) + 1
    print()
    print("Score distribution (top scores):")
    for score in sorted(by_score.keys(), reverse=True)[:15]:
        print(f"  {score:>3} pts:  {by_score[score]:>5,} parcels")

    out_path = args.output or (DATA_DIR / f"sell_score_{date.today().strftime('%Y%m%d')}.csv")
    written = write_csv(scored, out_path, args.top_n, args.min_score)
    print()
    print(f"Wrote top {written:,} parcels (score ≥ {args.min_score}) to {out_path}")
    if scored:
        top = scored[0]
        print()
        print(f"Top-scored parcel: {top.parcel.property_address} "
              f"({top.parcel.owner_name}) — score {top.total_score}")
        for ex in top.explanations:
            print(f"  • {ex}")


if __name__ == "__main__":
    main()
