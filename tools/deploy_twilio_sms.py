#!/usr/bin/env python3
"""
Deploy Twilio Function sms_v2.js to johnson-buys-sms service via API.
Replaces the manual console-paste process with a fully automated deploy.

Usage:
    python3 tools/deploy_twilio_sms.py
    python3 tools/deploy_twilio_sms.py --dry-run   # show what would happen
"""

import sys
import time
import base64
import json
import os
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV_FILE = REPO / ".env.cheaphomesfla"
SMS_V2 = REPO / "twilio-functions" / "sms_v2.js"

SERVICE_NAME = "johnson-buys-sms"
FUNCTION_PATH = "/sms"
CHRIS_PHONE = "+13055759040"


def load_env():
    """Load Twilio creds from .env.cheaphomesfla"""
    env = {}
    for line in ENV_FILE.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def twilio_request(method, url, env, data=None, files=None):
    """Make a Twilio API request with basic auth."""
    sid = env["TWILIO_ACCOUNT_SID"]
    tok = env["TWILIO_AUTH_TOKEN"]
    auth = base64.b64encode(f"{sid}:{tok}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}"}

    if files:
        # Multipart form upload (for function source)
        boundary = "----TwilioBoundary" + str(int(time.time()))
        body = b""
        for name, value in (data or {}).items():
            body += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        for name, (filename, content, ctype) in files.items():
            body += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\nContent-Type: {ctype}\r\n\r\n'.encode()
            body += content if isinstance(content, bytes) else content.encode()
            body += b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif data is not None:
        body = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    else:
        body = None

    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {e.read().decode()[:300]}")
        raise


def find_service(env):
    """Find the johnson-buys-sms service SID."""
    print(f"→ Looking up Service '{SERVICE_NAME}'...")
    r = twilio_request("GET", "https://serverless.twilio.com/v1/Services?PageSize=100", env)
    for svc in r.get("services", []):
        if svc.get("unique_name") == SERVICE_NAME or svc.get("friendly_name") == SERVICE_NAME:
            print(f"  ✓ Found: {svc['sid']}")
            return svc["sid"]
    raise SystemExit(f"  ✗ Service '{SERVICE_NAME}' not found. Existing services:\n  " +
                     "\n  ".join(f"{s.get('unique_name')} ({s['sid']})" for s in r.get("services", [])))


def find_function(env, service_sid):
    """Find the /sms function SID."""
    print(f"→ Looking up Function '{FUNCTION_PATH}'...")
    r = twilio_request("GET", f"https://serverless.twilio.com/v1/Services/{service_sid}/Functions?PageSize=100", env)
    for fn in r.get("functions", []):
        if fn.get("friendly_name") == "sms" or fn.get("friendly_name") == FUNCTION_PATH.lstrip("/"):
            print(f"  ✓ Found: {fn['sid']}")
            return fn["sid"]
    raise SystemExit(f"  ✗ Function '{FUNCTION_PATH}' not found. Existing functions:\n  " +
                     "\n  ".join(f"{f.get('friendly_name')} ({f['sid']})" for f in r.get("functions", [])))


def get_environment(env, service_sid):
    """Find the default environment SID."""
    print("→ Looking up Environment...")
    r = twilio_request("GET", f"https://serverless.twilio.com/v1/Services/{service_sid}/Environments", env)
    envs = r.get("environments", [])
    if not envs:
        raise SystemExit("  ✗ No environments found.")
    e = envs[0]
    print(f"  ✓ Using: {e['unique_name']} ({e['sid']})")
    return e["sid"], e["build_sid"]


def upload_version(env, service_sid, function_sid, code):
    """Upload new function version."""
    print("→ Uploading new function version...")
    url = f"https://serverless.twilio.com/v1/Services/{service_sid}/Functions/{function_sid}/Versions"
    files = {"Content": ("sms.js", code, "application/javascript")}
    data = {"Path": FUNCTION_PATH, "Visibility": "public"}
    r = twilio_request("POST", url, env, data=data, files=files)
    print(f"  ✓ Version: {r['sid']}")
    return r["sid"]


