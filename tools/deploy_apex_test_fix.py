#!/usr/bin/env python3
"""
deploy_apex_test_fix.py — fix the existing
BatchUpdateTheContactRecordsTest class so the insert doesn't fail
on REQUIRED_FIELD_MISSING for Lead.Property_Address__c.

Tooling API is blocked on production ("Can't alter metadata in an
active org") so we go via Metadata API SOAP deploy with
testLevel=RunSpecifiedTests pointing at the test class itself.

Run:
    cd ~/dealmatcher
    python3 tools/deploy_apex_test_fix.py
"""
from __future__ import annotations

import base64
import io
import os
import re
import sys
import time
import zipfile
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = SCRIPT_DIR / ".env.cheaphomesfla"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

API_VERSION = "60.0"


# Fixed test class — populates Property_Address__c so insert succeeds.
TEST_CLASS_BODY = """@isTest
private class BatchUpdateTheContactRecordsTest {
    @isTest
    static void testBatchLifecycle() {
        // Create test leads. Property_Address__c is required in this org,
        // so populate it on every insert.
        List<Lead> lstLead = new List<Lead>();
        for (Integer i = 0; i < 100; i++) {
            Lead l = new Lead(
                LastName = 'Apex Test ' + i,
                Company = 'TestCo ' + i,
                Property_Address__c = i + ' Test St, Miami, FL 33101',
                Status = 'New'
            );
            lstLead.add(l);
        }
        insert lstLead;

        Test.startTest();
        BatchUpdateTheContactRecords b = new BatchUpdateTheContactRecords();
        Database.executeBatch(b, 200);
        Test.stopTest();

        // Sanity: the 100 we inserted should still be queryable
        Integer count = [SELECT COUNT() FROM Lead WHERE LastName LIKE 'Apex Test%'];
        System.assertEquals(100, count, 'All 100 test leads should still exist after batch');
    }
}
"""


TEST_META_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<ApexClass xmlns="http://soap.sforce.com/2006/04/metadata">
    <apiVersion>{API_VERSION}</apiVersion>
    <status>Active</status>
</ApexClass>
"""


PACKAGE_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<Package xmlns="http://soap.sforce.com/2006/04/metadata">
    <types>
        <members>BatchUpdateTheContactRecordsTest</members>
        <name>ApexClass</name>
    </types>
    <version>{API_VERSION}</version>
</Package>
"""


def build_zip_in_memory():
    """Build the deploy zip without writing files to disk first."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("package.xml", PACKAGE_XML)
        z.writestr("classes/BatchUpdateTheContactRecordsTest.cls", TEST_CLASS_BODY)
        z.writestr("classes/BatchUpdateTheContactRecordsTest.cls-meta.xml", TEST_META_XML)
    return buf.getvalue()


def main():
    from simple_salesforce import Salesforce

    print("Connecting to Salesforce...")
    sf = Salesforce(
        username=os.environ["SF_USERNAME"],
        password=os.environ["SF_PASSWORD"],
        security_token=os.environ["SF_SECURITY_TOKEN"],
    )
    instance = sf.sf_instance.replace("https://", "").rstrip("/")
    soap_url = f"https://{instance}/services/Soap/m/{API_VERSION}"
    print(f"  ✓ {instance}")

    print("Building deploy zip in memory...")
    zip_bytes = build_zip_in_memory()
    zip_b64 = base64.b64encode(zip_bytes).decode("ascii")
    print(f"  ✓ {len(zip_bytes)} bytes")

    # Deploy with RunSpecifiedTests pointing at ourselves
    envelope = f"""<?xml version="1.0" encoding="UTF-8"?>
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
        <met:runTests>BatchUpdateTheContactRecordsTest</met:runTests>
        <met:singlePackage>true</met:singlePackage>
        <met:testLevel>RunSpecifiedTests</met:testLevel>
      </met:DeployOptions>
    </met:deploy>
  </soapenv:Body>
</soapenv:Envelope>"""

    print("\nSubmitting deploy with RunSpecifiedTests=BatchUpdateTheContactRecordsTest...")
    r = requests.post(
        soap_url,
        headers={"Content-Type": "text/xml; charset=UTF-8", "SOAPAction": "deploy"},
        data=envelope.encode("utf-8"),
        timeout=60,
    )
    if r.status_code != 200:
        print(f"  ❌ HTTP {r.status_code}")
        print(r.text[:3000])
        sys.exit(1)

    m = re.search(r"<id>([^<]+)</id>", r.text)
    if not m:
        print(f"  ❌ No async id: {r.text[:1500]}")
        sys.exit(1)
    async_id = m.group(1)
    print(f"  ✓ Async Id: {async_id}")

    last_state = None
    print("\nPolling status...")
    for attempt in range(60):
        poll = f"""<?xml version="1.0" encoding="UTF-8"?>
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
        pr = requests.post(
            soap_url,
            headers={"Content-Type": "text/xml; charset=UTF-8", "SOAPAction": "checkDeployStatus"},
            data=poll.encode("utf-8"),
            timeout=30,
        )
        sm = re.search(r"<status>([^<]+)</status>", pr.text)
        state = sm.group(1) if sm else "Unknown"
        if state != last_state:
            print(f"  [{attempt:2d}] state={state}")
            last_state = state
        if "<done>true</done>" in pr.text:
            if "<status>Succeeded</status>" in pr.text:
                print("\n  ✅ DEPLOY SUCCEEDED")
                # Extract coverage info from response
                runtest_m = re.search(r"<runTestResult>(.*?)</runTestResult>", pr.text, re.DOTALL)
                if runtest_m:
                    block = runtest_m.group(1)
                    succ = re.search(r"<numTestsRun>([^<]+)</numTestsRun>", block)
                    fail = re.search(r"<numFailures>([^<]+)</numFailures>", block)
                    print(f"  Tests run: {succ.group(1) if succ else '?'}, failures: {fail.group(1) if fail else '?'}")
                return 0
            else:
                print(f"\n  ❌ DEPLOY FAILED (status={state})")
                failures = re.findall(r"<componentFailures>(.*?)</componentFailures>", pr.text, re.DOTALL)
                test_failures = re.findall(r"<failures>(.*?)</failures>", pr.text, re.DOTALL)
                if failures:
                    print(f"  Component failures ({len(failures)}):")
                    for i, f in enumerate(failures[:5], 1):
                        prob = re.search(r"<problem>([^<]+)</problem>", f)
                        fn = re.search(r"<fileName>([^<]+)</fileName>", f)
                        print(f"    {i}. {fn.group(1) if fn else '?'}: {prob.group(1) if prob else '?'}")
                if test_failures:
                    print(f"  Test failures ({len(test_failures)}):")
                    for i, f in enumerate(test_failures[:5], 1):
                        msg = re.search(r"<message>([^<]+)</message>", f)
                        mn = re.search(r"<methodName>([^<]+)</methodName>", f)
                        print(f"    {i}. {mn.group(1) if mn else '?'}: {msg.group(1) if msg else '?'}")
                if not failures and not test_failures:
                    print("  (no detailed failures in response)")
                    print(pr.text[:3000])
                return 1
        time.sleep(3)
    print("  ❌ Timeout")
    return 1


if __name__ == "__main__":
    sys.exit(main())
