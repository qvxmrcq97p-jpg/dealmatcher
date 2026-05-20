#!/usr/bin/env python3
"""
cheaphomesfla_scraper.py  (v2.0 — 2026-04-30)

Daily wholesaler-deal scraper for the CheapHomesFLA buyer pipeline.

Renamed from johnson_buys_deal_scraper.py — the script serves the
CheapHomesFLA business (reads info@cheaphomesFLA.com, matches against
CheapHomesFLA buyers in Salesforce). The Johnson Buys naming was
legacy. SendGrid still ships from info@johnsonbuys.com because that's
the existing verified sender.

v2 changes vs v1:
  - Parsing logic extracted into ~/dealmatcher/parser.py (clean,
    unit-tested module — see ~/dealmatcher/tests/test_parser.py).
  - WhatsApp forwards (via Green-API → Cloudflare Worker) are now
    recognized by subject prefix ([WA-Group], [WA-DM]) or by sender
    address (whatsapp-deals@cheaphomesfla.com), and routed through
    the parser's WA-aware path.
  - Senders file moved from ~/Desktop/wholesaler_senders.txt to
    script-relative ~/dealmatcher/senders.txt.
  - Data files (state, deals dump, ledger, near-miss, log) STILL on
    ~/Desktop for now — downstream workbook builders / report scripts
    in the old session outputs folder still read from there. Migrate
    in a follow-up pass.

Schedule: 3x daily (10:00 AM / 2:00 PM / 6:00 PM) via launchd once
~/dealmatcher/plists/com.cheaphomes.dealmatcher.plist is installed in
~/Library/LaunchAgents/ (currently uninstalled — system not yet live).

Pipeline:
  1. Pulls new mail in info@cheaphomesFLA.com since the last run
  2. Filters to wholesaler senders in senders.txt OR to WhatsApp forwards
  3. Parses property details using parser.py
  4. Loads buyer Contact records from Salesforce where
     LeadSource = 'CheapHomesFLA_LandingPage'
  5. Matches each deal against each buyer's buy-box criteria
  6. Sends one personalized email per buyer with the deals that fit
  7. Dedups via Salesforce Task records so no deal+buyer pair ever re-sends
  8. Logs to ~/Desktop/deal_scraper_log_YYYYMMDD.txt + _latest.txt

Requires:
    pip3 install --break-system-packages msal requests simple-salesforce
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

# Add this script's directory + tools/ to sys.path so library imports
# (parser, render_per_buyer_email) resolve regardless of how launchd
# invokes us.
_SCRIPT_DIR = Path(__file__).resolve().parent
for p in (_SCRIPT_DIR, _SCRIPT_DIR / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# Auto-load .env.cheaphomesfla on startup. Existing OS env vars take
# precedence — this only fills in MISSING values. On Railway, the
# dashboard env vars take precedence (the .env file isn't deployed there).
def _autoload_env():
    env_file = _SCRIPT_DIR / ".env.cheaphomesfla"
    if not env_file.exists():
        return
    placeholder_pat = re.compile(r"^<.*>$")  # e.g. "<paste tenant id from step 6>"
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        # Override existing env vars if they look like unfilled placeholders
        existing = os.getenv(k, "")
        if not existing or placeholder_pat.match(existing):
            os.environ[k] = v
_autoload_env()

# parser.py — clean, unit-tested replacement for the inline parsing
# logic that lived in v1. See ~/dealmatcher/tests/test_parser.py.
from parser import (  # noqa: E402
    is_whatsapp_forward,
    parse_email_body,
    parse_whatsapp_body,
    ParsedDeal,
)

# render_per_buyer_email.py — Day 7 v2 email body builder. Tier-aware
# subjects (Hot/Warm/Cold), Top-100-Buyer-In-Zip callouts, and per-deal
# strategy hint badges (Fix & Flip / BRRRR / Buy & Hold).
from render_per_buyer_email import build_email  # noqa: E402

# =============================================================================
# CONFIG  — values marked TODO need Chris to fill in once before first run
# =============================================================================

DESKTOP = Path.home() / "Desktop"

# Code lives in ~/dealmatcher/, data still on ~/Desktop/ for now (downstream
# workbook builders read from Desktop). Migrate data in a follow-up pass.
SENDERS_FILE = _SCRIPT_DIR / "senders.txt"
STATE_FILE   = DESKTOP / "deal_scraper_state.json"
LOG_FILE     = DESKTOP / f"deal_scraper_log_{datetime.now().strftime('%Y%m%d')}.txt"
LOG_LATEST   = DESKTOP / "deal_scraper_log_latest.txt"

# --- Microsoft Graph (reads info@cheaphomesFLA.com) ---
# TODO[Chris]: register an Azure AD app in the cheaphomesFLA.com tenant with
# delegated permission "Mail.Read" and paste the values here. One-time setup.
GRAPH_CLIENT_ID   = os.getenv("GRAPH_CLIENT_ID",   "")   # TODO
GRAPH_TENANT_ID   = os.getenv("GRAPH_TENANT_ID",   "")   # TODO (or "common")
GRAPH_SCOPES      = ["Mail.Read"]
TARGET_MAILBOX    = "info@cheaphomesFLA.com"
TOKEN_CACHE_FILE  = DESKTOP / ".graph_token_cache.bin"

# --- Salesforce (reuse credentials already used by johnson_buys_campaign.py) ---
SF_USERNAME       = os.getenv("SF_USERNAME",       "info@johnsonbuys.com")
SF_PASSWORD       = os.getenv("SF_PASSWORD",       "")   # TODO: paste from campaign script
SF_SECURITY_TOKEN = os.getenv("SF_SECURITY_TOKEN", "")   # TODO: paste from campaign script
SF_DOMAIN         = os.getenv("SF_DOMAIN",         "login")  # "login" for prod, "test" for sandbox

# Salesforce Contact custom fields (verified live against johnsonshomes2 org on 4/23/26).
# The cheaphomesfla.com form fill writes into these fields on the Contact object.
BUYER_CRITERIA_FIELDS = {
    "max_budget":        "Buyer_Max_Budget__c",          # Picklist, e.g. "$100k", "$200k"
    "target_zips":       "Buyer_Target_Zips__c",         # Long Text Area, comma- or newline-separated
    "counties":          "Buyer_Counties_of_Interest__c",# Multi-Select Picklist, semicolon-separated
    "neighborhoods":     "Buyer_Neighborhoods__c",       # Text(255) free-form
    "primary_strategy":  "Buyer_Primary_Strategy__c",    # Picklist
    "attributes":        "BuyerAttributes__c",            # Multi-Select Picklist
    "willing_to_rehab":  "Are_you_willing_to_Rehab__c",  # Picklist
    "search_description":"Search_Description__c",        # Text(255)
    "status":            "Status__c",                    # Picklist (used to filter active buyers)
}

# Per-county multi-select picklists on Contact (city-level drill-down within a county).
# If the buyer has picked specific cities in a county, the value shows up in that county's field.
# The scraper uses this to check whether a deal's city falls inside a buyer's city selection.
COUNTY_CITY_FIELDS = {
    "Alachua":     "Alachua__c",
    "Brevard":     "Brevard__c",
    "Broward":     "Broward__c",
    "Charlotte":   "Charlotte__c",
    "Citrus":      "Citrus__c",
    "Collier":     "Collier__c",
    "Duval":       "Duval__c",
    "Hernando":    "Hernando__c",
    "Hillsborough":"Hillsborough__c",
    "Lee":         "Lee__c",
    "Leon":        "Leon__c",
    "Manatee":     "Manatee__c",
    "Miami-Dade":  "Miami_DADE__c",        # note the caps
    "Monroe":      "Monroe__c",
    "Palm Beach":  "West_Palm_Beach__c",   # note: org stores as West_Palm_Beach__c
    "Pasco":       "Pasco__c",
    "Pinellas":    "Pinellas__c",
    "Polk":        "Polk__c",
    "Sarasota":    "Sarasota__c",
    "Seminole":    "Seminole__c",
    "St. Johns":   "St_Johns__c",
    "St. Lucie":   "St_Lucie__c",
    "Volusia":     "Volusia__c",
}

# Status values that mean "this buyer is active and should receive deal emails".
# TODO[Chris]: confirm these match your actual Status picklist values.
ACTIVE_BUYER_STATUSES = {"Active", "Qualified", "New"}

# Rough mapping of Buyer_Max_Budget__c picklist strings → numeric max. Extend as needed.
BUDGET_PICKLIST_TO_MAX = {
    "Under $50k":        50_000,
    "$50k - $100k":      100_000,
    "$100k - $150k":     150_000,
    "$100k - $200k":     200_000,
    "$150k - $250k":     250_000,
    "$200k - $300k":     300_000,
    "$250k - $500k":     500_000,
    "$300k - $500k":     500_000,
    "$500k - $750k":     750_000,
    "$500k - $1M":     1_000_000,
    "$750k - $1M":     1_000_000,
    "$1M+":           10_000_000,
    "Over $1M":       10_000_000,
    "No limit":       10_000_000,
}


def _parse_budget(val):
    """Turn a Buyer_Max_Budget__c picklist string into a numeric ceiling."""
    if not val:
        return None
    if val in BUDGET_PICKLIST_TO_MAX:
        return BUDGET_PICKLIST_TO_MAX[val]
    # Best-effort fallback: extract the last number in the string and scale by 'k'/'M'
    m = re.search(r"([\d,.]+)\s*([kKmM]?)", val.replace("$", "").split("-")[-1])
    if not m:
        return None
    try:
        n = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    suffix = m.group(2).lower()
    if suffix == "k":
        n *= 1_000
    elif suffix == "m":
        n *= 1_000_000
    return int(n)

# --- SendGrid (reuse same key + from-address as seller campaign) ---
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")   # TODO: paste from campaign script
FROM_EMAIL  = "info@johnsonbuys.com"
FROM_NAME   = "Johnson Buys / CheapHomes FL"
REPLY_TO    = "info@cheaphomesFLA.com"

# --- Runtime ---
SUNDAY_SKIP = True       # mirror seller campaign; set False to send on Sundays
MAX_RUN_SECONDS = 600    # hard ceiling so launchd doesn't pile up runs
DEDUP_TAG_PREFIX = "CH-DEAL"   # Salesforce Task Subject prefix
DRY_RUN = os.getenv("DRY_RUN", "").lower() in ("1", "true", "yes")
TEST_SEND_TO = os.getenv("TEST_SEND_TO", "").strip()   # if set, route ALL matched emails to this address
DEALS_DUMP_FILE = DESKTOP / "deal_scraper_last_run_deals.json"   # always written for inspection
DEAL_LEDGER_FILE = DESKTOP / "deal_ledger.json"   # persistent lifetime ledger of unique properties
NEAR_MISS_FILE = DESKTOP / "near_miss_digest.json"   # per-buyer near-misses (same city/county, wrong zip)

# =============================================================================
# LOGGING
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("dealscraper")


# =============================================================================
# HELPERS
# =============================================================================

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_run_iso": None}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def load_wholesaler_addresses() -> set[str]:
    """Parse wholesaler_senders.txt → set of lowercase email addresses."""
    if not SENDERS_FILE.exists():
        raise FileNotFoundError(f"Wholesaler list not found at {SENDERS_FILE}")
    addrs: set[str] = set()
    for line in SENDERS_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.search(r"<([^>]+)>", line)
        if m:
            addrs.add(m.group(1).lower().strip())
    return addrs


# =============================================================================
# MICROSOFT GRAPH — read new wholesaler mail
# =============================================================================

def graph_access_token() -> str:
    """MSAL auth with delegated token cache.

    Cloud-friendly load order (first match wins):
      1. GRAPH_TOKEN_CACHE_B64 env var (Railway/headless: base64-encoded cache JSON)
      2. TOKEN_CACHE_FILE on disk (Mac/launchd: persisted cache from prior run)

    On the Mac, refreshes are persisted back to TOKEN_CACHE_FILE.
    On Railway, the env var is the source of truth — refreshes during a run
    aren't persisted (the original refresh token from the env var keeps
    working until expiry, ~90d, since Microsoft's v2 endpoint allows
    overlapping refresh tokens).

    First-time sign-in (device flow) is only attempted if no cache exists
    AND we're running interactively (TTY available). On Railway, missing
    cache is a fatal error with clear instructions.
    """
    import base64
    import sys

    import msal  # noqa: WPS433

    if not GRAPH_CLIENT_ID:
        raise RuntimeError(
            "GRAPH_CLIENT_ID env var is empty. "
            "Set it to the Azure AD app's Application (client) ID. "
            "For info@cheaphomesfla.com tenant: b2143511-d5e1-49d9-a121-8df37116b895"
        )

    cache = msal.SerializableTokenCache()

    # Source 1: env var (preferred for cloud)
    cache_b64 = os.getenv("GRAPH_TOKEN_CACHE_B64", "").strip()
    cache_loaded_from = None
    if cache_b64:
        try:
            cache.deserialize(base64.b64decode(cache_b64).decode("utf-8"))
            cache_loaded_from = "env:GRAPH_TOKEN_CACHE_B64"
        except Exception as e:
            raise RuntimeError(f"Failed to decode GRAPH_TOKEN_CACHE_B64: {e}")

    # Source 2: disk file (preferred for Mac with launchd)
    if not cache_loaded_from and TOKEN_CACHE_FILE.exists():
        try:
            cache.deserialize(TOKEN_CACHE_FILE.read_text())
            cache_loaded_from = f"file:{TOKEN_CACHE_FILE}"
        except Exception as e:
            print(f"WARN: failed to load token cache from disk: {e}", flush=True)

    app = msal.PublicClientApplication(
        GRAPH_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{GRAPH_TENANT_ID or 'common'}",
        token_cache=cache,
    )

    accounts = app.get_accounts()
    result = app.acquire_token_silent(GRAPH_SCOPES, account=accounts[0]) if accounts else None

    if not result:
        # No cached token — try device flow only if we're interactive (Mac/dev).
        # On Railway, this is fatal.
        is_interactive = sys.stdin.isatty()
        if not is_interactive:
            raise RuntimeError(
                "No cached Graph token and not running interactively. "
                "Set GRAPH_TOKEN_CACHE_B64 env var with a fresh device-flow cache. "
                "Generate one with: python3 tools/refresh_graph_token.py"
            )
        flow = app.initiate_device_flow(scopes=GRAPH_SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(f"Device flow init failed: {flow}")
        print(flow["message"], flush=True)
        result = app.acquire_token_by_device_flow(flow)

    # Persist refreshed cache to disk (Mac path) — Railway env-var is read-only,
    # so we just don't write anything back there. The original refresh token
    # remains valid until expiry.
    if cache.has_state_changed and cache_loaded_from != "env:GRAPH_TOKEN_CACHE_B64":
        try:
            TOKEN_CACHE_FILE.write_text(cache.serialize())
        except Exception as e:
            print(f"WARN: couldn't persist token cache to disk: {e}", flush=True)

    if "access_token" not in result:
        raise RuntimeError(f"Graph auth failed: {result.get('error_description')}")
    return result["access_token"]


def fetch_new_messages(token: str, since_iso: str | None) -> list[dict]:
    """Pull messages from info@cheaphomesFLA.com since `since_iso`."""
    url = f"https://graph.microsoft.com/v1.0/users/{TARGET_MAILBOX}/messages"
    params: dict[str, Any] = {
        "$top": 50,
        "$select": "id,subject,body,bodyPreview,from,sender,toRecipients,receivedDateTime",
        "$orderby": "receivedDateTime desc",
    }
    if since_iso:
        params["$filter"] = f"receivedDateTime gt {since_iso}"

    results: list[dict] = []
    headers = {"Authorization": f"Bearer {token}"}
    while url:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        results.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
        params = {}  # nextLink encodes all params
    return results


def is_wholesaler_mail(msg: dict, wholesalers: set[str]) -> tuple[bool, str | None]:
    """Identify a deal-bearing message.

    Returns (True, source_id) for:
      - Standard wholesaler email (sender in allowlist, OR a wholesaler
        email appears anywhere in a forwarded body)
      - WhatsApp forwards from the Green-API/Cloudflare Worker (subject
        starts with [WA-Group] or [WA-DM], or sender ==
        whatsapp-deals@cheaphomesfla.com). For WA, source_id encodes
        the WA chat/sender from the subject so downstream attribution
        still identifies who blasted the deal.
    """
    sender = (msg.get("sender", {}).get("emailAddress", {}).get("address") or "").lower()
    subject = msg.get("subject", "") or ""

    # WhatsApp forward — Worker-injected mail. Trust it (Worker already
    # ran looksLikePropertyMessage filter). Source ID = "wa:<chat/sender>".
    if is_whatsapp_forward(subject, sender):
        wa_id = subject.replace("[WA-Group]", "").replace("[WA-DM]", "").strip()
        if not wa_id:
            wa_id = "unknown_wa_sender"
        return True, f"wa:{wa_id[:80]}"

    # Standard wholesaler envelope match
    if sender in wholesalers:
        return True, sender

    # Fallback: forwarded body contains a known wholesaler address
    body = (msg.get("body", {}).get("content") or "").lower()
    for addr in wholesalers:
        if addr in body:
            return True, addr
    return False, None


# =============================================================================
# DEAL PARSING — delegated to parser.py
# =============================================================================
#
# v1 had ~200 lines of inline regex + parsing helpers here that produced
# ~97% junk addresses on real wholesaler email. Replaced with import
# from parser.py, which is unit-tested (tests/test_parser.py, 36 tests).
#
# This adapter keeps the dict shape downstream consumers expect
# (deal_scraper_last_run_deals.json, workbook builders, report scripts)
# while delegating the actual parsing to parser.parse_email_body or
# parser.parse_whatsapp_body depending on the message type.

def _first_url(text: str) -> str | None:
    """Best-effort first-URL extraction for the deal_url field."""
    m = re.search(r"https?://[^\s<>'\"]+", text)
    return m.group(0) if m else None


def _parsed_to_dict(
    p: ParsedDeal,
    msg: dict,
    wholesaler_id: str,
    wholesaler_name: str,
    body_text: str,
) -> dict:
    """Convert parser.ParsedDeal → legacy dict shape downstream expects."""
    return {
        "email_id":           msg["id"],
        "received_at":        msg["receivedDateTime"],
        "wholesaler_email":   wholesaler_id,
        "wholesaler_name":    wholesaler_name,
        "subject":            msg.get("subject", "") or "",
        "property_address":   p.address or None,
        "city":               p.city,
        "state":              p.state,
        "zip":                p.zip_code,
        "asking_price":       p.asking_price,
        "beds":               p.beds,
        "baths":              p.baths,
        "sqft":               p.sqft,
        "arv":                p.arv,
        "rehab_estimate":     p.rehab_estimate,
        "property_type":      p.property_type,
        "condition":          None,    # reserved for future NLP enrichment
        "deal_url":           _first_url(body_text),
        "notes":              None,
        "parse_warnings":     list(p.parse_warnings),
    }


def parse_deals(
    msg: dict,
    wholesaler_addr: str,
    wholesalers_lookup: dict[str, str],
) -> list[dict]:
    """Return one dict per property parsed out of the message.

    Routes WhatsApp-forwarded messages through parser.parse_whatsapp_body
    (which strips the Green-API wrapper first) and standard wholesaler
    emails through parser.parse_email_body.
    """
    body = (msg.get("body", {}).get("content") or "")
    subject = msg.get("subject", "") or ""
    sender = (msg.get("sender", {}).get("emailAddress", {}).get("address") or "").lower()

    if is_whatsapp_forward(subject, sender) or wholesaler_addr.startswith("wa:"):
        parsed = parse_whatsapp_body(body)
        wa_label = subject.replace("[WA-Group]", "").replace("[WA-DM]", "").strip()
        wholesaler_name = wa_label or "Unknown WA sender"
    else:
        parsed = parse_email_body(body)
        wholesaler_name = wholesalers_lookup.get(wholesaler_addr, wholesaler_addr)

    return [
        _parsed_to_dict(p, msg, wholesaler_addr, wholesaler_name, body)
        for p in parsed
    ]


# =============================================================================
# DEDUP + SOURCE TRACKING  (cross-wholesaler — same property sent by N wholesalers)
# =============================================================================

_ADDR_SUFFIX_NORMALIZE = {
    r"\bstreet\b":  "st",   r"\bavenue\b":  "ave",   r"\broad\b":   "rd",
    r"\bboulevard\b": "blvd", r"\bdrive\b": "dr",    r"\blane\b":   "ln",
    r"\bcourt\b":   "ct",    r"\bplace\b": "pl",     r"\bcircle\b": "cir",
    r"\bparkway\b": "pkwy",  r"\btrail\b": "trl",    r"\bterrace\b":"ter",
    r"\bhighway\b": "hwy",   r"\bnorth\b": "n",      r"\bsouth\b":  "s",
    r"\beast\b":    "e",     r"\bwest\b":  "w",
}


def normalize_address(deal: dict) -> str | None:
    """Produce a stable dedup key for a property.

    Strips punctuation, lowercases, canonicalizes street suffixes and
    directionals, collapses whitespace. Falls back to zip-only if the
    address is partially withheld (e.g. "1XXX Vineyard Pl"). If neither
    address nor zip survive, returns None — caller should treat as
    un-dedupable and keep the deal.
    """
    addr = (deal.get("property_address") or "").strip().lower()
    if not addr:
        addr = ""
    # Collapse privacy masks like "1XXX", "2***", "####" → keep the visible part
    addr = re.sub(r"[#*x]{2,}", "", addr, flags=re.IGNORECASE)
    # Drop punctuation (except digits, letters, spaces)
    addr = re.sub(r"[^\w\s]", " ", addr)
    # Canonicalize suffixes / directionals
    for pat, repl in _ADDR_SUFFIX_NORMALIZE.items():
        addr = re.sub(pat, repl, addr)
    addr = re.sub(r"\s+", " ", addr).strip()

    city = (deal.get("city") or "").strip().lower()
    zipc = (deal.get("zip") or "").strip()

    if not addr and not zipc:
        return None
    if not addr:
        # zip-only fallback is weak — combine with city for a *rough* key
        return f"~zip-{zipc}-{city}".strip("-")
    key_parts = [addr]
    if city:
        key_parts.append(city)
    if zipc:
        key_parts.append(zipc)
    return "|".join(key_parts)


def collapse_cross_posted(deals: list[dict]) -> list[dict]:
    """Merge duplicate deals (same normalized address) from multiple wholesalers.

    Returns a list where each dict has:
      - primary wholesaler = first-seen in this run
      - `also_from` = list of other wholesaler names also blasting the same deal today
      - lowest `asking_price` wins (wholesalers sometimes mark up cross-posted deals)
    """
    by_key: dict[str, dict] = {}
    unkeyed: list[dict] = []
    for d in deals:
        key = normalize_address(d)
        if key is None:
            unkeyed.append(d)
            continue
        d["_dedup_key"] = key
        existing = by_key.get(key)
        if not existing:
            d["also_from"] = []
            by_key[key] = d
            continue
        # Cross-post detected
        existing.setdefault("also_from", [])
        label = d.get("wholesaler_name") or d.get("wholesaler_email")
        if label and label != existing.get("wholesaler_name") and label not in existing["also_from"]:
            existing["also_from"].append(label)
        # Keep the lower price if both have one
        dp, ep = d.get("asking_price"), existing.get("asking_price")
        if dp is not None and (ep is None or dp < ep):
            existing["asking_price"] = dp
            existing.setdefault("price_history", []).append(
                {"from": label, "price": dp, "email_id": d.get("email_id")}
            )
    merged = list(by_key.values()) + unkeyed
    return merged


def load_deal_ledger() -> dict:
    """Persistent lifetime ledger: { dedup_key: {first_seen, wholesalers:[...], prices:[...]} }."""
    if DEAL_LEDGER_FILE.exists():
        try:
            return json.loads(DEAL_LEDGER_FILE.read_text())
        except Exception:  # noqa: BLE001
            return {}
    return {}


def save_deal_ledger(ledger: dict) -> None:
    try:
        DEAL_LEDGER_FILE.write_text(json.dumps(ledger, indent=2, default=str))
    except Exception as e:  # noqa: BLE001
        log.warning("Could not write deal ledger: %s", e)


def update_deal_ledger(ledger: dict, deals: list[dict]) -> None:
    """Append today's observations to the lifetime ledger."""
    now = datetime.now(timezone.utc).isoformat()
    for d in deals:
        key = d.get("_dedup_key") or normalize_address(d)
        if key is None:
            continue
        entry = ledger.setdefault(key, {
            "first_seen":  now,
            "first_wholesaler": d.get("wholesaler_name"),
            "address":     d.get("property_address"),
            "city":        d.get("city"),
            "zip":         d.get("zip"),
            "wholesalers": [],
            "prices":      [],
        })
        entry["last_seen"] = now
        src = d.get("wholesaler_name") or d.get("wholesaler_email")
        if src and src not in entry["wholesalers"]:
            entry["wholesalers"].append(src)
        for also in d.get("also_from", []):
            if also and also not in entry["wholesalers"]:
                entry["wholesalers"].append(also)
        if d.get("asking_price") is not None:
            entry["prices"].append({"date": now, "price": d["asking_price"], "from": src})


