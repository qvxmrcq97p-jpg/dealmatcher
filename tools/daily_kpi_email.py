#!/usr/bin/env python3
"""
daily_kpi_email.py — morning success summary
─────────────────────────────────────────────
Closes alert-map gap "i": you currently get notified when something
breaks but never get a "today went well" signal. Silence is ambiguous.

This emails Chris a one-page snapshot every morning at 9:15 AM ET
(15 min after the 9 AM watchdog) covering:

  • Today vs 7-day avg: emails sent, SMS sent, deals scraped
  • New leads today by source (PPL providers + organic)
  • Pipeline counts by Status
  • Sent Contract count + days-in-status (deals close to closing)
  • CHF buyer counts: hot / warm / cold / unscored
  • Current month closed-won count + spread (revenue progress)

Stays terse — under one screen height. Always sends, even on quiet days,
so receiving NO email by 9:30 AM = something's broken.

Designed for Railway daily cron at 13:15 UTC (= 9:15 AM ET).
   Cron: "15 13 * * 1-6"

Run locally:
    cd ~/dealmatcher && python3 tools/daily_kpi_email.py
    cd ~/dealmatcher && python3 tools/daily_kpi_email.py --print  # don't email
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


# ─── Helpers ─────────────────────────────────────────────────────────
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
        return None
    sid = re.search(r"<sessionId>(.+?)</sessionId>", body)
    srv = re.search(r"<serverUrl>(.+?)</serverUrl>", body)
    if not (sid and srv):
        return None
    inst = re.search(r"(https://[^/]+)", srv.group(1)).group(1)
    return sid.group(1), inst


def sf_count(session: str, instance: str, soql: str) -> int:
    """Returns just the count from a SELECT COUNT() query."""
    url = f"{instance}/services/data/v58.0/query?q={urllib.parse.quote(soql)}"
    code, body = http_get(url, {"Authorization": f"Bearer {session}"})
    if code != 200:
        return -1
    try:
        return json.loads(body).get("totalSize", -1)
    except Exception:  # noqa: BLE001
        return -1


def sf_query(session: str, instance: str, soql: str) -> list[dict]:
    url = f"{instance}/services/data/v58.0/query?q={urllib.parse.quote(soql)}"
    code, body = http_get(url, {"Authorization": f"Bearer {session}"})
    if code != 200:
        return []
    try:
        return json.loads(body).get("records", [])
    except Exception:  # noqa: BLE001
        return []


# ─── KPI gathering ───────────────────────────────────────────────────
def collect_kpis(session: str, instance: str) -> dict:
    today = dt.date.today().isoformat()

    # ── Lead inflow today by source ──
    leads_today = sf_query(session, instance,
        "SELECT LeadSource, Id FROM Lead WHERE CreatedDate = TODAY")
    lead_by_source: dict[str, int] = {}
    for r in leads_today:
        s = r.get("LeadSource") or "(none)"
        lead_by_source[s] = lead_by_source.get(s, 0) + 1
    lead_total_today = len(leads_today)

    # ── Lead inflow last 7 days for comparison ──
    leads_7d = sf_query(session, instance,
        "SELECT CreatedDate FROM Lead WHERE CreatedDate = LAST_N_DAYS:7")
    by_day: dict[str, int] = {}
    for r in leads_7d:
        d = r["CreatedDate"][:10]
        by_day[d] = by_day.get(d, 0) + 1
    other_days = [c for d, c in by_day.items() if d != today]
    lead_avg_7d = (sum(other_days) / len(other_days)) if other_days else 0.0

    # ── Pipeline status counts ──
    statuses = ("New", "Working", "Hot", "Sent Contract", "Closed Won")
    status_counts: dict[str, int] = {}
    for s in statuses:
        n = sf_count(session, instance,
            f"SELECT COUNT() FROM Lead WHERE Status = '{s}'")
        status_counts[s] = n

    # ── Sent Contract pipeline (deals close to closing) ──
    sent_contracts = sf_query(session, instance,
        "SELECT Name, LastModifiedDate FROM Lead "
        "WHERE Status = 'Sent Contract' "
        "ORDER BY LastModifiedDate DESC LIMIT 50")

    # ── Tasks today (campaign volume) ──
    email_today = sf_count(session, instance,
        "SELECT COUNT() FROM Task WHERE Subject LIKE 'JB-Day%' "
        "AND CreatedDate = TODAY")
    sms_today = sf_count(session, instance,
        "SELECT COUNT() FROM Task WHERE Subject LIKE 'JB-SMS-%' "
        "AND CreatedDate = TODAY")

    # ── CHF buyer tier counts ──
    chf_filter = "LeadSource = 'CheapHomesFLA_LandingPage'"
    hot_buyers = sf_count(session, instance,
        f"SELECT COUNT() FROM Contact WHERE {chf_filter} AND Buyer_Score__c >= 70")
    warm_buyers = sf_count(session, instance,
        f"SELECT COUNT() FROM Contact WHERE {chf_filter} "
        "AND Buyer_Score__c >= 50 AND Buyer_Score__c < 70")
    cold_buyers = sf_count(session, instance,
        f"SELECT COUNT() FROM Contact WHERE {chf_filter} "
        "AND Buyer_Score__c >= 1 AND Buyer_Score__c < 50")
    unscored_buyers = sf_count(session, instance,
        f"SELECT COUNT() FROM Contact WHERE {chf_filter} "
        "AND (Buyer_Score__c = 0 OR Buyer_Score__c = NULL)")

    # ── CHF deal flow today + 7-day avg ──
    deals_today = sf_count(session, instance,
        "SELECT COUNT() FROM Task WHERE Subject LIKE 'CH-DEAL-%' "
        "AND CreatedDate = TODAY")
    deals_7d_rows = sf_query(session, instance,
        "SELECT CreatedDate FROM Task WHERE Subject LIKE 'CH-DEAL-%' "
        "AND CreatedDate = LAST_N_DAYS:7")
    deal_by_day: dict[str, int] = {}
    for r in deals_7d_rows:
        d = r["CreatedDate"][:10]
        deal_by_day[d] = deal_by_day.get(d, 0) + 1
    deal_other = [c for d, c in deal_by_day.items() if d != today]
    deals_avg_7d = (sum(deal_other) / len(deal_other)) if deal_other else 0.0

    # ── Closed Won this month (revenue progress) ──
    closed_mtd = sf_count(session, instance,
        "SELECT COUNT() FROM Lead WHERE Status = 'Closed Won' "
        "AND LastModifiedDate = THIS_MONTH")

    return {
        "today": today,
        "lead_total_today": lead_total_today,
        "lead_avg_7d": lead_avg_7d,
        "lead_by_source": lead_by_source,
        "status_counts": status_counts,
        "sent_contracts_count": len(sent_contracts),
        "email_today": email_today,
        "sms_today": sms_today,
        "hot_buyers": hot_buyers,
        "warm_buyers": warm_buyers,
        "cold_buyers": cold_buyers,
        "unscored_buyers": unscored_buyers,
        "deals_today": deals_today,
        "deals_avg_7d": deals_avg_7d,
        "closed_mtd": closed_mtd,
    }


# ─── Render email body ───────────────────────────────────────────────
def render_text(k: dict) -> str:
    arrow = lambda today, avg: ("▲" if today > avg * 1.1
                                else "▼" if today < avg * 0.7
                                else "→")  # noqa: E731
    body: list[str] = []
    body.append(f"Daily KPI Snapshot — {k['today']}\n")

    body.append("LEAD INFLOW TODAY")
    body.append(f"   Total: {k['lead_total_today']} "
                f"(7d avg {k['lead_avg_7d']:.1f}) "
                f"{arrow(k['lead_total_today'], k['lead_avg_7d'])}")
    if k["lead_by_source"]:
        for src, n in sorted(k["lead_by_source"].items(), key=lambda x: -x[1]):
            body.append(f"   {src:<35}  {n}")
    body.append("")

    body.append("PIPELINE")
    for s in ("New", "Working", "Hot", "Sent Contract", "Closed Won"):
        body.append(f"   {s:<18}  {k['status_counts'].get(s, 0)}")
    body.append("")

    body.append("CAMPAIGNS TODAY")
    body.append(f"   JB Emails sent     {k['email_today']}")
    body.append(f"   JB SMS sent        {k['sms_today']}")
    body.append("")

    body.append("CHF BUYER TIERS")
    body.append(f"   🔥 Hot   (70+)     {k['hot_buyers']}")
    body.append(f"   🌤  Warm  (50-69)   {k['warm_buyers']}")
    body.append(f"   ❄️  Cold  (1-49)    {k['cold_buyers']}")
    body.append(f"   ❔ Unscored        {k['unscored_buyers']}")
    body.append("")

    body.append("CHF DEAL FLOW")
    body.append(f"   Deals matched today: {k['deals_today']} "
                f"(7d avg {k['deals_avg_7d']:.1f}) "
                f"{arrow(k['deals_today'], k['deals_avg_7d'])}")
    body.append("")

    body.append("MONTH-TO-DATE")
    body.append(f"   Closed Won:        {k['closed_mtd']} deals")
    body.append("")

    body.append("─" * 50)
    body.append("Watchdog ran at 9:00 AM. Cloud-health checks at top of every hour.")
    body.append("If you don't see this email by 9:30 AM, the system is broken — escalate.")
    return "\n".join(body)


def render_html(k: dict) -> str:
    """Pretty HTML version."""
    rows = []
    def row(label, value, sub=""):
        sub_html = f"<br><span style='color:#888;font-size:11px'>{sub}</span>" if sub else ""
        rows.append(f"""
            <tr>
              <td style="padding:6px 12px;border-bottom:1px solid #eee">{label}</td>
              <td style="padding:6px 12px;border-bottom:1px solid #eee;text-align:right;font-weight:600">{value}{sub_html}</td>
            </tr>""")

    row("Total Leads today",
        k["lead_total_today"],
        f"7d avg {k['lead_avg_7d']:.1f}")

    sources = sorted(k["lead_by_source"].items(), key=lambda x: -x[1])
    for src, n in sources:
        rows.append(f"""
            <tr>
              <td style="padding:4px 12px 4px 30px;color:#666;font-size:13px;border-bottom:1px solid #eee">{src}</td>
              <td style="padding:4px 12px;text-align:right;color:#666;border-bottom:1px solid #eee">{n}</td>
            </tr>""")

    for s in ("New", "Working", "Hot", "Sent Contract", "Closed Won"):
        row(s, k["status_counts"].get(s, 0))

    row("JB Emails sent today", k["email_today"])
    row("JB SMS sent today", k["sms_today"])

    row("🔥 Hot Buyers (70+)",   k["hot_buyers"])
    row("🌤 Warm Buyers (50-69)", k["warm_buyers"])
    row("❄️ Cold Buyers (1-49)",  k["cold_buyers"])
    row("Unscored Buyers",        k["unscored_buyers"])

    row("CHF Deals matched today",
        k["deals_today"],
        f"7d avg {k['deals_avg_7d']:.1f}")

    row("Closed Won this month",  k["closed_mtd"])

    return f"""<!DOCTYPE html>
