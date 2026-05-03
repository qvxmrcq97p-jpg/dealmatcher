#!/usr/bin/env python3
"""
sf_smoke_test.py — confirms the whole stack can talk to Salesforce
─────────────────────────────────────────────────────────────────
Run this BEFORE deploying anything to Railway to catch problems early:

  - SOAP login works (SF_USERNAME / SF_PASSWORD / SF_SECURITY_TOKEN)
  - REST queries work (Lead, Contact, Task)
  - All 4 custom fields exist + are FLS-readable for this user
  - SOQL queries used by each cron script return without error
  - Twilio + SendGrid credentials work

If anything fails, the error tells you exactly what to fix and where.

Run:
    cd ~/dealmatcher && python3 tools/sf_smoke_test.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from base64 import b64encode
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


GREEN = "\033[0;32m"
RED   = "\033[0;31m"
YEL   = "\033[0;33m"
RST   = "\033[0m"


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


def ok(msg: str) -> None:    print(f"  {GREEN}✓{RST} {msg}")
def fail(msg: str) -> None:  print(f"  {RED}✗{RST} {msg}")
def warn(msg: str) -> None:  print(f"  {YEL}⚠{RST} {msg}")
def section(msg: str) -> None: print(f"\n─── {msg} ───")


def main() -> int:
    fails = 0

    # ── Env vars present ──
    section("Environment variables")
    required = [
        "SF_USERNAME", "SF_PASSWORD", "SF_SECURITY_TOKEN",
        "SENDGRID_API_KEY", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN",
    ]
    optional = ["SF_DOMAIN", "TWILIO_FROM", "ALERT_TO", "ALERT_SMS_TO"]
    for k in required:
        if os.environ.get(k):
            ok(f"{k} set")
        else:
            fail(f"{k} MISSING")
            fails += 1
    for k in optional:
        if os.environ.get(k):
            ok(f"{k} set")
        else:
            warn(f"{k} not set (optional, defaults will apply)")

    if fails:
        print(f"\n{RED}✗ Fix env vars first; aborting{RST}")
        return 1

    # ── SF SOAP login ──
    section("Salesforce login")
    user = os.environ["SF_USERNAME"]
    domain = os.environ.get("SF_DOMAIN", "johnsonshomes2.my")
    soap = f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:urn="urn:partner.soap.sforce.com">
  <soapenv:Body><urn:login>
    <urn:username>{user}</urn:username>
    <urn:password>{os.environ['SF_PASSWORD']}{os.environ['SF_SECURITY_TOKEN']}</urn:password>
  </urn:login></soapenv:Body>
</soapenv:Envelope>"""
    code, body = http("POST", f"https://{domain}.salesforce.com/services/Soap/u/58.0",
        {"Content-Type": "text/xml", "SOAPAction": "login"}, soap.encode())
    if code != 200:
        fail(f"SOAP login HTTP {code}\n     {body[:300]}")
        return 1
    sid = re.search(r"<sessionId>(.+?)</sessionId>", body)
    srv = re.search(r"<serverUrl>(.+?)</serverUrl>", body)
    if not (sid and srv):
        fail("SOAP login response missing sessionId")
        return 1
    session = sid.group(1)
    instance = re.search(r"(https://[^/]+)", srv.group(1)).group(1)
    ok(f"Logged in as {user}")
    ok(f"Instance: {instance}")

    def q(soql):
        code, body = http("GET",
            f"{instance}/services/data/v58.0/query?q={urllib.parse.quote(soql)}",
            {"Authorization": f"Bearer {session}"})
        return code, body

    # ── REST queries ──
    section("REST queries")
    code, body = q("SELECT COUNT() FROM Lead")
    if code == 200:
        n = json.loads(body).get("totalSize", "?")
        ok(f"Lead query: {n} total Leads")
    else:
        fail(f"Lead query HTTP {code}: {body[:200]}")
        fails += 1

    code, body = q("SELECT COUNT() FROM Contact")
    if code == 200:
        ok(f"Contact query: {json.loads(body).get('totalSize', '?')} total Contacts")
    else:
        fail(f"Contact query HTTP {code}: {body[:200]}")
        fails += 1

    code, body = q("SELECT COUNT() FROM Task WHERE CreatedDate = LAST_N_DAYS:7")
    if code == 200:
        ok(f"Task query: {json.loads(body).get('totalSize', '?')} Tasks last 7 days")
    else:
        fail(f"Task query HTTP {code}: {body[:200]}")
        fails += 1

    # ── Custom field FLS check ──
    section("Custom field access (FLS)")
    custom_fields = [
        ("Contact", "Buyer_Score__c"),
        ("Contact", "Buyer_Target_Zips__c"),
        ("Contact", "Top_Buyer_Zips__c"),
        ("Lead", "Seller_Score__c"),
    ]
    for obj, field in custom_fields:
        code, body = q(f"SELECT {field} FROM {obj} LIMIT 1")
        if code == 200:
            ok(f"{obj}.{field}: readable")
        elif "INVALID_FIELD" in body or "No such column" in body:
            fail(f"{obj}.{field}: FIELD MISSING — run tools/add_sf_fields_v2.py")
            fails += 1
        elif "INSUFFICIENT_ACCESS" in body:
            fail(f"{obj}.{field}: FLS BLOCKED — run tools/add_sf_fields_v2.py to grant")
            fails += 1
        else:
            fail(f"{obj}.{field}: HTTP {code} — {body[:200]}")
            fails += 1

    # ── Cron-script SOQL queries ──
    section("Cron-script SOQL (probe each scheduled job)")
    cron_queries = [
        ("watchdog/launchd check",
         "SELECT COUNT() FROM Task WHERE Subject LIKE 'JB-%' AND CreatedDate = TODAY"),
        ("daily_kpi pipeline counts",
         "SELECT COUNT() FROM Lead WHERE Status = 'Sent Contract'"),
        ("hot_lead_alert engagement scan",
         "SELECT COUNT() FROM Task WHERE (Subject LIKE 'Email-Open%' OR Subject LIKE 'Email-Click%') AND CreatedDate = LAST_N_DAYS:7"),
        ("cloud_health PPL volume",
         "SELECT COUNT() FROM Lead WHERE LeadSource = 'Property Leads PPL' AND CreatedDate = LAST_N_DAYS:7"),
        ("cloud_health volume baseline",
         "SELECT COUNT() FROM Lead WHERE CreatedDate = LAST_N_DAYS:7"),
    ]
    for label, soql in cron_queries:
        code, body = q(soql)
        if code == 200:
            n = json.loads(body).get("totalSize", "?")
            ok(f"{label}: {n} records")
        else:
            fail(f"{label}: HTTP {code} — {body[:200]}")
            fails += 1

    # ── Twilio creds ──
    section("Twilio credentials")
    sid = os.environ["TWILIO_ACCOUNT_SID"]
    auth = b64encode(f"{sid}:{os.environ['TWILIO_AUTH_TOKEN']}".encode()).decode()
    code, body = http("GET",
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json",
        {"Authorization": f"Basic {auth}"})
    if code == 200:
        d = json.loads(body)
        ok(f"Twilio account active: {d.get('friendly_name')}")
    else:
        fail(f"Twilio HTTP {code}: {body[:200]}")
        fails += 1

    # ── SendGrid creds ──
    section("SendGrid credentials")
    code, body = http("GET",
        "https://api.sendgrid.com/v3/scopes",
        {"Authorization": f"Bearer {os.environ['SENDGRID_API_KEY']}"})
    if code == 200:
        scopes = json.loads(body).get("scopes", [])
        ok(f"SendGrid API key valid ({len(scopes)} scopes granted)")
    else:
        fail(f"SendGrid HTTP {code}: {body[:200]}")
        fails += 1

    # ── Summary ──
    print()
    if fails == 0:
        print(f"{GREEN}═══ ALL SMOKE TESTS PASSED ═══{RST}")
        print("Stack is ready for Railway deploy.")
        return 0
    else:
        print(f"{RED}═══ {fails} FAILURE(S) ═══{RST}")
        print("Fix above before deploying. See docs/RUNBOOK.md for paste-the-fix.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
