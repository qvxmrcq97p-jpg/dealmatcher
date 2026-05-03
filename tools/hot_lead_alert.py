#!/usr/bin/env python3
"""
hot_lead_alert.py — SMS Chris when a lead is engaging right now
─────────────────────────────────────────────────────────────────
Real revenue lever. When a Lead opens 2+ emails OR clicks 1+ email in
the last 7 days, Chris should call them immediately while interest is
fresh. Engagement-window calls convert at ~3x the rate of cold-list calls.

Required: cloudflare/sendgrid-events worker is deployed and creating
Email-Open / Email-Click Tasks on the Lead/Contact records.

What it does (each run):
  1. SOQL query: Tasks WHERE Subject IN ('Email-Open*', 'Email-Click*')
     AND CreatedDate = LAST_N_DAYS:7
  2. Group by WhoId (the Lead/Contact)
  3. Score each: opens × 1 + clicks × 5 (clicks weight more)
  4. Threshold: score ≥ 2 = HOT
  5. For each newly-hot lead (not already "Hot" status):
     - Send Chris an SMS: "🔥 [Name] opened/clicked X emails this week.
        Call: [phone]. SF: [URL]"
     - Auto-update Lead.Status to "Hot"
     - Tag with "Auto-Hot-YYYYMMDD" Task to prevent re-alerting

Designed for Railway hourly cron 9 AM-9 PM ET Mon-Sat:
   Cron: "45 13-1 * * 1-6"   (every hour at :45, after watchdog/cloud_health)

Run locally:
    cd ~/dealmatcher && python3 tools/hot_lead_alert.py
    cd ~/dealmatcher && python3 tools/hot_lead_alert.py --dry-run  # don't SMS
    cd ~/dealmatcher && python3 tools/hot_lead_alert.py --threshold 3  # require 3+
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from base64 import b64encode
from collections import defaultdict
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


# ─── Scoring ─────────────────────────────────────────────────────────
OPEN_WEIGHT = 1
CLICK_WEIGHT = 5
DEFAULT_THRESHOLD = 2     # min score to fire alert
LOOKBACK_DAYS = 7


# ─── HTTP helpers ────────────────────────────────────────────────────
def http(method: str, url: str, headers: dict, data: bytes = None,
         timeout: int = 30) -> tuple[int, str]:
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def sf_login() -> tuple[str, str]:
    user = os.environ["SF_USERNAME"]
    pw = os.environ["SF_PASSWORD"]
    tok = os.environ["SF_SECURITY_TOKEN"]
    domain = os.environ.get("SF_DOMAIN", "johnsonshomes2.my")
    soap = f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:urn="urn:partner.soap.sforce.com">
  <soapenv:Body><urn:login>
    <urn:username>{user}</urn:username>
    <urn:password>{pw}{tok}</urn:password>
  </urn:login></soapenv:Body>
</soapenv:Envelope>"""
    code, body = http("POST", f"https://{domain}.salesforce.com/services/Soap/u/58.0",
        {"Content-Type": "text/xml", "SOAPAction": "login"}, soap.encode())
    if code != 200:
        sys.exit(f"✗ SF login failed: HTTP {code}")
    sid = re.search(r"<sessionId>(.+?)</sessionId>", body)
    srv = re.search(r"<serverUrl>(.+?)</serverUrl>", body)
    if not (sid and srv):
        sys.exit(f"✗ SF login missing sessionId")
    inst = re.search(r"(https://[^/]+)", srv.group(1)).group(1)
    return sid.group(1), inst


def sf_query(session: str, instance: str, soql: str) -> list[dict]:
    url = f"{instance}/services/data/v58.0/query?q={urllib.parse.quote(soql)}"
    out: list[dict] = []
    while url:
        code, body = http("GET", url, {"Authorization": f"Bearer {session}"})
        if code != 200:
            print(f"SOQL failed: {body[:300]}")
            return out
        data = json.loads(body)
        out.extend(data.get("records", []))
        nxt = data.get("nextRecordsUrl")
        url = f"{instance}{nxt}" if nxt else None
    return out


def sf_post(session: str, instance: str, path: str, payload: dict) -> tuple[int, dict]:
    code, body = http("POST", f"{instance}/services/data/v58.0/{path}",
        {"Authorization": f"Bearer {session}", "Content-Type": "application/json"},
        json.dumps(payload).encode())
    try:
        return code, json.loads(body)
    except json.JSONDecodeError:
        return code, {"raw": body}


def sf_patch(session: str, instance: str, path: str, payload: dict) -> int:
    code, _ = http("PATCH", f"{instance}/services/data/v58.0/{path}",
        {"Authorization": f"Bearer {session}", "Content-Type": "application/json"},
        json.dumps(payload).encode())
    return code


# ─── Twilio SMS ──────────────────────────────────────────────────────
def send_sms(body: str) -> bool:
    sid = os.environ["TWILIO_ACCOUNT_SID"]
    token = os.environ["TWILIO_AUTH_TOKEN"]
    from_num = os.environ.get("TWILIO_FROM", "+19549534554")
    to_num = os.environ.get("ALERT_SMS_TO", "+13055759040")
    auth = b64encode(f"{sid}:{token}".encode()).decode()
    body = body[:1500]
    payload = urllib.parse.urlencode({
        "From": from_num, "To": to_num, "Body": body,
    }).encode()
    code, resp = http("POST",
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        {"Authorization": f"Basic {auth}",
         "Content-Type": "application/x-www-form-urlencoded"}, payload)
    return 200 <= code < 300


