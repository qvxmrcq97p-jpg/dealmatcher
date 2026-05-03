#!/usr/bin/env python3
"""
backfill_buyer_zips.py — set Buyer_Target_Zips__c on CHF Salesforce Contacts.

Reads ~/dealmatcher/data/buyer_zip_assignments.json mapping a buyer key
(Salesforce Id OR email) to a list of zip codes, then applies the
update on each Contact. Without target zips set, the deal matcher
matches NOTHING for a buyer — this script is the on-ramp.

Run:
    cd ~/dealmatcher

    # First time: create a template assignments file from the audit
    python3 tools/backfill_buyer_zips.py --init

    # Edit data/buyer_zip_assignments.json with real zip lists, then:
    python3 tools/backfill_buyer_zips.py --dry-run    # preview
    python3 tools/backfill_buyer_zips.py              # apply

Format of buyer_zip_assignments.json:
    {
      "0035e00000ABC123ABC": ["33125", "33126", "33127"],
      "investor@example.com": ["33162", "33168", "33169"]
    }

Use Salesforce Id (15 or 18 chars) for unambiguous targeting; email
keys are resolved to Id via SOQL at runtime.
"""
from __future__ import annotations

import argparse
import json
import os
import re
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

try:
    from simple_salesforce import Salesforce
except ImportError:
    print("ERROR: simple_salesforce not installed. Run:")
    print("  pip3 install --break-system-packages simple-salesforce")
    sys.exit(1)

ASSIGNMENTS_FILE = SCRIPT_DIR / "data" / "buyer_zip_assignments.json"


def init_template() -> None:
    """Generate a starter assignments file from the most recent audit JSON."""
    audit_files = sorted((SCRIPT_DIR / "data").glob("buyer_audit_*.json"))
    if not audit_files:
        print("No buyer_audit_*.json found in data/. Run tools/audit_buyers.py first.")
        sys.exit(2)
    audit = json.loads(audit_files[-1].read_text())
    template: dict[str, list[str]] = {}
    for b in audit:
        # Pre-fill with any existing zips so we don't accidentally clear them
        existing = b.get("Buyer_Target_Zips__c") or ""
        zips = [z.strip() for z in existing.replace(",", " ").split() if z.strip().isdigit()]
        template[b["Id"]] = zips
    ASSIGNMENTS_FILE.parent.mkdir(exist_ok=True)
    ASSIGNMENTS_FILE.write_text(json.dumps(template, indent=2))
    print(f"Wrote template: {ASSIGNMENTS_FILE}")
    print()
    print("Edit it. Each entry is buyer_id → list of zip strings, like:")
    print('  "0035e00000ABC123ABC": ["33125", "33126", "33127"]')
    print()
    print("Then re-run with --dry-run to preview, then without --dry-run to apply.")


def looks_like_sf_id(key: str) -> bool:
    return len(key) in (15, 18) and bool(re.match(r"^[a-zA-Z0-9]+$", key))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true",
                        help="Generate template assignments file from most recent audit")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print intended updates without writing")
    args = parser.parse_args()

    if args.init:
        init_template()
        return

    if not ASSIGNMENTS_FILE.exists():
        print(f"Missing: {ASSIGNMENTS_FILE}")
        print("Run with --init to generate a template.")
        sys.exit(2)

    assignments = json.loads(ASSIGNMENTS_FILE.read_text())
    print(f"Loaded {len(assignments)} buyer assignment(s) from {ASSIGNMENTS_FILE}\n")

    # Skip empty assignments AND comment-style underscore keys
    non_empty = {
        k: v for k, v in assignments.items()
        if v and not k.startswith("_")
    }
    if not non_empty:
        print("No buyers have zips assigned in the file. Nothing to do.")
        sys.exit(0)

    sf = Salesforce(
        username=os.environ["SF_USERNAME"],
        password=os.environ["SF_PASSWORD"],
        security_token=os.environ["SF_SECURITY_TOKEN"],
    )

    # Resolve emails → Salesforce Ids
    resolved: dict[str, str] = {}
    for key, zips in non_empty.items():
        if isinstance(zips, list):
            zip_str = ", ".join(str(z).strip() for z in zips if str(z).strip())
        else:
            zip_str = str(zips).strip()
        if not zip_str:
            continue
        if looks_like_sf_id(key):
            resolved[key] = zip_str
        elif "@" in key:
            safe = key.replace("'", "\\'")
            res = sf.query(f"SELECT Id FROM Contact WHERE Email = '{safe}' LIMIT 1")
            if res["records"]:
                resolved[res["records"][0]["Id"]] = zip_str
            else:
                print(f"  ! No Contact found for email {key}")
        else:
            print(f"  ! Unrecognized key format (not an SF Id or email): {key}")

    print(f"Resolved to {len(resolved)} buyer Id(s).\n")
    for buyer_id, zips in resolved.items():
        print(f"  {buyer_id}  →  Buyer_Target_Zips__c = {zips!r}")

    if args.dry_run:
        print("\n--dry-run: no updates applied.")
        return

    print()
    confirm = input(f"Apply Buyer_Target_Zips__c to {len(resolved)} Contact(s)? [y/N] ")
    if confirm.strip().lower() != "y":
        print("Aborted.")
        return

    success = 0
    failures: list[tuple[str, str]] = []
    for buyer_id, zips in resolved.items():
        try:
            sf.Contact.update(buyer_id, {"Buyer_Target_Zips__c": zips})
            print(f"  OK  {buyer_id}")
            success += 1
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL {buyer_id}: {e}")
            failures.append((buyer_id, str(e)))

    print(f"\nUpdated {success}/{len(resolved)} buyers.")
    if failures:
        print("Failures:")
        for bid, err in failures:
            print(f"  {bid}: {err}")


if __name__ == "__main__":
    main()
