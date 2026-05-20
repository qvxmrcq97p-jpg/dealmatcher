#!/usr/bin/env python3
"""
capture_inquiries.py — auto-capture buyer form-fill inquiries into Salesforce.

Form submissions on cheaphomesfla.com generate a "BUYER INQUIRY" notification
email that lands in the **Buyer Inquiries** folder of info@cheaphomesFLA.com.
Each one is a warm buyer telling you exactly which property they want. This
reads those notifications and upserts a Salesforce Contact for each — logging
the property they inquired about — so none of that buyer data is lost.

Reuses the scraper's Microsoft Graph auth (no new credentials).

SAFE BY DEFAULT: runs in DRY-RUN unless you pass --send. Dry-run prints exactly
what it WOULD write to Salesforce so you can verify the parsing first.

Usage:
    python3 tools/capture_inquiries.py            # DRY-RUN — parse + print only
    python3 tools/capture_inquiries.py --send     # actually upsert into Salesforce
    python3 tools/capture_inquiries.py --since 2026-05-19T00:00:00Z   # override window

State: tools/.inquiry_capture_state.json tracks the last processed time so the
same inquiry is never captured twice.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# ── env (same file the scraper uses) ─────────────────────────────────
ENV_FILE = Path.home() / "dealmatcher" / ".env.cheaphomesfla"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

import requests  # noqa: E402

MAILBOX = "info@cheaphomesFLA.com"
FOLDER_NAME_CANDIDATES = ["Buyer Inquiries", "Buyer Inquiry", "Inquiries",
                          "Buyer Inquires", "BuyerInquiries"]
STATE_FILE = REPO / "tools" / ".inquiry_capture_state.json"
LEADSOURCE = "CheapHomesFLA_LandingPage"


# ── Graph: find folder + pull messages ───────────────────────────────
def graph_token() -> str:
    import cheaphomesfla_scraper as s
    return s.graph_access_token()


def find_inquiry_folder_id(token: str) -> str | None:
    """Locate the Buyer Inquiries mail folder by display name."""
    url = f"https://graph.microsoft.com/v1.0/users/{MAILBOX}/mailFolders"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"$top": 100, "$select": "id,displayName"}
    folders = []
    while url:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        folders.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
        params = {}
    by_name = {f["displayName"].lower(): f["id"] for f in folders}
    for cand in FOLDER_NAME_CANDIDATES:
        if cand.lower() in by_name:
            return by_name[cand.lower()]
    # Loose contains-match fallback
    for name, fid in by_name.items():
        if "inquir" in name:
            return fid
    print(f"⚠️  Could not find a Buyer Inquiries folder. Folders present: "
          f"{sorted(by_name.keys())}")
    return None


def fetch_inquiries(token: str, folder_id: str, since_iso: str | None) -> list[dict]:
    url = f"https://graph.microsoft.com/v1.0/users/{MAILBOX}/mailFolders/{folder_id}/messages"
    headers = {"Authorization": f"Bearer {token}"}
    params: dict = {
        "$top": 50,
        "$select": "id,subject,body,bodyPreview,receivedDateTime",
        "$orderby": "receivedDateTime desc",
    }
    if since_iso:
        params["$filter"] = f"receivedDateTime gt {since_iso}"
    out = []
    while url:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        out.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
        params = {}
    return out


# ── Parse one inquiry email into structured fields ───────────────────
def _text(msg: dict) -> str:
    body = (msg.get("body", {}) or {}).get("content") or msg.get("bodyPreview") or ""
    # strip tags, collapse whitespace but keep line structure
    body = re.sub(r"<\s*br\s*/?>", "\n", body, flags=re.I)
    body = re.sub(r"</\s*(p|div|tr|li|h[1-6])\s*>", "\n", body, flags=re.I)
    body = re.sub(r"<[^>]+>", " ", body)
    body = body.replace("&nbsp;", " ").replace("&amp;", "&")
    lines = [ln.strip() for ln in body.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _field(text: str, label: str) -> str | None:
    # "Email\tvze2kq3r@verizon.net" or "Email: foo" or "Email foo"
    m = re.search(rf"{label}\s*[:\t]?\s*(.+)", text, flags=re.I)
    if m:
        val = m.group(1).strip()
        # cut at next label if it ran together
        val = re.split(r"\s{2,}", val)[0].strip()
        return val or None
    return None


def parse_inquiry(msg: dict) -> dict | None:
    text = _text(msg)
    if "buyer inquiry" not in text.lower():
        return None

    email = _field(text, "Email")
    if email:
        em = re.search(r"[\w.\-+]+@[\w.\-]+\.\w+", email)
        email = em.group(0) if em else None
    phone = _field(text, "Phone")
    finance = _field(text, "Finance")
    timeline = _field(text, "Timeline")
    submitted = _field(text, "Submitted")

    # Name + property are the two lines right after "BUYER INQUIRY"
    lines = text.splitlines()
    name = None
    prop = None
    for i, ln in enumerate(lines):
        if "buyer inquiry" in ln.lower():
            if i + 1 < len(lines):
                name = lines[i + 1].strip()
            if i + 2 < len(lines):
                cand = lines[i + 2].strip()
                # property line usually contains a digit (street number) + comma
                if re.search(r"\d", cand) and ("," in cand or re.search(r"\b(ave|st|dr|rd|ct|ln|blvd|ter|pl|way|cir)\b", cand, re.I)):
                    prop = cand
            break

    if not email or not name:
        return None

    parts = name.split()
    first = parts[0].title() if parts else name
    last = " ".join(parts[1:]).title() if len(parts) > 1 else "(none)"

    return {
        "first": first, "last": last, "email": email, "phone": phone,
        "finance": finance, "timeline": timeline, "property": prop,
        "submitted": submitted, "received": msg.get("receivedDateTime"),
    }


# ── County inference from a property line ────────────────────────────
def county_for_property(prop: str | None) -> str | None:
    if not prop:
        return None
    import cheaphomesfla_scraper as s  # noqa
    import deal_matcher as dm
    zm = re.search(r"\b(3\d{4})\b", prop)
    if zm:
        try:
            return dm.county_from_zip(zm.group(1))
        except Exception:
            return None
    return None


# ── Salesforce upsert ────────────────────────────────────────────────
def sf_login():
    from simple_salesforce import Salesforce
    return Salesforce(
        username=os.environ["SF_USERNAME"],
        password=os.environ["SF_PASSWORD"],
        security_token=os.environ["SF_SECURITY_TOKEN"],
        domain=os.environ.get("SF_DOMAIN", "johnsonshomes2.my"),
    )


def upsert_contact(sf, rec: dict, existing_fields: set) -> str:
    note = f"Form inquiry on {rec.get('property') or '(property unspecified)'}"
    if rec.get("finance") or rec.get("timeline"):
        note += f" · finance={rec.get('finance')} timeline={rec.get('timeline')}"
    county = county_for_property(rec.get("property"))

    fields = {
        "FirstName": rec["first"], "LastName": rec["last"],
        "Email": rec["email"], "LeadSource": LEADSOURCE,
        "HasOptedOutOfEmail": False,
    }
    if rec.get("phone"):
        fields["Phone"] = rec["phone"]
    if "Search_Description__c" in existing_fields:
        fields["Search_Description__c"] = note[:255]
    if county and "Buyer_Counties_of_Interest__c" in existing_fields:
        fields["Buyer_Counties_of_Interest__c"] = county

    safe = rec["email"].replace("'", "\\'")
    res = sf.query(f"SELECT Id FROM Contact WHERE Email = '{safe}'")
    if res["totalSize"] > 0:
        cid = res["records"][0]["Id"]
        sf.Contact.update(cid, fields)
        return f"updated {cid}"
    out = sf.Contact.create(fields)
    return f"created {out.get('id')}" if out.get("success") else f"FAILED {out}"


def load_state() -> str | None:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text()).get("last_iso")
        except Exception:
            return None
    return None


def save_state(iso: str) -> None:
    STATE_FILE.write_text(json.dumps({"last_iso": iso}, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="actually write to Salesforce")
    ap.add_argument("--since", default=None, help="ISO time override")
    ap.add_argument("--lookback-hours", type=int, default=48,
                    help="if no state, how far back to look (default 48h)")
    args = ap.parse_args()

    since = args.since or load_state()
    if not since:
        since = (datetime.now(timezone.utc) - timedelta(hours=args.lookback_hours)).isoformat()

    print(f"{'SEND' if args.send else 'DRY-RUN'} · pulling Buyer Inquiries since {since}")
    token = graph_token()
    folder_id = find_inquiry_folder_id(token)
    if not folder_id:
        return 1
    msgs = fetch_inquiries(token, folder_id, since)
    print(f"Found {len(msgs)} message(s) in the folder window.\n")

    parsed = []
    for m in msgs:
        rec = parse_inquiry(m)
        if rec:
            parsed.append(rec)

    if not parsed:
        print("No parseable inquiries. Nothing to do.")
        return 0

    sf = existing = None
    if args.send:
        sf = sf_login()
        existing = {f["name"] for f in sf.Contact.describe()["fields"]}

    for rec in parsed:
        county = county_for_property(rec.get("property"))
        line = (f"  {rec['first']} {rec['last']} <{rec['email']}> "
                f"ph={rec.get('phone')} · property={rec.get('property')} "
                f"· county={county or '(statewide)'}")
        if args.send:
            result = upsert_contact(sf, rec, existing)
            print(line + f"  → {result}")
        else:
            print(line + "  → WOULD upsert (dry-run)")

    # Advance state to newest received time
    newest = max((m.get("receivedDateTime") for m in msgs if m.get("receivedDateTime")),
                 default=None)
    if newest and args.send:
        save_state(newest)
        print(f"\nState advanced to {newest}")
    elif not args.send:
        print(f"\n(DRY-RUN — state not advanced. Re-run with --send to capture for real.)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
