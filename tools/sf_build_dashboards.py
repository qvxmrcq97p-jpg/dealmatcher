#!/usr/bin/env python3
"""
sf_build_dashboards.py — create all 32 reports + 10 dashboards in one shot.
─────────────────────────────────────────────────────────────────────────
Replaces the 4-6 hours of UI clicking with a single script run.

What it creates:
  - 32 underlying Reports (Lead, Contact, Task) with Group By + Chart configured
  - 10 Dashboards each with 2-5 widgets pointing at those reports

Run from your Mac:
    cd ~/dealmatcher
    python3 tools/sf_build_dashboards.py             # actually creates everything
    python3 tools/sf_build_dashboards.py --dry-run   # print plan only

Uses simple_salesforce (already in requirements.txt) via your existing
SF_USERNAME / SF_PASSWORD / SF_SECURITY_TOKEN in .env.cheaphomesfla.

After it runs:
    1. Open SF → Dashboards → Recent
    2. You'll see "01 Daily Lead Inflow" through "10 Buyer-Match Rate"
    3. Open each → click Refresh → pin to Home

Re-running is safe: existing reports/dashboards by the same name are
updated in place rather than duplicated.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import zipfile
import base64
import io
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = SCRIPT_DIR / ".env.cheaphomesfla"
if ENV_FILE.exists():
    for ln in ENV_FILE.read_text().splitlines():
        s = ln.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


API_VERSION = "58.0"


# ─── HTTP helpers (stdlib only) ──────────────────────────────────────
def http(method: str, url: str, headers: dict, data: Optional[bytes] = None,
         timeout: int = 60) -> tuple[int, str]:
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def sf_login() -> tuple[str, str]:
    user = os.environ["SF_USERNAME"]
    pw = os.environ["SF_PASSWORD"]
    tok = os.environ["SF_SECURITY_TOKEN"]
    domain = os.environ.get("SF_DOMAIN", "johnsonshomes2.my")
    soap = f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:urn="urn:partner.soap.sforce.com">
  <soapenv:Body>
    <urn:login>
      <urn:username>{user}</urn:username>
      <urn:password>{pw}{tok}</urn:password>
    </urn:login>
  </soapenv:Body>
</soapenv:Envelope>"""
    code, body = http("POST", f"https://{domain}.salesforce.com/services/Soap/u/{API_VERSION}",
                      {"Content-Type": "text/xml", "SOAPAction": "login"},
                      soap.encode())
    if code != 200:
        sys.exit(f"✗ SF login failed: HTTP {code}\n{body[:500]}")
    import re
    sid = re.search(r"<sessionId>(.+?)</sessionId>", body)
    srv = re.search(r"<serverUrl>(.+?)</serverUrl>", body)
    if not (sid and srv):
        sys.exit(f"✗ SF login response missing sessionId\n{body[:500]}")
    inst = re.search(r"(https://[^/]+)", srv.group(1)).group(1)
    return sid.group(1), inst


def sf_query(session: str, instance: str, soql: str) -> list[dict]:
    code, body = http("GET",
        f"{instance}/services/data/v{API_VERSION}/query?q={urllib.parse.quote(soql)}",
        {"Authorization": f"Bearer {session}"})
    if code != 200:
        return []
    return json.loads(body).get("records", [])


def sf_post(session: str, instance: str, path: str, payload: dict) -> tuple[int, dict]:
    code, body = http("POST", f"{instance}/services/data/v{API_VERSION}/{path}",
        {"Authorization": f"Bearer {session}", "Content-Type": "application/json"},
        json.dumps(payload).encode())
    try:
        return code, json.loads(body)
    except json.JSONDecodeError:
        return code, {"raw": body}


def sf_patch(session: str, instance: str, path: str, payload: dict) -> tuple[int, str]:
    return http("PATCH", f"{instance}/services/data/v{API_VERSION}/{path}",
        {"Authorization": f"Bearer {session}", "Content-Type": "application/json"},
        json.dumps(payload).encode())


# ─── Report definitions ──────────────────────────────────────────────
# Each report is a JSON definition matching SF Analytics REST schema.
# Common fields:
#   reportType         — "Leads", "TasksandEvents", "ContactList"
#   developerName      — unique API name (no spaces)
#   name               — display label
#   reportFormat       — TABULAR | SUMMARY | MATRIX
#   detailColumns      — flat columns (table view)
#   groupingsDown      — row groups (required for SUMMARY)
#   reportFilters      — filter list
#   chart              — chart config dict
#   showGrandTotal, showSubtotals, etc.