def ensure_chris_phone(env, service_sid, environment_sid):
    """Set CHRIS_PHONE env var if missing."""
    print("→ Checking environment variables...")
    url = f"https://serverless.twilio.com/v1/Services/{service_sid}/Environments/{environment_sid}/Variables"
    r = twilio_request("GET", url, env)
    existing = {v["key"]: v for v in r.get("variables", [])}
    if "CHRIS_PHONE" in existing:
        print(f"  ✓ CHRIS_PHONE already set: {existing['CHRIS_PHONE']['value']}")
        return
    print(f"  · CHRIS_PHONE missing — adding ({CHRIS_PHONE})")
    twilio_request("POST", url, env, data={"Key": "CHRIS_PHONE", "Value": CHRIS_PHONE})
    print("  ✓ Added CHRIS_PHONE")


def create_build(env, service_sid, version_sid):
    """Create a build with the new version."""
    print("→ Building...")
    url = f"https://serverless.twilio.com/v1/Services/{service_sid}/Builds"
    r = twilio_request("POST", url, env, data={"FunctionVersions": version_sid})
    build_sid = r["sid"]
    print(f"  · Build {build_sid} — waiting for completion...")
    # Poll until status=completed
    status_url = f"{url}/{build_sid}/Status"
    for i in range(60):
        time.sleep(2)
        s = twilio_request("GET", status_url, env)
        if s["status"] == "completed":
            print(f"  ✓ Build complete after {2*(i+1)}s")
            return build_sid
        elif s["status"] == "failed":
            raise SystemExit(f"  ✗ Build failed: {s}")
    raise SystemExit("  ✗ Build timed out after 120s")


def deploy_build(env, service_sid, environment_sid, build_sid):
    """Deploy the build to the environment."""
    print("→ Deploying build...")
    url = f"https://serverless.twilio.com/v1/Services/{service_sid}/Environments/{environment_sid}/Deployments"
    r = twilio_request("POST", url, env, data={"BuildSid": build_sid})
    print(f"  ✓ Deployed: {r['sid']}")
    return r["sid"]


def main():
    dry_run = "--dry-run" in sys.argv

    if not ENV_FILE.exists():
        raise SystemExit(f"✗ Missing {ENV_FILE}")
    if not SMS_V2.exists():
        raise SystemExit(f"✗ Missing {SMS_V2}")

    env = load_env()
    if "TWILIO_ACCOUNT_SID" not in env or "TWILIO_AUTH_TOKEN" not in env:
        raise SystemExit("✗ TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN missing from .env")

    code = SMS_V2.read_text()
    print(f"\n═══ DEPLOYING {SMS_V2.name} → {SERVICE_NAME}{FUNCTION_PATH} ═══")
    print(f"Code size: {len(code)} bytes\n")

    service_sid = find_service(env)
    function_sid = find_function(env, service_sid)
    environment_sid, _ = get_environment(env, service_sid)
    ensure_chris_phone(env, service_sid, environment_sid)

    if dry_run:
        print("\n[DRY RUN — would upload, build, and deploy here]")
        return

    version_sid = upload_version(env, service_sid, function_sid, code)
    build_sid = create_build(env, service_sid, version_sid)
    deployment_sid = deploy_build(env, service_sid, environment_sid, build_sid)

    print(f"\n═══ DEPLOY COMPLETE ═══")
    print(f"Service:    {service_sid}")
    print(f"Function:   {function_sid}")
    print(f"Version:    {version_sid}")
    print(f"Build:      {build_sid}")
    print(f"Deployment: {deployment_sid}")
    print()
    print("Next: text 'STOP' from a phone NOT in your Salesforce")
    print("  - You should get an auto-reply (the v2 opt-out behavior)")
    print("  - Your iPhone should NOT get a forwarded notification")
    print()


if __name__ == "__main__":
    main()
