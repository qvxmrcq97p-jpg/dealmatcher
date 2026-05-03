#!/usr/bin/env python3
"""
audit_buyers.py — show the current state of CheapHomesFLA buyers in Salesforce.

Pulls every Contact where LeadSource = 'CheapHomesFLA_LandingPage' and
prints a per-buyer report covering every field the deal matcher cares
about. Highlights what's missing — particularly Buyer_Target_Zips__c,
without which a buyer matches nothing under the strict zip-only
geographic matching rule.

Run:
    cd ~/dealmatcher
    python3 tools/audit_buyers.py

Dependencies (one-time install):
    pip3 install --break-system-packages simple-salesforce

Output:
    stdout report
    ~/dealmatcher/data/buyer_audit_YYYYMMDD.txt   (text copy)
    ~/dealmatcher/data/buyer_audit_YYYYMMDD.json  (raw records)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Resolve ~/dealmatcher/ as the project root regardless of cwd
SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

# Load .env.cheaphomesfla manually so we don't need python-dotenv
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
    print("Install with:")
    print("  pip3 install --break-system-packages simple-salesforce")
    sys.exit(1)


# Fields we want to inspect on each Contact. Filtered later against the
# org's actual schema in case any of these don't exist (older orgs,
# partial deploys).
FIELDS_TO_CHECK = [
    "Id",
    "FirstName", "LastName",
    "Email",
    "Phone", "MobilePhone",
    "HasOptedOutOfEmail", "DoNotCall",
    "LeadSource",
    "CreatedDate",
    # CHF-specific fields populated by the cheaphomesfla.com form
    "Buyer_Target_Zips__c",
    "Buyer_Counties_of_Interest__c",
    "Buyer_Max_Budget__c",
    "Buyer_Primary_Strategy__c",
    "Buyer_Neighborhoods__c",
    "Are_you_willing_to_Rehab__c",
    "Status__c",
    # Per-county city multi-select picklists
    "Miami_DADE__c", "Broward__c", "West_Palm_Beach__c",
    "Hillsborough__c", "Pinellas__c", "Duval__c",
    "Lee__c", "Sarasota__c", "Manatee__c", "Polk__c",
    "Alachua__c", "Brevard__c", "Charlotte__c", "Citrus__c",
    "Collier__c", "Hernando__c", "Leon__c", "Monroe__c",
    "Pasco__c", "Seminole__c", "St_Johns__c", "St_Lucie__c",
    "Volusia__c",
]

PER_COUNTY_FIELDS = {
    "Alachua__c", "Brevard__c", "Broward__c", "Charlotte__c", "Citrus__c",
    "Collier__c", "Duval__c", "Hernando__c", "Hillsborough__c", "Lee__c",
    "Leon__c", "Manatee__c", "Miami_DADE__c", "Monroe__c", "Pasco__c",
    "Pinellas__c", "Polk__c", "Sarasota__c", "Seminole__c", "St_Johns__c",
    "St_Lucie__c", "Volusia__c", "West_Palm_Beach__c",
}


def main() -> None:
    print(f"Connecting to Salesforce as {os.environ.get('SF_USERNAME')}...")
    sf = Salesforce(
        username=os.environ["SF_USERNAME"],
        password=os.environ["SF_PASSWORD"],
        security_token=os.environ["SF_SECURITY_TOKEN"],
    )
    print("Connected.\n")

    # Filter requested fields against the org's actual schema
    desc = sf.Contact.describe()
    existing = {f["name"] for f in desc["fields"]}
    fields = [f for f in FIELDS_TO_CHECK if f in existing]
    schema_missing = [f for f in FIELDS_TO_CHECK if f not in existing]

    soql = (
        f"SELECT {','.join(fields)} FROM Contact "
        f"WHERE LeadSource = 'CheapHomesFLA_LandingPage' "
        f"ORDER BY CreatedDate DESC"
    )
    print(f"Querying:\n  {soql}\n")
    res = sf.query_all(soql)
    buyers = res["records"]
    for b in buyers:
        b.pop("attributes", None)

    # ---------- Summary ----------
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append(f"CheapHomesFLA Buyer Audit — {datetime.now().isoformat(timespec='seconds')}")
    lines.append("=" * 78)
    lines.append(f"Active CHF buyers found: {len(buyers)}")
    lines.append(f"Schema fields not in org: {schema_missing or '(none)'}")
    lines.append("")

    has_email = sum(1 for b in buyers if b.get("Email"))
    has_phone = sum(1 for b in buyers if (b.get("Phone") or b.get("MobilePhone")))
    has_zips = sum(1 for b in buyers if b.get("Buyer_Target_Zips__c"))
    has_budget = sum(1 for b in buyers if b.get("Buyer_Max_Budget__c"))
    has_counties = sum(1 for b in buyers if b.get("Buyer_Counties_of_Interest__c"))
    has_rehab = sum(1 for b in buyers if b.get("Are_you_willing_to_Rehab__c"))
    has_strategy = sum(1 for b in buyers if b.get("Buyer_Primary_Strategy__c"))
    opted_out = sum(1 for b in buyers if b.get("HasOptedOutOfEmail"))

    lines.append(f"  has Email:                 {has_email}/{len(buyers)}")
    lines.append(f"  has Phone or Mobile:       {has_phone}/{len(buyers)}")
    lines.append(f"  has Buyer_Target_Zips:     {has_zips}/{len(buyers)}    *** matching key ***")
    lines.append(f"  has Buyer_Max_Budget:      {has_budget}/{len(buyers)}")
    lines.append(f"  has Counties of Interest:  {has_counties}/{len(buyers)}")
    lines.append(f"  has Buyer_Primary_Strategy:{has_strategy}/{len(buyers)}")
    lines.append(f"  has Rehab tolerance:       {has_rehab}/{len(buyers)}")
    lines.append(f"  HasOptedOutOfEmail:        {opted_out}/{len(buyers)}")
    lines.append("")

    # ---------- Per-buyer detail ----------
    lines.append("-" * 78)
    lines.append("Per-buyer detail:")
    lines.append("-" * 78)
    for i, b in enumerate(buyers, 1):
        name = f"{b.get('FirstName') or ''} {b.get('LastName') or ''}".strip() or "(no name)"
        lines.append(f"\n{i}. {name}    [{b['Id']}]    created {b.get('CreatedDate', '?')[:10]}")
        lines.append(f"   Email:    {b.get('Email') or '—'}")
        lines.append(f"   Phone:    {b.get('Phone') or b.get('MobilePhone') or '—'}")
        lines.append(f"   Status:   {b.get('Status__c') or '—'}")
        lines.append(f"   Budget:   {b.get('Buyer_Max_Budget__c') or '—'}")
        lines.append(f"   Strategy: {b.get('Buyer_Primary_Strategy__c') or '—'}")
        lines.append(f"   Rehab:    {b.get('Are_you_willing_to_Rehab__c') or '—'}")
        lines.append(f"   Counties: {b.get('Buyer_Counties_of_Interest__c') or '—'}")
        zips = b.get("Buyer_Target_Zips__c") or ""
        if zips:
            zip_list = [z.strip() for z in zips.replace(",", " ").split() if z.strip()]
            lines.append(f"   Zips:     {', '.join(zip_list)}    ({len(zip_list)} zips)")
        else:
            lines.append(f"   Zips:     (none — buyer matches NOTHING)  *** ACTION NEEDED ***")
        if b.get("Buyer_Neighborhoods__c"):
            lines.append(f"   Hoods:    {b['Buyer_Neighborhoods__c']}")
        # Per-county city pickers
        cc = []
        for f in PER_COUNTY_FIELDS:
            v = b.get(f)
            if v:
                cc.append(f"{f.replace('__c','').replace('_',' ')}: {v}")
        if cc:
            lines.append(f"   Cities:   {' | '.join(cc)}")
        lines.append(f"   Email opt-out: {bool(b.get('HasOptedOutOfEmail'))}, "
                     f"DNC: {bool(b.get('DoNotCall'))}")

    # ---------- Action recommendations ----------
    lines.append("")
    lines.append("-" * 78)
    lines.append("Action recommendations:")
    lines.append("-" * 78)
    no_zip = [b for b in buyers if not b.get("Buyer_Target_Zips__c")]
    if no_zip:
        lines.append(
            f"\n{len(no_zip)} buyer(s) have no Target Zips set — they will match NOTHING:"
        )
        for b in no_zip:
            counties = b.get("Buyer_Counties_of_Interest__c") or "(no counties either)"
            name = f"{b.get('FirstName') or ''} {b.get('LastName') or ''}".strip() or "(no name)"
            lines.append(f"  - {name}  ({b['Id']})")
            lines.append(f"      counties:    {counties}")
            # Pull non-empty per-county city pickers as a hint
            hints = []
            for f in PER_COUNTY_FIELDS:
                v = b.get(f)
                if v:
                    hints.append(f"{f.replace('__c','').replace('_',' ')}: {v}")
            if hints:
                lines.append(f"      city hints:  {' | '.join(hints)}")
        lines.append("")
        lines.append("Next steps:")
        lines.append("  1. For each buyer above, decide which Miami-Dade zip codes")
        lines.append("     they should receive deals from. Use their counties + city")
        lines.append("     hints + a brief conversation to confirm.")
        lines.append("  2. Edit data/buyer_zip_assignments.json (template will be created")
        lines.append("     by tools/backfill_buyer_zips.py --init).")
        lines.append("  3. Run: python3 tools/backfill_buyer_zips.py --dry-run  to preview")
        lines.append("     Run: python3 tools/backfill_buyer_zips.py            to apply")
    else:
        lines.append("\nAll buyers have Target Zips set — matcher should produce results.")

    report = "\n".join(lines)
    print(report)

    # ---------- Persist ----------
    out_dir = SCRIPT_DIR / "data"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")
    txt_file = out_dir / f"buyer_audit_{stamp}.txt"
    json_file = out_dir / f"buyer_audit_{stamp}.json"
    txt_file.write_text(report)
    json_file.write_text(json.dumps(buyers, indent=2, default=str))
    print(f"\n→ Saved: {txt_file}")
    print(f"→ Saved: {json_file}")


if __name__ == "__main__":
    main()
