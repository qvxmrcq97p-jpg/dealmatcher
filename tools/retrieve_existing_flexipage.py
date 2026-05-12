#!/usr/bin/env python3
"""
retrieve_existing_flexipage.py — retrieve the current Getting_Started_Home
FlexiPage from Salesforce so we can see the exact template name + structure
that works in this org. Writes to salesforce/existing_flexipage.xml for
inspection.

Run:
    cd ~/dealmatcher
    python3 tools/retrieve_existing_flexipage.py
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
API_VERSION = "60.0"


def load_env():
    for line in ENV_FILE.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main():
    load_env()
    from simple_salesforce import Salesforce
    sf = Salesforce(
        username=os.environ["SF_USERNAME"],
        password=os.environ["SF_PASSWORD"],
        security_token=os.environ["SF_SECURITY_TOKEN"],
    )
    instance = sf.sf_instance.replace("https://", "").replace("/", "")
    soap_url = f"https://{instance}/services/Soap/m/{API_VERSION}"

    print(f"Retrieving FlexiPage Getting_Started_Home from {instance}...")

    retrieve_envelope = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:met="http://soap.sforce.com/2006/04/metadata">
  <soapenv:Header>
    <met:SessionHeader><met:sessionId>{sf.session_id}</met:sessionId></met:SessionHeader>
  </soapenv:Header>
  <soapenv:Body>
    <met:retrieve>
      <met:retrieveRequest>
        <met:apiVersion>{API_VERSION}</met:apiVersion>
        <met:singlePackage>true</met:singlePackage>
        <met:unpackaged>
          <met:types>
            <met:members>Getting_Started_Home</met:members>
            <met:name>FlexiPage</met:name>
          </met:types>
          <met:version>{API_VERSION}</met:version>
        </met:unpackaged>
      </met:retrieveRequest>
    </met:retrieve>
  </soapenv:Body>
</soapenv:Envelope>"""

    resp = requests.post(
        soap_url,
        headers={"Content-Type": "text/xml; charset=UTF-8", "SOAPAction": "retrieve"},
        data=retrieve_envelope.encode("utf-8"),
        timeout=60,
    )
    if resp.status_code != 200:
        print(f"  ❌ HTTP {resp.status_code}")
        print(resp.text[:3000])
        return 1

    m = re.search(r"<id>([^<]+)</id>", resp.text)
    async_id = m.group(1)
    print(f"  ✓ Submitted retrieve (async ID: {async_id})")

    for attempt in range(30):
        poll_envelope = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:met="http://soap.sforce.com/2006/04/metadata">
  <soapenv:Header>
    <met:SessionHeader><met:sessionId>{sf.session_id}</met:sessionId></met:SessionHeader>
  </soapenv:Header>
  <soapenv:Body>
    <met:checkRetrieveStatus>
      <met:asyncProcessId>{async_id}</met:asyncProcessId>
      <met:includeZip>true</met:includeZip>
    </met:checkRetrieveStatus>
  </soapenv:Body>
</soapenv:Envelope>"""
        r = requests.post(
            soap_url,
            headers={"Content-Type": "text/xml; charset=UTF-8", "SOAPAction": "checkRetrieveStatus"},
            data=poll_envelope.encode("utf-8"),
            timeout=30,
        )
        if "<done>true</done>" in r.text:
            zip_m = re.search(r"<zipFile>([^<]+)</zipFile>", r.text)
            if zip_m:
                zip_bytes = base64.b64decode(zip_m.group(1))
                raw_zip_path = SCRIPT_DIR / "salesforce" / "retrieved.zip"
                raw_zip_path.write_bytes(zip_bytes)
                print(f"\n  ✓ Wrote raw zip to {raw_zip_path.relative_to(SCRIPT_DIR)}")
                import zipfile, io
                with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                    names = zf.namelist()
                    print(f"\n  Files in zip ({len(names)}):")
                    for name in names:
                        print(f"    - {name}")
                    # Find ANY xml that mentions a flexipage and dump first match
                    for name in names:
                        if name.endswith(".xml"):
                            content = zf.read(name).decode("utf-8")
                            out_path = SCRIPT_DIR / "salesforce" / f"retrieved_{name.replace('/', '_')}"
                            out_path.write_text(content)
                            print(f"  ✓ Wrote {out_path.relative_to(SCRIPT_DIR)}")
                            if "FlexiPage" in content or "flexipage" in content.lower():
                                print(f"\n--- {name} ---")
                                print(content[:3000])
                                print("...")
                return 0
            else:
                print(f"  ❌ No zipFile in response")
                print(r.text[:3000])
                return 1
        time.sleep(2)

    print("  ❌ Timeout")
    return 1


if __name__ == "__main__":
    sys.exit(main())
