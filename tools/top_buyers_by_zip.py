#!/usr/bin/env python3
"""
top_buyers_by_zip.py — rank the most active deed-buying investors per zip
in Miami-Dade over the last 24 months.

Drives two parts of the sprint:

  1. Stamp Top_Buyer_Zips__c on Salesforce Contacts that match a known
     active investor name. These buyers get the "YOU'RE A TOP BUYER IN
     THIS ZIP" callout in deal emails (render_per_buyer_email.py).

  2. Identify investor names + LLCs we DON'T have in Salesforce. Those
     become outreach targets — high-volume buyers we should onboard
     into the cheaphomesfla.com buyer list.

Approach:
  - Read miami_dade_comparable_sales.csv from the MD Open Data Hub
    (one row per deed transfer, with grantee/buyer name + zip + price).
  - Filter to last 24 months.
  - Group by (normalized_buyer_name, zip).
  - For each zip, rank buyers by deal count desc; keep top 100.
  - Cross-reference against Salesforce Contacts:
      • match by exact name → stamp Top_Buyer_Zips__c
      • match by LLC name in Buyer_Owner__c / Account → stamp Top_Buyer_Zips__c
      • no match → write to data/top_buyers_outreach_candidates.csv

Outputs:
  data/top_buyers_by_zip.json
      { "33125": [ {name, deals, total_volume, llc_flag}, ... 100 ], ... }
  data/top_buyers_outreach_candidates.csv
      Buyers in any zip's top 100 NOT in Salesforce — outreach targets.
  data/top_buyers_audit.txt
      Per-zip summary + matching stats.

Run:
  cd ~/dealmatcher
  python3 tools/top_buyers_by_zip.py                    # full run
  python3 tools/top_buyers_by_zip.py --no-sf-update     # skip SF writes
  python3 tools/top_buyers_by_zip.py --top-n 50         # top 50 per zip instead of 100
  python3 tools/top_buyers_by_zip.py --lookback-months 12  # last 12 mo

Schedule weekly (Sunday 11 PM) once running cleanly:
  Add to ~/dealmatcher/plists/com.cheaphomes.topbuyers.plist
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

ENV_FILE = SCRIPT_DIR / ".env.cheaphomesfla"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

DATA_DIR = SCRIPT_DIR / "data"
DEFAULT_SALES_CSV = DATA_DIR / "miami_dade_comparable_sales.csv"
TOP_BUYERS_JSON   = DATA_DIR / "top_buyers_by_zip.json"
OUTREACH_CSV      = DATA_DIR / "top_buyers_outreach_candidates.csv"
AUDIT_TXT         = DATA_DIR / "top_buyers_audit.txt"


# ---------------------------------------------------------------------------
# Schema synonyms (same idea as build_below_market_seed.py)
# ---------------------------------------------------------------------------

FIELD_SYNONYMS = {
    "buyer":         ("GRANTEE", "Grantee", "BUYER", "Buyer", "BUYER_NAME", "GranteeName"),
    "seller":        ("GRANTOR", "Grantor", "SELLER", "Seller", "GrantorName"),
    "sale_date":     ("SALE_DATE", "SaleDate", "DATE_OF_SALE", "SALEDATE", "RECORDED_DATE"),
    "sale_price":    ("SALE_AMT", "SALE_PRICE", "SalePrice", "AMOUNT", "PRICE", "SaleAmt"),
    "zip":           ("ZIP", "ZIPCODE", "Zip", "PostalCode", "ZIP_CODE", "PROPERTY_ZIP"),
    "address":       ("ADDRESS", "Address", "SITE_ADDRESS", "PROPERTY_ADDRESS"),
    "parcel_id":     ("PARCEL_ID", "FOLIO", "Folio", "PARCELID"),
}


def _resolve(headers: list[str], keys: tuple[str, ...]) -> dict[str, str]:
    norm = {h.strip(): h for h in headers}
    out: dict[str, str] = {}
    for logical in keys:
        for cand in FIELD_SYNONYMS.get(logical, ()):
            if cand in norm:
                out[logical] = norm[cand]
                break
    return out


def _parse_int(s) -> Optional[int]:
    if s is None or s == "":
        return None
    try:
        return int(float(str(s).replace(",", "").replace("$", "").strip()))
    except ValueError:
        return None


def _parse_date(s) -> Optional[date]:
    if not s:
        return None
    s = str(s).strip()
    if s.isdigit() and len(s) >= 10:
        try:
            return datetime.utcfromtimestamp(int(s) / (1000 if len(s) > 10 else 1)).date()
        except (ValueError, OSError):
            pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s.split(".")[0].split("T")[0]
                                     if "T" in s else s.split(".")[0], fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Buyer-name normalization
# ---------------------------------------------------------------------------

# Strip suffixes that don't add identity. Keep "LLC" / "INC" / "CORP" because
# they distinguish business buyers (likely full-time investors) from
# individuals.
_NAME_SUFFIX_NOISE = re.compile(
    r"\b(JR|SR|II|III|IV|ETALS?|ETAL|TRUSTEE|TRUST|REVOC|REV)\b\.?",
    re.IGNORECASE,
)
_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")

LLC_TOKENS = ("LLC", "INC", "CORP", "LP", "LTD", "LLP", "PLC", "GP", "PA")


def normalize_name(raw: str) -> str:
    if not raw:
        return ""
    s = raw.upper()
    s = _NAME_SUFFIX_NOISE.sub(" ", s)
    s = _PUNCT.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    return s


def is_llc(name: str) -> bool:
    if not name:
        return False
    upper = name.upper()
    return any(f" {t}" in f" {upper}" for t in LLC_TOKENS)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

@dataclass
class BuyerStats:
    name: str             # normalized
    raw_name: str         # one observed raw form (for display)
    deals: int = 0
    total_volume: int = 0
    is_llc: bool = False
    parcels: set = field(default_factory=set)


def aggregate_buyers_per_zip(
    csv_path: Path,
    *,
    today: Optional[date] = None,
    lookback_months: int = 24,
) -> tuple[dict[str, dict[str, BuyerStats]], int]:
    """Return ({zip: {normalized_name: BuyerStats}}, total_rows_used)."""
    today = today or date.today()
    cutoff = today - timedelta(days=lookback_months * 30)

    by_zip: dict[str, dict[str, BuyerStats]] = defaultdict(dict)
    rows_used = 0
    rows_skipped = 0

    if not csv_path.exists():
        raise FileNotFoundError(
            f"Sales CSV not found at {csv_path}. Download Miami-Dade Comparable "
            f"Sales from https://gis-mdc.opendata.arcgis.com (search 'Comparable "
            f"Sales' → Download → CSV) and save to {csv_path}."
        )

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols = _resolve(reader.fieldnames or [], ("buyer", "sale_date", "zip",
                                                   "sale_price", "parcel_id"))
        if "buyer" not in cols:
            raise ValueError(
                f"Sales CSV missing buyer/grantee column. Detected columns: "
                f"{reader.fieldnames}. Edit FIELD_SYNONYMS to map yours."
            )
        if "zip" not in cols:
            raise ValueError(
                f"Sales CSV missing zip column. Detected columns: "
                f"{reader.fieldnames}."
            )

        for row in reader:
            buyer_raw = (row.get(cols["buyer"]) or "").strip()
            zip_raw = (row.get(cols["zip"]) or "").strip()
            sale_date = _parse_date(row.get(cols.get("sale_date", ""), "")) if "sale_date" in cols else None
            sale_price = _parse_int(row.get(cols.get("sale_price", ""), "")) if "sale_price" in cols else None
            parcel_id = (row.get(cols.get("parcel_id", ""), "") or "").strip() if "parcel_id" in cols else ""

            if not buyer_raw or not zip_raw:
                rows_skipped += 1
                continue
            # Normalize zip to first 5 digits
            m = re.match(r"(\d{5})", zip_raw)
            if not m:
                rows_skipped += 1
                continue
            zip_code = m.group(1)
            if sale_date and sale_date < cutoff:
                rows_skipped += 1
                continue

            name_norm = normalize_name(buyer_raw)
            if not name_norm:
                rows_skipped += 1
                continue

            bucket = by_zip[zip_code]
            stats = bucket.get(name_norm)
            if stats is None:
                stats = BuyerStats(
                    name=name_norm,
                    raw_name=buyer_raw,
                    is_llc=is_llc(buyer_raw),
                )
                bucket[name_norm] = stats
            stats.deals += 1
            if sale_price:
                stats.total_volume += sale_price
            if parcel_id:
                stats.parcels.add(parcel_id)
            rows_used += 1

    print(f"  Aggregated {rows_used:,} sale rows into {sum(len(b) for b in by_zip.values()):,} "
          f"buyer-zip pairs across {len(by_zip)} zip codes  (skipped {rows_skipped:,})")
    return by_zip, rows_used


def rank_top_n(
    by_zip: dict[str, dict[str, BuyerStats]],
    top_n: int = 100,
) -> dict[str, list[BuyerStats]]:
    """Per zip, return top N buyers sorted by deal count desc, then volume desc."""
    out: dict[str, list[BuyerStats]] = {}
    for zip_code, bucket in by_zip.items():
        ranked = sorted(
            bucket.values(),
            key=lambda b: (b.deals, b.total_volume),
            reverse=True,
        )
        out[zip_code] = ranked[:top_n]
    return out


# ---------------------------------------------------------------------------
# Salesforce cross-reference
# ---------------------------------------------------------------------------

def fetch_sf_contacts(sf) -> list[dict]:
    """Pull all CHF Contacts with name + Top_Buyer_Zips__c."""
    soql = (
        "SELECT Id, FirstName, LastName, Email, Top_Buyer_Zips__c, AccountId "
        "FROM Contact WHERE LeadSource = 'CheapHomesFLA_LandingPage'"
    )
    res = sf.query_all(soql)
    out = []
    for r in res["records"]:
        r.pop("attributes", None)
        out.append(r)
    return out


def match_buyer_to_contact(buyer_norm: str, contacts_index: dict[str, dict]) -> Optional[dict]:
    """Try matching a normalized buyer name against a normalized-name → contact index."""
    if buyer_norm in contacts_index:
        return contacts_index[buyer_norm]
    # Try last-word match (LLC stripped)
    parts = buyer_norm.split()
    if len(parts) >= 2:
        # Common pattern: "JOHN SMITH LLC" → check for "JOHN SMITH"
        without_llc = " ".join(p for p in parts if p not in LLC_TOKENS)
        if without_llc and without_llc in contacts_index:
            return contacts_index[without_llc]
    return None


def update_contact_top_zips(sf, contact_id: str, zips: set[str]) -> tuple[bool, str]:
    """Set Top_Buyer_Zips__c on a Contact."""
    zip_str = ", ".join(sorted(zips))
    try:
        sf.Contact.update(contact_id, {"Top_Buyer_Zips__c": zip_str})
        return (True, zip_str)
    except Exception as e:
        return (False, str(e))


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_top_buyers_json(top_per_zip: dict[str, list[BuyerStats]], path: Path) -> None:
    out = {}
    for zip_code, lst in top_per_zip.items():
        out[zip_code] = [
            {
                "rank": i + 1,
                "name": b.raw_name,
                "name_normalized": b.name,
                "deals": b.deals,
                "total_volume": b.total_volume,
                "is_llc": b.is_llc,
                "unique_parcels": len(b.parcels),
            }
            for i, b in enumerate(lst)
        ]
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, indent=2))


def write_outreach_csv(unmatched_buyers: list[tuple[str, BuyerStats, set[str]]], path: Path) -> None:
    """unmatched_buyers: list of (raw_name, BuyerStats, zips_where_topN)."""
    path.parent.mkdir(exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["raw_name", "normalized_name", "is_llc",
                    "total_deals_across_top_zips", "total_volume",
                    "zips_in_top_100"])
        for raw, stats, zips in sorted(unmatched_buyers,
                                        key=lambda x: x[1].deals, reverse=True):
            w.writerow([
                raw, stats.name, stats.is_llc,
                stats.deals, stats.total_volume,
                ";".join(sorted(zips)),
            ])


def write_audit(top_per_zip: dict[str, list[BuyerStats]],
                matched_count: int, unmatched_count: int,
                path: Path) -> None:
    lines = [
        f"Top Buyers per Zip — {datetime.now().isoformat(timespec='seconds')}",
        "=" * 76,
        f"Zips analyzed:               {len(top_per_zip):,}",
        f"Total buyer-zip rankings:    {sum(len(b) for b in top_per_zip.values()):,}",
        f"Matched to SF Contact:       {matched_count:,}",
        f"Unmatched (outreach target): {unmatched_count:,}",
        "",
        "Per-zip breakdown:",
    ]
    for zip_code in sorted(top_per_zip.keys()):
        buyers = top_per_zip[zip_code]
        if not buyers:
            continue
        lines.append(f"\n{zip_code}: {len(buyers)} top buyers")
        for i, b in enumerate(buyers[:5], 1):
            mark = "🏢" if b.is_llc else "👤"
            vol = f"${b.total_volume:,}" if b.total_volume else "?"
            lines.append(f"  {i}. {mark} {b.raw_name[:60]:<60}  "
                         f"{b.deals} deals, {vol}")
        if len(buyers) > 5:
            lines.append(f"     ... ({len(buyers) - 5} more)")
    path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--csv",     type=Path, default=DEFAULT_SALES_CSV)
    p.add_argument("--top-n",   type=int,  default=100)
    p.add_argument("--lookback-months", type=int, default=24)
    p.add_argument("--no-sf-update", action="store_true",
                   help="Skip Salesforce writes — useful for first dry run")
    args = p.parse_args()

    print(f"Loading sales from {args.csv} ...")
    by_zip, rows_used = aggregate_buyers_per_zip(
        args.csv, lookback_months=args.lookback_months,
    )
    if rows_used == 0:
        print("No usable rows. Exiting.")
        sys.exit(2)

    print(f"\nRanking top {args.top_n} buyers per zip ...")
    top_per_zip = rank_top_n(by_zip, args.top_n)

    write_top_buyers_json(top_per_zip, TOP_BUYERS_JSON)
    print(f"  → {TOP_BUYERS_JSON}")

    # Cross-reference to Salesforce
    matched_count = 0
    unmatched_buyers: list[tuple[str, BuyerStats, set[str]]] = []
    contact_to_zips: dict[str, set[str]] = defaultdict(set)
    buyer_to_zips: dict[str, set[str]] = defaultdict(set)
    buyer_to_stats: dict[str, BuyerStats] = {}

    if not args.no_sf_update:
        try:
            from simple_salesforce import Salesforce
        except ImportError:
            print("WARNING: simple_salesforce not installed; skipping SF cross-reference.")
            print("  pip3 install --break-system-packages simple-salesforce")
            args.no_sf_update = True

    if args.no_sf_update:
        # Still produce the outreach csv based on un-Salesforce-matched names
        for zip_code, ranked in top_per_zip.items():
            for b in ranked:
                buyer_to_zips[b.name].add(zip_code)
                buyer_to_stats[b.name] = b
        for name_norm, zips in buyer_to_zips.items():
            unmatched_buyers.append((buyer_to_stats[name_norm].raw_name,
                                     buyer_to_stats[name_norm], zips))
        write_outreach_csv(unmatched_buyers, OUTREACH_CSV)
        write_audit(top_per_zip, 0, len(unmatched_buyers), AUDIT_TXT)
        print(f"  → {OUTREACH_CSV}")
        print(f"  → {AUDIT_TXT}")
        return

    print("\nConnecting to Salesforce for cross-reference + Top_Buyer_Zips__c update ...")
    sf = Salesforce(
        username=os.environ["SF_USERNAME"],
        password=os.environ["SF_PASSWORD"],
        security_token=os.environ["SF_SECURITY_TOKEN"],
    )
    contacts = fetch_sf_contacts(sf)
    print(f"  Loaded {len(contacts)} CHF Contacts")

    # Build name → contact index
    name_to_contact: dict[str, dict] = {}
    for c in contacts:
        full = f"{c.get('FirstName') or ''} {c.get('LastName') or ''}".strip()
        if full:
            name_to_contact[normalize_name(full)] = c
        # If you also stamp organization in Account.Name, you can add another index.

    # Walk top-buyer rankings
    for zip_code, ranked in top_per_zip.items():
        for b in ranked:
            buyer_to_zips[b.name].add(zip_code)
            buyer_to_stats[b.name] = b
            contact = match_buyer_to_contact(b.name, name_to_contact)
            if contact:
                contact_to_zips[contact["Id"]].add(zip_code)

    # Update SF Contacts
    for contact_id, zips in contact_to_zips.items():
        ok, msg = update_contact_top_zips(sf, contact_id, zips)
        if ok:
            matched_count += 1
            print(f"  ✓ {contact_id}: Top_Buyer_Zips__c = {msg}")
        else:
            print(f"  ✗ {contact_id}: {msg}")

    # Write outreach list (top buyers NOT in SF)
    matched_norm_names = {normalize_name(
        f"{c.get('FirstName') or ''} {c.get('LastName') or ''}".strip()
    ) for c in contacts}
    for name_norm, zips in buyer_to_zips.items():
        if name_norm in matched_norm_names:
            continue
        if not zips:
            continue
        unmatched_buyers.append((buyer_to_stats[name_norm].raw_name,
                                 buyer_to_stats[name_norm], zips))

    write_outreach_csv(unmatched_buyers, OUTREACH_CSV)
    write_audit(top_per_zip, matched_count, len(unmatched_buyers), AUDIT_TXT)
    print(f"\n  → {OUTREACH_CSV}  ({len(unmatched_buyers):,} outreach candidates)")
    print(f"  → {AUDIT_TXT}")
    print(f"\nMatched + updated {matched_count} SF Contacts with Top_Buyer_Zips__c.")


if __name__ == "__main__":
    main()