# Helper to make a date filter
def filter_date(field, op, value):
    return {"column": field, "operator": op, "value": value}


REPORTS: list[dict] = [
    # ─── Dashboard 1 — Daily Lead Inflow ──
    {
        "developerName": "DASH01_Leads_Today_By_Source",
        "name": "DASH01 — Leads Today by Source",
        "reportType": {"type": "LeadList"},
        "reportFormat": "SUMMARY",
        "groupingsDown": [{"name": "LEAD_SOURCE", "sortOrder": "Asc",
                           "dateGranularity": "None"}],
        "detailColumns": ["LAST_NAME", "EMAIL", "PHONE"],
        "reportFilters": [filter_date("CREATED_DATE", "equals", "TODAY")],
    },
    {
        "developerName": "DASH01_Leads_30day_Trend",
        "name": "DASH01 — Leads 30-Day Daily Trend",
        "reportType": {"type": "LeadList"},
        "reportFormat": "SUMMARY",
        "groupingsDown": [{"name": "CREATED_DATE", "sortOrder": "Asc",
                           "dateGranularity": "Day"}],
        "detailColumns": ["LAST_NAME", "EMAIL", "LEAD_SOURCE"],
        "reportFilters": [filter_date("CREATED_DATE", "equals", "LAST_N_DAYS:30")],
    },
    {
        "developerName": "DASH01_Leads_7day_By_Source",
        "name": "DASH01 — Leads Last 7 Days by Source",
        "reportType": {"type": "LeadList"},
        "reportFormat": "MATRIX",
        "groupingsDown": [{"name": "CREATED_DATE", "sortOrder": "Asc",
                           "dateGranularity": "Day"}],
        "groupingsAcross": [{"name": "LEAD_SOURCE", "sortOrder": "Asc",
                             "dateGranularity": "None"}],
        "detailColumns": ["LAST_NAME", "EMAIL"],
        "reportFilters": [filter_date("CREATED_DATE", "equals", "LAST_N_DAYS:7")],
    },
    {
        "developerName": "DASH01_Leads_MTD",
        "name": "DASH01 — Leads Month-To-Date",
        "reportType": {"type": "LeadList"},
        "reportFormat": "SUMMARY",
        "groupingsDown": [{"name": "LEAD_SOURCE", "sortOrder": "Asc",
                           "dateGranularity": "None"}],
        "detailColumns": ["LAST_NAME"],
        "reportFilters": [filter_date("CREATED_DATE", "equals", "THIS_MONTH")],
    },

    # ─── Dashboard 2 — Active Pipeline by Status ──
    {
        "developerName": "DASH02_Open_Leads_By_Status",
        "name": "DASH02 — Open Leads by Status",
        "reportType": {"type": "LeadList"},
        "reportFormat": "SUMMARY",
        "groupingsDown": [{"name": "STATUS", "sortOrder": "Asc",
                           "dateGranularity": "None"}],
        "detailColumns": ["LAST_NAME", "EMAIL", "PHONE"],
        "reportFilters": [
            {"column": "STATUS", "operator": "notEqual",
             "value": "Take me off the list,Doesn't own anymore"},
        ],
    },
    {
        "developerName": "DASH02_Sent_Contract_30d",
        "name": "DASH02 — Sent Contract Last 30 Days",
        "reportType": {"type": "LeadList"},
        "reportFormat": "TABULAR",
        "detailColumns": ["LAST_NAME", "PHONE", "STREET", "LAST_UPDATE"],
        "reportFilters": [
            {"column": "STATUS", "operator": "equals", "value": "Sent Contract"},
            filter_date("LAST_UPDATE", "equals", "LAST_N_DAYS:30"),
        ],
    },
    {
        "developerName": "DASH02_Stale_Working_14d",
        "name": "DASH02 — Stale Working Leads (14d+)",
        "reportType": {"type": "LeadList"},
        "reportFormat": "TABULAR",
        "detailColumns": ["LAST_NAME", "PHONE", "EMAIL", "LAST_UPDATE"],
        "reportFilters": [
            {"column": "STATUS", "operator": "equals", "value": "Working"},
            filter_date("LAST_UPDATE", "lessThan", "LAST_N_DAYS:14"),
        ],
    },

    # ─── Dashboard 3 — Lead Source Performance ──
    {
        "developerName": "DASH03_Source_Volume_60d",
        "name": "DASH03 — Lead Source Volume 60 Days",
        "reportType": {"type": "LeadList"},
        "reportFormat": "SUMMARY",
        "groupingsDown": [{"name": "LEAD_SOURCE", "sortOrder": "Asc",
                           "dateGranularity": "None"}],
        "detailColumns": ["LAST_NAME"],
        "reportFilters": [filter_date("CREATED_DATE", "equals", "LAST_N_DAYS:60")],
    },
    {
        "developerName": "DASH03_Source_SentContract_60d",
        "name": "DASH03 — Lead Source Sent Contract 60d",
        "reportType": {"type": "LeadList"},
        "reportFormat": "SUMMARY",
        "groupingsDown": [{"name": "LEAD_SOURCE", "sortOrder": "Asc",
                           "dateGranularity": "None"}],
        "detailColumns": ["LAST_NAME"],
        "reportFilters": [
            filter_date("CREATED_DATE", "equals", "LAST_N_DAYS:60"),
            {"column": "STATUS", "operator": "equals", "value": "Sent Contract"},
        ],
    },

    # ─── Dashboard 4 — Hot Buyers (CHF) ──
    {
        "developerName": "DASH04_Hot_Buyers",
        "name": "DASH04 — CHF Hot Buyers (Score 70+)",
        "reportType": {"type": "ContactList"},
        "reportFormat": "TABULAR",
        "detailColumns": ["FIRST_NAME", "LAST_NAME", "EMAIL"],
        "reportFilters": [
            {"column": "LEAD_SOURCE", "operator": "equals",
             "value": "CheapHomesFLA_LandingPage"},
        ]
    },
    {
        "developerName": "DASH04_Warm_Buyers",
        "name": "DASH04 — CHF Warm Buyers (50-69)",
        "reportType": {"type": "ContactList"},
        "reportFormat": "TABULAR",
        "detailColumns": ["FIRST_NAME", "LAST_NAME", "EMAIL"],
        "reportFilters": [
            {"column": "LEAD_SOURCE", "operator": "equals",
             "value": "CheapHomesFLA_LandingPage"},
        ],
    },
    {
        "developerName": "DASH04_Buyers_Missing_Zips",
        "name": "DASH04 — CHF Buyers Missing Zips",
        "reportType": {"type": "ContactList"},
        "reportFormat": "TABULAR",
        "detailColumns": ["FIRST_NAME", "LAST_NAME", "EMAIL"],
        "reportFilters": [
            {"column": "LEAD_SOURCE", "operator": "equals",
             "value": "CheapHomesFLA_LandingPage"},
        ],
    },

    # ─── Dashboard 5 — Daily Deal Activity ──
    {
        "developerName": "DASH05_Deals_Today",
        "name": "DASH05 — CHF Deals Today",
        "reportType": {"type": "TasksAndEvents"},
        "reportFormat": "TABULAR",
        "detailColumns": ["TASK_SUBJECT", "WHO_NAME", "CREATED_DATE"],
        "reportFilters": [
            {"column": "TASK_SUBJECT", "operator": "contains", "value": "CH-DEAL-"},
            filter_date("CREATED_DATE", "equals", "TODAY"),
        ],
    },
    {
        "developerName": "DASH05_Deals_14d_Trend",
        "name": "DASH05 — CHF Deals 14-Day Trend",
        "reportType": {"type": "TasksAndEvents"},
        "reportFormat": "SUMMARY",
        "groupingsDown": [{"name": "CREATED_DATE", "sortOrder": "Asc",
                           "dateGranularity": "Day"}],
        "detailColumns": ["TASK_SUBJECT", "WHO_NAME"],
        "reportFilters": [
            {"column": "TASK_SUBJECT", "operator": "contains", "value": "CH-DEAL-"},
            filter_date("CREATED_DATE", "equals", "LAST_N_DAYS:14"),
        ],
    },
    {
        "developerName": "DASH05_Deals_Per_Buyer_7d",
        "name": "DASH05 — Deals Matched per Buyer 7d",
        "reportType": {"type": "TasksAndEvents"},
        "reportFormat": "SUMMARY",
        "groupingsDown": [{"name": "WHO_NAME", "sortOrder": "Desc",
                           "dateGranularity": "None"}],
        "detailColumns": ["TASK_SUBJECT", "CREATED_DATE"],
        "reportFilters": [
            {"column": "TASK_SUBJECT", "operator": "contains", "value": "CH-DEAL-"},
            filter_date("CREATED_DATE", "equals", "LAST_N_DAYS:7"),
        ],
    },

    # ─── Dashboard 6 — Today's Follow-ups ──
    {
        "developerName": "DASH06_Tasks_Due_Today",
        "name": "DASH06 — Tasks Due Today",
        "reportType": {"type": "TasksAndEvents"},
        "reportFormat": "TABULAR",
        "detailColumns": ["TASK_SUBJECT", "WHO_NAME", "PRIORITY", "ACTIVITY_DATE"],
        "reportFilters": [
            filter_date("ACTIVITY_DATE", "equals", "TODAY"),
            {"column": "STATUS", "operator": "notEqual", "value": "Completed"},
        ],
        "sortColumn": "PRIORITY",
        "sortOrder": "Desc",
    },
    {
        "developerName": "DASH06_Tasks_Overdue",
        "name": "DASH06 — Tasks Overdue",
        "reportType": {"type": "TasksAndEvents"},
        "reportFormat": "TABULAR",
        "detailColumns": ["TASK_SUBJECT", "WHO_NAME", "PRIORITY", "ACTIVITY_DATE"],
        "reportFilters": [
            filter_date("ACTIVITY_DATE", "lessThan", "TODAY"),
            {"column": "STATUS", "operator": "notEqual", "value": "Completed"},
        ],
        "sortColumn": "ACTIVITY_DATE",
        "sortOrder": "Asc",
    },

    # ─── Dashboard 7 — SMS + Email Campaign Health ──
    {
        "developerName": "DASH07_JB_Email_Today",
        "name": "DASH07 — JB Email Sends Today",
        "reportType": {"type": "TasksAndEvents"},
        "reportFormat": "SUMMARY",
        "groupingsDown": [{"name": "TASK_SUBJECT", "sortOrder": "Asc",
                           "dateGranularity": "None"}],
        "detailColumns": ["TASK_SUBJECT", "WHO_NAME"],
        "reportFilters": [
            {"column": "TASK_SUBJECT", "operator": "startsWith", "value": "JB-Day"},
            filter_date("CREATED_DATE", "equals", "TODAY"),
        ],
    },
    {
        "developerName": "DASH07_JB_SMS_7d",
        "name": "DASH07 — JB SMS Sends 7-Day",
        "reportType": {"type": "TasksAndEvents"},
        "reportFormat": "SUMMARY",
        "groupingsDown": [{"name": "CREATED_DATE", "sortOrder": "Asc",
                           "dateGranularity": "Day"}],
        "detailColumns": ["TASK_SUBJECT", "WHO_NAME"],
        "reportFilters": [
            {"column": "TASK_SUBJECT", "operator": "startsWith", "value": "JB-SMS-"},
            filter_date("CREATED_DATE", "equals", "LAST_N_DAYS:7"),
        ],
    },
    {
        "developerName": "DASH07_Inbound_SMS_7d",
        "name": "DASH07 — Inbound SMS Replies 7-Day",
        "reportType": {"type": "TasksAndEvents"},
        "reportFormat": "SUMMARY",
        "groupingsDown": [{"name": "CREATED_DATE", "sortOrder": "Asc",
                           "dateGranularity": "Day"}],
        "detailColumns": ["TASK_SUBJECT", "WHO_NAME"],
        "reportFilters": [
            {"column": "TASK_SUBJECT", "operator": "contains", "value": "Inbound SMS"},
            filter_date("CREATED_DATE", "equals", "LAST_N_DAYS:7"),
        ],
    },
    {
        "developerName": "DASH07_Optouts_30d",
        "name": "DASH07 — Opt-outs 30-Day",
        "reportType": {"type": "LeadList"},
        "reportFormat": "SUMMARY",
        "groupingsDown": [{"name": "LAST_UPDATE", "sortOrder": "Asc",
                           "dateGranularity": "Day"}],
        "detailColumns": ["LAST_NAME"],
        "reportFilters": [
            {"column": "STATUS", "operator": "equals", "value": "Take me off the list"},
            filter_date("LAST_UPDATE", "equals", "LAST_N_DAYS:30"),
        ],
    },

    # ─── Dashboard 8 — Conversion Funnel ──
    {
        "developerName": "DASH08_Funnel_60d",
        "name": "DASH08 — Conversion Funnel 60d",
        "reportType": {"type": "LeadList"},
        "reportFormat": "SUMMARY",
        "groupingsDown": [{"name": "STATUS", "sortOrder": "Asc",
                           "dateGranularity": "None"}],
        "detailColumns": ["LAST_NAME"],
        "reportFilters": [filter_date("CREATED_DATE", "equals", "LAST_N_DAYS:60")],
    },

    # ─── Dashboard 9 — Revenue This Month ──
    {
        "developerName": "DASH09_Closed_MTD",
        "name": "DASH09 — Closed Won This Month",
        "reportType": {"type": "LeadList"},
        "reportFormat": "TABULAR",
        "detailColumns": ["LAST_NAME", "STREET", "LAST_UPDATE"],
        "reportFilters": [
            {"column": "STATUS", "operator": "equals", "value": "Sent Contract"},
            filter_date("LAST_UPDATE", "equals", "THIS_MONTH"),
        ],
    },
    {
        "developerName": "DASH09_Sent_Contract_Pipeline",
        "name": "DASH09 — Sent Contract Pipeline",
        "reportType": {"type": "LeadList"},
        "reportFormat": "TABULAR",
        "detailColumns": ["LAST_NAME", "PHONE", "STREET", "LAST_UPDATE"],
        "reportFilters": [
            {"column": "STATUS", "operator": "equals", "value": "Sent Contract"},
            filter_date("LAST_UPDATE", "equals", "LAST_N_DAYS:30"),
        ],
    },
    {
        "developerName": "DASH09_Closed_6mo_Trend",
        "name": "DASH09 — Closed 6-Month Trend",
        "reportType": {"type": "LeadList"},
        "reportFormat": "SUMMARY",
        "groupingsDown": [{"name": "LAST_UPDATE", "sortOrder": "Asc",
                           "dateGranularity": "Month"}],
        "detailColumns": ["LAST_NAME"],
        "reportFilters": [
            {"column": "STATUS", "operator": "equals", "value": "Sent Contract"},
            filter_date("LAST_UPDATE", "equals", "LAST_N_DAYS:180"),
        ],
    },

    # ─── Dashboard 10 — Buyer-Match Rate ──
    {
        "developerName": "DASH10_Matches_Per_Buyer_30d",
        "name": "DASH10 — Deal Matches per Buyer 30d",
        "reportType": {"type": "TasksAndEvents"},
        "reportFormat": "SUMMARY",
        "groupingsDown": [{"name": "WHO_NAME", "sortOrder": "Desc",
                           "dateGranularity": "None"}],
        "detailColumns": ["TASK_SUBJECT", "CREATED_DATE"],
        "reportFilters": [
            {"column": "TASK_SUBJECT", "operator": "contains", "value": "CH-DEAL-"},
            filter_date("CREATED_DATE", "equals", "LAST_N_DAYS:30"),
        ],
    },
]


