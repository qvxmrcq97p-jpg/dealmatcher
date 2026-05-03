#!/usr/bin/env python3
"""Finish what railway_create_services.py started.
Fixes cloud_health cron + creates daily_kpi.
Run with same env vars as the create script."""

from __future__ import annotations
import json, os, sys, time, urllib.request

GITHUB_REPO   = "qvxmrcq97p-jpg/dealmatcher"
GITHUB_BRANCH = "main"
API_URL       = "https://backboard.railway.com/graphql/v2"
HEADERS_BASE  = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/123.0.0.0 Safari/537.36"),
}


def gql(token, query, variables):
    payload = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        API_URL, data=payload,
        headers={**HEADERS_BASE, "Authorization": f"Bearer {token}"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        sys.exit(f"✗ {e}")
    if "errors" in data:
        sys.exit(f"✗ {json.dumps(data['errors'], indent=2)}")
    return data["data"]


def main():
    token = os.environ["RAILWAY_API_TOKEN"]
    project_id = os.environ["RAILWAY_PROJECT_ID"]

    # Find env id + cloud_health service id
    print("Finding project + services...")
    q = """
    query($id: String!) {
      project(id: $id) {
        environments { edges { node { id name } } }
        services { edges { node { id name } } }
      }
    }"""
    data = gql(token, q, {"id": project_id})
    project = data["project"]
    env_id = next(e["node"]["id"] for e in project["environments"]["edges"]
                  if e["node"]["name"] == "production")
    services = {e["node"]["name"]: e["node"]["id"] for e in project["services"]["edges"]}
    print(f"✓ environment: {env_id}")
    print(f"✓ existing services: {list(services.keys())}")

    update_q = """
    mutation($s: String!, $e: String!, $i: ServiceInstanceUpdateInput!) {
      serviceInstanceUpdate(serviceId: $s, environmentId: $e, input: $i)
    }"""

    # Fix cloud_health cron (it was created but cron rejected)
    if "cloud_health" in services:
        print("\n─── fixing cloud_health cron ───")
        new_cron = "0 13,14,15,16,17,18,19,20,21,22,23,0,1 * * 1-6"
        gql(token, update_q, {
            "s": services["cloud_health"], "e": env_id,
            "i": {"startCommand": "python tools/cloud_health_check.py",
                  "cronSchedule": new_cron}
        })
        print(f"  ✓ cron set: {new_cron}")
    else:
        print("\n⚠️  cloud_health service missing — skipping fix")

    # Create daily_kpi
    if "daily_kpi" in services:
        print("\n· daily_kpi already exists, skipping create")
    else:
        print("\n─── creating daily_kpi ───")
        create_q = """
        mutation($input: ServiceCreateInput!) {
          serviceCreate(input: $input) { id name }
        }"""
        d = gql(token, create_q, {
            "input": {"projectId": project_id, "name": "daily_kpi",
                      "source": {"repo": GITHUB_REPO}, "branch": GITHUB_BRANCH}
        })
        sid = d["serviceCreate"]["id"]
        print(f"  ✓ created (id={sid[:8]}...)")
        time.sleep(2)
        gql(token, update_q, {
            "s": sid, "e": env_id,
            "i": {"startCommand": "python tools/daily_kpi_email.py",
                  "cronSchedule": "15 13 * * 1-6"}
        })
        print("  ✓ configured: cron='15 13 * * 1-6'")

    print("\n✓ DONE — verify in Railway UI: 8 services total (scraper + 7 crons)")


if __name__ == "__main__":
    main()
