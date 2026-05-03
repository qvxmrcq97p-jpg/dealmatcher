#!/usr/bin/env python3
"""
build_investor_list.py — clean dedup'd investor contact CSV
────────────────────────────────────────────────────────────
Pulls every CHF investor we can identify and produces a single ready-to-
upload CSV for Constant Contact:

  Sources combined:
    1. Salesforce: Contacts WHERE LeadSource = 'CheapHomesFLA_LandingPage'
    2. Salesforce: Contacts created from SendGrid Event Webhook
       (LeadSource = 'Email Engagement (auto-created)')
    3. senders.txt — the wholesalers who email cheaphomesfla. These are
       BUYERS to us (they own deals to buy) but they also tend to be
       investors themselves who'd subscribe to our buy-box opt-in.
    4. Optional: a manual additions CSV at data/investor_additions.csv
       (1 row per investor, columns: email, first_name, last_name,
        company, phone, source). Created by hand if Chris wants to seed
       the list with people NOT in SF yet.

  Dedup keys:
    - Email (normalized to lowercase, trimmed) — primary
    - If two records share an email, keep the one with the most fields populated

  Output:
    ~/Desktop/investor_contacts_clean.csv      ← upload to Constant Contact
    ~/dealmatcher/data/investor_contacts.csv   ← repo copy

Run:
    cd ~/dealmatcher && python3 tools/build_investor_list.py
    cd ~/dealmatcher && python3 tools/build_investor_list.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = SCRIPT_DIR / ".env.cheaphomesfla"
if ENV_FILE.exists():
    for ln in ENV_FILE.read_text().splitlines():
        s = ln.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


# ─── Models ──────────────────────────────────────────────────────────
@dataclass
class Investor:
    email: str
    first_name: str = ""
    last_name: str = ""
    company: str = ""
    phone: str = ""
    source: str = ""
    target_zips: str = ""
    buyer_score: str = ""

    def filled_count(self) -> int:
        return sum(1 for f in (self.first_name, self.last_name, self.company,
                               self.phone, self.target_zips, self.buyer_score) if f)


# ─── Helpers ─────────────────────────────────────────────────────────
def norm_email(e: str) -> str:
    return (e or "").strip().lower()


def http_get(url: str, headers: dict, timeout: int = 30) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def http_post(url: str, data: bytes, headers: dict, timeout: int = 30) -> tuple[int, str]:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def sf_login() -> tuple[str, str] | None:
    user = os.environ.get("SF_USERNAME")
    pw = os.environ.get("SF_PASSWORD")
    tok = os.environ.get("SF_SECURITY_TOKEN")
    domain = os.environ.get("SF_DOMAIN", "johnsonshomes2.my")
    if not (user and pw and tok):
        print("✗ SF env vars not set. Skipping SF source.")
        return None
    soap = f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:urn="urn:partner.soap.sforce.com">
  <soapenv:Body>
    <urn:login>
      <urn:username>{user}</urn:username>
      <urn:password>{pw}{tok}</urn:password>
    </urn:login>
  </soapenv:Body>
</soapenv:Envelope>"""
    code, body = http_post(
        f"https://{domain}.salesforce.com/services/Soap/u/58.0",
        soap.encode(),
        {"Content-Type": "text/xml", "SOAPAction": "login"},
    )
    if code != 200:
        print(f"✗ SF login HTTP {code}")
        return None
    sid = re.search(r"<sessionId>(.+?)</sessionId>", body)
    srv = re.search(r"<serverUrl>(.+?)</serverUrl>", body)
    if not (sid and srv):
        return None
    inst = re.search(r"(https://[^/]+)", srv.group(1)).group(1)
    return sid.group(1), inst


def sf_query_all(session: str, instance: str, soql: str) -> list[dict]:
    """Paginate through all results."""
    url = f"{instance}/services/data/v58.0/query?q={urllib.parse.quote(soql)}"
    out: list[dict] = []
    while url:
        code, body = http_get(url, {"Authorization": f"Bearer {session}"})
        if code != 200:
            print(f"✗ SOQL failed: {body[:200]}")
            break
        data = json.loads(body)
        out.extend(data.get("records", []))
        nxt = data.get("nextRecordsUrl")
        url = f"{instance}{nxt}" if nxt else None
    return out


