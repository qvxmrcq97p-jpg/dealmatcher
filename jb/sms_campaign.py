#!/usr/bin/env python3
"""
Johnson Buys — Master SMS Campaign Runner (v2.2)
Runs daily (Monday-Saturday, skips Sunday). ALL daily SMS campaigns in one shot:
  1. New + Nurturing leads (200 each) — 6 touches over 45 days
  2. Sent Contract leads (200) — 1 initial + 1 follow-up
  3. 33127 Duplex leads (200/day) — 6 touches over 14 days
  4. 33142 Duplex leads (200/day) — 6 touches over 14 days

Distributes outbound SMS across multiple Twilio numbers (round-robin)
to avoid spam flagging and support scaling to 2000+ texts/day.

Runs daily until lists are exhausted. Tracks sends via Salesforce Tasks.
Uses curl for all network calls (avoids macOS Python socket issues).
"""

import datetime, subprocess, json, re, sys, time, urllib.parse, os

# ─── Sunday Skip ──────────────────────────────────────────────────────────────
if datetime.date.today().weekday() == 6:  # 6 = Sunday
    print(f"[{datetime.date.today()}] Sunday — skipping SMS campaign. Runs Mon-Sat.")
    sys.exit(0)

# ─── Credentials ──────────────────────────────────────────────────────────────
# ─── Credentials (env vars in cloud, .env file in local dev) ────────────
import os
SF_USERNAME       = os.environ["SF_USERNAME"]
SF_PASSWORD       = os.environ["SF_PASSWORD"]
SF_SECURITY_TOKEN = os.environ["SF_SECURITY_TOKEN"]
SF_DOMAIN         = os.environ.get("SF_DOMAIN", "johnsonshomes2.my")

TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN  = os.environ["TWILIO_AUTH_TOKEN"]

# ─── Multi-Number SMS Distribution ───────────────────────────────────────────
# Round-robin across multiple Twilio numbers to avoid spam flagging.
# Add new numbers here as they are purchased from Twilio.
TWILIO_FROM_NUMBERS = [
    "+19549534554",   # Primary — (954) 953-4554
    # +17866488624 REMOVED on 2026-04-20 — it is now the buyer/investor line
    # used by the /buyer-webhook Twilio Function (Cheap Homes FL). Keeping it
    # here would mix seller motivated-seller texts with the investor brand.
    # If you re-add a secondary seller number, do NOT use +17866488624.
    # Add more numbers below as purchased:
    # "+1XXXXXXXXXX",
    # "+1XXXXXXXXXX",
    # "+1XXXXXXXXXX",
    # "+1XXXXXXXXXX",
    # "+1XXXXXXXXXX",
    # "+1XXXXXXXXXX",
]

# Global counter for round-robin rotation
_sms_send_counter = 0

def get_next_from_number():
    """Round-robin through available Twilio numbers."""
    global _sms_send_counter
    num = TWILIO_FROM_NUMBERS[_sms_send_counter % len(TWILIO_FROM_NUMBERS)]
    _sms_send_counter += 1
    return num

# Legacy single-number reference (for backward compat)
TWILIO_FROM_NUMBER = TWILIO_FROM_NUMBERS[0]

CAMPAIGN_DAYS  = 45

# ─── Multi-Touch Follow-Up Schedule ──────────────────────────────────────────
# For zip code campaigns: 6 total touches (initial + 5 follow-ups) over 14 days
# Each entry: (tag_suffix, days_after_initial, message)
ZIP_TOUCH_SCHEDULE = [
    ("T1", 0, (
        "Hi! This is Chris. We are always ready to give you a cash offer on "
        "{Property_Address}. No obligation. Fast Closing. Any condition."
    )),
    ("T2", 2, (
        "Hi! Just following up — we're still interested in making a cash offer "
        "on {Property_Address}. Let us know if you'd like to chat. No pressure!"
    )),
    ("T3", 5, (
        "Hi, it's Chris again. Quick reminder — we buy houses in any condition "
        "and can close fast on {Property_Address}. Interested in a free, no-obligation offer?"
    )),
    ("T4", 8, (
        "Hi! Chris here. Still interested in {Property_Address}. "
        "We pay cash, cover closing costs, and can close on your timeline. Worth a quick chat?"
    )),
    ("T5", 11, (
        "Hi! Just wanted to reach out one more time about {Property_Address}. "
        "If you've been thinking about selling, we'd love to make you a fair cash offer. No strings attached!"
    )),
    ("T6", 14, (
        "Hi, it's Chris from Johnson Buys. Last check-in on {Property_Address} — "
        "our cash offer still stands. If now's not the right time, no worries at all. "
        "Feel free to reach out whenever you're ready!"
    )),
]