# =============================================================================
# SALESFORCE
# =============================================================================

def sf_client():
    from simple_salesforce import Salesforce  # noqa: WPS433
    return Salesforce(
        username=SF_USERNAME,
        password=SF_PASSWORD,
        security_token=SF_SECURITY_TOKEN,
        domain=SF_DOMAIN,
    )


def load_buyers(sf) -> list[dict]:
    # Discover which Contact fields actually exist in this org so a single
    # bad name in BUYER_CRITERIA_FIELDS / COUNTY_CITY_FIELDS doesn't crash
    # the whole run with INVALID_FIELD.
    try:
        desc = sf.Contact.describe()
        existing = {f["name"] for f in desc["fields"]}
    except Exception as e:  # noqa: BLE001
        log.warning("Could not describe Contact (%s); falling back to bare-minimum fields", e)
        existing = {"Id", "FirstName", "LastName", "Email", "HasOptedOutOfEmail",
                    "Buyer_Target_Zips__c", "LeadSource"}

    desired = [
        "Id", "FirstName", "LastName", "Email", "HasOptedOutOfEmail",
        *BUYER_CRITERIA_FIELDS.values(),
        *COUNTY_CITY_FIELDS.values(),
    ]
    field_list = [f for f in desired if f in existing]
    missing = [f for f in desired if f not in existing]
    if missing:
        log.warning("Skipping Contact fields not in this org's schema: %s", ", ".join(missing))

    # R9 (locked 2026-05-19): broadened LeadSource to 3 values so all
    # historical opt-in pathways resolve into Bucket A audience. Was
    # single-valued ('CheapHomesFLA_LandingPage') which missed buyers
    # imported under VIP_Signup or the legacy 'Cheap Homes FL - Buyer'.
    soql = (
        f"SELECT {','.join(field_list)} FROM Contact "
        f"WHERE LeadSource IN ('CheapHomesFLA_VIP_Signup', 'CheapHomesFLA_LandingPage', 'Cheap Homes FL - Buyer') "
        f"AND Email != null AND HasOptedOutOfEmail = false"
    )
    return sf.query_all(soql)["records"]


