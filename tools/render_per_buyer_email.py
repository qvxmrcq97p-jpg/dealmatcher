#!/usr/bin/env python3
"""
render_per_buyer_email.py — Day 7 per-buyer drop email v2.

Generates the personalized HTML email body sent to each opted-in CHF
buyer when one or more matched deals are ready. Builds on the v1
render_email_html() inside cheaphomesfla_scraper.py with three new
hooks:

  - Buyer Score tier (Hot / Warm / Cold) controls subject line +
    optional phone-call ping note.
  - Top-100-Buyers-per-Zip flag adds a "you're a top buyer in this zip"
    callout when the property zip matches one of the buyer's top zips.
  - Strategy hint surfaces a recommended play (Fix & Flip / BRRRR /
    Buy & Hold) per deal where we can infer it.

Importable from the scraper (clean function signature, no I/O):

    from render_per_buyer_email import build_email
    subject, html = build_email(buyer, deals)

CLI mode renders to stdout for visual review:
    python3 tools/render_per_buyer_email.py --sample
"""
from __future__ import annotations

import argparse
import html as _html
import json
import sys
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent.parent

BRAND_NAME = "CheapHomes FL / Johnson Buys"
BRAND_PHONE = "(305) 575-9040"
BRAND_EMAIL = "info@cheaphomesFLA.com"


# ---------------------------------------------------------------------------
# Tier helpers
# ---------------------------------------------------------------------------

def buyer_tier(buyer: dict) -> str:
    score = buyer.get("Buyer_Score__c")
    if score is None:
        return "Cold"
    if score >= 70:
        return "Hot"
    if score >= 50:
        return "Warm"
    return "Cold"


def is_top_buyer_for_zip(buyer: dict, zip_code: Optional[str]) -> bool:
    """True if this zip is one of the buyer's Top_Buyer_Zips__c
    (built by tools/top_buyers_by_zip.py — Day 5 work)."""
    if not zip_code:
        return False
    raw = buyer.get("Top_Buyer_Zips__c") or ""
    zips = [z.strip() for z in raw.replace(",", " ").split() if z.strip().isdigit()]
    return zip_code in zips


# ---------------------------------------------------------------------------
# Subject line construction — tier-aware
# ---------------------------------------------------------------------------

def build_subject(buyer: dict, deals: list[dict]) -> str:
    n = len(deals)
    plural = "s" if n != 1 else ""
    tier = buyer_tier(buyer)

    if tier == "Hot":
        # Hot buyers: lead with urgency
        return f"🔥 {n} STEAL{plural.upper()} matching your buy box — call us"
    if tier == "Warm":
        return f"🏠 {n} new deal{plural} matching your buy box"
    return f"🏠 {n} new deal{plural} for you to review"


# ---------------------------------------------------------------------------
# Per-deal card (one block in the email)
# ---------------------------------------------------------------------------

def _h(s) -> str:
    return _html.escape(str(s) if s is not None else "")


def _strategy_hint(deal: dict) -> Optional[str]:
    p = deal.get("asking_price")
    arv = deal.get("arv")
    cond = (deal.get("condition") or "").lower()
    if not p:
        return None
    if arv and (p / arv) <= 0.55:
        return "Fix & Flip — wide spread"
    if arv and (p / arv) <= 0.70:
        return "BRRRR — refi candidate"
    if "turnkey" in cond or "rent ready" in cond:
        return "Buy & Hold — turnkey"
    if p < 200_000:
        return "Buy & Hold — entry-level"
    return None


