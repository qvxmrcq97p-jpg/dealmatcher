#!/usr/bin/env python3
"""
Preview tonight's CC email — organized by Florida county, with source
attribution per deal, fully deduplicated.

Output:
  - Console: per-county count + top deals
  - ~/Desktop/preview_email_by_county_YYYYMMDD.html (open in browser to see)
  - ~/Desktop/preview_email_by_county_YYYYMMDD.md (markdown report)

Usage:
  python3 tools/preview_email_by_county.py [--hours=24] [--top-per-county=3]
"""
from __future__ import annotations

import argparse
import re
import sys
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DESKTOP = Path.home() / "Desktop"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from cheaphomesfla_scraper import (  # noqa: E402
    graph_access_token, fetch_new_messages, is_wholesaler_mail,
    parse_deals, SENDERS_FILE, load_wholesaler_addresses,
    collapse_cross_posted,
)
from tools.geocode_address import lookup as geocode_lookup  # noqa: E402

# Florida ZIP-to-county mapping (top-traffic zips for FL real estate scraping).
# Source: USPS data (compressed; only major investor-zip counties included).
# This isn't exhaustive — extend as needed.
FL_ZIP_COUNTY = {}
def _build_zip_county_map():
    # Major Florida zip ranges by county
    ranges = [
        ("Miami-Dade", [(33010, 33299)]),
        ("Broward",    [(33004, 33076), (33301, 33394)]),
        ("Palm Beach", [(33401, 33499)]),
        ("Hillsborough", [(33510, 33635), (33637, 33637), (33647, 33647)]),
        ("Pinellas",   [(33701, 33786)]),
        ("Pasco",      [(33523, 33526), (33540, 33545), (33552, 33558), (33574, 33576), (34638, 34691)]),
        ("Orange",     [(32801, 32839), (32885, 32899)]),
        ("Lee",        [(33900, 33994), (33919, 33919)]),
        ("Charlotte",  [(33947, 33983)]),
        ("Sarasota",   [(34230, 34293)]),
        ("Manatee",    [(34201, 34228)]),
        ("Collier",    [(34101, 34146), (34119, 34119)]),
        ("Polk",       [(33801, 33888)]),
        ("Volusia",    [(32114, 32198), (32759, 32760)]),
        ("Brevard",    [(32901, 32999)]),
        ("Seminole",   [(32701, 32799)]),
        ("St. Johns",  [(32080, 32099), (32145, 32145)]),
        ("Duval",      [(32099, 32259)]),
        ("Marion",     [(34470, 34488), (32113, 32113), (32179, 32195)]),
        ("Alachua",    [(32601, 32669)]),
        ("Leon",       [(32301, 32399)]),
        ("Citrus",     [(34428, 34465)]),
        ("Hernando",   [(34601, 34614)]),
        ("Monroe",     [(33001, 33092), (33036, 33037)]),
        ("Indian River", [(32948, 32970)]),
        ("Martin",     [(34990, 34997)]),
        ("St. Lucie",  [(34945, 34988)]),
        ("Osceola",    [(34741, 34773)]),
        ("Lake",       [(32702, 32796), (34736, 34797)]),
        ("Sumter",     [(33538, 33586)]),
    ]
    for county, rngs in ranges:
        for lo, hi in rngs:
            for z in range(lo, hi + 1):
                FL_ZIP_COUNTY.setdefault(f"{z:05d}", county)
_build_zip_county_map()


def zip_to_county(zip_code: str) -> str:
    if not zip_code:
        return "(unknown)"
    z = re.match(r"\d{5}", str(zip_code).strip())
    if not z:
        return "(unknown)"
    return FL_ZIP_COUNTY.get(z.group(), "Other FL")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--hours", type=int, default=24)
    p.add_argument("--top-per-county", type=int, default=5)
    p.add_argument("--no-email", action="store_true", help="Skip emailing the preview to ALERT_TO")
    return p.parse_args()