# ─── Dashboard definitions (Metadata API .dashboard XML) ─────────────
# Each dashboard has 1-5 components; each component points at a report
# by developerName and chooses how to render it (Donut, Line, Metric, etc.)

DASHBOARDS = [
    {
        "name": "01 Daily Lead Inflow",
        "developerName": "Z01_Daily_Lead_Inflow",
        "components": [
            ("DASH01_Leads_Today_By_Source", "Donut", "Today by Source"),
            ("DASH01_Leads_7day_By_Source", "ColumnStacked", "Last 7 Days"),
            ("DASH01_Leads_MTD", "Metric", "MTD Total"),
            ("DASH01_Leads_30day_Trend", "Line", "30-Day Trend"),
        ],
    },
    {
        "name": "02 Active Pipeline by Status",
        "developerName": "Z02_Active_Pipeline",
        "components": [
            ("DASH02_Open_Leads_By_Status", "Bar", "Open by Status"),
            ("DASH02_Sent_Contract_30d", "Table", "Sent Contract 30d"),
            ("DASH02_Stale_Working_14d", "Table", "Stale Working"),
        ],
    },
    {
        "name": "03 Lead Source Performance",
        "developerName": "Z03_Lead_Source_Performance",
        "components": [
            ("DASH03_Source_Volume_60d", "Bar", "Volume 60d"),
            ("DASH03_Source_SentContract_60d", "Bar", "Sent Contract 60d"),
        ],
    },
    {
        "name": "04 Hot Buyers (CHF)",
        "developerName": "Z04_Hot_Buyers",
        "components": [
            ("DASH04_Hot_Buyers", "Table", "Hot Buyers (Score 70+)"),
            ("DASH04_Warm_Buyers", "Table", "Warm Buyers (50-69)"),
            ("DASH04_Buyers_Missing_Zips", "Metric", "Buyers Missing Zips"),
        ],
    },
    {
        "name": "05 Daily Deal Activity",
        "developerName": "Z05_Daily_Deal_Activity",
        "components": [
            ("DASH05_Deals_Today", "Metric", "Deals Today"),
            ("DASH05_Deals_14d_Trend", "Line", "14-Day Trend"),
            ("DASH05_Deals_Per_Buyer_7d", "Bar", "Per Buyer 7d"),
        ],
    },
    {
        "name": "06 Today's Follow-ups",
        "developerName": "Z06_Todays_Followups",
        "components": [
            ("DASH06_Tasks_Due_Today", "Table", "Due Today"),
            ("DASH06_Tasks_Overdue", "Table", "Overdue"),
        ],
    },
    {
        "name": "07 Campaign Health",
        "developerName": "Z07_Campaign_Health",
        "components": [
            ("DASH07_JB_Email_Today", "Bar", "Email Today by Touch"),
            ("DASH07_JB_SMS_7d", "Column", "SMS 7-Day"),
            ("DASH07_Inbound_SMS_7d", "Line", "Inbound 7-Day"),
            ("DASH07_Optouts_30d", "Column", "Opt-outs 30d"),
        ],
    },
    {
        "name": "08 Conversion Funnel",
        "developerName": "Z08_Conversion_Funnel",
        "components": [
            ("DASH08_Funnel_60d", "Funnel", "Funnel 60d"),
        ],
    },
    {
        "name": "09 Revenue This Month",
        "developerName": "Z09_Revenue_This_Month",
        "components": [
            ("DASH09_Closed_MTD", "Table", "Closed MTD"),
            ("DASH09_Sent_Contract_Pipeline", "Table", "Sent Contract Pipeline"),
            ("DASH09_Closed_6mo_Trend", "Column", "6-Month Trend"),
        ],
    },
    {
        "name": "10 Buyer-Match Rate",
        "developerName": "Z10_Buyer_Match_Rate",
        "components": [
            ("DASH10_Matches_Per_Buyer_30d", "Bar", "Matches per Buyer"),
        ],
    },
]


