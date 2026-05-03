#!/usr/bin/env python3
"""
dedup_leads.py — find + merge duplicate Leads in Salesforce.

Duplicate detection runs three independent passes:
  1. Phone match — group by last-10-digits across Phone, MobilePhone, Phone2__c
  2. Email match — group by lowercased+stripped email
  3. Address match — group by normalized Property_Address__c
                    (uppercase, no punctuation, expanded suffixes)

For each duplicate group:
  - Master selected by: highest Seller_Score__c → most recent LastModifiedDate
  - Other records become candidates for merge into master
  - Output: CSV report at ~/dealmatcher/data/dedup_proposals_YYYYMMDD.csv

Salesforce native Lead merge API allows up to 3 records per call (1 master
+ 2 duplicates). Larger groups handled by chained merges (master + 2,
then result + 2 more, etc.).

Run:
    cd ~/dealmatcher

    # Step 1: dry-run analysis — produces CSV but no SF writes
    python3 tools/dedup_leads.py --dry-run

    # Step 2: review the CSV in ~/dealmatcher/data/
    open data/dedup_proposals_*.csv

    # Step 3: apply (irreversible — read CSV first!)
    python3 tools/dedup_leads.py --apply

By default scores recent leads first to avoid burning API limits on stale.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime
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

from simple_salesforce import Salesforce


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def normalize_phone(p: Optional[str]) -> Optional[str]:
    """Last 10 digits, or None if not enough digits."""
    if not p:
        return None
    digits = re.sub(r"\D", "", str(p))
    if len(digits) < 10:
        return None
    return digits[-10:]


def normalize_email(e: Optional[str]) -> Optional[str]:
    if not e:
        return None
    e = str(e).strip().lower()
    return e if "@" in e else None


_ADDR_SUFFIX = {
    r"\bSTREET\b": "ST",     r"\bAVENUE\b": "AVE",  r"\bROAD\b": "RD",
    r"\bBOULEVARD\b": "BLVD", r"\bDRIVE\b": "DR",   r"\bLANE\b": "LN",
    r"\bCOURT\b": "CT",       r"\bPLACE\b": "PL",   r"\bCIRCLE\b": "CIR",
    r"\bPARKWAY\b": "PKWY",   r"\bTERRACE\b": "TER",
    r"\bNORTH\b": "N",        r"\bSOUTH\b": "S",
    r"\bEAST\b": "E",         r"\bWEST\b": "W",
}


def normalize_address(a: Optional[str]) -> Optional[str]:
    if not a:
        return None
    s = str(a).upper().strip()
    s = re.sub(r"[.,#]", " ", s)
    for pat, repl in _ADDR_SUFFIX.items():
        s = re.sub(pat, repl, s)
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) >= 6 else None  # too-short addresses are noise


# ---------------------------------------------------------------------------
# Master selection
# ---------------------------------------------------------------------------

def pick_master(records: list[dict]) -> dict:
    """Highest Seller_Score__c → most recent LastModifiedDate → first."""
    def key(r):
        score = r.get("Seller_Score__c") or 0
        modified = r.get("LastModifiedDate") or "1970-01-01T00:00:00Z"
        return (-score, -ord(modified[0]) if modified else 0, modified)
    sorted_records = sorted(
        records,
        key=lambda r: (
            -(r.get("Seller_Score__c") or 0),  # higher score first
            r.get("LastModifiedDate") or "",   # more recent first (string sort works for ISO dates)
        ),
        reverse=False,
    )
    # Reverse second criterion (we want most recent)
    sorted_records = sorted(
        records,
        key=lambda r: (
            -(r.get("Seller_Score__c") or 0),
            -(int(r.get("LastModifiedDate", "").replace("-", "").replace("T", "")[:14] or "0")),
        ),
    )
    return sorted_records[0]


# ---------------------------------------------------------------------------
# Salesforce I/O
# ---------------------------------------------------------------------------

QUERY_FIELDS = [
    "Id", "FirstName", "LastName",
    "Phone", "MobilePhone", "Phone2__c",
    "Email",
    "Property_Address__c", "Property_City__c", "Property_Zip__c",
    "Status", "LeadSource",
    "Seller_Score__c",
    "CreatedDate", "LastModifiedDate",
]


def fetch_leads(sf, limit: int = 0) -> list[dict]:
    desc = sf.Lead.describe()
    existing = {f["name"] for f in desc["fields"]}
    fields = [f for f in QUERY_FIELDS if f in existing]
    soql = f"SELECT {','.join(fields)} FROM Lead ORDER BY LastModifiedDate DESC"
    if limit > 0:
        soql += f" LIMIT {limit}"
    print(f"Querying: {soql[:120]}...")
    res = sf.query_all(soql)
    out = []
    for r in res["records"]:
        r.pop("attributes", None)
        out.append(r)
    return out


def merge_leads(sf, master_id: str, dup_ids: list[str]) -> tuple[bool, str]:
    """Merge up to 2 duplicates into master via Lead merge API.

    Salesforce REST: POST /sobjects/Lead/{master}/merge
    Body: {"recordsToMerge": ["dup1Id", "dup2Id"]}  (max 2 per call)
    """
    if not dup_ids:
        return (True, "no dups to merge")
    # Chunk in groups of 2 since SF caps at master + 2 duplicates per call
    success_count = 0
    failure_msgs = []
    for i in range(0, len(dup_ids), 2):
        chunk = dup_ids[i:i + 2]
        try:
            sf.restful(
                f"sobjects/Lead/{master_id}/merge",
                method="POST",
                json={"recordsToMerge": chunk},
            )
            success_count += len(chunk)
        except Exception as e:  # noqa: BLE001
            failure_msgs.append(f"chunk {chunk}: {type(e).__name__}: {str(e)[:200]}")
    if failure_msgs:
        return (False, " | ".join(failure_msgs))
    return (True, f"merged {success_count} duplicate(s)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Analyze + write CSV, no merges (DEFAULT-SAFE)")
    parser.add_argument("--apply", action="store_true",
                        help="Apply merges via SF API. IRREVERSIBLE.")
    parser.add_argument("--limit", type=int, default=0,
                        help="Limit query to N most recent leads (0 = all)")
    parser.add_argument("--by", choices=("phone", "email", "address", "all"),
                        default="all",
                        help="Which dedup pass(es) to run. Default: all three.")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        args.dry_run = True
        print("(no flag specified — defaulting to --dry-run for safety)\n")

    print(f"Connecting as {os.environ.get('SF_USERNAME')}...")
    sf = Salesforce(
        username=os.environ["SF_USERNAME"],
        password=os.environ["SF_PASSWORD"],
        security_token=os.environ["SF_SECURITY_TOKEN"],
    )
    print(f"Connected: {sf.sf_instance}\n")

    leads = fetch_leads(sf, limit=args.limit)
    print(f"Loaded {len(leads):,} leads.\n")

    # ---------- Build buckets ----------
    phone_buckets: dict[str, list[dict]] = defaultdict(list)
    email_buckets: dict[str, list[dict]] = defaultdict(list)
    addr_buckets: dict[str, list[dict]] = defaultdict(list)

    for r in leads:
        # Phone bucket — try all 3 phone fields, normalize each, bucket each
        for fld in ("Phone", "MobilePhone", "Phone2__c"):
            n = normalize_phone(r.get(fld))
            if n:
                phone_buckets[n].append(r)
                break  # one phone bucket per lead is enough
        # Email bucket
        e = normalize_email(r.get("Email"))
        if e:
            email_buckets[e].append(r)
        # Address bucket
        a = normalize_address(r.get("Property_Address__c"))
        if a:
            addr_buckets[a].append(r)

    # ---------- Compute dupe groups ----------
    dupe_groups: list[tuple[str, str, list[dict]]] = []  # (reason, key, records)
    if args.by in ("phone", "all"):
        for k, recs in phone_buckets.items():
            if len(recs) > 1:
                dupe_groups.append(("phone", k, recs))
    if args.by in ("email", "all"):
        for k, recs in email_buckets.items():
            if len(recs) > 1:
                dupe_groups.append(("email", k, recs))
    if args.by in ("address", "all"):
        for k, recs in addr_buckets.items():
            if len(recs) > 1:
                dupe_groups.append(("address", k, recs))

    # ---------- De-duplicate the dupe groups themselves (a lead can be in
    # multiple groups; we merge in priority phone > email > address) ----------
    seen_lead_pairs: set[tuple[str, str]] = set()
    final_groups: list[dict] = []
    for reason, key, recs in dupe_groups:
        master = pick_master(recs)
        master_id = master["Id"]
        dup_ids = [r["Id"] for r in recs if r["Id"] != master_id]
        if not dup_ids:
            continue
        # Filter out pairs we've already proposed (e.g. same pair caught by
        # both phone and address)
        new_dups = []
        for dup_id in dup_ids:
            pair = tuple(sorted([master_id, dup_id]))
            if pair in seen_lead_pairs:
                continue
            seen_lead_pairs.add(pair)
            new_dups.append(dup_id)
        if not new_dups:
            continue
        final_groups.append({
            "reason": reason,
            "key": key,
            "master": master,
            "duplicates": [r for r in recs if r["Id"] in new_dups],
        })

    print(f"Found {len(final_groups):,} duplicate groups "
          f"covering {sum(len(g['duplicates']) for g in final_groups):,} duplicate Leads.\n")

    # ---------- By reason summary ----------
    by_reason = defaultdict(int)
    for g in final_groups:
        by_reason[g["reason"]] += 1
    for r, n in sorted(by_reason.items()):
        print(f"  {r:<10} groups: {n:,}")
    print()

    # ---------- Write CSV report ----------
    out_dir = SCRIPT_DIR / "data"
    out_dir.mkdir(exist_ok=True)
    stamp = date.today().strftime("%Y%m%d")
    csv_path = out_dir / f"dedup_proposals_{stamp}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "reason", "match_key",
            "master_id", "master_name", "master_status", "master_score", "master_modified",
            "dup_id", "dup_name", "dup_status", "dup_score", "dup_modified",
            "dup_address", "dup_phone",
        ])
        for g in final_groups:
            m = g["master"]
            mname = f"{m.get('FirstName') or ''} {m.get('LastName') or ''}".strip() or "(no name)"
            for d in g["duplicates"]:
                dname = f"{d.get('FirstName') or ''} {d.get('LastName') or ''}".strip() or "(no name)"
                w.writerow([
                    g["reason"], g["key"],
                    m["Id"], mname, m.get("Status", ""), m.get("Seller_Score__c", ""),
                    m.get("LastModifiedDate", ""),
                    d["Id"], dname, d.get("Status", ""), d.get("Seller_Score__c", ""),
                    d.get("LastModifiedDate", ""),
                    d.get("Property_Address__c", "") or "",
                    d.get("Phone") or d.get("MobilePhone") or "",
                ])
    print(f"→ Proposal CSV: {csv_path}")
    print(f"  Open it to review before applying:")
    print(f"  open {csv_path}")
    print()

    # ---------- Apply merges? ----------
    if args.dry_run:
        print("--dry-run: no merges applied.")
        print("Review the CSV. To apply, re-run with --apply.")
        return

    if args.apply:
        confirm = input(
            f"\n*** ABOUT TO MERGE {sum(len(g['duplicates']) for g in final_groups):,} "
            f"duplicate Leads into {len(final_groups):,} masters. "
            "This is IRREVERSIBLE. Type 'MERGE' to confirm: "
        )
        if confirm.strip() != "MERGE":
            print("Aborted.")
            return

        print(f"\nApplying {len(final_groups):,} merge groups...")
        ok_count = 0
        fail_count = 0
        failures = []
        for i, g in enumerate(final_groups):
            if i and i % 50 == 0:
                print(f"  ... {i:,}/{len(final_groups):,} ({ok_count} OK, {fail_count} fail)")
            master_id = g["master"]["Id"]
            dup_ids = [d["Id"] for d in g["duplicates"]]
            ok, msg = merge_leads(sf, master_id, dup_ids)
            if ok:
                ok_count += 1
            else:
                fail_count += 1
                failures.append((master_id, msg))

        print(f"\nMerged {ok_count:,}/{len(final_groups):,} groups successfully.")
        if failures:
            print(f"\n{len(failures)} failures (first 5):")
            for mid, msg in failures[:5]:
                print(f"  {mid}: {msg}")


if __name__ == "__main__":
    main()
