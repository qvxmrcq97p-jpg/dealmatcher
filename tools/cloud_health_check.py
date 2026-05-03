#!/usr/bin/env python3
"""
cloud_health_check.py — hourly multi-source health pinger
─────────────────────────────────────────────────────────
Closes alert gaps a, b, c, e from the Automation Map:

  a. Cloudflare Worker silently 500s
     → GETs each Worker's /health endpoint, alerts if non-200 or stale
       last_lead_at (default >24h)
  b. PPL provider stops sending
     → SOQL counts today's Leads per source vs 7-day average; alerts
       if today < 50% of average AND it's already past 6 PM
  c. SendGrid bounce / complaint rate
     → calls SendGrid stats API; alerts if bounce > 5% or complaint > 0.1%
  e. SF Lead inflow rate floor
     → total Lead creation today vs 7-day average; alerts if < 50%

Sends ONE email per run with all alerts collected (so a busy day doesn't
spam your inbox). Stays silent on green runs.

Designed to run on Railway as an hourly cron 9 AM — 9 PM ET on weekdays
(Mon-Sat — Sun the campaigns skip anyway). UTC cron equivalent:
   "0 13-1 * * 1-6"  →  every hour 9 AM ET to 9 PM ET, Mon-Sat

Run locally:
    cd ~/dealmatcher && python3 tools/cloud_health_check.py
    cd ~/dealmatcher && python3 tools/cloud_health_check.py --report   # always print, never email
    cd ~/dealmatcher && python3 tools/cloud_health_check.py --dry-run  # no SF calls
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent.parent

# Pull in .env.cheaphomesfla for local-dev runs (Railway uses real env vars)
ENV_FILE = SCRIPT_DIR / ".env.cheaphomesfla"
if ENV_FILE.exists():
    for ln in ENV_FILE.read_text().splitlines():
        s = ln.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


# ─── Configuration ───────────────────────────────────────────────────
WORKERS = [
    # (name, /health URL, max acceptable age in hours of last_lead_at)
    ("propertyleads-ppl-worker",
     "https://propertyleads-ppl-worker.cbfcalcio5.workers.dev/health",
     72),  # 72h: PPL providers can have multi-day quiet stretches
    ("motivatedsellers-ppl-worker",
     "https://motivatedsellers-ppl-worker.cbfcalcio5.workers.dev/health",
     72),
    ("whatsapp-worker",
     "https://whatsapp-worker.cbfcalcio5.workers.dev/health",
     24),  # WA traffic is daily; 24h silence = problem
]

PPL_VOLUME_FLOOR_RATIO = 0.50  # alert if today_count < 50% of 7d avg
SENDGRID_BOUNCE_THRESHOLD = 5.0       # %
SENDGRID_COMPLAINT_THRESHOLD = 0.1    # %
SF_LEAD_INFLOW_RATIO = 0.50           # alert if today total Leads < 50% of 7d avg
END_OF_DAY_HOUR = 18                  # only fire volume alerts after 6 PM ET


# ─── HTTP helpers (stdlib only — works on Railway zero-config) ───────
def http_get(url: str, headers: Optional[dict] = None, timeout: int = 12) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def http_post(url: str, data: bytes, headers: dict, timeout: int = 30) -> tuple[int, str]:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


# ─── Alert collector ─────────────────────────────────────────────────
class Alerts:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, str]] = []  # (severity, title, detail)
        self.oks: list[str] = []

    def red(self, t: str, d: str = "") -> None:    self.items.append(("🔴", t, d))
    def yellow(self, t: str, d: str = "") -> None: self.items.append(("🟡", t, d))
    def ok(self, msg: str) -> None:                self.oks.append(msg)

    def has_any(self) -> bool: return bool(self.items)
    def has_red(self) -> bool: return any(s == "🔴" for s, _, _ in self.items)

    def render(self) -> str:
        out: list[str] = []
        if self.items:
            out.append(f"🚨 CLOUD HEALTH — {len(self.items)} alert(s)\n")
            for sev, t, d in self.items:
                out.append(f"{sev} {t}")
                if d:
                    out.append(f"   {d}")
                out.append("")
        else:
            out.append("✅ All cloud-health checks passed.\n")
        if self.oks:
            out.append("\n--- Green checks ---")
            for m in self.oks:
                out.append(f"   ✓ {m}")
        return "\n".join(out)


# ─── Check 1: CF Worker /health endpoints ────────────────────────────
def check_workers(a: Alerts) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    for name, url, max_age_h in WORKERS:
        code, body = http_get(url)
        if code != 200:
            a.red(f"{name}: /health returned HTTP {code}",
                  f"URL: {url}\nBody: {body[:300]}")
            continue
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            a.red(f"{name}: /health returned non-JSON",
                  f"Body: {body[:300]}")
            continue
        last = data.get("last_lead_at") or data.get("last_message_at")
        if not last:
            a.yellow(f"{name}: no last_lead_at recorded",
                     "First successful POST hasn't happened yet, OR the LAST_LEAD_AT KV "
                     "binding isn't configured. Check wrangler.toml + the deploy.")
            continue
        try:
            t = dt.datetime.fromisoformat(last.replace("Z", "+00:00"))
        except ValueError:
            a.yellow(f"{name}: malformed last_lead_at",
                     f"Got: {last}")
            continue
        age_h = (now - t).total_seconds() / 3600
        if age_h > max_age_h:
            a.yellow(f"{name}: last activity {age_h:.0f}h ago",
                     f"Threshold {max_age_h}h. Provider may have stopped sending. "
                     f"Last: {last}")
        else:
            a.ok(f"{name}: healthy, last activity {age_h:.0f}h ago")


# ─── Salesforce SOAP login (curl-free, stdlib only) ──────────────────
def sf_login() -> Optional[tuple[str, str]]:
    user = os.environ.get("SF_USERNAME")
    pw   = os.environ.get("SF_PASSWORD")
    tok  = os.environ.get("SF_SECURITY_TOKEN")
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
    return sid.group(1), inst


def sf_query(session: str, instance: str, soql: str) -> list[dict]:
    url = f"{instance}/services/data/v58.0/query?q={urllib.parse.quote(soql)}"
    code, body = http_get(url, {"Authorization": f"Bearer {session}"})
    if code != 200:
        return []
    try:
        return json.loads(body).get("records", [])
    except Exception:  # noqa: BLE001
        return []


# ─── Check 2 + 3: PPL volume floor + SF Lead inflow ──────────────────
def check_lead_inflow(a: Alerts, args) -> None:
    now = dt.datetime.now()
    if now.hour < END_OF_DAY_HOUR:
        a.ok(f"Lead-volume check deferred (only fires after {END_OF_DAY_HOUR}:00 ET)")
        return

    if args.dry_run:
        a.ok("(dry-run) skipping Salesforce volume queries")
        return

    auth = sf_login()
    if not auth:
        a.red("Cloud-health: SF login failed",
              "Cannot run volume checks. Verify SF_USERNAME / SF_PASSWORD / SF_SECURITY_TOKEN.")
        return
    session, instance = auth

    # ── Total Leads today vs 7-day avg ──
    rows = sf_query(session, instance,
        "SELECT CreatedDate FROM Lead WHERE CreatedDate = LAST_N_DAYS:7")
    if not rows:
        a.yellow("No Leads created in last 7 days",
                 "If true, every PPL source is dead.")
        return

    today_count = 0
    by_day: dict[str, int] = {}
    for r in rows:
        d = r["CreatedDate"][:10]
        by_day[d] = by_day.get(d, 0) + 1
    today_iso = dt.date.today().isoformat()
    today_count = by_day.get(today_iso, 0)
    other_days = [c for d, c in by_day.items() if d != today_iso]
    avg = (sum(other_days) / len(other_days)) if other_days else 0
    if avg > 0 and today_count < avg * SF_LEAD_INFLOW_RATIO:
        a.yellow("Total Lead inflow below 50% of 7-day average",
                 f"Today: {today_count} leads. 7-day avg: {avg:.1f}. "
                 "Could be: PPL provider down, ad pause, Cloudflare worker erroring.")
    else:
        a.ok(f"Total Lead inflow OK: today={today_count}, 7d avg={avg:.1f}")

    # ── Per-source PPL volume floor ──
    for source in ("Property Leads PPL", "Motivated Sellers PPL"):
        rows2 = sf_query(session, instance,
            f"SELECT CreatedDate FROM Lead "
            f"WHERE LeadSource = '{source}' AND CreatedDate = LAST_N_DAYS:7")
        if not rows2:
            continue
        by_day2: dict[str, int] = {}
        for r in rows2:
            d = r["CreatedDate"][:10]
            by_day2[d] = by_day2.get(d, 0) + 1
        t_count = by_day2.get(today_iso, 0)
        other = [c for d, c in by_day2.items() if d != today_iso]
        s_avg = (sum(other) / len(other)) if other else 0
        if s_avg >= 5 and t_count < s_avg * PPL_VOLUME_FLOOR_RATIO:
            a.yellow(f"{source}: volume floor breached",
                     f"Today: {t_count}. 7-day avg: {s_avg:.1f}. "
                     "Provider may have paused on their side.")
        else:
            a.ok(f"{source}: today={t_count}, 7d avg={s_avg:.1f}")


# ─── Check 4: SendGrid stats ─────────────────────────────────────────
def check_sendgrid(a: Alerts) -> None:
    key = os.environ.get("SENDGRID_API_KEY")
    if not key:
        a.yellow("SendGrid: SENDGRID_API_KEY not set",
                 "Skipping bounce/complaint check.")
        return

    today = dt.date.today().isoformat()
    code, body = http_get(
        f"https://api.sendgrid.com/v3/stats?start_date={today}&end_date={today}&aggregated_by=day",
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    if code != 200:
        a.yellow("SendGrid stats API failed",
                 f"HTTP {code}, body[:200]: {body[:200]}")
        return
    try:
        stats = json.loads(body)
        m = stats[0]["stats"][0]["metrics"]
    except (KeyError, IndexError, json.JSONDecodeError):
        a.yellow("SendGrid stats parse failed", f"Body: {body[:300]}")
        return

    delivered = m.get("delivered", 0)
    bounces = m.get("bounces", 0)
    complaints = m.get("spam_reports", 0) + m.get("spam_report_drops", 0)
    if delivered == 0:
        a.ok("SendGrid: no sends yet today")
        return

    bounce_pct = (bounces / max(delivered + bounces, 1)) * 100
    complaint_pct = (complaints / max(delivered, 1)) * 100

    if bounce_pct > SENDGRID_BOUNCE_THRESHOLD:
        a.red(f"SendGrid bounce rate {bounce_pct:.1f}% (>{SENDGRID_BOUNCE_THRESHOLD}%)",
              f"delivered={delivered}, bounces={bounces}. List hygiene needed.")
    else:
        a.ok(f"SendGrid bounce: {bounce_pct:.1f}% ({bounces}/{delivered+bounces})")

    if complaint_pct > SENDGRID_COMPLAINT_THRESHOLD:
        a.red(f"SendGrid complaint rate {complaint_pct:.2f}% (>{SENDGRID_COMPLAINT_THRESHOLD}%)",
              f"complaints={complaints}, delivered={delivered}. Reputation risk.")
    else:
        a.ok(f"SendGrid complaints: {complaint_pct:.2f}% ({complaints})")


# ─── Email alert sender (SendGrid v3) ────────────────────────────────
def send_alert_email(subject: str, body: str) -> None:
    key = os.environ.get("SENDGRID_API_KEY")
    to = os.environ.get("ALERT_TO", "info@johnsonbuys.com")
    if not key:
        print("⚠️  No SENDGRID_API_KEY — printing to stdout instead:\n\n", body)
        return
    payload = {
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": "info@johnsonbuys.com", "name": "Cloud Health"},
        "subject": subject,
        "content": [{"type": "text/plain", "value": body}],
    }
    code, resp = http_post(
        "https://api.sendgrid.com/v3/mail/send",
        json.dumps(payload).encode(),
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    if 200 <= code < 300:
        print(f"✓ Alert email sent (HTTP {code})")
    else:
        print(f"✗ Alert email failed (HTTP {code}): {resp[:200]}")


# ─── Main ────────────────────────────────────────────────────────────
def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--report", action="store_true",
                   help="Print full report regardless of state; do not send email.")
    p.add_argument("--dry-run", action="store_true",
                   help="Skip Salesforce queries.")
    args = p.parse_args()

    a = Alerts()
    check_workers(a)
    check_lead_inflow(a, args)
    check_sendgrid(a)

    body = a.render()
    print(body)

    if args.report:
        return 0
    if a.has_any():
        sev = "🔴" if a.has_red() else "🟡"
        ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M %Z")
        send_alert_email(f"{sev} Cloud Health alert ({ts})", body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