# ─── Sources ─────────────────────────────────────────────────────────
def from_salesforce(session: str, instance: str) -> list[Investor]:
    """Pull CHF buyer Contacts."""
    soql = (
        "SELECT FirstName, LastName, Email, Phone, Account.Name, "
        "       Buyer_Target_Zips__c, Buyer_Score__c, LeadSource "
        "FROM Contact "
        "WHERE Email != null "
        "AND LeadSource IN ('CheapHomesFLA_LandingPage', "
        "                   'Email Engagement (auto-created)')"
    )
    rows = sf_query_all(session, instance, soql)
    out: list[Investor] = []
    for r in rows:
        email = norm_email(r.get("Email"))
        if not email:
            continue
        acct = (r.get("Account") or {}).get("Name", "") if r.get("Account") else ""
        out.append(Investor(
            email=email,
            first_name=r.get("FirstName") or "",
            last_name=r.get("LastName") or "",
            company=acct,
            phone=r.get("Phone") or "",
            source=f"SF:{r.get('LeadSource')}",
            target_zips=r.get("Buyer_Target_Zips__c") or "",
            buyer_score=str(int(r["Buyer_Score__c"])) if r.get("Buyer_Score__c") else "",
        ))
    print(f"  ✓ Salesforce: {len(out)} investor Contacts")
    return out


def from_senders_file() -> list[Investor]:
    """Parse senders.txt — known wholesalers who email cheaphomesfla.
    They tend to own LLCs and would opt into the buy-box list."""
    p = SCRIPT_DIR / "senders.txt"
    if not p.exists():
        print("  ⚠️  senders.txt not found")
        return []
    out: list[Investor] = []
    pat = re.compile(r"^(.*?)\s*<([^>]+)>\s*$")
    for line in p.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = pat.match(s)
        if not m:
            continue
        display, email = m.group(1).strip(), norm_email(m.group(2))
        if not email:
            continue
        # Split display name into first/last/company (best-effort)
        first = last = company = ""
        if "," in display:
            company, person = [x.strip() for x in display.split(",", 1)]
            parts = person.split()
            if parts:
                first = parts[0]
                last = " ".join(parts[1:])
        else:
            parts = display.split()
            if len(parts) == 1:
                company = parts[0]
            elif len(parts) >= 2:
                first = parts[0]
                last = " ".join(parts[1:])
        out.append(Investor(
            email=email,
            first_name=first,
            last_name=last,
            company=company,
            source="senders.txt (CHF wholesaler)",
        ))
    print(f"  ✓ senders.txt: {len(out)} wholesaler emails")
    return out


def from_manual_csv() -> list[Investor]:
    p = SCRIPT_DIR / "data" / "investor_additions.csv"
    if not p.exists():
        return []
    out: list[Investor] = []
    with open(p, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            email = norm_email(row.get("email"))
            if not email:
                continue
            out.append(Investor(
                email=email,
                first_name=row.get("first_name", ""),
                last_name=row.get("last_name", ""),
                company=row.get("company", ""),
                phone=row.get("phone", ""),
                source=row.get("source", "manual"),
            ))
    print(f"  ✓ manual additions: {len(out)} rows")
    return out


# ─── Dedup ───────────────────────────────────────────────────────────
def dedup(records: list[Investor]) -> list[Investor]:
    by_email: dict[str, Investor] = {}
    for r in records:
        existing = by_email.get(r.email)
        if not existing or r.filled_count() > existing.filled_count():
            by_email[r.email] = r
        else:
            # merge missing fields into existing
            for f in ("first_name", "last_name", "company", "phone",
                      "target_zips", "buyer_score"):
                if not getattr(existing, f) and getattr(r, f):
                    setattr(existing, f, getattr(r, f))
    return list(by_email.values())


# ─── Output ──────────────────────────────────────────────────────────
def write_csv(records: list[Investor], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Constant Contact-friendly columns: Email, First Name, Last Name,
    # Company Name, Phone — no extras CC won't recognize on import.
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Email", "First Name", "Last Name", "Company Name",
                    "Phone", "Source", "Buyer Score", "Target Zips"])
        for r in sorted(records, key=lambda x: (x.last_name.lower(), x.email)):
            w.writerow([r.email, r.first_name, r.last_name, r.company,
                        r.phone, r.source, r.buyer_score, r.target_zips])
    print(f"✓ wrote {len(records)} unique investors → {out_path}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="Skip Salesforce; only use senders.txt + manual additions")
    args = p.parse_args()

    print("Building investor list from all sources...")
    records: list[Investor] = []

    if not args.dry_run:
        auth = sf_login()
        if auth:
            session, instance = auth
            print(f"✓ SF connected: {instance}")
            records.extend(from_salesforce(session, instance))

    records.extend(from_senders_file())
    records.extend(from_manual_csv())

    print()
    print(f"Total raw records: {len(records)}")
    cleaned = dedup(records)
    print(f"After dedup:       {len(cleaned)}")
    print()

    out_repo    = SCRIPT_DIR / "data" / "investor_contacts.csv"
    out_desktop = Path.home() / "Desktop" / "investor_contacts_clean.csv"
    write_csv(cleaned, out_repo)
    try:
        shutil.copyfile(out_repo, out_desktop)
        print(f"✓ also at {out_desktop}")
    except Exception as e:
        print(f"⚠️  Desktop copy failed: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
