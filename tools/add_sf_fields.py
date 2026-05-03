#!/usr/bin/env python3
"""
add_sf_fields.py — create the 4 custom fields the dealmatcher pipeline needs.

Adds:
  - Contact.Buyer_Score__c        Number(3,0)
  - Contact.Top_Buyer_Zips__c     LongTextArea(1024 chars, 5 visible lines)
  - Contact.Seller_Score__c       Number(3,0)
  - Lead.Seller_Score__c          Number(3,0)

Idempotent — re-running this is safe. Existing fields are detected and skipped.

Run:
    cd ~/dealmatcher
    python3 tools/add_sf_fields.py
    python3 tools/add_sf_fields.py --dry-run    # describe only, no writes

If the script errors out and you'd rather click through the UI:
    Salesforce → Setup → Object Manager → Contact → Fields & Relationships
    → New → Number → 3 length, 0 decimals → Field Name: Buyer_Score
    Repeat for Top_Buyer_Zips (Long Text Area, 1024 chars) and
    Seller_Score (Number 3,0). Then do Object Manager → Lead and add
    Seller_Score there too.
"""
from __future__ import annotations

import argparse
import os
import sys
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
    print("ERROR: simple_salesforce not installed. Run:")
    print("  pip3 install --break-system-packages simple-salesforce")
    sys.exit(1)


# Field definitions
FIELDS = [
    {
        "object": "Contact",
        "api_name": "Buyer_Score__c",
        "label": "Buyer Score",
        "type": "Number",
        "precision": 3,
        "scale": 0,
        "description": (
            "Composite buyer score 0-100. Hot >=70, Warm 50-69, Cold <50. "
            "Components: close history 40%, email engagement 30%, "
            "capital deployed 20%, decision velocity 10%. "
            "Refreshed by tools/buyer_score.py."
        ),
    },
    {
        "object": "Contact",
        "api_name": "Top_Buyer_Zips__c",
        "label": "Top Buyer Zips",
        "type": "LongTextArea",
        "length": 1024,
        "visibleLines": 5,
        "description": (
            "Comma-separated zip codes where this Contact is among the "
            "top 100 most active investors over the last 24 months "
            "(deeds recorded under their name or LLC). Refreshed weekly "
            "by tools/top_buyers_by_zip.py."
        ),
    },
    {
        "object": "Contact",
        "api_name": "Seller_Score__c",
        "label": "Seller Score",
        "type": "Number",
        "precision": 3,
        "scale": 0,
        "description": (
            "Motivated-seller score 0-105. Foreclosure 30 + tax-delinquent 25 + "
            "code violations 15 + hold-time 10 + equity 15 + out-of-state mailing 5 + "
            "no-homestead 5. Refreshed weekly by tools/sell_score.py."
        ),
    },
    {
        "object": "Lead",
        "api_name": "Seller_Score__c",
        "label": "Seller Score",
        "type": "Number",
        "precision": 3,
        "scale": 0,
        "description": "Same scale as Contact.Seller_Score__c. See tools/sell_score.py.",
    },
]


def field_exists(sf, object_name: str, api_name: str) -> bool:
    """Return True if the given custom field already exists on the object."""
    try:
        desc = getattr(sf, object_name).describe()
        return any(f["name"] == api_name for f in desc["fields"])
    except Exception as e:  # noqa: BLE001
        print(f"  (could not describe {object_name}: {e})")
        return False


def create_field(sf, fdef: dict) -> str:
    """Create the field via Metadata API. Returns 'created' or 'failed: <reason>'."""
    mdapi = sf.mdapi
    full_name = f"{fdef['object']}.{fdef['api_name']}"
    try:
        if fdef["type"] == "Number":
            metadata = mdapi.CustomField(
                fullName=full_name,
                label=fdef["label"],
                type=mdapi.FieldType("Number"),
                precision=fdef["precision"],
                scale=fdef["scale"],
                description=fdef.get("description", ""),
                required=False,
                externalId=False,
            )
        elif fdef["type"] == "LongTextArea":
            metadata = mdapi.CustomField(
                fullName=full_name,
                label=fdef["label"],
                type=mdapi.FieldType("LongTextArea"),
                length=fdef["length"],
                visibleLines=fdef["visibleLines"],
                description=fdef.get("description", ""),
            )
        else:
            return f"failed: unknown type {fdef['type']}"

        result = mdapi.CustomField.create(metadata)
        # simple_salesforce returns either a single result or a list
        if isinstance(result, list):
            result = result[0]
        success = getattr(result, "success", None)
        if success:
            return "created"
        # Surface error messages
        errors = getattr(result, "errors", None) or []
        msgs = []
        for e in errors:
            sm = getattr(e, "message", str(e))
            msgs.append(sm)
        return f"failed: {'; '.join(msgs) or 'unknown error'}"
    except Exception as e:  # noqa: BLE001
        return f"failed: {e}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Describe only — print which fields exist vs need creation")
    args = parser.parse_args()

    print(f"Connecting as {os.environ.get('SF_USERNAME')}...")
    sf = Salesforce(
        username=os.environ["SF_USERNAME"],
        password=os.environ["SF_PASSWORD"],
        security_token=os.environ["SF_SECURITY_TOKEN"],
    )
    print(f"Connected. SF instance: {sf.sf_instance}\n")

    plan = []
    for fdef in FIELDS:
        full = f"{fdef['object']}.{fdef['api_name']}"
        if field_exists(sf, fdef["object"], fdef["api_name"]):
            plan.append((fdef, "exists"))
            print(f"  [exists]  {full}")
        else:
            plan.append((fdef, "create"))
            if fdef["type"] == "Number":
                detail = f", {fdef['precision']},{fdef['scale']}"
            else:
                detail = f", {fdef['length']} chars"
            print(f"  [create]  {full}  ({fdef['type']}{detail})")

    if args.dry_run:
        print("\n--dry-run: no fields created.")
        return

    to_create = [(f, s) for f, s in plan if s == "create"]
    if not to_create:
        print("\nAll 4 fields already exist. Nothing to do.")
        return

    print(f"\nCreating {len(to_create)} field(s) via Metadata API...")
    created = 0
    failed = []
    for fdef, _ in to_create:
        full = f"{fdef['object']}.{fdef['api_name']}"
        result = create_field(sf, fdef)
        if result == "created":
            print(f"  OK    {full}")
            created += 1
        else:
            print(f"  FAIL  {full}: {result}")
            failed.append((full, result))

    print(f"\nCreated {created}/{len(to_create)} field(s).")
    if failed:
        print("\nFailures:")
        for f, e in failed:
            print(f"  {f}: {e}")
        print("\nIf the script can't create them, fall back to the UI path:")
        print("  Setup → Object Manager → Contact → Fields & Relationships → New")

    # Verification: re-describe and confirm
    print("\nVerification (re-describing both objects)...")
    for fdef in FIELDS:
        full = f"{fdef['object']}.{fdef['api_name']}"
        ok = field_exists(sf, fdef["object"], fdef["api_name"])
        print(f"  {'present' if ok else 'MISSING':<8}  {full}")


if __name__ == "__main__":
    main()
