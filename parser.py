"""
parser.py — wholesaler email body → list of clean ParsedDeal records.

Pure functions only. No I/O. No Salesforce. No SendGrid. No network.
Trivially unit-testable; see tests/test_parser.py.

Replaces the inline parsing in johnson_buys_deal_scraper.py v1, which
produced ~97% junk addresses on the Apr 28 production sample
(boilerplate not stripped, HTML entities not decoded, comp/sold lines
mistaken for deal addresses, sqft mistaken for price, phone numbers
mistaken for the leading house number).

Design principles:
  - Clean the body text BEFORE running any extraction regex (decode
    entities, strip phone numbers, strip wholesaler boilerplate).
  - Address regex is conservative: leading number must be 2-5 digits,
    must be followed by a space, must end in a recognized street
    suffix within ~5 word tokens. Word boundaries everywhere so phone
    digits cannot start an address match.
  - Address candidates are rejected if they're preceded by
    SOLD/COMP/Sale-price markers — those are comparable-sales lines,
    not the deal address.
  - Price is label-anchored first ($N after Asking|Price|Wholesale|
    List|Cash|Offer), with a bare-$N fallback only if no labeled
    price exists. Anything below $30k is treated as a parser error
    (almost always sqft mis-extracted as price).
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import List, Optional

# ---------------------------------------------------------------------------
# Cleanup pipeline — runs over every body before any extraction regex
# ---------------------------------------------------------------------------

_PHONE_RE = re.compile(
    r"\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}"
)

_JUNK_PHRASES = (
    "* NEW DEAL *", "*NEW DEAL*", "NEW DEAL!!!", "NEW DEAL!!", "NEW DEAL!",
    "NEW DEAL", "***NEW DEAL***", "*** NEW DEAL ***",
    "* * *", "***",
    "Call us:", "Call us at:", "Text us:", "Call Now:",
    "GET INFO HERE", "View Property", "More Info",
)

_CALL_TEXT_RE = re.compile(
    r"\b(Call|Text|Phone|Tel|TEL|Mobile|Cell)\b\s*(?:us\s*)?(?:at\s*)?[:\.]?\s*",
    re.IGNORECASE,
)


def clean_body(text: str) -> str:
    """Decode HTML entities, strip tags, kill phone numbers + boilerplate, normalize whitespace.

    This is the most important function in the parser — every downstream
    regex assumes its input has been through clean_body.
    """
    if not text:
        return ""
    # 1. Strip HTML tags (defensive — scraper does this too)
    text = re.sub(r"<[^>]+>", " ", text)
    # 2. Decode HTML entities — &nbsp; &amp; &#39; etc. CRITICAL FIX.
    text = html.unescape(text)
    # 3. Replace U+00A0 (non-breaking space) with regular space
    text = text.replace(" ", " ")
    # 4. Strip phone numbers BEFORE any address matching — they share
    #    the leading-digits pattern and cause catastrophic false matches
    #    like '900 Call (954) 589-0144 822 33rd Street'.
    text = _PHONE_RE.sub(" ", text)
    # 5. Strip wholesaler boilerplate phrases
    for phrase in _JUNK_PHRASES:
        text = text.replace(phrase, " ")
    # 6. Strip leftover Call/Text/Phone labels
    text = _CALL_TEXT_RE.sub(" ", text)
    # 7. Collapse whitespace (preserve paragraph breaks)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]*\n+", "\n\n", text)
    text = text.strip()
    return text


# ---------------------------------------------------------------------------
# Address extraction
# ---------------------------------------------------------------------------

# Street suffixes we recognize. Conservative — only common ones. Tighter
# than the v1 regex because false positives are far worse than false
# negatives (a dropped deal vs. a buyer email full of garbage).
_STREET_SUFFIX = (
    r"(?:St|St\.|Street|Ave|Ave\.|Avenue|Rd|Rd\.|Road|"
    r"Blvd|Blvd\.|Boulevard|Dr|Dr\.|Drive|Ln|Ln\.|Lane|"
    r"Ct|Ct\.|Court|Ter|Ter\.|Terrace|Pl|Pl\.|Place|"
    r"Way|Hwy|Highway|Pkwy|Parkway|Cir|Cir\.|Circle|"
    r"Trl|Trail|Loop|Sq|Square)"
)

# Address pattern:
#   - WORD BOUNDARY (so phone digits can't lead in)
#   - 2-5 digit house number (rejects single-digit junk like "2 9451 Caribbean")
#   - REQUIRED whitespace
#   - 1-5 token middle. Each token must START with a letter OR digit
#     (allows 'NE', 'San', '161st', '23rd', '164th'). Lowercase OK because
#     real wholesaler emails are inconsistent ('Ne', 'st', etc.).
#   - REQUIRED street suffix at the end
#   - WORD BOUNDARY
# IGNORECASE because wholesaler emails mix cases freely.
# Reserved words that are NEVER part of a real street name. If any of
# these appear as an inner token, the address match is rejected — they
# leak in from sentences like "1500 sqft. 1410 NE 161st St" where v1
# would match "1500 sqft. 1410 NE 161st St" as ONE address.
_RESERVED_NON_ADDRESS_TOKENS = (
    "sqft", "sq.ft", "sq.ft.", "sf",
    "br", "bd", "ba",
    "arv", "rehab", "reno", "asking",
    "price", "wholesale", "comp", "comps",
    "sold", "asking", "cash",
)
_RESERVED_TOKEN_PATTERN = "(?:" + "|".join(re.escape(t) for t in _RESERVED_NON_ADDRESS_TOKENS) + ")"

ADDRESS_RE = re.compile(
    r"\b"                                              # left word boundary
    r"(\d{2,5})"                                        # house number 2-5 digits
    r"\s+"                                              # required space
    r"(?=\S*[A-Za-z])"                                  # next token must contain a letter
                                                        # — rejects "33162 1410 NE 161st St"
                                                        # being matched as one address
                                                        # (33162 is a zip; 1410 is the real number)
    r"("
        r"(?:"
            r"(?!" + _RESERVED_TOKEN_PATTERN + r"\b)"   # token NOT in blacklist
            r"[A-Za-z0-9][A-Za-z0-9'.-]*\s+"            # 1-5 alphanumeric-start tokens
        r"){1,5}"
    r")"
    + _STREET_SUFFIX +
    r"\b",
    re.IGNORECASE,
)

# If an address candidate is preceded (within ~80 chars) by any of these
# markers, we reject it — it's a comparable sale or a sold record, not
# the deal address. This prevents the classic v1 bug:
#   "Asking $420K. COMPS: SOLD $595K 1191 NE 165TH TER" → 1191 was
#   being sent to buyers as the deal address.
_COMP_REJECTION_RE = re.compile(
    r"(?:\b(?:SOLD|COMP|COMPS|RECENT|SETTLED|CLOSED|"
    r"SALE\s*PRICE|SOLD\s*FOR|LAST\s*SOLD|PREVIOUSLY)\b"
    r"[^.\n]{0,40})",
    re.IGNORECASE,
)


def find_addresses(cleaned_text: str) -> List[re.Match]:
    """Return all address matches in cleaned text, with comp-rejection applied.

    The input MUST already have been through clean_body().
    """
    out: List[re.Match] = []
    for m in ADDRESS_RE.finditer(cleaned_text):
        window_before = cleaned_text[max(0, m.start() - 80):m.start()]
        if _COMP_REJECTION_RE.search(window_before):
            continue
        out.append(m)
    return out


# ---------------------------------------------------------------------------
# City / State / Zip
# ---------------------------------------------------------------------------

# City must START with capital letter (not lowercase 'rd'/'st'/etc bleeding
# in from a previous address). State case-insensitive via inline group.
# Post-filter (in parse_block) rejects city values containing street
# suffixes — guards against matches like "Caribbean Blvd Cutler Bay".
CITY_STATE_ZIP_RE = re.compile(
    r"([A-Z][A-Za-z\s.\-]+?),?\s+(?i:FL|Fla|Florida)\s+(\d{5})(?:-\d{4})?",
)

# A "city" value containing any of these tokens is suspect — almost
# certainly the regex captured a piece of the street, not the city.
_CITY_REJECT_RE = re.compile(
    r"\b(?:St|Ave|Rd|Blvd|Dr|Ln|Ct|Ter|Pl|Way|Hwy|Pkwy|Cir|Trl|Loop|"
    r"Street|Avenue|Road|Boulevard|Drive|Lane|Court|Terrace|Place|"
    r"Highway|Parkway|Circle|Trail)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Price extraction (label-anchored first, fallback to bare $)
# ---------------------------------------------------------------------------

PRICE_LABEL_RE = re.compile(
    r"(?:Asking|Price|Wholesale\s*Price|Wholesale|List(?:ed)?(?:\s*Price)?|"
    r"Sale\s*Price|Net\s*to\s*Seller|Cash\s*Price|All-?in|"
    r"Buy\s*it\s*Now|Offer\s*Price|Offer)"
    r"\s*[:#=\-]?\s*\$?\s*([\d,]+(?:\.\d+)?)\s*([KkMm])?",
    re.IGNORECASE,
)

DOLLAR_PRICE_RE = re.compile(
    r"\$\s*([\d,]+(?:\.\d+)?)\s*([KkMm])?"
)

# Anything below this is treated as a parser error (sqft, lot size, etc.)
PRICE_FLOOR = 30_000

ARV_RE = re.compile(
    r"\bARV\b\s*[:#=\-]?\s*\$?\s*([\d,]+(?:\.\d+)?)\s*([KkMm])?",
    re.IGNORECASE,
)

REHAB_RE = re.compile(
    r"\b(?:Rehab(?:\s*Cost)?|Repairs?|Repair\s*Cost|Reno|Renovation)\b"
    r"\s*[:#=\-]?\s*\$?\s*([\d,]+(?:\.\d+)?)\s*([KkMm])?",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Beds / Baths / Sqft
# ---------------------------------------------------------------------------

# Long form: "3 BR" / "3 Beds" / "3 bedroom"
BEDS_RE = re.compile(
    r"\b(\d{1,2}(?:\.5)?)\s*"
    r"(?:BD\b|BR\b|Bed(?:room)?s?|bd|br)\b",
    re.IGNORECASE,
)
BATHS_RE = re.compile(
    r"\b(\d{1,2}(?:\.5)?)\s*"
    r"(?:BA\b|Bath(?:room)?s?|ba)\b",
    re.IGNORECASE,
)

# Shorthand: "3/2", "3-2", "3BD/2BA", "BD: 3"
BB_SHORTHAND_RE = re.compile(
    r"\b(\d{1,2})\s*[/\-]\s*(\d{1,2}(?:\.5)?)"
    r"(?:\s*(?:BD|BR|Bed)s?\s*[/\-]?\s*(?:BA|Bath)s?)?\b"
)

SQFT_RE = re.compile(
    r"\b(\d{3,5}(?:,\d{3})?)\s*"
    r"(?:sq\s*\.?\s*ft\.?|sqft|sf|square\s*feet)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Property type
# ---------------------------------------------------------------------------

PROPERTY_TYPE_HINTS = {
    "SFR":         re.compile(r"\b(single\s*family|sfr|sfh|single-family)\b", re.I),
    "Duplex":      re.compile(r"\bduplex\b", re.I),
    "Triplex":     re.compile(r"\btriplex\b", re.I),
    "Multifamily": re.compile(r"\b(multi[-\s]?family|4-?plex|quad|fourplex)\b", re.I),
    "Land":        re.compile(r"\b(vacant\s*land|buildable\s*lot|raw\s*land)\b", re.I),
    "Condo":       re.compile(r"\bcondo\b", re.I),
    "Townhouse":   re.compile(r"\b(townhouse|townhome)\b", re.I),
}


# ---------------------------------------------------------------------------
# ParsedDeal data class
# ---------------------------------------------------------------------------

@dataclass
class ParsedDeal:
    address: str = ""
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    asking_price: Optional[int] = None
    arv: Optional[int] = None
    rehab_estimate: Optional[int] = None
    beds: Optional[float] = None
    baths: Optional[float] = None
    sqft: Optional[int] = None
    property_type: Optional[str] = None
    parse_warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Safe numeric helpers — never raise ValueError on empty / junk input
# (this is the fix for the int() empty-string crash that wedged 50+
# Microsoft Graph messages per run in v1)
# ---------------------------------------------------------------------------

def safe_int(s: Optional[str]) -> Optional[int]:
    if s is None:
        return None
    s = s.strip().replace(",", "").replace("$", "")
    if not s or not re.search(r"\d", s):
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def safe_float(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    s = s.strip().replace(",", "")
    if not s or not re.search(r"\d", s):
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def normalize_price(raw: str, suffix: Optional[str]) -> Optional[int]:
    """Turn ('250', 'k') -> 250000; ('250,000', None) -> 250000; ('1.2', 'M') -> 1200000."""
    n = safe_float(raw)
    if n is None:
        return None
    if suffix:
        s = suffix.lower()
        if s == "k":
            n *= 1_000
        elif s == "m":
            n *= 1_000_000
    return int(n)


# ---------------------------------------------------------------------------
# Main parsing entry points
# ---------------------------------------------------------------------------

def parse_block(block_text: str) -> ParsedDeal:
    """Parse a single property block (one property's worth of text) → ParsedDeal."""
    cleaned = clean_body(block_text)
    deal = ParsedDeal()

    # Address (use the FIRST valid one in this block)
    addrs = find_addresses(cleaned)
    if addrs:
        m = addrs[0]
        deal.address = " ".join(m.group(0).split())  # collapse internal whitespace
    else:
        deal.parse_warnings.append("no_address")

    # City / State / Zip
    csz = CITY_STATE_ZIP_RE.search(cleaned)
    if csz:
        candidate_city = csz.group(1).strip().rstrip(",")
        # Reject city candidates that contain street suffixes — those are
        # cases where the regex captured part of the address as the city.
        if not _CITY_REJECT_RE.search(candidate_city):
            deal.city = candidate_city
        deal.state = "FL"
        deal.zip_code = csz.group(2)

    # Price — labeled first, then fall back to bare $N
    pm = PRICE_LABEL_RE.search(cleaned)
    if pm:
        deal.asking_price = normalize_price(pm.group(1), pm.group(2))
    else:
        # Skip ARV-tagged dollars when looking for asking price
        # (ARV often appears as $X right after the label)
        # Strip ARV patterns first so DOLLAR_PRICE_RE doesn't catch them
        no_arv = ARV_RE.sub(" ", cleaned)
        no_rehab = REHAB_RE.sub(" ", no_arv)
        pm = DOLLAR_PRICE_RE.search(no_rehab)
        if pm:
            deal.asking_price = normalize_price(pm.group(1), pm.group(2))

    # Sanity floor: anything <$30k is a parser error (sqft, lot size, etc.)
    if deal.asking_price is not None and deal.asking_price < PRICE_FLOOR:
        deal.parse_warnings.append(f"price_below_floor:{deal.asking_price}")
        deal.asking_price = None

    # ARV
    am = ARV_RE.search(cleaned)
    if am:
        deal.arv = normalize_price(am.group(1), am.group(2))

    # Rehab estimate
    rm = REHAB_RE.search(cleaned)
    if rm:
        deal.rehab_estimate = normalize_price(rm.group(1), rm.group(2))

    # Beds + baths — try shorthand "3/2" first, then long-form
    bb = BB_SHORTHAND_RE.search(cleaned)
    if bb:
        deal.beds = safe_float(bb.group(1))
        deal.baths = safe_float(bb.group(2))
    else:
        bm = BEDS_RE.search(cleaned)
        if bm:
            deal.beds = safe_float(bm.group(1))
        bam = BATHS_RE.search(cleaned)
        if bam:
            deal.baths = safe_float(bam.group(1))

    # Sqft
    sm = SQFT_RE.search(cleaned)
    if sm:
        deal.sqft = safe_int(sm.group(1))

    # Property type
    for ptype, pat in PROPERTY_TYPE_HINTS.items():
        if pat.search(cleaned):
            deal.property_type = ptype
            break

    return deal


def split_into_blocks(body: str) -> List[str]:
    """Split a multi-property inventory blast into one block per address.

    Each block runs from one address match to the next. Falls back to
    [body] if zero or one address found (single-property email).
    """
    cleaned = clean_body(body)
    addrs = find_addresses(cleaned)
    if len(addrs) <= 1:
        return [cleaned]
    blocks: List[str] = []
    positions = [m.start() for m in addrs]
    for i, start in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(cleaned)
        blocks.append(cleaned[start:end])
    return blocks


def parse_email_body(body: str) -> List[ParsedDeal]:
    """Parse one wholesaler email body → list of ParsedDeal records.

    Emits zero-or-more deals. A block is kept if it has either:
      - an address, OR
      - both a price AND a zip code (the address might just be partial)
    """
    blocks = split_into_blocks(body)
    deals = [parse_block(b) for b in blocks]
    return [
        d for d in deals
        if d.address or (d.asking_price and d.zip_code)
    ]


# ---------------------------------------------------------------------------
# WhatsApp / Green-API forwarded messages
# ---------------------------------------------------------------------------
#
# Green-API webhooks → Cloudflare Worker → SendGrid → info@cheaphomesFLA.com
#
# The Worker wraps each WA message in an email body that looks like:
#
#     Forwarded from WhatsApp via Green-API
#
#     Sender:     Antonio Pacheco
#     Chat:       Miami Deals (group)
#     Chat ID:    1234567890@g.us
#     Received:   2026-04-28T17:00:00Z
#
#     From: Antonio Pacheco <wa-1234567890@whatsapp>
#
#     --- MESSAGE ---
#     <the actual WA message text the wholesaler sent>
#     --- END MESSAGE ---
#
#     Media URL: https://...   (optional)
#
# Subject is "[WA-Group] {chatName} — {senderName}" or "[WA-DM] {senderName}".
# The From address is always the Worker's FROM_EMAIL
# (whatsapp-deals@cheaphomesfla.com), NOT a wholesaler email — so the
# wholesaler-email allowlist check in scraper.py CAN'T filter on From for
# WA mail. Use the subject/sender prefix detector below instead.

_WA_MESSAGE_BLOCK_RE = re.compile(
    r"---\s*MESSAGE\s*---\s*(.*?)\s*---\s*END MESSAGE\s*---",
    re.IGNORECASE | re.DOTALL,
)

_WA_SUBJECT_PREFIXES = ("[WA-Group]", "[WA-DM]", "[WA-")
_WA_FROM_ADDRESSES = (
    "whatsapp-deals@cheaphomesfla.com",
    "whatsapp-deals@cheaphomesFLA.com",
)


def is_whatsapp_forward(subject: str, from_addr: str) -> bool:
    """Return True if this email is a Green-API/Worker WhatsApp forward."""
    if subject:
        sub = subject.strip()
        for prefix in _WA_SUBJECT_PREFIXES:
            if sub.startswith(prefix):
                return True
    if from_addr:
        addr = from_addr.lower().strip()
        for known in _WA_FROM_ADDRESSES:
            if addr == known.lower():
                return True
    return False


def extract_whatsapp_message(body: str) -> str:
    """Strip the Green-API wrapper from a WA-forwarded email body.

    Returns just the raw message the wholesaler sent on WhatsApp.
    Falls back to the full body if no wrapper found (defensive).
    """
    if not body:
        return ""
    m = _WA_MESSAGE_BLOCK_RE.search(body)
    if m:
        return m.group(1).strip()
    return body


def parse_whatsapp_body(body: str) -> List[ParsedDeal]:
    """Parse a WA-forwarded email body → list of ParsedDeal records.

    Strips the Green-API wrapper first, then runs the same parsing
    pipeline as regular wholesaler emails. WhatsApp messages are usually
    one property per message (no multi-property blasts), so we typically
    get 0 or 1 deal back per call — but split_into_blocks still handles
    the rare multi-deal WA message correctly.
    """
    inner = extract_whatsapp_message(body)
    return parse_email_body(inner)
