#!/usr/bin/env python3
"""
Johnson Buys - Twilio Webhook Server
Receives incoming SMS replies and logs them to Salesforce.
"""

from flask import Flask, request
from simple_salesforce import Salesforce
from datetime import datetime
import logging
import re
import ngrok
import threading

app = Flask(__name__)

# ── CREDENTIALS ──────────────────────────────────────────────────────────────
# ─── Credentials (env vars in cloud, .env file in local dev) ────────────
import os
SF_USERNAME       = os.environ["SF_USERNAME"]
SF_PASSWORD       = os.environ["SF_PASSWORD"]
SF_SECURITY_TOKEN = os.environ["SF_SECURITY_TOKEN"]
SF_INSTANCE_URL   = os.environ.get("SF_INSTANCE_URL",
                                   "https://johnsonshomes2.my.salesforce.com")

# ── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── OPT-OUT KEYWORDS ─────────────────────────────────────────────────────────
OPT_OUT_KEYWORDS = {"stop", "unsubscribe", "remove", "quit", "cancel",
                    "take me off", "dont contact", "do not contact"}


def connect_salesforce():
    return Salesforce(
        username=SF_USERNAME,
        password=SF_PASSWORD,
        security_token=SF_SECURITY_TOKEN,
        domain="johnsonshomes2.my",
    )


def clean_phone(number):
    """Normalize phone to E.164 format for Salesforce lookup."""
    if not number:
        return None
    digits = re.sub(r"\D", "", number)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return digits
    return None


def find_lead_by_phone(sf, phone_digits):
    """Search for a lead matching the incoming phone number."""
    formatted_variants = [
        phone_digits,
        f"({phone_digits[:3]}) {phone_digits[3:6]}-{phone_digits[6:]}",
        f"{phone_digits[:3]}-{phone_digits[3:6]}-{phone_digits[6:]}",
        f"+1{phone_digits}",
        f"1{phone_digits}",
    ]
    for variant in formatted_variants:
        query = f"""
            SELECT Id, FirstName, LastName, Status, Property_Address__c
            FROM Lead
            WHERE (Phone = '{variant}' OR MobilePhone = '{variant}')
            AND IsConverted = false
            LIMIT 1
        """
        result = sf.query(query)
        if result["records"]:
            return result["records"][0]
    return None


def is_opt_out(message):
    """Check if the reply is an opt-out request."""
    lower = message.lower().strip()
    return any(keyword in lower for keyword in OPT_OUT_KEYWORDS)


def log_reply_to_salesforce(sf, lead_id, lead_name, message, opt_out=False):
    """Log the incoming reply as a Task with the reply visible in the subject line."""
    try:
        prefix = "OPT-OUT" if opt_out else "SMS Reply"
        # Put the actual message in the Subject so it's visible without clicking
        subject = f"{prefix}: {message[:80]}"
        sf.Task.create({
            "WhoId": lead_id,
            "Subject": subject,
            "Description": f"Full reply from {lead_name}: {message}",
            "Status": "Completed",
            "ActivityDate": datetime.today().strftime("%Y-%m-%d"),
        })
        log.info(f"Task created for {lead_name}: {subject}")
    except Exception as e:
        log.warning(f"Could not create task for {lead_name}: {e}")


def update_lead_status(sf, lead_id, status, lead=None):
    """Update the lead's status in Salesforce."""
    try:
        update_data = {"Status": status}
        if lead and lead.get("Property_Address__c"):
            update_data["Property_Address__c"] = lead["Property_Address__c"]
        sf.Lead.update(lead_id, update_data)
        log.info(f"Updated lead {lead_id} status to '{status}'.")
    except Exception as e:
        log.warning(f"Could not update lead status: {e}. Reply was still logged.")


@app.route("/webhook", methods=["POST"])
def webhook():
    from_number = request.form.get("From", "")
    body = request.form.get("Body", "").strip()

    log.info(f"Incoming SMS from {from_number}: {body}")

    phone_digits = clean_phone(from_number)
    if not phone_digits:
        log.warning("Could not parse phone number. Skipping.")
        return "", 200

    try:
        sf = connect_salesforce()
        lead = find_lead_by_phone(sf, phone_digits)

        if not lead:
            log.warning(f"No lead found for {from_number}. Skipping.")
            return "", 200

        lead_id = lead["Id"]
        lead_name = f"{lead.get('FirstName', '')} {lead.get('LastName', '')}".strip()
        opt_out = is_opt_out(body)

        log_reply_to_salesforce(sf, lead_id, lead_name, body, opt_out=opt_out)

        if opt_out:
            update_lead_status(sf, lead_id, "Take Me Off The List", lead=lead)
            log.info(f"{lead_name} opted out — status updated.")
        else:
            update_lead_status(sf, lead_id, "Working", lead=lead)
            log.info(f"{lead_name} replied — status updated to Working.")

    except Exception as e:
        log.error(f"Error processing reply: {e}")

    return "", 200


if __name__ == "__main__":
    import ngrok
    listener = ngrok.connect(5001, authtoken="3Bi31ffQCLNEai4d6ddEUmlvQri_4ost5LuMXF32s2vrZ9XDX")
    public_url = listener.url()
    log.info(f"")
    log.info(f"╔══════════════════════════════════════════════════════════════╗")
    log.info(f"  ✅ Webhook is LIVE!")
    log.info(f"  📲 Set this URL in Twilio:")
    log.info(f"  {public_url}/webhook")
    log.info(f"╚══════════════════════════════════════════════════════════════╝")
    log.info(f"")
    app.run(host="0.0.0.0", port=5001)
