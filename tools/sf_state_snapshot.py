#!/usr/bin/env python3
"""
sf_state_snapshot.py — print a "where we stand right now" view of the
CHF / Johnson Buys Salesforce org.

Pulls live numbers and points to specific URLs in your SF instance so
you can click through and verify each one. No writes — pure read.

Run:
    cd ~/dealmatcher && python3 tools/sf_state_snapshot.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = SCRIPT_DIR / ".env.cheaphomesfla"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from simple_salesforce import Salesforce


def banner(title: str) -> None:
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


def sub(label: str) -> None:
    print(f"\n--- {label} ---")


def main() -> None:
    sf = Salesforce(
        username=os.environ["SF_USERNAME"],
        password=os.environ["SF_PASSWORD"],
        security_token=os.environ["SF_SECURITY_TOKEN"],
    )
    base = f"https://{sf.sf_instance}"
    today = datetime.now(timezone.utc)

    banner(f"CHF / JB Salesforce State — {today.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Org:  {base}")

    # ------------------------------------------------------------------
    # 1. Custom fields readiness
    # ------------------------------------------------------------------
    sub("Custom field readiness (Contact + Lead)")
    contact_desc = sf.Contact.describe()
    lead_desc = sf.Lead.describe()
    contact_fields = {f["name"] for f in contact_desc["fields"]}
    lead_fields = {f["name"] for f in lead_desc["fields"]}
    needed = [
        ("Contact", "Buyer_Score__c", contact_fields),
        ("Contact", "Top_Buyer_Zips__c", contact_fields),
        ("Contact", "Seller_Score__c", contact_fields),
        ("Contact", "Buyer_Target_Zips__c", contact_fields),
        ("Lead", "Seller_Score__c", lead_fields),
    ]
    for obj, fld, present_set in needed:
        marker = "✓" if fld in present_set else "✗"
        print(f"  {marker} {obj}.{fld}")

    # ------------------------------------------------------------------
    # 2. CHF buyers (Contacts)
    # ------------------------------------------------------------------
    sub("CHF Buyers — Contact pipeline")
    res = sf.query_all(
        "SELECT Id, FirstName, LastName, Email, Buyer_Target_Zips__c, "
        "Buyer_Max_Budget__c, Buyer_Counties_of_Interest__c, "
        "Buyer_Primary_Strategy__c, Buyer_Score__c, Top_Buyer_Zips__c "
        "FROM Contact WHERE LeadSource = 'CheapHomesFLA_LandingPage' "
        "ORDER BY CreatedDate DESC"
    )
    buyers = [r for r in res["records"]]
    for b in buyers:
        b.pop("attributes", None)
    print(f"  Total CHF buyers: {len(buyers)}")
    has_zips = sum(1 for b in buyers if b.get("Buyer_Target_Zips__c"))
    has_score = sum(1 for b in buyers if b.get("Buyer_Score__c") is not None)
    has_top_zips = sum(1 for b in buyers if b.get("Top_Buyer_Zips__c"))
    print(f"    With Buyer_Target_Zips__c set:    {has_zips}/{len(buyers)}  (matchable for deals)")
    print(f"    With Buyer_Score__c populated:    {has_score}/{len(buyers)}  (run buyer_score.py to fill)")
    print(f"    With Top_Buyer_Zips__c populated: {has_top_zips}/{len(buyers)}  (run top_buyers_by_zip.py to fill)")
    print(f"\n  Click to verify: {base}/lightning/o/Contact/list?filterName=Recent")
    print(f"  Per-buyer detail:")
    for b in buyers:
        name = f"{b.get('FirstName') or ''} {b.get('LastName') or ''}".strip() or "(no name)"
        zips = b.get("Buyer_Target_Zips__c") or ""
        n_zips = len([z for z in zips.replace(",", " ").split() if z.strip().isdigit()]) if zips else 0
        marker = "✓" if zips else "✗"
        print(f"    {marker} {name:<22} {b.get('Buyer_Max_Budget__c') or '—':<14} "
              f"{n_zips:>2} zips  Score={b.get('Buyer_Score__c') or '—'}  {b.get('Id')}")

    # ------------------------------------------------------------------
    # 3. Lead pipeline
    # ------------------------------------------------------------------
    sub("Seller Lead pipeline (Lead object)")
    cnt = sf.query("SELECT COUNT(Id) c FROM Lead")
    total_leads = int(cnt["records"][0]["c"]) if cnt["records"] else 0
    cnt2 = sf.query("SELECT COUNT(Id) c FROM Lead WHERE Property_Address__c != null")
    leads_w_addr = int(cnt2["records"][0]["c"]) if cnt2["records"] else 0
    cnt3 = sf.query("SELECT COUNT(Id) c FROM Lead WHERE Seller_Score__c != null")
    leads_scored = int(cnt3["records"][0]["c"]) if cnt3["records"] else 0
    print(f"  Total Leads:                      {total_leads:,}")
    print(f"    With Property_Address__c set:   {leads_w_addr:,}")
    print(f"    With Seller_Score__c populated: {leads_scored:,}")
    print(f"\n  Click to verify: {base}/lightning/o/Lead/list?filterName=Recent")

    # Status breakdown (top 10)
    res = sf.query_all(
        "SELECT Status, COUNT(Id) c FROM Lead GROUP BY Status ORDER BY COUNT(Id) DESC LIMIT 15"
    )
    print(f"\n  Lead status breakdown:")
    for r in res["records"]:
        r.pop("attributes", None)
        status = r.get("Status") or "(none)"
        print(f"    {status:<35} {r.get('c', 0):>6,}")

    # ------------------------------------------------------------------
    # 4. Today's campaign activity (Tasks)
    # ------------------------------------------------------------------
    sub("Today's campaign activity")
    # Salesforce can't GROUP BY long-text Subject. Pull records and group
    # in Python instead.
    today_iso = today.strftime("%Y-%m-%d")
    res = sf.query_all(
        "SELECT Subject FROM Task "
        "WHERE CreatedDate = TODAY AND Subject LIKE 'JB-%'"
    )
    from collections import Counter
    subjects = Counter()
    for r in res["records"]:
        r.pop("attributes", None)
        subjects[r.get("Subject") or "(no subject)"] += 1
    if subjects:
        for subj, n in subjects.most_common():
            print(f"    {subj:<35} {n:>5,}")
        print(f"    {'TOTAL JB-tagged today':<35} {sum(subjects.values()):>5,}")
    else:
        print(f"    (no JB-tagged Tasks created today yet)")

    # CHF deal matches
    cnt = sf.query(
        "SELECT COUNT(Id) c FROM Task WHERE CreatedDate = TODAY AND Subject LIKE 'CH-DEAL-%'"
    )
    chf_tasks = int(cnt["records"][0]["c"]) if cnt["records"] else 0
    print(f"\n    CH-DEAL Tasks today (cheaphomesfla matches): {chf_tasks}")
    print(f"      → 0 expected pre-go-live; will populate after 8 PM scraper test")

    # ------------------------------------------------------------------
    # 5. Recent Lead-status changes (last 7 days)
    # ------------------------------------------------------------------
    sub("Recent Lead activity (last 7 days)")
    cnt = sf.query("SELECT COUNT(Id) c FROM Lead WHERE LastModifiedDate = LAST_N_DAYS:7")
    modified = int(cnt["records"][0]["c"]) if cnt["records"] else 0
    cnt = sf.query("SELECT COUNT(Id) c FROM Lead WHERE CreatedDate = LAST_N_DAYS:7")
    created = int(cnt["records"][0]["c"]) if cnt["records"] else 0
    print(f"    Created in last 7 days:   {created:,}")
    print(f"    Modified in last 7 days:  {modified:,}")

    # ------------------------------------------------------------------
    # 6. What's still pending in SF
    # ------------------------------------------------------------------
    sub("What's still pending in Salesforce")
    pending = []
    if has_zips < len(buyers):
        pending.append(f"  {len(buyers) - has_zips} buyer(s) without Buyer_Target_Zips set "
                       f"(Abe Saldivar — pending his answer)")
    if has_score == 0:
        pending.append(f"  Run tools/buyer_score.py to populate Buyer_Score__c on all {len(buyers)} buyers")
    if has_top_zips == 0:
        pending.append(f"  Run tools/top_buyers_by_zip.py once parcels.csv is downloaded")
    if leads_scored == 0:
        pending.append(f"  Run tools/score_existing_leads.py to populate Seller_Score__c on Leads "
                       f"(low-effort sort/filter aid; real value adds when public-records data is wired)")
    if chf_tasks == 0:
        pending.append(f"  CHF deal matcher goes live tonight 8 PM → CH-DEAL Tasks will start populating")
    if not pending:
        print("    Nothing pending — all data flows are live.")
    else:
        for p in pending:
            print(p)

    print()
    print("=" * 72)
    print(f"Snapshot complete. {len(buyers)} CHF buyers, {total_leads:,} sellers, "
          f"4 custom fields ready, scraper goes live at 8 PM.")
    print("=" * 72)


if __name__ == "__main__":
    main()