def load_existing_dedup_tags(sf) -> set[str]:
    """Pull Task subjects that match our dedup prefix so we never re-send."""
    res = sf.query_all(
        f"SELECT Subject FROM Task WHERE Subject LIKE '{DEDUP_TAG_PREFIX}-%'"
    )
    return {r["Subject"] for r in res["records"]}


def record_send_task(sf, buyer_id: str, subject: str) -> None:
    """Record a dedup-tagged Task so the same deal+buyer pair never re-sends.

    `subject` is pre-built by the caller using the address-based dedup key.
    """
    sf.Task.create({
        "WhoId": buyer_id,
        "Subject": subject,
        "Status": "Completed",
        "Priority": "Normal",
        "ActivityDate": datetime.now(timezone.utc).date().isoformat(),
    })


# =============================================================================
# MATCHING
# =============================================================================

def _parse_multiselect(val) -> set[str]:
    """Salesforce multi-select picklists come back as semicolon-separated strings."""
    if not val:
        return set()
    return {s.strip() for s in str(val).split(";") if s.strip()}


def _parse_ziplist(val) -> set[str]:
    """Buyer_Target_Zips__c is a long text area; accept commas, whitespace, or newlines."""
    if not val:
        return set()
    tokens = re.split(r"[,\s]+", str(val))
    return {t.strip() for t in tokens if t.strip().isdigit() and len(t.strip()) == 5}


