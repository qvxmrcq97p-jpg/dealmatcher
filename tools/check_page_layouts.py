#!/usr/bin/env python3
"""
check_page_layouts.py — verify which custom fields are on which page layouts
for Contact and Lead.

Useful sanity check after manually editing layouts in Setup. The describe-
layouts REST endpoint returns the active layout for each record type and
which sections + fields it contains.

Run:
    cd ~/dealmatcher
    python3 tools/check_page_layouts.py
"""
from __future__ import annotations

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

# Fields we care about per object
TARGETS = {
    "Contact": ("Buyer_Score__c", "Top_Buyer_Zips__c", "Seller_Score__c", "Buyer_Target_Zips__c"),
    "Lead":    ("Seller_Score__c",),
}


def main() -> None:
    sf = Salesforce(
        username=os.environ["SF_USERNAME"],
        password=os.environ["SF_PASSWORD"],
        security_token=os.environ["SF_SECURITY_TOKEN"],
    )
    print(f"Connected: {sf.sf_instance}\n")

    for obj, fields in TARGETS.items():
        print(f"========== {obj} layouts ==========")
        try:
            layouts = sf.restful(f"sobjects/{obj}/describe/layouts/")
        except Exception as e:
            print(f"  ERROR fetching layouts: {e}")
            continue

        # describe/layouts returns recordTypeMappings + layouts (per record type)
        # For each layout, list fields present.
        for lyt in layouts.get("layouts", []):
            label = lyt.get("name") or "(unnamed)"
            print(f"\n  Layout: {label}")
            present_fields: set[str] = set()
            for section in lyt.get("detailLayoutSections", []):
                for row in section.get("layoutRows", []):
                    for item in row.get("layoutItems", []):
                        for col in item.get("layoutComponents", []):
                            api = col.get("value")
                            if api:
                                present_fields.add(api)
            for f in fields:
                marker = "✓ ON LAYOUT" if f in present_fields else "✗ NOT on layout"
                print(f"    {marker:<22}  {f}")


if __name__ == "__main__":
    main()
