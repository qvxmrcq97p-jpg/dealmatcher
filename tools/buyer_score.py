#!/usr/bin/env python3
"""
buyer_score.py — score every CheapHomesFLA buyer Contact in Salesforce.

Per sprint Day 5 spec, Buyer_Score__c is a weighted composite of:

    Close history       40%   — CHF deals actually closed by this buyer
    Email engagement    30%   — opt-in status, opens, clicks
    Capital deployed    20%   — stated Buyer_Max_Budget__c picklist
    Decision velocity   10%   — days from match → response on past deals

A buyer's tier:
    Hot   ≥ 70
    Warm  50 - 69
    Cold  < 50

The score lands on Buyer_Score__c so the deal matcher and per-buyer
drop email can use it for personalization (Hot Buyers get a phone-call
ping note; Cold Buyers get the standard email).

The system isn't fully producing close-history or engagement data yet
(parser only just got fixed, no campaigns have run end-to-end), so
every buyer will land in Cold/Warm range initially and the relative
ordering will be driven by stated budget + recency. That's expected;
scores refine as the pipeline accumulates real activity.

Run:
    cd ~/dealmatcher
    python3 tools/buyer_score.py             # compute + write to SF
    python3 tools/buyer_score.py --dry-run   # preview, no SF writes
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
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

try:
    from simple_salesforce import Salesforce
except ImportError:
    print("ERROR: simple_salesforce not installed.")
    print("  pip3 install --break-system-packages simple-salesforce")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Component scoring (each returns 0-100)
# ---------------------------------------------------------------------------

def score_close_history(close_count: int) -> int:
    """0 closes → 0 ; 1 close → 50 ; 2+ closes → 100. Plateau at 2 because
    a buyer who closes twice has already proven they execute — adding more
    dilutes the signal vs other dimensions."""
    if close_count <= 0:
        return 0
    if close_count == 1:
        return 50
    return 100


def score_email_engagement(
    has_email: bool,
    opted_out: bool,
    days_since_signup: Optional[int],
    sends_count: int = 0,
    opens_count: int = 0,
    clicks_count: int = 0,
) -> int:
    """Email engagement, blended.

    Until we have real SendGrid event-tracking events, the signals
    available are:
      - has email + not opted-out             → baseline 50
      - recent signup (< 30 days)             → +20
      - any opens recorded                    → +20
      - any clicks recorded                   → +30 (replaces opens bonus)

    Once SendGrid event hooks land, we can swap to true open rate.
    """
    if not has_email or opted_out:
        return 0
    score = 50
    if days_since_signup is not None and days_since_signup <= 30:
        score += 20
    if clicks_count > 0:
        score = min(100, score + 30)
    elif opens_count > 0:
        score = min(100, score + 20)
    if sends_count == 0:
        # Brand-new buyer — keep them at the recency-bonus level
        return min(score, 70)
    return min(score, 100)


# Map the Buyer_Max_Budget__c picklist to a 0-100 capital score.
# Higher budget tier = more capital deployed = higher score.
BUDGET_SCORE_MAP = {
    "Under $50k":       10,
    "$50k - $100k":     20,
    "$100k - $150k":    30,
    "$100k - $200k":    35,
    "$150k - $250k":    40,
    "$200k - $300k":    50,
    "$250k - $500k":    60,
    "$300k - $500k":    65,
    "$500k - $750k":    75,
    "$500k - $1M":      85,
    "$750k - $1M":      85,
    "$1M+":             100,
    "Over $1M":         100,
    "No limit":         100,
}


def score_capital_deployed(budget_picklist: Optional[str]) -> int:
    if not budget_picklist:
        return 0
    return BUDGET_SCORE_MAP.get(budget_picklist.strip(), 0)


def score_decision_velocity(avg_response_days: Optional[float]) -> int:
    """≤ 1 day → 100 ; ≤ 3 days → 75 ; ≤ 7 days → 50 ; ≤ 14 days → 25 ; else 0.

    None = no data yet → default to 50 (neutral) so brand-new buyers
    aren't penalized purely for lack of history.
    """
    if avg_response_days is None:
        return 50
    if avg_response_days <= 1:
        return 100
    if avg_response_days <= 3:
        return 75
    if avg_response_days <= 7:
        return 50
    if avg_response_days <= 14:
        return 25
    return 0


WEIGHT_CLOSE      = 0.40
WEIGHT_ENGAGEMENT = 0.30
WEIGHT_CAPITAL    = 0.20
WEIGHT_VELOCITY   = 0.10


def composite_score(
    close_count: int,
    has_email: bool,
    opted_out: bool,
    days_since_signup: Optional[int],
    sends_count: int,
    opens_count: int,
    clicks_count: int,
    budget: Optional[str],
    avg_response_days: Optional[float],
) -> tuple[int, dict[str, int]]:
    components = {
        "close":      score_close_history(close_count),
        "engagement": score_email_engagement(has_email, opted_out, days_since_signup,
                                             sends_count, opens_count, clicks_count),
        "capital":    score_capital_deployed(budget),
        "velocity":   score_decision_velocity(avg_response_days),
    }
    total = round(
        components["close"]      * WEIGHT_CLOSE
      + components["engagement"] * WEIGHT_ENGAGEMENT
      + components["capital"]    * WEIGHT_CAPITAL
      + components["velocity"]   * WEIGHT_VELOCITY
    )
    return total, components


def tier(score: int) -> str:
    if score >= 70:
        return "Hot"
    if score >= 50:
        return "Warm"
    return "Cold"


# ---------------------------------------------------------------------------
# Salesforce I/O
# ---------------------------------------------------------------------------

def fetch_buyers(sf) -> list[dict]:
    fields = [
        "Id", "FirstName", "LastName", "Email", "Phone", "MobilePhone",
        "HasOptedOutOfEmail", "DoNotCall",
        "CreatedDate",
        "Buyer_Max_Budget__c",
        "Buyer_Primary_Strategy__c",
        "Buyer_Counties_of_Interest__c",
        "Buyer_Target_Zips__c",
    ]
    desc = sf.Contact.describe()
    existing = {f["name"] for f in desc["fields"]}
    fields = [f for f in fields if f in existing]
    soql = (
        f"SELECT {','.join(fields)} FROM Contact "
        f"WHERE LeadSource = 'CheapHomesFLA_LandingPage'"
    )
    res = sf.query_all(soql)
    out = []
    for r in res["records"]:
        r.pop("attributes", None)
        out.append(r)
    return out


def fetch_close_count(sf, buyer_id: str) -> int:
    """Closes = CH-DEAL Tasks where the buyer's Lead/Opportunity reached
    a closed-won state. Until Opportunity tracking is wired, count
    CH-DEAL Tasks with Status='Completed' as a proxy."""
    safe = buyer_id.replace("'", "\\'")
    try:
        res = sf.query(
            f"SELECT COUNT(Id) c FROM Task "
            f"WHERE WhoId='{safe}' AND Subject LIKE 'CH-DEAL-%' "
            f"AND Status='Completed'"
        )
        return int(res["records"][0].get("c", 0)) if res["records"] else 0
    except Exception:  # noqa: BLE001
        return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute and print scores without writing to Salesforce")
    args = parser.parse_args()

    print(f"Connecting to Salesforce as {os.environ.get('SF_USERNAME')}...")
    sf = Salesforce(
        username=os.environ["SF_USERNAME"],
        password=os.environ["SF_PASSWORD"],
        security_token=os.environ["SF_SECURITY_TOKEN"],
    )
    print("Connected.\n")

    buyers = fetch_buyers(sf)
    print(f"Loaded {len(buyers)} CHF buyers.\n")

    desc = sf.Contact.describe()
    has_score_field = any(f["name"] == "Buyer_Score__c" for f in desc["fields"])
    if not has_score_field and not args.dry_run:
        print("WARNING: Buyer_Score__c custom field does not exist on Contact.")
        print("  Create it in Salesforce Setup → Contact → Fields → New (Number, length 3, decimals 0).")
        print("  Until then, run with --dry-run to compute scores in memory only.")
        print()

    today = datetime.now(timezone.utc)
    rows = []
    for b in buyers:
        close_count = fetch_close_count(sf, b["Id"])
        created = b.get("CreatedDate")
        days_since_signup = None
        if created:
            try:
                cd = datetime.fromisoformat(created.replace("Z", "+00:00"))
                days_since_signup = (today - cd).days
            except ValueError:
                pass
        score, components = composite_score(
            close_count=close_count,
            has_email=bool(b.get("Email")),
            opted_out=bool(b.get("HasOptedOutOfEmail")),
            days_since_signup=days_since_signup,
            sends_count=0,    # TODO: wire SendGrid event tracking
            opens_count=0,
            clicks_count=0,
            budget=b.get("Buyer_Max_Budget__c"),
            avg_response_days=None,    # TODO: wire from Task response history
        )
        rows.append({
            "buyer_id": b["Id"],
            "name": f"{b.get('FirstName') or ''} {b.get('LastName') or ''}".strip() or "(no name)",
            "email": b.get("Email") or "—",
            "budget": b.get("Buyer_Max_Budget__c") or "—",
            "close_count": close_count,
            "components": components,
            "score": score,
            "tier": tier(score),
        })

    rows.sort(key=lambda r: r["score"], reverse=True)

    print(f"{'Tier':<6}{'Score':>6}  {'Name':<24}  {'Budget':<14}  {'Closes':>6}  Components")
    print("-" * 110)
    for r in rows:
        c = r["components"]
        print(f"{r['tier']:<6}{r['score']:>6}  {r['name']:<24}  "
              f"{r['budget']:<14}  {r['close_count']:>6}  "
              f"close={c['close']:<3} eng={c['engagement']:<3} "
              f"cap={c['capital']:<3} vel={c['velocity']}")

    if args.dry_run or not has_score_field:
        print(f"\n{'--dry-run' if args.dry_run else 'No Buyer_Score__c field'}: "
              "no Salesforce updates applied.")
        return

    print()
    confirm = input(f"Apply Buyer_Score__c to {len(rows)} Contacts? [y/N] ")
    if confirm.strip().lower() != "y":
        print("Aborted.")
        return

    success = 0
    for r in rows:
        try:
            sf.Contact.update(r["buyer_id"], {"Buyer_Score__c": r["score"]})
            success += 1
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL {r['buyer_id']}: {e}")
    print(f"\nUpdated {success}/{len(rows)} Contacts.")


if __name__ == "__main__":
    main()
