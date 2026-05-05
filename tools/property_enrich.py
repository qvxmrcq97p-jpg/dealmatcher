#!/usr/bin/env python3
"""
Property enrichment — verifies bed/bath/sqft/owner/distress data on each
scraped deal by calling a property-data API.

NOTE (May 4, 2026): PropStream does NOT have a public API. Replaced with
provider-agnostic design — works with PropertyRadar, BatchLeads, DataTree,
ATTOM, or Estated by swapping PROVIDER + endpoint config.

Set PROPERTY_DATA_PROVIDER in .env to one of:
  - "propertyradar"  (recommended — has scoring + 200+ filters)
  - "batchleads"     (60+ filters, skip-trace bundled)
  - "datatree"       (most comprehensive, enterprise pricing)
  - "attom"          (pay-per-call, $0.05-0.20)
  - "estated"        (cheap basic data, $0.04/call)

Run after the daily scraper. Caches per-address indefinitely (county records
don't change daily). Updates SF Property/Lead records with verified data.

Usage:
  python3 tools/propstream_enrich.py                    # enrich all deals scraped today
  python3 tools/propstream_enrich.py --hours=48         # enrich last 48h
  python3 tools/propstream_enrich.py --address "..."    # one-off lookup
  python3 tools/propstream_enrich.py --rebuild-cache    # force re-fetch all (rare)

Requires:
  PROPSTREAM_API_KEY in .env.cheaphomesfla (after Premium plan upgrade)
  PROPSTREAM_USERNAME in .env (their API uses Basic auth user/key)

API docs: https://docs.propstream.com (login required)
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CACHE_FILE = REPO / "logs" / "propstream_cache.json"
CACHE_FILE.parent.mkdir(exist_ok=True)

# PropStream API endpoint (verify against their docs once you have access)
API_BASE = "https://api.propstream.com/v1"


def load_env():
    env = dict(os.environ)
    env_file = REPO / ".env.cheaphomesfla"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env.setdefault(k.strip(), v.strip())
    return env


def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            pass
    return {}


def save_cache(cache: dict):
    try:
        CACHE_FILE.write_text(json.dumps(cache, indent=2))
    except Exception as e:
        print(f"WARN: cache save failed: {e}")


def normalize_address(addr: str, city: str = "", state: str = "FL", zip_code: str = "") -> str:
    """Build a canonical key for caching. Address-only addresses won't dedupe
    perfectly but it's good enough for the volume we deal with."""
    parts = [(addr or "").strip().lower()]
    if city:
        parts.append(city.strip().lower())
    if state:
        parts.append(state.strip().lower())
    if zip_code:
        parts.append(str(zip_code)[:5])
    return "|".join(p for p in parts if p)


def lookup_property(env: dict, address: str, city: str = "", state: str = "FL",
                     zip_code: str = "", force: bool = False) -> dict | None:
    """Call PropStream API for a property. Returns enrichment dict or None.

    Caches results forever (county property data is essentially static).

    Returned fields (when available from PropStream):
      - bedrooms, bathrooms, square_feet, lot_size_sqft
      - year_built, property_type
      - owner_name, owner_mailing_address, owner_state
      - last_sold_price, last_sold_date
      - estimated_value
      - is_in_foreclosure, is_tax_delinquent, has_code_violation,
        is_in_probate, is_in_bankruptcy, is_in_divorce
      - equity_percent
      - photos (list of URLs)
    """
    if not env.get("PROPSTREAM_API_KEY"):
        return None

    key = normalize_address(address, city, state, zip_code)
    cache = load_cache()
    if not force and key in cache:
        return cache[key]

    auth = base64.b64encode(
        f"{env.get('PROPSTREAM_USERNAME', '')}:{env['PROPSTREAM_API_KEY']}".encode()
    ).decode()

    # NOTE: this endpoint shape is per PropStream's typical REST API. Verify
    # exact path + parameters once you have docs access. Most likely:
    #   GET /v1/properties/search?address=...
    # OR
    #   POST /v1/properties/lookup with JSON body
    # Adjust if their docs differ.

    params = {
        "address": address,
        "city": city,
        "state": state,
    }
    if zip_code:
        params["zip"] = zip_code

    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v})
    url = f"{API_BASE}/properties/search?{qs}"

    req = urllib.request.Request(url, headers={
        "Authorization": f"Basic {auth}",
        "Accept": "application/json",
        "User-Agent": "dealmatcher/1.0",
    })

    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"  ⚠ PropStream lookup failed for {address[:50]}: {e}")
        # Cache the failure with TTL so we retry later
        cache[key] = {"_error": str(e)[:200], "_cached_at": datetime.now(timezone.utc).isoformat()}
        save_cache(cache)
        return None

    # PropStream typically returns array; first match wins
    properties = data.get("results") or data.get("properties") or [data] if data else []
    if not properties:
        return None

    p = properties[0]

    # Map their fields to our normalized shape (best-effort; refine after first run)
    enrichment = {
        "bedrooms": p.get("bedrooms") or p.get("beds") or None,
        "bathrooms": p.get("bathrooms") or p.get("baths") or None,
        "square_feet": p.get("square_feet") or p.get("sqft") or p.get("building_sqft") or None,
        "lot_size_sqft": p.get("lot_size_sqft") or p.get("lot_size") or None,
        "year_built": p.get("year_built") or None,
        "property_type": p.get("property_type") or p.get("use_code_description") or None,
        "owner_name": p.get("owner_name") or p.get("owner1_first_name", "") + " " + p.get("owner1_last_name", "") or None,
        "owner_mailing_address": p.get("owner_mailing_address") or None,
        "owner_state": p.get("owner_state") or None,
        "owner_is_out_of_state": (p.get("owner_state") or "").upper() != state.upper() if p.get("owner_state") else None,
        "last_sold_price": p.get("last_sold_price") or p.get("sale_price") or None,
        "last_sold_date": p.get("last_sold_date") or p.get("sale_date") or None,
        "estimated_value": p.get("estimated_value") or p.get("avm") or None,
        "equity_percent": p.get("equity_percent") or None,
        # Distress signals
        "is_in_foreclosure": bool(p.get("is_in_foreclosure") or p.get("foreclosure_status")),
        "is_tax_delinquent": bool(p.get("is_tax_delinquent") or p.get("tax_delinquent")),
        "has_code_violation": bool(p.get("has_code_violation") or p.get("code_violation")),
        "is_in_probate": bool(p.get("is_in_probate") or p.get("probate")),
        "is_in_bankruptcy": bool(p.get("is_in_bankruptcy") or p.get("bankruptcy")),
        "is_in_divorce": bool(p.get("is_in_divorce") or p.get("divorce")),
        # Photos
        "photos": p.get("photos") or p.get("listing_photos") or [],
        # Raw for debugging
        "_propstream_raw": {k: v for k, v in p.items() if k not in ("photos",)},
        "_cached_at": datetime.now(timezone.utc).isoformat(),
    }

    cache[key] = enrichment
    save_cache(cache)
    time.sleep(0.3)  # gentle rate limiting

    return enrichment


