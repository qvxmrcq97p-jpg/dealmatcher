#!/usr/bin/env python3
"""
sf_setup_helper.py — creates the most useful Salesforce List Views via API,
and prints exact UI-click instructions for the 3 morning dashboards.

Why this exists: Dashboards are hard to create via Salesforce API (the
metadata format is gnarly and the deploy path is unreliable). List Views
are easy via API and give you 80% of the visibility a dashboard provides.

This script:
  1. Creates 4 high-value List Views via SF Tooling API
  2. Prints click-by-click dashboard build instructions for the 3 dashboards
     (compresses 45 min of UI clicking to ~15 min)

Run:
    cd ~/dealmatcher && python3 tools/sf_setup_helper.py
    cd ~/dealmatcher && python3 tools/sf_setup_helper.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

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
# List View definitions
# ---------------------------------------------------------------------------

LIST_VIEWS = [
    {
        "object": "Contact",
        "developerName": "CHF_Hot_Buyers",
        "label": "CHF — Hot Buyers (call today)",
        "filterCriteria": [
            {"field": "Contact.LeadSource", "operation": "equals",
             "value": "CheapHomesFLA_LandingPage"},
            {"field": "Contact.Buyer_Score__c", "operation": "greaterOrEqual", "value": "70"},
        ],
        "sobjectType": "Contact",
        "scope": "Everything",
        "columns": ["FULL_NAME", "EMAIL", "PHONE", "Buyer_Score__c",
                    "Buyer_Target_Zips__c", "Top_Buyer_Zips__c", "Buyer_Max_Budget__c"],
    },
    {
        "object": "Contact",
        "developerName": "CHF_Buyers_Need_Zips",
        "label": "CHF — Buyers Missing Target Zips",
        "filterCriteria": [
            {"field": "Contact.LeadSource", "operation": "equals",
             "value": "CheapHomesFLA_LandingPage"},
            {"field": "Contact.Buyer_Target_Zips__c", "operation": "equals", "value": ""},
        ],
        "sobjectType": "Contact",
        "scope": "Everything",
        "columns": ["FULL_NAME", "EMAIL", "Buyer_Counties_of_Interest__c",
                    "Buyer_Max_Budget__c", "CreatedDate"],
    },
    {
        "object": "Lead",
        "developerName": "Hot_Sellers_Today",
        "label": "Sellers — Hot Score (call today)",
        "filterCriteria": [
            {"field": "Lead.Seller_Score__c", "operation": "greaterOrEqual", "value": "70"},
            {"field": "Lead.Status", "operation": "notEqual",
             "value": "Dead,Not Interested,Take me off the list,Doesn't own anymore"},
        ],
        "sobjectType": "Lead",
        "scope": "Everything",
        "columns": ["FULL_NAME", "PHONE", "MOBILE_PHONE", "Property_Address__c",
                    "Seller_Score__c", "Auction_Date__c", "Final_Judgment__c",
                    "Reason_to_sell__c", "Status"],
    },
    {
        "object": "Lead",
        "developerName": "Recent_Sent_Contracts",
        "label": "Sellers — Recent Sent Contract (last 30d)",
        "filterCriteria": [
            {"field": "Lead.Status", "operation": "equals", "value": "Sent Contract"},
            {"field": "Lead.LastModifiedDate", "operation": "greaterThan",
             "value": "LAST_N_DAYS:30"},
        ],
        "sobjectType": "Lead",
        "scope": "Everything",
        "columns": ["FULL_NAME", "Property_Address__c", "Status",
                    "LastModifiedDate", "Owner_Asking_Price__c", "Offer_Amount__c"],
    },
]


# ---------------------------------------------------------------------------
# API path
# ---------------------------------------------------------------------------

def list_view_exists(sf, object_name: str, developer_name: str) -> bool:
    """Check if a list view with this developerName already exists."""
    try:
        res = sf.toolingexecute(
            f"query/?q=SELECT+Id+FROM+ListView+WHERE+SobjectType%3D%27{object_name}%27"
            f"+AND+DeveloperName%3D%27{developer_name}%27"
        )
        return bool(res.get("records"))
    except Exception:  # noqa: BLE001
        return False


def create_list_view(sf, lv: dict) -> tuple[bool, str]:
    """Create a list view via the Tooling API. Returns (success, message)."""
    if list_view_exists(sf, lv["object"], lv["developerName"]):
        return (True, "already exists")
    payload = {
        "Name": lv["label"],
        "DeveloperName": lv["developerName"],
        "SobjectType": lv["sobjectType"],
        "FilterScope": lv["scope"],
    }
    try:
        result = sf.toolingexecute("sobjects/ListView", method="POST", data=payload)
        if result.get("success"):
            return (True, f"created (id={result.get('id', '?')})")
        return (False, f"errors: {result.get('errors')}")
    except Exception as e:  # noqa: BLE001
        return (False, f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Dashboard click-by-click guide
# ---------------------------------------------------------------------------

DASHBOARD_GUIDE = """
═══════════════════════════════════════════════════════════════════════
DASHBOARD BUILD GUIDE — copy-paste ready, ~15 min total
═══════════════════════════════════════════════════════════════════════

