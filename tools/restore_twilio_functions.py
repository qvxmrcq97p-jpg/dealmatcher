#!/usr/bin/env python3
"""
Recovery: rebuild the johnson-buys-sms service from a specific known-good
build SID, with the new sms_v2 swapped in at /sms.

Usage:
    python3 tools/restore_twilio_functions.py [--from-build=ZBxxxx]

Default --from-build is the last-known-good build before the broken deploy.
"""
import sys
import time
import base64
import json
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV_FILE = REPO / ".env.cheaphomesfla"

SERVICE_SID = "ZS99a31d595457ceb712048c13dc3f3b2c"
FUNCTION_SID_SMS = "ZH976945068df59b25c99a48a55880189d"
ENVIRONMENT_SID = "ZE52139c82aa57608f8b3e4b233d1a97d4"
DEFAULT_GOOD_BUILD = "ZBfb7532c154f4c2b1596c0f2b01d9aab6"  # had all 6 functions


def env_load():
    e = {}
    for line in ENV_FILE.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            e[k.strip()] = v.strip()
    return e


def auth_header(env):
    sid = env["TWILIO_ACCOUNT_SID"]
    tok = env["TWILIO_AUTH_TOKEN"]
    return "Basic " + base64.b64encode(f"{sid}:{tok}".encode()).decode()


def get(url, env):
    req = urllib.request.Request(url, headers={"Authorization": auth_header(env)})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def post(url, env, fields):
    """POST x-www-form-urlencoded with optional repeated keys (list of tuples)."""
    body = urllib.parse.urlencode(fields)
    req = urllib.request.Request(
        url,
        data=body.encode(),
        method="POST",
        headers={
            "Authorization": auth_header(env),
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main():
    good_build_sid = DEFAULT_GOOD_BUILD
    new_sms_version_sid = None
    for arg in sys.argv[1:]:
        if arg.startswith("--from-build="):
            good_build_sid = arg.split("=", 1)[1]
        elif arg.startswith("--sms-version="):
            new_sms_version_sid = arg.split("=", 1)[1]

    env = env_load()
    print("\n═══ TWILIO RECOVERY — REBUILD FROM KNOWN-GOOD BUILD ═══\n")
    print(f"Service:        {SERVICE_SID}")
    print(f"From build:     {good_build_sid}")

    # Read the known-good build to get all 6 function/asset versions
    print(f"\n→ Reading source build {good_build_sid}...")
    src = get(f"https://serverless.twilio.com/v1/Services/{SERVICE_SID}/Builds/{good_build_sid}", env)
    fn_vers = src.get("function_versions", [])
    asset_vers = src.get("asset_versions", [])
    deps = src.get("dependencies") or []

    print(f"  found {len(fn_vers)} function version(s):")
    for fv in fn_vers:
        print(f"    - {fv['sid']}  path={fv.get('path')}  visibility={fv.get('visibility')}")
    print(f"  found {len(asset_vers)} asset version(s)")

    # If no --sms-version given, find the most recent version of /sms function
    if not new_sms_version_sid:
        print(f"\n→ Finding most recent version of /sms (function {FUNCTION_SID_SMS})...")
        v = get(
            f"https://serverless.twilio.com/v1/Services/{SERVICE_SID}/Functions/{FUNCTION_SID_SMS}/Versions?PageSize=5",
            env,
        )
        versions = v.get("versions", [])
        if not versions:
            raise SystemExit("  ✗ No /sms versions found at all. Re-run deploy_twilio_sms.py first to upload v2.")
        new_sms_version_sid = versions[0]["sid"]
        print(f"  ✓ Latest /sms version: {new_sms_version_sid} (date: {versions[0].get('date_created')})")

    # Replace /sms version in the function_versions list
    final_versions = []
    sms_replaced = False
    for fv in fn_vers:
        if fv.get("function_sid") == FUNCTION_SID_SMS:
            final_versions.append(new_sms_version_sid)
            sms_replaced = True
            print(f"  · replacing /sms: {fv['sid']} → {new_sms_version_sid}")
        else:
            final_versions.append(fv["sid"])

    if not sms_replaced:
        # The good build didn't have /sms at all — append the new version
        final_versions.append(new_sms_version_sid)
        print(f"  · appending /sms: {new_sms_version_sid}")

    asset_version_sids = [a["sid"] for a in asset_vers]

    # Build the form fields list (repeated keys for arrays)
    fields = []
    fields += [("FunctionVersions", v) for v in final_versions]
    fields += [("AssetVersions", v) for v in asset_version_sids]
    if deps:
        fields.append(("Dependencies", json.dumps(deps)))

    print(f"\n→ Creating new build with {len(final_versions)} fn + {len(asset_version_sids)} asset version(s)...")
    new_build = post(f"https://serverless.twilio.com/v1/Services/{SERVICE_SID}/Builds", env, fields)
    new_build_sid = new_build["sid"]
    print(f"  · Build {new_build_sid} — waiting for completion...")

    # Poll
    for i in range(60):
        time.sleep(2)
        s = get(f"https://serverless.twilio.com/v1/Services/{SERVICE_SID}/Builds/{new_build_sid}/Status", env)
        if s["status"] == "completed":
            print(f"  ✓ Build complete after {2*(i+1)}s")
            break
        elif s["status"] == "failed":
            raise SystemExit(f"  ✗ Build failed: {s}")
    else:
        raise SystemExit("  ✗ Build timed out after 120s")

    # Deploy
    print("\n→ Deploying...")
    dep = post(
        f"https://serverless.twilio.com/v1/Services/{SERVICE_SID}/Environments/{ENVIRONMENT_SID}/Deployments",
        env,
        [("BuildSid", new_build_sid)],
    )
    print(f"  ✓ Deployed: {dep['sid']}")

    print("\n═══ RESTORE COMPLETE ═══")
    print(f"Build:      {new_build_sid}")
    print(f"Deployment: {dep['sid']}")
    print()
    print("All 6 functions should now be live again, with new sms_v2 at /sms.")
    print()


if __name__ == "__main__":
    main()
