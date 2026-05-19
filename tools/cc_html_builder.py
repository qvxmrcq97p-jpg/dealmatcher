#!/usr/bin/env python3
"""
cc_html_builder.py — render the daily CC statewide HTML on Railway.

Wraps deal_matcher.build_cc_statewide so it works in the Railway runtime
where `~/Desktop` doesn't exist. Provides shim paths so the renderer's
file lookups resolve to repo-local files instead.

Public entry point:
    build_cc_html(deals) -> (subject, html)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Make deal_matcher importable
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _bootstrap_desktop_shim() -> None:
    """Make `~/Desktop` resolve to repo-local files for renderer compatibility.

    deal_matcher.build_cc_statewide reads:
      - ~/Desktop/county_commentary.md     (commentary text per county)
      - ~/Desktop/county_counts_today.json (live worker counts, optional)

    On Railway, $HOME is /root and /root/Desktop doesn't exist. We create
    /root/Desktop and symlink the commentary file in so the renderer works.
    """
    home = Path(os.path.expanduser("~"))
    desktop = home / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)

    # Commentary file
    src_commentary = REPO / "county_commentary.md"
    dst_commentary = desktop / "county_commentary.md"
    if src_commentary.exists() and not dst_commentary.exists():
        try:
            dst_commentary.symlink_to(src_commentary)
        except OSError:
            # symlink may not be supported; fall back to copy
            dst_commentary.write_text(src_commentary.read_text())


def build_cc_html(deals: list) -> tuple[str, str]:
    """Render the v4 CC statewide HTML using deal_matcher.build_cc_statewide.

    `deals` should be a list of deal_matcher.Deal instances (or dict-compatible
    objects) — same shape the scraper builds during normal Bucket A processing.
    """
    _bootstrap_desktop_shim()
    import deal_matcher as dm  # noqa: E402

    # Make sure county is filled where the renderer expects it
    for d in deals:
        if getattr(d, "county", None) is None and getattr(d, "zip_code", None):
            d.county = dm.county_from_zip(d.zip_code)
    subject, html = dm.build_cc_statewide(deals)
    return subject, html


def deals_from_scraper_payload(payload: list[dict]) -> list:
    """Convert the production scraper's raw deal dicts (the format written to
    deal_scraper_last_run_deals.json by cheaphomesfla_scraper.py) into
    deal_matcher.Deal instances build_cc_statewide can consume.
    """
    _bootstrap_desktop_shim()
    import deal_matcher as dm  # noqa: E402
    out = []
    for d in payload:
        out.append(dm.Deal(
            address    = d.get("property_address") or "",
            city       = d.get("city"),
            state      = (d.get("state") or "FL"),
            zip_code   = d.get("zip"),
            county     = None,  # populated by build_cc_html via county_from_zip
            price      = _to_int(d.get("asking_price")),
            arv        = _to_int(d.get("arv")),
            beds       = d.get("beds"),
            baths      = d.get("baths"),
            sqft       = _to_int(d.get("sqft")),
            property_type = d.get("property_type"),
            condition  = d.get("condition"),
            source_wholesaler = d.get("wholesaler_name"),
            source_email      = d.get("wholesaler_email"),
            source_subject    = d.get("subject"),
            source_message_id = d.get("email_id"),
            parse_confidence  = "auto",
            raw_text_excerpt  = (d.get("notes") or "")[:240],
        ))
    return out


def _to_int(v):
    if v is None: return None
    if isinstance(v, (int, float)):
        try: return int(v)
        except Exception: return None
    s = str(v).strip().replace("$", "").replace(",", "")
    mult = 1
    if s.lower().endswith("k"): mult, s = 1_000, s[:-1]
    elif s.lower().endswith("m"): mult, s = 1_000_000, s[:-1]
    try: return int(float(s) * mult)
    except ValueError: return None