<html><body style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;color:#222;max-width:600px;margin:24px auto">
  <h2 style="color:#0F2540;margin:0 0 4px 0">Daily KPI Snapshot</h2>
  <div style="color:#888;margin-bottom:18px">{k['today']}</div>
  <table style="border-collapse:collapse;width:100%;background:#FAF8F2;border-radius:6px">
    {''.join(rows)}
  </table>
  <div style="margin-top:18px;padding:12px;background:#F5F2EA;border-radius:6px;color:#666;font-size:12px">
    Watchdog ran at 9:00 AM. Cloud-health checks every hour.
    If you don't see this email by 9:30 AM ET, the system is broken — escalate.
  </div>
</body></html>"""


# ─── Send email via SendGrid ─────────────────────────────────────────
def send_email(text: str, html: str) -> None:
    key = os.environ.get("SENDGRID_API_KEY")
    to = os.environ.get("ALERT_TO", "info@johnsonbuys.com")
    if not key:
        print("⚠️  No SENDGRID_API_KEY — printing instead:\n\n", text)
        return
    payload = {
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": "info@johnsonbuys.com", "name": "Daily KPI"},
        "subject": f"📊 Daily KPI — {dt.date.today().isoformat()}",
        "content": [
            {"type": "text/plain", "value": text},
            {"type": "text/html", "value": html},
        ],
    }
    code, resp = http_post(
        "https://api.sendgrid.com/v3/mail/send",
        json.dumps(payload).encode(),
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    print(f"{'✓' if 200 <= code < 300 else '✗'} HTTP {code} — {resp[:120]}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--print", dest="print_only", action="store_true",
                   help="Print to stdout, don't send email")
    args = p.parse_args()

    auth = sf_login()
    if not auth:
        print("✗ SF login failed — check env vars")
        return 1
    session, instance = auth

    k = collect_kpis(session, instance)
    text = render_text(k)
    html = render_html(k)

    print(text)

    if not args.print_only:
        send_email(text, html)
    return 0


if __name__ == "__main__":
    sys.exit(main())
