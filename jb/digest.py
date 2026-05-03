#!/usr/bin/env python3
"""
Johnson Buys — Daily Follow-Up Digest
──────────────────────────────────────
Shows all leads with follow-up tasks due today or overdue.
Run manually or scheduled to print at 8am each morning.

Usage:  python3 ~/Desktop/sf_followup_digest.py
"""

import subprocess, json, re, urllib.parse, sys, datetime, tempfile, os

# ─── Credentials (env vars in cloud, .env file in local dev) ────────────
import os
SF_USERNAME       = os.environ["SF_USERNAME"]
SF_PASSWORD       = os.environ["SF_PASSWORD"]
SF_SECURITY_TOKEN = os.environ["SF_SECURITY_TOKEN"]
SF_DOMAIN         = os.environ.get("SF_DOMAIN", "johnsonshomes2.my")

def sf_login():
    soap = ('<?xml version="1.0" encoding="utf-8"?>'
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"'
            ' xmlns:urn="urn:partner.soap.sforce.com"><soapenv:Body><urn:login>'
            f'<urn:username>{SF_USERNAME}</urn:username>'
            f'<urn:password>{SF_PASSWORD}{SF_SECURITY_TOKEN}</urn:password>'
            '</urn:login></soapenv:Body></soapenv:Envelope>')
    with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
        f.write(soap)
        tmpfile = f.name
    r = subprocess.run(["curl", "-s", "-m", "30", "-X", "POST",
        f"https://{SF_DOMAIN}.salesforce.com/services/Soap/u/58.0",
        "-H", "Content-Type: text/xml", "-H", "SOAPAction: login",
        "--data-binary", f"@{tmpfile}"],
        capture_output=True, text=True, timeout=35)
    os.unlink(tmpfile)
    session = re.search(r"<sessionId>(.+?)</sessionId>", r.stdout)
    server  = re.search(r"<serverUrl>(.+?)</serverUrl>", r.stdout)
    if not session:
        print("❌ Login failed:", r.stdout[:200])
        sys.exit(1)
    sf_instance = re.search(r"(https://[^/]+)", server.group(1)).group(1)
    return session.group(1), sf_instance

def sf_query(session_id, sf_instance, soql):
    url = f"{sf_instance}/services/data/v58.0/query?q={urllib.parse.quote(soql)}"
    r = subprocess.run(["curl", "-s", "-m", "30", url,
        "-H", f"Authorization: Bearer {session_id}"],
        capture_output=True, text=True, timeout=35)
    try:
        data = json.loads(r.stdout)
        return data.get("records", [])
    except Exception:
        return []

def sf_complete_task(session_id, sf_instance, task_id):
    """Mark a follow-up task as Completed after calling."""
    url = f"{sf_instance}/services/data/v58.0/sobjects/Task/{task_id}"
    subprocess.run(["curl", "-s", "-m", "30", "-X", "PATCH", url,
        "-H", f"Authorization: Bearer {session_id}",
        "-H", "Content-Type: application/json",
        "-d", json.dumps({"Status": "Completed"})],
        capture_output=True, text=True, timeout=35)

def main():
    today = datetime.date.today()
    print(f"\n{'='*60}")
    print(f"  JOHNSON BUYS — Follow-Up Digest  ({today})")
    print(f"{'='*60}\n")

    print("Connecting to Salesforce...")
    session_id, sf_instance = sf_login()
    print(f"✓ Connected\n")

    # Query overdue + today's follow-up tasks (Not Started only)
    soql = (
        "SELECT Id, Subject, ActivityDate, Description, "
        "Who.Name, Who.Id "
        "FROM Task "
        f"WHERE Status = 'Not Started' AND ActivityDate <= {today.isoformat()} "
        "AND OwnerId != null "
        "ORDER BY ActivityDate ASC, Who.Name ASC "
        "LIMIT 100"
    )
    tasks = sf_query(session_id, sf_instance, soql)

    if not tasks:
        print("  🎉 No follow-ups due today. You're all caught up!\n")
        return

    overdue = [t for t in tasks if t.get("ActivityDate", "") < today.isoformat()]
    due_today = [t for t in tasks if t.get("ActivityDate", "") == today.isoformat()]

    if overdue:
        print(f"  ⚠️  OVERDUE ({len(overdue)} tasks)\n")
        for t in overdue:
            name     = (t.get("Who") or {}).get("Name", "Unknown")
            due      = t.get("ActivityDate", "")
            subject  = t.get("Subject", "Follow-up")
            desc     = t.get("Description", "")
            days_ago = (today - datetime.date.fromisoformat(due)).days if due else 0
            print(f"    📌 {name}")
            print(f"       Task:    {subject}")
            if desc:
                print(f"       Note:    {desc}")
            print(f"       Due:     {due}  ({days_ago} day{'s' if days_ago != 1 else ''} overdue)")
            print()

    if due_today:
        print(f"  📅 DUE TODAY ({len(due_today)} tasks)\n")
        for t in due_today:
            name    = (t.get("Who") or {}).get("Name", "Unknown")
            subject = t.get("Subject", "Follow-up")
            desc    = t.get("Description", "")
            priority = t.get("Priority", "Normal")
            flag = "🔥 " if priority == "High" else "   "
            print(f"    {flag}{name}")
            print(f"       Task:  {subject}")
            if desc:
                print(f"       Note:  {desc}")
            print()

    print(f"{'='*60}")
    print(f"  Total due: {len(tasks)}  |  Overdue: {len(overdue)}  |  Today: {len(due_today)}")
    print(f"{'='*60}\n")
    print("  After calling a lead, mark their task done in Salesforce")
    print("  or run sf_triage.py to update their status.\n")

if __name__ == "__main__":
    main()