def send_preview_email(html: str, summary: str, subject: str = None):
    """Email the preview HTML to ALERT_TO (info@johnsonbuys.com) via SendGrid
    so Chris can review on his phone / forward / edit."""
    import urllib.request

    env = {}
    env_file = REPO / ".env.cheaphomesfla"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()

    if not env.get("SENDGRID_API_KEY"):
        print("⚠ SENDGRID_API_KEY missing — skipping email")
        return False

    to_email = env.get("ALERT_TO") or env.get("FROM_EMAIL") or "info@johnsonbuys.com"
    from_email = env.get("FROM_EMAIL") or "info@johnsonbuys.com"
    subj = subject or f"📋 PREVIEW — Today's CC blast (review/edit before sending)"

    payload = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": from_email, "name": "DealMatcher Preview"},
        "subject": subj,
        "content": [
            {"type": "text/plain", "value": f"PREVIEW of today's CC blast.\n\n{summary}\n\nReply to this email if you want to discuss layout/content changes.\n\nThe HTML preview is below."},
            {"type": "text/html", "value": html},
        ],
    }

    import json as _json
    body = _json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {env['SENDGRID_API_KEY']}",
            "Content-Type": "application/json",
        },
    )
    try:
        urllib.request.urlopen(req, timeout=20)
        print(f"  ✓ Preview emailed to {to_email}")
        return True
    except Exception as e:
        print(f"  ✗ Email send failed: {e}")
        return False


