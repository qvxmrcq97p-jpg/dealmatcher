#!/usr/bin/env python3
"""
Johnson Buys — 4-Touch Email Drip Campaign
Runs daily. Sends each lead exactly one email per touch, spaced out:
  Day  1 — Initial outreach
  Day  7 — First follow-up
  Day 21 — Second follow-up
  Day 45 — Final touch

Tracks sends via Salesforce Tasks so it never double-sends.
Uses curl for all network calls (avoids macOS Python socket issues).

OPTIMIZED: Pre-loads all sent Task records in bulk (1 query) instead of
           querying Salesforce individually per lead (was 16,000+ calls).
"""

import datetime, subprocess, json, re, sys, time, urllib.parse

# ─── Sunday Skip ──────────────────────────────────────────────────────────────
if datetime.date.today().weekday() == 6:  # 6 = Sunday
    print(f"[{datetime.date.today()}] Sunday — skipping email campaign. Runs Mon–Sat.")
    sys.exit(0)


# ─── Credentials ──────────────────────────────────────────────────────────────
# ─── Credentials (env vars in cloud, .env file in local dev) ────────────
import os
SF_USERNAME       = os.environ["SF_USERNAME"]
SF_PASSWORD       = os.environ["SF_PASSWORD"]
SF_SECURITY_TOKEN = os.environ["SF_SECURITY_TOKEN"]
SF_DOMAIN         = os.environ.get("SF_DOMAIN", "johnsonshomes2.my")

EMAIL_ADDRESS    = os.environ.get("EMAIL_ADDRESS", "info@johnsonbuys.com")
SENDGRID_API_KEY = os.environ["SENDGRID_API_KEY"]

BATCH_SIZE  = 500   # total emails per day across all touches
FROM_NAME   = "Chris Johnson"
PHONE       = "(305) 575-9040"
WEBSITE     = "johnsonbuys.com"

# Task subject tags — used to detect which touches have already been sent
TAGS = {
    1:  "JB-Day1-Sent",
    7:  "JB-Day7-Sent",
    21: "JB-Day21-Sent",
    45: "JB-Day45-Sent",
}

# ─── Salesforce via curl ───────────────────────────────────────────────────────
def sf_login():
    soap = f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:urn="urn:partner.soap.sforce.com">
  <soapenv:Body>
    <urn:login>
      <urn:username>{SF_USERNAME}</urn:username>
      <urn:password>{SF_PASSWORD}{SF_SECURITY_TOKEN}</urn:password>
    </urn:login>
  </soapenv:Body>
