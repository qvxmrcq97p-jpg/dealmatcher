"""
Scraper safeguards — three layers of protection against silent failures.

LAYER 1 — Inline failure alerting
    On any fatal exception in main(), send SMS + email to Chris within 60s.

LAYER 2 — "Ran but did nothing" alerting
    If a run completes successfully but produced 0 parsed deals, log a
    heartbeat. If 3+ CONSECUTIVE runs each produce 0 deals (which would
    indicate auth/filter regression rather than just a slow news day),
    fire SMS + email — but only ONCE per stretch (suppress duplicates).

LAYER 3 — Heartbeat file (read by system_watchdog)
    Each run writes a JSON heartbeat with last-run timestamp + stats.
    system_watchdog.py polls this and alerts if stale (>5 hours).

Usage in cheaphomesfla_scraper.py:

    from tools.scraper_safeguards import safeguard_run

    if __name__ == "__main__":
        safeguard_run(main)

That's it — wraps main() with full alerting + heartbeat logic.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parent.parent
HEARTBEAT_FILE = REPO / "logs" / "scraper_heartbeat.json"
HEARTBEAT_FILE.parent.mkdir(exist_ok=True)

# How many consecutive zero-deal runs before alerting
ZERO_DEAL_ALERT_THRESHOLD = 3


def _load_env(env_file: Path) -> dict:
    """Load .env-style file, returns dict."""
    env = {}
    if not env_file.exists():
        return env
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def _get_creds() -> dict:
    """Pull alerting creds from env (preferred) or .env.cheaphomesfla (fallback)."""
    creds = {
        "SENDGRID_API_KEY": os.getenv("SENDGRID_API_KEY", ""),
        "FROM_EMAIL": os.getenv("FROM_EMAIL", "info@johnsonbuys.com"),
        "ALERT_TO": os.getenv("ALERT_TO", "info@johnsonbuys.com"),
        "TWILIO_ACCOUNT_SID": os.getenv("TWILIO_ACCOUNT_SID", ""),
        "TWILIO_AUTH_TOKEN": os.getenv("TWILIO_AUTH_TOKEN", ""),
        "TWILIO_FROM": os.getenv("TWILIO_FROM", "+19549534554"),
        "ALERT_SMS_TO": os.getenv("ALERT_SMS_TO", "+13055759040"),
    }
    # Fall back to .env.cheaphomesfla for any missing values
    if not all(creds.values()):
        env_creds = _load_env(REPO / ".env.cheaphomesfla")
        for k in creds:
            if not creds[k] and k in env_creds:
                creds[k] = env_creds[k]
    return creds


def _send_sms(body: str, creds: dict) -> bool:
    """Best-effort SMS via Twilio. Truncates to 1500 chars."""
    if not creds.get("TWILIO_ACCOUNT_SID") or not creds.get("ALERT_SMS_TO"):
        return False
    try:
        import requests
        body = body[:1500]
        r = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{creds['TWILIO_ACCOUNT_SID']}/Messages.json",
            auth=(creds["TWILIO_ACCOUNT_SID"], creds["TWILIO_AUTH_TOKEN"]),
            data={"From": creds["TWILIO_FROM"], "To": creds["ALERT_SMS_TO"], "Body": body},
            timeout=15,
        )
        return r.ok
    except Exception as e:
        print(f"WARN: SMS alert failed: {e}", file=sys.stderr)
        return False


def _send_email(subject: str, body: str, creds: dict) -> bool:
    """Best-effort email via SendGrid."""
    if not creds.get("SENDGRID_API_KEY"):
        return False
    try:
        import requests
        r = requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={
                "Authorization": f"Bearer {creds['SENDGRID_API_KEY']}",
                "Content-Type": "application/json",
            },
            json={
                "personalizations": [{"to": [{"email": creds["ALERT_TO"]}]}],
                "from": {"email": creds["FROM_EMAIL"], "name": "Scraper Safeguards"},
                "subject": subject,
                "content": [{"type": "text/plain", "value": body}],
            },
            timeout=20,
        )
        return r.ok
    except Exception as e:
        print(f"WARN: Email alert failed: {e}", file=sys.stderr)
        return False


def _alert(subject: str, body: str, sms_summary: str | None = None) -> None:
    """Fire SMS + email. Best-effort, swallows errors so alerting failures
    never crash the scraper itself."""
    creds = _get_creds()
    sms_text = sms_summary or f"{subject}\n\n{body[:200]}"
    sms_ok = _send_sms(sms_text, creds)
    email_ok = _send_email(subject, body, creds)
    print(f"ALERT: SMS={sms_ok} email={email_ok} | {subject}", file=sys.stderr)


def _read_heartbeat() -> dict:
    if not HEARTBEAT_FILE.exists():
        return {}
    try:
        return json.loads(HEARTBEAT_FILE.read_text())
    except Exception:
        return {}


def _write_heartbeat(payload: dict) -> None:
    try:
        HEARTBEAT_FILE.write_text(json.dumps(payload, indent=2))
    except Exception as e:
        print(f"WARN: heartbeat write failed: {e}", file=sys.stderr)


def _token_expiry_warning() -> str | None:
    """Return a warning string if the Graph refresh token is close to expiry,
    else None.

    The token cache is base64-decoded from GRAPH_TOKEN_CACHE_B64 env var or
    read from ~/Desktop/.graph_token_cache.bin. We extract the refresh token's
    issuance epoch and warn if we're past day 75 (90-day expiry)."""
    try:
        cache_b64 = os.getenv("GRAPH_TOKEN_CACHE_B64", "").strip()
        if cache_b64:
            cache = json.loads(base64.b64decode(cache_b64).decode("utf-8"))
        else:
            cache_path = Path.home() / "Desktop" / ".graph_token_cache.bin"
            if not cache_path.exists():
                return "No cached Graph token found anywhere — auth will fail next run"
            cache = json.loads(cache_path.read_text())

        rts = cache.get("RefreshToken", {})
        if not rts:
            return "Cache has no RefreshToken — auth may fail soon"
        # Refresh tokens carry "last_modification_time" or similar
        latest = max(
            (int(v.get("last_modification_time", 0)) for v in rts.values() if isinstance(v, dict)),
            default=0,
        )
        if latest:
            age_days = (datetime.now(timezone.utc).timestamp() - latest) / 86400
            if age_days > 75:
                return f"Graph refresh token is {int(age_days)} days old (~90d expiry). Run tools/refresh_graph_token.py soon."
    except Exception:
        return None
    return None