def deal_matches_buyer(deal: dict, buyer: dict) -> bool:
    """True if this deal fits the buyer's buy-box.

    POLICY (updated 5/4/26 per Chris):
    Firehose-by-default. Buyers without geo criteria filled in Salesforce
    receive ALL deals (top-of-funnel volume; we'd rather over-serve than
    miss). Once they provide a zip, county, or city in their buy-box, we
    switch to filtered mode and only send matching deals.

    Matching layers (applied in order):
      1. Status — only active buyers (always enforced)
      2. Has-geo-criteria check — if buyer has NO target_zips AND NO counties
         AND NO city picks, the deal matches by default (firehose).
      3. Budget — applies whenever it's set, regardless of geo state. A
         buyer's stated budget gate is always honored.
      4. Geo — if any geo criterion is set, the deal must match at least
         one of: target zip, target county, or per-county city pick.
      5. Rehab tolerance — if buyer said "No" to rehab, skip gut-rehab.
    """
    f = BUYER_CRITERIA_FIELDS

    # ── 1. Status — only send to active buyers ──
    if ACTIVE_BUYER_STATUSES:
        status = buyer.get(f["status"])
        if status and status not in ACTIVE_BUYER_STATUSES:
            return False

    # ── 3. Budget filter (applies whether or not geo is set) ──
    price = deal.get("asking_price")
    if price is not None:
        ceiling = _parse_budget(buyer.get(f["max_budget"]))
        if ceiling is not None and price > ceiling:
            return False
    # If price is unknown, keep the deal moving — let Chris decide via reply.

    # ── 2. Has-geo-criteria check ──
    zips = _parse_ziplist(buyer.get(f["target_zips"]))
    counties = _parse_multiselect(buyer.get(f["counties"]))
    city_picks: list[str] = []
    for _county, api in COUNTY_CITY_FIELDS.items():
        city_picks.extend(_parse_multiselect(buyer.get(api)))

    has_geo = bool(zips or counties or city_picks)

    if not has_geo:
        # Buyer has NO geo criteria filled yet.
        # Per-buyer scraper email is reserved for criteria-filled buyers.
        # Unsegmented buyers get the broad CC daily blast instead (1 email/day,
        # top 10 deals, plus buy-box CTA). This keeps SendGrid volume sane.
        # When they fill their buy-box, they auto-graduate to per-buyer matching.
        return False

    # ── 4. Geo filter (buyer has SOME geo criteria set) ──
    deal_zip = (deal.get("zip") or "").strip()
    deal_city = (deal.get("city") or "").strip().lower()
    deal_county = (deal.get("county") or "").strip()

    geo_match = False
    if zips and deal_zip and deal_zip in zips:
        geo_match = True
    elif counties and deal_county and deal_county in counties:
        geo_match = True
    elif city_picks and deal_city:
        if any(deal_city == c.strip().lower() for c in city_picks):
            geo_match = True

    if not geo_match:
        return False

    # ── 5. Rehab tolerance ──
    return _passes_rehab_filter(deal, buyer)


