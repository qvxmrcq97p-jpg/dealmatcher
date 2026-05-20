#!/usr/bin/env python3
"""
send_bucket_b_test.py — render Bucket B from the last scrape dump and send it
ONLY to a single test address (default info@cheaphomesfla.com), with a [TEST]
subject prefix.

This is the safety gate added 2026-05-20 after a 1-deal / $275B campaign shipped
to the full 22K list. Nothing goes to the real list until the EXACT campaign
HTML has landed in the operator's inbox and been eyeballed.

The test render goes through the identical code path the real send uses
(deals_from_scraper_payload → build_cc_statewide), so what you see in your
inbox is byte-for-byte what the real blast would send from the same dump.

Usage:
    python3 tools/send_bucket_b_test.py [test_email]

Exit codes:
    0  test email sent
    2  deal-count floor not met (too few deals — would abort the real send too)
    3  render or send error
"""
from __future__ import annotations

import os
import sys
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# ── Load env (same file the scraper uses) ────────────────────────────
ENV_FILE = Path.home() / "dealmatcher" / ".env.cheaphomesfla"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

import requests  # noqa: E402
from tools.cc_html_builder import _bootstrap_desktop_shim, deals_from_scraper_payload  # noqa: E402
_bootstrap_desktop_shim()
import deal_matcher as dm  # noqa: E402

# Must match the scraper's floor exactly.
MIN_DEALS_FOR_BLAST = int(os.getenv("MIN_DEALS_FOR_BLAST", "15"))
DUMP = Path.home() / "Desktop" / "deal_scraper_last_run_deals.json"

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
FROM_EMAIL = "info@cheaphomesFLA.com"
FROM_NAME = "Chris Johnson"
REPLY_TO = "info@cheaphomesFLA.com"


def main() -> int:
    test_to = sys.argv[1] if len(sys.argv) > 1 else "info@cheaphomesfla.com"

    if not DUMP.exists():
        print(f"❌ No dump at {DUMP}. Run the scrape (dry-run) step first.")
        return 3

    raw = json.loads(DUMP.read_text())
    deals = deals_from_scraper_payload(raw)
    for d in deals:
        if not d.county and d.zip_code:
            d.county = dm.county_from_zip(d.zip_code)

    n = len(deals)
    print(f"Loaded {n} deals from {DUMP.name}")

    # ── Deal-count floor — same rule as the real send ───────────────
    if n < MIN_DEALS_FOR_BLAST:
        print(f"🚨 DEAL-COUNT FLOOR: only {n} deal(s) (floor={MIN_DEALS_FOR_BLAST}). "
              f"The real send would ABORT this. Not sending a test of a near-empty "
              f"blast. Re-scrape with a full 24h window and check the count.")
        return 2

    # ── Render through the real code path ───────────────────────────
    try:
        subject, html = dm.build_cc_statewide(deals)
    except Exception as e:  # noqa: BLE001
        print(f"❌ Render failed: {e}")
        return 3

    # Guard accounting so the operator sees what was scrubbed
    price_drops = sum(1 for d in deals if getattr(d, "price_dropped_reason", None))
    arv_drops = sum(1 for d in deals if getattr(d, "arv_dropped_reason", None))
    spec_drops = sum(1 for d in deals if getattr(d, "specs_dropped_reasons", None))
    print(f"  guards: price={price_drops} arv={arv_drops} specs={spec_drops} nulled")

    test_subject = f"[TEST — DO NOT FORWARD] {subject}"
    payload = {
        "personalizations": [{"to": [{"email": test_to, "name": "Chris (TEST)"}]}],
        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
        "reply_to": {"email": REPLY_TO},
        "subject": test_subject,
        "content": [{"type": "text/html", "value": html}],
    }
    try:
        r = requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {SENDGRID_API_KEY}",
                     "Content-Type": "application/json"},
            json=payload, timeout=30,
        )
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        body = getattr(getattr(e, "response", None), "text", "")
        print(f"❌ SendGrid test send failed: {e}  {body[:300]}")
        return 3

    print(f"✅ TEST email sent to {test_to}")
    print(f"   Subject: {test_subject}")
    print(f"   {n} deals · check your inbox before approving the real blast.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
