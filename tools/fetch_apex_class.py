#!/usr/bin/env python3
"""
fetch_apex_class.py — pull an Apex class source from Salesforce via the
Tooling API. Writes to salesforce/apex/<ClassName>.cls so we can inspect
the code and write tests against it.

Run:
    cd ~/dealmatcher
    python3 tools/fetch_apex_class.py BatchUpdateTheContactRecords
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
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 tools/fetch_apex_class.py <ClassName> [<ClassName2> ...]")
        sys.exit(1)

    from simple_salesforce import Salesforce
    sf = Salesforce(
        username=os.environ["SF_USERNAME"],
        password=os.environ["SF_PASSWORD"],
        security_token=os.environ["SF_SECURITY_TOKEN"],
    )

    out_dir = SCRIPT_DIR / "salesforce" / "apex"
    out_dir.mkdir(parents=True, exist_ok=True)

    for cls_name in sys.argv[1:]:
        print(f"Fetching {cls_name}...")
        names_quoted = f"'{cls_name}'"
        r = sf.toolingexecute(
            f"query/?q=SELECT+Id,Name,ApiVersion,Status,Body+FROM+ApexClass+WHERE+Name+IN+({names_quoted})"
        )
        records = r.get("records", [])
        if not records:
            print(f"  ❌ Not found: {cls_name}")
            continue
        rec = records[0]
        cls_path = out_dir / f"{rec['Name']}.cls"
        meta_path = out_dir / f"{rec['Name']}.cls-meta.xml"
        cls_path.write_text(rec["Body"])
        meta_path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ApexClass xmlns="http://soap.sforce.com/2006/04/metadata">\n'
            f'    <apiVersion>{rec["ApiVersion"]}</apiVersion>\n'
            f'    <status>{rec["Status"]}</status>\n'
            '</ApexClass>\n'
        )
        print(f"  ✓ Id: {rec['Id']}")
        print(f"  ✓ Status: {rec['Status']}, API: {rec['ApiVersion']}")
        print(f"  ✓ Wrote {cls_path.relative_to(SCRIPT_DIR)}")
        print(f"  ✓ Wrote {meta_path.relative_to(SCRIPT_DIR)}")
        print(f"  ✓ Body length: {len(rec['Body'])} chars")
        print("")
        print("─── First 80 lines ───")
        for i, line in enumerate(rec["Body"].splitlines()[:80], 1):
            print(f"  {i:3d}  {line}")
        print("─── ... ───")


if __name__ == "__main__":
    main()
