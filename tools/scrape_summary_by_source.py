#!/usr/bin/env python3
"""
Scrape summary by source — shows how many deals came from email vs WhatsApp,
broken down per wholesaler and per WhatsApp group.

Read-only. No SF writes, no emails sent.

Usage:
  python3 tools/scrape_summary_by_source.py [--hours=12]
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DESKTOP = Path.home() / "Desktop"

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from cheaphomesfla_scraper import (  # noqa: E402
    graph_access_token,
    fetch_new_messages,
    is_wholesaler_mail,
    parse_deals,
    SENDERS_FILE,
    load_wholesaler_addresses,
)
from parser import is_whatsapp_forward  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--hours", type=int, default=12)
    return p.parse_args()


def main():
    args = parse_args()
    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=args.hours)).isoformat()

    print(f"\n═══ DEAL SOURCE SUMMARY — last {args.hours} hours ═══")
    print(f"Window: {since}  →  {now.isoformat()}\n")

    print("→ Authenticating + fetching messages...")
    token = graph_access_token()
    msgs = fetch_new_messages(token, since)
    print(f"  ✓ {len(msgs)} messages pulled\n")

    wholesalers = load_wholesaler_addresses()
    lookup = {}
    for raw in SENDERS_FILE.read_text().splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        m = re.match(r"(.+?)\s*<([^>]+)>", raw)
        if m:
            lookup[m.group(2).lower().strip()] = m.group(1).strip()

    # Per-source tallies
    email_msgs = 0
    email_deals = 0
    wa_msgs = 0
    wa_deals = 0

    deals_per_email_sender = defaultdict(int)   # display name → deal count
    msgs_per_email_sender = defaultdict(int)
    deals_per_wa_group = defaultdict(int)       # group/chat name → deal count
    msgs_per_wa_chat = defaultdict(int)

    for msg in msgs:
        is_ws, addr = is_wholesaler_mail(msg, wholesalers)
        if not is_ws:
            continue

        subject = msg.get("subject", "") or ""
        sender = (msg.get("sender", {}).get("emailAddress", {}).get("address") or "").lower()

        try:
            deals = parse_deals(msg, addr, lookup)
        except Exception:
            deals = []

        # Classify: email vs WhatsApp forward
        is_wa = is_whatsapp_forward(subject, sender) or (addr and addr.startswith("wa:"))

        if is_wa:
            wa_msgs += 1
            wa_deals += len(deals)
            # Group/chat name from subject (e.g. "[WA-Group] Deal Group ABC — Sender")
            m = re.match(r"\[WA-(?:Group|DM)\]\s*(.+?)(?:\s*—\s*|$)", subject)
            chat = m.group(1).strip() if m else (subject[:40] or "(unknown)")
            deals_per_wa_group[chat] += len(deals)
            msgs_per_wa_chat[chat] += 1
        else:
            email_msgs += 1
            email_deals += len(deals)
            display = lookup.get(addr, addr) if addr else "(no sender)"
            deals_per_email_sender[display] += len(deals)
            msgs_per_email_sender[display] += 1

    # ─── Print summary ───
    print("═══ TOTALS ═══")
    print(f"  Email side:")
    print(f"    Messages:  {email_msgs}")
    print(f"    Deals:     {email_deals}")
    print()
    print(f"  WhatsApp side:")
    print(f"    Messages:  {wa_msgs}")
    print(f"    Deals:     {wa_deals}")
    print()
    print(f"  Combined: {email_msgs + wa_msgs} messages → {email_deals + wa_deals} deals")
    print()

    # ─── Email breakdown ───
    if email_msgs:
        print("═══ EMAIL SOURCES (top wholesalers by deal count) ═══")
        sorted_email = sorted(deals_per_email_sender.items(), key=lambda x: -x[1])
        for sender, dcount in sorted_email[:20]:
            mcount = msgs_per_email_sender[sender]
            print(f"  {dcount:4d} deals from {sender:50s} ({mcount} email{'s' if mcount != 1 else ''})")
        print()

    # ─── WhatsApp breakdown ───
    if wa_msgs:
        print("═══ WHATSAPP SOURCES (top groups/chats by deal count) ═══")
        sorted_wa = sorted(deals_per_wa_group.items(), key=lambda x: -x[1])
        for chat, dcount in sorted_wa[:30]:
            mcount = msgs_per_wa_chat[chat]
            print(f"  {dcount:4d} deals from {chat:50s} ({mcount} message{'s' if mcount != 1 else ''})")
        print()

    if not wa_msgs:
        print("⚠ No WhatsApp messages in this window.")
        print("  This could mean:")
        print("  - Green-API webhook isn't firing (check console.green-api.com)")
        print("  - WhatsApp Web session disconnected on the Green-API side")
        print("  - Just a quiet window (try --hours=24 or --hours=48)")
        print()

    # ─── Save report ───
    report_file = DESKTOP / f"deal_source_summary_{now.strftime('%Y%m%d_%H%M')}.md"
    lines = [
        f"# Deal Source Summary — {now.strftime('%Y-%m-%d %H:%M ET')}\n",
        f"Window: last {args.hours} hours\n",
        f"## Totals\n",
        f"| Source | Messages | Deals |",
        f"|---|---|---|",
        f"| Email | {email_msgs} | {email_deals} |",
        f"| WhatsApp | {wa_msgs} | {wa_deals} |",
        f"| **Total** | **{email_msgs + wa_msgs}** | **{email_deals + wa_deals}** |\n",
    ]
    if email_msgs:
        lines.append("## Email sources\n")
        for sender, dcount in sorted(deals_per_email_sender.items(), key=lambda x: -x[1]):
            lines.append(f"- `{sender}` — **{dcount} deals** ({msgs_per_email_sender[sender]} emails)")
        lines.append("")
    if wa_msgs:
        lines.append("## WhatsApp sources\n")
        for chat, dcount in sorted(deals_per_wa_group.items(), key=lambda x: -x[1]):
            lines.append(f"- `{chat}` — **{dcount} deals** ({msgs_per_wa_chat[chat]} messages)")
        lines.append("")
    report_file.write_text("\n".join(lines))
    print(f"📝 Saved report to: {report_file}\n")


if __name__ == "__main__":
    main()
