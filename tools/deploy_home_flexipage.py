#!/usr/bin/env python3
"""
deploy_home_flexipage.py — deploy salesforce/home_page_deploy.zip
via the Salesforce Metadata API SOAP endpoint. Replaces the
Workbench manual upload flow.

Run:
    cd ~/dealmatcher
    python3 tools/deploy_home_flexipage.py

Output:
  - Submits the zip as a deploy
  - Polls every 3s until done (typical 15-60s)
  - On success: prints "✅ DEPLOY SUCCEEDED"
  - On failure: prints the Salesforce error detail so you can patch
    the FlexiPage XML and re-deploy.
"""
from __future__ import annotations

import base64
import os
import re
import sys
import time
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = SCRIPT_DIR / ".env.cheaphomesfla"
ZIP_PATH = SCRIPT_DIR / "salesforce" / "home_page_deploy.zip"
API_VERSION = "60.0"


def load_env():
    if not ENV_FILE.exists():
        print(f"ERROR: {ENV_FILE} not found")
        sys.exit(1)
    for line in ENV_FILE.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main():
    load_env()

    if not ZIP_PATH.exists():
        print(f"ERROR: {ZIP_PATH} not found")
        print("Run tools/fetch_home_dashboards.py first to build the zip.")
        sys.exit(1)

    try:
        from simple_salesforce import Salesforce
    except ImportError:
        print("ERROR: simple_salesforce not installed.")
        print("  python3 -m pip install --break-system-packages simple-salesforce")
        sys.exit(1)

    print("Connecting to Salesforce...")
    sf = Salesforce(
        username=os.environ["SF_USERNAME"],
        password=os.environ["SF_PASSWORD"],
        security_token=os.environ["SF_SECURITY_TOKEN"],
    )
    instance = sf.sf_instance.replace("https://", "").replace("/", "")
    soap_url = f"https://{instance}/services/Soap/m/{API_VERSION}"
    print(f"  ✓ Instance: {instance}")
    print(f"  ✓ Endpoint: {soap_url}")

    print(f"Reading {ZIP_PATH.name} ({ZIP_PATH.stat().st_size} bytes)...")
    zip_b64 = base64.b64encode(ZIP_PATH.read_bytes()).decode("ascii")

    deploy_envelope = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:met="http://soap.sforce.com/2006/04/metadata">
  <soapenv:Header>
    <met:SessionHeader><met:sessionId>{sf.session_id}</met:sessionId></met:SessionHeader>
  </soapenv:Header>
  <soapenv:Body>
    <met:deploy>
      <met:ZipFile>{zip_b64}</met:ZipFile>
      <met:DeployOptions>
        <met:allowMissingFiles>false</met:allowMissingFiles>
        <met:autoUpdatePackage>false</met:autoUpdatePackage>
        <met:checkOnly>false</met:checkOnly>
        <met:ignoreWarnings>false</met:ignoreWarnings>
        <met:performRetrieve>false</met:performRetrieve>
        <met:purgeOnDelete>false</met:purgeOnDelete>
        <met:rollbackOnError>true</met:rollbackOnError>
        <met:singlePackage>true</met:singlePackage>
        <met:testLevel>RunLocalTests</met:testLevel>
      </met:DeployOptions>
    </met:deploy>
  </soapenv:Body>
</soapenv:Envelope>"""

    print("Submitting deploy...")
    resp = requests.post(
        soap_url,
        headers={
            "Content-Type": "text/xml; charset=UTF-8",
            "SOAPAction": "deploy",
        },
        data=deploy_envelope.encode("utf-8"),
        timeout=60,
    )
    if resp.status_code != 200:
        print(f"  ❌ HTTP {resp.status_code}")
        print(resp.text[:3000])
        sys.exit(1)

    m = re.search(r"<id>([^<]+)</id>", resp.text)
    if not m:
        print("  ❌ Could not parse async ID from response:")
        print(resp.text[:3000])
        sys.exit(1)
    async_id = m.group(1)
    print(f"  ✓ Submitted. Async ID: {async_id}")

    print("Polling status...")
    last_state = None
    for attempt in range(80):
        poll_envelope = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:met="http://soap.sforce.com/2006/04/metadata">
  <soapenv:Header>
    <met:SessionHeader><met:sessionId>{sf.session_id}</met:sessionId></met:SessionHeader>
  </soapenv:Header>
  <soapenv:Body>
    <met:checkDeployStatus>
      <met:asyncProcessId>{async_id}</met:asyncProcessId>
      <met:includeDetails>true</met:includeDetails>
    </met:checkDeployStatus>
  </soapenv:Body>
</soapenv:Envelope>"""
        r = requests.post(
            soap_url,
            headers={
                "Content-Type": "text/xml; charset=UTF-8",
                "SOAPAction": "checkDeployStatus",
            },
            data=poll_envelope.encode("utf-8"),
            timeout=30,
        )
        state_m = re.search(r"<status>([^<]+)</status>", r.text)
        state = state_m.group(1) if state_m else "Unknown"
        if state != last_state:
            print(f"  [{attempt:2d}] status={state}")
            last_state = state

        if "<done>true</done>" in r.text:
            print("")
            # Use <status>Succeeded/Failed</status> as ground truth, NOT
            # <success>true</success> (that field also appears nested inside
            # <runTestsResult> and gives false positives).
            if "<status>Succeeded</status>" in r.text:
                print("  ✅ DEPLOY SUCCEEDED")
                print("")
                print("Refresh: https://johnsonshomes2.lightning.force.com/lightning/page/home")
                return 0
            else:
                print(f"  ❌ DEPLOY FAILED (status={state})")
                print("")
                # Print component failure details
                failures = re.findall(
                    r"<componentFailures>(.*?)</componentFailures>",
                    r.text,
                    re.DOTALL,
                )
                if failures:
                    print(f"Found {len(failures)} component failure(s):")
                    for i, f in enumerate(failures[:10], 1):
                        problem = re.search(r"<problem>([^<]+)</problem>", f)
                        ftype = re.search(r"<problemType>([^<]+)</problemType>", f)
                        file_name = re.search(r"<fileName>([^<]+)</fileName>", f)
                        line_no = re.search(r"<lineNumber>([^<]+)</lineNumber>", f)
                        col = re.search(r"<columnNumber>([^<]+)</columnNumber>", f)
                        print(f"  {i}. file={file_name.group(1) if file_name else '?'} "
                              f"line={line_no.group(1) if line_no else '?'}:{col.group(1) if col else '?'}")
                        print(f"     type={ftype.group(1) if ftype else '?'}")
                        print(f"     problem={problem.group(1) if problem else '?'}")
                else:
                    err_msg = re.search(r"<errorMessage>([^<]+)</errorMessage>", r.text)
                    if err_msg:
                        print(f"  Error: {err_msg.group(1)}")
                    else:
                        print("  (no component failures parsed — raw response below)")
                        print(r.text[:5000])
                return 1

        time.sleep(3)

    print("  ❌ Timeout — deploy still running after 4 min. Check Workbench manually.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
