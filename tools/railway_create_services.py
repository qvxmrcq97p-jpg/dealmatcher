#!/usr/bin/env python3
"""
railway_create_services.py — create the 7 remaining cron services in Railway
─────────────────────────────────────────────────────────────────────────────
You already created the `scraper` service via the UI. This script creates
the other 7 (jb_email, jb_sms, jb_followup, jb_digest, watchdog,
cloud_health, daily_kpi) via Railway's GraphQL API in one shot.

Setup (one-time, ~2 min):

  1. Get a Railway API token:
     https://railway.app/account/tokens → Create New Token → copy it
  2. Add to your shell:
     export RAILWAY_API_TOKEN='paste-token-here'
     export RAILWAY_PROJECT_ID='856c877c-5b0d-4bf4-97ae-160e75408121'
     (Project ID is in your Railway URL: /project/<ID>/...)

Run:
     cd ~/dealmatcher
     python3 tools/railway_create_services.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import urllib.error
from typing import Optional

# ─── Service definitions ─────────────────────────────────────────────
GITHUB_REPO = "qvxmrcq97p-jpg/dealmatcher"   # same repo as scraper service
GITHUB_BRANCH = "main"

SERVICES = [
    {"name": "jb_email",      "start": "python jb/email_campaign.py",        "cron": "0 12 * * 1-6"},
    {"name": "jb_sms",        "start": "python jb/sms_campaign.py",          "cron": "15 12 * * 1-6"},
    {"name": "jb_followup",   "start": "python jb/followup.py",              "cron": "0 12 * * *"},
    {"name": "jb_digest",     "start": "python jb/digest.py",                "cron": "30 12 * * *"},
    {"name": "watchdog",      "start": "python tools/system_watchdog.py",    "cron": "0 13 * * *"},
    {"name": "cloud_health",  "start": "python tools/cloud_health_check.py", "cron": "0 13-1 * * 1-6"},
    {"name": "daily_kpi",     "start": "python tools/daily_kpi_email.py",    "cron": "15 13 * * 1-6"},
]

API_URL = "https://backboard.railway.com/graphql/v2"


# ─── HTTP / GraphQL helpers ──────────────────────────────────────────
def gql(token: str, query: str, variables: dict) -> dict:
    payload = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            # Cloudflare blocks bare urllib User-Agent — pretend to be Chrome
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/123.0.0.0 Safari/537.36",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        sys.exit(f"✗ HTTP {e.code}: {body[:500]}")
    except Exception as e:  # noqa: BLE001
        sys.exit(f"✗ Network error: {e}")

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        sys.exit(f"✗ Bad JSON: {body[:500]}")

    if "errors" in data:
        sys.exit(f"✗ GraphQL errors: {json.dumps(data['errors'], indent=2)}")

    return data["data"]


# ─── Required env ────────────────────────────────────────────────────
def require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        sys.exit(f"✗ Missing env var: {name}\n"
                 f"  Set with: export {name}='value'")
    return v


# ─── Lookup environment id for the project ──────────────────────────
def get_environment_id(token: str, project_id: str) -> str:
    q = """
    query getProject($id: String!) {
      project(id: $id) {
        id
        name
        environments {
          edges { node { id name } }
        }
      }
    }
    """
    data = gql(token, q, {"id": project_id})
    project = data.get("project")
    if not project:
        sys.exit(f"✗ Project {project_id} not found or token doesn't have access")
    print(f"✓ Project: {project['name']}")
    envs = [e["node"] for e in project["environments"]["edges"]]
    prod = next((e for e in envs if e["name"] == "production"), None)
    if not prod:
        sys.exit(f"✗ No 'production' environment found. Got: {[e['name'] for e in envs]}")
    print(f"✓ Production environment: {prod['id']}")
    return prod["id"]


# ─── Create a service from GitHub repo ──────────────────────────────
def create_service(token: str, project_id: str, env_id: str,
                   name: str, start_cmd: str, cron: str) -> Optional[str]:
    """Returns the new service's id, or None on failure."""
    # Step 1 — create service connected to GitHub repo
    create_q = """
    mutation serviceCreate($input: ServiceCreateInput!) {
      serviceCreate(input: $input) {
        id
        name
      }
    }
    """
    create_vars = {
        "input": {
            "projectId": project_id,
            "name": name,
            "source": {"repo": GITHUB_REPO},
            "branch": GITHUB_BRANCH,
        }
    }
    data = gql(token, create_q, create_vars)
    svc = data.get("serviceCreate")
    if not svc:
        print(f"  ✗ Service create failed for {name}")
        return None
    service_id = svc["id"]
    print(f"  ✓ Created service: {name} (id={service_id[:8]}...)")

    # Step 2 — set start command + cron via serviceInstanceUpdate
    time.sleep(2)   # let Railway settle
    update_q = """
    mutation serviceInstanceUpdate(
      $serviceId: String!,
      $environmentId: String!,
      $input: ServiceInstanceUpdateInput!
    ) {
      serviceInstanceUpdate(
        serviceId: $serviceId,
        environmentId: $environmentId,
        input: $input
      )
    }
    """
    update_vars = {
        "serviceId": service_id,
        "environmentId": env_id,
        "input": {
            "startCommand": start_cmd,
            "cronSchedule": cron,
        },
    }
    gql(token, update_q, update_vars)
    print(f"  ✓ Configured: start='{start_cmd}', cron='{cron}'")
    return service_id


# ─── Main ────────────────────────────────────────────────────────────
def main() -> int:
    token = require_env("RAILWAY_API_TOKEN")
    project_id = require_env("RAILWAY_PROJECT_ID")

    print("=" * 64)
    print("Railway — create 7 cron services")
    print("=" * 64)
    env_id = get_environment_id(token, project_id)
    print()

    success = 0
    for s in SERVICES:
        print(f"─── {s['name']} ───")
        sid = create_service(token, project_id, env_id,
                             s["name"], s["start"], s["cron"])
        if sid:
            success += 1
        print()
        time.sleep(1.5)   # avoid rate limits

    print("=" * 64)
    print(f"✓ {success}/{len(SERVICES)} services created")
    print("=" * 64)
    if success < len(SERVICES):
        print("Failed services need manual creation via the UI.")
        return 1
    print("\nNext: open Railway → trigger each service once to smoke-test.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