# ─── New + Nurturing Follow-Up Schedule ──────────────────────────────────────
# 6 total touches (initial + 5 follow-ups) spread over 45 days
# Mirrors the email drip cadence: Day 0, 3, 7, 14, 21, 45
NEW_NURTURING_TOUCH_SCHEDULE = [
    ("T1", 0, (
        "Hi! This is Chris. We are always ready to give you a cash offer on "
        "{Property_Address}. No obligation. Fast Closing. Any condition."
    )),
    ("T2", 3, (
        "Hi! Just following up — we're still interested in making a cash offer "
        "on {Property_Address}. Let us know if you'd like to chat. No pressure!"
    )),
    ("T3", 7, (
        "Hi, it's Chris again. Quick reminder — we buy houses in any condition "
        "and can close fast on {Property_Address}. Interested in a free, no-obligation offer?"
    )),
    ("T4", 14, (
        "Hi! Chris here. Still interested in {Property_Address}. "
        "We pay cash, cover closing costs, and can close on your timeline. Worth a quick chat?"
    )),
    ("T5", 21, (
        "Hi! Just wanted to reach out one more time about {Property_Address}. "
        "If you've been thinking about selling, we'd love to make you a fair cash offer. No strings attached!"
    )),
    ("T6", 45, (
        "Hi, it's Chris from Johnson Buys. Last check-in on {Property_Address} — "
        "our cash offer still stands. If now's not the right time, no worries at all. "
        "Feel free to reach out whenever you're ready!"
    )),
]

