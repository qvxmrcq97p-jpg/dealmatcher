#!/usr/bin/env python3
"""
morning_preflight.py — single-command system status, run every morning.

Pulls a one-page snapshot of every moving part: JB email campaign,
JB SMS campaign, cheaphomesfla scraper, launchd job status, today's
Salesforce Task counts. Catches problems before they cascade.

Run:
    cd ~/dealmatcher && python3 tools/morning_preflight.py

Use it daily — first thing after coffee — to confirm everything fired
overnight. Output is one screen, no scrolling required.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

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
TODAY_STR = date.today().strftime("%Y%m%d")


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def hr() -> None:
    print("─" * 72)


def banner(title: str) -> None:
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


def status(label: str, ok: bool, detail: str = "") -> None:
    mark = "✓" if ok else "✗"
    print(f"  {mark} {label:<40} {detail}")


# ---------------------------------------------------------------------------
# launchctl jobs
# ---------------------------------------------------------------------------

EXPECTED_JOBS = (
    "com.johnsonbuys.emailcampaign",
    "com.johnsonbuys.smscampaign",
    "com.johnsonbuys.followup",
    "com.johnsonbuys.digest",
    "com.johnsonbuys.webhook",
    "com.cheaphomes.dealmatcher",
)


def check_launchd() -> None:
    banner("launchd jobs")
    try:
        out = subprocess.check_output(["launchctl", "list"], text=True, timeout=15)
    except Exception as e:  # noqa: BLE001
        print(f"  ERROR: launchctl unavailable ({e})")
        return
    loaded_jobs = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            loaded_jobs.add(parts[2])
    for job in EXPECTED_JOBS:
        is_loaded = job in loaded_jobs
        # Get exit status if loaded
        detail = ""
        if is_loaded:
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[2] == job:
                    pid, last_exit = parts[0], parts[1]
                    if pid != "-":
                        detail = f"PID {pid} (running)"
                    elif last_exit != "0":
                        detail = f"last exit code: {last_exit} ⚠️"
                    else:
                        detail = "loaded, last exit OK"
                    break
        else:
            detail = "NOT LOADED"
        status(job, is_loaded, detail)


# ---------------------------------------------------------------------------
# Log file checks
# ---------------------------------------------------------------------------

def check_log(name: str, path: Path, last_n: int = 5) -> None:
    print(f"\n  {name}: {path}")
    if not path.exists():
        print(f"    ⚠️  log file does not exist")
        return
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    age = datetime.now() - mtime
    age_str = (
        f"{int(age.total_seconds() / 60)}m ago" if age < timedelta(hours=1)
        else f"{int(age.total_seconds() / 3600)}h ago" if age < timedelta(days=1)
        else f"{age.days}d ago"
    )
    age_warn = "⚠️ STALE" if age > timedelta(hours=26) else ""
    print(f"    last modified: {mtime.strftime('%Y-%m-%d %H:%M')} ({age_str}) {age_warn}")
    try:
        text = path.read_text(errors="replace")
    except Exception as e:  # noqa: BLE001
        print(f"    ERROR reading: {e}")
        return
    lines = text.splitlines()
    last_lines = lines[-last_n:]
    for line in last_lines:
        print(f"    │ {line[:120]}")


def check_campaign_logs() -> None:
    banner("Campaign logs")
    today = date.today()
    today_path = DESKTOP / f"campaign_log_{today.strftime('%Y%m%d')}.txt"
    latest_path = DESKTOP / "campaign_log_latest.txt"
    sms_today = DESKTOP / f"sms_all_campaigns_log_{today.strftime('%Y%m%d')}.txt"
    sms_latest = DESKTOP / "sms_all_campaigns_log_latest.txt"
    scraper_log = SCRIPT_DIR / "logs" / "scraper_stdout.log"
    scraper_log_alt = DESKTOP / f"deal_scraper_log_{today.strftime('%Y%m%d')}.txt"

    # JB email
    if today_path.exists():
        check_log("JB email (today)", today_path, last_n=8)
    else:
        check_log("JB email (latest)", latest_path, last_n=8)

    # JB SMS
    if sms_today.exists():
        check_log("JB SMS (today)", sms_today, last_n=6)
    else:
        check_log("JB SMS (latest)", sms_latest, last_n=6)

    # Cheaphomesfla scraper
    if scraper_log.exists():
        check_log("CHF scraper (launchd)", scraper_log, last_n=8)
    elif scraper_log_alt.exists():
        check_log("CHF scraper (today)", scraper_log_alt, last_n=8)
    else:
        print("\n  ⚠️  CHF scraper log not found — has it ever fired? Check go-live.")


# ---------------------------------------------------------------------------
# Salesforce activity check
# ---------------------------------------------------------------------------

def check_sf_activity() -> None:
    banner("Salesforce activity (today)")
    try:
        from simple_salesforce import Salesforce
    except ImportError:
        print("  simple_salesforce not installed — skipping SF check")
        return
    try:
        sf = Salesforce(
            username=os.environ["SF_USERNAME"],
            password=os.environ["SF_PASSWORD"],
            security_token=os.environ["SF_SECURITY_TOKEN"],
        )
    except Exception as e:  # noqa: BLE001
        print(f"  ERROR connecting to SF: {e}")
        return

    # JB email + SMS Tasks today
    res = sf.query_all("SELECT Subject FROM Task WHERE CreatedDate = TODAY AND Subject LIKE 'JB-%'")
    jb_subjects = Counter()
    for r in res["records"]:
        r.pop("attributes", None)
        jb_subjects[r.get("Subject") or "(no subject)"] += 1

    if jb_subjects:
        print(f"  ✓ JB Tasks created today: {sum(jb_subjects.values()):,}")
        for subj, n in jb_subjects.most_common(8):
            print(f"      {subj:<35} {n:>5,}")
    else:
        print("  ✗ No JB Tasks created today yet")
        print("      Email campaign fires 8:00 AM, SMS at 8:15 AM. If past 9 AM, investigate.")

    # CHF deal Tasks today (cheaphomesfla matches)
    cnt = sf.query("SELECT COUNT(Id) c FROM Task WHERE CreatedDate = TODAY AND Subject LIKE 'CH-DEAL-%'")
    chf = int(cnt["records"][0].get("c", 0)) if cnt["records"] else 0
    if chf > 0:
        print(f"  ✓ CHF deal-match Tasks today: {chf:,}")
    else:
        print(f"  ⚠ CHF deal-match Tasks today: 0 — scheduled scraper runs at 10/14/18:00")

    # Recent Lead activity
    cnt = sf.query("SELECT COUNT(Id) c FROM Lead WHERE CreatedDate = TODAY")
    new_today = int(cnt["records"][0].get("c", 0)) if cnt["records"] else 0
    cnt = sf.query("SELECT COUNT(Id) c FROM Lead WHERE LastModifiedDate = TODAY")
    mod_today = int(cnt["records"][0].get("c", 0)) if cnt["records"] else 0
    print(f"\n  Lead activity today:")
    print(f"      Created today:  {new_today:,}")
    print(f"      Modified today: {mod_today:,}")


# ---------------------------------------------------------------------------
# Quick summary
# ---------------------------------------------------------------------------

def summary_card() -> None:
    """Print a 1-line green/red summary at the top — eye candy for at-a-glance."""
    issues = []
    # JB email log freshness
    p = DESKTOP / f"campaign_log_{TODAY_STR}.txt"
    if not p.exists():
        issues.append("no JB email run today")
    # JB SMS log freshness
    p = DESKTOP / f"sms_all_campaigns_log_{TODAY_STR}.txt"
    if not p.exists():
        issues.append("no JB SMS run today")
    # CHF scraper log freshness (launchd or desktop variant)
    log_a = SCRIPT_DIR / "logs" / "scraper_stdout.log"
    log_b = DESKTOP / f"deal_scraper_log_{TODAY_STR}.txt"
    if not (log_a.exists() or log_b.exists()):
        issues.append("CHF scraper has not fired today")

    print()
    print("═" * 72)
    if issues:
        print(f"  ⚠️  PREFLIGHT — {len(issues)} concern(s):")
        for i in issues:
            print(f"     • {i}")
    else:
        print("  ✓ PREFLIGHT — all visible scheduled jobs ran today.")
    print(f"  {datetime.now().strftime('%A %B %d, %Y at %I:%M %p')}")
    print("═" * 72)


def main() -> None:
    summary_card()
    check_launchd()
    check_campaign_logs()
    check_sf_activity()
    print()
    hr()
    print("  Run again any time:  cd ~/dealmatcher && python3 tools/morning_preflight.py")
    hr()


if __name__ == "__main__":
    main()