</soapenv:Envelope>"""
    r = subprocess.run(
        ["curl", "-s", "-m", "30", "-X", "POST",
         f"https://{SF_DOMAIN}.salesforce.com/services/Soap/u/58.0",
         "-H", "Content-Type: text/xml", "-H", "SOAPAction: login", "-d", soap],
        capture_output=True, text=True, timeout=35
    )
    session = re.search(r"<sessionId>(.+?)</sessionId>", r.stdout)
    server  = re.search(r"<serverUrl>(.+?)</serverUrl>", r.stdout)
    if not session:
        print("❌ Salesforce login failed:", r.stdout[:300])
        sys.exit(1)
    session_id  = session.group(1)
    sf_instance = re.search(r"(https://[^/]+)", server.group(1)).group(1)
    return session_id, sf_instance

def sf_query(session_id, sf_instance, soql, all_records=False):
    url = f"{sf_instance}/services/data/v58.0/query?q={urllib.parse.quote(soql)}"
    records = []
    while url:
        r = subprocess.run(
            ["curl", "-s", "-m", "60", url,
             "-H", f"Authorization: Bearer {session_id}"],
            capture_output=True, text=True, timeout=65
        )
        try:
            data = json.loads(r.stdout)
        except Exception:
            print(f"❌ SF query parse error: {r.stdout[:200]}")
            return []
        if isinstance(data, list):
            print(f"❌ SF query error: {data[0].get('message','?')}")
            return []
        records.extend(data.get("records", []))
        if not all_records or data.get("done", True):
            break
        next_url = data.get("nextRecordsUrl")
        url = f"{sf_instance}{next_url}" if next_url else None
    return records

def sf_post(session_id, sf_instance, path, body):
    url = f"{sf_instance}/services/data/v58.0/{path}"
    r = subprocess.run(
        ["curl", "-s", "-m", "30", "-X", "POST", url,
         "-H", f"Authorization: Bearer {session_id}",
         "-H", "Content-Type: application/json",
         "-d", json.dumps(body)],
        capture_output=True, text=True, timeout=35
    )
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"error": r.stdout[:200]}

def sf_get_listview_leads(session_id, sf_instance, listview_dev_name, fields):
    """Fetch leads from a Salesforce List View by developer name."""
    # Get the ListView Id
    lv_records = sf_query(session_id, sf_instance,
        f"SELECT Id FROM ListView WHERE SobjectType = 'Lead' AND DeveloperName = '{listview_dev_name}'",
        all_records=False)
    if not lv_records:
        alt_name = listview_dev_name.lstrip('X')
        lv_records = sf_query(session_id, sf_instance,
            f"SELECT Id FROM ListView WHERE SobjectType = 'Lead' AND DeveloperName = '{alt_name}'",
            all_records=False)
    if not lv_records:
        print(f"  ❌ List view '{listview_dev_name}' not found.")
        return []

    lv_id = lv_records[0]["Id"]

    # Use list view results endpoint to get lead IDs
    url = f"{sf_instance}/services/data/v58.0/sobjects/Lead/listviews/{lv_id}/results"
    r = subprocess.run(
        ["curl", "-s", "-m", "60", url,
         "-H", f"Authorization: Bearer {session_id}"],
        capture_output=True, text=True, timeout=65)
    try:
        data = json.loads(r.stdout)
    except Exception:
        print(f"  ❌ List view results parse error")
        return []

    lead_ids = []
    for rec in data.get("records", []):
        for col in rec.get("columns", []):
            val = col.get("value")
            if val and isinstance(val, str) and val.startswith("00Q"):
                lead_ids.append(val)
                break

    if not lead_ids:
        return []

    # Fetch full lead records
    all_leads = []
    field_str = ", ".join(fields)
    for i in range(0, len(lead_ids), 200):
        batch = lead_ids[i:i+200]
        id_list = "','".join(batch)
        leads = sf_query(session_id, sf_instance,
            f"SELECT {field_str} FROM Lead WHERE Id IN ('{id_list}')",
            all_records=False)
        all_leads.extend(leads)
    return all_leads

def bulk_load_sent_tags(session_id, sf_instance):
    """
    Pre-loads ALL JB drip task records in one (or a few paged) query.
    Returns dict: { lead_id -> { tag_string -> date_sent (datetime.date) } }
    This replaces per-lead already_sent() queries — reducing 16k API calls to ~1.
    """
    print("Pre-loading sent-tag history from Salesforce...")
    records = sf_query(
        session_id, sf_instance,
        "SELECT WhoId, Subject, ActivityDate FROM Task WHERE Subject LIKE 'JB-%' ORDER BY CreatedDate DESC",
        all_records=True
    )
    sent = {}
    all_tag_values = set(TAGS.values())
    for r in records:
        who  = r.get("WhoId")
        subj = r.get("Subject", "") or ""
        date_str = r.get("ActivityDate") or ""
        if not who:
            continue
        if who not in sent:
            sent[who] = {}
        for tag in all_tag_values:
            if tag in subj and tag not in sent[who]:
                try:
                    sent_date = datetime.date.fromisoformat(date_str)
                except Exception:
                    sent_date = datetime.date.today()
                sent[who][tag] = sent_date
    print(f"✓ Loaded history for {len(sent)} leads ({len(records)} task records)\n")
    return sent

def log_task(session_id, sf_instance, lead_id, first, last, email, day):
    sf_post(session_id, sf_instance, "sobjects/Task", {
        "WhoId":        lead_id,
        "Subject":      f"{TAGS[day]}: {first} {last}",
        "Status":       "Completed",
        "ActivityDate": str(datetime.date.today()),
        "Description":  f"Day {day} email sent to {email} — Johnson Buys drip campaign.",
    })

# ─── Email templates ───────────────────────────────────────────────────────────
HEADER = """
<table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f0f2f5; padding: 30px 0;">
  <tr><td align="center">
  <table width="600" cellpadding="0" cellspacing="0"
    style="background-color:#ffffff; border-radius:8px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,0.08);">
    <tr>
      <td style="background-color:#1a3c6e; padding:28px 40px; text-align:center;">
        <div style="color:#fff; font-size:26px; font-weight:bold; letter-spacing:1px;">JOHNSON BUYS</div>
        <div style="color:#a8c4e8; font-size:13px; margin-top:4px; letter-spacing:2px;">MIAMI'S TRUSTED CASH HOME BUYER</div>
      </td>
    </tr>"""

FOOTER = f"""
    <tr>
      <td style="padding:24px 40px 32px 40px;">
        <table cellpadding="0" cellspacing="0">
          <tr>
            <td style="padding-right:20px; border-right:3px solid #1a3c6e;">
              <div style="font-size:17px; font-weight:bold; color:#1a3c6e;">Chris Johnson</div>
              <div style="font-size:13px; color:#666; margin-top:2px;">Founder, Johnson Buys</div>
            </td>
            <td style="padding-left:20px;">
              <div style="font-size:13px; color:#555; line-height:1.8;">
                📱 {PHONE}<br>
                📧 {EMAIL_ADDRESS}<br>
                🌐 {WEBSITE}<br>📍 Miami, FL
              </div>
            </td>
          </tr>
        </table>
      </td>
    </tr>
    <tr>
      <td style="background-color:#f8f9fb; padding:16px 40px; border-top:1px solid #e8e8e8;">
        <p style="font-size:11px; color:#aaa; margin:0; line-height:1.6;">
          You received this email because your property was included in a recent outreach list.
          To be removed, simply reply with "Remove" and we'll take care of it immediately.
        </p>
      </td>
    </tr>
  </table></td></tr>
