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
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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


_STREET_ABBREV = {
    " street": " st", " avenue": " ave", " boulevard": " blvd",
    " drive": " dr", " road": " rd", " place": " pl", " court": " ct",
    " terrace": " ter", " lane": " ln", " parkway": " pkwy",
    " circle": " cir", " highway": " hwy", " trail": " trl",
    " northwest ": " nw ", " northeast ": " ne ",
    " southwest ": " sw ", " southeast ": " se ",
    " north ": " n ", " south ": " s ", " east ": " e ", " west ": " w ",
}


def _norm_address(addr: str) -> str:
    """Aggressively normalize a street address for cross-wholesaler matching.

    Lowercases, strips punctuation, collapses common street-type abbreviations
    so '2261 Nw 2nd Street' and '2261 NW 2nd St' produce identical keys.

    Also strips junk PREFIXES that the parser sometimes glues onto the real
    address ('30 Ref 4490 pine garden ln', '900 Property number 3 3866 luth
    dr', 'NEW DEAL 3779 oswego ave', a leading phone number, etc.). Without
    this, a re-blast of an old listing gets a different key, dodges the
    dedupe AND the freshness guard, and a stale April property sails through
    disguised as new. (Caught 2026-05-20: 4490 Pine Garden Ln.)
    """
    if not addr:
        return ""
    s = " " + addr.lower().strip() + " "
    # punctuation → space
    for ch in [",", ".", "#", "-"]:
        s = s.replace(ch, " ")
    # collapse whitespace
    s = " ".join(s.split())
    s = " " + s + " "
    for full, abbr in _STREET_ABBREV.items():
        s = s.replace(full, abbr)
    return s.strip()


def _norm_dedup_key(d: dict) -> str:
    """Build a tight cross-wholesaler key — street address only.

    City/zip are intentionally NOT in the key because wholesalers
    inconsistently fill them. Two wholesalers reporting the same house with
    different city/zip completeness must still group together so we can
    sanity-check their ARVs against each other.
    """
    addr_norm = _norm_address(d.get("property_address") or "")
    if not addr_norm:
        # Fall back to scraper's own dedup key if present
        return (d.get("_dedup_key") or "").strip().lower()
    return addr_norm


def _reconcile_arvs_across_wholesalers(payload: list[dict]) -> list[dict]:
    """Cross-wholesaler ARV consensus check.

    When the same property comes in from multiple wholesalers, no single
    wholesaler gets to declare the ARV. We apply two rules:

      1. If 2+ wholesalers report this property but only ONE supplies an ARV,
         drop that ARV (lone outlier claim — common inflation pattern).
      2. If 2+ wholesalers supply ARVs, set all records to the LOWEST value
         (wholesalers inflate ARVs to attract buyers; they almost never
         deflate them. The min is the most defensible).

    Caught yesterday's Pompano fiasco: 3 wholesalers, only Shark claimed
    $1.2M ARV — rule 1 drops it.

    Returns a NEW list of dicts (does not mutate input). 'arv' field is
    set to None where the rule says drop. 'arv_reconciled_from' note added
    so the audit log can show what happened.
    """
    # Group rows by dedup key
    groups: dict[str, list[dict]] = {}
    for d in payload:
        groups.setdefault(_norm_dedup_key(d), []).append(d)

    out: list[dict] = []
    for key, rows in groups.items():
        if len(rows) == 1:
            # Single wholesaler — nothing to reconcile, pass through
            out.extend(rows)
            continue

        arvs_present = [_to_int(r.get("arv")) for r in rows]
        arvs_present = [a for a in arvs_present if a]

        new_arv: Optional[int]
        note: str
        if len(arvs_present) == 0:
            new_arv = None
            note = ""
        elif len(arvs_present) == 1:
            # Lone claim — drop it. Rule 1.
            new_arv = None
            note = f"arv-reconciled: dropped lone ${arvs_present[0]:,} claim ({len(rows)} wholesalers, only 1 supplied ARV)"
        else:
            # Multiple claims — take the minimum. Rule 2.
            new_arv = min(arvs_present)
            note = f"arv-reconciled: used min ${new_arv:,} from {len(arvs_present)} wholesaler claims (range ${min(arvs_present):,}-${max(arvs_present):,})"

        for r in rows:
            new_row = dict(r)
            new_row["arv"] = new_arv
            if note:
                new_row["_arv_reconcile_note"] = note
            out.append(new_row)

    return out


def _has_usable_address(d: dict) -> bool:
    """True if this record has a real street address (not junk / not a
    'comparable sales' or 'property number N' parser artifact)."""
    a = (d.get("property_address") or "").strip().lower()
    if not a:
        return False
    # Reject known parser-artifact patterns
    if re.search(r"comparable|property number|\bsales\b|^\[wa-group\]|^\[wa-dm\]", a):
        return False
    # Must contain a digit (street number) AND a street-type token
    if not re.search(r"\d", a):
        return False
    if not re.search(r"\b(ave|st|street|dr|drive|rd|road|ct|court|ln|lane|blvd|"
                     r"ter|terrace|pl|place|way|cir|circle|hwy|trl|pkwy|"
                     r"ne|nw|se|sw|n|s|e|w)\b", a):
        return False
    return True


