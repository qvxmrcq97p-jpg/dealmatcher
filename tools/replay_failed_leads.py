#!/usr/bin/env python3
"""
Replay failed Motivated Sellers PPL leads — finds every failure-alert email
in info@cheaphomesFLA.com inbox, extracts the raw payload that the worker
attached, and re-POSTs each one to the (now-fixed) worker.

Reuses the scraper's Graph auth so no extra setup needed.

Usage:
    python3 tools/replay_failed_leads.py [--dry-run] [--days=7]

Output: per-payload status, plus a saved CSV of recovered Lead IDs.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DESKTOP = Path.home() / "Desktop"

# Reuse scraper auth + fetch
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

WORKER_URL = "https://motivatedsellers-ppl-worker.cbfcalcio5.workers.dev/"

FAILURE_SUBJECT_PAT = re.compile(r"Motivated Sellers PPL FAILURE", re.I)
PAYLOAD_PAT = re.compile(r"Full raw payload:\s*\n(\{.*?\n\})", re.DOTALL)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=14, help="Search inbox over last N days")
    p.add_argument("--dry-run", action="store_true", help="Show what would replay, don't actually POST")
    p.add_argument("--limit", type=int, default=200)
    return p.parse_args()


def main():
    args = parse_args()
    import requests

    from cheaphomesfla_scraper import (
        graph_access_token,
        TARGET_MAILBOX,
    )

    # Override target mailbox: failure alerts go to info@johnsonbuys.com (the
    # ALERT_TO env var on the worker), NOT info@cheaphomesFLA.com (which is
    # what the scraper reads). Search the right inbox.
    ALERT_MAILBOX = "info@johnsonbuys.com"

    def fetch_alert_emails(token: str, since_iso: str) -> list[dict]:
        """Pull mail from the alerts mailbox since `since_iso`."""
        import urllib.parse
        url = f"https://graph.microsoft.com/v1.0/users/{ALERT_MAILBOX}/messages"
        params = {
            "$top": 100,
            "$select": "id,subject,body,receivedDateTime",
            "$orderby": "receivedDateTime desc",
            "$filter": f"receivedDateTime gt {since_iso} and contains(subject, 'Motivated Sellers PPL FAILURE')",
        }
        results = []
        headers = {"Authorization": f"Bearer {token}"}
        while url:
            r = requests.get(url, headers=headers, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            results.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
            params = {}
        return results

    print(f"\n═══ REPLAY FAILED LEADS — last {args.days} days ═══\n")
    print("→ Authenticating Microsoft Graph...")
    token = graph_access_token()
    print(f"  ✓ Got token\n")

    # Pull failure alerts from the JB mailbox (where worker's ALERT_TO sends to)
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
    print(f"→ Searching {ALERT_MAILBOX} for failure alerts since {since}...")
    alerts = fetch_alert_emails(token, since)
    print(f"  ✓ Found {len(alerts)} 'Motivated Sellers PPL FAILURE' alert email(s)\n")

    if not alerts:
        print("Nothing to recover. ✓\n")
        return

    # Sort oldest first (so SF Lead create order matches original lead timestamp)
    alerts.sort(key=lambda m: m.get("receivedDateTime", ""))

    # Deduplicate by lead_id (in case multiple alerts for same lead)
    seen_ids = set()
    payloads = []
    for m in alerts:
        body = (m.get("body", {}).get("content") or "")
        # Strip HTML tags before regex
        body_text = re.sub(r"<[^>]+>", "\n", body)
        body_text = re.sub(r"&nbsp;", " ", body_text)
        body_text = re.sub(r"&amp;", "&", body_text)

        m_payload = PAYLOAD_PAT.search(body_text)
        if not m_payload:
            print(f"  ⚠ Couldn't extract payload from email: {m.get('subject', '')[:60]}")
            continue
        try:
            payload = json.loads(m_payload.group(1))
        except Exception as e:
            print(f"  ⚠ Bad JSON in email: {e}")
            continue
        lead_id = payload.get("lead_id") or payload.get("key") or payload.get("id")
        if lead_id and lead_id in seen_ids:
            continue
        if lead_id:
            seen_ids.add(lead_id)
        payloads.append((m.get("receivedDateTime"), payload))

    print(f"→ Extracted {len(payloads)} unique payload(s) ready to replay\n")

    if args.dry_run:
        print("DRY-RUN — not POSTing. Sample payloads:\n")
        for ts, p in payloads[:5]:
            print(f"  {ts}: {p.get('first_name', '?')} {p.get('last_name', '?')} ({p.get('phone', '?')})")
        if len(payloads) > 5:
            print(f"  ... and {len(payloads) - 5} more")
        return

    # Replay each — small delay between to avoid hammering Twilio/SF
    results = []
    for i, (ts, payload) in enumerate(payloads[:args.limit], 1):
        name = f"{payload.get('first_name', '')} {payload.get('last_name', '')}".strip() or "(no name)"
        print(f"  [{i}/{len(payloads)}] {ts[:16]} {name:30s}", end="", flush=True)
        try:
            r = requests.post(
                WORKER_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            data = r.json()
            sf_id = data.get("sf_lead_id")
            errs = data.get("errors", [])
            if sf_id:
                print(f"  ✓ SF: {sf_id}")
                results.append({"ts": ts, "name": name, "sf_lead_id": sf_id, "errors": errs})
            else:
                print(f"  ✗ NO SF ID — errors: {errs}")
                results.append({"ts": ts, "name": name, "sf_lead_id": None, "errors": errs})
        except Exception as e:
            print(f"  ✗ POST failed: {e}")
            results.append({"ts": ts, "name": name, "sf_lead_id": None, "errors": [str(e)]})
        time.sleep(0.4)

    # Save report
    report_file = DESKTOP / f"replayed_leads_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    report_file.write_text(json.dumps(results, indent=2))
    print(f"\n📝 Report saved to: {report_file}")

    success = sum(1 for r in results if r.get("sf_lead_id"))
    fail = len(results) - success
    print(f"\n═══ DONE ═══")
    print(f"Recovered: {success} / {len(results)}")
    if fail:
        print(f"⚠ Still failed: {fail}")
        print("These leads need manual SF entry — see report above for details.")


if __name__ == "__main__":
    main()
