#!/usr/bin/env python3
"""
Today's deals report — generates ONE comprehensive markdown report covering:
  - Pipeline health (all 5 workers)
  - Scraper status (auth, heartbeat)
  - Email volume + WhatsApp volume in the last 24h
  - Per-wholesaler breakdown
  - Per-WhatsApp-group breakdown
  - Sample of clean parsed deals
  - Per-buyer matches today (from Salesforce)

Saves to ~/Desktop/todays_deals_report_YYYYMMDD_HHMM.md AND opens it.

Usage:
  python3 tools/todays_deals_report.py [--hours=24]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DESKTOP = Path.home() / "Desktop"

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--hours", type=int, default=24)
    return p.parse_args()


def http_json(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"_error": str(e)}


def main():
    args = parse_args()
    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=args.hours)).isoformat()

    out = [f"# Today's Deal Pipeline Report — {now.strftime('%Y-%m-%d %H:%M ET')}\n"]
    out.append(f"Window: last {args.hours} hours\n")
    out.append("---\n")

    # ─── 1. Pipeline health ───
    out.append("## 1. Pipeline Health (right now)\n")
    workers = [
        ("propertyleads-ppl-worker", "last_lead_at"),
        ("motivatedsellers-ppl-worker", "last_lead_at"),
        ("sendgrid-events", "last_event_at"),
        ("railway-deploy-alerts", "last_alert_at"),
        ("cheaphomesfla-whatsapp-webhook", "last_message_at"),
    ]
    out.append("| Worker | Status | Last activity |")
    out.append("|---|---|---|")
    for w, field in workers:
        data = http_json(f"https://{w}.cbfcalcio5.workers.dev/health")
        if data.get("_error"):
            out.append(f"| {w} | ✗ unreachable | — |")
        else:
            ts = data.get(field) or "(never)"
            out.append(f"| {w} | ✓ HTTP 200 | {ts} |")
    out.append("")

    # ─── 2. Scraper heartbeat ───
    out.append("## 2. Scraper Status\n")
    hb_file = REPO / "logs" / "scraper_heartbeat.json"
    if hb_file.exists():
        try:
            hb = json.loads(hb_file.read_text())
            out.append(f"- **Last run:** {hb.get('last_run', 'never')}")
            out.append(f"- **Status:** {'✓ OK' if hb.get('last_run_ok') else '✗ FAILED — ' + str(hb.get('last_run_error'))}")
            stats = hb.get("stats", {})
            for k in ("emails_pulled", "deals_parsed", "buyers_matched", "emails_sent"):
                if k in stats:
                    out.append(f"- {k}: **{stats[k]}**")
            if hb.get("token_warning"):
                out.append(f"- ⚠ {hb['token_warning']}")
        except Exception as e:
            out.append(f"⚠ couldn't read heartbeat: {e}")
    else:
        out.append("⚠ Heartbeat file missing — scraper hasn't run via main() yet (Railway service hasn't run since cloud auth fix).")
    out.append("")

    # ─── 3. Live scrape — what's in the inbox right now ───
    out.append(f"## 3. Live Test Scrape (last {args.hours}h)\n")
    try:
        from cheaphomesfla_scraper import (
            graph_access_token, fetch_new_messages, is_wholesaler_mail,
            parse_deals, SENDERS_FILE, load_wholesaler_addresses,
        )
        from parser import is_whatsapp_forward

        token = graph_access_token()
        msgs = fetch_new_messages(token, since)
        wholesalers = load_wholesaler_addresses()
        lookup = {}
        for raw in SENDERS_FILE.read_text().splitlines():
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            m = re.match(r"(.+?)\s*<([^>]+)>", raw)
            if m:
                lookup[m.group(2).lower().strip()] = m.group(1).strip()

        email_msgs = email_deals = wa_msgs = wa_deals = 0
        deals_per_email = defaultdict(int)
        msgs_per_email = defaultdict(int)
        deals_per_wa = defaultdict(int)
        msgs_per_wa = defaultdict(int)
        sample_deals = []
        bad_count = 0

        for msg in msgs:
            is_ws, addr = is_wholesaler_mail(msg, wholesalers)
            if not is_ws:
                continue
            subject = msg.get("subject", "") or ""
            sender = (msg.get("sender", {}).get("emailAddress", {}).get("address") or "").lower()
            try:
                deals = parse_deals(msg, addr, lookup)
            except Exception:
                continue
            is_wa = is_whatsapp_forward(subject, sender) or (addr and addr.startswith("wa:"))
            if is_wa:
                wa_msgs += 1
                wa_deals += len(deals)
                m = re.match(r"\[WA-(?:Group|DM)\]\s*(.+?)(?:\s*—\s*|$)", subject)
                chat = m.group(1).strip() if m else (subject[:40] or "(unknown)")
                deals_per_wa[chat] += len(deals)
                msgs_per_wa[chat] += 1
            else:
                email_msgs += 1
                email_deals += len(deals)
                display = lookup.get(addr, addr) if addr else "?"
                deals_per_email[display] += len(deals)
                msgs_per_email[display] += 1
            for d in deals[:5]:
                addr_str = d.get("property_address", "")
                price = d.get("asking_price")
                if addr_str and price and 30_000 <= price <= 5_000_000 and re.match(r"^\d+\s+\w", addr_str):
                    sample_deals.append((addr_str, price, d.get("beds"), d.get("sqft"), "📱WA" if is_wa else "📧Email"))
                else:
                    bad_count += 1

        out.append(f"### Totals\n")
        out.append(f"| Source | Messages | Deals |")
        out.append(f"|---|---|---|")
        out.append(f"| 📧 Email | {email_msgs} | {email_deals} |")
        out.append(f"| 📱 WhatsApp | {wa_msgs} | {wa_deals} |")
        out.append(f"| **Total** | **{email_msgs + wa_msgs}** | **{email_deals + wa_deals}** |\n")

        if email_msgs:
            out.append(f"### Top Email Sources\n")
            for sender, dc in sorted(deals_per_email.items(), key=lambda x: -x[1])[:15]:
                out.append(f"- `{sender}` — **{dc} deals** ({msgs_per_email[sender]} emails)")
            out.append("")

        if wa_msgs:
            out.append(f"### Top WhatsApp Groups\n")
            for chat, dc in sorted(deals_per_wa.items(), key=lambda x: -x[1])[:30]:
                out.append(f"- `{chat}` — **{dc} deals** ({msgs_per_wa[chat]} messages)")
            out.append("")
        else:
            out.append(f"⚠ No WhatsApp messages in this window. Check Green-API console.\n")

        if sample_deals:
            out.append(f"### Sample of Clean Parsed Deals (first 30)\n")
            for addr_str, price, beds, sqft, src in sample_deals[:30]:
                bd = f"{int(beds)}bd" if beds else "?bd"
                sf = f"{int(sqft):,} sqft" if sqft else "?sqft"
                out.append(f"- {src} `{addr_str}` — **${price:,}** ({bd}, {sf})")
            out.append("")

    except Exception as e:
        out.append(f"⚠ Live scrape failed: {e}")
        out.append("")

    # ─── 4. Today's SF activity ───
    out.append("## 4. Today's Salesforce Activity\n")
    try:
        # Reuse env loading from scraper
        env_file = REPO / ".env.cheaphomesfla"
        env = {}
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip()
        from simple_salesforce import Salesforce
        sf = Salesforce(
            username=env["SF_USERNAME"],
            password=env["SF_PASSWORD"],
            security_token=env["SF_SECURITY_TOKEN"],
            domain=env.get("SF_DOMAIN", "login"),
        )
        # New Leads today
        r = sf.query("SELECT COUNT(Id) c FROM Lead WHERE CreatedDate = TODAY")
        out.append(f"- **New Leads today:** {r['records'][0]['c']}")
        # By source
        try:
            r2 = sf.query("SELECT LeadSource, COUNT(Id) c FROM Lead WHERE CreatedDate = TODAY GROUP BY LeadSource")
            for row in r2["records"]:
                src = row.get("LeadSource") or "(unset)"
                out.append(f"  - {src}: {row['c']}")
        except Exception:
            pass
        # Buyer-deal Tasks
        r3 = sf.query("SELECT COUNT(Id) c FROM Task WHERE CreatedDate = TODAY AND Subject LIKE 'Deal:%'")
        out.append(f"- **Buyer-deal matches today:** {r3['records'][0]['c']}")
    except Exception as e:
        out.append(f"⚠ couldn't query SF: {e}")
    out.append("")

    # ─── 5. Save + open ───
    report_file = DESKTOP / f"todays_deals_report_{now.strftime('%Y%m%d_%H%M')}.md"
    report_file.write_text("\n".join(out))
    print(f"\n✓ Report saved to: {report_file}\n")
    # Open in default app (TextEdit)
    try:
        subprocess.run(["open", str(report_file)], check=False)
    except Exception:
        pass
    # Also print to stdout
    print("\n".join(out))


if __name__ == "__main__":
    main()
