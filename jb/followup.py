#!/usr/bin/env python3
"""
Johnson Buys - Salesforce + Twilio Automated Follow-Up Script
Sends SMS follow-ups to leads based on their Salesforce status.
"""

import argparse
import logging
import re
from datetime import datetime
from simple_salesforce import Salesforce
from twilio.rest import Client

# ── BATCH SIZE ────────────────────────────────────────────────────────────────
BATCH_SIZE = 200  # Number of leads to text per run

# ── CREDENTIALS ──────────────────────────────────────────────────────────────
# ─── Credentials (env vars in cloud, .env file in local dev) ────────────
import os
SF_USERNAME       = os.environ["SF_USERNAME"]
SF_PASSWORD       = os.environ["SF_PASSWORD"]
SF_SECURITY_TOKEN = os.environ["SF_SECURITY_TOKEN"]
SF_CONSUMER_KEY   = os.environ.get("SF_CONSUMER_KEY",    "")
SF_CONSUMER_SECRET= os.environ.get("SF_CONSUMER_SECRET", "")
SF_INSTANCE_URL   = os.environ.get("SF_INSTANCE_URL",
                                   "https://johnsonshomes2.my.salesforce.com")

TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN  = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "+17866488624")

# ── MESSAGE TEMPLATE ─────────────────────────────────────────────────────────
FOLLOW_UP_MESSAGE = (
    "This is Chris, we spoke recently about your property located at {address} - "
    "I am able to close in as little as 7 days - No repairs, No agent fee, No Hassle. "
    "I even pay your closing costs! If your interested in a No Obligation Cash Offer. "
    "Reply Yes and I will email you an offer today!"
)

# Statuses that trigger a follow-up text
STATUS_MAP = {
    "New",
    "In Progress",
    "In Progress Priority",
    "Nurturing",
    "Re-Attempt",
    "No Response",
    "Sent Contract",
}

# ── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def connect_salesforce():
    log.info("Connecting to Salesforce...")
    sf = Salesforce(
        username=SF_USERNAME,
        password=SF_PASSWORD,
        security_token=SF_SECURITY_TOKEN,
        domain="johnsonshomes2.my",
    )
    log.info("Connected to Salesforce.")
    return sf


def get_leads(sf):
    statuses = "', '".join(STATUS_MAP)
    query = f"""
        SELECT Id, FirstName, LastName, Phone, MobilePhone, Status,
               Street, City, State
        FROM Lead
        WHERE Status IN ('{statuses}')
        AND IsConverted = false
        AND (Phone != null OR MobilePhone != null)
    """
    result = sf.query_all(query)
    leads = result.get("records", [])
    log.info(f"Found {len(leads)} leads to process.")
    return leads


def clean_phone(number):
    """Strip all non-digit characters and format as E.164 (+1XXXXXXXXXX)."""
    if not number:
        return None
    digits = re.sub(r"\D", "", number)
    if len(digits) == 10:
        return f"+1{digits}"
    elif len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return None  # Invalid number — skip it


def get_phone(lead):
    raw = lead.get("MobilePhone") or lead.get("Phone")
    return clean_phone(raw)


def build_message(lead):
    status = lead.get("Status", "")
    if status not in STATUS_MAP:
        return None
    first_name = lead.get("FirstName") or "there"
    street = lead.get("Street") or ""
    city   = lead.get("City") or ""
    state  = lead.get("State") or ""
    address_parts = [p for p in [street, city, state] if p]
    address = ", ".join(address_parts) if address_parts else "your property"
    return FOLLOW_UP_MESSAGE.format(name=first_name, address=address)


def send_sms(twilio_client, to_number, message, test_mode=False):
    if test_mode:
        log.info(f"[TEST MODE] Would send to {to_number}:\n  {message}")
        return "TEST-SID"
    msg = twilio_client.messages.create(
        body=message,
        from_=TWILIO_FROM_NUMBER,
        to=to_number,
    )
    return msg.sid


def already_texted(sf, lead_id):
    """Returns True if this lead already received an automated SMS."""
    result = sf.query(
        f"SELECT Id FROM Task WHERE WhoId = '{lead_id}' "
        f"AND Subject = 'Automated SMS sent by Johnson Buys script' LIMIT 1"
    )
    return result["totalSize"] > 0


def log_activity_to_salesforce(sf, lead_id, message, test_mode=False):
    if test_mode:
        log.info(f"[TEST MODE] Would log activity on Lead {lead_id}")
        return
    sf.Task.create({
        "WhoId": lead_id,
        "Subject": "Automated SMS sent by Johnson Buys script",
        "Description": message,
        "Status": "Completed",
        "ActivityDate": datetime.today().strftime("%Y-%m-%d"),
    })


def run(test_mode=False):
    mode_label = "TEST MODE" if test_mode else "LIVE MODE"
    log.info(f"Starting Johnson Buys follow-up script — {mode_label}")

    sf = connect_salesforce()
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

    all_leads = get_leads(sf)
    leads = all_leads[:BATCH_SIZE]
    log.info(f"Processing batch of {len(leads)} leads (out of {len(all_leads)} total).")
    sent = 0
    skipped = 0
    already_sent = 0

    for lead in leads:
        name = f"{lead.get('FirstName', '')} {lead.get('LastName', '')}".strip()
        phone = get_phone(lead)
        message = build_message(lead)

        if not phone:
            log.warning(f"Skipping {name} — no phone number.")
            skipped += 1
            continue

        if not message:
            log.warning(f"Skipping {name} — no message template for status '{lead.get('Status')}'.")
            skipped += 1
            continue

        if already_texted(sf, lead["Id"]):
            log.info(f"Skipping {name} — already texted.")
            already_sent += 1
            continue

        log.info(f"Processing: {name} | Status: {lead.get('Status')} | Phone: {phone}")
        sid = send_sms(twilio_client, phone, message, test_mode=test_mode)
        log_activity_to_salesforce(sf, lead["Id"], message, test_mode=test_mode)
        log.info(f"  ✓ Sent (SID: {sid})")
        sent += 1

    log.info(f"\nDone. Sent: {sent} | Already texted (skipped): {already_sent} | Other skipped: {skipped} | Total leads: {len(all_leads)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Johnson Buys Salesforce Follow-Up Script")
    parser.add_argument("--test", action="store_true", help="Test mode — no texts sent.")
    args = parser.parse_args()
    run(test_mode=args.test)