def _passes_rehab_filter(deal: dict, buyer: dict) -> bool:
    """Returns True unless the buyer explicitly said no-rehab and this is gut-rehab."""
    f = BUYER_CRITERIA_FIELDS
    willing = (buyer.get(f["willing_to_rehab"]) or "").lower()
    condition = (deal.get("condition") or "").lower()
    if willing in ("no", "not willing") and (
        "gut" in condition or "heavy rehab" in condition or "tear down" in condition
    ):
        return False
    return True


def classify_near_miss(deal: dict, buyer: dict) -> str | None:
    """If a deal didn't match this buyer on zip but is geographically close
    (same city they picked, or same county), return a label for the near-miss
    digest. Returns None if the deal is not even close.

    Output labels:
      "CITY_HIT"    — deal's city is one of the buyer's per-county city picks
      "COUNTY_HIT"  — deal's city is anywhere in a county the buyer opted into
      None          — unrelated geography
    """
    f = BUYER_CRITERIA_FIELDS
    deal_city = (deal.get("city") or "").strip().lower()
    if not deal_city:
        return None

    # City-level match against buyer's per-county city selections
    for _county, api in COUNTY_CITY_FIELDS.items():
        cities = _parse_multiselect(buyer.get(api))
        if any(deal_city == c.strip().lower() for c in cities):
            return "CITY_HIT"

    # County-level match: if the deal's city appears anywhere in a county the buyer opted into.
    counties = _parse_multiselect(buyer.get(f["counties"]))
    for cty in counties:
        api = COUNTY_CITY_FIELDS.get(cty)
        if api is None:
            continue
        # NOTE: we don't have a city→county lookup table here — a future upgrade
        # would load one. For now, if the buyer has per-county cities selected
        # we've already caught CITY_HIT above. COUNTY_HIT is reserved for when
        # we add a full city→county resolver.
    return None


