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
    """Find the /sms function SID by matching deployed path on the active build."""
    print(f"→ Looking up Function '{FUNCTION_PATH}'...")

    # Functions API returns metadata only — friendly_name often = "Untitled_N".
    # The actual path lives on each function's Versions. Cross-reference each
    # function's most recent version to its path.
    funcs = twilio_request(
        "GET",
        f"https://serverless.twilio.com/v1/Services/{service_sid}/Functions?PageSize=100",
        env,
    ).get("functions", [])

    matches = []
    for fn in funcs:
        # Get the most recent version's path
        vers = twilio_request(
            "GET",
            f"https://serverless.twilio.com/v1/Services/{service_sid}/Functions/{fn['sid']}/Versions?PageSize=1",
            env,
        ).get("versions", [])
        if vers:
            path = vers[0].get("path", "")
            if path == FUNCTION_PATH or path == FUNCTION_PATH.lstrip("/"):
                matches.append((fn, path))

    if len(matches) == 1:
        fn, path = matches[0]
        print(f"  ✓ Found '{path}' → {fn['sid']} (friendly_name: {fn.get('friendly_name')})")
        return fn["sid"]

    if len(matches) > 1:
        print(f"  ! Multiple functions map to {FUNCTION_PATH}:")
        for fn, path in matches:
            print(f"    - {fn['sid']} ({fn.get('friendly_name')})")
        # Pick the most recently updated
        matches.sort(key=lambda m: m[0].get("date_updated", ""), reverse=True)
        fn = matches[0][0]
        print(f"  → Using most recently updated: {fn['sid']}")
        return fn["sid"]

    # No match in Functions/Versions — check the active build's function_versions
    # (deployed paths can differ from per-function latest versions if a build
    # pinned an older version of a function).
    print(f"  · No match via per-function Versions. Checking active deployment...")

    envs = twilio_request(
        "GET", f"https://serverless.twilio.com/v1/Services/{service_sid}/Environments", env
    ).get("environments", [])
    if envs and envs[0].get("build_sid"):
        build_sid = envs[0]["build_sid"]
        build = twilio_request(
            "GET", f"https://serverless.twilio.com/v1/Services/{service_sid}/Builds/{build_sid}", env
        )
        fvs = build.get("function_versions", [])
        print(f"  · Active build {build_sid} has {len(fvs)} function version(s):")
        for fv in fvs:
            print(f"      - function_sid={fv.get('function_sid')}  path={fv.get('path')}  visibility={fv.get('visibility')}")
            if fv.get("path") == FUNCTION_PATH:
                print(f"  ✓ Match: {fv.get('function_sid')}")
                return fv["function_sid"]

    # Last resort — list everything for debugging
    print(f"  ✗ No function has path '{FUNCTION_PATH}' anywhere.")
    print(f"  Functions exist but all are empty placeholders. Likely the SMS")
    print(f"  webhook is wired to a Studio Flow or a different service.")
    print(f"")
    print(f"  Check in Twilio Console:")
    print(f"    Phone Numbers → Manage → +1 (954) 953-4554 → Messaging section")
    print(f"  See where 'A MESSAGE COMES IN' actually points.")
    raise SystemExit(f"  Aborting.")


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
    """Upload new function version. Uses the dedicated serverless-upload subdomain."""
    print("→ Uploading new function version...")
    # Code uploads go to serverless-upload.twilio.com, not serverless.twilio.com
    url = f"https://serverless-upload.twilio.com/v1/Services/{service_sid}/Functions/{function_sid}/Versions"
    files = {"Content": ("sms.js", code, "application/javascript")}
    data = {"Path": FUNCTION_PATH, "Visibility": "protected"}
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


def create_build(env, service_sid, version_sid, function_sid):
    """Create a build with the new version + ALL other current functions/assets preserved.

    A Twilio Build is a snapshot — if you only pass FunctionVersions=<one>, all
    other functions get DROPPED from production. We must include every other
    function's current version SID and replace only the one we changed.
    """
    print("→ Building (preserving other functions)...")

    # Get the currently-deployed build's function + asset versions
    envs = twilio_request(
        "GET", f"https://serverless.twilio.com/v1/Services/{service_sid}/Environments", env
    ).get("environments", [])
    if not envs or not envs[0].get("build_sid"):
        raise SystemExit("  ✗ No current build to preserve from")
    cur_build_sid = envs[0]["build_sid"]
    cur = twilio_request(
        "GET", f"https://serverless.twilio.com/v1/Services/{service_sid}/Builds/{cur_build_sid}", env
    )

    # Function versions: keep all except the one matching our function_sid
    fn_versions = []
    for fv in cur.get("function_versions", []):
        if fv.get("function_sid") == function_sid:
            print(f"  · replacing /{fv.get('path')} version: {fv['sid']} → {version_sid}")
            fn_versions.append(version_sid)
        else:
            fn_versions.append(fv["sid"])
    # If the function wasn't in the old build (new function), add the new version
    if version_sid not in fn_versions:
        fn_versions.append(version_sid)

    # Asset versions: keep all unchanged
    asset_versions = [av["sid"] for av in cur.get("asset_versions", [])]

    print(f"  · build will include {len(fn_versions)} function version(s) + {len(asset_versions)} asset version(s)")

    # Twilio API accepts repeated form params for list values
    body_parts = [("FunctionVersions", v) for v in fn_versions]
    body_parts += [("AssetVersions", v) for v in asset_versions]
    if cur.get("dependencies"):
        body_parts.append(("Dependencies", json.dumps(cur["dependencies"])))
    body = urllib.parse.urlencode(body_parts)

    sid = env["TWILIO_ACCOUNT_SID"]
    tok = env["TWILIO_AUTH_TOKEN"]
    auth = base64.b64encode(f"{sid}:{tok}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    url = f"https://serverless.twilio.com/v1/Services/{service_sid}/Builds"
    req = urllib.request.Request(url, data=body.encode(), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"  ✗ Build POST failed: HTTP {e.code} — {e.read().decode()[:300]}")

    build_sid = result["sid"]
    print(f"  · Build {build_sid} — waiting for completion...")
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
    build_sid = create_build(env, service_sid, version_sid, function_sid)
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