# ─── Campaign Configurations ─────────────────────────────────────────────────
# "multi_touch" campaigns use a touch schedule (6 touches over N days)
# "simple" campaigns use 1 initial + 1 follow-up (3-day gap)
CAMPAIGNS = [
    {
        "name": "New + Nurturing",
        "mode": "multi_touch",
        "tag_prefix": "JB-SMS-NN",
        "daily_limit": 200,
        "touch_schedule": NEW_NURTURING_TOUCH_SCHEDULE,
        "queries": [
            {
                "label": "New",
                "limit": 200,
                "soql": (
                    "SELECT Id, FirstName, LastName, Phone, Phone2__c, MobilePhone, "
                    "Property_Address__c, Status, SMS_Opt_Out__c "
                    "FROM Lead "
                    "WHERE Status = 'New' "
                    "AND IsConverted = false "
                    "AND (SMS_Opt_Out__c = false OR SMS_Opt_Out__c = null) "
                    "AND (Phone != null OR Phone2__c != null OR MobilePhone != null) "
                    "AND CreatedDate >= {cutoff}T00:00:00Z "
                    "ORDER BY CreatedDate DESC"  # fresh first — prioritize today's leads
                ),
            },
            {
                "label": "Nurturing",
                "limit": 200,
                "soql": (
                    "SELECT Id, FirstName, LastName, Phone, Phone2__c, MobilePhone, "
                    "Property_Address__c, Status, SMS_Opt_Out__c "
                    "FROM Lead "
                    "WHERE Status = 'Nurturing' "
                    "AND IsConverted = false "
                    "AND (SMS_Opt_Out__c = false OR SMS_Opt_Out__c = null) "
                    "AND (Phone != null OR Phone2__c != null OR MobilePhone != null) "
                    "ORDER BY CreatedDate DESC"  # fresh first — prioritize today's leads
                ),
            },
        ],
    },
    {
        "name": "Sent Contract",
        "mode": "simple",
        "tag_initial": "JB-SMS-SC-Sent",
        "tag_followup": "JB-SMS-SC-FU-Sent",
        "followup_days": 3,
        "msg_initial": (
            "Hi! This is Chris from Johnson Buys. Just checking in on the contract "
            "we sent over for {Property_Address}. Do you have any questions? "
            "We're ready to move forward whenever you are!"
        ),
        "msg_followup": (
            "Hi! Following up on the contract for {Property_Address}. "
            "We'd love to get this closed for you. Let us know if you need anything!"
        ),
        "queries": [
            {
                "label": "Sent Contract",
                "limit": 200,
                "soql": (
                    "SELECT Id, FirstName, LastName, Phone, Phone2__c, MobilePhone, "
                    "Property_Address__c, Status, SMS_Opt_Out__c "
                    "FROM Lead "
                    "WHERE Status = 'Sent Contract' "
                    "AND IsConverted = false "
                    "AND (SMS_Opt_Out__c = false OR SMS_Opt_Out__c = null) "
                    "AND (Phone != null OR Phone2__c != null OR MobilePhone != null) "
                    "ORDER BY CreatedDate DESC"  # fresh first — prioritize today's leads
                ),
            },
        ],
    },
    {
        "name": "33127 Duplex B4",
        "mode": "multi_touch",
        "tag_prefix": "JB-SMS-33127",
        "daily_limit": 200,
        "listview_name": "X33127_Duplex_B4",
    },
    {
        "name": "33142 Duplex B4",
        "mode": "multi_touch",
        "tag_prefix": "JB-SMS-33142",
        "daily_limit": 200,
        "listview_name": "X33142_Duplex_B4",
    },
]

# ─── Logging ──────────────────────────────────────────────────────────────────
LOG_LINES = []
# In cloud mode (Railway) write log only to stdout — Railway captures it.
# In local mode (Mac), also append to ~/Desktop for human review.
DESKTOP = os.path.expanduser("~/Desktop") if not os.environ.get("CLOUD_MODE") else None

def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_LINES.append(line)

def write_log():
    # In cloud (Railway) DESKTOP is None — log already went to stdout via log()
    # which Railway captures. Skip file-write so we don't crash on join(None).
    if DESKTOP is None:
        return
    today = datetime.date.today().strftime("%Y%m%d")
    for name in [f"sms_all_campaigns_log_{today}.txt", "sms_all_campaigns_log_latest.txt"]:
        path = os.path.join(DESKTOP, name)
        with open(path, "w") as f:
            f.write("\n".join(LOG_LINES))

# ─── Salesforce via curl ──────────────────────────────────────────────────────
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
        log(f"❌ Salesforce login failed: {r.stdout[:300]}")
        sys.exit(1)
    session_id  = session.group(1)
    sf_instance = re.search(r"(https://[^/]+)", server.group(1)).group(1)
    log(f"✅ Salesforce login OK → {sf_instance}")
    return session_id, sf_instance

def sf_query(session_id, sf_instance, soql):
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
            log(f"❌ SF query parse error: {r.stdout[:200]}")
            break
        if "records" not in data:
            log(f"❌ SF query error: {r.stdout[:200]}")
            break
        records.extend(data["records"])
        url = f"{sf_instance}{data['nextRecordsUrl']}" if not data.get("done", True) else None
    return records