# =============================================================================
# SENDGRID
# =============================================================================

def render_email_html(buyer: dict, deals: list[dict]) -> tuple[str, str]:
    """Render the buyer-facing email HTML using the v4 brief template
    (Georgia serif + Courier mono + dark stat strip + county spotlights +
    "Did You Know?" commentary + per-county data summaries + 23-county
    grid at bottom + mobile responsive).

    v3 (2026-05-19, locked R24-template): Both buckets ship the same v4
    design — per-buyer (Bucket A SendGrid) and statewide (Bucket B CC).
    Same masthead, same buttons, same layout, same content blocks. Only
    geographic scope differs. Chris reviewed and approved this design 45+
    times today; the per-buyer renderer was still pointing at the legacy
    render_per_buyer_email.build_email by mistake. Fixed by delegating
    to deal_matcher.build_v4_brief.

    IMPORTANT (per Chris, R3): The email is branded as a DIRECT deal
    from CheapHomesFLA. We NEVER expose which wholesaler originated the
    deal — no "From: <wholesaler>" line, no "also listed by" callout,
    no subject reference to the source. Source attribution is tracked
    internally in deal_scraper_last_run_deals.json + deal_ledger.json.
    """
    # Convert scraper's dict-shape deals → deal_matcher.Deal dataclass instances
    # and call the v4 builder. Both functions live in deal_matcher.py copied
    # into the repo root.
    from tools.cc_html_builder import deals_from_scraper_payload, _bootstrap_desktop_shim
    _bootstrap_desktop_shim()
    import deal_matcher as dm  # noqa: E402

    deal_objs = deals_from_scraper_payload(deals)
    # Populate county from zip where missing — v4 spotlights group by county
    for d in deal_objs:
        if not getattr(d, "county", None) and getattr(d, "zip_code", None):
            d.county = dm.county_from_zip(d.zip_code)
    subject, html = dm.build_v4_brief(buyer, deal_objs)

    # R3-ENFORCE (locked 2026-05-19 evening): the rendered HTML MUST NOT
    # contain sourcing-disclosure language. Subscribers never see how we
    # source deals (wholesaler network, WhatsApp pipeline, etc.). If any
    # forbidden phrase appears, refuse to send — fail loud, ship nothing.
    # Caught 2026-05-19 19:48 EDT when a 22K-subscriber CC blast went out
    # with "sourced from our 26-wholesaler network and the WhatsApp
    # off-market pipeline" text. Never again.
    _FORBIDDEN = ("wholesaler", "whatsapp", "off-market pipeline", "26-wholesaler", "wholesale network")
    _html_lc = html.lower()
    for _phrase in _FORBIDDEN:
        if _phrase in _html_lc:
            raise RuntimeError(
                f"R3-ENFORCE BLOCK: rendered email contains forbidden phrase "
                f"{_phrase!r}. Sourcing details must NEVER leak to subscribers. "
                f"Fix the renderer template before retrying."
            )

    return subject, html


