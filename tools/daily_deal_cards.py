#!/usr/bin/env python3
"""
daily_deal_cards.py — generate 1080x1080 branded deal cards from today's deals.

For sprint Day 5 content engine: top 3-5 STEAL deals → branded PNG cards
ready for IG/FB/LI/X scheduling via Buffer.

Reads:
    ~/Desktop/deal_scraper_last_run_deals.json  (latest scrape output)

Writes:
    ~/dealmatcher/data/cards/YYYY-MM-DD/01_address_slug.png
    ~/dealmatcher/data/cards/YYYY-MM-DD/01_address_slug_caption.txt

The .txt caption is the suggested social copy — paste into Buffer along
with the PNG.

Run:
    cd ~/dealmatcher
    python3 tools/daily_deal_cards.py            # default 5 cards
    python3 tools/daily_deal_cards.py --top 3    # top 3 only
    python3 tools/daily_deal_cards.py --logo path/to/logo.png

Dependency:
    pip3 install --break-system-packages pillow
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
from datetime import date
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DEALS_JSON = Path.home() / "Desktop" / "deal_scraper_last_run_deals.json"
OUT_DIR = SCRIPT_DIR / "data" / "cards"

# CheapHomes FL brand defaults — override with --logo / --color flags
BRAND_NAME = "CheapHomes FL"
BRAND_TAGLINE = "Off-market wholesale deals for serious investors"
BRAND_PHONE = "(305) 575-9040"
BRAND_WEBSITE = "cheaphomesFLA.com"
COLOR_BG = (15, 28, 47)        # deep navy
COLOR_ACCENT = (235, 175, 25)  # gold
COLOR_TEXT = (255, 255, 255)
COLOR_TEXT_MUTED = (200, 210, 220)
COLOR_STEAL = (28, 175, 100)   # green for STEAL badge

CARD_SIZE = 1080


# ---------------------------------------------------------------------------
# Pillow loader — graceful degradation if not installed
# ---------------------------------------------------------------------------

def _load_pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont
        return Image, ImageDraw, ImageFont
    except ImportError:
        print("ERROR: Pillow not installed. Run:")
        print("  pip3 install --break-system-packages pillow")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Deal selection — pick the top N "steals"
# ---------------------------------------------------------------------------

def is_steal(deal: dict) -> bool:
    """A deal is a STEAL if it has a price, an address, and the price feels
    aggressive vs ARV (or just below median for the area).

    Without ARV we can't compute a precise spread, so we use simple heuristics:
      - has asking_price AND arv → ratio ≤ 0.65 = STEAL
      - has asking_price AND no arv → STEAL if price < $250k (Miami floor)
    """
    p = deal.get("asking_price")
    if not p:
        return False
    arv = deal.get("arv")
    if arv:
        return (p / arv) <= 0.65
    return p < 250_000


def steal_score(deal: dict) -> float:
    """Lower = bigger steal. Used for sorting."""
    p = deal.get("asking_price") or 1_000_000
    arv = deal.get("arv")
    return (p / arv) if arv else (p / 1_000_000)


def pick_top_deals(all_deals: list[dict], n: int) -> list[dict]:
    candidates = [
        d for d in all_deals
        if d.get("property_address") and is_steal(d)
    ]
    candidates.sort(key=steal_score)
    return candidates[:n]


# ---------------------------------------------------------------------------
# Card rendering
# ---------------------------------------------------------------------------

def _try_font(ImageFont, paths: list[str], size: int):
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _font_paths(weight: str = "regular") -> list[str]:
    """Common macOS font paths. Falls back to PIL default if none found."""
    if weight == "bold":
        return [
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
    return [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]


def render_card(deal: dict, out_path: Path, *, logo_path: Optional[Path] = None) -> None:
    Image, ImageDraw, ImageFont = _load_pillow()

    img = Image.new("RGB", (CARD_SIZE, CARD_SIZE), COLOR_BG)
    draw = ImageDraw.Draw(img)

    # Fonts
    f_brand = _try_font(ImageFont, _font_paths("bold"), 56)
    f_huge = _try_font(ImageFont, _font_paths("bold"), 96)
    f_addr = _try_font(ImageFont, _font_paths("bold"), 64)
    f_med = _try_font(ImageFont, _font_paths("regular"), 42)
    f_small = _try_font(ImageFont, _font_paths("regular"), 32)
    f_tiny = _try_font(ImageFont, _font_paths("regular"), 26)

    # Top accent bar
    draw.rectangle([(0, 0), (CARD_SIZE, 12)], fill=COLOR_ACCENT)

    # Brand header
    draw.text((60, 60), BRAND_NAME, fill=COLOR_TEXT, font=f_brand)

    # Optional logo (top-right)
    if logo_path and logo_path.exists():
        try:
            logo = Image.open(logo_path).convert("RGBA")
            target_h = 96
            scale = target_h / logo.height
            target_w = int(logo.width * scale)
            logo = logo.resize((target_w, target_h), Image.LANCZOS)
            img.paste(logo, (CARD_SIZE - target_w - 60, 50), logo)
        except Exception as e:  # noqa: BLE001
            print(f"  (logo render skipped: {e})")

    # STEAL badge
    if is_steal(deal):
        badge_text = "STEAL"
        bbox = draw.textbbox((0, 0), badge_text, font=f_brand)
        bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
        bx, by = 60, 200
        pad = 24
        draw.rounded_rectangle(
            [(bx, by), (bx + bw + pad * 2, by + bh + pad * 2)],
            radius=18,
            fill=COLOR_STEAL,
        )
        draw.text((bx + pad, by + pad), badge_text, fill=COLOR_TEXT, font=f_brand)

    # Address — wrap to 2 lines max
    addr = deal.get("property_address") or "Address available on request"
    addr_lines = textwrap.wrap(addr, width=22)[:2]
    y = 360
    for line in addr_lines:
        draw.text((60, y), line, fill=COLOR_TEXT, font=f_addr)
        y += 80

    # City / Zip
    city_zip = " ".join(filter(None, [deal.get("city"), deal.get("zip")])) or ""
    if city_zip:
        draw.text((60, y), city_zip, fill=COLOR_TEXT_MUTED, font=f_med)
        y += 60

    # Price block
    price = deal.get("asking_price")
    arv = deal.get("arv")
    y_price = 660
    if price:
        draw.text((60, y_price), "ASKING", fill=COLOR_TEXT_MUTED, font=f_small)
        draw.text((60, y_price + 40), f"${price:,}", fill=COLOR_ACCENT, font=f_huge)
    if arv:
        draw.text((CARD_SIZE - 460, y_price), "ARV", fill=COLOR_TEXT_MUTED, font=f_small)
        draw.text((CARD_SIZE - 460, y_price + 40), f"${arv:,}", fill=COLOR_TEXT, font=f_huge)

    # Stats line: beds / baths / sqft / type
    parts = []
    if deal.get("beds") is not None:
        parts.append(f"{int(deal['beds'])}BR")
    if deal.get("baths") is not None:
        parts.append(f"{deal['baths']:g}BA")
    if deal.get("sqft"):
        parts.append(f"{deal['sqft']:,} sqft")
    if deal.get("property_type"):
        parts.append(deal["property_type"])
    stats = "  •  ".join(parts) or " "
    draw.text((60, 880), stats, fill=COLOR_TEXT, font=f_med)

    # Footer (bottom strip)
    draw.rectangle([(0, CARD_SIZE - 110), (CARD_SIZE, CARD_SIZE)], fill=COLOR_ACCENT)
    footer_text = f"{BRAND_PHONE}    •    {BRAND_WEBSITE}"
    draw.text((60, CARD_SIZE - 78), footer_text, fill=(15, 28, 47), font=f_small)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG", optimize=True)


# ---------------------------------------------------------------------------
# Caption text — separate file the user can paste into Buffer
# ---------------------------------------------------------------------------

CAPTION_TEMPLATES = {
    "Fix & Flip":   "🔥 OFF-MARKET DEAL ALERT 🔥\n\n{addr}\n{city_zip}\n\nAsking {price}{arv_part}\n{stats}\n\n💸 Fix-and-flip play. Cash buyers DM us for the full package.\n\n{phone}\n#MiamiRealEstate #FixAndFlip #Wholesale #OffMarket #InvestorDeals",
    "Buy & Hold":   "💎 NEW INCOME PROPERTY 💎\n\n{addr}\n{city_zip}\n\nAsking {price}{arv_part}\n{stats}\n\n📈 Buy-and-hold cash flow play. Reply for rent comps & full package.\n\n{phone}\n#MiamiRealEstate #BuyAndHold #Rental #InvestorDeals #OffMarket",
    "BRRRR":        "🏠 BRRRR-READY 🏠\n\n{addr}\n{city_zip}\n\nAsking {price}{arv_part}\n{stats}\n\nGreat refi target post-rehab. DM for full numbers.\n\n{phone}\n#BRRRR #MiamiRealEstate #InvestorDeals #OffMarket",
    "default":      "🚨 NEW DEAL 🚨\n\n{addr}\n{city_zip}\n\nAsking {price}{arv_part}\n{stats}\n\nReply for the full package — comps, photos, contract.\n\n{phone}\n#MiamiRealEstate #OffMarket #Wholesale #InvestorDeals",
}


def render_caption(deal: dict) -> str:
    strategy = (deal.get("property_type") or "default")  # weak proxy
    tpl = CAPTION_TEMPLATES.get(strategy, CAPTION_TEMPLATES["default"])

    parts = []
    if deal.get("beds") is not None:
        parts.append(f"{int(deal['beds'])}BR")
    if deal.get("baths") is not None:
        parts.append(f"{deal['baths']:g}BA")
    if deal.get("sqft"):
        parts.append(f"{deal['sqft']:,} sqft")
    stats = " · ".join(parts)

    arv_part = f"  |  ARV ${deal['arv']:,}" if deal.get("arv") else ""

    return tpl.format(
        addr=deal.get("property_address") or "Address on request",
        city_zip=" ".join(filter(None, [deal.get("city"), deal.get("zip")])) or "",
        price=f"${deal['asking_price']:,}" if deal.get("asking_price") else "Call",
        arv_part=arv_part,
        stats=stats or "",
        phone=BRAND_PHONE,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "deal").lower()).strip("_")[:40]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deals", type=Path, default=DEFAULT_DEALS_JSON)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--logo", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    if not args.deals.exists():
        print(f"Deals file not found: {args.deals}")
        print("Run the scraper first (or pass --deals /path/to/deals.json).")
        sys.exit(2)

    deals = json.loads(args.deals.read_text())
    print(f"Loaded {len(deals)} deals from {args.deals}")
    selected = pick_top_deals(deals, args.top)
    print(f"Picked {len(selected)} steal candidate(s)")

    if not selected:
        print("No qualifying deals (need a STEAL price + address). Nothing to render.")
        return

    today = date.today().strftime("%Y-%m-%d")
    out_dir = args.out_dir / today
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, deal in enumerate(selected, 1):
        s = slug(deal.get("property_address"))
        png = out_dir / f"{i:02d}_{s}.png"
        cap = out_dir / f"{i:02d}_{s}_caption.txt"
        render_card(deal, png, logo_path=args.logo)
        cap.write_text(render_caption(deal))
        print(f"  → {png.name}  +  caption")

    print(f"\nDone. Cards in: {out_dir}")
    print("Upload to Buffer (or your scheduler of choice) with the matching caption.")


if __name__ == "__main__":
    main()
