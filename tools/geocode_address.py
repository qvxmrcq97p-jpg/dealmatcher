#!/usr/bin/env python3
"""
Free address geocoder using the US Census Bureau Geocoding API.

Resolves "address + city + state" → standardized address with ZIP.
No API key required, no cost. Rate limited to ~1 req/sec by their servers.

Cache: results stored at logs/geocode_cache.json so repeat lookups are instant.

Usage as a library:
    from tools.geocode_address import lookup
    result = lookup("123 Main St", city="Miami", state="FL")
    # result["zip"], result["city"], result["state"], result["full"]
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
CACHE_FILE = REPO / "logs" / "geocode_cache.json"
CACHE_FILE.parent.mkdir(exist_ok=True)


_cache: dict | None = None


def _load_cache() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    if CACHE_FILE.exists():
        try:
            _cache = json.loads(CACHE_FILE.read_text())
            return _cache
        except Exception:
            pass
    _cache = {}
    return _cache


def _save_cache():
    if _cache is None:
        return
    try:
        CACHE_FILE.write_text(json.dumps(_cache, indent=2))
    except Exception:
        pass


def lookup(address: str, city: str = "", state: str = "FL") -> Optional[dict]:
    """Look up an address via Census API. Returns dict with zip/city/state/full
    if matched, None if no match.

    Caches per-key forever (addresses don't change). To rebust, delete
    logs/geocode_cache.json.
    """
    if not address:
        return None
    cache = _load_cache()
    key = f"{address.strip()}|{city.strip()}|{state.strip()}".lower()
    if key in cache:
        return cache[key]

    parts = [address.strip()]
    if city:
        parts.append(city.strip())
    if state:
        parts.append(state.strip())
    one_line = ", ".join(parts)

    url = (
        "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
        f"?address={urllib.parse.quote(one_line)}"
        "&benchmark=Public_AR_Current&format=json"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "dealmatcher/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
    except Exception:
        cache[key] = None
        _save_cache()
        return None

    matches = data.get("result", {}).get("addressMatches", [])
    if not matches:
        cache[key] = None
        _save_cache()
        return None

    m = matches[0]
    components = m.get("addressComponents", {})
    result = {
        "zip": components.get("zip", ""),
        "city": components.get("city", ""),
        "state": components.get("state", ""),
        "full": m.get("matchedAddress", ""),
        "lat": m.get("coordinates", {}).get("y"),
        "lon": m.get("coordinates", {}).get("x"),
    }
    cache[key] = result
    _save_cache()
    return result


def batch_lookup(addresses: list, throttle: float = 0.5) -> list:
    """Look up multiple addresses sequentially with throttling."""
    results = []
    for i, item in enumerate(addresses):
        if isinstance(item, dict):
            addr = item.get("address") or item.get("property_address", "")
            city = item.get("city", "")
            state = item.get("state", "FL")
        else:
            addr, city, state = item, "", "FL"
        r = lookup(addr, city, state)
        results.append(r)
        # Throttle so we don't hammer the Census API
        if i < len(addresses) - 1 and r is not None:
            time.sleep(throttle)
    return results


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 tools/geocode_address.py '123 Main St, Miami, FL'")
        sys.exit(1)
    full = " ".join(sys.argv[1:])
    parts = full.split(",")
    addr = parts[0].strip()
    city = parts[1].strip() if len(parts) > 1 else ""
    state = parts[2].strip() if len(parts) > 2 else "FL"
    r = lookup(addr, city, state)
    print(json.dumps(r, indent=2) if r else "No match")