def _v1_render_email_html_DEPRECATED(buyer: dict, deals: list[dict]) -> tuple[str, str]:
    """v1 render kept for emergency rollback — call render_email_html(),
    not this. Will be deleted once v2 has run cleanly for a few days."""
    first = buyer.get("FirstName") or "there"
    subject = f"🏠 {len(deals)} new deal{'s' if len(deals) != 1 else ''} matching your buy box"

    cards = []
    for d in deals:
        price_str = f"${d['asking_price']:,}" if d.get("asking_price") else "Call for pricing"
        arv_str   = f"${d['arv']:,}"          if d.get("arv")          else "—"
        beds      = d.get("beds") or "?"
        baths     = d.get("baths") or "?"
        sqft_str  = f"{d['sqft']:,}" if d.get("sqft") else "?"
        # Intentionally no View-deal link — original wholesaler URLs can reveal source branding.
        # Buyers reply to this email or call Chris; Chris retrieves the source from the backend.
        addr      = d.get("property_address") or "Address available on request"
        city_zip  = f"{d.get('city','')}, FL {d.get('zip','')}".strip(", ")
        cond      = d.get("condition")
        cond_html = f'<p style="color:#333;"><i>{cond}</i></p>' if cond else ""
        cards.append(f"""
        <div style="border:1px solid #ccc;padding:16px;margin-bottom:16px;border-radius:6px;font-family:Arial,sans-serif;">
          <h3 style="margin:0 0 8px 0;">{addr}</h3>
          <p style="margin:0 0 4px 0;color:#555;">{city_zip}</p>
          <p><b>Asking:</b> {price_str} &nbsp;|&nbsp; <b>ARV:</b> {arv_str}</p>
          <p><b>{beds} bd / {baths} ba</b> &nbsp;|&nbsp; <b>{sqft_str} sqft</b> &nbsp;|&nbsp; {d.get('property_type') or 'SFR'}</p>
          {cond_html}
        </div>""")

    html = f"""<html><body style="font-family:Arial,sans-serif;max-width:640px;margin:0 auto;">
      <p>Hi {first},</p>
      <p>We spotted <b>{len(deals)}</b> new deal{'s' if len(deals) != 1 else ''} that match your buy box:</p>
      {''.join(cards)}
      <p>Interested in any of these? Reply to this email or call Chris at <a href="tel:+13055759040">(305) 575-9040</a> and we'll send the full package (photos, comps, contract).</p>
      <p style="color:#888;font-size:12px;margin-top:32px;">— Johnson Buys / CheapHomes FL</p>
    </body></html>"""
    return subject, html


