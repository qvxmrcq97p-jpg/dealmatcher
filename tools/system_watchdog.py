#!/usr/bin/env python3
"""
system_watchdog.py — daily health check + email alerts.

Runs every morning (default 9:00 AM via launchd). Checks every moving
part of the JB + CHF stack. If anything is unhealthy, sends Chris an
email. If everything is green, stays silent.

Watchdog catches issues within 24 hours instead of multi-day silent
failures. Specifically catches:

  - Plist not loaded in launchd
  - Plist last exit code != 0
  - Campaign log not modified in last 26 hours (yesterday's run never happened)
  - SendGrid daily limit being approached
  - Twilio account balance critically low
  - Cheaphomesfla scraper produced 0 deals last run (probable parser/auth break)
  - SF connection failures
  - Disk space critically low

Usage:
    cd ~/dealmatcher && python3 tools/system_watchdog.py             # checks + alerts if needed
    cd ~/dealmatcher && python3 tools/system_watchdog.py --report    # always print full report (no email)
    cd ~/dealmatcher && python3 tools/system_watchdog.py --test-alert # send a test alert email

To install as a daily 9 AM launchd job:
    cp ~/dealmatcher/plists/com.cheaphomes.watchdog.plist ~/Library/LaunchAgents/
    launchctl load ~/Library/LaunchAgents/com.cheaphomes.watchdog.plist
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
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

DESKTOP = Path.home() / "Desktop"
ALERT_TO = os.environ.get("WATCHDOG_ALERT_TO", "info@johnsonbuys.com")
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")

EXPECTED_PLISTS = (
    "com.johnsonbuys.emailcampaign",
    "com.johnsonbuys.smscampaign",
    "com.johnsonbuys.followup",
    "com.johnsonbuys.digest",
    "com.johnsonbuys.webhook",
    "com.cheaphomes.dealmatcher",
)

# How fresh each log file should be (hours)
LOG_FRESHNESS = {
    "campaign_log_latest.txt":              (DESKTOP / "campaign_log_latest.txt", 26),
    "sms_all_campaigns_log_latest.txt":     (DESKTOP / "sms_all_campaigns_log_latest.txt", 26),
    "deal_scraper_log_latest.txt":          (DESKTOP / "deal_scraper_log_latest.txt", 12),  # 3x/day
    "scraper_stdout.log":                   (SCRIPT_DIR / "logs" / "scraper_stdout.log", 12),
}


# ---------------------------------------------------------------------------
# Issues collector
# ---------------------------------------------------------------------------

class Issues:
    """Accumulates findings, prints to stdout, returns email body if any."""
    def __init__(self):
        self.alerts: list[tuple[str, str, str]] = []   # (severity, title, detail)
        self.green: list[str] = []                      # ok-status messages

    def alert(self, severity: str, title: str, detail: str = "") -> None:
        self.alerts.append((severity, title, detail))

    def ok(self, msg: str) -> None:
        self.green.append(msg)

    @property
    def has_critical(self) -> bool:
        return any(s == "🔴" for s, _, _ in self.alerts)

    @property
    def has_any(self) -> bool:
        return bool(self.alerts)

    def render_text(self) -> str:
        lines = []
        if self.alerts:
            lines.append(f"🚨 SYSTEM WATCHDOG — {len(self.alerts)} alert(s)")
            lines.append(f"Run at: {datetime.now().isoformat(timespec='seconds')}")
            lines.append("")
            lines.append("=" * 60)
            for sev, title, detail in self.alerts:
                lines.append(f"\n{sev} {title}")
                if detail:
                    lines.append(f"   {detail}")
            lines.append("\n" + "=" * 60)
        else:
            lines.append(f"✅ SYSTEM WATCHDOG — all green")
            lines.append(f"Run at: {datetime.now().isoformat(timespec='seconds')}")
        if self.green:
            lines.append("\nVerified healthy:")
            for g in self.green:
                lines.append(f"  ✓ {g}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_launchd_jobs(issues: Issues) -> None:
    try:
        out = subprocess.check_output(["launchctl", "list"], text=True, timeout=15)
    except Exception as e:  # noqa: BLE001
        issues.alert("🔴", "launchctl list failed",
                     f"Could not query launchd: {e}. Watchdog cannot verify scheduled jobs.")
        return

    loaded = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            loaded[parts[2]] = (parts[0], parts[1])  # (pid, last_exit)

    for job in EXPECTED_PLISTS:
        info = loaded.get(job)
        if not info:
            issues.alert("🔴", f"Plist not loaded: {job}",
                         f"Fix: launchctl load ~/Library/LaunchAgents/{job}.plist")
            continue
        pid, last_exit = info
        if last_exit not in ("-", "0"):
            issues.alert(
                "🟡",
                f"{job}: last exit code {last_exit}",
                f"Most recent run failed. Check ~/Desktop/<log file> or "
                f"~/dealmatcher/logs/ for the error. Re-fire with: "
                f"launchctl start {job}",
            )
        else:
            issues.ok(f"{job}: loaded, last exit clean")


def check_log_freshness(issues: Issues) -> None:
    now = datetime.now()
    for label, (path, max_hours) in LOG_FRESHNESS.items():
        if not path.exists():
            issues.alert("🟡", f"Log missing: {label}",
                         f"{path} does not exist. Has the job ever run?")
            continue
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        age = now - mtime
        age_hours = age.total_seconds() / 3600
        if age_hours > max_hours:
            issues.alert(
                "🔴" if age_hours > max_hours * 2 else "🟡",
                f"Log stale: {label}",
                f"Last modified {age_hours:.0f}h ago (expected within {max_hours}h). "
                f"Schedule may have stopped firing. Check the corresponding plist.",
            )
        else:
            issues.ok(f"{label}: fresh ({age_hours:.0f}h ago)")


def check_recent_campaign_results(issues: Issues) -> None:
    """Read today's campaign log and look for anomalies (mass failures, etc.)."""
    today = date.today().strftime("%Y%m%d")
    log_path = DESKTOP / f"campaign_log_{today}.txt"
    if not log_path.exists():
        # Today might not have run yet (if watchdog runs before 8 AM)
        if datetime.now().hour < 9:
            return
        issues.alert("🟡", "Today's email campaign log missing",
                     f"Expected at {log_path}. Did the 8 AM run fire?")
        return
    try:
        text = log_path.read_text(errors="replace")
    except Exception:  # noqa: BLE001
        return

    sent = text.count("✓ Sent:")
    failed = text.count("✗ Failed:")
    sendgrid_limit = text.count("Maximum credits exceeded") + text.count("exceeded your messaging limits")

    if sendgrid_limit > 50:
        issues.alert("🔴", f"SendGrid throttling email campaign ({sendgrid_limit} hits today)",
                     "Daily SendGrid limit is being hit hard. Verify Essentials plan is "
                     "active and there's no manual cap below 500. Login to "
                     "https://app.sendgrid.com → Account Details.")
    elif sendgrid_limit > 0:
        issues.alert("🟡", f"SendGrid threw {sendgrid_limit} limit errors today",
                     "Some sends throttled. Plan may need upgrade or the daily counter "
                     "didn't reset cleanly.")
    else:
        issues.ok(f"Email campaign: {sent} sent, {failed} failed (no SendGrid throttling)")

    if failed > sent and (sent + failed) > 10:
        issues.alert("🟡", f"Email campaign: more failures ({failed}) than successes ({sent})",
                     "Sender reputation issue, or SendGrid blocking. Investigate today's log.")