The 3 dashboards we want, with their exact reports + components.

─────────────────────────────────────────────────────────────────────────
DASHBOARD 1 — "CHF Buyer Pipeline"  (5 min)
─────────────────────────────────────────────────────────────────────────

1. App Launcher → Reports → New Report
   Type: Contacts → Continue
2. Filter:  LeadSource = "CheapHomesFLA_LandingPage"
3. Group rows by:  Buyer_Primary_Strategy__c
4. Save as:  "CHF Buyers by Strategy"
5. Repeat steps 1-4 four more times — same filter, different groupings:
   a. Group by Buyer_Max_Budget__c    →  save as "CHF Buyers by Budget"
   b. Group by computed buckets (formula):
        IF(Buyer_Score__c >= 70, "Hot",
          IF(Buyer_Score__c >= 50, "Warm",
            IF(Buyer_Score__c > 0, "Cold", "Unscored")))
        Add as Bucket Field, save as "CHF Buyers by Score Tier"
   c. No grouping — just total count, save as "CHF Total Buyers"
   d. Filter additionally: Buyer_Target_Zips__c = "" (or NULL)
        save as "CHF Buyers Missing Zips"

6. App Launcher → Dashboards → New Dashboard → name "CHF Buyer Pipeline"
7. Drag 5 components onto the dashboard, one report each:
   • Donut chart from "CHF Buyers by Score Tier"
   • Bar chart from "CHF Buyers by Strategy"
   • Bar chart from "CHF Buyers by Budget"
   • Counter (big number) from "CHF Total Buyers"
   • Counter from "CHF Buyers Missing Zips"
8. Save → Pin to Home tab.

─────────────────────────────────────────────────────────────────────────
DASHBOARD 2 — "Deal Pipeline" (CHF wholesale flow)  (5 min)
─────────────────────────────────────────────────────────────────────────

1. New Report → Tasks
2. Filter:  Subject contains "CH-DEAL-" + CreatedDate = LAST_N_DAYS:7
3. Group by:  WhoId.Name
   Save as "CH Deals matched per buyer (7d)"

4. New Report → Tasks
   Filter: Subject contains "CH-DEAL-" + CreatedDate = LAST_N_DAYS:14
   Group by: CreatedDate (DAY)
   Add chart: Line chart
   Save as "CH Deals per day (14d)"

5. New Dashboard → "Deal Pipeline"
   Drag both reports as components.
   Save → Pin to Home tab.

─────────────────────────────────────────────────────────────────────────
DASHBOARD 3 — "Seller Lead Pipeline" (Johnson Buys)  (5 min)
─────────────────────────────────────────────────────────────────────────

1. New Report → Leads → Group by Status → save as "Leads by Status"
2. New Report → Leads → Group by LeadSource → save as "Leads by Source"
3. New Report → Leads filtered by CreatedDate = LAST_N_DAYS:30,
   group by CreatedDate(DAY) → save as "Leads created last 30d"
4. New Report → Tasks filtered by Subject CONTAINS 'JB-' AND
   CreatedDate = LAST_N_DAYS:30, group by CreatedDate(DAY)
   → save as "Campaign sends per day (30d)"

5. New Dashboard → "Seller Lead Pipeline"
   Drag all 4 as components.  Save → Pin to Home tab.

─────────────────────────────────────────────────────────────────────────
After all 3 dashboards exist:

App Launcher → Home → click the dropdown → "Edit Page" → drag the 3
dashboards onto the Home tab. Save & Activate. Now they load every time
you open Salesforce.

═══════════════════════════════════════════════════════════════════════
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print plan but do not create list views")
    parser.add_argument("--guide-only", action="store_true",
                        help="Skip API calls; just print the dashboard guide")
    args = parser.parse_args()

    if not args.guide_only:
        print(f"Connecting as {os.environ.get('SF_USERNAME')}...")
        sf = Salesforce(
            username=os.environ["SF_USERNAME"],
            password=os.environ["SF_PASSWORD"],
            security_token=os.environ["SF_SECURITY_TOKEN"],
        )
        print(f"Connected: {sf.sf_instance}\n")

        print("=" * 72)
        print("LIST VIEWS — creates 4 most useful sliced lists")
        print("=" * 72)
        for lv in LIST_VIEWS:
            full = f"{lv['object']}.{lv['developerName']}"
            if args.dry_run:
                print(f"  [dry-run] would create: {full}  ({lv['label']!r})")
                continue
            ok, msg = create_list_view(sf, lv)
            mark = "✓" if ok else "✗"
            print(f"  {mark} {full:<40}  {msg}")

        print()
        print("Note: list views created via API have the metadata in place but")
        print("filter criteria is set via UI follow-up. Visit each list view to")
        print("confirm filters look right and adjust if needed:")
        for lv in LIST_VIEWS:
            obj = lv["object"]
            dn = lv["developerName"]
            print(f"  https://{sf.sf_instance}/lightning/o/{obj}/list?filterName={dn}")

    print(DASHBOARD_GUIDE)


if __name__ == "__main__":
    main()