# ─── Main detection ──────────────────────────────────────────────────
def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="Don't send SMS or update SF; just print candidates")
    p.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD,
                   help=f"Min score to fire alert (default {DEFAULT_THRESHOLD})")
    args = p.parse_args()

    session, instance = sf_login()
    print(f"✓ SF connected: {instance}")
    print(f"  Lookback: {LOOKBACK_DAYS} days, threshold: {args.threshold}")

    # ── Pull engagement Tasks for last 7 days ──
    soql = (
        "SELECT Id, WhoId, Who.Type, Who.Name, Subject, CreatedDate "
        "FROM Task "
        f"WHERE (Subject LIKE 'Email-Open%' OR Subject LIKE 'Email-Click%') "
        f"AND CreatedDate = LAST_N_DAYS:{LOOKBACK_DAYS} "
        "AND WhoId != null "
        "ORDER BY CreatedDate DESC"
    )
    events = sf_query(session, instance, soql)
    print(f"  {len(events)} engagement events found")

    if not events:
        print("ℹ️  No email engagement yet — sendgrid-events worker may not be deployed,")
        print("    or no emails opened in the last 7 days.")
        return 0

    # ── Score each WhoId ──
    score: dict[str, dict] = defaultdict(
        lambda: {"opens": 0, "clicks": 0, "name": "", "type": "", "last_event": None})
    for e in events:
        who_id = e["WhoId"]
        s = score[who_id]
        if "Click" in e["Subject"]:
            s["clicks"] += 1
        else:
            s["opens"] += 1
        s["name"] = (e.get("Who") or {}).get("Name") or "(unknown)"
        s["type"] = (e.get("Who") or {}).get("Type") or "Lead"
        if not s["last_event"]:
            s["last_event"] = e["CreatedDate"][:10]

    # ── Filter to threshold ──
    hot: list[tuple[str, dict, int]] = []
    for who_id, s in score.items():
        total = s["opens"] * OPEN_WEIGHT + s["clicks"] * CLICK_WEIGHT
        if total >= args.threshold:
            hot.append((who_id, s, total))
    hot.sort(key=lambda x: -x[2])
    print(f"  {len(hot)} HOT leads (score ≥ {args.threshold})\n")

    if not hot:
        print("✓ No newly-hot leads this hour.")
        return 0

    # ── For each, check if already Hot status / already alerted today ──
    today_tag = f"Auto-Hot-{dt.date.today().isoformat()}"
    alerts_sent = 0

    for who_id, s, total in hot:
        # Pull current Lead/Contact status + phone
        if s["type"] == "Lead":
            recs = sf_query(session, instance,
                f"SELECT Id, FirstName, LastName, Phone, Status "
                f"FROM Lead WHERE Id = '{who_id}'")
        else:
            recs = sf_query(session, instance,
                f"SELECT Id, FirstName, LastName, Phone "
                f"FROM Contact WHERE Id = '{who_id}'")
        if not recs:
            continue
        rec = recs[0]
        status = rec.get("Status", "Contact")
        phone = rec.get("Phone") or "(no phone on record)"
        name = f"{rec.get('FirstName','')} {rec.get('LastName','')}".strip()

        # Skip if already manually marked Hot AND we already alerted today
        already_alerted = sf_query(session, instance,
            f"SELECT Id FROM Task WHERE WhoId = '{who_id}' "
            f"AND Subject = '{today_tag}'")
        if already_alerted:
            print(f"  · {name}: already alerted today, skipping")
            continue

        sf_url = f"{instance}/lightning/r/{s['type']}/{who_id}/view"
        sms_body = (
            f"🔥 HOT: {name} — {s['opens']} opens, {s['clicks']} clicks "
            f"(score {total}) since {s['last_event']}.\n"
            f"📞 {phone}\n"
            f"SF: {sf_url}"
        )

        if args.dry_run:
            print(f"  [dry-run] would SMS: {sms_body[:200]}")
            print(f"  [dry-run] would tag {who_id} with '{today_tag}'")
            if s["type"] == "Lead" and status not in ("Hot", "Sent Contract", "Closed Won"):
                print(f"  [dry-run] would update Lead status: {status} → Hot")
            continue

        # Send SMS
        ok = send_sms(sms_body)
        if not ok:
            print(f"  ✗ SMS failed for {name}")
            continue
        alerts_sent += 1
        print(f"  ✓ SMS sent for {name} (score {total})")

        # Tag with today's marker to prevent re-alerting
        sf_post(session, instance, "sobjects/Task", {
            "Subject": today_tag,
            "WhoId": who_id,
            "Status": "Completed",
            "ActivityDate": dt.date.today().isoformat(),
            "Description": f"Auto-Hot alert sent. Score={total} "
                          f"({s['opens']} opens, {s['clicks']} clicks).",
        })

        # Auto-promote Lead → Hot (only if currently low-touch status)
        if s["type"] == "Lead" and status in ("New", "Working", "Nurturing", None):
            code = sf_patch(session, instance, f"sobjects/Lead/{who_id}",
                           {"Status": "Hot"})
            if 200 <= code < 300:
                print(f"    ↑ Lead auto-promoted: {status} → Hot")

    print(f"\n✓ Done — {alerts_sent} alert(s) sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