</table>"""

DYK_FACTS = {
    1:  ("Many of our sellers stay in the home for <strong>30 or even 60 days</strong> "
         "after they receive money from closing — completely rent-free. "
         "You get paid and keep living there on your timeline."),
    7:  ("We buy homes with tenants who <strong>aren't paying rent</strong>. "
         "You don't have to deal with evictions or wait them out — "
         "we take the property as-is, tenants and all."),
    21: ("We can close in as little as <strong>7 days</strong> — or give you up to "
         "<strong>6 months</strong> if you need more time to move. "
         "The timeline is entirely yours to choose."),
    45: ("We've helped sellers <strong>stop foreclosure</strong> by closing before "
         "the auction date. If you're behind on payments, we may be able to help "
         "you walk away with cash instead of losing everything."),
}

def did_you_know(day):
    fact = DYK_FACTS[day]
    return f"""
    <tr>
      <td style="padding:20px 40px;">
        <div style="background:#fff8e6; border-left:4px solid #e6a817;
                    border-radius:4px; padding:16px 20px;">
          <div style="font-size:14px; color:#7a5c00; line-height:1.8;">
            <strong>💡 Did you know?</strong> {fact}
          </div>
        </div>
      </td>
    </tr>"""

def cta_button(label="📱 Text or Call (305) 575-9040"):
    return f"""
    <tr>
      <td style="padding:24px 40px; text-align:center;">
        <a href="sms:+13055759040"
           style="display:inline-block; background-color:#1a3c6e; color:#fff;
                  text-decoration:none; padding:14px 36px; border-radius:6px;
                  font-size:16px; font-weight:bold;">{label}</a>
        <p style="font-size:14px; color:#888; margin-top:14px;">
          Or just reply to this email — I read every response personally.
        </p>
      </td>
    </tr>"""

def divider():
    return '<tr><td style="padding:0 40px;"><hr style="border:none; border-top:1px solid #e8e8e8;"></td></tr>'


def build_day1(first, address):
    subject = f"Cash Offer for Your Home at {address}"
    body = HEADER + f"""
    <tr>
      <td style="padding:36px 40px 20px 40px;">
        <p style="font-size:16px; color:#222; margin:0 0 16px 0;">Hi {first},</p>
        <p style="font-size:15px; color:#444; line-height:1.7; margin:0 0 16px 0;">
          My name is <strong>Chris Johnson</strong> — I'm a local cash home buyer here in Miami,
          and I wanted to personally reach out about your property at:
        </p>
        <div style="background:#f0f2f5; border-left:4px solid #1a3c6e; padding:12px 20px;
                    border-radius:4px; margin-bottom:20px;">
          <span style="font-size:15px; font-weight:bold; color:#1a3c6e;">📍 {address}</span>
        </div>
        <p style="font-size:15px; color:#444; line-height:1.7; margin:0;">
          If selling has ever crossed your mind, I'd love to make it as <strong>simple and
          stress-free as possible</strong>. No repairs. No agent fees. Close in as little as 7 days.
        </p>
      </td>
    </tr>
    {divider()}
    <tr>
      <td style="padding:24px 40px;">
        <div style="font-size:13px; font-weight:bold; color:#1a3c6e; letter-spacing:1.5px;
                    text-transform:uppercase; margin-bottom:20px;">Why Sellers Choose Johnson Buys</div>
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:14px;">
          <tr>
            <td width="48" valign="top" style="padding-top:2px;">
              <div style="background:#1a3c6e; color:#fff; width:36px; height:36px; border-radius:50%;
                          text-align:center; line-height:36px; font-size:17px;">💵</div>
            </td>
            <td style="padding-left:14px;">
              <div style="font-size:15px; font-weight:bold; color:#222;">Cash — No Bank Needed</div>
              <div style="font-size:14px; color:#666; margin-top:2px; line-height:1.6;">
                No lenders, no loan approvals, no risk of financing falling through at the last minute.</div>
            </td>
          </tr>
        </table>
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:14px;">
          <tr>
            <td width="48" valign="top" style="padding-top:2px;">
              <div style="background:#1a3c6e; color:#fff; width:36px; height:36px; border-radius:50%;
                          text-align:center; line-height:36px; font-size:17px;">⚡</div>
            </td>
            <td style="padding-left:14px;">
              <div style="font-size:15px; font-weight:bold; color:#222;">Close in as Little as 7 Days</div>
              <div style="font-size:14px; color:#666; margin-top:2px; line-height:1.6;">
                We work around your schedule — not ours.</div>
            </td>
          </tr>
        </table>
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:14px;">
          <tr>
            <td width="48" valign="top" style="padding-top:2px;">
              <div style="background:#1a3c6e; color:#fff; width:36px; height:36px; border-radius:50%;
                          text-align:center; line-height:36px; font-size:17px;">🔨</div>
            </td>
            <td style="padding-left:14px;">
              <div style="font-size:15px; font-weight:bold; color:#222;">We Buy As-Is</div>
              <div style="font-size:14px; color:#666; margin-top:2px; line-height:1.6;">
                No cleaning, no repairs, no open houses. We buy the home exactly as it sits.</div>
            </td>
          </tr>
        </table>
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td width="48" valign="top" style="padding-top:2px;">
              <div style="background:#1a3c6e; color:#fff; width:36px; height:36px; border-radius:50%;
                          text-align:center; line-height:36px; font-size:17px;">🚫</div>
            </td>
            <td style="padding-left:14px;">
              <div style="font-size:15px; font-weight:bold; color:#222;">No Commissions or Closing Costs</div>
              <div style="font-size:14px; color:#666; margin-top:2px; line-height:1.6;">
                The offer we make is what you walk away with. No surprises.</div>
            </td>
          </tr>
        </table>
      </td>
    </tr>
    {divider()}
    {did_you_know(1)}
    {divider()}
    {cta_button()}
    {divider()}
    """ + FOOTER
    return subject, body


def build_day7(first, address):
    subject = f"Quick Follow-Up — {address}"
    body = HEADER + f"""
    <tr>
      <td style="padding:36px 40px 28px 40px;">
        <p style="font-size:16px; color:#222; margin:0 0 16px 0;">Hi {first},</p>
        <p style="font-size:15px; color:#444; line-height:1.7; margin:0 0 16px 0;">
          I reached out last week about your property at <strong>{address}</strong> and
          just wanted to make sure my email didn't get buried.
        </p>
        <p style="font-size:15px; color:#444; line-height:1.7; margin:0 0 16px 0;">
          I'm still very interested in making you a <strong>no-obligation cash offer</strong>.
          There's no pressure and no commitment — just a straightforward number so you know
          what your options are.
        </p>
        <p style="font-size:15px; color:#444; line-height:1.7; margin:0;">
          If now isn't the right time, that's completely fine — just let me know and
          I'll follow up when it's more convenient for you.
        </p>
      </td>
    </tr>
    {divider()}
    <tr>
      <td style="padding:20px 40px;">
        <div style="background:#f0f6ff; border-radius:8px; padding:20px 24px;">
          <div style="font-size:15px; font-weight:bold; color:#1a3c6e; margin-bottom:10px;">
            A quick reminder of what we offer:
          </div>
          <div style="font-size:14px; color:#444; line-height:2.0;">
            ✅ &nbsp;Cash purchase — no financing contingencies<br>
            ✅ &nbsp;Close in 7–14 days or on your timeline<br>
            ✅ &nbsp;Buy as-is — zero repairs or prep work<br>
            ✅ &nbsp;No agent fees, no closing costs to you<br>
            ✅ &nbsp;Zero obligation to accept
          </div>
        </div>
      </td>
    </tr>
    {divider()}
    {did_you_know(7)}
    {divider()}
    {cta_button("📱 Reply or Call (305) 575-9040")}
    {divider()}
    """ + FOOTER
    return subject, body


def build_day21(first, address):
    subject = f"Still interested in an offer on {address}?"
    body = HEADER + f"""
    <tr>
      <td style="padding:36px 40px 28px 40px;">
        <p style="font-size:16px; color:#222; margin:0 0 16px 0;">Hi {first},</p>
        <p style="font-size:15px; color:#444; line-height:1.7; margin:0 0 16px 0;">
          I've reached out a couple of times about your property at <strong>{address}</strong>.
          I completely understand if the timing hasn't been right.
        </p>
        <p style="font-size:15px; color:#444; line-height:1.7; margin:0 0 16px 0;">
          I work with a lot of sellers who weren't ready to sell at first — and then something
          changed. Whether it's a life event, carrying costs adding up, or just being done with
          the property, I'm here when the time is right.
        </p>
        <p style="font-size:15px; color:#444; line-height:1.7; margin:0;">
          A quick 5-minute call is all it takes to get a number in your hands.
          <strong>No commitment, no pressure, no obligation.</strong>
        </p>
      </td>
    </tr>
    {divider()}
    {did_you_know(21)}
    {divider()}
    {cta_button("📞 Let's Talk — (305) 575-9040")}
    {divider()}
    """ + FOOTER
    return subject, body


def build_day45(first, address):
    subject = f"Closing out my file on {address}"
    body = HEADER + f"""
    <tr>
      <td style="padding:36px 40px 28px 40px;">
        <p style="font-size:16px; color:#222; margin:0 0 16px 0;">Hi {first},</p>
        <p style="font-size:15px; color:#444; line-height:1.7; margin:0 0 16px 0;">
          I've been following up about <strong>{address}</strong> for the past several weeks,
          and I don't want to keep filling your inbox if it's not helpful. So this will be
          my last note.
        </p>
        <p style="font-size:15px; color:#444; line-height:1.7; margin:0 0 16px 0;">
          If you've ever considered selling — even just to know what you could get —
          I'm still very interested. A cash offer from me costs you nothing and takes
          less than a day to put together.
        </p>
        <p style="font-size:15px; color:#444; line-height:1.7; margin:0;">
          If the time ever comes, I hope you'll think of Johnson Buys first. Wishing
          you all the best, {first}.
        </p>
      </td>
    </tr>
    {divider()}
    <tr>
      <td style="padding:16px 40px 8px 40px; text-align:center;">
        <p style="font-size:15px; color:#444;">
          <strong>One last chance to get your no-obligation cash offer:</strong>
        </p>
      </td>
    </tr>
    {did_you_know(45)}
    {divider()}
    {cta_button("📱 Get My Cash Offer — (305) 575-9040")}
    {divider()}
    """ + FOOTER
    return subject, body


BUILDERS = {1: build_day1, 7: build_day7, 21: build_day21, 45: build_day45}


def send_via_sendgrid(to_address, first, address, day):
    subject, html = BUILDERS[day](first, address)
    payload = {
        "personalizations": [{"to": [{"email": to_address}]}],
        "from": {"email": EMAIL_ADDRESS, "name": FROM_NAME},
        "subject": subject,
        "content": [{"type": "text/html", "value": html}],
        "tracking_settings": {
            "click_tracking":  {"enable": True},
            "open_tracking":   {"enable": True},
        }
    }
    result = subprocess.run([
        "curl", "-s", "-m", "30", "-X", "POST",
        "https://api.sendgrid.com/v3/mail/send",
        "-H", f"Authorization: Bearer {SENDGRID_API_KEY}",
        "-H", "Content-Type: application/json",
        "-d", json.dumps(payload)
    ], capture_output=True, text=True, timeout=35)
    # SendGrid returns 202 on success with empty body
    if result.returncode != 0:
        raise RuntimeError(f"curl error: {result.stderr[:200]}")
    if result.stdout.strip():
        try:
            resp = json.loads(result.stdout)
            if resp.get("errors"):
                raise RuntimeError(f"SendGrid error: {resp['errors']}")
        except json.JSONDecodeError:
            pass  # non-JSON response is fine (202 has empty body)
    return True


# ─── Main ──────────────────────────────────────────────────────────────────────
def main():
    today = datetime.date.today()
    print(f"Johnson Buys — 4-Touch Email Campaign  ({today})")
    print("=" * 55)

    print("Connecting to Salesforce...")
    session_id, sf_instance = sf_login()
    print(f"✓ Salesforce: {sf_instance}\n")

    # ── Step 1: Pre-load ALL sent-tag history in one bulk query ──────────────
    # This replaces per-lead already_sent() queries — was 16,000+ API calls!
    sent_tags = bulk_load_sent_tags(session_id, sf_instance)

    # ── Step 2: Pull all emailable leads (newest first) ──────────────────────
    EXCLUDED = (
        # Current clean statuses — never email these
        "'Not Interested','Take me off the list','Dead','Closed','Under Contract',"
        # Legacy statuses still in system until migration runs
        "'Wrong Number','Doesn\\'t own anymore','Unqualified','Purchased',"
        "'Referred to Real Estate Agent','Not Realistic','Listed','Sent Contract'"
    )
    print("Pulling emailable leads from Salesforce...")
    all_leads = sf_query(
        session_id, sf_instance,
        f"SELECT Id, FirstName, LastName, Email, Property_Address__c, Street, City, State "
        f"FROM Lead WHERE Email != null AND Status NOT IN ({EXCLUDED}) "
        f"ORDER BY CreatedDate DESC",
        all_records=True
    )
    print(f"✓ Total emailable leads: {len(all_leads)}\n")
    print("✓ Using SendGrid API for delivery\n")

    sent = skipped = failed = 0
    budget = BATCH_SIZE

    def address_for(lead):
        pa = lead.get("Property_Address__c") or ""
        if pa.strip():
            return pa.strip()
        parts = [lead.get("Street") or "", lead.get("City") or "",
                 lead.get("State") or ""]
        addr  = ", ".join(p for p in parts if p)
        return addr or "your property"

    # Minimum days between touches
    MIN_GAP = {1: 0, 7: 7, 21: 21, 45: 45}

    # ── Step 3: Process touches — Day 45 → 21 → 7 → 1 ───────────────────────
    for day in [45, 21, 7, 1]:
        if budget <= 0:
            break
        tag      = TAGS[day]
        prev_day = {45: 21, 21: 7, 7: 1, 1: None}[day]
        prev_tag = TAGS.get(prev_day) if prev_day else None

        print(f"─── Day {day} Touch (tag: {tag}) ───")
        day_sent = 0

        for lead in all_leads:
            if budget <= 0:
                break
            lid   = lead["Id"]
            first = (lead.get("FirstName") or "there").strip() or "there"
            last  = (lead.get("LastName")  or "").strip()
            email = lead["Email"]

            lead_history = sent_tags.get(lid, {})

            # Skip if this touch already sent
            if tag in lead_history:
                skipped += 1
                continue

            # Day 7+: must have received the previous touch, AND enough days must have passed
            if prev_tag:
                if prev_tag not in lead_history:
                    continue  # hasn't received prior touch yet
                days_since_prev = (today - lead_history[prev_tag]).days
                if days_since_prev < MIN_GAP[day]:
                    continue  # too soon — wait until the right day

            addr = address_for(lead)
            # Always count this attempt against the budget (prevents hammering
            # all 8k leads when SendGrid is erroring — budget = attempts, not just successes)
            budget -= 1
            try:
                send_via_sendgrid(email, first, addr, day)
                log_task(session_id, sf_instance, lid, first, last, email, day)
                # Update in-memory cache so subsequent loops see this send
                sent_tags.setdefault(lid, {})[tag] = today
                print(f"  ✓ Day {day} → {first} {last} <{email}>")
                sent    += 1
                day_sent += 1
                time.sleep(0.3)   # gentle pacing
            except Exception as e:
                print(f"  ✗ Failed: {first} {last} ({email}) — {e}")
                failed += 1

        print(f"  Sent {day_sent} Day-{day} emails.\n")

    print("=" * 55)
    print(f"✅ Campaign run complete for {today}")
    print(f"   Sent:    {sent}")
    print(f"   Skipped: {skipped}  (already received that touch)")
    print(f"   Failed:  {failed}")
    print(f"   Budget remaining: {budget}/{BATCH_SIZE}")

    # ── Step 4: Zip Code Email Campaigns (33127 & 33142) ────────────────────
    # 6 touches over 14 days — mirrors the SMS drip schedule
    # Separate tags and budget so they don't conflict with the main campaign
    ZIP_EMAIL_CAMPAIGNS = [
        {"zip": "33127", "tag_prefix": "JB-ZIP-33127-Email", "budget": 50, "listview_name": "X33127_Duplex_B4"},
        {"zip": "33142", "tag_prefix": "JB-ZIP-33142-Email", "budget": 50, "listview_name": "X33142_Duplex_B4"},
    ]

    ZIP_EMAIL_SCHEDULE = [
        (1,  0,  "Day1"),   # Day 0: initial email
        (2,  2,  "Day2"),   # Day 2: first follow-up
        (3,  5,  "Day5"),   # Day 5
        (4,  8,  "Day8"),   # Day 8
        (5, 11, "Day11"),   # Day 11
        (6, 14, "Day14"),   # Day 14: final
    ]

    ZIP_EMAIL_SUBJECTS = {
        "Day1":  "Cash Offer for Your Property at {address}",
        "Day2":  "Quick Follow-Up — {address}",
        "Day5":  "Still Interested? {address}",
        "Day8":  "Cash Offer Reminder — {address}",
        "Day11": "One More Thought About {address}",
        "Day14": "Last Check-In — {address}",
    }

    ZIP_EMAIL_BODIES = {
        "Day1": (
            "Hi {first},\n\n"
            "My name is Chris Johnson — I'm a local cash home buyer here in Miami, "
            "and I wanted to personally reach out about your property at {address}.\n\n"
            "If selling has ever crossed your mind, I'd love to make it as simple and "
            "stress-free as possible. No repairs. No agent fees. Close in as little as 7 days.\n\n"
            "Would you be open to hearing a no-obligation cash offer?"
        ),
        "Day2": (
            "Hi {first},\n\n"
            "I reached out a couple of days ago about {address} and just wanted to "
            "make sure my email didn't get buried.\n\n"
            "I'm still very interested in making you a no-obligation cash offer. "
            "There's no pressure — just a straightforward number so you know your options."
        ),
        "Day5": (
            "Hi {first},\n\n"
            "Quick reminder — we buy houses in any condition and can close fast on "
            "{address}. Whether your home needs repairs or you just want a hassle-free "
            "sale, we've got you covered.\n\n"
            "Interested in a free, no-obligation offer?"
        ),
        "Day8": (
            "Hi {first},\n\n"
            "Just checking in about {address}. We pay cash, cover closing costs, "
            "and can close on your timeline.\n\n"
            "A 5-minute call is all it takes to get a number in your hands. Worth a chat?"
        ),
        "Day11": (
            "Hi {first},\n\n"
            "I wanted to reach out one more time about {address}. "
            "If you've been thinking about selling, I'd love to make you a fair cash offer. "
            "No strings attached!\n\n"
            "Whenever you're ready, I'm here."
        ),
        "Day14": (
            "Hi {first},\n\n"
            "This is my last check-in about {address}. Our cash offer still stands, "
            "and if now's not the right time, no worries at all.\n\n"
            "Feel free to reach out whenever you're ready. Wishing you all the best!\n\n"
            "— Chris Johnson, Johnson Buys"
        ),
    }

    def build_zip_email(first, address, day_key):
        subject = ZIP_EMAIL_SUBJECTS[day_key].replace("{address}", address)
        body_text = ZIP_EMAIL_BODIES[day_key].replace("{first}", first).replace("{address}", address)
        html = HEADER + f"""
        <tr>
          <td style="padding:36px 40px 28px 40px;">
            {"".join(f'<p style="font-size:15px; color:#444; line-height:1.7; margin:0 0 16px 0;">{line}</p>' for line in body_text.split(chr(10)+chr(10)) if line.strip())}
          </td>
        </tr>
        {divider()}
        {cta_button()}
        {divider()}
        """ + FOOTER
        return subject, html

    def send_zip_email(to_address, first, address, day_key):
        subject, html = build_zip_email(first, address, day_key)
        payload = {
            "personalizations": [{"to": [{"email": to_address}]}],
            "from": {"email": EMAIL_ADDRESS, "name": FROM_NAME},
            "subject": subject,
            "content": [{"type": "text/html", "value": html}],
            "tracking_settings": {
                "click_tracking":  {"enable": True},
                "open_tracking":   {"enable": True},
            }
        }
        result = subprocess.run([
            "curl", "-s", "-m", "30", "-X", "POST",
            "https://api.sendgrid.com/v3/mail/send",
            "-H", f"Authorization: Bearer {SENDGRID_API_KEY}",
            "-H", "Content-Type: application/json",
            "-d", json.dumps(payload)
        ], capture_output=True, text=True, timeout=35)
        if result.returncode != 0:
            raise RuntimeError(f"curl error: {result.stderr[:200]}")
        if result.stdout.strip():
            try:
                resp = json.loads(result.stdout)
                if resp.get("errors"):
                    raise RuntimeError(f"SendGrid error: {resp['errors']}")
            except json.JSONDecodeError:
                pass
        return True

    print(f"\n{'=' * 55}")
    print(f"  ZIP CODE EMAIL CAMPAIGNS")
    print(f"{'=' * 55}\n")

    for zc in ZIP_EMAIL_CAMPAIGNS:
        zip_code = zc["zip"]
        tag_prefix = zc["tag_prefix"]
        zip_budget = zc["budget"]

        print(f"─── Zip {zip_code} Emails (budget: {zip_budget}) ───")

        # Fetch leads from Salesforce list view
        listview_name = zc.get("listview_name")
        if listview_name:
            print(f"  Loading leads from list view '{listview_name}'...")
            zip_leads = sf_get_listview_leads(
                session_id, sf_instance, listview_name,
                ["Id", "FirstName", "LastName", "Email", "Property_Address__c", "Street", "City", "State"]
            )
            # Filter to only those with email
            zip_leads = [l for l in zip_leads if l.get("Email")]
        else:
            # ORDER BY CreatedDate DESC prioritizes today's PPL leads over old
            # backlog. With a 500/day SendGrid budget, fresh leads are higher
            # converters per email — they get the Day-1 touch first.
            zip_leads = sf_query(
                session_id, sf_instance,
                f"SELECT Id, FirstName, LastName, Email, Property_Address__c, Street, City, State "
                f"FROM Lead WHERE Email != null AND PostalCode = '{zip_code}' "
                f"AND IsConverted = false "
                f"ORDER BY CreatedDate DESC",
                all_records=True
            )
        print(f"  Emailable leads in {zip_code}: {len(zip_leads)}")

        if not zip_leads:
            print(f"  No leads. Skipping.\n")
            continue

        # Load touch history for these leads
        zip_lead_ids = [l["Id"] for l in zip_leads]
        all_zip_tags = [f"{tag_prefix}-{s[2]}" for s in ZIP_EMAIL_SCHEDULE]
        tag_filter = " OR ".join([f"Subject LIKE '%{tag}%'" for tag in all_zip_tags])

        zip_tasks = []
        for i in range(0, len(zip_lead_ids), 200):
            batch = zip_lead_ids[i:i+200]
            id_list = "','".join(batch)
            tasks = sf_query(
                session_id, sf_instance,
                f"SELECT WhoId, Subject, ActivityDate FROM Task "
                f"WHERE WhoId IN ('{id_list}') "
                f"AND ({tag_filter}) "
                f"ORDER BY CreatedDate DESC",
                all_records=True
            )
            zip_tasks.extend(tasks)

        # Build history: leadId -> { tag -> date }
        zip_history = {}
        for t in zip_tasks:
            lid = t["WhoId"]
            if lid not in zip_history:
                zip_history[lid] = {}
            subj = t.get("Subject", "")
            for full_tag in all_zip_tags:
                if full_tag in subj and full_tag not in zip_history[lid]:
                    try:
                        zip_history[lid][full_tag] = datetime.date.fromisoformat(t.get("ActivityDate", ""))
                    except:
                        zip_history[lid][full_tag] = today

        # Determine next touch for each lead
        zip_sent = zip_failed = 0
        for lead in zip_leads:
            if zip_budget <= 0:
                break
            lid = lead["Id"]
            hist = zip_history.get(lid, {})
            first = (lead.get("FirstName") or "there").strip() or "there"
            last = (lead.get("LastName") or "").strip()
            email = lead["Email"]
            addr = address_for(lead)

            first_tag = f"{tag_prefix}-{ZIP_EMAIL_SCHEDULE[0][2]}"
            first_touch_date = hist.get(first_tag)

            # Find next touch to send
            touch_to_send = None
            if first_tag not in hist:
                touch_to_send = ZIP_EMAIL_SCHEDULE[0]
            elif first_touch_date:
                for idx, (num, days_after, day_key) in enumerate(ZIP_EMAIL_SCHEDULE[1:], start=1):
                    tag = f"{tag_prefix}-{day_key}"
                    if tag in hist:
                        continue
                    days_since_first = (today - first_touch_date).days
                    if days_since_first >= days_after:
                        touch_to_send = ZIP_EMAIL_SCHEDULE[idx]
                        break

            if not touch_to_send:
                continue

            num, days_after, day_key = touch_to_send
            tag = f"{tag_prefix}-{day_key}"

            zip_budget -= 1
            try:
                send_zip_email(email, first, addr, day_key)
                # Log task in Salesforce
                sf_post(session_id, sf_instance, "sobjects/Task", {
                    "WhoId": lid,
                    "Subject": f"{tag}: {first} {last}",
                    "Status": "Completed",
                    "ActivityDate": str(today),
                    "Description": f"Zip {zip_code} email touch {day_key} sent to {email}",
                })
                # Update in-memory cache
                zip_history.setdefault(lid, {})[tag] = today
                sent_tags.setdefault(lid, {})[tag] = today
                print(f"  ✓ {day_key} → {first} {last} <{email}>")
                zip_sent += 1
                time.sleep(0.3)
            except Exception as e:
                print(f"  ✗ Failed: {first} {last} ({email}) — {e}")
                zip_failed += 1

        print(f"  Zip {zip_code}: Sent {zip_sent} | Failed {zip_failed}\n")

    print(f"{'=' * 55}")
    print(f"✅ All campaigns complete for {today}")


if __name__ == "__main__":
    main()
