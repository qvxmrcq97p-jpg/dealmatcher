#!/usr/bin/env python3
"""
add_sf_fields_v2.py — robust create-or-grant-FLS for the 4 custom fields.

v1 used Metadata API via simple_salesforce mdapi which silently failed.
v2 uses the Tooling API directly + does a SOQL probe per field to detect
the real state (exists+visible, exists+FLS-blocked, or genuinely missing).

For each target field this script:
  1. SOQL probes: SELECT <field> FROM <object> LIMIT 1
       - succeeds → field exists and is readable: skip
       - INVALID_FIELD → genuinely missing: create via Tooling API
       - any other error → unknown state: report and skip
  2. After Tooling-API create succeeds, grant Read+Edit FLS to the
     connected user's profile (via the auto-owned PermissionSet)
     so subsequent describe/SOQL calls can see it.

Run:
    cd ~/dealmatcher
    python3 tools/add_sf_fields_v2.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent.parent
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
    from simple_salesforce.exceptions import SalesforceMalformedRequest
except ImportError:
    print("ERROR: simple_salesforce not installed. Run:")
    print("  pip3 install --break-system-packages simple-salesforce")
    sys.exit(1)


FIELDS = [
    {
        "object": "Contact",
        "api_name": "Buyer_Score__c",
        "label": "Buyer Score",
        "metadata": {
            "label": "Buyer Score",
            "type": "Number",
            "precision": 3,
            "scale": 0,
            "description": "Composite buyer score 0-100. Hot >=70, Warm 50-69, Cold <50.",
            "required": False,
            "externalId": False,
        },
    },
    {
        "object": "Contact",
        "api_name": "Top_Buyer_Zips__c",
        "label": "Top Buyer Zips",
        "metadata": {
            "label": "Top Buyer Zips",
            "type": "LongTextArea",
            "length": 1024,
            "visibleLines": 5,
            "description": "Zips where this Contact is among top 100 most active investors (last 24mo deeds).",
        },
    },
    {
        "object": "Contact",
        "api_name": "Seller_Score__c",
        "label": "Seller Score",
        "metadata": {
            "label": "Seller Score",
            "type": "Number",
            "precision": 3,
            "scale": 0,
            "description": "Motivated-seller score 0-105.",
            "required": False,
            "externalId": False,
        },
    },
    {
        "object": "Lead",
        "api_name": "Seller_Score__c",
        "label": "Seller Score",
        "metadata": {
            "label": "Seller Score",
            "type": "Number",
            "precision": 3,
            "scale": 0,
            "description": "Motivated-seller score 0-105. Same scale as Contact.Seller_Score__c.",
            "required": False,
            "externalId": False,
        },
    },
]


def probe_field(sf, object_name: str, field_api_name: str) -> str:
    """Returns 'visible', 'missing', 'no_fls', or 'unknown'."""
    try:
        sf.query(f"SELECT {field_api_name} FROM {object_name} LIMIT 1")
        return "visible"
    except SalesforceMalformedRequest as e:
        msg = str(e).upper()
        body = repr(e)
        if "INVALID_FIELD" in msg or "NO SUCH COLUMN" in msg or "INVALID_FIELD" in body.upper():
            return "missing"
        if "INSUFFICIENT" in msg or "FIELD_CUSTOM_VALIDATION" in msg or "NO_ACCESS" in msg:
            return "no_fls"
        return f"unknown:{e}"
    except Exception as e:
        return f"unknown:{e}"


def create_field_via_tooling(sf, object_name: str, field_api_name: str, metadata: dict) -> tuple[bool, str]:
    """Create a custom field via the Tooling API REST endpoint."""
    full_name = f"{object_name}.{field_api_name}"
    payload = {
        "FullName": full_name,
        "Metadata": metadata,
    }
    try:
        result = sf.toolingexecute("sobjects/CustomField", method="POST", data=payload)
    except Exception as e:
        # SalesforceMalformedRequest carries the response body in str(e)
        return (False, f"{type(e).__name__}: {e}")
    if not isinstance(result, dict):
        return (False, f"unexpected response type {type(result).__name__}: {result!r}")
    if result.get("success"):
        return (True, f"created (id={result.get('id', '?')})")
    errors = result.get("errors") or []
    if errors:
        msgs = []
        for e in errors:
            if isinstance(e, dict):
                msgs.append(f"{e.get('statusCode', '')}: {e.get('message', '')}")
            else:
                msgs.append(str(e))
        return (False, " | ".join(msgs))
    return (False, f"no success, no errors. raw={json.dumps(result)[:300]}")


def get_admin_profile_permset(sf) -> Optional[str]:
    """Find the auto-owned PermissionSet for the connected user's profile."""
    username = os.environ["SF_USERNAME"]
    safe = username.replace("'", "\\'")
    me = sf.query(
        f"SELECT ProfileId FROM User WHERE Username = '{safe}' LIMIT 1"
    )
    if not me["records"]:
        return None
    profile_id = me["records"][0]["ProfileId"]
    ps = sf.query(
        f"SELECT Id FROM PermissionSet WHERE ProfileId = '{profile_id}' "
        f"AND IsOwnedByProfile = true LIMIT 1"
    )
    if not ps["records"]:
        return None
    return ps["records"][0]["Id"]