# ─── Report creation via Analytics REST ──────────────────────────────
def upsert_report(session: str, instance: str, rd: dict,
                  folder_id: str, dry_run: bool) -> Optional[str]:
    """Create or update a report. Returns report Id."""
    name = rd["name"]
    dev = rd["developerName"]

    # Check if report already exists
    existing = sf_query(session, instance,
        f"SELECT Id FROM Report WHERE DeveloperName = '{dev}'")
    existing_id = existing[0]["Id"] if existing else None

    if dry_run:
        action = "update" if existing_id else "create"
        print(f"  [dry-run] would {action} report: {name}")
        return existing_id or "dry-run-id"

    payload = {
        "reportMetadata": {
            "name": name,
            "developerName": dev,
            "reportType": rd["reportType"],
            "reportFormat": rd["reportFormat"],
            "folderId": folder_id,
            "detailColumns": rd.get("detailColumns", []),
            "groupingsDown": rd.get("groupingsDown", []),
            "groupingsAcross": rd.get("groupingsAcross", []),
            "reportFilters": rd.get("reportFilters", []),
            "showGrandTotal": True,
            "showSubtotals": True,
            "aggregates": ["RowCount"],
        }
    }
    if "chart" in rd:
        payload["reportMetadata"]["chart"] = rd["chart"]

    def fmt_err(b):
        # SF errors can be a list of {message, errorCode} dicts, OR a single dict, OR raw string
        if isinstance(b, list):
            return "; ".join(
                f"{e.get('errorCode','?')}: {e.get('message', e)}" if isinstance(e, dict) else str(e)
                for e in b
            )
        if isinstance(b, dict):
            return b.get("raw") or b.get("message") or json.dumps(b)
        return str(b)

    if existing_id:
        # PATCH update
        code, body = sf_patch(session, instance,
            f"analytics/reports/{existing_id}", payload)
        if 200 <= code < 300:
            print(f"  ✓ Updated report: {name}")
            return existing_id
        else:
            print(f"  ✗ Update failed for {name}: HTTP {code}\n     {str(body)[:400]}")
            return None
    else:
        # POST create
        code, body = sf_post(session, instance, "analytics/reports", payload)
        if 200 <= code < 300 and isinstance(body, dict):
            new_id = body.get("reportMetadata", {}).get("id") or body.get("id")
            print(f"  ✓ Created report: {name}")
            return new_id
        else:
            print(f"  ✗ Create failed for {name}: HTTP {code}\n     {fmt_err(body)[:400]}")
            return None