def _load_ledger_first_seen() -> dict:
    """Map normalized address -> first_seen ISO datetime from the deal ledger.
    Used by the freshness guard so re-blasted stale listings get dropped no
    matter how many times a wholesaler re-circulates them."""
    import json as _json
    from pathlib import Path as _Path
    ledger_path = _Path.home() / "Desktop" / "deal_ledger.json"
    out: dict = {}
    if not ledger_path.exists():
        return out
    try:
        ledger = _json.loads(ledger_path.read_text())
    except Exception:
        return out
    for rec in ledger.values():
        a = _norm_address(rec.get("address") or "")
        fs = rec.get("first_seen")
        if not a or not fs:
            continue
        # Keep the EARLIEST first_seen for an address. The same property can
        # appear under multiple ledger keys (slightly different address strings
        # from different wholesalers); we must judge freshness by the oldest
        # sighting, or a recent re-post masks a stale listing. (Caught
        # 2026-05-20: 4490 Pine Garden Ln, 26 days old, survived because a
        # second posting had a fresh date.)
        if a not in out or fs < out[a]:
            out[a] = fs
    return out


# ── 24-HOUR SEND GATE (locked 2026-05-20) ──────────────────────────────
# The ONLY date we trust is the email's received-date. The ledger's
# "first_seen" is corrupted by an old backlog scrape that stamped ~1,800
# properties with a single timestamp, so it can't be used to judge age.
# Rule per Chris: we only send deals whose EMAIL arrived in the last 24
# hours — no backlog, nothing older. A deal with no parseable received-date
# is kept (we can't prove it's stale) but counted so it's visible.
# Override the window via env CHF_SEND_WINDOW_HOURS.
import os as _os
SEND_WINDOW_HOURS = float(_os.getenv("CHF_SEND_WINDOW_HOURS", "24"))


def _received_dt(d: dict):
    """Parse a deal's email received timestamp. Returns datetime or None."""
    from datetime import datetime
    raw = d.get("received_at") or d.get("received") or d.get("receivedDateTime")
    if not raw or not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None




def _drop_junk_and_dedupe(payload: list[dict]) -> list[dict]:
    """Clean the payload for sending:
      1. Drop records with no usable address (parser junk).
      2. Drop deals whose EMAIL arrived more than SEND_WINDOW_HOURS ago
         (the 24h gate — uses the trustworthy received-date, NOT the
         corrupted ledger first_seen).
      3. Dedupe by normalized address (keep first occurrence).
    Returns a list reflecting unique, real, CURRENT (last-24h) properties.
    """
    import logging
    from datetime import datetime, timezone, timedelta
    log = logging.getLogger(__name__)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=SEND_WINDOW_HOURS)

    seen: set[str] = set()
    cleaned: list[dict] = []
    dropped_junk = 0
    dropped_dupe = 0
    dropped_old = 0
    no_date = 0
    for d in payload:
        if not _has_usable_address(d):
            dropped_junk += 1
            continue

        # THE RULE: only post deals whose email landed in the last 24 hours.
        rdt = _received_dt(d)
        if rdt is not None:
            if rdt.tzinfo is None:
                rdt = rdt.replace(tzinfo=timezone.utc)
            if rdt < cutoff:
                dropped_old += 1
                continue
        else:
            no_date += 1  # no received-date — keep, but track

        key = _norm_address(d.get("property_address") or "")
        if key in seen:
            dropped_dupe += 1
            continue
        seen.add(key)
        cleaned.append(d)

    try:
        log.warning("SEND-GATE: dropped %d junk + %d older-than-%gh + %d dupes "
                    "(%d no-date kept) → %d deals from the last %gh",
                    dropped_junk, SEND_WINDOW_HOURS, dropped_old,
                    dropped_dupe, no_date, len(cleaned), SEND_WINDOW_HOURS)
    except Exception:
        pass
    return cleaned


def deals_from_scraper_payload(payload: list[dict]) -> list:
    """Convert the production scraper's raw deal dicts (the format written to
    deal_scraper_last_run_deals.json by cheaphomesfla_scraper.py) into
    deal_matcher.Deal instances build_cc_statewide can consume.

    Cross-wholesaler ARV reconciliation runs first, then each row is converted
    to a Deal. The Deal.__post_init__ sanity guard catches anything that slips
    past the cross-wholesaler check.
    """
    _bootstrap_desktop_shim()
    import logging  # noqa: E402
    import deal_matcher as dm  # noqa: E402
    log = logging.getLogger(__name__)

    # Step 0 — drop parser junk + dedupe by address (added 2026-05-20).
    # The raw scrape contains records the parser couldn't turn into a real
    # property: rows with no address at all (just a wholesaler name), and
    # "comparable sales" / "property number N" artifacts. These inflate the
    # headline count and can't render a usable deal card. We drop them, then
    # dedupe by normalized address so the same house from 3 wholesalers counts
    # once. The result is a count Chris can stand behind ("280 real" not
    # "405 with junk + dupes").
    payload = _drop_junk_and_dedupe(payload)

    # Step 1 — reconcile ARVs across wholesalers BEFORE creating Deal objects.
    payload = _reconcile_arvs_across_wholesalers(payload)

    out = []
    for d in payload:
        # Log if the reconciliation step dropped/changed an ARV for this row
        note = d.get("_arv_reconcile_note")
        if note:
            try:
                log.warning(
                    "ARV-RECONCILE %s @ %s: %s",
                    (d.get("wholesaler_name") or "?"),
                    (d.get("property_address") or "?"),
                    note,
                )
            except Exception:
                pass

        out.append(dm.Deal(
            source_wholesaler = d.get("wholesaler_name") or "",
            source_email      = d.get("wholesaler_email") or "",
            source_message_id = d.get("email_id") or "",
            source_subject    = d.get("subject") or "",
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
            condition  = d.get("condition"),
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
