#!/usr/bin/env python3
"""
twilio_delivery_monitor.py — closes alert-map gap "d"
─────────────────────────────────────────────────────
Pulls Twilio Messages API for the last 24 hours, computes per-Twilio-number
delivery rate, and alerts Chris if:

  - Any number's delivered rate < 90% (carriers blocking — A2P 10DLC issue)
  - Any number has > 5% failed/undelivered (junk-fold + carrier block mix)
  - Total daily volume drops > 50% vs 7-day average (campaign script crash)

Why this matters: Twilio's outbound API returns "queued" or "sent" for
messages that carriers later silently drop. You'd see green logs in your
campaign script and zero actual deliveries. This catches that.

Designed for Railway hourly cron: "30 * * * *"  (every hour at :30,
offset from cloud_health_check at :00 to spread the API load).

Run locally:
    cd ~/dealmatcher && python3 tools/twilio_delivery_monitor.py
    cd ~/dealmatcher && python3 tools/twilio_delivery_monitor.py --report  # always print
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
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


# ─── Thresholds ──────────────────────────────────────────────────────
DELIVERY_RATE_WARN  = 0.90   # < 90% delivered = warn
DELIVERY_RATE_RED   = 0.75   # < 75% delivered = critical
FAILED_RATIO_WARN   = 0.05   # > 5% failed/undelivered = warn
VOLUME_DROP_RATIO   = 0.50   # today vs 7d avg


# ─── HTTP helpers (stdlib only) ──────────────────────────────────────
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


# ─── Twilio Messages API ─────────────────────────────────────────────
def fetch_messages(sid: str, token: str, since_iso: str,
                   page_size: int = 1000) -> list[dict]:
    """Paginate Messages API. Returns list of message records."""
    auth = b64encode(f"{sid}:{token}".encode()).decode()
    out: list[dict] = []
    url = (f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
           f"?DateSent%3E={urllib.parse.quote(since_iso)}"
           f"&PageSize={page_size}")
    while url:
        code, body = http_get(url, {"Authorization": f"Basic {auth}"})
        if code != 200:
            print(f"✗ Twilio API HTTP {code}: {body[:300]}")
            break
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            print(f"✗ Twilio API returned non-JSON: {body[:300]}")
            break
        out.extend(data.get("messages", []))
        nxt = data.get("next_page_uri")
        url = f"https://api.twilio.com{nxt}" if nxt else None
    return out


# ─── Analysis ────────────────────────────────────────────────────────
def analyze(messages: list[dict]) -> dict:
    """Group by from_number; compute delivery counts."""
    # Twilio status values:
    #   queued, sending, sent, delivered, undelivered, failed, accepted, scheduled
    # "delivered" = carrier confirmed
    # "undelivered" / "failed" = carrier rejected
    # "sent" without "delivered" = unconfirmed (typical for ~5-10% legit traffic)
    by_from: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    total = 0
    for m in messages:
        # Only outbound messages (we sent them) — skip inbound
        if m.get("direction") not in ("outbound-api", "outbound-call",
                                       "outbound-reply"):
            continue
        from_num = m.get("from") or "(unknown)"
        status = m.get("status") or "unknown"
        by_from[from_num][status] += 1
        by_from[from_num]["total"] += 1
        total += 1
    return {"by_from": dict(by_from), "total": total}


# ─── Salesforce (for volume baseline) ────────────────────────────────
def fetch_volume_baseline() -> float | None:
    """Return 7-day average outbound SMS count from SF Tasks (JB-SMS-* tags)."""
    try:
        from urllib.parse import quote
        # Use simple SF SOAP login + REST
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
        import re
        sid = re.search(r"<sessionId>(.+?)</sessionId>", body)
        srv = re.search(r"<serverUrl>(.+?)</serverUrl>", body)
        if not (sid and srv):
            return None
        inst = re.search(r"(https://[^/]+)", srv.group(1)).group(1)
        soql = ("SELECT CreatedDate FROM Task WHERE Subject LIKE 'JB-SMS-%' "
                "AND CreatedDate = LAST_N_DAYS:7")
        url = f"{inst}/services/data/v58.0/query?q={quote(soql)}"
        code, body = http_get(url, {"Authorization": f"Bearer {sid.group(1)}"})
        if code != 200:
            return None
        recs = json.loads(body).get("records", [])
        today = dt.date.today().isoformat()
        by_day: dict[str, int] = {}
        for r in recs:
            d = r["CreatedDate"][:10]
            by_day[d] = by_day.get(d, 0) + 1
        other = [c for d, c in by_day.items() if d != today]
        if not other:
            return None
        return sum(other) / len(other)
    except Exception:
        return None


# ─── Alert dispatch ──────────────────────────────────────────────────
def send_alert(subject: str, body: str) -> None:
    key = os.environ.get("SENDGRID_API_KEY")
    to = os.environ.get("ALERT_TO", "info@johnsonbuys.com")
    if not key:
        print("⚠️  No SENDGRID_API_KEY — printing to stdout:\n\n", body)
        return
    payload = {
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": "info@johnsonbuys.com", "name": "Twilio Monitor"},
        "subject": subject,
        "content": [{"type": "text/plain", "value": body}],
    }
    code, resp = http_post(
        "https://api.sendgrid.com/v3/mail/send",
        json.dumps(payload).encode(),
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    print(f"{'✓' if 200 <= code < 300 else '✗'} alert email HTTP {code}")


# ─── Main ────────────────────────────────────────────────────────────
def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--report", action="store_true",
                   help="Always print full report; never email")
    args = p.parse_args()

    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    if not (sid and token):
        print("✗ TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN required")
        return 1

    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"Fetching Twilio messages since {since}...")
    msgs = fetch_messages(sid, token, since)
    print(f"  {len(msgs)} outbound messages in last 24h")
    if not msgs:
        print("ℹ️  No outbound traffic — likely Sunday or campaigns paused")
        return 0

    result = analyze(msgs)
    alerts: list[tuple[str, str, str]] = []   # (sev, title, detail)

    # ── Per-from-number checks ──
    print()
    print("Per-Twilio-number delivery rates:")
    for from_num, stats in result["by_from"].items():
        total = stats.get("total", 0)
        delivered = stats.get("delivered", 0)
        failed = stats.get("failed", 0) + stats.get("undelivered", 0)
        sent_unconfirmed = stats.get("sent", 0)
        delivered_rate = delivered / total if total else 0
        failed_rate = failed / total if total else 0

        line = (f"  {from_num}: {total} total | "
                f"delivered={delivered} ({delivered_rate*100:.1f}%) | "
                f"failed/undelivered={failed} ({failed_rate*100:.1f}%) | "
                f"sent-unconfirmed={sent_unconfirmed}")
        print(line)

        if delivered_rate < DELIVERY_RATE_RED:
            alerts.append(("🔴", f"{from_num}: delivery rate {delivered_rate*100:.0f}%",
                           f"Only {delivered}/{total} delivered. CARRIER BLOCK likely. "
                           "Check Twilio → Insights → Errors. May need new A2P 10DLC registration."))
        elif delivered_rate < DELIVERY_RATE_WARN:
            alerts.append(("🟡", f"{from_num}: delivery rate {delivered_rate*100:.0f}%",
                           f"{delivered}/{total} delivered (target ≥90%). "
                           "Monitor — may need new sending number or campaign reset."))

        if failed_rate > FAILED_RATIO_WARN:
            alerts.append(("🟡", f"{from_num}: {failed_rate*100:.0f}% failed/undelivered",
                           f"{failed} of {total}. Common causes: invalid numbers, "
                           "carrier rejection, A2P 10DLC throttling."))

    # ── Volume drop check ──
    baseline = fetch_volume_baseline()
    if baseline and baseline > 10:
        ratio = result["total"] / baseline
        if ratio < VOLUME_DROP_RATIO:
            alerts.append(("🟡", f"SMS volume {result['total']} vs 7d avg {baseline:.0f}",
                           "Outbound volume well below average. Campaign script may have "
                           "crashed silently."))

    print()
    print("─" * 60)
    if alerts:
        body_lines = [f"🚨 Twilio Delivery Monitor — {len(alerts)} alert(s)\n"]
        for sev, title, detail in alerts:
            body_lines.append(f"{sev} {title}")
            body_lines.append(f"   {detail}")
            body_lines.append("")
        body_lines.append("\nAction:")
        body_lines.append("1. Open Twilio Console → Insights → Errors")
        body_lines.append("2. Check A2P 10DLC campaign approval status")
        body_lines.append("3. If carrier blocks confirmed, request a new sending number")
        body = "\n".join(body_lines)
        print(body)
        if not args.report:
            send_alert(f"🚨 Twilio delivery alert ({len(alerts)})", body)
    else:
        print("✅ All Twilio delivery checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
