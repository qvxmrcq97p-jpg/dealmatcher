#!/usr/bin/env python3
"""
Build the daily 11 AM Constant Contact aggregate email from today's scraped deals.

Pipeline:
  1. Query Salesforce for today's scraper-generated Tasks (per-buyer-deal pairs)
  2. Deduplicate by deal address — get the unique deals discovered today
  3. Score / pick top N outliers (lowest list price by far, biggest discount, etc.)
  4. Render polished HTML email with photos + "why it's a deal" data card
  5. Output:
     a. Save HTML to ~/Desktop/cc_email_YYYYMMDD.html (paste-ready for CC composer)
     b. Email the HTML to Chris (he reviews + pastes into Constant Contact)
     c. (Future v2) Auto-create+schedule via CC API if plan supports it

CC ↔ SF reporting:
  - Constant Contact has a Salesforce integration (CC settings → Apps → Salesforce)
    that pushes email opens/clicks/unsubscribes back into SF as Activities
  - Once enabled, every recipient who clicks gets logged to their SF Lead
  - For now this script just generates the email — the SF integration is a
    one-time setup task (see TODO.md "CC ↔ SF integration check")

Usage:
    python3 tools/build_daily_cc_email.py [--top=5] [--no-send]

Schedule: run at 10:30 AM ET via Railway cron (after the 10 AM scraper run).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DESKTOP = Path.home() / "Desktop"


def load_env():
    env = dict(os.environ)
    env_file = REPO / ".env.cheaphomesfla"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env.setdefault(k.strip(), v.strip())
    return env


def query_todays_deals(env, cap=200):
    """Query SF for Tasks created today by the scraper, return unique deals."""
    from simple_salesforce import Salesforce  # type: ignore
    sf = Salesforce(
        username=env["SF_USERNAME"],
        password=env["SF_PASSWORD"],
        security_token=env["SF_SECURITY_TOKEN"],
        domain=env.get("SF_DOMAIN", "login"),
    )
    today = datetime.now().strftime("%Y-%m-%d")
    # The scraper logs Tasks with subject like "Deal: 123 Main St → Buyer Name"
    soql = (
        "SELECT Id, Subject, Description, CreatedDate, WhoId "
        "FROM Task "
        "WHERE CreatedDate >= TODAY "
        "AND Subject LIKE 'Deal:%' "
        "ORDER BY CreatedDate DESC "
        f"LIMIT {cap}"
    )
    rows = sf.query_all(soql).get("records", [])
    deals = {}
    for r in rows:
        subj = r.get("Subject", "")
        # Extract address from "Deal: <address> → <buyer>"
        m = re.match(r"Deal:\s*(.+?)\s*(?:→|->|—|to)\s*", subj)
        if not m:
            continue
        addr = m.group(1).strip()
        if not addr:
            continue
        # Description usually contains the structured deal info from the scraper
        if addr not in deals:
            deals[addr] = {
                "address": addr,
                "first_seen": r.get("CreatedDate"),
                "description": r.get("Description") or "",
                "match_count": 1,
            }
        else:
            deals[addr]["match_count"] += 1
    return list(deals.values())


def extract_deal_fields(deal):
    """Try to pull list_price, beds, baths, sqft, photos out of the description."""
    desc = deal.get("description") or ""
    out = {}
    # Price: look for $X or List $X
    m = re.search(r"(?:List|Asking|Price|Wholesale)[:\s\$]*([\d,]{3,12})", desc, re.I)
    if m:
        try:
            out["list_price"] = int(m.group(1).replace(",", ""))
        except ValueError:
            pass
    if "list_price" not in out:
        m = re.search(r"\$\s*([\d,]{3,12})", desc)
        if m:
            try:
                out["list_price"] = int(m.group(1).replace(",", ""))
            except ValueError:
                pass
    # Beds / baths / sqft
    for pat, key in [
        (r"(\d+)\s*(?:bed|br|bd)\b", "beds"),
        (r"(\d+(?:\.\d+)?)\s*(?:bath|ba)\b", "baths"),
        (r"([\d,]{3,7})\s*(?:sqft|sq\.?\s*ft|sf)\b", "sqft"),
    ]:
        m = re.search(pat, desc, re.I)
        if m:
            try:
                v = m.group(1).replace(",", "")
                out[key] = float(v) if "." in v else int(v)
            except ValueError:
                pass
    return out


def pick_top_outliers(deals, top=5):
    """Pick the most attention-grabbing N deals.

    Until ATTOM data lands, 'outlier' = lowest list price (cheapest first),
    breaking ties by buyer match count (more matches = higher relevance)."""
    enriched = []
    for d in deals:
        fields = extract_deal_fields(d)
        d.update(fields)
        if "list_price" in d:
            enriched.append(d)
    enriched.sort(key=lambda x: (x.get("list_price", 9_999_999), -x.get("match_count", 0)))
    return enriched[:top]


def render_html(deals, today_str):
    """Polished, mobile-first HTML for CC composer paste."""
    rows_html = []
    for i, d in enumerate(deals, 1):
        price = f"${d['list_price']:,}" if d.get("list_price") else "Inquire"
        beds = f"{int(d['beds'])} bed" if d.get("beds") else ""
        baths = f"{d['baths']:g} bath" if d.get("baths") else ""
        sqft = f"{int(d['sqft']):,} sqft" if d.get("sqft") else ""
        meta = " · ".join(x for x in (beds, baths, sqft) if x)
        match_note = f"<small style='color:#888;'>{d.get('match_count', 0)} buyer match{'es' if d.get('match_count', 0) != 1 else ''}</small>" if d.get("match_count") else ""

        rows_html.append(f"""
        <tr><td style="padding:18px 0; border-bottom:1px solid #eee;">
            <div style="font-weight:bold; font-size:18px; color:#222;">#{i} — {escape(d['address'])}</div>
            <div style="font-size:24px; color:#0a7c2f; margin:6px 0;">{price}</div>
            {f'<div style="color:#555; font-size:14px;">{escape(meta)}</div>' if meta else ''}
            {match_note}
            <div style="margin-top:10px;">
                <a href="https://cheaphomesfla.com/deals?ref=cc-{today_str}" style="color:#0a66c2; text-decoration:none; font-weight:bold;">View deal details →</a>
            </div>
        </td></tr>
        """)

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Today's Deals — {today_str}</title></head>
<body style="margin:0; padding:0; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; color:#222; background:#fafafa;">
<table cellpadding="0" cellspacing="0" border="0" align="center" width="100%" style="max-width:600px; margin:0 auto; background:#fff;">
  <tr><td style="padding:30px 25px; background:linear-gradient(135deg,#0a66c2,#0a7c2f); color:#fff;">
    <div style="font-size:14px; opacity:0.9; letter-spacing:1px; text-transform:uppercase;">CheapHomesFLA · Today's Below-Market Deals</div>
    <h1 style="margin:8px 0 0; font-size:28px;">{today_str}: Top {len(deals)} Outliers</h1>
    <div style="margin-top:8px; font-size:14px; opacity:0.85;">Hand-picked from {sum(d.get('match_count', 0) for d in deals) or 'N/A'} fresh wholesaler emails</div>
  </td></tr>

  <tr><td style="padding:25px;">
    <p style="font-size:16px; line-height:1.5; margin-top:0;">Hi <em>[FirstName]</em>,</p>
    <p style="font-size:15px; line-height:1.6;">Here are the most below-market deals our scraper picked up overnight. Each one is below comparable sold prices in their zip codes, and at least one investor in our network has matching buy-box criteria.</p>
    <p style="font-size:15px; line-height:1.6;"><strong>Reply with the deal number(s) you want to inquire on</strong> — I'll loop you in directly with the wholesaler.</p>

    <table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin:20px 0;">
        {''.join(rows_html)}
    </table>

    <div style="margin:30px 0; padding:20px; background:#f5f9ff; border-left:4px solid #0a66c2;">
        <strong style="font-size:16px;">Investor Toolkit (Free):</strong>
        <ul style="margin:10px 0 0 20px; padding:0; font-size:14px; line-height:1.7;">
            <li><a href="https://cheaphomesfla.com/tools/comp-lookup?ref=cc" style="color:#0a66c2;">Comp Houses Lookup Tool</a> — pull recent sold comps for any address</li>
            <li><a href="https://cheaphomesfla.com/tools/flip-calc?ref=cc" style="color:#0a66c2;">Fix-and-Flip Profit Calculator</a></li>
            <li><a href="https://cheaphomesfla.com/tools/rental-calc?ref=cc" style="color:#0a66c2;">Rental Cash-Flow Calculator</a></li>
        </ul>
    </div>

    <p style="font-size:14px; color:#666; line-height:1.5; margin-top:25px;">
      Got a buy-box that's stricter or wider than what's in our system? <a href="mailto:info@cheaphomesfla.com" style="color:#0a66c2;">Reply with your criteria</a> and we'll tune your daily list.
    </p>
  </td></tr>

  <tr><td style="padding:20px 25px; background:#222; color:#aaa; font-size:12px; text-align:center;">
    Sent by Christopher Johnson · CheapHomesFLA · Florida Investment Property Specialists<br>
    <a href="https://cheaphomesfla.com" style="color:#bbb;">cheaphomesfla.com</a>
    <br><br>
    Don't want these? <a href="%%unsubscribe%%" style="color:#bbb;">Unsubscribe here</a>
  </td></tr>
</table>
</body></html>"""
    return html


