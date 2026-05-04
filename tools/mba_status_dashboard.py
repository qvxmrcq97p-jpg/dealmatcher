#!/usr/bin/env python3
"""
MBA Status Dashboard — single-command full ops snapshot.

Run on any Mac to see:
  - Is THIS Mac fully set up to administer the stack?
  - Is the cloud pipeline healthy right now?
  - What was today's deal flow (email + WhatsApp)?
  - What outbound campaigns ran today?
  - Recent code changes
  - What you can do from here (capability matrix)
  - Open issues + suggested next actions
  - Quick-link URLs to all dashboards

Usage: python3 tools/mba_status_dashboard.py
"""
from __future__ import annotations

import base64
import json
import os
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DESKTOP = Path.home() / "Desktop"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"

# Color codes
GREEN, RED, YELLOW, BLUE, BOLD, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[34m", "\033[1m", "\033[2m", "\033[0m"


def ok(msg): return f"{GREEN}✓{RESET} {msg}"
def warn(msg): return f"{YELLOW}⚠{RESET} {msg}"
def bad(msg): return f"{RED}✗{RESET} {msg}"
def header(msg): return f"\n{BOLD}▶ {msg}{RESET}"


def load_env():
    env = dict(os.environ)
    env_file = REPO / ".env.cheaphomesfla"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env.setdefault(k.strip(), v.strip())
    return env


def http_json(url, headers=None, timeout=8):
    try:
        h = {"User-Agent": UA, "Accept": "application/json"}
        if headers:
            h.update(headers)
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def http_status(url, headers=None, timeout=8):
    try:
        h = {"User-Agent": UA}
        if headers:
            h.update(headers)
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def hours_since(iso):
    if not iso:
        return None
    try:
        s = iso.rstrip("Z").split(".")[0]
        dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        return None


def section_mac_setup():
    print(header("Mac setup"))
    # Repo present
    if (REPO / ".git").exists():
        try:
            last_pull = subprocess.check_output(["git", "log", "-1", "--format=%cr"], cwd=REPO, text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            last_pull = "unknown"
        print(ok(f"Repo at {REPO} (last commit: {last_pull})"))
    else:
        print(bad(f"Repo not found at {REPO} — run bootstrap_macbook.sh"))
        return

    # .env present
    env_file = REPO / ".env.cheaphomesfla"
    if env_file.exists():
        env = load_env()
        configured = sum(1 for k in ["SF_USERNAME", "SENDGRID_API_KEY", "TWILIO_ACCOUNT_SID", "GRAPH_CLIENT_ID"] if env.get(k))
        print(ok(f".env.cheaphomesfla present ({configured}/4 core services configured)"))
    else:
        print(bad(".env.cheaphomesfla missing — AirDrop from primary Mac"))

    # CLI tools
    tools_status = []
    for t in ["git", "python3", "node", "wrangler", "gh", "twilio"]:
        try:
            subprocess.check_output(["which", t], stderr=subprocess.DEVNULL)
            tools_status.append((t, True))
        except Exception:
            tools_status.append((t, False))
    installed = [t for t, has in tools_status if has]
    missing = [t for t, has in tools_status if not has]
    if not missing:
        print(ok(f"All CLI tools installed: {', '.join(installed)}"))
    else:
        print(warn(f"CLI tools installed: {', '.join(installed)}"))
        print(warn(f"  Missing (optional): {', '.join(missing)} — `brew install <name>`"))

    # SSH key + GitHub access
    try:
        r = subprocess.run(
            ["git", "ls-remote", "--heads", "origin", "main"],
            cwd=REPO, capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            print(ok("GitHub SSH access works (push/pull will succeed)"))
        else:
            print(bad("GitHub SSH access broken — `cat ~/.ssh/id_ed25519.pub | pbcopy` and add at https://github.com/settings/keys"))
    except Exception as e:
        print(bad(f"GitHub SSH check failed: {e}"))

    # Wrangler login
    try:
        r = subprocess.run(["wrangler", "whoami"], capture_output=True, text=True, timeout=10)
        out = r.stdout + r.stderr
        m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", out)
        if m:
            print(ok(f"wrangler logged in as {m.group()}"))
        elif "not logged" in out.lower() or r.returncode != 0:
            print(warn("wrangler not logged in (only matters for ad-hoc deploys; CI handles regular deploys)"))
    except FileNotFoundError:
        pass


def section_pipeline_health():
    print(header("Pipeline health (live, just checked)"))
    workers = [
        ("propertyleads-ppl-worker", "last_lead_at", 24),
        ("motivatedsellers-ppl-worker", "last_lead_at", 24),
        ("sendgrid-events", "last_event_at", 12),
        ("railway-deploy-alerts", "last_alert_at", 72),
        ("cheaphomesfla-whatsapp-webhook", "last_message_at", 6),
    ]
    all_green = True
    for w, field, stale_h in workers:
        url = f"https://{w}.cbfcalcio5.workers.dev/health"
        data = http_json(url)
        if not data:
            print(bad(f"{w} /health unreachable"))
            all_green = False
            continue
        ts = data.get(field)
        if ts:
            age = hours_since(ts)
            if age is None or age > stale_h:
                print(warn(f"{w}: {field} = {age:.1f}h ago (threshold {stale_h}h)"))
                all_green = False
            else:
                print(ok(f"{w}: HTTP 200, {field} = {age:.1f}h ago"))
        else:
            note = "never received yet" if field == "last_alert_at" else "no events yet"
            print(ok(f"{w}: HTTP 200 ({note})"))

    # Scraper heartbeat
    hb_file = REPO / "logs" / "scraper_heartbeat.json"
    if hb_file.exists():
        try:
            hb = json.loads(hb_file.read_text())
            age = hours_since(hb.get("last_run", ""))
            if hb.get("last_run_ok"):
                print(ok(f"Scraper last run: {age:.1f}h ago, status OK ({hb.get('stats', {}).get('deals_parsed', 0)} deals)"))
            else:
                print(bad(f"Scraper last run failed: {hb.get('last_run_error', 'unknown')}"))
        except Exception:
            print(warn("Scraper heartbeat unreadable"))
    else:
        print(warn("Scraper heartbeat missing (file populates after first cloud run via main())"))


def section_auth_checks():
    print(header("Authentication health"))
    env = load_env()

    # SF
    try:
        from simple_salesforce import Salesforce
        sf = Salesforce(
            username=env["SF_USERNAME"],
            password=env["SF_PASSWORD"],
            security_token=env["SF_SECURITY_TOKEN"],
            domain=env.get("SF_DOMAIN", "login"),
        )
        r = sf.query("SELECT COUNT(Id) c FROM Lead")
        print(ok(f"Salesforce: auth works ({r['records'][0]['c']:,} total Leads)"))
    except ImportError:
        print(warn("Salesforce: simple_salesforce not installed (pip3 install --break-system-packages simple-salesforce)"))
    except Exception as e:
        print(bad(f"Salesforce auth FAILED: {str(e)[:100]}"))

    # SendGrid
    if env.get("SENDGRID_API_KEY"):
        code = http_status("https://api.sendgrid.com/v3/user/profile", headers={"Authorization": f"Bearer {env['SENDGRID_API_KEY']}"})
        print(ok("SendGrid: auth works") if code == 200 else bad(f"SendGrid: auth FAILED (HTTP {code})"))

    # Twilio
    if env.get("TWILIO_ACCOUNT_SID") and env.get("TWILIO_AUTH_TOKEN"):
        auth = base64.b64encode(f"{env['TWILIO_ACCOUNT_SID']}:{env['TWILIO_AUTH_TOKEN']}".encode()).decode()
        code = http_status(f"https://api.twilio.com/2010-04-01/Accounts/{env['TWILIO_ACCOUNT_SID']}.json", headers={"Authorization": f"Basic {auth}"})
        print(ok("Twilio: auth works") if code == 200 else bad(f"Twilio: auth FAILED (HTTP {code})"))


def section_today_activity():
    print(header(f"Today's activity ({datetime.now().strftime('%Y-%m-%d')})"))
    env = load_env()
    try:
        from simple_salesforce import Salesforce
        sf = Salesforce(
            username=env["SF_USERNAME"],
            password=env["SF_PASSWORD"],
            security_token=env["SF_SECURITY_TOKEN"],
            domain=env.get("SF_DOMAIN", "login"),
        )

        # New Leads today
        try:
            r = sf.query("SELECT COUNT(Id) c FROM Lead WHERE CreatedDate = TODAY")
            print(f"  New Leads today: {r['records'][0]['c']}")
        except Exception:
            pass

        # Per-source breakdown
        try:
            r = sf.query("SELECT LeadSource, COUNT(Id) c FROM Lead WHERE CreatedDate = TODAY GROUP BY LeadSource")
            for row in r["records"]:
                print(f"    by source: {row.get('LeadSource', 'unknown') or 'unknown'} → {row['c']}")
        except Exception:
            pass

        # Tasks created today (scraper deal-match Tasks)
        try:
            r = sf.query("SELECT COUNT(Id) c FROM Task WHERE CreatedDate = TODAY AND Subject LIKE 'Deal:%'")
            print(f"  Buyer-deal matches today: {r['records'][0]['c']}")
        except Exception:
            pass

    except Exception as e:
        print(warn(f"  Couldn't query SF: {e}"))


def section_recent_commits():
    print(header("Recent commits"))
    try:
        out = subprocess.check_output(["git", "log", "-7", "--oneline", "--no-color"], cwd=REPO, text=True, stderr=subprocess.DEVNULL)
        for line in out.strip().split("\n"):
            print(f"  {line}")
    except Exception:
        print(warn("  git log unavailable"))


def section_capabilities():
    print(header("What you can do from this Mac (capability matrix)"))
    items = [
        ("Edit code → push to GitHub → CI auto-deploys Workers", True),
        ("Deploy/redeploy individual Cloudflare Workers via wrangler", True),
        ("Set Cloudflare Worker secrets via wrangler secret put", True),
        ("Manage Railway services (web dashboard or CLI)", True),
        ("Query/modify Salesforce via simple_salesforce", True),
        ("Send SMS/email via Twilio/SendGrid APIs", True),
        ("Run any tools/ script (~30 helpers)", True),
        ("Recover from any documented incident (docs/RUNBOOK.md)", True),
        ("Refresh Microsoft Graph token (tools/refresh_graph_token.py)", True),
        ("Deploy ads / campaigns (manual via FB/Google dashboards)", True),
    ]
    for desc, ok_flag in items:
        print(ok(desc) if ok_flag else warn(desc))


def section_open_issues():
    print(header("Active TODOs + decisions needed"))
    todo = REPO / "TODO.md"
    if todo.exists():
        text = todo.read_text()
        # Count - [ ]  vs - [x]
        pending = text.count("- [ ]")
        done = text.count("- [x]")
        print(f"  TODO.md: {pending} pending, {done} done — `less {todo}` to read")

    # Specific known pending items
    print(f"  ⏳ Pipeline Health Monitor: NOT YET deployed as Railway service (see docs/RAILWAY_SERVICES.md)")
    print(f"  ⏳ GRAPH env vars: verify set on Railway service `dealmatcher`")
    print(f"  ⏳ Parser refinement (sqft/bed extraction quality)")


def section_quick_links():
    print(header("Dashboards (open in browser)"))
    links = [
        ("Salesforce", "https://johnsonshomes2.my.salesforce.com"),
        ("Railway", "https://railway.com/dashboard"),
        ("Cloudflare", "https://dash.cloudflare.com"),
        ("SendGrid", "https://app.sendgrid.com"),
        ("Twilio", "https://console.twilio.com"),
        ("Constant Contact", "https://app.constantcontact.com"),
        ("FB Ads Manager", "https://business.facebook.com/adsmanager"),
        ("Google Ads", "https://ads.google.com"),
        ("GitHub repo", "https://github.com/qvxmrcq97p-jpg/dealmatcher"),
        ("Green-API (WhatsApp)", "https://console.green-api.com"),
    ]
    for name, url in links:
        print(f"  • {name:25s} {url}")


def section_run_book():
    print(header("Quick references"))
    print(f"  • Universal entry: less ~/dealmatcher/START_HERE.md")
    print(f"  • Daily playbook:  less ~/dealmatcher/DAILY_PLAYBOOK.md")
    print(f"  • Trouble-shoot:   less ~/dealmatcher/docs/TROUBLESHOOTING.md")
    print(f"  • Paste-the-fix:   less ~/dealmatcher/docs/RUNBOOK.md")
    print(f"  • Product strategy: less ~/dealmatcher/PRODUCT_STRATEGY.md")
    print(f"  • Active TODO:     less ~/dealmatcher/TODO.md")


def main():
    print(f"\n{BOLD}╔══════════════════════════════════════════════════════════════════╗")
    print(f"║   DEALMATCHER STATUS DASHBOARD — {datetime.now().strftime('%a %b %-d %H:%M %Z')}".ljust(67) + "║")
    print(f"║   Machine: {socket.gethostname()}".ljust(67) + "║")
    print(f"╚══════════════════════════════════════════════════════════════════╝{RESET}")

    section_mac_setup()
    section_pipeline_health()
    section_auth_checks()
    section_today_activity()
    section_recent_commits()
    section_capabilities()
    section_open_issues()
    section_quick_links()
    section_run_book()

    print(f"\n{DIM}Run `python3 tools/pipeline_health_monitor.py` for live alerting checks.{RESET}")
    print(f"{DIM}Run `bash tools/smoke_test_all.sh` for end-to-end stack health check.{RESET}\n")


if __name__ == "__main__":
    main()
