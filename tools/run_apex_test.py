#!/usr/bin/env python3
"""
run_apex_test.py — trigger an Apex test class to run, poll until done,
report coverage on the target class + org-wide aggregate.

Use case: BatchUpdateTheContactRecordsTest already exists with proper
test methods, but coverage on BatchUpdateTheContactRecords is 0% because
the test hasn't been run recently. Just run it to populate coverage.

Run:
    cd ~/dealmatcher
    python3 tools/run_apex_test.py BatchUpdateTheContactRecordsTest
    # optional second arg: target class to report coverage for
    python3 tools/run_apex_test.py BatchUpdateTheContactRecordsTest BatchUpdateTheContactRecords
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = SCRIPT_DIR / ".env.cheaphomesfla"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 tools/run_apex_test.py <TestClassName> [<TargetClassName>]")
        sys.exit(1)
    test_class = sys.argv[1]
    target_class = sys.argv[2] if len(sys.argv) > 2 else None

    from simple_salesforce import Salesforce
    sf = Salesforce(
        username=os.environ["SF_USERNAME"],
        password=os.environ["SF_PASSWORD"],
        security_token=os.environ["SF_SECURITY_TOKEN"],
    )
    print(f"Connected: {sf.sf_instance}")

    # 1. Get test class Id
    q = sf.toolingexecute(
        f"query/?q=SELECT+Id+FROM+ApexClass+WHERE+Name='{test_class}'"
    )
    if not q.get("records"):
        print(f"❌ Test class '{test_class}' not found")
        sys.exit(1)
    test_id = q["records"][0]["Id"]
    print(f"Test class Id: {test_id}")

    # 2. Trigger async test
    print(f"\nTriggering run of {test_class}...")
    resp = sf.toolingexecute(
        "runTestsAsynchronous/",
        method="POST",
        data={"classids": test_id},
    )
    async_id = resp if isinstance(resp, (str, int)) else resp.get("id") or resp.get("asyncApexJobId")
    if not async_id:
        print(f"❌ Could not parse async id: {resp}")
        sys.exit(1)
    async_id = str(async_id)
    print(f"  ✓ Async test parent Id: {async_id}")

    # 3. Poll AsyncApexJob (the parent job) until ALL its test method jobs complete.
    # The runTestsAsynchronous endpoint returns a "parent" ID. Salesforce creates
    # one child AsyncApexJob per test method. We poll the parent's overall status.
    print("\nPolling status...")
    last_state = None
    for attempt in range(60):
        # Query both the parent and any children
        r = sf.query(
            f"SELECT Id, Status, JobItemsProcessed, NumberOfErrors, "
            f"ExtendedStatus FROM AsyncApexJob "
            f"WHERE Id = '{async_id}' OR ParentJobId = '{async_id}'"
        )
        if not r["records"]:
            time.sleep(2)
            continue
        # Aggregate: all jobs Completed/Failed/Aborted = done
        states = [rec["Status"] for rec in r["records"]]
        all_done = all(s in ("Completed", "Failed", "Aborted") for s in states)
        agg = "/".join(states)
        if agg != last_state:
            print(f"  [{attempt:2d}] states={agg}")
            last_state = agg
        if all_done:
            break
        time.sleep(3)
    else:
        print("❌ Timeout")
        sys.exit(1)

    # Print test method results
    print("\n--- Test results ---")
    tr = sf.toolingexecute(
        f"query/?q=SELECT+MethodName,Outcome,Message,StackTrace+FROM+ApexTestResult"
        f"+WHERE+AsyncApexJobId='{async_id}'"
    )
    for rec in tr.get("records", []):
        marker = "✅" if rec["Outcome"] == "Pass" else "❌"
        print(f"  {marker} {rec['MethodName']} — {rec['Outcome']}")
        if rec.get("Message"):
            print(f"       {rec['Message']}")
        if rec.get("StackTrace"):
            print(f"       {rec['StackTrace'][:200]}")

    # 4. Coverage for the target class
    if target_class:
        print(f"\n--- Coverage for {target_class} ---")
        cov = sf.toolingexecute(
            f"query/?q=SELECT+ApexClassOrTrigger.Name,NumLinesCovered,NumLinesUncovered"
            f"+FROM+ApexCodeCoverage+WHERE+ApexClassOrTrigger.Name='{target_class}'"
        )
        for r in cov.get("records", []):
            covered = r["NumLinesCovered"]
            uncovered = r["NumLinesUncovered"]
            total = covered + uncovered
            pct = (covered / total * 100) if total else 0
            print(f"  {r['ApexClassOrTrigger']['Name']}: {covered}/{total} ({pct:.1f}%)")
            if pct >= 75:
                print(f"  ✅ Above 75% threshold — metadata deploys unblocked for this class")

    # 5. Org-wide aggregate (what the deploy gate looks at)
    print("\n--- Org-wide aggregate coverage ---")
    agg_q = sf.toolingexecute("query/?q=SELECT+PercentCovered+FROM+ApexOrgWideCoverage")
    for r in agg_q.get("records", []):
        pct = r["PercentCovered"]
        print(f"  Org-wide: {pct}%")
        if pct >= 75:
            print("  ✅ Org-wide ≥ 75% — production metadata deploys should pass test-coverage gate")
        else:
            print(f"  ⚠ Org-wide < 75% — production deploys still blocked. Need {75 - pct}% more coverage.")


if __name__ == "__main__":
    main()