def sf_get_listview_leads(session_id, sf_instance, listview_dev_name):
    """Fetch leads from a Salesforce List View by developer name.
    Uses the ListView SOQL + REST API to get the actual lead records."""
    lv_soql = (
        f"SELECT Id FROM ListView "
        f"WHERE SobjectType = 'Lead' AND DeveloperName = '{listview_dev_name}'"
    )
    lv_records = sf_query(session_id, sf_instance, lv_soql)
    if not lv_records:
        log(f"   ⚠️ List view '{listview_dev_name}' not found. Trying without X prefix...")
        alt_name = listview_dev_name.lstrip('X')
        lv_soql = (
            f"SELECT Id FROM ListView "
            f"WHERE SobjectType = 'Lead' AND DeveloperName = '{alt_name}'"
        )
        lv_records = sf_query(session_id, sf_instance, lv_soql)
    if not lv_records:
        log(f"   ❌ List view not found by either name.")
        return []

    lv_id = lv_records[0]["Id"]
    log(f"   List view ID: {lv_id}")

    url = f"{sf_instance}/services/data/v58.0/sobjects/Lead/listviews/{lv_id}/results"
    r = subprocess.run(
        ["curl", "-s", "-m", "60", url,
         "-H", f"Authorization: Bearer {session_id}"],
        capture_output=True, text=True, timeout=65
    )
    try:
        data = json.loads(r.stdout)
    except Exception:
        log(f"   ❌ List view results parse error: {r.stdout[:200]}")
        return []

    if "records" not in data:
        log(f"   ❌ List view results error: {r.stdout[:300]}")
        return []

    lead_ids = []
    for rec in data.get("records", []):
        cols = rec.get("columns", [])
        for col in cols:
            val = col.get("value")
            if val and isinstance(val, str) and val.startswith("00Q"):
                lead_ids.append(val)
                break

    if not lead_ids:
        log(f"   ⚠️ No lead IDs extracted from list view results.")
        return []

    log(f"   Found {len(lead_ids)} leads in list view")

    all_leads = []
    for i in range(0, len(lead_ids), 200):
        batch = lead_ids[i:i+200]
        id_list = "','".join(batch)
        leads = sf_query(session_id, sf_instance,
            f"SELECT Id, FirstName, LastName, Phone, Phone2__c, MobilePhone, "
            f"Property_Address__c, Status, SMS_Opt_Out__c "
            f"FROM Lead WHERE Id IN ('{id_list}')"
        )
        all_leads.extend(leads)

    filtered = [
        l for l in all_leads
        if not l.get("SMS_Opt_Out__c")
        and (l.get("Phone") or l.get("Phone2__c") or l.get("MobilePhone"))
    ]
    log(f"   {len(filtered)} leads with phone numbers (after opt-out filter)")
    return filtered

def sf_create_task(session_id, sf_instance, lead_id, subject, description):
    today = datetime.date.today().isoformat()
    payload = json.dumps({
        "WhoId": lead_id,
        "Subject": subject,
        "Status": "Completed",
        "Priority": "Normal",
        "ActivityDate": today,
        "Description": description
    })
    r = subprocess.run(
        ["curl", "-s", "-m", "30", "-X", "POST",
         f"{sf_instance}/services/data/v58.0/sobjects/Task",
         "-H", f"Authorization: Bearer {session_id}",
         "-H", "Content-Type: application/json",
         "-d", payload],
        capture_output=True, text=True, timeout=35
    )
    try:
        resp = json.loads(r.stdout)
        return resp.get("success", False)
    except Exception:
        return False

# ─── Twilio via curl ──────────────────────────────────────────────────────────
def send_twilio_sms(to_number, message_body, from_number=None):
    """Send SMS via Twilio. Uses round-robin from_number if not specified."""
    if from_number is None:
        from_number = get_next_from_number()

    clean = re.sub(r"[^0-9]", "", to_number)
    if len(clean) == 10:
        clean = "1" + clean
    clean = "+" + clean

    r = subprocess.run(
        ["curl", "-s", "-m", "30", "-X", "POST",
         f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json",
         "-u", f"{TWILIO_ACCOUNT_SID}:{TWILIO_AUTH_TOKEN}",
         "--data-urlencode", f"To={clean}",
         "--data-urlencode", f"From={from_number}",
         "--data-urlencode", f"Body={message_body}"],
        capture_output=True, text=True, timeout=35
    )
    try:
        resp = json.loads(r.stdout)
        if resp.get("sid"):
            return True, resp["sid"]
        else:
            return False, resp.get("message", r.stdout[:200])
    except Exception:
        return False, r.stdout[:200]

