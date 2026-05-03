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
    "Buyer_Neighborhoods__c",
    "Finance_Type__c",
    "Are_you_willing_to_Rehab__c",
    "Have_you_bought_an_Investment_property__c",
]


def fetch_active_buyers(sf: Any) -> List[Dict[str, Any]]:
    """Return Contact records that have opted into the CheapHomesFLA buyer
    program via the website form.

    SAFETY RAIL: we require *both* `Buyer_Counties_of_Interest__c` and
    `Buyer_Max_Budget__c` to be populated. This matches the cheaphomesFLA.com
    form (all 4 buyer fields are required). Contacts tagged `ContactType__c
    INCLUDES ('Buyer')` but missing those fields are legacy / general contacts
    who have NOT explicitly requested deal alerts; sending to them blindly
    would be spam and a runaway cost. If a buyer wants alerts, they fill the
    form. This is deliberately conservative.
    """
    fields = ", ".join(BUYER_FIELDS)
    query = (
        f"SELECT {fields} FROM Contact "
        f"WHERE ContactType__c INCLUDES ('Buyer') "
        f"AND Buyer_Counties_of_Interest__c != NULL "
        f"AND Buyer_Max_Budget__c != NULL "
        f"AND (Email != NULL OR MobilePhone != NULL OR Phone != NULL)"
    )
    log.debug("Buyer query: %s", query)
    results = sf.query_all(query)
    records = results.get("records", [])
    cleaned = []
    for r in records:
        r.pop("attributes", None)
        cleaned.append(r)
    log.info(
        "Fetched %d opted-in buyer Contact(s) (filter: counties + budget set)",
        len(cleaned),
    )
    if not cleaned:
        log.warning(
            "No opted-in buyers found. Matcher will parse deals but send zero "
            "alerts. Buyers will start flowing in once the cheaphomesFLA.com "
            "form -> Salesforce Zap is built and submissions populate "
            "Buyer_Counties_of_Interest__c + Buyer_Max_Budget__c."
        )
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


def match(deal: Deal, buyer: Dict[str, Any]) -> Tuple[bool, int, List[str]]:
    """Apply hard filters, then compute soft score.

    Returns ``(passes, score, reasons)``. When ``passes`` is False, ``reasons``
    carries the failure description for logging.
    """
    buyer_counties = parse_counties(buyer.get("Buyer_Counties_of_Interest__c"))
    # Hard: county. If deal county unknown, we cannot match.
    if not deal.county:
        return False, 0, ["deal county unknown"]
    if buyer_counties and deal.county not in buyer_counties:
        return False, 0, [f"county mismatch: deal={deal.county} buyer={buyer_counties}"]

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


def build_email_html(deal: Deal, buyer: Dict[str, Any]) -> Tuple[str, str]:
    """Return (subject, html_body) for the SendGrid email."""
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
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose)
    log.info(
        "Starting deal_matcher (dry_run=%s, since=%sh)", args.dry_run, args.since,
    )

    senders = load_senders(SENDERS_FILE)
    if not senders:
        log.error("No approved senders loaded; aborting.")
        return 2

    mailboxes = load_mailbox_config(MAILBOX_CONFIG_FILE)
    if not mailboxes:
        log.error("No mailboxes configured; aborting.")
        return 2

    since = datetime.now(timezone.utc) - timedelta(hours=args.since)

    deals: List[Deal] = []
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

    for deal in deals:
        if kill_switch_tripped:
            break
        for buyer in buyers:
            # Global kill-switch: if we've already queued too many sends in
            # this run, something is wrong — abort before costing money.
            if stats["matches_sent"] >= MAX_MATCHES_PER_RUN:
                log.error(
                    "KILL-SWITCH: matches_sent=%d >= MAX_MATCHES_PER_RUN=%d — "
                    "aborting remainder of this run. Review filters.",
                    stats["matches_sent"], MAX_MATCHES_PER_RUN,
                )
                kill_switch_tripped = True
                break
            try:
                passes, score, reasons = match(deal, buyer)
                if not passes:
                    log.debug(
                        "No match: buyer=%s deal=%s reasons=%s",
                        buyer.get("Id"), deal.address, reasons,
                    )
                    continue

                if per_buyer_count[buyer["Id"]] >= MAX_MATCHES_PER_BUYER_PER_DAY:
                    log.info(
                        "Rate-limit hit for buyer=%s (>= %d matches today); skipping",
                        buyer.get("Id"), MAX_MATCHES_PER_BUYER_PER_DAY,
                    )
                    continue

                if buyer.get("HasOptedOutOfEmail") and buyer.get("DoNotCall"):
                    stats["skipped_optout"] += 1
                    log.info("Skipping buyer=%s (both email opt-out AND DNC)", buyer.get("Id"))
                    continue

                if args.dry_run:
                    log.info(
                        "[DRY-RUN] Would send to %s (%s): %s | source=%s | score=%d",
                        buyer.get("Email") or buyer.get("MobilePhone") or buyer.get("Id"),
                        buyer.get("Id"),
                        deal.address,
                        deal.source_wholesaler,
                        score,
                    )
                    stats["matches_sent"] += 1
                    per_buyer_count[buyer["Id"]] += 1
                    continue

                if already_matched(sf, buyer["Id"], deal):
                    stats["skipped_dupe"] += 1
                    log.info(
                        "Dedupe: already sent buyer=%s deal=%s",
                        buyer.get("Id"), deal.address,
                    )
                    continue

                send_match(twilio, sg, sf, deal, buyer, score)
                stats["matches_sent"] += 1
                per_buyer_count[buyer["Id"]] += 1
            except Exception as exc:  # noqa: BLE001
                stats["errors"] += 1
                log.exception(
                    "Error processing buyer=%s deal=%s: %s",
                    buyer.get("Id"), getattr(deal, "address", "?"), exc,
                )

    write_log_file(stats, deals, buyers)
    log.info("Done. Stats: %s", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