def send_via_sendgrid(to_email: str, to_name: str, subject: str, html: str) -> None:
    payload = {
        "personalizations": [{"to": [{"email": to_email, "name": to_name}]}],
        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
        "reply_to": {"email": REPLY_TO},
        "subject": subject,
        "content": [{"type": "text/html", "value": html}],
    }
    r = requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={
            "Authorization": f"Bearer {SENDGRID_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    r.raise_for_status()


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    log.info("=== DEAL SCRAPER RUN STARTED ===")
    start_ts = datetime.now(timezone.utc)

    if SUNDAY_SKIP and datetime.now().weekday() == 6:
        log.info("Sunday skip — exiting.")
        return

    wholesalers = load_wholesaler_addresses()
    if not wholesalers:
        log.error("No wholesaler addresses loaded; aborting.")
        return

    # Build reverse-lookup (address → display name) by re-parsing the file
    lookup: dict[str, str] = {}
    for raw in SENDERS_FILE.read_text().splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        m = re.match(r"(.+?)\s*<([^>]+)>", raw)
        if m:
            lookup[m.group(2).lower().strip()] = m.group(1).strip()

    log.info("Loaded %d wholesaler addresses", len(wholesalers))

    state = load_state()
    since = state.get("last_run_iso")
    log.info("Pulling mail since: %s", since or "(first run)")

    # 1. Fetch mail
    token = graph_access_token()
    msgs = fetch_new_messages(token, since)
    log.info("Fetched %d messages from %s", len(msgs), TARGET_MAILBOX)

    # 2. Filter + parse
    all_deals: list[dict] = []
    for msg in msgs:
        is_ws, addr = is_wholesaler_mail(msg, wholesalers)
        if not is_ws:
            continue
        try:
            deals = parse_deals(msg, addr, lookup)
            all_deals.extend(deals)
        except Exception as e:  # noqa: BLE001
            log.warning("Parse failed on %s: %s", msg.get("id"), e)
    raw_count = len(all_deals)
    log.info("Parsed %d raw deals across %d wholesaler emails", raw_count, sum(
        1 for m in msgs if is_wholesaler_mail(m, wholesalers)[0]
    ))

    # Collapse cross-posted deals (same property from multiple wholesalers in one run)
    all_deals = collapse_cross_posted(all_deals)
    collapsed_count = len(all_deals)
    crosspost_count = raw_count - collapsed_count
    if crosspost_count:
        log.info("Dedup collapsed %d cross-posts → %d unique deals this run",
                 crosspost_count, collapsed_count)

    # Update the lifetime ledger (persistent view of every unique property ever seen,
    # every wholesaler that has blasted it, and price history over time).
    ledger = load_deal_ledger()
    update_deal_ledger(ledger, all_deals)
    save_deal_ledger(ledger)
    log.info("Lifetime ledger: %d unique properties tracked", len(ledger))

    # Always dump parsed deals to ~/Desktop so you can eyeball them even outside dry-run
    try:
        DEALS_DUMP_FILE.write_text(json.dumps(all_deals, indent=2, default=str))
        log.info("Parsed deals written to %s", DEALS_DUMP_FILE)
    except Exception as e:  # noqa: BLE001
        log.warning("Could not write deals dump: %s", e)

    if not all_deals:
        log.info("No new deals — exiting clean.")
        state["last_run_iso"] = start_ts.isoformat()
        save_state(state)
        return

    # 3. Load buyers + existing dedup tags
    sf = sf_client()
    buyers = load_buyers(sf)
    dedup_tags = load_existing_dedup_tags(sf)
    log.info("Loaded %d active buyers", len(buyers))

    if DRY_RUN:
        log.info("=== DRY RUN MODE — no SendGrid emails, no Salesforce Tasks created ===")
    if TEST_SEND_TO:
        log.info("=== TEST_SEND_TO override: ALL matched emails will be routed to %s ===", TEST_SEND_TO)

    # 4. Match + send
    #    Dedup key is address-based (via normalize_address), NOT email_id. That way if
    #    three wholesalers blast the same property this week, no buyer ever gets it twice.
    #    Near-misses (right city/county, wrong zip) go to near_miss_digest.json instead
    #    of being sent — they're Chris's signal to expand that buyer's zip list.
    sent_buyers = 0
    sent_pairs = 0
    near_misses: list[dict] = []
    for buyer in buyers:
        matched = []
        for deal in all_deals:
            # Produce a stable per-property key; fall back to email_id only if the
            # property can't be normalized (extremely rare — address+zip both missing)
            addr_key = deal.get("_dedup_key") or normalize_address(deal) or deal["email_id"]
            # Salesforce Task Subject has a 255-char limit — truncate a long address key
            short_key = re.sub(r"[^\w-]", "_", addr_key)[:180]
            dedup_subject = f"{DEDUP_TAG_PREFIX}-{short_key}-{buyer['Id']}"
            if dedup_subject in dedup_tags:
                continue
            if deal_matches_buyer(deal, buyer):
                deal["_dedup_subject"] = dedup_subject
                matched.append(deal)
            else:
                # Not a strict match — is it a near-miss on geography?
                reason = classify_near_miss(deal, buyer)
                if reason:
                    near_misses.append({
                        "buyer_id":    buyer["Id"],
                        "buyer_name":  f"{buyer.get('FirstName','')} {buyer.get('LastName','')}".strip(),
                        "buyer_email": buyer.get("Email"),
                        "deal_address": deal.get("property_address"),
                        "deal_city":   deal.get("city"),
                        "deal_zip":    deal.get("zip"),
                        "deal_price":  deal.get("asking_price"),
                        "reason":      reason,
                        "seen_at":     datetime.now(timezone.utc).isoformat(),
                    })

        if not matched:
            continue

        if DRY_RUN:
            log.info(
                "WOULD send %d deal(s) to %s %s <%s> — deals: %s",
                len(matched),
                buyer.get("FirstName", ""),
                buyer.get("LastName", ""),
                buyer.get("Email"),
                [d.get("property_address") or d.get("subject") for d in matched],
            )
            sent_buyers += 1
            sent_pairs += len(matched)
            continue

        subject, html = render_email_html(buyer, matched)
        to_email = TEST_SEND_TO or buyer["Email"]
        try:
            send_via_sendgrid(
                to_email,
                f"{buyer.get('FirstName', '')} {buyer.get('LastName', '')}".strip(),
                subject, html,
            )
            sent_buyers += 1
            sent_pairs += len(matched)
            # Only write dedup Tasks when sending to the real buyer — not in TEST_SEND_TO mode,
            # or we'd never send the same deal to the real buyer later.
            if not TEST_SEND_TO:
                for d in matched:
                    record_send_task(sf, buyer["Id"], d["_dedup_subject"])
            log.info("Sent %d deals → %s (buyer %s %s)",
                     len(matched), to_email, buyer.get("FirstName", ""), buyer["Id"])
        except Exception as e:  # noqa: BLE001
            log.error("Send failed for %s: %s", to_email, e)

    log.info("Send summary: %d emails to %d buyers (%d deal-buyer pairs)",
             sent_buyers, sent_buyers, sent_pairs)

    # Near-miss digest — appended to the ongoing file so you see accumulation over time
    if near_misses:
        existing_digest: list[dict] = []
        if NEAR_MISS_FILE.exists():
            try:
                existing_digest = json.loads(NEAR_MISS_FILE.read_text())
            except Exception:  # noqa: BLE001
                existing_digest = []
        existing_digest.extend(near_misses)
        try:
            NEAR_MISS_FILE.write_text(json.dumps(existing_digest, indent=2, default=str))
            log.info("Logged %d near-misses to %s (lifetime: %d)",
                     len(near_misses), NEAR_MISS_FILE, len(existing_digest))
        except Exception as e:  # noqa: BLE001
            log.warning("Could not write near-miss digest: %s", e)

        # Per-buyer rollup so Chris can scan the log quickly
        from collections import Counter
        by_buyer = Counter(nm["buyer_name"] for nm in near_misses)
        for name, count in by_buyer.most_common():
            log.info("  near-miss → %s: %d deal(s) in same city/county, different zip",
                     name, count)

    # 4b. Bucket B — Constant Contact statewide blast (locked R24-API 2026-05-19).
    # Runs after Bucket A SendGrid so per-investor briefs go first. Dedups
    # Bucket A buyers off the CC master list to prevent double-email, then
    # creates a CC v3 campaign and (if CC_AUTO_SEND=true) sends it.
    # Failures here are logged but don't crash the run — Bucket A already shipped.
    if not DRY_RUN:
        try:
            from tools.cc_blast_pipeline import run as _cc_run
            buyer_emails = [b.get("Email") for b in buyers if b.get("Email")]
            bucket_b = _cc_run(all_deals, buyer_emails)
            log.info("Bucket B pipeline result: %s",
                     {k: v for k, v in bucket_b.items() if k != "campaign"})
            _campaign = bucket_b.get("campaign") or {}
            if _campaign.get("campaign_id"):
                log.info("Bucket B campaign_id: %s (auto_send=%s)",
                         _campaign["campaign_id"], bucket_b.get("auto_send"))
        except Exception as e:  # noqa: BLE001
            log.error("Bucket B pipeline crashed (Bucket A already shipped): %s", e)
    else:
        log.info("DRY_RUN — skipping Bucket B")

    # 5. State
    state["last_run_iso"] = start_ts.isoformat()
    save_state(state)

    # Copy log → latest for easy tailing
    try:
        LOG_LATEST.write_text(LOG_FILE.read_text())
    except Exception:  # noqa: BLE001
        pass

    log.info("=== RUN COMPLETE ===")


if __name__ == "__main__":
    # Wrap main() with three-layer safeguards:
    #   1. Inline SMS+email on fatal exception
    #   2. SMS+email if 3+ consecutive runs produce zero deals (quiet failure detector)
    #   3. Heartbeat file at logs/scraper_heartbeat.json (read by system_watchdog)
    # See tools/scraper_safeguards.py for details.
    from tools.scraper_safeguards import safeguard_run
    safeguard_run(main)