# ─── Send a text and log it ──────────────────────────────────────────────────
def get_all_phones(lead):
    """Return a deduplicated list of all phone numbers on a lead."""
    phones = []
    seen = set()
    for field in ("Phone", "Phone2__c", "MobilePhone"):
        raw = lead.get(field)
        if not raw:
            continue
        for num in re.split(r"[,;]+", str(raw)):
            cleaned = re.sub(r"[^0-9]", "", num.strip())
            if len(cleaned) >= 7 and cleaned not in seen:
                seen.add(cleaned)
                phones.append(num.strip())
    return phones

def send_and_track(session_id, sf_instance, lead, touch_label, msg_template, tag):
    phones = get_all_phones(lead)
    if not phones:
        return "skipped", 0

    prop_addr = lead.get("Property_Address__c") or "your property"
    message = msg_template.replace("{Property_Address}", prop_addr)
    name_str = f"{lead.get('FirstName', '')} {lead.get('LastName', '')}".strip()

    sent_count = 0
    any_success = False
    last_error = ""

    for phone in phones:
        from_num = get_next_from_number()
        success, result = send_twilio_sms(phone, message, from_number=from_num)
        if success:
            sent_count += 1
            any_success = True
            log(f"   ✅ {touch_label:10s} → {name_str} ({phone}) via {from_num[-4:]}")
        else:
            last_error = result
            log(f"   ❌ {touch_label:10s} → {name_str} ({phone}) — {result}")
        time.sleep(0.3)

    if any_success:
        all_phones_str = ", ".join(phones)
        desc = f"SMS sent to {all_phones_str}: {message}"
        sf_create_task(session_id, sf_instance, lead["Id"], tag, desc)
        return "sent", sent_count
    else:
        return "failed", 0

# ─── Run a SIMPLE campaign (1 initial + 1 follow-up) ─────────────────────────
def run_simple_campaign(session_id, sf_instance, campaign):
    name = campaign["name"]
    tag_initial = campaign["tag_initial"]
    tag_followup = campaign["tag_followup"]
    followup_days = campaign["followup_days"]

    log("")
    log("=" * 60)
    log(f"  CAMPAIGN: {name}  (simple: initial + 1 follow-up)")
    log("=" * 60)

    cutoff_date = (datetime.date.today() - datetime.timedelta(days=CAMPAIGN_DAYS)).isoformat()

    all_leads = []
    for q in campaign["queries"]:
        soql = q["soql"].replace("{cutoff}", cutoff_date)
        leads = sf_query(session_id, sf_instance, soql)
        log(f"   {q['label']} leads found: {len(leads)}")
        all_leads.append((leads, q["limit"], q["label"]))

    leads_flat = []
    for leads, limit, label in all_leads:
        leads_flat.extend(leads)

    if not leads_flat:
        log(f"   No leads found. Skipping.")
        return 0, 0, 0

    lead_ids = [l["Id"] for l in leads_flat]
    log(f"   Loading SMS send history...")
    all_tasks = []
    for i in range(0, len(lead_ids), 200):
        batch = lead_ids[i:i+200]
        id_list = "','".join(batch)
        tasks = sf_query(session_id, sf_instance,
            f"SELECT WhoId, Subject, CreatedDate FROM Task "
            f"WHERE WhoId IN ('{id_list}') "
            f"AND (Subject = '{tag_initial}' OR Subject = '{tag_followup}') "
            f"ORDER BY CreatedDate DESC"
        )
        all_tasks.extend(tasks)

    sms_history = {}
    for t in all_tasks:
        lid = t["WhoId"]
        if lid not in sms_history:
            sms_history[lid] = {"has_initial": False, "has_followup": False, "initial_date": None}
        if t["Subject"] == tag_initial:
            sms_history[lid]["has_initial"] = True
            try:
                dt = datetime.datetime.fromisoformat(t["CreatedDate"].replace("Z", "+00:00"))
                if sms_history[lid]["initial_date"] is None or dt > sms_history[lid]["initial_date"]:
                    sms_history[lid]["initial_date"] = dt
            except:
                pass
        elif t["Subject"] == tag_followup:
            sms_history[lid]["has_followup"] = True

    log(f"   Loaded {len(all_tasks)} task records")

    now = datetime.datetime.now(datetime.timezone.utc)
    to_send_by_group = []
    for leads, limit, label in all_leads:
        group = []
        for lead in leads:
            lid = lead["Id"]
            hist = sms_history.get(lid, {"has_initial": False, "has_followup": False, "initial_date": None})
            if not hist["has_initial"]:
                group.append((lead, "INITIAL", campaign["msg_initial"], tag_initial))
            elif not hist["has_followup"] and hist["initial_date"]:
                if (now - hist["initial_date"]).days >= followup_days:
                    group.append((lead, "FOLLOW-UP", campaign["msg_followup"], tag_followup))
        log(f"   {label}: {len(group)} to text — limit {limit}")
        to_send_by_group.append(group[:limit])

    combined = []
    for group in to_send_by_group:
        combined.extend(group)

    sent = failed = skipped = total_msgs = 0
    log(f"   Sending to {len(combined)} leads (all phone numbers per lead)...")
    for lead, touch, msg, tag in combined:
        result, msg_count = send_and_track(session_id, sf_instance, lead, touch, msg, tag)
        if result == "sent":
            sent += 1
            total_msgs += msg_count
        elif result == "failed": failed += 1
        else: skipped += 1
        time.sleep(0.3)

    log(f"   ✅ '{name}' done: {sent} leads contacted ({total_msgs} texts) | Failed {failed} | Skipped {skipped}")
    return total_msgs, failed, skipped

