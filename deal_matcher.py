#!/usr/bin/env python3
"""
deal_matcher.py

Cheap Homes FLA / Johnson Buys deal matcher.

Reads wholesaler deal emails from one or more source inboxes (Gmail via IMAP and
Microsoft Graph for Outlook.com / Microsoft 365 mailboxes), filters by a sender
allowlist, parses each email to extract property details, matches each deal
against active buyer Contacts in Salesforce, then notifies matched buyers via
Twilio SMS and SendGrid email. A Salesforce Task is created on each buyer's
Contact record to prevent duplicate sends.

Usage:
    python deal_matcher.py [--dry-run] [--since HOURS] [--verbose]

Environment variables:
    SF_USERNAME, SF_PASSWORD, SF_SECURITY_TOKEN
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
    SENDGRID_API_KEY
    GMAIL_CJM_APP_PASSWORD
    GRAPH_CHF_TENANT_ID, GRAPH_CHF_CLIENT_ID, GRAPH_CHF_CLIENT_SECRET

Target: Python 3.9+
"""

from __future__ import annotations

import argparse
import email
import imaplib
import json
import logging
import os
import re
import sys
import urllib.parse
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - dependency surfaced at runtime
    BeautifulSoup = None  # type: ignore

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore

try:
    import msal
except ImportError:  # pragma: no cover
    msal = None  # type: ignore

try:
    from simple_salesforce import Salesforce
except ImportError:  # pragma: no cover
    Salesforce = None  # type: ignore

try:
    from twilio.rest import Client as TwilioClient
except ImportError:  # pragma: no cover
    TwilioClient = None  # type: ignore

try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail
except ImportError:  # pragma: no cover
    SendGridAPIClient = None  # type: ignore
    Mail = None  # type: ignore

try:
    from dotenv import load_dotenv
    # Look for .env alongside the script first (e.g., ~/dealmatcher/.env.cheaphomesfla),
    # then fall back to default (CWD / ~/.env).
    _env_here = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.cheaphomesfla")
    if os.path.exists(_env_here):
        load_dotenv(_env_here)
    else:
        load_dotenv()
except ImportError:  # pragma: no cover
    pass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TWILIO_FROM_NUMBER = "+19549534554"
SENDGRID_FROM_EMAIL = "info@cheaphomesFLA.com"
SENDGRID_FROM_NAME = "Cheap Homes FLA"

