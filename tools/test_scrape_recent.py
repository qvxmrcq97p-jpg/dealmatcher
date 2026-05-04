#!/usr/bin/env python3
"""
Test scrape — pulls the last N hours of mail from info@cheaphomesFLA.com,
runs filter + parser, reports what would happen WITHOUT touching Salesforce
or sending any emails.

Output:
  - Console summary
  - ~/Desktop/test_scrape_YYYYMMDD_HHMM.md (full report with samples)

Usage:
  python3 tools/test_scrape_recent.py [--hours=12] [--show-misses]

  --hours=N       Pull mail from last N hours (default 12)
  --show-misses   Also dump emails that DIDN'T match wholesaler/WA filters
                  (useful for spotting wholesalers not in senders.txt)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DESKTOP = Path.home() / "Desktop"

# Make scraper imports resolve
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

# Import the actual production functions so we test the SAME code paths.
from cheaphomesfla_scraper import (  # noqa: E402
    graph_access_token,
    fetch_new_messages,
    is_wholesaler_mail,
    parse_deals,
    SENDERS_FILE,
    load_wholesaler_addresses,
)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--hours", type=int, default=12)
    p.add_argument("--show-misses", action="store_true")
    p.add_argument("--max-misses", type=int, default=200)
    return p.parse_args()


def main():
    args = parse_args()
    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=args.hours)).isoformat()

    print(f"\n═══ TEST SCRAPE — last {args.hours} hours ═══")
    print(f"Window: {since}  →  {now.isoformat()}")
    print(f"(NO Salesforce writes. NO emails sent. Read-only inspection.)\n")

    # ─── 1. Auth ───
    print("→ Authenticating against Microsoft Graph...")
    try:
        token = graph_access_token()
        print(f"  ✓ Got access token ({len(token)} chars)\n")
    except Exception as e:
        print(f"  ✗ Auth failed: {e}\n")
        print("  → If the cache is stale: python3 tools/refresh_graph_token.py")
        sys.exit(1)

    # ─── 2. Pull messages ───
    print(f"→ Fetching messages received since {since}...")
    try:
        msgs = fetch_new_messages(token, since)
        print(f"  ✓ Pulled {len(msgs)} messages\n")
    except Exception as e:
        print(f"  ✗ Fetch failed: {e}\n")
        sys.exit(1)

    # ─── 3. Wholesaler filter ───
    wholesalers = load_wholesaler_addresses()
    lookup = {}
    for raw in SENDERS_FILE.read_text().splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        m = re.match(r"(.+?)\s*<([^>]+)>", raw)
        if m:
            lookup[m.group(2).lower().strip()] = m.group(1).strip()

    matches = []
    misses = []
    for msg in msgs:
        is_ws, addr = is_wholesaler_mail(msg, wholesalers)
        if is_ws:
            matches.append((msg, addr))
        else:
            misses.append(msg)

    print(f"→ Filter: {len(matches)} matched wholesaler/WA, {len(misses)} missed\n")

    # ─── 4. Parse each match ───
    all_deals = []
    parse_failures = []
    print(f"→ Parsing {len(matches)} wholesaler emails...\n")
    for msg, addr in matches:
        subj = (msg.get("subject") or "").strip()[:80]
        sender = addr or "?"
        try:
            deals = parse_deals(msg, addr, lookup)
            all_deals.extend(deals)
            mark = f"  ✓ [{len(deals):2d} deals] {sender:40s} | {subj}"
            print(mark)
        except Exception as e:
            parse_failures.append((subj, sender, str(e)))
            print(f"  ✗ [parse err] {sender:40s} | {subj} → {e}")

    print(f"\n→ Parse result: {len(all_deals)} total deals from {len(matches)} matched emails")
    if parse_failures:
        print(f"  ⚠ {len(parse_failures)} emails failed to parse cleanly")

    # ─── 5. Quality check on parsed deals ───
    print(f"\n═══ DEAL QUALITY SAMPLE ═══\n")
    bad_addr = []
    bad_price = []
    no_price = []

    for d in all_deals[:100]:
        addr = (d.get("address") or "").strip() if hasattr(d, "get") else getattr(d, "address", "")
        if not isinstance(d, dict):
            d = d.__dict__ if hasattr(d, "__dict__") else {"address": addr, "list_price": getattr(d, "list_price", None)}
        addr = d.get("property_address") or d.get("address", "")
        price = d.get("asking_price") or d.get("list_price") or d.get("price")
        # Basic address sanity: must have number + street word
        addr_ok = bool(re.match(r"^\d+\s+\w", addr or ""))
        if not addr_ok:
            bad_addr.append(addr)
            continue
        if not price:
            no_price.append((addr, "no price"))
        elif price < 30_000:
            bad_price.append((addr, price))
        elif price > 5_000_000:
            bad_price.append((addr, price))

    clean = len(all_deals) - len(bad_addr) - len(bad_price) - len(no_price)
    print(f"  Total parsed:        {len(all_deals)}")
    print(f"  ✓ Clean (addr+price): {clean}")
    print(f"  ⚠ No price:           {len(no_price)}")
    print(f"  ⚠ Suspicious price:   {len(bad_price)}")
    print(f"  ✗ Bad address:        {len(bad_addr)}")

    # Show samples
    print(f"\n--- Sample of CLEAN deals (first 10) ---")
    n = 0
    for d in all_deals:
        if not isinstance(d, dict):
            d = d.__dict__ if hasattr(d, "__dict__") else {}
        addr = d.get("property_address") or d.get("address", "")
        price = d.get("asking_price") or d.get("list_price") or d.get("price")
        if addr and price and 30_000 <= price <= 5_000_000 and re.match(r"^\d+\s+\w", addr):
            beds = d.get("beds") or "?"
            sqft = d.get("sqft") or "?"
            print(f"  • {addr:50s} ${price:>10,}  ({beds} bd, {sqft} sqft)")
            n += 1
            if n >= 10:
                break

    if bad_price:
        print(f"\n--- Sample SUSPICIOUS prices (need parser fix) ---")
        for addr, price in bad_price[:5]:
            print(f"  ✗ {addr} → ${price:,}")

    if bad_addr:
        print(f"\n--- Sample BAD addresses ---")
        for addr in bad_addr[:5]:
            print(f"  ✗ {addr!r}")

    # ─── 6. Misses (optional) ───
    if args.show_misses and misses:
        print(f"\n═══ EMAILS THAT DIDN'T MATCH FILTERS (first {min(args.max_misses, len(misses))}) ═══\n")
        print("(These bypassed the scraper. If any are wholesalers, add their address to senders.txt.)\n")
        for m in misses[:args.max_misses]:
            sender = m.get("from", {}).get("emailAddress", {}).get("address", "?")
            subj = (m.get("subject") or "").strip()[:80]
            print(f"  ? {sender:50s} | {subj}")

    # ─── 7. Save report to Desktop ───
    out_file = DESKTOP / f"test_scrape_{now.strftime('%Y%m%d_%H%M')}.md"
    report = []
    report.append(f"# Test Scrape Report — {now.strftime('%Y-%m-%d %H:%M ET')}\n")
    report.append(f"Window: last {args.hours} hours\n")
    report.append(f"## Summary\n")
    report.append(f"- Pulled: **{len(msgs)} messages**")
    report.append(f"- Wholesaler/WA filtered: **{len(matches)}**")
    report.append(f"- Missed (not in senders.txt): **{len(misses)}**")
    report.append(f"- Parsed deals total: **{len(all_deals)}**")
    report.append(f"- Parse failures: **{len(parse_failures)}**")
    report.append(f"- Clean (addr+price valid): **{clean}**")
    report.append(f"- No-price: {len(no_price)}, suspicious-price: {len(bad_price)}, bad-addr: {len(bad_addr)}\n")

    if parse_failures:
        report.append("## Parse Failures\n")
        for subj, sender, err in parse_failures:
            report.append(f"- **{sender}**: `{subj}` — {err}")
        report.append("")

    report.append("## Sample CLEAN deals (first 25)\n")
    n = 0
    for d in all_deals:
        if not isinstance(d, dict):
            d = d.__dict__ if hasattr(d, "__dict__") else {}
        addr = d.get("property_address") or d.get("address", "")
        price = d.get("asking_price") or d.get("list_price") or d.get("price")
        if addr and price and 30_000 <= price <= 5_000_000:
            report.append(f"- `{addr}` — ${price:,} (beds: {d.get('beds', '?')}, sqft: {d.get('sqft', '?')})")
            n += 1
            if n >= 25:
                break

    if args.show_misses and misses:
        report.append(f"\n## Misses (potential new senders to add)\n")
        for m in misses[:args.max_misses]:
            sender = m.get("from", {}).get("emailAddress", {}).get("address", "?")
            subj = (m.get("subject") or "").strip()[:80]
            report.append(f"- `{sender}` — {subj}")

    out_file.write_text("\n".join(report))
    print(f"\n📝 Full report saved to: {out_file}\n")


if __name__ == "__main__":
    main()