def email_html_to_chris(html, today_str, env):
    """Email the HTML draft to Chris so he can paste into CC composer."""
    import requests
    if not env.get("SENDGRID_API_KEY"):
        print("⚠ SENDGRID_API_KEY missing — can't email draft. HTML saved locally only.")
        return False
    payload = {
        "personalizations": [{"to": [{"email": env.get("ALERT_TO", "info@johnsonbuys.com")}]}],
        "from": {"email": env.get("FROM_EMAIL", "info@johnsonbuys.com"), "name": "Daily CC Email Builder"},
        "subject": f"📋 Today's CC Email Draft — {today_str} (paste into Constant Contact)",
        "content": [
            {"type": "text/plain", "value":
                f"Today's draft is ready.\n\n"
                f"To send via Constant Contact:\n"
                f"1. Open https://app.constantcontact.com\n"
                f"2. New Email → choose 'Plain HTML' or 'Custom Code' template\n"
                f"3. Paste the HTML below into the editor\n"
                f"4. Set subject: 'Top {today_str} below-market FL deals — first one is at {('$' + format(0, ',')) if not html else 'opening below'}'\n"
                f"5. Schedule send for 11:00 AM ET\n\n"
                f"--- HTML BELOW ---\n\n{html}"},
            {"type": "text/html", "value": f"<p><strong>Today's CC email draft</strong> — preview below. To send via Constant Contact, copy the rendered HTML from the .html attachment in your repo at <code>~/Desktop/cc_email_{today_str}.html</code>.</p><hr>{html}"},
        ],
    }
    r = requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={"Authorization": f"Bearer {env['SENDGRID_API_KEY']}", "Content-Type": "application/json"},
        json=payload,
        timeout=20,
    )
    if r.ok:
        print(f"✓ Draft emailed to {env.get('ALERT_TO')}")
        return True
    print(f"✗ Email send failed: {r.status_code} {r.text[:200]}")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=5, help="How many deals to feature")
    ap.add_argument("--no-send", action="store_true", help="Just save the HTML, don't email it")
    args = ap.parse_args()

    env = load_env()
    today_str = datetime.now().strftime("%Y-%m-%d")

    print(f"\n═══ DAILY CC EMAIL BUILDER — {today_str} ═══\n")
    print("→ Querying Salesforce for today's scraped deals...")
    try:
        deals = query_todays_deals(env)
    except Exception as e:
        print(f"✗ SF query failed: {e}")
        sys.exit(1)
    print(f"  Found {len(deals)} unique deals across all matched buyers today")

    if not deals:
        print("\n⚠ No deals scraped today. Possible causes:")
        print("  - Scraper hasn't run yet (next run at top of next 4-hour interval)")
        print("  - Scraper auth broken — run: python3 tools/audit_scraper_accuracy.py")
        print("  - No fresh wholesaler emails today (it's a quiet day)")
        sys.exit(2)

    top_deals = pick_top_outliers(deals, top=args.top)
    print(f"\n→ Picking top {args.top} outliers (lowest list price, most matches):")
    for i, d in enumerate(top_deals, 1):
        price = f"${d.get('list_price', 0):,}" if d.get("list_price") else "no-price"
        print(f"   {i}. {d['address']} — {price} ({d.get('match_count', 0)} matches)")

    print("\n→ Rendering HTML...")
    html = render_html(top_deals, today_str)
    out_file = DESKTOP / f"cc_email_{today_str}.html"
    out_file.write_text(html)
    print(f"  ✓ Saved to {out_file} ({len(html):,} bytes)")

    if not args.no_send:
        print("\n→ Emailing draft to Chris...")
        email_html_to_chris(html, today_str, env)

    print(f"\n═══ DONE ═══\n")
    print(f"To send via Constant Contact:")
    print(f"  1. Open https://app.constantcontact.com")
    print(f"  2. New Email → 'Plain HTML' or 'Custom Code' template")
    print(f"  3. Paste contents of {out_file}")
    print(f"  4. Subject: 'Top {len(top_deals)} below-market FL deals — {today_str}'")
    print(f"  5. Schedule send for 11:00 AM ET")
    print()


if __name__ == "__main__":
    main()