# ─── Run a MULTI-TOUCH campaign (initial + N follow-ups) ─────────────────────
def run_multi_touch_campaign(session_id, sf_instance, campaign):
    name = campaign["name"]
    tag_prefix = campaign["tag_prefix"]
    daily_limit = campaign["daily_limit"]
    schedule = campaign.get("touch_schedule", ZIP_TOUCH_SCHEDULE)
    num_touches = len(schedule)
    max_days = schedule[-1][1]

    log("")
    log("=" * 60)
    log(f"  CAMPAIGN: {name}  (multi-touch: {num_touches} texts over {max_days} days)")
    log("=" * 60)

    all_tags = [f"{tag_prefix}-{t[0]}" for t in schedule]
    tag_filter = " OR ".join([f"Subject = '{tag}'" for tag in all_tags])

    cutoff_date = (datetime.date.today() - datetime.timedelta(days=CAMPAIGN_DAYS)).isoformat()

    if "listview_name" in campaign:
        leads = sf_get_listview_leads(session_id, sf_instance, campaign["listview_name"])
    elif "queries" in campaign:
        leads = []
        for q in campaign["queries"]:
            soql = q["soql"].replace("{cutoff}", cutoff_date)
            q_leads = sf_query(session_id, sf_instance, soql)
            log(f"   {q['label']} leads found: {len(q_leads)}")
            leads.extend(q_leads[:q.get("limit", 200)])
    else:
        leads = sf_query(session_id, sf_instance, campaign["soql"])
    log(f"   Leads found: {len(leads)}")

    if not leads:
        log(f"   No leads found. Skipping.")
        return 0, 0, 0

    lead_ids = [l["Id"] for l in leads]
    log(f"   Loading multi-touch SMS history...")
    all_tasks = []
    for i in range(0, len(lead_ids), 200):
        batch = lead_ids[i:i+200]
        id_list = "','".join(batch)
        tasks = sf_query(session_id, sf_instance,
            f"SELECT WhoId, Subject, CreatedDate FROM Task "
            f"WHERE WhoId IN ('{id_list}') "
            f"AND ({tag_filter}) "
            f"ORDER BY CreatedDate DESC"
        )
        all_tasks.extend(tasks)

    touch_history = {}
    for t in all_tasks:
        lid = t["WhoId"]
        if lid not in touch_history:
            touch_history[lid] = {}
        subj = t["Subject"]
        try:
            dt = datetime.datetime.fromisoformat(t["CreatedDate"].replace("Z", "+00:00"))
            if subj not in touch_history[lid] or dt > touch_history[lid][subj]:
                touch_history[lid][subj] = dt
        except:
            touch_history[lid][subj] = None

    log(f"   Loaded {len(all_tasks)} task records for {len(touch_history)} leads")

    now = datetime.datetime.now(datetime.timezone.utc)
    to_send = []

    for lead in leads:
        lid = lead["Id"]
        hist = touch_history.get(lid, {})

        first_tag = f"{tag_prefix}-{schedule[0][0]}"
        first_touch_date = hist.get(first_tag)

        if first_tag not in hist:
            tag = first_tag
            msg = schedule[0][2]
            to_send.append((lead, "T1-INIT", msg, tag))
            continue

        if first_touch_date is None:
            continue

        for idx, (suffix, days_after, msg) in enumerate(schedule[1:], start=1):
            tag = f"{tag_prefix}-{suffix}"
            if tag in hist:
                continue
            days_since_first = (now - first_touch_date).days
            if days_since_first >= days_after:
                to_send.append((lead, f"T{idx+1}-FU{idx}", msg, tag))
                break

    touch_counts = {}
    for _, touch_label, _, _ in to_send:
        touch_counts[touch_label] = touch_counts.get(touch_label, 0) + 1
    for label, count in sorted(touch_counts.items()):
        log(f"   {label}: {count} leads")
    log(f"   Total to send: {len(to_send)} — daily limit: {daily_limit}")

    to_send = to_send[:daily_limit]

    sent = failed = skipped = 0
    all_done = len(to_send) == 0

    total_msgs = 0
    if all_done:
        log(f"   🎉 All leads in this list have completed all {num_touches} touches! List exhausted.")
    else:
        log(f"   Sending to {len(to_send)} leads (all phone numbers per lead)...")

    for lead, touch_label, msg_template, tag in to_send:
        result, msg_count = send_and_track(session_id, sf_instance, lead, touch_label, msg_template, tag)
        if result == "sent":
            sent += 1
            total_msgs += msg_count
        elif result == "failed": failed += 1
        else: skipped += 1
        time.sleep(0.3)

    log(f"   ✅ '{name}' done: {sent} leads contacted ({total_msgs} texts) | Failed {failed} | Skipped {skipped}")
    return total_msgs, failed, skipped

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    log("=" * 60)
    log("  Johnson Buys — Master SMS Campaign Runner v2.2")
    log(f"  Date: {datetime.date.today().isoformat()}")
    log(f"  Sending numbers: {len(TWILIO_FROM_NUMBERS)} (round-robin)")
    log(f"  New+Nurturing: 6 touches over 45 days | Zip codes: 6 touches over 14 days")
    log("=" * 60)

    session_id, sf_instance = sf_login()

    total_sent = 0
    total_failed = 0
    total_skipped = 0

    for campaign in CAMPAIGNS:
        if campaign["mode"] == "simple":
            s, f, sk = run_simple_campaign(session_id, sf_instance, campaign)
        elif campaign["mode"] == "multi_touch":
            s, f, sk = run_multi_touch_campaign(session_id, sf_instance, campaign)
        else:
            log(f"⚠️ Unknown mode '{campaign['mode']}' for {campaign['name']}")
            continue
        total_sent += s
        total_failed += f
        total_skipped += sk

    log("")
    log("=" * 60)
    log(f"  ALL CAMPAIGNS COMPLETE")
    log(f"  Total Sent: {total_sent}  |  Failed: {total_failed}  |  Skipped: {total_skipped}")
    log(f"  Numbers used: {len(TWILIO_FROM_NUMBERS)} (round-robin)")
    log("=" * 60)

    write_log()

if __name__ == "__main__":
    main()