def render_deal_card(deal: dict, *, top_buyer_zip: bool = False) -> str:
    addr = deal.get("property_address") or "Address available on request"
    price_str = f"${deal['asking_price']:,}" if deal.get("asking_price") else "Call for pricing"
    arv_str = f"${deal['arv']:,}" if deal.get("arv") else "—"
    beds = deal.get("beds")
    beds_str = f"{int(beds)}" if beds is not None else "?"
    baths = deal.get("baths")
    baths_str = f"{baths:g}" if baths is not None else "?"
    sqft_str = f"{deal['sqft']:,}" if deal.get("sqft") else "?"
    city_zip = " ".join(filter(None, [deal.get("city"), deal.get("zip")])) or ""
    ptype = deal.get("property_type") or "SFR"
    strategy = _strategy_hint(deal)

    callouts = []
    if top_buyer_zip:
        callouts.append(
            '<span style="display:inline-block;padding:4px 10px;background:#0f5132;'
            'color:#fff;border-radius:4px;font-size:12px;font-weight:bold;'
            'margin-right:8px;">YOU\'RE A TOP BUYER IN THIS ZIP</span>'
        )
    if strategy:
        callouts.append(
            f'<span style="display:inline-block;padding:4px 10px;background:#1a3a5e;'
            f'color:#fff;border-radius:4px;font-size:12px;font-weight:bold;'
            f'margin-right:8px;">{_h(strategy).upper()}</span>'
        )
    callouts_html = "".join(callouts)

    return f"""
    <div style="border:1px solid #ccc;padding:18px;margin-bottom:18px;
                border-radius:8px;font-family:Arial,sans-serif;background:#ffffff;">
      {f'<div style="margin-bottom:10px;">{callouts_html}</div>' if callouts_html else ''}
      <h3 style="margin:0 0 6px 0;color:#0f1c2f;">{_h(addr)}</h3>
      <p style="margin:0 0 10px 0;color:#555;">{_h(city_zip)}</p>
      <table style="width:100%;border-collapse:collapse;font-size:14px;">
        <tr>
          <td style="padding:4px 0;"><strong>Asking:</strong> {_h(price_str)}</td>
          <td style="padding:4px 0;"><strong>ARV:</strong> {_h(arv_str)}</td>
        </tr>
        <tr>
          <td style="padding:4px 0;"><strong>{beds_str} bd / {baths_str} ba</strong></td>
          <td style="padding:4px 0;"><strong>{_h(sqft_str)} sqft</strong></td>
        </tr>
        <tr>
          <td colspan="2" style="padding:4px 0;color:#555;">{_h(ptype)}</td>
        </tr>
      </table>
    </div>
    """


# ---------------------------------------------------------------------------
# Tier-conditional intro / outro
# ---------------------------------------------------------------------------

def _intro(buyer: dict, n: int) -> str:
    first = _h(buyer.get("FirstName") or "there")
    tier = buyer_tier(buyer)
    plural = "s" if n != 1 else ""
    if tier == "Hot":
        return (
            f"<p>Hi {first},</p>"
            f"<p>You're one of our top closers — wanted you to see <b>{n}</b> deal{plural} "
            f"that hit your buy box this morning before they get circulated. "
            f"<b>Call or text Chris directly at "
            f"<a href='tel:{BRAND_PHONE.replace(' ','').replace('(','').replace(')','').replace('-','')}'>{BRAND_PHONE}</a></b> "
            f"if any of these grab you — moves fast at this tier.</p>"
        )
    if tier == "Warm":
        return (
            f"<p>Hi {first},</p>"
            f"<p>{n} new deal{plural} matched your buy box this morning. "
            f"Reply to this email or call <a href='tel:{BRAND_PHONE.replace(' ','').replace('(','').replace(')','').replace('-','')}'>{BRAND_PHONE}</a> "
            f"for the full package on any of them.</p>"
        )
    return (
        f"<p>Hi {first},</p>"
        f"<p>{n} new deal{plural} matched your stated buy box. Take a look — "
        f"reply if anything is interesting and we'll send the package.</p>"
    )


