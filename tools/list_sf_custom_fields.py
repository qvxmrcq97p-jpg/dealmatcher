#!/usr/bin/env python3
"""
list_sf_custom_fields.py — print every custom field on Contact and Lead.

Use this to confirm the EXACT API names in your org before running
tools/add_sf_fields.py. If a field exists in Setup but doesn't show up
here, it's a field-level security issue: your integration user
(info@johnsonbuys.com) needs Read access on the field via Setup →
Profiles → System Administrator → Object Settings → Contact →
Field Permissions.

Run:
    cd ~/dealmatcher
    python3 tools/list_sf_custom_fields.py
"""
import os
import sys
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

sf = Salesforce(
    username=os.environ["SF_USERNAME"],
    password=os.environ["SF_PASSWORD"],
    security_token=os.environ["SF_SECURITY_TOKEN"],
)
print(f"Connected: {sf.sf_instance}\n")

OF_INTEREST = (
    "buyer_score", "top_buyer_zips", "buyer_target_zips",
    "seller_score", "buyerattributes", "buyer_attribute",
    "buyer_max_budget", "buyer_neighborhoods",
    "buyer_primary_strategy", "buyer_counties_of_interest",
    "are_you_willing_to_rehab",
)

for obj in ("Contact", "Lead"):
    print(f"========== {obj} custom fields ==========")
    desc = getattr(sf, obj).describe()
    custom = [f for f in desc["fields"] if f["name"].endswith("__c")]
    if not custom:
        print("  (no custom fields found via API)")
        print()
        continue
    for f in sorted(custom, key=lambda x: x["name"]):
        marker = "  ← OF INTEREST" if any(o in f["name"].lower() for o in OF_INTEREST) else ""
        print(f"  {f['name']:<42}  type={f['type']:<14}  label={f['label']!r}{marker}")
    print()
