#!/usr/bin/env python3
"""
Pipeline Health Monitor — runs every hour on Railway. Aggressively checks every
piece of the inbound + outbound pipeline and SMS+emails Chris if ANY layer is
silently broken.

Catches the failure modes that slipped past today's debugging:
  - Worker /health bindings missing (e.g. SHARED_SECRET not set)
  - Worker /health timestamps too stale (worker alive but not receiving)
  - SF auth broken on workers (validates by sending a no-op SOQL)
  - Scraper heartbeat stale (logs/scraper_heartbeat.json older than 5 hours)
  - SendGrid auth broken (test-fetch a profile)
  - Twilio auth broken (test-fetch the account)

Runs every hour via Railway service `pipeline_health_monitor` with cron `0 * * * *`.

Output:
  - Each check result printed to stdout (Railway logs)
  - SMS + email to Chris if ANY check fails (deduped by issue type to avoid spam)
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HEARTBEAT_FILE = REPO / "logs" / "scraper_heartbeat.json"
ALERT_STATE = REPO / "logs" / "monitor_alert_state.json"
ALERT_STATE.parent.mkdir(exist_ok=True)


def load_env_for_local() -> dict:
    """Load .env.cheaphomesfla into os.environ for local runs (Railway already has env vars)."""
    env_file = REPO / ".env.cheaphomesfla"
    if not env_file.exists():
        return os.environ.copy()
    e = dict(os.environ)
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            e.setdefault(k, v)
    return e


# Cloudflare's bot protection blocks "Python-urllib/3.x" UAs by default.
# Use a realistic browser UA so requests get through.
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}


def http_get_json(url: str, headers: dict = None, timeout: int = 10):
    h = dict(DEFAULT_HEADERS)
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def http_get_status(url: str, headers: dict = None, timeout: int = 10) -> int:
    try:
        h = dict(DEFAULT_HEADERS)
        h.update(headers or {})
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def parse_iso(s):
    if not s:
        return None
    try:
        # Strip 'Z' if present
        s = s.rstrip("Z")
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc) if "T" in s else None
    except Exception:
        return None


def hours_since(iso: str) -> float:
    dt = parse_iso(iso)
    if not dt:
        return 1e9
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600


# Per-worker freshness expectations during business hours (8am-8pm ET)
# Outside business hours, we relax the thresholds 4x
WORKERS = {
    "propertyleads-ppl-worker": {
        "url": "https://propertyleads-ppl-worker.cbfcalcio5.workers.dev/health",
        "timestamp_field": "last_lead_at",
        "stale_after_hours": 24,
        "required_bindings": ["sf_username", "sendgrid_key", "twilio_sid"],
    },
    "motivatedsellers-ppl-worker": {
        "url": "https://motivatedsellers-ppl-worker.cbfcalcio5.workers.dev/health",
        "timestamp_field": "last_lead_at",
        "stale_after_hours": 24,
        "required_bindings": ["sf_username", "sendgrid_key", "twilio_sid"],
    },
    "sendgrid-events": {
        "url": "https://sendgrid-events.cbfcalcio5.workers.dev/health",
        "timestamp_field": "last_event_at",
        "stale_after_hours": 12,
        "required_bindings": ["sf_username"],
    },
    "railway-deploy-alerts": {
        "url": "https://railway-deploy-alerts.cbfcalcio5.workers.dev/health",
        "timestamp_field": "last_alert_at",
        "stale_after_hours": 72,  # alerts only fire on actual failures, expect rare
        "required_bindings": ["sendgrid", "twilio"],
    },
    "cheaphomesfla-whatsapp-webhook": {
        "url": "https://cheaphomesfla-whatsapp-webhook.cbfcalcio5.workers.dev/health",
        "timestamp_field": "last_message_at",
        "stale_after_hours": 6,  # 30 groups should produce constant flow
        "required_bindings": ["shared_secret"],
        # Disabled 2026-05-12 per Chris — WhatsApp deal-forwarder turned off
        # (volume untenable). Green-API webhook URL unset in console, worker
        # still deployed but receiving nothing. Remove "disabled" to re-enable.
        "disabled": True,
    },
}


def check_workers(failures, env):
    for name, cfg in WORKERS.items():
        if cfg.get("disabled"):
            continue
        try:
            data = http_get_json(cfg["url"])
        except Exception as e:
            failures.append(f"{name} /health unreachable: {e}")
            continue

        # Check bindings
        bindings = data.get("bindings", {})
        for b in cfg["required_bindings"]:
            if not bindings.get(b):
                failures.append(f"{name}: required binding '{b}' is missing or false")

        # Check freshness
        ts = data.get(cfg["timestamp_field"])
        if ts:
            age = hours_since(ts)
            # Relax threshold outside business hours (8am-8pm ET = 12-00 UTC roughly)
            now_utc = datetime.now(timezone.utc)
            is_business_hours = 12 <= now_utc.hour <= 23
            threshold = cfg["stale_after_hours"] * (1 if is_business_hours else 4)
            if age > threshold:
                failures.append(
                    f"{name}: {cfg['timestamp_field']} is {age:.1f}h old (threshold {threshold}h) — pipeline may be silently broken"
                )


def check_scraper_heartbeat(failures):
    if not HEARTBEAT_FILE.exists():
        failures.append("scraper heartbeat file missing — scraper may have never run successfully")
        return
    try:
        hb = json.loads(HEARTBEAT_FILE.read_text())
    except Exception as e:
        failures.append(f"scraper heartbeat unreadable: {e}")
        return
    if not hb.get("last_run_ok"):
        failures.append(f"scraper last run FAILED: {hb.get('last_run_error', 'unknown')}")
    age = hours_since(hb.get("last_run", ""))
    if age > 5:
        failures.append(f"scraper hasn't run in {age:.1f}h (expected every 4h)")
    if hb.get("consecutive_zero_runs", 0) >= 3:
        failures.append(f"scraper has produced 0 deals for {hb['consecutive_zero_runs']} consecutive runs")
    if hb.get("token_warning"):
        failures.append(f"Graph token: {hb['token_warning']}")


def check_sf_auth(failures, env):
    """Live login test — proves SF creds in .env (and on workers, since they share) are valid."""
    try:
        from simple_salesforce import Salesforce
        sf = Salesforce(
            username=env["SF_USERNAME"],
            password=env["SF_PASSWORD"],
            security_token=env["SF_SECURITY_TOKEN"],
            domain=env.get("SF_DOMAIN", "login"),
        )
        sf.query("SELECT Id FROM Lead LIMIT 1")
    except ImportError:
        return  # not installed in this env
    except Exception as e:
        failures.append(f"Salesforce auth failed: {str(e)[:200]}")


def check_sendgrid_auth(failures, env):
    if not env.get("SENDGRID_API_KEY"):
        failures.append("SENDGRID_API_KEY missing from env")
        return
    try:
        code = http_get_status(
            "https://api.sendgrid.com/v3/user/profile",
            headers={"Authorization": f"Bearer {env['SENDGRID_API_KEY']}"},
            timeout=10,
        )
        if code != 200:
            failures.append(f"SendGrid auth failed (HTTP {code})")
    except Exception as e:
        failures.append(f"SendGrid auth check error: {e}")


def check_twilio_auth(failures, env):
    sid = env.get("TWILIO_ACCOUNT_SID")
    tok = env.get("TWILIO_AUTH_TOKEN")
    if not sid or not tok:
        failures.append("Twilio creds missing from env")
        return
    try:
        auth = base64.b64encode(f"{sid}:{tok}".encode()).decode()
        code = http_get_status(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json",
            headers={"Authorization": f"Basic {auth}"},
            timeout=10,
        )
        if code != 200:
            failures.append(f"Twilio auth failed (HTTP {code})")
    except Exception as e:
        failures.append(f"Twilio auth check error: {e}")


def load_alert_state():
    if ALERT_STATE.exists():
        try:
            return json.loads(ALERT_STATE.read_text())
        except Exception:
            pass
    return {}


def save_alert_state(state):
    try:
        ALERT_STATE.write_text(json.dumps(state, indent=2))
    except Exception as e:
        print(f"WARN: couldn't save alert state: {e}", file=sys.stderr)


def fire_alert(failures, env):
    """Send SMS + email if there are NEW failures (deduped by issue text per 6 hours)."""
    now = datetime.now(timezone.utc).isoformat()
    state = load_alert_state()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()

    # Filter to NEW failures (haven't alerted on this exact text in last 6h)
    new_fails = []
    for f in failures:
        last = state.get(f)
        if not last or last < cutoff:
            new_fails.append(f)
            state[f] = now

    if not new_fails:
        print(f"[{now}] {len(failures)} ongoing issue(s) — already alerted in last 6h, suppressing")
        save_alert_state(state)
        return

    # Build alert body
    sms = f"🚨 PIPELINE ALERT ({len(new_fails)} new issue{'s' if len(new_fails) != 1 else ''})\n" + \
          "\n".join(f" • {f[:80]}" for f in new_fails[:5])
    email_body = (
        f"Pipeline Health Monitor detected NEW issues:\n\n" +
        "\n".join(f" • {f}" for f in new_fails) +
        f"\n\nFull issue list ({len(failures)} total):\n" +
        "\n".join(f" - {f}" for f in failures) +
        f"\n\nDiagnostic next steps:\n" +
        f"  1. Run: bash tools/smoke_test_all.sh\n" +
        f"  2. Run: python3 tools/audit_scraper_accuracy.py\n" +
        f"  3. Check: docs/RUNBOOK.md for matching error\n"
    )

    # Send SMS
    sid = env.get("TWILIO_ACCOUNT_SID")
    tok = env.get("TWILIO_AUTH_TOKEN")
    sms_to = env.get("ALERT_SMS_TO", "+13055759040")
    sms_from = env.get("TWILIO_FROM", "+19549534554")
    if sid and tok and sms_to:
        try:
            import urllib.parse
            auth = base64.b64encode(f"{sid}:{tok}".encode()).decode()
            req = urllib.request.Request(
                f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                data=urllib.parse.urlencode({"From": sms_from, "To": sms_to, "Body": sms[:1500]}).encode(),
                method="POST",
                headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
            )
            urllib.request.urlopen(req, timeout=15)
            print(f"[{now}] SMS alert sent to {sms_to}")
        except Exception as e:
            print(f"[{now}] WARN: SMS send failed: {e}", file=sys.stderr)

    # Send email
    sg = env.get("SENDGRID_API_KEY")
    alert_to = env.get("ALERT_TO", "info@johnsonbuys.com")
    if sg and alert_to:
        try:
            req = urllib.request.Request(
                "https://api.sendgrid.com/v3/mail/send",
                data=json.dumps({
                    "personalizations": [{"to": [{"email": alert_to}]}],
                    "from": {"email": env.get("FROM_EMAIL", "info@johnsonbuys.com"), "name": "Pipeline Monitor"},
                    "subject": f"🚨 Pipeline alert: {len(new_fails)} new issue(s)",
                    "content": [{"type": "text/plain", "value": email_body}],
                }).encode(),
                method="POST",
                headers={"Authorization": f"Bearer {sg}", "Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=20)
            print(f"[{now}] Email alert sent to {alert_to}")
        except Exception as e:
            print(f"[{now}] WARN: email send failed: {e}", file=sys.stderr)

    save_alert_state(state)


def main():
    env = load_env_for_local()
    print(f"\n═══ PIPELINE HEALTH MONITOR — {datetime.now(timezone.utc).isoformat()} ═══\n")

    failures = []

    print("→ Checking 5 Cloudflare Workers...")
    check_workers(failures, env)

    print("→ Checking scraper heartbeat...")
    check_scraper_heartbeat(failures)

    print("→ Checking Salesforce auth...")
    check_sf_auth(failures, env)

    print("→ Checking SendGrid auth...")
    check_sendgrid_auth(failures, env)

    print("→ Checking Twilio auth...")
    check_twilio_auth(failures, env)

    print()
    if not failures:
        print("✓ ALL CHECKS PASSED — pipeline is healthy")
        return 0

    print(f"✗ FOUND {len(failures)} ISSUE(S):")
    for f in failures:
        print(f"  • {f}")
    print()

    fire_alert(failures, env)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