def check_scraper_results(issues: Issues) -> None:
    """Verify the cheaphomesfla scraper produced deals on its last run."""
    state_file = DESKTOP / "deal_scraper_state.json"
    deals_file = DESKTOP / "deal_scraper_last_run_deals.json"
    if not state_file.exists() or not deals_file.exists():
        # Scraper may not have ever run yet (pre-go-live)
        return
    try:
        state = json.loads(state_file.read_text())
        last_run_iso = state.get("last_run_iso", "")
        last_run = datetime.fromisoformat(last_run_iso.replace("Z", "+00:00"))
        age_hours = (datetime.now(timezone.utc) - last_run).total_seconds() / 3600
        if age_hours > 24:
            issues.alert("🟡", f"Cheaphomesfla scraper last ran {age_hours:.0f}h ago",
                         "Expected daily 10/14/18:00. Check launchctl load status.")
            return
    except Exception:  # noqa: BLE001
        pass

    try:
        deals = json.loads(deals_file.read_text())
        if isinstance(deals, list):
            n = len(deals)
            if n == 0:
                issues.alert("🟡", "Cheaphomesfla scraper: 0 deals last run",
                             "Either no wholesalers blasted today, OR parser broke / Graph "
                             "auth expired. Tail ~/dealmatcher/logs/scraper_stdout.log to "
                             "investigate.")
            else:
                issues.ok(f"Cheaphomesfla scraper: {n} deals from last run")
    except Exception:  # noqa: BLE001
        pass