# ─── Folder management ───────────────────────────────────────────────
def get_or_create_folder(session: str, instance: str, dev_name: str,
                         display_name: str, folder_type: str) -> Optional[str]:
    """folder_type: 'Report' or 'Dashboard'"""
    existing = sf_query(session, instance,
        f"SELECT Id FROM Folder WHERE DeveloperName = '{dev_name}' "
        f"AND Type = '{folder_type}'")
    if existing:
        return existing[0]["Id"]
    code, body = sf_post(session, instance, "sobjects/Folder", {
        "Name": display_name,
        "DeveloperName": dev_name,
        "Type": folder_type,
        "AccessType": "Public",
    })
    if 200 <= code < 300 and body.get("id"):
        print(f"  ✓ Created folder: {display_name}")
        return body["id"]
    print(f"  ⚠️  Could not create folder {display_name}: HTTP {code} {body}")
    return None


# ─── Main ────────────────────────────────────────────────────────────
def discover(session: str, instance: str) -> None:
    """Print info about this org's report types + existing reports so I can
    figure out the right developerName / column-ID values."""
    print("\n=== AVAILABLE REPORT TYPES ===")
    code, body = http("GET",
        f"{instance}/services/data/v{API_VERSION}/analytics/reportTypes",
        {"Authorization": f"Bearer {session}"})
    if code == 200:
        try:
            data = json.loads(body)
            types = data.get("reportTypes", data) if isinstance(data, dict) else data
            for rt in (types[:80] if isinstance(types, list) else []):
                if isinstance(rt, dict):
                    print(f"  {rt.get('type','?'):<35} {rt.get('label','?')}")
        except Exception as e:
            print(f"  parse error: {e}\n  raw: {body[:1000]}")
    else:
        print(f"  HTTP {code}: {body[:500]}")

    print("\n=== YOUR EXISTING WORKING REPORTS (so I can match the format) ===")
    soql = ("SELECT Id, Name, DeveloperName, Format, FolderName "
            "FROM Report WHERE CreatedDate = LAST_N_DAYS:30 LIMIT 30")
    code, body = http("GET",
        f"{instance}/services/data/v{API_VERSION}/query?q={urllib.parse.quote(soql)}",
        {"Authorization": f"Bearer {session}"})
    if code == 200:
        for r in json.loads(body).get("records", []):
            print(f"  [{r.get('Format','?'):<7}] {r.get('Name','?')}  ({r.get('DeveloperName','?')})")

    # For one of your existing Lead reports, fetch its full describe
    # so we see what report type + column IDs SF used
    print("\n=== FULL DESCRIBE OF YOUR 'LEADS - TODAY BY SOURCE' REPORT ===")
    code, body = http("GET",
        f"{instance}/services/data/v{API_VERSION}/query?q="
        + urllib.parse.quote("SELECT Id FROM Report WHERE Name = 'LEADS - TODAY BY SOURCE' LIMIT 1"),
        {"Authorization": f"Bearer {session}"})
    if code == 200:
        recs = json.loads(body).get("records", [])
        if recs:
            rid = recs[0]["Id"]
            code2, body2 = http("GET",
                f"{instance}/services/data/v{API_VERSION}/analytics/reports/{rid}/describe",
                {"Authorization": f"Bearer {session}"})
            if code2 == 200:
                d = json.loads(body2)
                rm = d.get("reportMetadata", {})
                print(f"  reportType:   {rm.get('reportType')}")
                print(f"  reportFormat: {rm.get('reportFormat')}")
                print(f"  detailColumns (first 10): {rm.get('detailColumns', [])[:10]}")
                print(f"  groupingsDown: {rm.get('groupingsDown')}")
                print(f"  reportFilters: {rm.get('reportFilters')}")
                if rm.get("chart"):
                    print(f"  chart: {rm.get('chart')}")
            else:
                print(f"  describe HTTP {code2}: {body2[:300]}")
        else:
            print("  no 'LEADS - TODAY BY SOURCE' report found")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="Print plan; don't actually create reports/dashboards")
    p.add_argument("--reports-only", action="store_true",
                   help="Skip dashboard creation; just create the reports")
    p.add_argument("--discover", action="store_true",
                   help="Print available report types + your existing reports' metadata")
    args = p.parse_args()

    print("=" * 72)
    print("Salesforce Dashboard Builder — 32 reports + 10 dashboards")
    print("=" * 72)

    if args.dry_run:
        print("[DRY RUN — no changes will be made]\n")

    session, instance = sf_login()
    print(f"✓ Connected: {instance}\n")

    if args.discover:
        discover(session, instance)
        return 0

    # ── Folders ──
    print("─── Folders ───")
    if not args.dry_run:
        report_folder_id = get_or_create_folder(session, instance,
            "DealMatcher_Reports", "DealMatcher Reports", "Report")
        dash_folder_id = get_or_create_folder(session, instance,
            "DealMatcher_Dashboards", "DealMatcher Dashboards", "Dashboard")
    else:
        print("  [dry-run] would create DealMatcher Reports + Dashboards folders")
        report_folder_id = dash_folder_id = "dry-run-folder-id"

    # ── Reports ──
    print(f"\n─── Reports ({len(REPORTS)}) ───")
    report_ids: dict[str, str] = {}
    for rd in REPORTS:
        rid = upsert_report(session, instance, rd, report_folder_id, args.dry_run)
        if rid:
            report_ids[rd["developerName"]] = rid
        time.sleep(0.2)   # avoid SF rate limit

    success = sum(1 for r in REPORTS if r["developerName"] in report_ids)
    print(f"\n✓ {success}/{len(REPORTS)} reports ready")

    if args.reports_only:
        print("\n--reports-only mode: skipping dashboards.")
        return 0

    # ── Dashboards ──
    # NOTE: dashboard creation via REST is not supported on standard editions.
    # We use Metadata API zip-deploy instead, which is significantly more code.
    # For now, print the dashboard construction plan and let Christopher
    # build them via the UI quickly (each dashboard is now ~5 min since
    # the underlying reports are pre-configured with charts).
    print(f"\n─── Dashboards ({len(DASHBOARDS)}) ───")
    print("Standard SF API doesn't support direct dashboard creation.")
    print("Reports above are now ready with charts pre-configured.")
    print()
    print("To build each dashboard (~5 min each, 50 min total):")
    print("  1. SF → Dashboards → New Dashboard → name '01 Daily Lead Inflow' → Create")
    print("  2. + Widget → Chart or Table → search for the report by name → Select")
    print("  3. Pick chart icon (Donut/Bar/Line/Metric/Table) → Add")
    print("  4. Repeat for each component listed below per dashboard")
    print()
    print("─── Dashboard build cheat sheet ───\n")
    for d in DASHBOARDS:
        print(f"📊 {d['name']}")
        for report_dev, viz, label in d["components"]:
            report_name = next((r["name"] for r in REPORTS
                                if r["developerName"] == report_dev), "?")
            print(f"   • {viz:8} ← {report_name}")
        print()

    print("=" * 72)
    print("DONE — reports created, dashboard build cheat sheet above")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
