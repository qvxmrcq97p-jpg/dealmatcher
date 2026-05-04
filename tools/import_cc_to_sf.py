#!/usr/bin/env python3
"""
Import Constant Contact list into Salesforce as Contacts.

Cross-references your existing 26k CC contacts against SF Contacts.
For anyone in CC but not in SF, creates a new SF Contact with:
  - LeadSource = 'CheapHomesFLA_LandingPage' (so the scraper sees them)
  - Status = 'Active'
  - Empty buy-box criteria (so they're in firehose mode for CC blast,
    but get no per-buyer scraper emails until they self-segment via form)

Then optionally syncs CC engagement signals (last_open, last_click) onto
SF Contact custom fields for segmentation later.

Workflow:
  1. Export CC list to CSV (CC dashboard → Contacts → Export → CSV)
  2. Save as ~/Desktop/cc_export.csv (or pass --csv path)
  3. Run: python3 tools/import_cc_to_sf.py --csv ~/Desktop/cc_export.csv [--dry-run]

Output:
  - Per-row report (created / matched / skipped)
  - Summary: how many new Contacts created, how many already existed
  - Saved CSV report at ~/Desktop/cc_to_sf_import_report_YYYYMMDD.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DESKTOP = Path.home() / "Desktop"

sys.path.insert(0, str(REPO))


def load_env():
    env = {}
    env_file = REPO / ".env.cheaphomesfla"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", required=True, help="Path to CC export CSV")
    p.add_argument("--dry-run", action="store_true", help="Show what would happen, don't create anything")
    p.add_argument("--limit", type=int, default=0, help="Cap rows processed (0 = all)")
    return p.parse_args()


def normalize_email(s):
    return (s or "").strip().lower()


def main():
    args = parse_args()
    env = load_env()

    csv_path = Path(args.csv).expanduser()
    if not csv_path.exists():
        print(f"✗ CSV not found at {csv_path}")
        sys.exit(1)

    from simple_salesforce import Salesforce, exceptions as sf_exc
    sf = Salesforce(
        username=env["SF_USERNAME"],
        password=env["SF_PASSWORD"],
        security_token=env["SF_SECURITY_TOKEN"],
        domain=env.get("SF_DOMAIN", "login"),
    )

    print(f"\n═══ CC → SF IMPORT ═══")
    print(f"CSV:     {csv_path}")
    print(f"Dry-run: {args.dry_run}")
    print()

    # Step 1: Read CC CSV
    print("→ Reading CC export CSV...")
    cc_contacts = []
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            email = normalize_email(row.get("Email") or row.get("email") or row.get("Email Address") or "")
            if not email or "@" not in email:
                continue
            cc_contacts.append({
                "email": email,
                "first_name": (row.get("First Name") or row.get("first_name") or "").strip(),
                "last_name": (row.get("Last Name") or row.get("last_name") or "").strip(),
                "phone": (row.get("Phone") or row.get("phone") or "").strip(),
                "city": (row.get("City") or row.get("city") or "").strip(),
                "state": (row.get("State") or row.get("state") or "").strip(),
                "zip": (row.get("Zip") or row.get("zip") or row.get("Postal Code") or "").strip(),
            })
    print(f"  ✓ {len(cc_contacts)} valid contacts in CSV\n")

    if args.limit and args.limit < len(cc_contacts):
        cc_contacts = cc_contacts[:args.limit]
        print(f"  (limited to first {args.limit} for this run)\n")

    # Step 2: Bulk fetch existing SF Contacts by email (chunk to avoid SOQL limits)
    print("→ Cross-referencing against existing SF Contacts...")
    existing_emails = set()
    BATCH = 200
    for i in range(0, len(cc_contacts), BATCH):
        batch = cc_contacts[i:i + BATCH]
        emails = [c["email"] for c in batch]
        # SOQL IN clause; quoting required
        in_clause = ",".join(f"'{e}'" for e in emails)
        soql = f"SELECT Id, Email FROM Contact WHERE Email IN ({in_clause}) LIMIT {BATCH}"
        try:
            r = sf.query(soql)
            for rec in r["records"]:
                if rec.get("Email"):
                    existing_emails.add(rec["Email"].lower())
        except Exception as e:
            print(f"  ⚠ batch {i//BATCH} query failed: {e}")
        if i % 1000 == 0 and i:
            print(f"    checked {i}/{len(cc_contacts)}...")
    print(f"  ✓ {len(existing_emails)} CC contacts already in SF")
    print(f"  ✓ {len(cc_contacts) - len(existing_emails)} need to be created\n")

    if args.dry_run:
        print("DRY-RUN — no SF Contacts will be created.")
        print(f"\nWould create {len(cc_contacts) - len(existing_emails)} new SF Contacts.")
        print(f"Would skip {len(existing_emails)} existing.")
        return

    # Step 3: Create missing Contacts
    print("→ Creating new SF Contacts...")
    results = []
    created = 0
    failed = 0
    skipped = 0
    for i, c in enumerate(cc_contacts, 1):
        if c["email"] in existing_emails:
            results.append({**c, "status": "skipped_exists", "sf_id": ""})
            skipped += 1
            continue

        first = c["first_name"] or "Friend"  # SF Contact requires LastName at minimum
        last = c["last_name"] or first
        if not last or last == first:
            last = "Investor"

        record = {
            "FirstName": first[:40] or None,
            "LastName": last[:80] or "Investor",
            "Email": c["email"],
            "Phone": c["phone"] or None,
            "MailingCity": c["city"] or None,
            "MailingState": c["state"] or None,
            "MailingPostalCode": c["zip"] or None,
            "LeadSource": "CheapHomesFLA_LandingPage",
            "Status__c": "Active",  # custom field — adjust if your org uses different picklist
        }
        # Strip nulls
        record = {k: v for k, v in record.items() if v is not None}

        try:
            r = sf.Contact.create(record)
            sf_id = r.get("id") if r.get("success") else None
            if sf_id:
                results.append({**c, "status": "created", "sf_id": sf_id})
                created += 1
            else:
                results.append({**c, "status": "failed", "sf_id": "", "error": str(r)})
                failed += 1
        except Exception as e:
            err = str(e)[:200]
            results.append({**c, "status": "failed", "sf_id": "", "error": err})
            failed += 1

        if i % 100 == 0:
            print(f"    {i}/{len(cc_contacts)} processed (created: {created}, skipped: {skipped}, failed: {failed})")
        time.sleep(0.05)  # gentle on SF API

    # Step 4: Save report CSV
    report_file = DESKTOP / f"cc_to_sf_import_report_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    with report_file.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["email", "first_name", "last_name", "phone", "city", "state", "zip", "status", "sf_id", "error"])
        writer.writeheader()
        for row in results:
            writer.writerow({k: row.get(k, "") for k in writer.fieldnames})

    print(f"\n═══ DONE ═══")
    print(f"  Created:  {created}")
    print(f"  Skipped:  {skipped} (already in SF)")
    print(f"  Failed:   {failed}")
    print(f"\n📝 Report saved to: {report_file}")
    print()
    if failed:
        print("Failures (likely SF validation rules or duplicate-detection):")
        for row in results:
            if row.get("status") == "failed":
                print(f"  ✗ {row['email']}: {row.get('error', '?')[:120]}")
                if results.index(row) >= 5:
                    print(f"  ... and more (see report CSV)")
                    break


if __name__ == "__main__":
    main()
