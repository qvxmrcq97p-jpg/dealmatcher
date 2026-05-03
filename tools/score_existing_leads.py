#!/usr/bin/env python3
"""
score_existing_leads.py — score every existing Salesforce Lead's
Seller_Score__c using fields already populated on the Lead.

Fast path that doesn't require the MD parcels CSV download. Uses the
PPL-imported metadata that's already on every Lead (auction date,
final judgment, probate, reason to sell, equity, timeline, etc.) to
compute a 0-100 Seller Score.

Scoring rubric (tuned to fields actually present in the johnsonshomes2
org per list_sf_custom_fields.py inspection):

    Auction_Date__c set + future or recent past   30 pts
    Final_Judgment__c > 0                         25 pts
    Reason_to_sell__c contains foreclosure/tax/   20 pts
        divorce/inherited/behind/distress
    Timeline_to_sell__c = ASAP / 30 days          15 pts
    Probate_Date__c set                           15 pts
    Date_of_Death__c set (heir scenario)          10 pts
    Years_In_Home__c >= 10                        10 pts
    Home equity ratio >= 0.5 (estimated)          15 pts
    Property_Condition__c contains distressed     10 pts

Maximum total ~150 (can exceed 100 — clamped).

Run:
    cd ~/dealmatcher
    python3 tools/score_existing_leads.py --dry-run    # preview
    python3 tools/score_existing_leads.py              # apply

Idempotent: re-running just refreshes scores.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
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

from simple_salesforce import Salesforce


# ---------------------------------------------------------------------------
# Score weights
# ---------------------------------------------------------------------------

W_AUCTION         = 30
W_FINAL_JUDGMENT  = 25
W_DISTRESS_REASON = 20
W_TIMELINE_FAST   = 15
W_PROBATE         = 15
W_DEATH           = 10
W_LONG_HOLD       = 10
W_HIGH_EQUITY     = 15
W_BAD_CONDITION   = 10

DISTRESS_KEYWORDS = (
    "foreclosure", "tax", "behind", "delinquent", "divorce",
    "inherited", "probate", "death", "estate", "default", "lien",
    "bankruptcy", "auction", "short sale",
)

CONDITION_DISTRESS_KEYWORDS = (
    "distressed", "needs repair", "needs work", "damage", "fire",
    "vacant", "abandoned", "tear down", "uninhabitable",
)

FAST_TIMELINES = ("ASAP", "30 days", "Immediately", "1 month")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_date(s) -> Optional[date]:
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s.split("T")[0], fmt).date()
        except ValueError:
            continue
    return None


_NUMERIC = re.compile(r"-?\d[\d,]*\.?\d*")


def parse_money(s) -> Optional[float]:
    """Pull a number out of strings like '$120,000' or '120000.50'."""
    if s is None or s == "":
        return None
    if isinstance(s, (int, float)):
        return float(s)
    m = _NUMERIC.search(str(s).replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_lead(lead: dict, today: Optional[date] = None) -> tuple[int, list[str]]:
    today = today or date.today()
    score = 0
    explain: list[str] = []

    # 1. Auction date — active or recent foreclosure
    auction_d = parse_date(lead.get("Auction_Date__c"))
    if auction_d:
        # Score if auction is in the future or within last 90 days
        delta_days = (auction_d - today).days
        if delta_days >= -90:
            score += W_AUCTION
            explain.append(f"Auction date {auction_d} (+{W_AUCTION})")

    # 2. Final judgment > 0 (foreclosure judgment)
    fj = parse_money(lead.get("Final_Judgment__c"))
    if fj and fj > 0:
        score += W_FINAL_JUDGMENT
        explain.append(f"Final judgment ${fj:,.0f} (+{W_FINAL_JUDGMENT})")

    # 3. Reason to sell — distress keywords
    reason = (lead.get("Reason_to_sell__c") or "").lower()
    if any(k in reason for k in DISTRESS_KEYWORDS):
        matched = next((k for k in DISTRESS_KEYWORDS if k in reason), "")
        score += W_DISTRESS_REASON
        explain.append(f"Distress reason: '{matched}' (+{W_DISTRESS_REASON})")

    # 4. Timeline to sell — fast
    timeline = (lead.get("Timeline_to_sell__c") or "")
    if any(t.lower() in timeline.lower() for t in FAST_TIMELINES):
        score += W_TIMELINE_FAST
        explain.append(f"Fast timeline: '{timeline}' (+{W_TIMELINE_FAST})")

    # 5. Probate date set
    if parse_date(lead.get("Probate_Date__c")):
        score += W_PROBATE
        explain.append(f"Probate filing (+{W_PROBATE})")

    # 6. Date of death — heir scenario
    if parse_date(lead.get("Date_of_Death__c")):
        score += W_DEATH
        explain.append(f"Owner death recorded (+{W_DEATH})")

    # 7. Long hold time
    yrs = lead.get("Years_In_Home__c")
    if yrs is not None and yrs >= 10:
        score += W_LONG_HOLD
        explain.append(f"Held {yrs:.0f}y (+{W_LONG_HOLD})")

    # 8. High equity
    equity = parse_money(lead.get("Home_Equity_Estimate__c"))
    home_value = parse_money(lead.get("Estimated_Home_Value__c"))
    if equity and home_value and home_value > 0:
        ratio = equity / home_value
        if ratio >= 0.5:
            score += W_HIGH_EQUITY
            explain.append(f"High equity (ratio {ratio:.0%}) (+{W_HIGH_EQUITY})")

    # 9. Bad property condition
    condition = (lead.get("Property_Condition__c") or "").lower()
    if any(k in condition for k in CONDITION_DISTRESS_KEYWORDS):
        score += W_BAD_CONDITION
        explain.append(f"Distressed condition (+{W_BAD_CONDITION})")

    # Clamp to 0-100 (rubric can exceed 100)
    score = min(score, 100)
    return score, explain


# ---------------------------------------------------------------------------
# SF I/O
# ---------------------------------------------------------------------------

LEAD_FIELDS = [
    "Id", "FirstName", "LastName", "Status",
    "Property_Address__c", "Property_City__c", "Property_Zip__c",
    "Auction_Date__c",
    "Final_Judgment__c",
    "Reason_to_sell__c",
    "Timeline_to_sell__c",
    "Probate_Date__c",
    "Date_of_Death__c",
    "Years_In_Home__c",
    "Home_Equity_Estimate__c",
    "Estimated_Home_Value__c",
    "Property_Condition__c",
    "Seller_Score__c",
]


def fetch_leads(sf, limit: int = 0) -> list[dict]:
    """Pull leads from Salesforce, newest-first. limit=0 means all leads.

    Uses ORDER BY CreatedDate DESC so the most recently imported leads
    score first — these have the freshest foreclosure / auction / probate
    metadata and are worth focusing on. Older leads from years past often
    have stale distress signals that no longer reflect reality.
    """
    desc = sf.Lead.describe()
    existing = {f["name"] for f in desc["fields"]}
    fields = [f for f in LEAD_FIELDS if f in existing]
    if "CreatedDate" not in fields:
        fields.append("CreatedDate")
    missing = [f for f in LEAD_FIELDS if f not in existing]
    if missing:
        print(f"  (skipping fields not in this org: {missing})")

    soql = (
        f"SELECT {','.join(fields)} FROM Lead "
        f"WHERE Property_Address__c != null "
        f"ORDER BY CreatedDate DESC"
    )
    if limit > 0:
        soql += f" LIMIT {limit}"
    print(f"Querying: {soql}")
    # Use query (not query_all) when LIMIT is present — query_all paginates
    # past the LIMIT in some simple_salesforce versions. With LIMIT it's
    # always a single page anyway.
    if limit > 0 and limit <= 2000:
        res = sf.query(soql)
    else:
        res = sf.query_all(soql)
    leads = []
    for r in res["records"]:
        r.pop("attributes", None)
        leads.append(r)
    return leads


def update_lead_score(sf, lead_id: str, score: int) -> tuple[bool, str]:
    try:
        sf.Lead.update(lead_id, {"Seller_Score__c": score})
        return (True, "")
    except Exception as e:
        return (False, str(e))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="Compute scores and print summary, but DO NOT write to SF")
    p.add_argument("--top", type=int, default=20,
                   help="Print top N highest-scored leads in summary")
    p.add_argument("--limit", type=int, default=2000,
                   help="Score only the most recent N leads, ordered by "
                        "CreatedDate desc. Default 2000 (focus on fresh "
                        "metadata). Pass 0 to score ALL leads.")
    args = p.parse_args()

    print(f"Connecting as {os.environ.get('SF_USERNAME')}...")
    sf = Salesforce(
        username=os.environ["SF_USERNAME"],
        password=os.environ["SF_PASSWORD"],
        security_token=os.environ["SF_SECURITY_TOKEN"],
    )
    print(f"Connected: {sf.sf_instance}\n")

    leads = fetch_leads(sf, limit=args.limit)
    print(f"Loaded {len(leads):,} leads with property addresses "
          f"(newest first)\n")

    scored = []
    for lead in leads:
        score, explain = score_lead(lead)
        scored.append({"lead": lead, "score": score, "explain": explain})

    # Distribution
    bins = {"Hot (70+)": 0, "Warm (50-69)": 0, "Cold (1-49)": 0, "Zero": 0}
    for s in scored:
        if s["score"] == 0:
            bins["Zero"] += 1
        elif s["score"] >= 70:
            bins["Hot (70+)"] += 1
        elif s["score"] >= 50:
            bins["Warm (50-69)"] += 1
        else:
            bins["Cold (1-49)"] += 1
    print("Score distribution:")
    for label, n in bins.items():
        pct = 100 * n / max(len(scored), 1)
        print(f"  {label:<14}  {n:>5,}  ({pct:.0f}%)")
    print()

    # Top N
    scored.sort(key=lambda x: x["score"], reverse=True)
    print(f"Top {args.top} highest-scored leads:")
    for s in scored[: args.top]:
        l = s["lead"]
        name = f"{l.get('FirstName') or ''} {l.get('LastName') or ''}".strip() or "(no name)"
        addr = l.get("Property_Address__c") or "?"
        print(f"  {s['score']:>3}  {name[:30]:<30}  {addr[:50]:<50}")
        for e in s["explain"][:3]:
            print(f"        • {e}")
    print()

    if args.dry_run:
        print("--dry-run: no Salesforce updates applied.")
        return

    # Bulk API path — for big lead pipelines (44k+), this is the only sane way.
    # simple_salesforce.bulk2 wraps the Bulk API v2: 1 ingest job per call,
    # up to 10k records per CSV batch, finishes in seconds.
    print(f"Updating Seller_Score__c on {len(scored):,} Leads via Bulk API v2...")
    records = [
        {"Id": s["lead"]["Id"], "Seller_Score__c": s["score"]}
        for s in scored
    ]
    try:
        # bulk2 ingest signature: data=list_of_dicts, with method='update' for upsert-by-Id
        results = sf.bulk2.Lead.update(records, batch_size=10000)
        # bulk2 returns a list of dicts: [{'numberRecordsProcessed': N, 'numberRecordsFailed': N, ...}]
        total_processed = sum(r.get("numberRecordsProcessed", 0) for r in results)
        total_failed = sum(r.get("numberRecordsFailed", 0) for r in results)
        print(f"\nBulk update complete:")
        print(f"  Processed: {total_processed:,}")
        print(f"  Failed:    {total_failed:,}")
        if total_failed:
            print(f"  See SF Setup → Bulk Data Load Jobs for failure details.")
    except AttributeError:
        # simple_salesforce < 1.12 doesn't have bulk2. Fall back to bulk (v1).
        print("  (simple_salesforce.bulk2 not available — falling back to bulk v1)")
        results = sf.bulk.Lead.update(records, batch_size=10000)
        success = sum(1 for r in results if r.get("success"))
        failed = len(results) - success
        print(f"\nBulk v1 update complete:")
        print(f"  Success: {success:,}")
        print(f"  Failed:  {failed:,}")
    except Exception as e:
        print(f"\nBulk update FAILED: {type(e).__name__}: {e}")
        print("\nFalling back to one-at-a-time (slow). Cancel with Ctrl+C if you want.")
        success = 0
        failures: list[tuple[str, str]] = []
        for i, s in enumerate(scored):
            if i and i % 100 == 0:
                print(f"  ... {i:,}/{len(scored):,} ({success} OK, {len(failures)} failed)")
            ok, msg = update_lead_score(sf, s["lead"]["Id"], s["score"])
            if ok:
                success += 1
            else:
                failures.append((s["lead"]["Id"], msg))
        print(f"\nUpdated {success:,}/{len(scored):,} leads.")


if __name__ == "__main__":
    main()