def safeguard_run(main_fn: Callable[[], None]) -> None:
    """Wrap the scraper's main() with full safeguard layers."""
    start = datetime.now(timezone.utc)
    run_iso = start.isoformat()

    # Stats accumulator that main() can update via tools.scraper_safeguards.record_stat()
    stats = {
        "run_start": run_iso,
        "emails_pulled": 0,
        "deals_parsed": 0,
        "buyers_matched": 0,
        "emails_sent": 0,
        "errors": [],
    }
    # Expose the dict so main() can mutate it in place
    sys.modules[__name__]._current_stats = stats

    err = None
    try:
        main_fn()
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        err = e
        tb = traceback.format_exc()
        # LAYER 1 — fatal exception alert
        sms = f"🚨 SCRAPER FATAL\n{type(e).__name__}: {str(e)[:120]}"
        email_body = (
            f"Scraper crashed at {run_iso}.\n\n"
            f"Exception: {type(e).__name__}: {e}\n\n"
            f"Traceback:\n{tb}\n\n"
            f"Stats so far: {json.dumps(stats, indent=2, default=str)}\n\n"
            f"Next steps:\n"
            f"1. Check Railway logs for context\n"
            f"2. Run audit: python3 tools/audit_scraper_accuracy.py\n"
            f"3. Common fixes:\n"
            f"   - Graph auth: python3 tools/refresh_graph_token.py\n"
            f"   - Salesforce auth: reset security token\n"
        )
        _alert(f"🚨 Scraper FATAL: {type(err).__name__}", email_body, sms_summary=sms)

    # Always write heartbeat (success or failure)
    end = datetime.now(timezone.utc)
    duration_s = (end - start).total_seconds()
    prev = _read_heartbeat()
    consecutive_zero = prev.get("consecutive_zero_runs", 0)

    # Update consecutive-zero counter
    if err is None:
        if stats["deals_parsed"] == 0 and stats["emails_pulled"] == 0:
            consecutive_zero += 1
        else:
            consecutive_zero = 0

    payload = {
        "last_run": run_iso,
        "last_run_duration_s": round(duration_s, 1),
        "last_run_ok": err is None,
        "last_run_error": str(err) if err else None,
        "stats": stats,
        "consecutive_zero_runs": consecutive_zero,
        "token_warning": _token_expiry_warning(),
    }
    _write_heartbeat(payload)

    # LAYER 2 — "ran but did nothing" alert (only fire ONCE per stretch)
    if err is None and consecutive_zero == ZERO_DEAL_ALERT_THRESHOLD:
        sms = f"⚠️ SCRAPER QUIET\n{ZERO_DEAL_ALERT_THRESHOLD} consecutive runs with 0 deals/emails. Check filters + auth."
        email_body = (
            f"Scraper has produced zero deals AND zero pulled emails for "
            f"{ZERO_DEAL_ALERT_THRESHOLD} consecutive runs.\n\n"
            f"This is unusual. Possible causes:\n"
            f"  - Auth quietly broken (no exception raised but Graph returns nothing)\n"
            f"  - senders.txt empty or all wholesalers paused outreach\n"
            f"  - Mailbox emptied by accident\n\n"
            f"Action:\n"
            f"  1. Run: python3 tools/audit_scraper_accuracy.py\n"
            f"  2. Check info@cheaphomesFLA.com inbox manually for new wholesaler emails\n"
            f"  3. Verify senders.txt looks right: cat ~/dealmatcher/senders.txt | wc -l\n"
        )
        _alert("⚠️ Scraper quiet for 3 runs", email_body, sms_summary=sms)

    # Token expiry warning
    if payload.get("token_warning"):
        sms = f"🔑 SCRAPER TOKEN\n{payload['token_warning']}"
        _alert("🔑 Scraper Graph token expiring soon", payload["token_warning"], sms_summary=sms)

    if err is not None:
        sys.exit(1)


def record_stat(key: str, value: int = 1) -> None:
    """Called from inside main() to update run statistics.

    Example:
        from tools.scraper_safeguards import record_stat
        record_stat("emails_pulled", n_pulled)
        record_stat("deals_parsed", len(deals))

    Safe to call when not running under safeguard_run() — does nothing.
    """
    stats = getattr(sys.modules[__name__], "_current_stats", None)
    if stats is None:
        return
    if key in stats:
        if isinstance(stats[key], list):
            stats[key].append(value)
        else:
            stats[key] += value
    else:
        stats[key] = value