def grant_fls(sf, object_name: str, field_api_name: str, permset_id: str) -> tuple[bool, str]:
    """Create a FieldPermissions record granting Read+Edit on this field
    to the admin profile's auto-owned PermissionSet."""
    full_name = f"{object_name}.{field_api_name}"
    try:
        # Check if FieldPermissions already exists
        safe = full_name.replace("'", "\\'")
        existing = sf.query(
            f"SELECT Id, PermissionsRead, PermissionsEdit FROM FieldPermissions "
            f"WHERE Field = '{safe}' AND ParentId = '{permset_id}' LIMIT 1"
        )
        if existing["records"]:
            row = existing["records"][0]
            if row.get("PermissionsRead") and row.get("PermissionsEdit"):
                return (True, "FLS already granted")
            # Update existing record
            sf.FieldPermissions.update(row["Id"], {
                "PermissionsRead": True,
                "PermissionsEdit": True,
            })
            return (True, "FLS updated to Read+Edit")
        # Create new
        result = sf.FieldPermissions.create({
            "ParentId": permset_id,
            "SObjectType": object_name,
            "Field": full_name,
            "PermissionsRead": True,
            "PermissionsEdit": True,
        })
        if result.get("success"):
            return (True, "FLS granted")
        return (False, f"FLS create failed: {result.get('errors')}")
    except Exception as e:
        msg = str(e)
        if "duplicate" in msg.lower() or "DUPLICATE_VALUE" in msg.upper():
            return (True, "FLS already exists")
        return (False, f"{type(e).__name__}: {msg}")


def main() -> None:
    print(f"Connecting as {os.environ.get('SF_USERNAME')}...")
    sf = Salesforce(
        username=os.environ["SF_USERNAME"],
        password=os.environ["SF_PASSWORD"],
        security_token=os.environ["SF_SECURITY_TOKEN"],
    )
    print(f"Connected. SF instance: {sf.sf_instance}\n")

    print("Looking up admin profile permission set for FLS grants...")
    permset_id = get_admin_profile_permset(sf)
    print(f"  Profile-owned PermissionSet ID: {permset_id}\n")

    summary = []

    for f in FIELDS:
        full = f"{f['object']}.{f['api_name']}"
        print(f"--- {full} ---")
        state = probe_field(sf, f["object"], f["api_name"])

        if state == "visible":
            print(f"  ✓ Already exists and readable. No action.")
            summary.append((full, "OK (already)"))
            continue

        if state == "missing":
            print(f"  → SOQL says missing. Probing via Tooling API to distinguish "
                  f"truly-missing vs FLS-blocked-but-exists...")
            ok, msg = create_field_via_tooling(sf, f["object"], f["api_name"], f["metadata"])
            if ok:
                print(f"    ✓ Created: {msg}")
                if permset_id:
                    fok, fmsg = grant_fls(sf, f["object"], f["api_name"], permset_id)
                    print(f"    {'✓' if fok else '✗'} FLS: {fmsg}")
                summary.append((full, f"CREATED ({msg})"))
            elif "DUPLICATE_DEVELOPER_NAME" in msg or "already a field" in msg.lower():
                # Field truly exists in the org metadata, but the integration
                # user doesn't have FLS on it. The fix is to grant FLS only.
                print(f"    → Field already exists in org (FLS-blocked from API user). "
                      f"Granting Read+Edit FLS...")
                if permset_id:
                    fok, fmsg = grant_fls(sf, f["object"], f["api_name"], permset_id)
                    print(f"    {'✓' if fok else '✗'} {fmsg}")
                    summary.append((full, "FLS GRANTED" if fok else f"FLS FAILED: {fmsg}"))
                else:
                    summary.append((full, "FLS GRANT SKIPPED (no permset id)"))
            else:
                print(f"    ✗ Create failed: {msg}")
                summary.append((full, f"FAILED: {msg}"))
            continue

        if state == "no_fls":
            print(f"  → Field exists but no FLS. Granting Read+Edit...")
            if permset_id:
                fok, fmsg = grant_fls(sf, f["object"], f["api_name"], permset_id)
                print(f"    {'✓' if fok else '✗'} {fmsg}")
                summary.append((full, "FLS GRANTED" if fok else f"FLS FAILED: {fmsg}"))
            else:
                summary.append((full, "FLS GRANT SKIPPED (no permset id)"))
            continue

        print(f"  ? Unknown state: {state}")
        summary.append((full, f"UNKNOWN: {state}"))

    print("\n========== SUMMARY ==========")
    for full, status in summary:
        print(f"  {full:<45}  {status}")
    print()

    print("Final verification (re-probing each field)...")
    for f in FIELDS:
        full = f"{f['object']}.{f['api_name']}"
        state = probe_field(sf, f["object"], f["api_name"])
        marker = "✓" if state == "visible" else "✗"
        print(f"  {marker} {full:<45}  {state}")


if __name__ == "__main__":
    main()