# Paths are relative to the script's own directory so the whole thing can be
# moved around (e.g., from ~/Desktop to ~/dealmatcher/) without code changes.
# The macOS Full Disk Access requirement only applies to ~/Desktop, ~/Documents,
# ~/Downloads and a few other protected folders — placing everything in a
# plain ~/dealmatcher/ folder lets launchd read/write without FDA grants.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SENDERS_FILE = os.path.join(_SCRIPT_DIR, "cheaphomesfla_senders.txt")
MAILBOX_CONFIG_FILE = os.path.join(_SCRIPT_DIR, "mailbox_config.json")
LOG_DIR = os.path.join(_SCRIPT_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Per-buyer cap: at most this many deals can be sent to ONE buyer across all
# runs in a given day. Dropped from 10 -> 3 after the 2026-04-21 dry-run
# showed 7890 buyers x 10 = 78,900 theoretical sends, which would cost
# ~$1,100/day in Twilio SMS alone. Quality over quantity — buyers appreciate
# 3 curated deals far more than 10 that fill their inbox.
MAX_MATCHES_PER_BUYER_PER_DAY = 3

# Global per-RUN cap — a hard kill-switch. If a single run tries to send more
# than this many alerts, we abort with a loud error. Prevents runaway cost
# from a buyer-filter bug or a malformed deal email that looks like N deals.
# Tuned assuming ~50 opted-in buyers and ~20 deals per run -> ~1000 max
# legit matches. 1500 is comfortably above that but far below the 78,900
# figure from the un-filtered dry-run.
MAX_MATCHES_PER_RUN = 1500

log = logging.getLogger("deal_matcher")


# ---------------------------------------------------------------------------
# FL ZIP -> County map (partial; covers the 27 FL counties in scope).
# Keys are ZIP prefixes (3 digits) mapping to a best-guess county. The full
# 5-digit ZIP is checked first for overrides. This is intentionally
# conservative; if we cannot resolve, we fall back to the city string.
# ---------------------------------------------------------------------------

FL_ZIP_PREFIX_TO_COUNTY: Dict[str, str] = {
    # South FL core
    "330": "Miami-Dade",
    "331": "Miami-Dade",
    "332": "Miami-Dade",
    "333": "Broward",
    "334": "Palm Beach",
    # Treasure Coast / Space Coast
    "349": "Martin",
    "329": "Brevard",
    "327": "Orange",
    "328": "Orange",
    # Tampa Bay
    "335": "Hillsborough",
    "336": "Hillsborough",
    "337": "Pinellas",
    "338": "Polk",
    "339": "Lee",
    "341": "Sarasota",
    "342": "Manatee",
    # NE FL
    "320": "Duval",
    "322": "Duval",
    "326": "Alachua",
    # Panhandle
    "323": "Leon",
    "324": "Bay",
    "325": "Walton",
}

FL_ZIP_OVERRIDES: Dict[str, str] = {
    # Specific 5-digit ZIPs that cross county lines
    "33470": "Palm Beach",  # Loxahatchee
    "33496": "Palm Beach",
    "33498": "Palm Beach",
    "34974": "Okeechobee",
    "34972": "Okeechobee",
    "34945": "St. Lucie",
    "34946": "St. Lucie",
    "34947": "St. Lucie",
    "34950": "St. Lucie",
    "34951": "St. Lucie",
    "34952": "St. Lucie",
    "34953": "St. Lucie",
    "34957": "Martin",
    "34994": "Martin",
    "34996": "Martin",
    "34997": "Martin",
}

# City -> county for high-volume Miami-Dade and neighboring cities (used when
# ZIP parsing fails). Lowercase keys.
FL_CITY_TO_COUNTY: Dict[str, str] = {
    "miami": "Miami-Dade",
    "miami beach": "Miami-Dade",
    "hialeah": "Miami-Dade",
    "hialeah gardens": "Miami-Dade",
    "homestead": "Miami-Dade",
    "miami gardens": "Miami-Dade",
    "north miami": "Miami-Dade",
    "north miami beach": "Miami-Dade",
    "doral": "Miami-Dade",
    "aventura": "Miami-Dade",
    "cutler bay": "Miami-Dade",
    "kendall": "Miami-Dade",
    "opa-locka": "Miami-Dade",
    "opa locka": "Miami-Dade",
    "coral gables": "Miami-Dade",
    "fort lauderdale": "Broward",
    "hollywood": "Broward",
    "pompano beach": "Broward",
    "pembroke pines": "Broward",
    "davie": "Broward",
    "sunrise": "Broward",
    "plantation": "Broward",
    "miramar": "Broward",
    "coral springs": "Broward",
    "deerfield beach": "Broward",
    "west palm beach": "Palm Beach",
    "boca raton": "Palm Beach",
    "delray beach": "Palm Beach",
    "boynton beach": "Palm Beach",
    "lake worth": "Palm Beach",
    "riviera beach": "Palm Beach",
    "jupiter": "Palm Beach",
    "tampa": "Hillsborough",
    "brandon": "Hillsborough",
    "st. petersburg": "Pinellas",
    "saint petersburg": "Pinellas",
    "clearwater": "Pinellas",
    "orlando": "Orange",
    "kissimmee": "Osceola",
    "jacksonville": "Duval",
    "naples": "Collier",
    "fort myers": "Lee",
    "cape coral": "Lee",
    "sarasota": "Sarasota",
    "bradenton": "Manatee",
    "ocala": "Marion",
    "gainesville": "Alachua",
    "tallahassee": "Leon",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Sender:
    """A single entry from the wholesaler allowlist."""
    display_name: str
    email: str
    note: str = ""


@dataclass
class Deal:
    """Parsed deal extracted from a wholesaler email."""
    source_wholesaler: str
    source_email: str
    source_message_id: str
    source_subject: str
    address: str = ""
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    county: Optional[str] = None
    price: Optional[int] = None
    arv: Optional[int] = None
    beds: Optional[int] = None
    baths: Optional[float] = None
    sqft: Optional[int] = None
    condition: Optional[str] = None  # 'distressed' | 'fixer' | 'needs_rehab' | 'turnkey' | None
    strategy_hint_text: str = ""
    parse_confidence: str = "high"  # 'high' | 'medium' | 'low'
    raw_text_excerpt: str = ""


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(verbose: bool) -> Path:
    """Configure root logger. Returns the path to the day log file."""
    log_path = Path(LOG_DIR) / f"cheaphomes_match_log_{datetime.now().strftime('%Y%m%d')}.txt"
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s %(levelname)s %(name)s - %(message)s"
    handlers: List[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_path, mode="a", encoding="utf-8"),
    ]
    logging.basicConfig(level=level, format=fmt, handlers=handlers, force=True)
    log.info("Logging initialized (level=%s, file=%s)", logging.getLevelName(level), log_path)
    return log_path


# ---------------------------------------------------------------------------
# Sender allowlist
# ---------------------------------------------------------------------------

def load_senders(path: str) -> List[Sender]:
    """Load approved wholesaler senders from the pipe-delimited file.

    Lines look like::

        Display Name (Company) | someone@example.com    # optional comment

    Blank lines and lines beginning with '#' are ignored.
    """
    senders: List[Sender] = []
    p = Path(path)
    if not p.exists():
        log.warning("Sender allowlist not found at %s; no senders loaded.", path)
        return senders

    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Strip trailing inline comment
        if "#" in line:
            # Keep '#' that is inside a token only if no whitespace before it.
            hash_idx = line.find("#")
            # Only treat as comment if preceded by whitespace.
            if hash_idx > 0 and line[hash_idx - 1].isspace():
                line = line[:hash_idx].rstrip()
        if "|" not in line:
            log.warning("Skipping malformed sender line: %r", raw)
            continue
        # Split on the LAST pipe — some display names legitimately contain a
        # pipe (e.g. "Only Direct | Michael"), but by convention the email
        # address is always the final segment after the final pipe.
        name_part, addr_part = line.rsplit("|", 1)
        display = name_part.strip()
        addr_and_note = addr_part.strip()
        # Allow optional trailing "(...)" note after the address
        m = re.match(r"(\S+@\S+)\s*(.*)", addr_and_note)
        if not m:
            log.warning("Skipping malformed sender line (no email): %r", raw)
            continue
        email_addr = m.group(1).rstrip(",;")
        note = m.group(2).strip()
        senders.append(Sender(display_name=display, email=email_addr.lower(), note=note))
    log.info("Loaded %d approved senders from %s", len(senders), path)
    return senders


def sender_matches(from_header: str, senders: List[Sender]) -> Optional[Sender]:
    """Return the matching Sender entry for a raw From header, else None.

    Matches first by envelope email (exact, case-insensitive), then falls back
    to display-name substring match (useful when ccsend.com / mailchimpapp.com
    rotate the local part).
    """
    if not from_header:
        return None
    display_raw, addr = parseaddr(from_header)
    addr_lc = (addr or "").lower().strip()
    display_lc = (display_raw or "").lower().strip()

    # 1) Exact envelope match
    for s in senders:
        if s.email and s.email == addr_lc:
            return s

    # 2) Domain match for marketing-platform envelopes
    #    (e.g. anything @shared1.ccsend.com or @mailchimpapp.com from a known sender)
    marketing_domains = ("shared1.ccsend.com", "mailchimpapp.com", "ccsend.com")
    if addr_lc.split("@")[-1] in marketing_domains or any(
        addr_lc.endswith("@" + d) for d in marketing_domains
    ):
        # Fall through to display-name match below
        pass

    # 3) Display-name fallback (case-insensitive substring in either direction)
    if display_lc:
        for s in senders:
            sd = s.display_name.lower()
            if not sd:
                continue
            # Use the pre-parenthesis portion of the approved display name as
            # the "core" (e.g. "Jonathan Espinosa" from "Jonathan Espinosa (JE Financial Holdings)")
            core = sd.split("(")[0].strip()
            if core and (core in display_lc or display_lc in core):
                return s
    return None


# ---------------------------------------------------------------------------
# Mailbox config
# ---------------------------------------------------------------------------

def load_mailbox_config(path: str) -> List[Dict[str, Any]]:
    """Load the mailbox config JSON file.

    Ignores entries whose key begins with '_' (treated as comments).
    """
    p = Path(path)
    if not p.exists():
        log.error("Mailbox config not found at %s", path)
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        log.error("Mailbox config JSON invalid: %s", exc)
        return []
    mailboxes = data.get("mailboxes", []) if isinstance(data, dict) else data
    clean: List[Dict[str, Any]] = []
    for mbox in mailboxes:
        if not isinstance(mbox, dict):
            continue
        if mbox.get("enabled") is False:
            continue
        # Filter out commented keys
        clean.append({k: v for k, v in mbox.items() if not k.startswith("_")})
    log.info("Loaded %d enabled mailbox(es) from %s", len(clean), path)
    return clean


# ---------------------------------------------------------------------------
# Email fetching -- Gmail IMAP
# ---------------------------------------------------------------------------

def _decode_header(value: Optional[str]) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for text, enc in parts:
        if isinstance(text, bytes):
            try:
                out.append(text.decode(enc or "utf-8", errors="replace"))
            except LookupError:
                out.append(text.decode("utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out).strip()


def _message_html_and_text(msg: email.message.Message) -> Tuple[str, str]:
    """Return (html, text) bodies from a MIME message, decoded best-effort."""
    html_parts: List[str] = []
    text_parts: List[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if part.get("Content-Disposition", "").lower().startswith("attachment"):
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                decoded = payload.decode(charset, errors="replace")
            except LookupError:
                decoded = payload.decode("utf-8", errors="replace")
            if ctype == "text/html":
                html_parts.append(decoded)
            elif ctype == "text/plain":
                text_parts.append(decoded)
    else:
        payload = msg.get_payload(decode=True)
        if payload is not None:
            charset = msg.get_content_charset() or "utf-8"
            try:
                decoded = payload.decode(charset, errors="replace")
            except LookupError:
                decoded = payload.decode("utf-8", errors="replace")
            if msg.get_content_type() == "text/html":
                html_parts.append(decoded)
            else:
                text_parts.append(decoded)
    return "\n".join(html_parts), "\n".join(text_parts)


def fetch_gmail(mbox: Dict[str, Any], since: datetime, senders: List[Sender]) -> List[Deal]:
    """Fetch deals from a Gmail IMAP inbox and parse them.

    Required mbox keys: ``username`` (email), ``password_env`` (env var name).
    Optional: ``host`` (default imap.gmail.com), ``port`` (default 993),
    ``folder`` (default INBOX).
    """
    username = mbox.get("username")
    pw_env = mbox.get("password_env", "GMAIL_CJM_APP_PASSWORD")
    password = os.environ.get(pw_env)
    if not username or not password:
        log.error("Gmail mailbox %s missing username or %s env var", username, pw_env)
        return []

    host = mbox.get("host", "imap.gmail.com")
    port = int(mbox.get("port", 993))
    folder = mbox.get("folder", "INBOX")

    deals: List[Deal] = []
    try:
        conn = imaplib.IMAP4_SSL(host, port)
        conn.login(username, password)
        conn.select(folder, readonly=True)

        since_str = since.strftime("%d-%b-%Y")
        typ, data = conn.search(None, f'(SINCE "{since_str}")')
        if typ != "OK":
            log.error("IMAP search failed on %s: %s", username, typ)
            conn.logout()
            return []

        ids = data[0].split() if data and data[0] else []
        log.info("Gmail %s: %d messages since %s", username, len(ids), since_str)

        for msg_id in ids:
            try:
                typ, msg_data = conn.fetch(msg_id, "(RFC822)")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                from_hdr = _decode_header(msg.get("From"))
                match = sender_matches(from_hdr, senders)
                if not match:
                    continue

                subject = _decode_header(msg.get("Subject"))
                message_id = msg.get("Message-ID", "").strip() or f"gmail-{msg_id.decode()}"
                date_hdr = msg.get("Date", "")
                try:
                    msg_date = parsedate_to_datetime(date_hdr) if date_hdr else None
                except (TypeError, ValueError):
                    msg_date = None
                if msg_date and msg_date.tzinfo is None:
                    msg_date = msg_date.replace(tzinfo=timezone.utc)
                if msg_date and msg_date < since:
                    continue

                html_body, text_body = _message_html_and_text(msg)
                log.debug("Parsing Gmail message %s from %s", message_id, from_hdr)
                extracted = parse_deal_email(
                    html_body=html_body,
                    text_body=text_body,
                    subject=subject,
                    source_wholesaler=match.display_name,
                    source_email=match.email or parseaddr(from_hdr)[1],
                    source_message_id=message_id,
                )
                deals.extend(extracted)
            except Exception as exc:  # noqa: BLE001 defensive
                log.exception("Error parsing Gmail message %s: %s", msg_id, exc)
                continue

        conn.close()
        conn.logout()
    except Exception as exc:  # noqa: BLE001
        log.exception("Gmail fetch failed for %s: %s", username, exc)
    return deals


# ---------------------------------------------------------------------------
# Email fetching -- Microsoft Graph
# ---------------------------------------------------------------------------

def _graph_token(tenant_id: str, client_id: str, client_secret: str) -> Optional[str]:
    if msal is None:
        log.error("msal not installed; cannot obtain Graph token")
        return None
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=authority,
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        log.error("Graph token acquisition failed: %s", result.get("error_description"))
        return None
    return result["access_token"]


def fetch_graph(mbox: Dict[str, Any], since: datetime, senders: List[Sender]) -> List[Deal]:
    """Fetch deals from a Microsoft Graph mailbox (app-only auth).

    Required mbox keys: ``user`` (UPN/email), ``tenant_env``, ``client_env``,
    ``secret_env`` (names of env vars holding those values).
    Optional: ``folder`` (default Inbox), ``top`` (default 200).
    """
    if requests is None:
        log.error("requests not installed; cannot fetch Graph messages")
        return []
    user = mbox.get("user")
    tenant_env = mbox.get("tenant_env", "GRAPH_CHF_TENANT_ID")
    client_env = mbox.get("client_env", "GRAPH_CHF_CLIENT_ID")
    secret_env = mbox.get("secret_env", "GRAPH_CHF_CLIENT_SECRET")

    tenant_id = os.environ.get(tenant_env)
    client_id = os.environ.get(client_env)
    client_secret = os.environ.get(secret_env)
    if not all([user, tenant_id, client_id, client_secret]):
        log.error("Graph mailbox %s missing one or more required env vars", user)
        return []

    token = _graph_token(tenant_id, client_id, client_secret)
    if not token:
        return []

    folder = mbox.get("folder", "Inbox")
    top = int(mbox.get("top", 200))
    since_iso = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    url = (
        f"https://graph.microsoft.com/v1.0/users/{user}/mailFolders/{folder}/messages"
        f"?$top={top}&$filter=receivedDateTime ge {since_iso}"
        f"&$select=id,subject,from,sender,receivedDateTime,body,internetMessageId"
    )
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    deals: List[Deal] = []
    try:
        while url:
            resp = requests.get(url, headers=headers, timeout=60)
            if resp.status_code != 200:
                log.error("Graph fetch %s -> %s %s", user, resp.status_code, resp.text[:500])
                break
            payload = resp.json()
            for item in payload.get("value", []):
                try:
                    from_obj = (item.get("from") or {}).get("emailAddress") or {}
                    from_addr = from_obj.get("address", "")
                    from_name = from_obj.get("name", "")
                    from_hdr = f"{from_name} <{from_addr}>" if from_addr else from_name
                    match = sender_matches(from_hdr, senders)
                    if not match:
                        continue

                    subject = item.get("subject", "") or ""
                    message_id = item.get("internetMessageId") or item.get("id") or ""
                    body = item.get("body") or {}
                    content_type = body.get("contentType", "text")
                    content = body.get("content", "") or ""
                    html_body = content if content_type.lower() == "html" else ""
                    text_body = content if content_type.lower() != "html" else ""

                    extracted = parse_deal_email(
                        html_body=html_body,
                        text_body=text_body,
                        subject=subject,
                        source_wholesaler=match.display_name,
                        source_email=match.email or from_addr,
                        source_message_id=message_id,
                    )
                    deals.extend(extracted)
                except Exception as exc:  # noqa: BLE001
                    log.exception("Error parsing Graph message: %s", exc)
                    continue
            url = payload.get("@odata.nextLink")
    except Exception as exc:  # noqa: BLE001
        log.exception("Graph fetch failed for %s: %s", user, exc)
    return deals


# ---------------------------------------------------------------------------
# Deal parsing
# ---------------------------------------------------------------------------

ADDRESS_RE = re.compile(
    r"(\d{1,6}\s+[A-Z][A-Za-z0-9\.\-']*(?:\s+[A-Z][A-Za-z0-9\.\-']*){0,6}"
    r"(?:\s+(?:St|St\.|Street|Ave|Ave\.|Avenue|Rd|Rd\.|Road|Blvd|Blvd\.|Boulevard|"
    r"Dr|Dr\.|Drive|Ln|Ln\.|Lane|Ct|Ct\.|Court|Ter|Ter\.|Terrace|Pl|Pl\.|Place|"
    r"Way|Hwy|Highway|Pkwy|Parkway|Cir|Cir\.|Circle))?"
    r"(?:,\s*[A-Za-z][A-Za-z\s\.\-]+)?,?\s+(?:FL|Florida)\s+(\d{5})(?:-\d{4})?)",
    re.IGNORECASE,
)

PRICE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)\s*([KkMm])?")
BEDS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:BD|Bed(?:room)?s?|bd)", re.IGNORECASE)
BATHS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:BA|Bath(?:room)?s?|ba)", re.IGNORECASE)
SQFT_RE = re.compile(r"([\d,]+)\s*(?:sq\.?\s*ft\.?|sqft|sf)", re.IGNORECASE)
CITY_STATE_ZIP_RE = re.compile(
    r",\s*([A-Za-z][A-Za-z\s\.\-]+?),?\s+(?:FL|Florida)\s+(\d{5})",
    re.IGNORECASE,
)


def html_to_text(html: str) -> str:
    """Strip HTML to plain text, preserving line breaks between blocks."""
    if not html:
        return ""
    if BeautifulSoup is None:
        # Last-ditch: strip tags crudely
        return re.sub(r"<[^>]+>", " ", html)
    soup = BeautifulSoup(html, "lxml" if _lxml_available() else "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    # Insert newlines at block-level tags so deals on adjacent lines stay separate
    for br in soup.find_all(["br"]):
        br.replace_with("\n")
    for block in soup.find_all(["p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5"]):
        block.append("\n")
    text = soup.get_text(separator=" ")
    # Collapse runs of spaces but keep newlines
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _lxml_available() -> bool:
    try:
        import lxml  # noqa: F401
        return True
    except ImportError:
        return False


def _normalize_price(raw: str, suffix: Optional[str]) -> Optional[int]:
    try:
        val = float(raw.replace(",", ""))
    except ValueError:
        return None
    if suffix:
        if suffix.lower() == "k":
            val *= 1_000
        elif suffix.lower() == "m":
            val *= 1_000_000
    # Filter noise (e.g. "$50" or "$1")
    if val < 1000:
        return None
    return int(val)


def _zip_to_county(zip_code: Optional[str], city: Optional[str]) -> Optional[str]:
    if zip_code:
        if zip_code in FL_ZIP_OVERRIDES:
            return FL_ZIP_OVERRIDES[zip_code]
        prefix = zip_code[:3]
        if prefix in FL_ZIP_PREFIX_TO_COUNTY:
            return FL_ZIP_PREFIX_TO_COUNTY[prefix]
    if city:
        return FL_CITY_TO_COUNTY.get(city.strip().lower())
    return None


def _infer_condition(text: str) -> Optional[str]:
    t = text.lower()
    if any(k in t for k in ("distressed", "heavy rehab", "gut job", "fire damage", "tear down")):
        return "distressed"
    if any(k in t for k in ("fixer", "fixer-upper", "fixer upper", "needs work")):
        return "fixer"
    if any(k in t for k in ("needs rehab", "needs reno", "light rehab", "cosmetic rehab", "cosmetics")):
        return "needs_rehab"
    if any(k in t for k in ("turnkey", "turn-key", "turn key", "rent ready", "rent-ready", "move-in ready")):
        return "turnkey"
    return None


def _strategy_hint(text: str) -> str:
    """Return a hint string summarizing any strategy cues in the deal text."""
    t = text.lower()
    hints: List[str] = []
    for phrase, label in (
        ("fix and flip", "Fix & Flip"),
        ("fix & flip", "Fix & Flip"),
        ("flip", "Fix & Flip"),
        ("brrrr", "BRRRR"),
        ("buy and hold", "Buy & Hold"),
        ("buy & hold", "Buy & Hold"),
        ("rental", "Buy & Hold"),
        ("novation", "Other / Novations"),
        ("wholesale", "Other / Novations"),
    ):
        if phrase in t:
            hints.append(label)
    return " ".join(sorted(set(hints)))


def _extract_around(text: str, start: int, end: int, window: int = 400) -> str:
    lo = max(0, start - window)
    hi = min(len(text), end + window)
    return text[lo:hi]


def _int_or_none(s: str) -> Optional[int]:
    try:
        return int(float(s.replace(",", "")))
    except (ValueError, AttributeError):
        return None


def _float_or_none(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def parse_deal_email(
    html_body: str,
    text_body: str,
    subject: str,
    source_wholesaler: str,
    source_email: str,
    source_message_id: str,
) -> List[Deal]:
    """Parse a wholesaler email into zero-or-more :class:`Deal` records.

    Strategy:
      1. Prefer HTML (stripped to text) as the source; fall back to text body.
      2. Find every address match; treat each as the anchor of one deal.
      3. Extract price, beds, baths, sqft, condition from a context window
         around the address.
      4. If no addresses are found, return a single ``parse_confidence=low``
         deal carrying the raw text so Chris can still see it.

    This function is deliberately unit-testable: it takes plain strings and
    returns plain data objects. No network or side effects.
    """
    text = html_to_text(html_body) if html_body else (text_body or "")
    if not text.strip():
        log.debug("Empty body for message %s", source_message_id)
        return []

    deals: List[Deal] = []
    seen_addresses: set = set()

    for m in ADDRESS_RE.finditer(text):
        addr_full = re.sub(r"\s+", " ", m.group(1)).strip().rstrip(",")
        zip_code = m.group(2)
        if addr_full.lower() in seen_addresses:
            continue
        seen_addresses.add(addr_full.lower())

        window = _extract_around(text, m.start(), m.end(), window=500)

        city = None
        state = "FL"
        csz = CITY_STATE_ZIP_RE.search(addr_full)
        if csz:
            city = csz.group(1).strip()
            zip_code = csz.group(2)

        price = None
        price_match = PRICE_RE.search(window)
        if price_match:
            price = _normalize_price(price_match.group(1), price_match.group(2))

        beds = None
        b = BEDS_RE.search(window)
        if b:
            beds = _int_or_none(b.group(1))

        baths = None
        ba = BATHS_RE.search(window)
        if ba:
            baths = _float_or_none(ba.group(1))

        sqft = None
        sf_m = SQFT_RE.search(window)
        if sf_m:
            sqft = _int_or_none(sf_m.group(1))

        county = _zip_to_county(zip_code, city)
        condition = _infer_condition(window)
        strategy_hint = _strategy_hint(window + " " + subject)

        deals.append(
            Deal(
                source_wholesaler=source_wholesaler,
                source_email=source_email,
                source_message_id=source_message_id,
                source_subject=subject,
                address=addr_full,
                city=city,
                state=state,
                zip_code=zip_code,
                county=county,
                price=price,
                beds=beds,
                baths=baths,
                sqft=sqft,
                condition=condition,
                strategy_hint_text=strategy_hint,
                parse_confidence="high",
                raw_text_excerpt=window[:1000],
            )
        )

    if not deals:
        log.info(
            "No structured deals found in %s (subject=%r); emitting low-confidence deal",
            source_message_id, subject,
        )
        deals.append(
            Deal(
                source_wholesaler=source_wholesaler,
                source_email=source_email,
                source_message_id=source_message_id,
                source_subject=subject,
                address=subject.strip()[:200] or "(unparsed)",
                city=None,
                state=None,
                zip_code=None,
                county=None,
                price=None,
                beds=None,
                baths=None,
                sqft=None,
                condition=None,
                strategy_hint_text=_strategy_hint(subject + " " + text[:2000]),
                parse_confidence="low",
                raw_text_excerpt=text[:2000],
            )
        )

    log.info(
        "Parsed %d deal(s) from %s (source=%s)",
        len(deals), source_message_id, source_wholesaler,
    )
    return deals


# ---------------------------------------------------------------------------
# Salesforce
# ---------------------------------------------------------------------------

def login_salesforce() -> Any:
    """Log in to Salesforce via simple_salesforce; returns an Salesforce client."""
    if Salesforce is None:
        raise RuntimeError("simple_salesforce not installed")
    username = os.environ["SF_USERNAME"]
    password = os.environ["SF_PASSWORD"]
    token = os.environ["SF_SECURITY_TOKEN"]
    sf = Salesforce(username=username, password=password, security_token=token)
    log.info("Salesforce login OK as %s", username)
    return sf


BUYER_FIELDS = [
    "Id",
    "FirstName",
    "LastName",
    "Email",
    "Phone",
    "MobilePhone",
    "HasOptedOutOfEmail",
    "DoNotCall",
    "ContactType__c",
    "Buyer_Primary_Strategy__c",
    "Buyer_Max_Budget__c",
    "Buyer_Counties_of_Interest__c",
    "Buyer_Target_Zips__c",
    "Buyer_Neighborhoods__c",
    "Finance_Type__c",
    "Are_you_willing_to_Rehab__c",
    "Have_you_bought_an_Investment_property__c",
]


# LeadSource values that all mean "CheapHomesFLA buyer who chose counties."
# Canonical is CheapHomesFLA_VIP_Signup (post 2026-05-18 consolidation), but
# legacy / variant values must still match — otherwise buyers whose data hasn't
# been migrated yet get silently dropped from Bucket A. Eddie Sellos discovered
# this the hard way on 2026-05-18.
CHF_BUYER_LEAD_SOURCES = [
    "CheapHomesFLA_VIP_Signup",
    "CheapHomesFLA_LandingPage",
    "Cheap Homes FL - Buyer",
]


def _load_vip_floor() -> List[str]:
    """Load the VIP audience-floor list — buyer emails that MUST receive the
    brief regardless of LeadSource / Buyer_Counties drift in SF.

    File: ~/Desktop/vip_audience_floor.yaml (simple list-of-emails YAML, no
    PyYAML dependency required — we parse a minimal subset by hand so the
    matcher stays import-light).

    Returns lowercase, deduped emails. Missing file → empty list (silent).
    """
    floor_path = Path.home() / "Desktop" / "vip_audience_floor.yaml"
    if not floor_path.exists():
        return []
    emails = set()
    for raw in floor_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Accept both "- email@x.com" and "email: email@x.com" forms.
        if line.startswith("- "):
            line = line[2:].strip()
        if ":" in line and "@" not in line.split(":", 1)[0]:
            # "email: foo@bar" — take after the colon
            line = line.split(":", 1)[1].strip()
        # Strip inline trailing comments ("email@x.com  # note about buyer")
        # AFTER the - / key handling so a leading # doesn't get this far.
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        # Strip surrounding quotes
        line = line.strip('"').strip("'")
        if "@" in line:
            emails.add(line.lower())
    return sorted(emails)


def fetch_active_buyers(sf: Any) -> List[Dict[str, Any]]:
    """Return Contact records that have opted into the CheapHomesFLA buyer
    program via the website form, UNION'd with the VIP audience floor.

    Audience = (LeadSource ∈ CHF buyer set ∧ counties set ∧ budget set ∧
                has-channel) ∪ (Email ∈ vip_audience_floor.yaml)

    The floor list is a belt-and-suspenders safeguard: if a known buyer's
    SF data drifts (LeadSource changes, counties get blanked), they still
    receive the brief. The next day's audit script flags the drift so we
    can fix the underlying record.
    """
    # 1. Standard SOQL filter — every Contact tagged with a CheapHomesFLA buyer
    # LeadSource gets the brief. Policy (Chris locked 2026-05-19):
    #   - Buyer with counties set → filtered brief (matcher honors their counties).
    #   - Buyer with NO counties set → full-state brief (matcher at line ~1149
    #     skips the county filter when buyer_counties is empty).
    #   - Buyer with NO budget set → no price cap (budget_picklist_to_dollars
    #     returns None, matcher treats as unlimited).
    # The previous "rails 2+3 must be NOT NULL" gate was dropped — it was
    # silently excluding ~12 of ~36 CheapHomesFLA buyers from the daily brief.
    # Email/Phone "has any contact channel" rail kept — without a channel we
    # have nowhere to send.
    lead_source_in = ", ".join(f"'{s}'" for s in CHF_BUYER_LEAD_SOURCES)
    fields = ", ".join(BUYER_FIELDS)
    primary_query = (
        f"SELECT {fields} FROM Contact "
        f"WHERE LeadSource IN ({lead_source_in}) "
        f"AND (Email != NULL OR MobilePhone != NULL OR Phone != NULL)"
    )
    log.debug("Primary buyer query: %s", primary_query)
    primary = sf.query_all(primary_query).get("records", [])

    # 2. VIP floor — emails that must be included regardless of filter state.
    floor = _load_vip_floor()
    floor_records: List[Dict[str, Any]] = []
    if floor:
        # Quote-escape emails for the IN clause
        in_list = ", ".join("'" + e.replace("'", "\\'") + "'" for e in floor)
        floor_query = (
            f"SELECT {fields} FROM Contact "
            f"WHERE Email IN ({in_list})"
        )
        log.debug("VIP-floor buyer query: %s", floor_query)
        floor_records = sf.query_all(floor_query).get("records", [])
        log.info(
            "VIP audience floor: %d email(s) configured, %d Contact(s) matched.",
            len(floor), len(floor_records),
        )
        # Surface floor entries that have NO matching Contact — these are the
        # ones we want Chris to know about (the buyer profile is missing).
        matched_emails = {(r.get("Email") or "").lower() for r in floor_records}
        unmatched = [e for e in floor if e not in matched_emails]
        if unmatched:
            log.warning(
                "VIP floor emails with NO Contact in SF: %s — create their "
                "Contacts or remove from the floor file.",
                unmatched,
            )

    # 3. Union by Id; floor records win on conflict (they're the deliberate include).
    by_id: Dict[str, Dict[str, Any]] = {}
    for r in primary:
        r.pop("attributes", None)
        by_id[r["Id"]] = r
    for r in floor_records:
        r.pop("attributes", None)
        if r["Id"] not in by_id:
            r["_floor_override"] = True  # tag so the matcher / logs can show this
        by_id[r["Id"]] = r

    cleaned = list(by_id.values())
    log.info(
        "Fetched %d opted-in buyer Contact(s) — primary filter=%d, floor adds=%d.",
        len(cleaned), len(primary), len(cleaned) - len(primary),
    )

    # Per-buyer audience log for verification before/after a live send.
    audience_log = Path.home() / "Desktop" / f"audience_{datetime.now().strftime('%Y%m%d')}.txt"
    try:
        with audience_log.open("w") as fh:
            fh.write(f"Audience for {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            fh.write(f"Total: {len(cleaned)} buyer(s)\n")
            fh.write("=" * 70 + "\n")
            for r in sorted(cleaned, key=lambda x: (x.get("LastName") or "", x.get("FirstName") or "")):
                tag = " [FLOOR]" if r.get("_floor_override") else ""
                fh.write(
                    f"  {r.get('FirstName','') or ''} {r.get('LastName','') or ''}"
                    f"  <{r.get('Email') or '(no email)'}>"
                    f"  LeadSource={r.get('LeadSource') or '(empty)'}"
                    f"  Zips={r.get('Buyer_Target_Zips__c') or '(empty)'}"
                    f"  Counties={r.get('Buyer_Counties_of_Interest__c') or '(empty)'}"
                    f"{tag}\n"
                )
        log.info("Audience log written: %s", audience_log)
    except Exception as exc:
        log.warning("Could not write audience log: %s", exc)

    if not cleaned:
        log.warning("No opted-in buyers found. Matcher will parse deals but send zero alerts.")
    return cleaned


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

BUDGET_MAP: Dict[str, Optional[int]] = {
    # Original form-style values (if entered that way via Setup UI)
    "< $250k": 250_000,
    "$250k - $500k": 500_000,
    "$500k - $1M": 1_000_000,
    "$1M+": None,
    # "Under ..." variants that the Setup UI wizard may sanitize to
    "Under $250k": 250_000,
    "Under 250k": 250_000,
    # Metadata-API-safe API names (if schema ever deployed via zip)
    "250k to 500k": 500_000,
    "500k to 1M": 1_000_000,
    "1M plus": None,
}


def budget_picklist_to_dollars(value: Optional[str]) -> Optional[int]:
    """Return the upper-bound dollar amount for a budget picklist value.

    Tolerates multiple label formats because different deploy paths (Setup UI
    vs Metadata API) sanitize special characters differently. Any unknown
    value falls through to ``None`` (no price cap), which is safe for matching
    — we'd rather send a possibly-out-of-budget alert than silently filter a
    buyer out due to a string mismatch.
    """
    if not value:
        return None
    v = value.strip()
    hit = BUDGET_MAP.get(v)
    if hit is not None or v in BUDGET_MAP:
        return hit
    # Loose fallback: strip dollar signs, spaces, hyphens; lowercase.
    normalized = v.lower().replace("$", "").replace(",", "").replace(" ", "").replace("-", "")
    loose_map = {
        "<250k": 250_000, "under250k": 250_000,
        "250kto500k": 500_000, "250k500k": 500_000,
        "500kto1m": 1_000_000, "500k1m": 1_000_000,
        "1m+": None, "1mplus": None, "1m": None,
    }
    return loose_map.get(normalized)


def parse_counties(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [c.strip() for c in value.split(";") if c.strip()]


def parse_zips(value: Optional[str]) -> List[str]:
    """Buyer_Target_Zips__c is a Long Text Area. Accepts commas, whitespace,
    or newlines as separators. Only 5-digit numeric tokens are kept."""
    if not value:
        return []
    tokens = re.split(r"[,\s]+", str(value))
    return [t.strip() for t in tokens if t.strip().isdigit() and len(t.strip()) == 5]


def county_from_zip(zip_str: Optional[str]) -> Optional[str]:
    """Map a 5-digit FL zip to its SF Buyer_Counties picklist DISPLAY name
    (e.g. 'Miami-Dade'). Returns None for non-FL or unknown zips.

    Port of countyFromZip() in comps-form-worker — covers ~95% of FL
    population across ~25 counties. Ranges sourced from USPS ZIP-by-county
    tables. Keep in sync with the JS version in
    ~/Desktop/comps-form-worker/src/comps_form_worker.js (~line 240).
    """
    try:
        n = int(str(zip_str or "").strip()[:5])
    except (ValueError, TypeError):
        return None
    if n < 32000 or n > 34999:
        return None
    # South FL tri-county
    if 33010 <= n <= 33199: return "Miami-Dade"
    if 33301 <= n <= 33359: return "Broward"
    if 33060 <= n <= 33099: return "Broward"
    if 33401 <= n <= 33499: return "Palm Beach"
    # Treasure Coast
    if 34945 <= n <= 34988: return "St. Lucie"
    if 34994 <= n <= 34997: return "Martin"
    if 32958 <= n <= 32969: return "Indian River"
    if 34972 <= n <= 34974: return "Okeechobee"
    # SW FL
    if 33901 <= n <= 33994: return "Lee"
    if 34101 <= n <= 34145: return "Collier"
    if 34201 <= n <= 34228: return "Manatee"
    if 34230 <= n <= 34293: return "Sarasota"
    if 33950 <= n <= 33983: return "Charlotte"
    # Tampa Bay
    if 33601 <= n <= 33694: return "Hillsborough"
    if 33701 <= n <= 33784: return "Pinellas"
    if 33523 <= n <= 33597: return "Pasco"
    if 34601 <= n <= 34614: return "Hernando"
    # Central FL
    if 32801 <= n <= 32899: return "Orange"
    if 32701 <= n <= 32799: return "Seminole"
    if 33801 <= n <= 33899: return "Polk"
    if 34471 <= n <= 34488: return "Marion"
    if 34741 <= n <= 34772: return "Osceola"
    if 32757 <= n <= 32788: return "Lake"
    # North FL
    if 32201 <= n <= 32299: return "Duval"
    if 32080 <= n <= 32092: return "St. Johns"
    if 32601 <= n <= 32669: return "Alachua"
    if 32301 <= n <= 32399: return "Leon"
    # East Coast Central
    if 32901 <= n <= 32959: return "Brevard"
    if 32114 <= n <= 32198: return "Volusia"
    return None


def match(deal: Deal, buyer: Dict[str, Any]) -> Tuple[bool, int, List[str]]:
    """Apply hard filters, then compute soft score.

    Returns ``(passes, score, reasons)``. When ``passes`` is False, ``reasons``
    carries the failure description for logging.

    Geo filter hierarchy (Chris locked 2026-05-19 — R16, refined):
      Zips are PER-COUNTY sub-filters, not a global override.

      • Buyer has counties + no zips → standard county filter.
        Every deal in those counties matches.
      • Buyer has counties + zips → for each of the buyer's counties:
          - If buyer specified one or more zips in THAT county → strict zip
            filter for that county only (deal must be in those zips).
          - If buyer specified no zips in that county → all deals in the
            county match (county-wide).
        Example: Axel has counties=Miami-Dade;Broward, zips=33133 (a
        Miami-Dade zip). He gets ONLY 33133 deals in Miami-Dade, but every
        Broward deal (because he didn't specify any Broward zip).
      • Buyer has zips + no counties → strict zip-only filter (edge case).
      • Buyer has neither → full-state brief (R10).
    """
    buyer_zips = parse_zips(buyer.get("Buyer_Target_Zips__c"))
    buyer_counties = parse_counties(buyer.get("Buyer_Counties_of_Interest__c"))

    # Deal dataclass uses zip_code (matching SF MailingPostalCode convention);
    # fall back to .zip for legacy/JSON-fed records.
    deal_zip = (getattr(deal, "zip_code", None) or getattr(deal, "zip", None) or "").strip()

    if buyer_counties:
        # County must match
        if not deal.county:
            return False, 0, ["deal county unknown"]
        if deal.county not in buyer_counties:
            return False, 0, [f"county mismatch: deal={deal.county} buyer={buyer_counties}"]
        # Deal's county IS in buyer's counties.
        # Now apply per-county zip scoping (R16): does buyer have zips for THIS county?
        if buyer_zips:
            zips_in_this_county = [
                z for z in buyer_zips if county_from_zip(z) == deal.county
            ]
            if zips_in_this_county:
                # Buyer restricted this county to specific zips.
                if not deal_zip:
                    return False, 0, [
                        f"deal zip unknown (buyer has zip filter for {deal.county})"
                    ]
                if deal_zip not in zips_in_this_county:
                    return False, 0, [
                        f"zip mismatch in {deal.county}: deal={deal_zip} "
                        f"buyer_zips_for_county={zips_in_this_county}"
                    ]
            # else: buyer has zips but none in this county → county-wide deals OK.
    elif buyer_zips:
        # Edge case: zips set, counties empty. Strict zip-only.
        if not deal_zip:
            return False, 0, ["deal zip unknown (buyer has zip-only filter)"]
        if deal_zip not in buyer_zips:
            return False, 0, [f"zip mismatch: deal={deal_zip} buyer_zips={buyer_zips}"]
    # else: both empty → no geo filter, full-state per R10.

    # Hard: price
    budget_cap = budget_picklist_to_dollars(buyer.get("Buyer_Max_Budget__c"))
    if deal.price is not None and budget_cap is not None and deal.price > budget_cap:
        return False, 0, [f"price {deal.price} above buyer cap {budget_cap}"]

    # Hard: condition vs rehab appetite
    rehab = buyer.get("Are_you_willing_to_Rehab__c")
    if rehab == "No - Turnkey only" and deal.condition in ("distressed", "fixer", "needs_rehab"):
        return False, 0, ["condition mismatch: buyer wants turnkey"]

    # Soft scoring
    score = 10
    strategy = buyer.get("Buyer_Primary_Strategy__c") or ""
    if deal.condition == "distressed" and strategy == "Fix & Flip":
        score += 10
    if deal.condition == "turnkey" and strategy == "Buy & Hold":
        score += 10
    if deal.strategy_hint_text and strategy and strategy.lower() in deal.strategy_hint_text.lower():
        score += 5
    neighborhoods = buyer.get("Buyer_Neighborhoods__c") or ""
    if neighborhoods:
        haystack = (deal.address + " " + (deal.city or "")).lower()
        for n in neighborhoods.split(","):
            n = n.strip().lower()
            if n and n in haystack:
                score += 3

    return True, score, []


# ---------------------------------------------------------------------------
# De-dupe
# ---------------------------------------------------------------------------

_SLUG_PUNCT_RE = re.compile(r"[^a-z0-9\s-]")


def address_slug(address: str) -> str:
    s = (address or "").lower()
    s = _SLUG_PUNCT_RE.sub("", s)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s[:40] or "noaddr"


def match_task_subject(deal: Deal, when: Optional[datetime] = None) -> str:
    when = when or datetime.now()
    return f"CHF-Match-{when.strftime('%Y%m%d')}-{address_slug(deal.address)}"


def already_matched(sf: Any, buyer_id: str, deal: Deal) -> bool:
    subject = match_task_subject(deal)
    # SOQL string escape for single quotes
    safe_subject = subject.replace("'", "\\'")
    safe_buyer = buyer_id.replace("'", "\\'")
    query = (
        f"SELECT Id FROM Task WHERE WhoId = '{safe_buyer}' "
        f"AND Subject = '{safe_subject}' LIMIT 1"
    )
    try:
        res = sf.query(query)
        total = res.get("totalSize", 0)
        return total > 0
    except Exception as exc:  # noqa: BLE001
        log.exception("already_matched query failed: %s", exc)
        # Conservative: treat as matched to avoid resending on transient error
        return True


# ---------------------------------------------------------------------------
# Notification rendering & sending
# ---------------------------------------------------------------------------

def _price_str(deal: Deal) -> str:
    if deal.price is None:
        return "Price: TBD"
    return f"${deal.price:,}"


def _specs_str(deal: Deal) -> str:
    parts: List[str] = []
    if deal.beds is not None:
        parts.append(f"{deal.beds}BR")
    if deal.baths is not None:
        parts.append(f"{deal.baths:g}BA")
    if deal.sqft is not None:
        parts.append(f"{deal.sqft:,} sqft")
    return " / ".join(parts)


def build_sms_body(deal: Deal, buyer: Dict[str, Any]) -> str:
    """Build the SMS body. Keeps total length well under the 1600-char GSM cap."""
    first = buyer.get("FirstName") or "there"
    specs = _specs_str(deal)
    body_lines = [
        f"Hi {first} - new deal from {deal.source_wholesaler}:",
        deal.address,
        f"{_price_str(deal)}" + (f" | {specs}" if specs else ""),
    ]
    if deal.condition:
        body_lines.append(f"Condition: {deal.condition}")
    body_lines.append(
        f'Source email: "{(deal.source_subject or "")[:60]}" (ID: {deal.source_message_id[:40]})'
    )
    body_lines.append("Reply YES for more info. - Cheap Homes FLA")
    return "\n".join(body_lines)


def _h(s: Any) -> str:
    """HTML escape — None becomes empty string."""
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                  .replace('"', "&quot;").replace("'", "&#39;"))


def _money(n: Any) -> str:
    if n is None or n == "":
        return "—"
    try:
        return f"${int(n):,}"
    except (TypeError, ValueError):
        return _h(n)


def _load_county_commentary() -> Dict[str, str]:
    """Load per-county manual editorial paragraphs from county_commentary.md.

    Format: one `## County Name` heading per county; the lines between that
    heading and the next `##` (or EOF) become that county's commentary HTML.
    Empty / placeholder-only sections (just '(...)' in parens) are skipped
    so they don't render as visible empty paragraphs.
    """
    p = Path.home() / "Desktop" / "county_commentary.md"
    if not p.exists():
        return {}
    out: Dict[str, str] = {}
    current_county = None
    current_lines: List[str] = []
    def flush() -> None:
        if not current_county:
            return
        body = "\n".join(current_lines).strip()
        # Skip placeholder-only sections (single paren note or empty).
        # A real commentary will have more than just one line of parenthetical note.
        if not body:
            return
        if body.startswith("(") and body.endswith(")") and "\n" not in body:
            return
        # Very simple md→html: paragraphs split on blank lines + **bold**.
        paras = [b.strip() for b in re.split(r"\n\s*\n", body) if b.strip()]
        html_paras = []
        for para in paras:
            t = _h(para)
            # bold
            t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
            html_paras.append(f'<p style="font-family:Georgia,serif;font-size:14px;line-height:1.55;color:#1a1a1a;margin:0 0 10px 0;">{t}</p>')
        out[current_county] = "\n".join(html_paras)

    for raw in p.read_text().splitlines():
        line = raw.rstrip()
        m = re.match(r"^##\s+(.+)$", line)
        if m:
            flush()
            current_county = m.group(1).strip()
            current_lines = []
        else:
            if current_county is not None:
                current_lines.append(line)
    flush()
    return out


def _county_data_summary(deals_in: List["Deal"]) -> str:
    """Auto-generated, fact-only data summary paragraph for a spotlight.

    Pulled purely from the deals in this spotlight — never invents external
    market stats. Renders count, price range, max spread + which property,
    largest by sqft, etc.
    """
    n = len(deals_in)
    if not n:
        return ""

    prices = [d.price for d in deals_in if getattr(d, "price", None)]
    spreads = []
    for d in deals_in:
        p = getattr(d, "price", None)
        a = getattr(d, "arv", None)
        if p and a:
            spreads.append((int(a) - int(p), d))
    sqfts = [(getattr(d, "sqft", None) or 0, d) for d in deals_in if getattr(d, "sqft", None)]

    bits: List[str] = []
    bits.append(f"<strong>{n} deal{'s' if n != 1 else ''}</strong> in this spotlight today.")

    if prices:
        lo, hi = min(prices), max(prices)
        if lo == hi:
            bits.append(f"All asking <strong>${lo:,}</strong>.")
        else:
            bits.append(f"Asking range <strong>${lo:,} – ${hi:,}</strong>.")

    if spreads:
        spreads.sort(reverse=True, key=lambda t: t[0])
        top_spread, top_deal = spreads[0]
        bits.append(
            f'Biggest spread <strong>${top_spread:,}</strong> on '
            f'<em>{_h(top_deal.address)}</em>'
            f'{" (" + _h(top_deal.city) + ")" if top_deal.city else ""}.'
        )

    if sqfts and len(sqfts) > 1:
        sqfts.sort(reverse=True, key=lambda t: t[0])
        largest = sqfts[0]
        if largest[0] >= 2000:
            bits.append(
                f'Largest property: <strong>{largest[0]:,} sqft</strong> at '
                f'<em>{_h(largest[1].address)}</em>.'
            )

    inner = " ".join(bits)
    return (
        '<div style="background:#fafaf5;border-left:3px solid #d68a1c;padding:14px 16px;margin:0 0 16px 0;">'
        f'<div style="font-family:\'Courier New\',monospace;font-size:10px;letter-spacing:2px;color:#d68a1c;text-transform:uppercase;margin-bottom:6px;">Today\'s data</div>'
        f'<p style="font-family:Georgia,serif;font-size:14px;line-height:1.55;color:#1a1a1a;margin:0;">{inner}</p>'
        "</div>"
    )


def _format_geo_summary(buyer: Dict[str, Any]) -> str:
    """Human-readable description of this buyer's R16 geo filter for the intro."""
    counties = parse_counties(buyer.get("Buyer_Counties_of_Interest__c"))
    zips     = parse_zips(buyer.get("Buyer_Target_Zips__c"))
    if not counties and not zips:
        return "every active county in Florida (no buy-box set)"
    if zips and not counties:
        return "ZIP " + ", ".join(zips) + " statewide"
    parts = []
    for c in counties:
        zips_in_c = [z for z in zips if county_from_zip(z) == c]
        if zips_in_c:
            parts.append(f"{c} (ZIP {', '.join(zips_in_c)})")
        else:
            parts.append(f"{c} (county-wide)")
    return " + ".join(parts)


def build_v4_brief(buyer: Dict[str, Any], deals: List["Deal"]) -> Tuple[str, str]:
    """Render ONE consolidated per-buyer brief in the locked v4 template.

    Spec: ~/Desktop/JOHNSONBUYS_SESSION_STATE.md section "📨 EMAIL TEMPLATE"
    (locked 2026-05-19). Visual reference: ~/Desktop/preview_buyer_email_v4.html
    extracted from the live CC blast at https://conta.cc/49ADUha.

    deals = list of Deal objects already filtered to this buyer's R16 geo.
    Returns (subject, html_body).
    """
    first = _h(buyer.get("FirstName") or "Investor")
    n_deals = len(deals)
    plural = "" if n_deals == 1 else "s"
    geo_summary = _format_geo_summary(buyer)
    today_long = datetime.now().strftime("%A · %B %-d, %Y") if sys.platform != "win32" else datetime.now().strftime("%A · %B %#d, %Y")

    # Subject — tier-neutral, content-forward
    date_short = datetime.now().strftime('%b %-d' if sys.platform != 'win32' else '%b %#d')
    if n_deals == 0:
        subject = f"Your CheapHomesFLA brief · {date_short} — quiet day in your counties, browse below"
    else:
        subject = (
            f"{n_deals} below-market opportunit{'y' if n_deals == 1 else 'ies'} for your buy-box · "
            f"CheapHomesFLA · {date_short}"
        )

    # Group deals into "spotlights" — by county for county buyers, by zip for zip-only.
    # Order: counties as the buyer declared them in SF, then any remainder.
    counties = parse_counties(buyer.get("Buyer_Counties_of_Interest__c"))
    zips     = parse_zips(buyer.get("Buyer_Target_Zips__c"))
    spotlight_keys: List[str] = []   # ordered list of section keys
    spotlight_titles: Dict[str, str] = {}
    by_key: Dict[str, List["Deal"]] = {}

    if counties:
        for c in counties:
            zips_in_c = [z for z in zips if county_from_zip(z) == c]
            title = f"{c} · ZIP {', '.join(zips_in_c)}" if zips_in_c else f"{c} · county-wide"
            spotlight_keys.append(c)
            spotlight_titles[c] = title
            by_key[c] = []
        for d in deals:
            key = d.county if d.county in by_key else (counties[0] if counties else "_other")
            by_key.setdefault(key, []).append(d)
    elif zips:
        # Zip-only buyer (R16 edge case)
        for d in deals:
            z = (getattr(d, "zip_code", None) or getattr(d, "zip", None) or "?")
            by_key.setdefault(z, []).append(d)
        spotlight_keys = sorted(by_key.keys())
        for z in spotlight_keys:
            spotlight_titles[z] = f"ZIP {z}"
    else:
        # No geo — single statewide section
        spotlight_keys = ["_all"]
        spotlight_titles["_all"] = "Florida statewide"
        by_key["_all"] = list(deals)

    # Keep spotlights for counties the buyer EXPLICITLY chose even when no
    # deals matched — those sections still render with commentary + the
    # "See more [County] →" button so the buyer can browse the live
    # county-deals-worker page. Only drop empty zip-only spotlights (edge case).
    if counties:
        # Make sure every buyer-county has a (possibly empty) bucket
        for c in counties:
            by_key.setdefault(c, [])
        spotlight_keys = list(counties)
    else:
        spotlight_keys = [k for k in spotlight_keys if by_key.get(k)]
    total_spotlights = len(spotlight_keys)

    # Load manual commentary (county_commentary.md) once per email
    commentary = _load_county_commentary()

    # ── Spotlight section renderer ──
    def render_spotlight(idx: int, total: int, title: str, deals_in: List["Deal"], start_n: int) -> str:
        cards = []
        for i, d in enumerate(deals_in):
            n = start_n + i
            addr_full = _h(d.address or "Address available on request")
            city_zip = " ".join(filter(None, [d.city, getattr(d, "state", None), getattr(d, "zip_code", None) or getattr(d, "zip", None)]))
            specs_bits = []
            if getattr(d, "beds", None):     specs_bits.append(f"{d.beds} bed")
            if getattr(d, "baths", None):    specs_bits.append(f"{d.baths} bath")
            if getattr(d, "sqft", None):     specs_bits.append(f"{int(d.sqft):,} sqft")
            if getattr(d, "property_type", None): specs_bits.append(_h(d.property_type))
            subline = _h(" · ".join(specs_bits)) if specs_bits else "Specs available on request"
            price   = _money(getattr(d, "price", None) or getattr(d, "asking_price", None))
            arv     = _money(getattr(d, "arv", None))
            spread_val = None
            try:
                p = getattr(d, "price", None) or getattr(d, "asking_price", None)
                a = getattr(d, "arv", None)
                if p and a:
                    spread_val = int(a) - int(p)
            except (TypeError, ValueError):
                spread_val = None
            spread = _money(spread_val)

            inquire_url = (
                f"https://comps.cheaphomesfla.com/today?"
                f"address={urllib.parse.quote(d.address or '')}"
                f"&city={urllib.parse.quote(d.city or '')}"
                f"&zip={urllib.parse.quote(str(getattr(d, 'zip_code', None) or getattr(d, 'zip', None) or ''))}"
                f"&utm_source=sendgrid&utm_campaign=daily_{datetime.now().strftime('%Y%m%d')}"
            )

            cards.append(f"""
      <tr><td class="px-mobile" style="padding:24px 32px 0 32px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
          <tr>
            <td class="card-num-wrap" valign="top" style="width:70px;padding-right:14px;">
              <div class="card-num" style="font-family:Georgia,serif;font-size:38px;line-height:1;color:#bbb;">{n:02d}</div>
            </td>
            <td valign="top">
              <div style="font-family:Georgia,serif;font-size:18px;color:#0d0d0d;font-weight:bold;line-height:1.25;">{addr_full}</div>
              <div style="font-family:Georgia,serif;font-size:13px;color:#555;margin-top:4px;">{subline} · {_h(city_zip)}</div>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin-top:14px;border-top:1px solid #e0e0d8;border-bottom:1px solid #e0e0d8;">
                <tr>
                  <td class="price-cell" style="padding:12px 0;border-right:1px solid #e0e0d8;">
                    <div style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:1px;color:#666;text-transform:uppercase;">Asking</div>
                    <div style="font-family:Georgia,serif;font-size:18px;color:#0a7c2f;font-weight:bold;margin-top:3px;">{price}</div>
                  </td>
                  <td class="price-cell" style="padding:12px 14px;border-right:1px solid #e0e0d8;">
                    <div style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:1px;color:#666;text-transform:uppercase;">ARV Est.</div>
                    <div style="font-family:Georgia,serif;font-size:18px;color:#0d0d0d;font-weight:bold;margin-top:3px;">{arv}</div>
                  </td>
                  <td class="price-cell" style="padding:12px 14px;">
                    <div style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:1px;color:#666;text-transform:uppercase;">Spread</div>
                    <div style="font-family:Georgia,serif;font-size:18px;color:#0d0d0d;font-weight:bold;margin-top:3px;">{spread}</div>
                  </td>
                </tr>
              </table>
              <div style="margin-top:14px;">
                <a class="inquire-btn" href="{inquire_url}" style="display:block;background:#0a66c2;color:#ffffff;font-family:Georgia,serif;font-size:14px;font-weight:bold;text-decoration:none;padding:14px 18px;border-radius:4px;text-align:center;">Request photos, comps &amp; a showing — {addr_full} →</a>
              </div>
            </td>
          </tr>
        </table>
      </td></tr>
""")

        # Compute the county-deals-worker URL for "See more in [County] →".
        # Title looks like "Miami-Dade · ZIP 33133" or "Broward · county-wide".
        # The county portion is everything before " · ". Slug rule matches
        # comps-form-worker's countyFromZip().slug — lowercase, & → and, periods
        # stripped, spaces and slashes → hyphens.
        county_name = title.split(" · ")[0].strip() if " · " in title else title.strip()
        slug = (
            county_name.lower()
            .replace(".", "")
            .replace(" & ", "-and-")
            .replace(" ", "-")
            .replace("/", "-")
        )
        # Per-spotlight footer button: "See more [County] deals today →"
        # Links to county-deals-worker page (deployed 2026-05-18, route
        # comps.cheaphomesfla.com/today/*). UTM-tagged so click attribution
        # back to this email works in the worker's analytics.
        county_footer = f"""
      <tr><td style="padding:8px 32px 0 32px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
          <tr>
            <td valign="top" style="width:70px;padding-right:14px;"></td>
            <td valign="top">
              <a href="https://comps.cheaphomesfla.com/today/{slug}?ref=sendgrid-{datetime.now().strftime('%Y%m%d')}-{slug}&utm_source=sendgrid&utm_campaign=daily_{datetime.now().strftime('%Y%m%d')}&utm_content=county_browse" style="display:block;background:#0a66c2;color:#ffffff;font-family:Georgia,serif;font-size:14px;font-weight:bold;text-decoration:none;padding:14px 18px;border-radius:4px;text-align:center;">See more {_h(county_name)} deals today →</a>
            </td>
          </tr>
        </table>
      </td></tr>"""

        # County-specific content block: auto-stats summary + optional manual commentary
        data_summary_html = _county_data_summary(deals_in)
        manual_html = commentary.get(county_name, "")
        manual_block = (
            f'<div style="margin:0 0 16px 0;">{manual_html}</div>' if manual_html else ""
        )
        content_block = ""
        if data_summary_html or manual_block:
            content_block = f"""
      <tr><td class="px-mobile" style="padding:20px 32px 0 32px;">
        {data_summary_html}
        {manual_block}
      </td></tr>"""

        return f"""
      <tr><td class="px-mobile" style="padding:28px 32px 8px 32px;">
        <div style="border-top:1px solid #1a1a1a;border-bottom:1px solid #1a1a1a;padding:14px 0;text-align:center;">
          <div style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:2px;color:#1a1a1a;text-transform:uppercase;">Spotlight {idx} of {total} · {len(deals_in)} active</div>
          <div style="font-family:Georgia,serif;font-size:26px;color:#0d0d0d;margin-top:6px;">{_h(title)}</div>
        </div>
      </td></tr>{content_block}
{''.join(cards)}{county_footer}"""

    spotlights_html = []
    deal_n = 1
    for i, k in enumerate(spotlight_keys, start=1):
        deals_in = by_key[k]
        spotlights_html.append(render_spotlight(i, total_spotlights, spotlight_titles[k], deals_in, deal_n))
        deal_n += len(deals_in)

    # Stat strip metrics
    largest_spread = "—"
    try:
        spreads = []
        for d in deals:
            p = getattr(d, "price", None) or getattr(d, "asking_price", None)
            a = getattr(d, "arv", None)
            if p and a:
                spreads.append(int(a) - int(p))
        if spreads:
            top = max(spreads)
            largest_spread = f"${top//1000}K" if top >= 1000 else f"${top:,}"
    except Exception:
        pass

    most_active = "—"
    if spotlight_keys and counties:
        most_active = max(spotlight_keys, key=lambda k: len(by_key[k]))

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only">
<meta name="supported-color-schemes" content="light">
<title>CheapHomesFLA · Daily Brief</title>
<style type="text/css">
  /* Mobile-only overrides — supported in iOS Mail, Gmail mobile, Apple Mail,
     and most modern email clients. Outlook desktop ignores @media so it keeps
     the 680px desktop layout. */
  @media only screen and (max-width: 600px) {{
    table.brief-container {{ width:100% !important; }}
    /* Tighten outer gutter from 32px → 18px on phones */
    .px-mobile {{ padding-left:18px !important; padding-right:18px !important; }}
    /* Hero typography scales down */
    h1.brief-hero {{ font-size:32px !important; line-height:1 !important; }}
    .brief-spotlight-title {{ font-size:22px !important; }}
    /* Stat strip 4-col → 2x2 grid on mobile */
    .stat-cell {{ display:inline-block !important; width:50% !important; box-sizing:border-box !important; border-right:none !important; border-bottom:1px solid #333 !important; }}
    .stat-cell:nth-child(2n) {{ border-right:none !important; }}
    .stat-cell:nth-last-child(-n+2) {{ border-bottom:none !important; }}
    /* Rates row: 4 cells become 2x2 grid on mobile */
    .rates-row td {{ display:inline-block !important; width:50% !important; box-sizing:border-box !important; }}
    .rates-row td.rates-badge {{ display:block !important; width:100% !important; text-align:center !important; }}
    /* Per-deal price stack: ASKING / ARV / SPREAD stacks vertically */
    .price-cell {{ display:block !important; width:100% !important; border-right:none !important; border-bottom:1px solid #e0e0d8 !important; padding:10px 0 !important; }}
    .price-cell:last-child {{ border-bottom:none !important; }}
    /* Deal-card number column gets smaller + above content instead of beside */
    .card-num {{ font-size:26px !important; padding-right:0 !important; padding-bottom:6px !important; width:auto !important; display:block !important; }}
    .card-num-wrap {{ display:block !important; width:100% !important; }}
    /* Per-deal CTA button stays full width on mobile (already is, just ensure wrap) */
    a.inquire-btn {{ font-size:13px !important; padding:13px 12px !important; line-height:1.3 !important; }}
  }}
</style>
</head>
<body style="margin:0;padding:0;background:#f5f5f0;font-family:Georgia,serif;color:#1a1a1a;">
<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background:#f5f5f0;">
  <tr><td align="center">

    <table class="brief-container" role="presentation" cellspacing="0" cellpadding="0" border="0" width="680" style="max-width:680px;width:100%;background:#ffffff;margin:0;">

      <tr><td class="px-mobile" style="padding:36px 32px 8px 32px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
          <tr>
            <td style="font-family:'Courier New',monospace;font-size:11px;letter-spacing:2px;color:#1a1a1a;text-transform:uppercase;">Vol. 1 · Daily Brief</td>
            <td align="right" style="font-family:Georgia,serif;font-size:13px;color:#1a1a1a;">{_h(today_long)}</td>
          </tr>
        </table>
        <h1 class="brief-hero" style="font-family:Georgia,serif;font-size:42px;line-height:1;margin:8px 0 6px 0;font-weight:normal;color:#0d0d0d;">CheapHomesFLA</h1>
        <div style="font-family:Georgia,serif;font-style:italic;font-size:14px;color:#666;margin-bottom:14px;">Florida's Daily Below-Market Investment Brief — for {first}</div>
        <a href="https://comps.cheaphomesfla.com/today" style="font-family:Georgia,serif;font-size:14px;color:#0a66c2;text-decoration:none;font-weight:bold;">Browse today's full Florida inventory by county →</a>
      </td></tr>

      <tr><td class="px-mobile" style="padding:0 32px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#1a1a1a;color:#ffffff;">
          <tr>
            <td class="stat-cell" style="padding:18px 14px;border-right:1px solid #333;">
              <div style="font-family:Georgia,serif;font-size:24px;color:#ffffff;line-height:1;">{n_deals}</div>
              <div style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:1.5px;color:#bbb;text-transform:uppercase;margin-top:4px;">For Your Box</div>
            </td>
            <td class="stat-cell" style="padding:18px 14px;border-right:1px solid #333;">
              <div style="font-family:Georgia,serif;font-size:24px;color:#ffffff;line-height:1;">{total_spotlights}</div>
              <div style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:1.5px;color:#bbb;text-transform:uppercase;margin-top:4px;">Markets Active</div>
            </td>
            <td class="stat-cell" style="padding:18px 14px;border-right:1px solid #333;">
              <div style="font-family:Georgia,serif;font-size:24px;color:#0a7c2f;line-height:1;">{_h(largest_spread)}</div>
              <div style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:1.5px;color:#bbb;text-transform:uppercase;margin-top:4px;">Largest Spread</div>
            </td>
            <td class="stat-cell" style="padding:18px 14px;">
              <div style="font-family:Georgia,serif;font-size:22px;color:#ffffff;line-height:1;">{_h(most_active)}</div>
              <div style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:1.5px;color:#bbb;text-transform:uppercase;margin-top:4px;">Most Active</div>
            </td>
          </tr>
        </table>
      </td></tr>

      <tr><td class="px-mobile" style="padding:24px 32px 4px 32px;">
        <p style="font-family:Georgia,serif;font-size:15px;line-height:1.55;color:#1a1a1a;margin:0;">Hi {first},</p>
        <p style="font-family:Georgia,serif;font-size:15px;line-height:1.55;color:#1a1a1a;margin:8px 0 0 0;">
          {("Today nothing in our wholesaler intake matched your buy-box (<strong>" + _h(geo_summary) + "</strong>) — but your counties are still active below. Click through to browse each county's live inventory at comps.cheaphomesfla.com. Today's narrowness is normal for narrow zip filters; the daily flow widens over the week.") if n_deals == 0 else ("Today's filtered cut: <strong>" + str(n_deals) + " below-market opportunit" + ("y" if n_deals == 1 else "ies") + "</strong> across <strong>" + _h(geo_summary) + "</strong>. Your buy-box is honored — nothing outside it.")} <a href="https://www.cheaphomesfla.com/?utm_source=sendgrid&utm_campaign=buybox" style="color:#0a66c2;">Adjust counties or zips →</a>
        </p>
      </td></tr>

      {''.join(spotlights_html)}

      <tr><td class="px-mobile" style="padding:0 32px 36px 32px;border-top:1px solid #1a1a1a;padding-top:32px;">
        <div style="font-family:Georgia,serif;font-size:13px;color:#1a1a1a;line-height:1.6;">
          <strong>CheapHomesFLA · Johnson Buys</strong><br>
          <span style="font-family:'Courier New',monospace;font-size:12px;color:#555;">(305) 575-9040 · info@cheaphomesFLA.com</span>
        </div>
        <div style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:0.5px;color:#888;margin-top:14px;line-height:1.5;">
          You're receiving this because you opted into the CheapHomesFLA buyer brief and selected counties / zips in your buy-box. Reply STOP to skip tomorrow.
        </div>
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""

    return subject, html


def _rank_deals_for_feature(deals_in: List["Deal"]) -> List["Deal"]:
    """Sort a county's deals best-first for the featured slot.

    Chris's editorial bias (locked 2026-05-19): the CC blast features investor-
    friendly fix-and-flip / value-add deals in the $200K–$750K band, not
    mega-deals or waterfront developments. Mega-deals still appear in the
    "+ X more →" overflow pill — they're not hidden, just not featured.

    Tier order (lowest-numbered tier wins):
      0. Under $750K asking WITH real ARV → spread DESC
      1. Under $750K asking, no ARV → price ASC (cheapest entry first)
      2. $750K+ WITH real ARV → spread DESC (mega-deals at bottom)
      3. $750K+ without ARV → price ASC
      4. No price data (lowest)
    """
    SWEET_SPOT_CAP = 750_000
    def key(d):
        p = getattr(d, "price", None)
        a = getattr(d, "arv", None)
        if p and a and p < SWEET_SPOT_CAP:
            return (0, -(int(a) - int(p)))
        if p and p < SWEET_SPOT_CAP:
            return (1, int(p))
        if p and a:
            return (2, -(int(a) - int(p)))
        if p:
            return (3, int(p))
        return (4, 0)
    return sorted(deals_in, key=key)


def build_cc_statewide(deals: List["Deal"], top_per_county: int = 3) -> Tuple[str, str]:
    """Render the CC statewide brief (Bucket B) — same v4 design language as
    per-buyer briefs but scoped to ALL deals (no R16 filter, no per-buyer geo).

    Audience: full Cheap Homes FLA master list (~22K). Chris composes in the
    CC web UI; this function produces paste-ready HTML.

    Differences from build_v4_brief() (per-buyer Bucket A):
      - No buyer FirstName personalization → "Hi investor," or just no salutation
      - No per-buyer geo summary
      - Stat strip shows STATEWIDE numbers
      - Spotlights group by county, ordered by deal count desc
      - Per-spotlight content (data summary + commentary) same as Bucket A
      - "See more [County] →" buttons same as Bucket A
      - Adds a "Active across the rest of Florida" county grid at the very
        bottom — every FL county we can list, linking to /today/{slug}
      - Footer text: "You're receiving this as a CheapHomesFLA subscriber.
        Set your buy-box at cheaphomesfla.com to get a county-filtered brief
        instead." (encourages flip from Bucket B → Bucket A)
    """
    commentary = _load_county_commentary()
    today_long = datetime.now().strftime("%A · %B %-d, %Y") if sys.platform != "win32" else datetime.now().strftime("%A · %B %#d, %Y")
    date_short = datetime.now().strftime('%b %-d' if sys.platform != 'win32' else '%b %#d')
    n_deals = len(deals)

    # Group deals by county
    by_county: Dict[str, List["Deal"]] = {}
    for d in deals:
        if not d.county and d.zip_code:
            d.county = county_from_zip(d.zip_code)
        key = d.county or "Other Florida"
        by_county.setdefault(key, []).append(d)

    # Order spotlights by deal count desc; if tie, alphabetical
    county_order = sorted(by_county.keys(), key=lambda c: (-len(by_county[c]), c))
    total_spotlights = len(county_order)

    # Subject
    subject = f"{n_deals} below-market opportunities across Florida · CheapHomesFLA · {date_short}"

    # Stat strip metrics — investor-band only (<$1M asking) so mega-deals
    # like $5M+ developments don't dominate the top "Largest Spread" stat.
    INVESTOR_PRICE_CAP = 1_000_000
    spreads = []
    for d in deals:
        p = getattr(d, "price", None)
        a = getattr(d, "arv", None)
        if p and a and int(p) < INVESTOR_PRICE_CAP:
            spreads.append(int(a) - int(p))
    largest_spread = "—"
    if spreads:
        top = max(spreads)
        # Format clearly: $1.2M for ≥$1M, $250K for ≥$10K, $9,500 for less.
        if top >= 1_000_000:
            largest_spread = f"${top/1_000_000:.1f}M"
        elif top >= 10_000:
            largest_spread = f"${top//1000}K"
        else:
            largest_spread = f"${top:,}"
    most_active = county_order[0] if county_order else "—"

    # ── Spotlight renderer (shared structure with build_v4_brief) ──
    def render_spotlight(idx: int, total: int, county_name: str, deals_in: List["Deal"], start_n: int) -> str:
        cards = []
        for i, d in enumerate(deals_in):
            n = start_n + i
            addr_full = _h(d.address or "Address available on request")
            city_zip = " ".join(filter(None, [d.city, getattr(d, "state", None), getattr(d, "zip_code", None)]))
            specs_bits = []
            if getattr(d, "beds", None):     specs_bits.append(f"{d.beds} bed")
            if getattr(d, "baths", None):    specs_bits.append(f"{d.baths} bath")
            if getattr(d, "sqft", None):     specs_bits.append(f"{int(d.sqft):,} sqft")
            if getattr(d, "property_type", None): specs_bits.append(_h(d.property_type))
            subline = _h(" · ".join(specs_bits)) if specs_bits else "Specs available on request"
            price = _money(getattr(d, "price", None))
            arv   = _money(getattr(d, "arv", None))
            try:
                p = getattr(d, "price", None); a = getattr(d, "arv", None)
                spread_val = (int(a) - int(p)) if (p and a) else None
            except (TypeError, ValueError):
                spread_val = None
            spread = _money(spread_val)
            inquire_url = (
                f"https://comps.cheaphomesfla.com/today?"
                f"address={urllib.parse.quote(d.address or '')}"
                f"&city={urllib.parse.quote(d.city or '')}"
                f"&zip={urllib.parse.quote(str(getattr(d, 'zip_code', None) or ''))}"
                f"&utm_source=cc&utm_campaign=daily_{datetime.now().strftime('%Y%m%d')}"
            )
            cards.append(f"""
      <tr><td class="px-mobile" style="padding:24px 32px 0 32px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
          <tr>
            <td class="card-num-wrap" valign="top" style="width:70px;padding-right:14px;">
              <div class="card-num" style="font-family:Georgia,serif;font-size:38px;line-height:1;color:#bbb;">{n:02d}</div>
            </td>
            <td valign="top">
              <div style="font-family:Georgia,serif;font-size:18px;color:#0d0d0d;font-weight:bold;line-height:1.25;">{addr_full}</div>
              <div style="font-family:Georgia,serif;font-size:13px;color:#555;margin-top:4px;">{subline} · {_h(city_zip)}</div>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin-top:14px;border-top:1px solid #e0e0d8;border-bottom:1px solid #e0e0d8;">
                <tr>
                  <td class="price-cell" style="padding:12px 0;border-right:1px solid #e0e0d8;">
                    <div style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:1px;color:#666;text-transform:uppercase;">Asking</div>
                    <div style="font-family:Georgia,serif;font-size:18px;color:#0a7c2f;font-weight:bold;margin-top:3px;">{price}</div>
                  </td>
                  <td class="price-cell" style="padding:12px 14px;border-right:1px solid #e0e0d8;">
                    <div style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:1px;color:#666;text-transform:uppercase;">ARV Est.</div>
                    <div style="font-family:Georgia,serif;font-size:18px;color:#0d0d0d;font-weight:bold;margin-top:3px;">{arv}</div>
                  </td>
                  <td class="price-cell" style="padding:12px 14px;">
                    <div style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:1px;color:#666;text-transform:uppercase;">Spread</div>
                    <div style="font-family:Georgia,serif;font-size:18px;color:#0d0d0d;font-weight:bold;margin-top:3px;">{spread}</div>
                  </td>
                </tr>
              </table>
              <div style="margin-top:14px;">
                <a class="inquire-btn" href="{inquire_url}" style="display:block;background:#0a66c2;color:#ffffff;font-family:Georgia,serif;font-size:14px;font-weight:bold;text-decoration:none;padding:14px 18px;border-radius:4px;text-align:center;">Request photos, comps &amp; a showing — {addr_full} →</a>
              </div>
            </td>
          </tr>
        </table>
      </td></tr>
""")
        slug = county_name.lower().replace(".", "").replace(" & ", "-and-").replace(" ", "-").replace("/", "-")
        county_footer = f"""
      <tr><td class="px-mobile" style="padding:8px 32px 0 32px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
          <tr>
            <td valign="top" style="width:70px;padding-right:14px;"></td>
            <td valign="top">
              <a href="https://comps.cheaphomesfla.com/today/{slug}?ref=cc-{datetime.now().strftime('%Y%m%d')}-{slug}&utm_source=cc&utm_campaign=daily_{datetime.now().strftime('%Y%m%d')}&utm_content=county_browse" style="display:block;background:#0a66c2;color:#ffffff;font-family:Georgia,serif;font-size:14px;font-weight:bold;text-decoration:none;padding:14px 18px;border-radius:4px;text-align:center;">See more {_h(county_name)} deals today →</a>
            </td>
          </tr>
        </table>
      </td></tr>"""
        data_summary_html = _county_data_summary(deals_in)
        manual_html = commentary.get(county_name, "")
        manual_block = f'<div style="margin:0 0 16px 0;">{manual_html}</div>' if manual_html else ""
        content_block = ""
        if data_summary_html or manual_block:
            content_block = f"""
      <tr><td class="px-mobile" style="padding:20px 32px 0 32px;">
        {data_summary_html}
        {manual_block}
      </td></tr>"""
        return f"""
      <tr><td class="px-mobile" style="padding:28px 32px 8px 32px;">
        <div style="border-top:1px solid #1a1a1a;border-bottom:1px solid #1a1a1a;padding:14px 0;text-align:center;">
          <div style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:2px;color:#1a1a1a;text-transform:uppercase;">Spotlight {idx} of {total} · {len(deals_in)} active</div>
          <div style="font-family:Georgia,serif;font-size:26px;color:#0d0d0d;margin-top:6px;">{_h(county_name)}</div>
        </div>
      </td></tr>{content_block}
{''.join(cards)}{county_footer}"""

    # For each spotlight, feature only the top N deals by spread DESC; the
    # rest roll into a "+ X more in [County] today →" pill at the end of the
    # spotlight (links to /today/{slug}). Per Chris 2026-05-19: 3-4 featured
    # per county keeps the email tight; CC blast yesterday did same pattern.
    spotlights_html = []
    deal_n = 1
    for i, c in enumerate(county_order, start=1):
        ranked = _rank_deals_for_feature(by_county[c])
        featured = ranked[:top_per_county]
        overflow_count = max(0, len(ranked) - top_per_county)
        spotlights_html.append(render_spotlight(i, total_spotlights, c, featured, deal_n))
        # Add an overflow pill if there are more deals in this county
        if overflow_count > 0:
            slug = c.lower().replace(".", "").replace(" & ", "-and-").replace(" ", "-").replace("/", "-")
            overflow_pill = f"""
      <tr><td class="px-mobile" style="padding:8px 32px 0 32px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
          <tr>
            <td valign="top" style="width:70px;padding-right:14px;"></td>
            <td valign="top" style="text-align:center;padding:8px 0;">
              <a href="https://comps.cheaphomesfla.com/today/{slug}?ref=cc-{datetime.now().strftime('%Y%m%d')}-{slug}-overflow&utm_source=cc&utm_campaign=daily_{datetime.now().strftime('%Y%m%d')}&utm_content=overflow" style="font-family:Georgia,serif;font-size:14px;color:#0a66c2;text-decoration:none;font-style:italic;">+ {overflow_count} more in {_h(c)} today →</a>
            </td>
          </tr>
        </table>
      </td></tr>"""
            spotlights_html.append(overflow_pill)
        deal_n += len(featured)

    # County grid at bottom — every FL county CheapHomesFLA covers (23 per
    # Chris locked 2026-05-19). Ordered geographically S→N E→W within region.
    all_fl_counties = [
        # South FL tri-county
        "Miami-Dade", "Broward", "Palm Beach",
        # Treasure Coast
        "Martin", "St. Lucie", "Indian River", "Okeechobee",
        # SW FL
        "Lee", "Collier", "Charlotte", "Sarasota", "Manatee",
        # Tampa Bay
        "Hillsborough", "Pinellas", "Pasco", "Hernando",
        # Central FL
        "Orange", "Seminole", "Lake", "Osceola", "Polk",
        # East-Central FL
        "Brevard", "Volusia",
    ]
    # 3-column TABLE grid (matches yesterday's CC blast structure at
    # conta.cc/4ue2sop). Each cell is a visible cream-background box with:
    # County name (large), deal count (bold), browse link. Counties with
    # deals today render with a green "N today" stat; counties without
    # render "Browse →".
    #
    # Live-count backstop (per Chris 2026-05-19 "get those fucking numbers
    # right"): if ~/Desktop/county_counts_today.json exists (written by
    # fetch_live_county_counts.py against comps.cheaphomesfla.com/today/{slug}),
    # we use the MAX of (local-JSON tally, live worker tally) so the grid
    # never under-reports.
    live_counts: dict = {}
    try:
        import json as _json, os as _os
        _live_path = _os.path.expanduser("~/Desktop/county_counts_today.json")
        if _os.path.exists(_live_path):
            with open(_live_path) as _f:
                _payload = _json.load(_f)
            live_counts = _payload.get("counts", {}) or {}
    except Exception:
        live_counts = {}

    grid_rows_html = []
    # Build rows of 3 columns
    for row_start in range(0, len(all_fl_counties), 3):
        row_cells = []
        for c in all_fl_counties[row_start:row_start + 3]:
            slug = c.lower().replace(".", "").replace(" & ", "-and-").replace(" ", "-").replace("/", "-")
            _local_n = len(by_county.get(c, []))
            _live_n = live_counts.get(c)
            try:
                _live_n = int(_live_n) if _live_n is not None else None
            except (TypeError, ValueError):
                _live_n = None
            # Use the larger of the two so the box never under-reports
            n_today = max(_local_n, _live_n or 0)
            if n_today > 0:
                count_html = (
                    f'<div style="font-family:Georgia,serif;font-size:22px;color:#0a7c2f;font-weight:bold;line-height:1;">{n_today}</div>'
                    f'<div style="font-family:\'Courier New\',monospace;font-size:10px;letter-spacing:1px;color:#666;text-transform:uppercase;margin-top:4px;">Active today</div>'
                )
            else:
                count_html = (
                    f'<div style="font-family:Georgia,serif;font-size:13px;color:#0a66c2;line-height:1.3;">Browse →</div>'
                    f'<div style="font-family:\'Courier New\',monospace;font-size:10px;letter-spacing:1px;color:#999;text-transform:uppercase;margin-top:4px;">Updated daily</div>'
                )
            row_cells.append(
                f'<td valign="top" width="33%" style="padding:0 4px 8px 4px;">'
                f'<a href="https://comps.cheaphomesfla.com/today/{slug}?utm_source=cc&utm_campaign=daily_{datetime.now().strftime("%Y%m%d")}&utm_content=county_grid" '
                f'style="display:block;background:#fafaf5;border:1px solid #e0e0d8;border-radius:6px;padding:14px;text-decoration:none;color:#1a1a1a;">'
                f'<div style="font-family:Georgia,serif;font-size:16px;color:#0d0d0d;font-weight:bold;line-height:1.2;margin-bottom:8px;">{_h(c)}</div>'
                f'{count_html}'
                f'</a>'
                f'</td>'
            )
        # Pad row if last row has fewer than 3 cells
        while len(row_cells) < 3:
            row_cells.append('<td width="33%" style="padding:0 4px 8px 4px;"></td>')
        grid_rows_html.append(f'<tr>{"".join(row_cells)}</tr>')
    county_grid_html = (
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
        'style="border-collapse:separate;border-spacing:0;">'
        f'{"".join(grid_rows_html)}'
        '</table>'
    )

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only">
<title>CheapHomesFLA · Daily Brief</title>
<style type="text/css">
  @media only screen and (max-width: 600px) {{
    table.brief-container {{ width:100% !important; }}
    .px-mobile {{ padding-left:18px !important; padding-right:18px !important; }}
    h1.brief-hero {{ font-size:32px !important; line-height:1 !important; }}
    .brief-spotlight-title {{ font-size:22px !important; }}
    .stat-cell {{ display:inline-block !important; width:50% !important; box-sizing:border-box !important; border-right:none !important; border-bottom:1px solid #333 !important; }}
    .stat-cell:nth-last-child(-n+2) {{ border-bottom:none !important; }}
    .rates-row td {{ display:inline-block !important; width:50% !important; box-sizing:border-box !important; }}
    .rates-row td.rates-badge {{ display:block !important; width:100% !important; text-align:center !important; }}
    .price-cell {{ display:block !important; width:100% !important; border-right:none !important; border-bottom:1px solid #e0e0d8 !important; padding:10px 0 !important; }}
    .price-cell:last-child {{ border-bottom:none !important; }}
    .card-num {{ font-size:26px !important; padding-right:0 !important; padding-bottom:6px !important; width:auto !important; display:block !important; }}
    .card-num-wrap {{ display:block !important; width:100% !important; }}
    a.inquire-btn {{ font-size:13px !important; padding:13px 12px !important; line-height:1.3 !important; }}
  }}
</style>
</head>
<body style="margin:0;padding:0;background:#f5f5f0;font-family:Georgia,serif;color:#1a1a1a;">
<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background:#f5f5f0;">
  <tr><td align="center">
    <table class="brief-container" role="presentation" cellspacing="0" cellpadding="0" border="0" width="680" style="max-width:680px;width:100%;background:#ffffff;margin:0;">

      <tr><td class="px-mobile" style="padding:36px 32px 8px 32px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
          <tr>
            <td style="font-family:'Courier New',monospace;font-size:11px;letter-spacing:2px;color:#1a1a1a;text-transform:uppercase;">Vol. 1 · Daily Brief</td>
            <td align="right" style="font-family:Georgia,serif;font-size:13px;color:#1a1a1a;">{_h(today_long)}</td>
          </tr>
        </table>
        <h1 class="brief-hero" style="font-family:Georgia,serif;font-size:42px;line-height:1;margin:8px 0 6px 0;font-weight:normal;color:#0d0d0d;">CheapHomesFLA</h1>
        <div style="font-family:Georgia,serif;font-style:italic;font-size:14px;color:#666;margin-bottom:14px;">Florida's Daily Below-Market Investment Brief</div>
        <a href="https://comps.cheaphomesfla.com/today" style="font-family:Georgia,serif;font-size:14px;color:#0a66c2;text-decoration:none;font-weight:bold;">Browse today's full Florida inventory by county →</a>
      </td></tr>

      <tr><td class="px-mobile" style="padding:0 32px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#1a1a1a;color:#ffffff;">
          <tr>
            <td class="stat-cell" style="padding:18px 14px;border-right:1px solid #333;">
              <div style="font-family:Georgia,serif;font-size:24px;color:#ffffff;line-height:1;">{n_deals}</div>
              <div style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:1.5px;color:#bbb;text-transform:uppercase;margin-top:4px;">Active Today</div>
            </td>
            <td class="stat-cell" style="padding:18px 14px;border-right:1px solid #333;">
              <div style="font-family:Georgia,serif;font-size:24px;color:#ffffff;line-height:1;">{total_spotlights}</div>
              <div style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:1.5px;color:#bbb;text-transform:uppercase;margin-top:4px;">Counties Active</div>
            </td>
            <td class="stat-cell" style="padding:18px 14px;border-right:1px solid #333;">
              <div style="font-family:Georgia,serif;font-size:24px;color:#0a7c2f;line-height:1;">{_h(largest_spread)}</div>
              <div style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:1.5px;color:#bbb;text-transform:uppercase;margin-top:4px;">Largest Spread</div>
            </td>
            <td class="stat-cell" style="padding:18px 14px;">
              <div style="font-family:Georgia,serif;font-size:22px;color:#ffffff;line-height:1;">{_h(most_active)}</div>
              <div style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:1.5px;color:#bbb;text-transform:uppercase;margin-top:4px;">Most Active</div>
            </td>
          </tr>
        </table>
      </td></tr>

      <tr><td class="px-mobile" style="padding:24px 32px 4px 32px;">
        <p style="font-family:Georgia,serif;font-size:15px;line-height:1.55;color:#1a1a1a;margin:0;">
          <strong>Today's statewide brief:</strong> {n_deals} below-market opportunities across {total_spotlights} Florida counties, sourced from our 26-wholesaler network and the WhatsApp off-market pipeline. Below: every active deal, grouped by county. At the bottom: links to every Florida county we cover for buyers who want to widen the lens.
        </p>
        <p style="font-family:Georgia,serif;font-size:14px;line-height:1.55;color:#555;margin:12px 0 0 0;font-style:italic;">
          Want a brief filtered to only your counties + zips instead of statewide? <a href="https://www.cheaphomesfla.com/?utm_source=cc&utm_campaign=buybox" style="color:#0a66c2;font-style:normal;">Set your buy-box →</a> Takes 60 seconds, runs daily after that.
        </p>
      </td></tr>

      {''.join(spotlights_html)}

      <tr><td class="px-mobile" style="padding:40px 32px 12px 32px;border-top:1px solid #1a1a1a;">
        <div style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:2px;color:#1a1a1a;text-transform:uppercase;margin-bottom:12px;">Active across the rest of Florida</div>
        <p style="font-family:Georgia,serif;font-size:14px;line-height:1.55;color:#1a1a1a;margin:0 0 14px 0;">
          Click any county to see what's live there today. Inventory updates daily from our 26-wholesaler network.
        </p>
        <div>{county_grid_html}</div>
      </td></tr>

      <tr><td class="px-mobile" style="padding:32px 32px 36px 32px;">
        <div style="font-family:Georgia,serif;font-size:13px;color:#1a1a1a;line-height:1.6;">
          <strong>CheapHomesFLA · Johnson Buys</strong><br>
          <span style="font-family:'Courier New',monospace;font-size:12px;color:#555;">(305) 575-9040 · info@cheaphomesFLA.com</span>
        </div>
        <div style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:0.5px;color:#888;margin-top:14px;line-height:1.5;">
          You're receiving this as a CheapHomesFLA subscriber. <a href="https://www.cheaphomesfla.com/?utm_source=cc&utm_campaign=buybox" style="color:#0a66c2;">Set your buy-box</a> to get a county-filtered brief instead of statewide.
        </div>
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""
    return subject, html


def build_email_html(deal: "Deal", buyer: Dict[str, Any]) -> Tuple[str, str]:
    """LEGACY single-deal renderer — DEPRECATED.

    Per Chris 2026-05-19: do NOT send one-email-per-matched-deal. Send ONE
    consolidated email per buyer using build_v4_brief(). The main loop must
    group matches by buyer first, then call build_v4_brief() once.

    This function is kept as a no-op stub so any unmigrated caller fails
    fast with a clear message instead of silently shipping the old template.
    """
    raise RuntimeError(
        "build_email_html() is deprecated. Use build_v4_brief(buyer, deals[]) — "
        "one consolidated email per buyer, not per deal. Per Chris 2026-05-19."
    )

    # (unreachable — kept below to preserve original code for emergency reference)
    first = buyer.get("FirstName") or "Investor"
    specs = _specs_str(deal) or "Specs: TBD"
    subject = f"[Cheap Homes FLA] New deal: {deal.address[:80]}"
    safe_excerpt = (deal.raw_text_excerpt or "").replace("<", "&lt;").replace(">", "&gt;")
    html = f"""<!doctype html>
<html>
<body style="font-family: Arial, sans-serif; color: #222;">
  <p>Hi {first},</p>
  <p>New off-market deal forwarded from <strong>{deal.source_wholesaler}</strong>
     (source: {deal.source_email}).</p>
  <table cellpadding="6" cellspacing="0" border="0" style="border-collapse: collapse;">
    <tr><td><strong>Address</strong></td><td>{deal.address}</td></tr>
    <tr><td><strong>City / State / ZIP</strong></td><td>{deal.city or ''} {deal.state or ''} {deal.zip_code or ''}</td></tr>
    <tr><td><strong>County</strong></td><td>{deal.county or ''}</td></tr>
    <tr><td><strong>Price</strong></td><td>{_price_str(deal)}</td></tr>
    <tr><td><strong>Specs</strong></td><td>{specs}</td></tr>
    <tr><td><strong>Condition</strong></td><td>{deal.condition or 'Not stated'}</td></tr>
  </table>
  <p><strong>Reply to this email to receive more info</strong> - we will forward
     your interest directly to {deal.source_wholesaler}.</p>
  <hr>
  <p style="font-size: 12px; color: #666;">
    Source subject: {deal.source_subject}<br>
    Source message ID: {deal.source_message_id}<br>
    Parse confidence: {deal.parse_confidence}
  </p>
  <details>
    <summary style="font-size: 12px; color: #666;">Original excerpt</summary>
    <pre style="white-space: pre-wrap; font-size: 12px; color: #444;">{safe_excerpt}</pre>
  </details>
  <p style="font-size: 12px; color: #666;">
    Chris Johnson - Cheap Homes FLA / Johnson Buys<br>
    info@cheaphomesFLA.com
  </p>
</body>
</html>"""
    return subject, html


def _send_sms(twilio: Any, to_number: str, body: str) -> None:
    twilio.messages.create(from_=TWILIO_FROM_NUMBER, to=to_number, body=body)


def _send_email(sg: Any, to_email: str, subject: str, html: str) -> None:
    msg = Mail(
        from_email=(SENDGRID_FROM_EMAIL, SENDGRID_FROM_NAME),
        to_emails=to_email,
        subject=subject,
        html_content=html,
    )
    sg.send(msg)


def _create_match_task(sf: Any, buyer_id: str, deal: Deal, score: int) -> None:
    subject = match_task_subject(deal)
    body_lines = [
        f"Source wholesaler: {deal.source_wholesaler} <{deal.source_email}>",
        f"Source subject: {deal.source_subject}",
        f"Source message ID: {deal.source_message_id}",
        f"Address: {deal.address}",
        f"City/State/ZIP: {deal.city or ''} {deal.state or ''} {deal.zip_code or ''}",
        f"County: {deal.county or ''}",
        f"Price: {_price_str(deal)}",
        f"Specs: {_specs_str(deal)}",
        f"Condition: {deal.condition or ''}",
        f"Match score: {score}",
        f"Parse confidence: {deal.parse_confidence}",
    ]
    sf.Task.create({
        "Subject": subject,
        "WhoId": buyer_id,
        "Status": "Completed",
        "Priority": "Normal",
        "ActivityDate": datetime.now().strftime("%Y-%m-%d"),
        "Description": "\n".join(body_lines),
    })


def send_match(
    twilio: Any,
    sg: Any,
    sf: Any,
    deal: Deal,
    buyer: Dict[str, Any],
    score: int,
) -> None:
    """Send SMS + email for a matched deal and create the dedupe Task.

    Defensive: individual channel failures are logged but do not raise.
    """
    opted_out_email = bool(buyer.get("HasOptedOutOfEmail"))
    do_not_call = bool(buyer.get("DoNotCall"))
    phone = buyer.get("MobilePhone") or buyer.get("Phone")
    email_addr = buyer.get("Email")

    sms_sent = False
    email_sent = False

    # SMS
    if phone and not do_not_call and twilio is not None:
        try:
            body = build_sms_body(deal, buyer)
            _send_sms(twilio, phone, body)
            sms_sent = True
            log.info("SMS sent to %s (%s) for %s", buyer.get("Id"), phone, deal.address)
        except Exception as exc:  # noqa: BLE001
            log.exception("SMS send failed for %s: %s", buyer.get("Id"), exc)
    else:
        log.debug("Skipping SMS for %s (phone=%s, DNC=%s)", buyer.get("Id"), bool(phone), do_not_call)

    # Email
    if email_addr and not opted_out_email and sg is not None:
        try:
            subject, html = build_email_html(deal, buyer)
            _send_email(sg, email_addr, subject, html)
            email_sent = True
            log.info("Email sent to %s (%s) for %s", buyer.get("Id"), email_addr, deal.address)
        except Exception as exc:  # noqa: BLE001
            log.exception("Email send failed for %s: %s", buyer.get("Id"), exc)
    else:
        log.debug(
            "Skipping email for %s (email=%s, opted_out=%s)",
            buyer.get("Id"), bool(email_addr), opted_out_email,
        )

    # Create dedupe Task if at least one channel landed
    if sms_sent or email_sent:
        try:
            _create_match_task(sf, buyer["Id"], deal, score)
            log.info("Created match Task for %s (%s)", buyer.get("Id"), deal.address)
        except Exception as exc:  # noqa: BLE001
            log.exception("Task create failed for %s: %s", buyer.get("Id"), exc)
    else:
        log.warning(
            "No channel delivered for buyer=%s deal=%s; not creating Task",
            buyer.get("Id"), deal.address,
        )


# ---------------------------------------------------------------------------
# Final log file
# ---------------------------------------------------------------------------

def write_log_file(stats: Dict[str, int], deals: List[Deal], buyers: List[Dict[str, Any]]) -> None:
    path = Path(LOG_DIR) / f"cheaphomes_match_log_{datetime.now().strftime('%Y%m%d')}.txt"
    lines = [
        "",
        "=" * 72,
        f"RUN SUMMARY {datetime.now().isoformat(timespec='seconds')}",
        "=" * 72,
        f"Deals parsed:    {stats.get('deals', 0)}",
        f"Buyers loaded:   {stats.get('buyers', 0)}",
        f"Matches sent:    {stats.get('matches_sent', 0)}",
        f"Skipped (dupe):  {stats.get('skipped_dupe', 0)}",
        f"Skipped (optout):{stats.get('skipped_optout', 0)}",
        f"Errors:          {stats.get('errors', 0)}",
        "",
        "Deals:",
    ]
    for d in deals:
        lines.append(
            f"  - [{d.parse_confidence}] {d.source_wholesaler} | {d.address} "
            f"| {d.city or ''} {d.zip_code or ''} | {_price_str(d)} | {_specs_str(d)}"
        )
    lines.append("")
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError as exc:
        log.exception("Failed to write summary log: %s", exc)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cheap Homes FLA deal matcher")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what WOULD be sent; do not send SMS/email or create Tasks.",
    )
    parser.add_argument(
        "--since",
        type=int,
        default=26,
        help="How many hours back to pull mail from (default: 26 — covers the full 24h with a 2h overlap buffer against launchd jitter).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose / DEBUG-level logging.",
    )
    parser.add_argument(
        "--deals-json",
        type=str,
        default=None,
        help="Path to a JSON file of deals to use INSTEAD of scraping mailboxes. "
             "Bypasses the Gmail/Graph fetch entirely. Use when Graph creds are "
             "rotten and you have a hand-built deal list (or one scraped via "
             "Outlook MCP). File schema: {\"deals\": [{address, city, state, zip_code, "
             "county, price, arv, beds, baths, sqft, property_type, condition, "
             "source_wholesaler, source_email, source_subject, source_message_id, "
             "parse_confidence, raw_text_excerpt}, ...]}",
    )
    parser.add_argument(
        "--skip-health-check",
        action="store_true",
        help="Skip the credential pre-flight check (NOT recommended).",
    )
    return parser.parse_args(argv)


def check_health(args: argparse.Namespace) -> Tuple[bool, List[str]]:
    """Pre-flight watchdog (added 2026-05-19 per Chris).

    Validates that the deal pipeline has the minimum credentials + config it
    needs BEFORE any scraping happens. Returns (all_clear, problems[]).

    Catches the recurring silent-failure modes:
      - Empty GRAPH_CHF_* env vars (info@cheaphomesfla.com unreachable)
      - Missing SF login creds
      - Missing SendGrid API key (only on live send)
      - All mailboxes disabled AND no --deals-json fallback
      - Gmail app passwords look revoked (heuristic: SF says they all
        rotated, but we can't confirm without an actual login attempt)

    Writes a status JSON to ~/Desktop/health_check_status.json so any
    sibling script can see the latest state without re-running.
    """
    problems: List[str] = []

    # 1. Salesforce — required for buyer audience
    sf_user = os.environ.get("SF_USERNAME") or ""
    sf_pwd  = os.environ.get("SF_PASSWORD") or ""
    sf_tok  = os.environ.get("SF_SECURITY_TOKEN") or ""
    if not (sf_user and sf_pwd and sf_tok):
        problems.append(
            f"SF creds incomplete (USERNAME={'set' if sf_user else 'EMPTY'}, "
            f"PASSWORD={'set' if sf_pwd else 'EMPTY'}, "
            f"SECURITY_TOKEN={'set' if sf_tok else 'EMPTY'}) — "
            "fix in ~/Desktop/.env.cheaphomesfla"
        )

    # 2. Deal source — either --deals-json OR at least one enabled mailbox
    if args.deals_json:
        if not Path(args.deals_json).exists():
            problems.append(f"--deals-json file not found: {args.deals_json}")
    else:
        # Need at least one enabled mailbox with valid creds.
        try:
            mboxes = load_mailbox_config(MAILBOX_CONFIG_FILE)
        except Exception as exc:  # noqa: BLE001
            mboxes = []
            problems.append(f"Could not load mailbox config: {exc}")
        if not mboxes:
            problems.append(
                "No enabled mailboxes in ~/Desktop/mailbox_config.json AND no "
                "--deals-json fallback supplied. Nothing to scrape."
            )
        else:
            # Check each enabled mailbox's required env vars upfront.
            for mb in mboxes:
                kind = (mb.get("type") or "").lower()
                if kind == "gmail":
                    pw_env = mb.get("password_env", "")
                    if pw_env and not os.environ.get(pw_env):
                        problems.append(
                            f"Gmail mailbox {mb.get('username','?')}: env var "
                            f"{pw_env} is empty — regenerate the Google app "
                            f"password at https://myaccount.google.com/apppasswords"
                        )
                elif kind == "graph":
                    for ek in ("tenant_env", "client_env", "secret_env"):
                        envname = mb.get(ek, "")
                        if envname and not os.environ.get(envname):
                            problems.append(
                                f"Graph mailbox {mb.get('user','?')}: env var "
                                f"{envname} is empty — paste from Azure Portal → "
                                f"App Registrations for the Mail.Read app"
                            )

    # 3. SendGrid — only required on live send
    if not args.dry_run:
        if not os.environ.get("SENDGRID_API_KEY"):
            problems.append("SENDGRID_API_KEY is empty — live send will fail.")

    # Write status file regardless (visible to Morning Health Check.command)
    try:
        status = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "all_clear": not problems,
            "problems": problems,
            "mode": "dry-run" if args.dry_run else "live",
            "deals_source": args.deals_json or "mailbox-scrape",
        }
        (Path.home() / "Desktop" / "health_check_status.json").write_text(
            json.dumps(status, indent=2)
        )
    except Exception:
        pass  # status file is best-effort

    return (not problems), problems


def load_deals_json(path: str) -> List[Deal]:
    """Load deals from a JSON file (bypasses the mailbox scrape).

    Schema: see --deals-json help string. Missing optional fields fall back to
    Deal dataclass defaults. The four required fields are source_wholesaler,
    source_email, source_message_id, source_subject — synthesize them from
    whatever you have if your source doesn't carry them natively.
    """
    p = Path(path)
    if not p.exists():
        log.error("--deals-json file not found: %s", path)
        return []
    try:
        data = json.loads(p.read_text())
    except Exception as exc:  # noqa: BLE001
        log.error("Could not parse --deals-json file %s: %s", path, exc)
        return []

    raw_deals = data.get("deals") if isinstance(data, dict) else data
    if not isinstance(raw_deals, list):
        log.error("--deals-json must contain a top-level 'deals' array or be an array itself")
        return []

    out: List[Deal] = []
    for i, d in enumerate(raw_deals):
        try:
            # Required fields with safe defaults so we don't crash on partial data
            kwargs = {
                "source_wholesaler": d.get("source_wholesaler") or "Unknown",
                "source_email":      d.get("source_email") or "unknown@unknown",
                "source_message_id": d.get("source_message_id") or f"json-{i}",
                "source_subject":    d.get("source_subject") or "",
                "address":           d.get("address") or "",
                "city":              d.get("city"),
                "state":             d.get("state"),
                "zip_code":          d.get("zip_code") or d.get("zip"),
                "county":            d.get("county"),
                "price":             d.get("price"),
                "arv":               d.get("arv"),
                "beds":              d.get("beds"),
                "baths":             d.get("baths"),
                "sqft":              d.get("sqft"),
                "condition":         d.get("condition"),
                "strategy_hint_text": d.get("strategy_hint_text") or "",
                "parse_confidence":  d.get("parse_confidence") or "high",
                "raw_text_excerpt":  d.get("raw_text_excerpt") or "",
            }
            out.append(Deal(**kwargs))
        except Exception as exc:  # noqa: BLE001
            log.warning("Skipping malformed deal[%d]: %s", i, exc)
            continue

    log.info("Loaded %d deal(s) from JSON: %s", len(out), path)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose)
    log.info(
        "Starting deal_matcher (dry_run=%s, since=%sh, deals_json=%s)",
        args.dry_run, args.since, args.deals_json or "(none)",
    )

    # ── Pre-flight health check (Chris locked 2026-05-19) ─────────────────
    if not args.skip_health_check:
        ok, problems = check_health(args)
        if not ok:
            log.error("=" * 70)
            log.error("PRE-FLIGHT HEALTH CHECK FAILED — %d issue(s):", len(problems))
            for i, p in enumerate(problems, 1):
                log.error("  %d. %s", i, p)
            log.error("=" * 70)
            log.error("Refusing to run. To bypass (NOT recommended), pass --skip-health-check.")
            log.error("Status file: ~/Desktop/health_check_status.json")
            return 4
        log.info("✓ Pre-flight health check passed.")

    senders = load_senders(SENDERS_FILE)
    if not senders:
        log.error("No approved senders loaded; aborting.")
        return 2

    since = datetime.now(timezone.utc) - timedelta(hours=args.since)
    deals: List[Deal] = []

    if args.deals_json:
        # ── JSON-driven path: bypass mailbox scrape entirely ────────────
        log.info("Loading deals from JSON (skipping mailbox scrape): %s", args.deals_json)
        deals = load_deals_json(args.deals_json)
    else:
        # ── Normal scrape path (Gmail IMAP + Graph) ─────────────────────
        mailboxes = load_mailbox_config(MAILBOX_CONFIG_FILE)
        if not mailboxes:
            log.error("No mailboxes configured; aborting.")
            return 2

        for mbox in mailboxes:
            kind = (mbox.get("type") or "").lower()
            try:
                if kind == "gmail":
                    deals.extend(fetch_gmail(mbox, since, senders))
                elif kind == "graph":
                    deals.extend(fetch_graph(mbox, since, senders))
                else:
                    log.warning("Unknown mailbox type %r; skipping", kind)
            except Exception as exc:  # noqa: BLE001
                log.exception("Mailbox fetch failed (%s): %s", kind, exc)

    # Backfill county from zip when missing (helps R16 zip-only filters resolve)
    for d in deals:
        if not d.county and (d.zip_code or getattr(d, "zip", None)):
            d.county = county_from_zip(d.zip_code or getattr(d, "zip", None))

    log.info("Total deals parsed: %d", len(deals))

    # Salesforce
    try:
        sf = login_salesforce()
    except Exception as exc:  # noqa: BLE001
        log.exception("Salesforce login failed: %s", exc)
        return 3

    try:
        buyers = fetch_active_buyers(sf)
    except Exception as exc:  # noqa: BLE001
        log.exception("Failed to fetch buyers: %s", exc)
        buyers = []

    # Twilio / SendGrid clients (None if we're dry-running or creds missing)
    twilio = None
    sg = None
    if not args.dry_run:
        try:
            if TwilioClient is None:
                raise RuntimeError("twilio SDK not installed")
            twilio = TwilioClient(
                os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"],
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("Twilio client init failed; SMS disabled: %s", exc)
            twilio = None
        try:
            if SendGridAPIClient is None:
                raise RuntimeError("sendgrid SDK not installed")
            sg = SendGridAPIClient(os.environ["SENDGRID_API_KEY"])
        except Exception as exc:  # noqa: BLE001
            log.exception("SendGrid client init failed; email disabled: %s", exc)
            sg = None

    stats: Dict[str, int] = {
        "deals": len(deals),
        "buyers": len(buyers),
        "matches_sent": 0,
        "skipped_dupe": 0,
        "skipped_optout": 0,
        "errors": 0,
    }
    per_buyer_count: Dict[str, int] = defaultdict(int)
    kill_switch_tripped = False

    # ── PASS 1 — collect all (deal, buyer) matches into per-buyer baskets ──
    # Per Chris 2026-05-19 (R17): send ONE consolidated email per buyer with
    # all their matched deals as cards, NOT one email per matched deal.
    matches_by_buyer: Dict[str, Dict[str, Any]] = {}
    # shape: { buyer_id: {"buyer": buyer_dict, "deals": [Deal, ...], "scores": [int, ...]} }

    for deal in deals:
        for buyer in buyers:
            try:
                passes, score, reasons = match(deal, buyer)
                if not passes:
                    log.debug(
                        "No match: buyer=%s deal=%s reasons=%s",
                        buyer.get("Id"), deal.address, reasons,
                    )
                    continue
                if buyer.get("HasOptedOutOfEmail") and buyer.get("DoNotCall"):
                    stats["skipped_optout"] += 1
                    log.debug("Skipping buyer=%s (email opt-out AND DNC)", buyer.get("Id"))
                    continue
                bid = buyer["Id"]
                bucket = matches_by_buyer.setdefault(
                    bid, {"buyer": buyer, "deals": [], "scores": []}
                )
                bucket["deals"].append(deal)
                bucket["scores"].append(score)
            except Exception as exc:  # noqa: BLE001
                stats["errors"] += 1
                log.exception(
                    "Match error: buyer=%s deal=%s: %s",
                    buyer.get("Id"), getattr(deal, "address", "?"), exc,
                )

    log.info(
        "Match pass complete: %d buyers got matches (of %d audience), %d total deal-buyer pairs",
        len(matches_by_buyer),
        len(buyers),
        sum(len(b["deals"]) for b in matches_by_buyer.values()),
    )

    # ── PASS 2 — render + send (or preview) one v4 brief per buyer ──
    desktop = Path.home() / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    today_str = datetime.now().strftime("%Y%m%d")

    for bid, bucket in matches_by_buyer.items():
        buyer = bucket["buyer"]
        buyer_deals = bucket["deals"]
        email = (buyer.get("Email") or "").strip()
        if not email:
            log.info("Skipping buyer=%s — no Email on Contact", bid)
            continue

        try:
            subject, html = build_v4_brief(buyer, buyer_deals)
        except Exception as exc:  # noqa: BLE001
            stats["errors"] += 1
            log.exception("Render failed for buyer=%s: %s", bid, exc)
            continue

        # Always dump the rendered per-buyer brief to Desktop so Chris can
        # eyeball any one of them BEFORE the live send fires. File name is
        # the buyer's email (sanitized) so it's obvious which is which.
        safe_email = re.sub(r"[^a-zA-Z0-9._-]", "_", email)
        brief_path = desktop / f"audience_brief_{today_str}_{safe_email}.html"
        try:
            brief_path.write_text(html)
            log.info(
                "Brief rendered for %s — %d deal(s) — preview: %s",
                email, len(buyer_deals), brief_path,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not write brief preview for %s: %s", email, exc)

        if args.dry_run:
            stats["matches_sent"] += len(buyer_deals)
            continue

        # Global kill-switch on live sends only — protects against accidental fan-out.
        if stats["matches_sent"] >= MAX_MATCHES_PER_RUN:
            log.error(
                "KILL-SWITCH: matches_sent=%d >= MAX_MATCHES_PER_RUN=%d — "
                "aborting remaining live sends. Review filters.",
                stats["matches_sent"], MAX_MATCHES_PER_RUN,
            )
            break

        # Skip live-send entirely on a buyer if EVERY deal in their bucket is
        # already matched (SF Task dedupe) — would just be a re-send.
        unsent_deals = []
        unsent_scores = []
        for d, s in zip(buyer_deals, bucket["scores"]):
            if already_matched(sf, bid, d):
                stats["skipped_dupe"] += 1
                log.info("Dedupe: buyer=%s already got deal=%s", bid, d.address)
            else:
                unsent_deals.append(d)
                unsent_scores.append(s)
        if not unsent_deals:
            log.info("All %d deal(s) for buyer=%s already sent in prior runs; no email fired.",
                     len(buyer_deals), bid)
            continue

        # Re-render with only the unsent subset so the brief shows fresh content.
        try:
            subject, html = build_v4_brief(buyer, unsent_deals)
        except Exception as exc:  # noqa: BLE001
            stats["errors"] += 1
            log.exception("Re-render (post-dedupe) failed for buyer=%s: %s", bid, exc)
            continue

        # Send the one consolidated email
        try:
            if sg is None:
                raise RuntimeError("SendGrid client not initialized")
            _send_email(sg, email, subject, html)
            stats["matches_sent"] += len(unsent_deals)
            log.info(
                "✓ Sent v4 brief to %s — %d deal(s)",
                email, len(unsent_deals),
            )
        except Exception as exc:  # noqa: BLE001
            stats["errors"] += 1
            log.exception("SendGrid failed for %s: %s", email, exc)
            continue

        # Create one SF Task per (deal, buyer) for dedupe on future runs.
        for d, s in zip(unsent_deals, unsent_scores):
            try:
                _create_match_task(sf, bid, d, s)
            except Exception as exc:  # noqa: BLE001
                log.warning("Task create failed for buyer=%s deal=%s: %s", bid, d.address, exc)

    write_log_file(stats, deals, buyers)
    log.info("Done. Stats: %s", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