def _outro(buyer: dict) -> str:
    tier = buyer_tier(buyer)
    if tier == "Hot":
        ping = (
            "<p style='background:#fff3cd;padding:12px;border-left:4px solid #f0b400;'>"
            "<b>Hot-buyer note:</b> Chris will personally text you on the top deal "
            "in this list within the hour. If you don't see anything that fits, "
            "reply STOP TODAY and we'll skip you for today's blast.</p>"
        )
    else:
        ping = ""
    return (
        f"{ping}"
        f"<p style='color:#666;font-size:13px;margin-top:24px;'>— {_h(BRAND_NAME)}<br>"
        f"<a href='tel:{BRAND_PHONE.replace(' ','').replace('(','').replace(')','').replace('-','')}'>{BRAND_PHONE}</a> · "
        f"<a href='mailto:{BRAND_EMAIL}'>{BRAND_EMAIL}</a></p>"
    )


# ---------------------------------------------------------------------------
# Main entry point — used by the scraper
# ---------------------------------------------------------------------------

def build_email(buyer: dict, deals: list[dict]) -> tuple[str, str]:
    """Return (subject, html_body) for a per-buyer email drop."""
    subject = build_subject(buyer, deals)

    cards = []
    for d in deals:
        top_for_zip = is_top_buyer_for_zip(buyer, d.get("zip"))
        cards.append(render_deal_card(d, top_buyer_zip=top_for_zip))

    body_html = f"""<!doctype html>
<html><body style='font-family:Arial,sans-serif;max-width:680px;margin:0 auto;
                   background:#f7f9fc;padding:24px;'>
  <div style='background:#ffffff;padding:24px;border-radius:8px;'>
    {_intro(buyer, len(deals))}
    {''.join(cards)}
    {_outro(buyer)}
  </div>
</body></html>"""
    return subject, body_html


# ---------------------------------------------------------------------------
# CLI — sample render for visual review
# ---------------------------------------------------------------------------

SAMPLE_BUYER = {
    "FirstName": "Edward",
    "LastName": "Sellos",
    "Email": "selloscapitalmanagement@gmail.com",
    "Buyer_Score__c": 78,
    "Top_Buyer_Zips__c": "33125, 33127, 33142",
}

SAMPLE_DEALS = [
    {
        "property_address": "1410 NE 161st St",
        "city": "North Miami Beach", "zip": "33162",
        "asking_price": 320_000, "arv": 600_000,
        "beds": 3.0, "baths": 2.0, "sqft": 1450, "property_type": "SFR",
    },
    {
        "property_address": "9876 Caribbean Blvd",
        "city": "Cutler Bay", "zip": "33189",
        "asking_price": 450_000, "arv": 700_000,
        "beds": 4.0, "baths": 2.5, "sqft": 2000, "property_type": "SFR",
    },
    {
        "property_address": "1521 NW 1st Avenue",
        "city": "Miami", "zip": "33125",   # this matches Top_Buyer_Zips__c
        "asking_price": 195_000, "arv": 400_000,
        "beds": 2.0, "baths": 1.0, "sqft": 950, "property_type": "Duplex",
        "condition": "needs rehab",
    },
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true",
                        help="Render the built-in sample (Edward + 3 deals) to stdout")
    parser.add_argument("--buyer-json", type=Path, default=None,
                        help="Path to a JSON file with a single buyer dict")
    parser.add_argument("--deals-json", type=Path, default=None,
                        help="Path to a JSON file with a list of deal dicts")
    parser.add_argument("--out", type=Path, default=None,
                        help="Write rendered HTML to this file (otherwise stdout)")
    args = parser.parse_args()

    if args.sample:
        buyer, deals = SAMPLE_BUYER, SAMPLE_DEALS
    else:
        if not (args.buyer_json and args.deals_json):
            print("Provide --sample OR both --buyer-json and --deals-json")
            sys.exit(2)
        buyer = json.loads(args.buyer_json.read_text())
        deals = json.loads(args.deals_json.read_text())

    subject, html = build_email(buyer, deals)

    if args.out:
        args.out.write_text(html)
        print(f"Subject: {subject}")
        print(f"→ Wrote {args.out}")
    else:
        print(f"Subject: {subject}")
        print()
        print(html)


if __name__ == "__main__":
    main()