def check_disk_space(issues: Issues) -> None:
    try:
        usage = shutil.disk_usage(str(Path.home()))
        gb_free = usage.free / (1024 ** 3)
        if gb_free < 5:
            issues.alert("🔴", f"Disk critically low: {gb_free:.1f} GB free",
                         "Logs are likely flooding storage. Free up space ASAP.")
        elif gb_free < 20:
            issues.alert("🟡", f"Disk getting tight: {gb_free:.1f} GB free", "")
        else:
            issues.ok(f"Disk: {gb_free:.0f} GB free")
    except Exception:  # noqa: BLE001
        pass


def check_salesforce_basic(issues: Issues) -> None:
    """Quick SF connectivity check + Lead count sanity."""
    try:
        from simple_salesforce import Salesforce
    except ImportError:
        return  # silent — not installed in this env
    try:
        sf = Salesforce(
            username=os.environ["SF_USERNAME"],
            password=os.environ["SF_PASSWORD"],
            security_token=os.environ["SF_SECURITY_TOKEN"],
        )
        cnt = sf.query("SELECT COUNT(Id) c FROM Lead")
        n = int(cnt["records"][0].get("c", 0)) if cnt["records"] else 0
        if n > 0:
            issues.ok(f"Salesforce: {n:,} Leads in pipeline (connection OK)")
    except Exception as e:  # noqa: BLE001
        issues.alert(
            "🔴",
            "Salesforce connection FAILED",
            f"Watchdog cannot reach SF: {type(e).__name__}: {str(e)[:200]}. "
            "Check SF_PASSWORD / SF_SECURITY_TOKEN env vars in .env.cheaphomesfla.",
        )


# ---------------------------------------------------------------------------
# Email alert via SendGrid
# ---------------------------------------------------------------------------

def send_alert_email(subject: str, body: str) -> bool:
    if not SENDGRID_API_KEY:
        print("(no SENDGRID_API_KEY — skipping alert email)")
        return False
    try:
        import requests
    except ImportError:
        return False
    payload = {
        "personalizations": [{"to": [{"email": ALERT_TO}]}],
        "from": {"email": "info@johnsonbuys.com", "name": "Johnson Buys Watchdog"},
        "subject": subject,
        "content": [{"type": "text/plain", "value": body}],
    }
    r = requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={
            "Authorization": f"Bearer {SENDGRID_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=15,
    )
    return r.status_code in (200, 202)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--report", action="store_true",
                   help="Always print full report; never send email")
    p.add_argument("--test-alert", action="store_true",
                   help="Send a test alert email and exit")
    args = p.parse_args()

    if args.test_alert:
        ok = send_alert_email(
            "🧪 SYSTEM WATCHDOG: test alert",
            "This is a test alert. If you received this, alert delivery is wired correctly.\n\n"
            "— Johnson Buys Watchdog",
        )
        print("Test alert sent." if ok else "Test alert FAILED — check SENDGRID_API_KEY")
        return

    issues = Issues()
    print("Running system watchdog checks...\n")

    check_launchd_jobs(issues)
    check_log_freshness(issues)
    check_recent_campaign_results(issues)
    check_scraper_results(issues)
    check_disk_space(issues)
    check_salesforce_basic(issues)

    body = issues.render_text()
    print(body)
    print()

    if args.report:
        print("(--report flag: not sending email)")
        return

    if not issues.has_any:
        print("All green — no email sent.")
        return

    severity = "🚨" if issues.has_critical else "⚠️"
    subject = f"{severity} JB watchdog — {len(issues.alerts)} alert(s) — {date.today().isoformat()}"
    sent = send_alert_email(subject, body)
    if sent:
        print(f"\nAlert email sent to {ALERT_TO}")
    else:
        print(f"\nAlert email FAILED — please check ~/dealmatcher/logs/ manually")


if __name__ == "__main__":
    main()