def main():
    args = parse_args()
    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=args.hours)).isoformat()

    print(f"\n═══ EMAIL PREVIEW BY COUNTY — last {args.hours}h ═══\n")
    print("→ Pulling + parsing + deduplicating deals...")
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

    all_deals = []
    for msg in msgs:
        is_ws, addr = is_wholesaler_mail(msg, wholesalers)
        if not is_ws:
            continue
        try:
            all_deals.extend(parse_deals(msg, addr, lookup))
        except Exception:
            continue
    print(f"  → {len(all_deals)} raw deals (before dedup)")

    deduped = collapse_cross_posted(all_deals)
    print(f"  → {len(deduped)} unique deals (after cross-poster merge)")

    # Filter to clean (has address + price)
    clean = []
    needs_geocode = []
    for d in deduped:
        addr = d.get("property_address") or ""
        price = d.get("asking_price")
        if addr and price and 30000 <= price <= 5000000 and re.match(r"^\d+\s+\w", addr):
            existing_zip = (d.get("zip") or "").strip()
            if not existing_zip:
                needs_geocode.append(d)
            clean.append(d)
    print(f"  → {len(clean)} clean deals with valid addr + price")

    # Backfill missing ZIPs via Census Bureau Geocoder (free, no API key)
    if needs_geocode:
        print(f"  → geocoding {len(needs_geocode)} addresses missing ZIP (Census API)...")
        geocoded = 0
        for i, d in enumerate(needs_geocode):
            if i % 20 == 0 and i > 0:
                print(f"      {i}/{len(needs_geocode)}")
            r = geocode_lookup(
                d.get("property_address", ""),
                city=d.get("city") or "",
                state=d.get("state") or "FL",
            )
            if r and r.get("zip"):
                d["zip"] = r["zip"]
                if not d.get("city") and r.get("city"):
                    d["city"] = r["city"]
                if not d.get("state") and r.get("state"):
                    d["state"] = r["state"]
                geocoded += 1
        print(f"      ✓ geocoded {geocoded}/{len(needs_geocode)} (cache speeds repeat lookups)")

    # Now compute county for each clean deal (post-geocoding)
    for d in clean:
        d["_county"] = zip_to_county(d.get("zip"))
    print()
    today_str = now.strftime("%Y-%m-%d")

    # Group by county
    by_county = defaultdict(list)
    for d in clean:
        by_county[d["_county"]].append(d)

    # Sort: counties by deal count desc; deals within county by price asc
    sorted_counties = sorted(by_county.items(), key=lambda kv: -len(kv[1]))
    for c, deals in sorted_counties:
        deals.sort(key=lambda x: x.get("asking_price") or 1e9)

    # ─── Console summary ───
    print("═══ COUNTY BREAKDOWN ═══\n")
    print(f"{'County':<20} {'Deals':>6} Sample (lowest priced)")
    print("-" * 80)
    for c, deals in sorted_counties:
        sample = deals[0]
        addr_short = sample.get("property_address", "")[:40]
        price = sample.get("asking_price")
        print(f"{c:<20} {len(deals):>6} {addr_short} — ${price:,}" if price else
              f"{c:<20} {len(deals):>6} {addr_short}")
    print()
    print(f"Total unique deals: {len(clean)}")
    print()

    # ─── HTML preview (mirrors what the email would look like) ───
    html_chunks = [
        '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Email Preview</title></head>',
        '<body style="margin:0; font-family:-apple-system,BlinkMacSystemFont,Helvetica,Arial,sans-serif; background:#f5f5f5;">',
        '<table cellpadding="0" cellspacing="0" border="0" align="center" width="100%" style="max-width:680px; margin:0 auto; background:#fff;">',
        '<tr><td style="padding:30px 25px; background:linear-gradient(135deg,#0a66c2,#0a7c2f); color:#fff;">',
        f'<h1 style="margin:0; font-size:26px;">Today\'s Top {len(clean)} Florida Deals</h1>',
        f'<div style="margin-top:6px; font-size:14px; opacity:0.9;">Hand-filtered from {len(deduped)} unique deals across 30+ wholesale sources</div>',
        '</td></tr>',
    ]

    for c_idx, (c, deals) in enumerate(sorted_counties):
        # Pretty county header — gradient bar with county name + deal count badge
        html_chunks.append(f'''
        <tr><td style="padding:0;">
          <div style="margin:30px 0 0; padding:18px 25px; background:linear-gradient(90deg, #0a66c2 0%, #0a7c2f 100%); color:#fff;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <div>
                <div style="font-size:11px; letter-spacing:2px; text-transform:uppercase; opacity:0.85;">Florida</div>
                <h2 style="margin:2px 0 0; font-size:22px; font-weight:bold;">{escape(c)} County</h2>
              </div>
              <div style="background:rgba(255,255,255,0.18); padding:6px 14px; border-radius:20px; font-size:13px; font-weight:bold;">{len(deals)} deals</div>
            </div>
          </div>
        </td></tr>
        ''')
        for i, d in enumerate(deals[:args.top_per_county], 1):
            addr = escape(d.get("property_address", ""))
            city = escape(d.get("city") or "")
            state = escape(d.get("state") or "FL")
            zip_code = escape(d.get("zip") or "")
            price = d.get("asking_price")
            beds = d.get("beds") or "?"
            sqft = d.get("sqft") or "?"
            # NOTE: bed/bath/sqft INTENTIONALLY hidden — wholesaler-typed values
            # are unreliable (often grab lot dimensions, building age, or wrong
            # numbers as sqft). Will re-enable once ATTOM Data API enrichment lands
            # and we have ground-truth from county records.
            #
            # Source attribution also not shown — that's our backend supply chain.

            html_chunks.append(f'''
            <tr><td style="padding:18px 25px; border-bottom:1px solid #eee;">
              <table cellpadding="0" cellspacing="0" border="0" width="100%">
                <tr>
                  <td valign="top" style="width:40px; padding-right:14px;">
                    <div style="width:36px; height:36px; border-radius:50%; background:#0a66c2; color:#fff; text-align:center; line-height:36px; font-weight:bold; font-size:15px;">{i}</div>
                  </td>
                  <td valign="top">
                    <div style="font-weight:bold; font-size:16px; color:#222;">{addr}</div>
                    <div style="font-size:13px; color:#666; margin:2px 0;">{city}{', ' + state if city else state} {zip_code}</div>
                    <div style="font-size:22px; color:#0a7c2f; margin:8px 0; font-weight:bold;">${price:,}</div>
                    <div style="margin-top:12px;">
                      <a href="mailto:info@cheaphomesfla.com?subject=I%27m%20interested%20in%20%23{i}%20{escape(c.replace(' ', '%20'))}%20-%20{escape(addr.replace(' ', '%20')[:60])}&body=Hi%20Chris%2C%0A%0AI%27m%20interested%20in%20deal%20%23{i}%20in%20{escape(c.replace(' ', '%20'))}%20County%20-%20{escape(addr.replace(' ', '%20')[:60])}.%0A%0APlease%20send%20me%20more%20details%20%2B%20photos.%0A%0AMy%20info%3A%0AName%3A%0APhone%3A%0AEntity%3A%0A%0AThanks%21" style="display:inline-block; padding:10px 18px; background:#0a7c2f; color:#fff; text-decoration:none; border-radius:6px; font-size:14px; font-weight:bold;">📨 I want full details on this</a>
                    </div>
                  </td>
                </tr>
              </table>
            </td></tr>
            ''')

        # "See more" CTA — drives to buyer form pre-filled with this county
        remaining = len(deals) - args.top_per_county
        if remaining > 0:
            county_slug = c.lower().replace(' ', '-').replace('.', '')
            html_chunks.append(f'''
            <tr><td style="padding:14px 25px 24px; text-align:center; background:#fafafa;">
              <div style="font-size:14px; color:#555; margin-bottom:10px;">
                <strong>{remaining} more {escape(c)} County deal{'s' if remaining != 1 else ''}</strong> we hand-filtered today.
              </div>
              <a href="https://cheaphomesfla.com/buyer-form?utm_source=cc&utm_medium=email&utm_campaign=daily_deals&counties={county_slug}&utm_content={today_str}_{county_slug}_more"
                 style="display:inline-block; padding:11px 22px; background:#0a66c2; color:#fff; text-decoration:none; border-radius:6px; font-size:14px; font-weight:bold;">
                Get all {escape(c)} deals → tell us your criteria
              </a>
            </td></tr>
            ''')

    # Buy-box CTA at the bottom
    html_chunks.append('''
    <tr><td style="padding:30px 25px; background:#f5f9ff;">
      <h3 style="margin:0 0 10px; font-size:18px;">Want a curated list? Tell us your buy-box.</h3>
      <p style="font-size:14px; line-height:1.6; color:#444; margin:0 0 15px;">
        Get personalized matches the moment a deal in your zip codes / price band hits — both on-market AND off-market FL properties.
      </p>
      <a href="https://cheaphomesfla.com/buyer-form?utm_source=cc&utm_medium=email&utm_campaign=preview" style="display:inline-block; padding:12px 22px; background:#0a66c2; color:#fff; text-decoration:none; border-radius:6px; font-weight:bold;">Set my buy-box → 2 min</a>
    </td></tr>
    ''')
    html_chunks.append('</table></body></html>')

    out_html = DESKTOP / f"preview_email_by_county_{now.strftime('%Y%m%d_%H%M')}.html"
    out_html.write_text("".join(html_chunks))
    print(f"📄 HTML preview: {out_html}")

    # Markdown summary
    out_md = DESKTOP / f"preview_email_by_county_{now.strftime('%Y%m%d_%H%M')}.md"
    md = [f"# Email Preview by County — {now.strftime('%Y-%m-%d %H:%M ET')}\n"]
    md.append(f"Window: last {args.hours}h\n")
    md.append(f"- Raw deals: {len(all_deals)}")
    md.append(f"- After dedup (same address from multiple wholesalers merged): {len(deduped)}")
    md.append(f"- Clean (addr + price valid): {len(clean)}\n")
    md.append("\n*Source attribution kept INTERNAL — never include in public email.*\n")
    for c, deals in sorted_counties:
        md.append(f"\n## {c} ({len(deals)} deals)\n")
        for d in deals[:args.top_per_county]:
            addr = d.get("property_address", "")
            price = d.get("asking_price")
            wholesaler = d.get("wholesaler_name") or "?"
            also = d.get("also_from") or []
            also_str = f" (also: {', '.join(also[:3])})" if also else ""
            # Markdown report keeps source for YOUR internal lookup when buyer inquires
            md.append(f"- `{addr}` · ${price:,} · 🔒 internal source: {wholesaler}{also_str}")
    out_md.write_text("\n".join(md))
    print(f"📝 Markdown report: {out_md}")

    # Auto-open the HTML
    try:
        subprocess.run(["open", str(out_html)], check=False)
    except Exception:
        pass
    print(f"\n✓ Preview opened in default browser.")

    # Email the preview HTML to ALERT_TO so Chris can review on phone / forward
    if not args.no_email:
        full_html = "".join(html_chunks)
        summary = (
            f"Window: last {args.hours}h\n"
            f"Counties: {len(sorted_counties)}\n"
            f"Total clean deals: {len(clean)}\n"
            f"Top {args.top_per_county} per county displayed."
        )
        send_preview_email(full_html, summary)


if __name__ == "__main__":
    main()