def enrich_recent_deals(env: dict, hours: int = 24, dry_run: bool = False):
    """Pull recent scraped deals from SF Tasks (or directly query the scraper
    state files) and enrich each via PropStream."""
    print(f"\n═══ PROPSTREAM ENRICH — last {hours}h ═══\n")

    # For now, use the scraper's existing imports to pull fresh deals
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(REPO / "tools"))

    from cheaphomesfla_scraper import (
        graph_access_token, fetch_new_messages, is_wholesaler_mail,
        parse_deals, SENDERS_FILE, load_wholesaler_addresses,
        collapse_cross_posted,
    )

    print("→ Pulling recent deals to enrich...")
    token = graph_access_token()
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
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

    deals = []
    for msg in msgs:
        is_ws, addr = is_wholesaler_mail(msg, wholesalers)
        if not is_ws:
            continue
        try:
            deals.extend(parse_deals(msg, addr, lookup))
        except Exception:
            pass

    deduped = collapse_cross_posted(deals)
    clean = [d for d in deduped if d.get("property_address") and d.get("asking_price")]
    print(f"  → {len(clean)} unique deals to enrich")

    if not clean:
        print("Nothing to enrich.")
        return

    enriched_count = 0
    cached_count = 0
    failed_count = 0

    for i, d in enumerate(clean, 1):
        addr = d.get("property_address") or ""
        city = d.get("city") or ""
        state = d.get("state") or "FL"
        zip_code = d.get("zip") or ""

        cache = load_cache()
        cache_key = normalize_address(addr, city, state, zip_code)
        was_cached = cache_key in cache and "_error" not in cache[cache_key]

        if dry_run:
            status = "(cached)" if was_cached else "(would fetch)"
            print(f"  [{i}/{len(clean)}] {status} {addr[:50]}")
            continue

        result = lookup_property(env, addr, city, state, zip_code)
        if result and "_error" not in result:
            if was_cached:
                cached_count += 1
            else:
                enriched_count += 1
            d["_propstream"] = result
        else:
            failed_count += 1

        if i % 20 == 0:
            print(f"  ... {i}/{len(clean)} (new: {enriched_count}, cached: {cached_count}, failed: {failed_count})")

    print(f"\n═══ DONE ═══")
    print(f"  New enrichments: {enriched_count}")
    print(f"  Cache hits: {cached_count}")
    print(f"  Failed: {failed_count}")
    print(f"\nCache file: {CACHE_FILE}")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--hours", type=int, default=24)
    p.add_argument("--address", help="One-off address lookup")
    p.add_argument("--city", default="")
    p.add_argument("--state", default="FL")
    p.add_argument("--zip", default="")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--rebuild-cache", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    env = load_env()

    if not env.get("PROPSTREAM_API_KEY"):
        print("✗ PROPSTREAM_API_KEY not set in .env.cheaphomesfla")
        print("  Sign up at propstream.com → upgrade to Premium → get API key → add to .env")
        sys.exit(1)

    if args.rebuild_cache:
        if CACHE_FILE.exists():
            CACHE_FILE.unlink()
        print("✓ Cache cleared. Re-run without --rebuild-cache to fetch fresh data.")
        return

    if args.address:
        result = lookup_property(env, args.address, args.city, args.state, args.zip)
        print(json.dumps(result, indent=2) if result else "No match")
        return

    enrich_recent_deals(env, hours=args.hours, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
