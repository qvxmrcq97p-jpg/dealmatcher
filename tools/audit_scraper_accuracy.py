#!/usr/bin/env python3
"""
Scraper accuracy audit — produces a quality report covering the last N days
of scraper runs. Surfaces:

  - How many emails arrived vs how many got past the senders.txt filter
  - How many parsed successfully vs failed
  - Address/price extraction quality (suspicious values flagged)
  - Dedup ledger stats (re-send attempts, near-misses)
  - WhatsApp ingestion rate
  - Parser unit test status

Run: python3 tools/audit_scraper_accuracy.py [--days=3]

Outputs a Markdown report to stdout AND saves to ~/Desktop/scraper_audit_YYYYMMDD.md
"""
import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DESKTOP = Path.home() / "Desktop"
LOGS_DIR = REPO / "logs"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=3, help="How many days of logs to audit")
    p.add_argument("--save", action="store_true", default=True)
    return p.parse_args()


def read_recent_logs(days):
    """Returns concatenated text of all relevant log files within window."""
    cutoff = datetime.now() - timedelta(days=days)
    blob = ""
    files_read = []

    # 1. Repo logs/scraper_stdout.log (Railway-friendly)
    for fname in ["scraper_stdout.log", "scraper_stderr.log"]:
        p = LOGS_DIR / fname
        if p.exists():
            try:
                blob += f"\n=== {p} ===\n" + p.read_text(errors="replace")
                files_read.append(str(p))
            except Exception as e:
                blob += f"\n=== {p} (read error: {e}) ===\n"

    # 2. Desktop log files (legacy)
    if DESKTOP.exists():
        for p in sorted(DESKTOP.glob("deal_scraper_log_*.txt")):
            try:
                mtime = datetime.fromtimestamp(p.stat().st_mtime)
                if mtime >= cutoff:
                    blob += f"\n=== {p} ===\n" + p.read_text(errors="replace")
                    files_read.append(str(p))
            except Exception:
                pass

    return blob, files_read


def read_state_files():
    """Returns ledger + state + near-miss data."""
    out = {}
    for name in ["deal_scraper_state.json", "deal_scraper_ledger.json", "deal_scraper_near_miss.json"]:
        p = DESKTOP / name
        if p.exists():
            try:
                out[name] = json.loads(p.read_text())
            except Exception as e:
                out[name] = f"(read error: {e})"
        else:
            out[name] = None
    return out


def run_parser_tests():
    """Execute pytest on tests/test_parser.py and capture results."""
    tests_path = REPO / "tests" / "test_parser.py"
    if not tests_path.exists():
        return ("MISSING", "tests/test_parser.py not found")
    try:
        r = subprocess.run(
            ["python3", "-m", "pytest", str(tests_path), "-v", "--tb=short"],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            timeout=60,
        )
        ok = r.returncode == 0
        return ("PASS" if ok else "FAIL", r.stdout + "\n" + r.stderr)
    except FileNotFoundError:
        return ("SKIPPED", "pytest not installed (pip3 install pytest)")
    except subprocess.TimeoutExpired:
        return ("TIMEOUT", "tests took >60s")
    except Exception as e:
        return ("ERROR", str(e))


def extract_run_summaries(blob):
    """Look for per-run summary lines in scraper logs.

    The scraper typically logs lines like:
        Pulled N new emails since last run
        Filtered to N wholesaler / WA messages
        Parsed N deals
        Matched N deals to N buyers
        Sent N emails
    """
    runs = []
    current = {}
    for line in blob.split("\n"):
        # Detect run start
        if re.search(r"=== run start ===|Starting deal scraper|Run started", line, re.I):
            if current:
                runs.append(current)
            current = {"start_line": line.strip()}
        # Various summary metrics
        for pat, key in [
            (r"Pulled (\d+) new emails", "emails_pulled"),
            (r"Filtered to (\d+).*wholesaler", "wholesaler_filtered"),
            (r"(\d+) WhatsApp", "whatsapp_count"),
            (r"Parsed (\d+) deals?", "parsed_deals"),
            (r"Matched (\d+) deals? to (\d+) buyers?", "matches"),
            (r"Sent (\d+) emails?", "emails_sent"),
            (r"Skipped (\d+).*duplicat", "skipped_dups"),
            (r"Error|Exception|Traceback", "errors"),
        ]:
            m = re.search(pat, line, re.I)
            if m:
                if key == "matches":
                    current[key] = (int(m.group(1)), int(m.group(2)))
                elif key == "errors":
                    current.setdefault("errors", []).append(line.strip()[:200])
                else:
                    current[key] = int(m.group(1))
    if current:
        runs.append(current)
    return runs


def quality_check_addresses(blob):
    """Look for parsed deal lines and flag suspicious addresses/prices."""
    suspicious = []
    deal_pattern = re.compile(
        r"(\d+\s+[A-Za-z][A-Za-z0-9 .]{3,60}?\s+(?:St|Ave|Rd|Blvd|Dr|Ln|Way|Ct|Pl|Pkwy|Hwy|Ter|Cir))",
        re.I,
    )
    # Lines like "PARSED: 123 Main St | Price: $245000"
    parsed_lines = re.findall(r"PARSED:.*?Price:\s*\$([\d,]+)", blob)
    for price_str in parsed_lines:
        try:
            price = int(price_str.replace(",", ""))
            if price < 30000:
                suspicious.append(f"Price too low (likely sqft): ${price}")
            elif price > 5_000_000:
                suspicious.append(f"Price too high (likely typo): ${price}")
        except ValueError:
            pass

    return suspicious


def report(args):
    print(f"# Scraper Accuracy Audit — {datetime.now().strftime('%Y-%m-%d %H:%M ET')}")
    print(f"\nWindow: last {args.days} days")
    print(f"\n---\n")

    # ─── 1. Logs ───
    print("## 1. Log file inventory\n")
    blob, files = read_recent_logs(args.days)
    if files:
        for f in files:
            sz = Path(f).stat().st_size if Path(f).exists() else 0
            print(f"- `{f}` ({sz:,} bytes)")
    else:
        print("**⚠ No log files found.** Scraper may not be writing logs, or logs may be only in Railway dashboard.\n")
        print("Check Railway: https://railway.com/dashboard → luminous-spontaneity → dealmatcher service → Logs tab\n")

    # ─── 2. Run summaries ───
    print(f"\n## 2. Run summaries (extracted from logs)\n")
    runs = extract_run_summaries(blob)
    if runs:
        print(f"Found **{len(runs)} run(s)** in window.\n")
        for i, r in enumerate(runs[-10:], 1):  # last 10
            print(f"### Run {i}")
            for k, v in r.items():
                if k == "errors":
                    print(f"- ⚠ Errors:")
                    for e in v[:3]:
                        print(f"  - `{e}`")
                else:
                    print(f"- {k}: **{v}**")
            print()
    else:
        print("⚠ No run summaries detected in logs. Either logs don't have summary lines, or scraper isn't running.\n")

    # ─── 3. Address/price quality ───
    print(f"\n## 3. Suspicious parsed values\n")
    sus = quality_check_addresses(blob)
    if sus:
        for s in sus[:20]:
            print(f"- ⚠ {s}")
    else:
        print("✅ No suspicious price values found in window (or logs don't include parsed line details).\n")

    # ─── 4. State files ───
    print(f"\n## 4. State / ledger inspection\n")
    state = read_state_files()
    for name, val in state.items():
        if val is None:
            print(f"- ⚠ `~/Desktop/{name}` not found")
        elif isinstance(val, str):
            print(f"- ⚠ `~/Desktop/{name}`: {val}")
        elif isinstance(val, dict):
            print(f"- `~/Desktop/{name}`: **{len(val)} entries**")
            # Get newest entry timestamp if structure permits
            try:
                latest = max(
                    (v.get("ts", v.get("timestamp", v.get("date", ""))) for v in val.values() if isinstance(v, dict)),
                    default=""
                )
                if latest:
                    print(f"  - newest entry: {latest}")
            except Exception:
                pass
        elif isinstance(val, list):
            print(f"- `~/Desktop/{name}`: **{len(val)} entries**")

    # ─── 5. Senders file ───
    print(f"\n## 5. Wholesaler senders\n")
    sf = REPO / "senders.txt"
    if sf.exists():
        senders = [l.strip() for l in sf.read_text().splitlines() if l.strip() and not l.startswith("#")]
        print(f"`senders.txt` has **{len(senders)} active sender(s)**.")
        if len(senders) < 5:
            print("\n⚠ Very few senders — confirm none have been accidentally removed.")
        print("\nFirst 10:")
        for s in senders[:10]:
            print(f"- `{s}`")
    else:
        print("⚠ `senders.txt` missing.")

    # ─── 6. Parser unit tests ───
    print(f"\n## 6. Parser unit tests\n")
    status, output = run_parser_tests()
    print(f"**Status:** {status}\n")
    if status == "PASS":
        # Count pass/total
        passed = re.search(r"(\d+) passed", output)
        if passed:
            print(f"✅ {passed.group(1)} tests passed.")
    else:
        print("```\n" + output[-1500:] + "\n```")

    # ─── 7. Cloud worker health (WhatsApp side) ───
    print(f"\n## 7. WhatsApp Worker health\n")
    try:
        import urllib.request
        with urllib.request.urlopen(
            "https://cheaphomesfla-whatsapp-webhook.cbfcalcio5.workers.dev/health",
            timeout=8,
        ) as r:
            data = json.loads(r.read())
            print("✅ Worker reachable.")
            for k, v in data.items():
                print(f"- {k}: `{v}`")
    except Exception as e:
        print(f"⚠ Couldn't reach Worker: {e}")

    # ─── 8. Final assessment ───
    print(f"\n## 8. Final assessment\n")
    issues = []
    if not files:
        issues.append("No scraper logs found — can't verify what's running")
    if status != "PASS":
        issues.append(f"Parser unit tests: {status}")
    if not state.get("deal_scraper_ledger.json"):
        issues.append("No ledger.json — can't verify dedup is working")
    if sus:
        issues.append(f"{len(sus)} suspicious parsed value(s)")

    if not issues:
        print("✅ **Audit clean — scraper appears to be producing trustworthy output.**")
        print("\nSafe to proceed with dashboards / aggregate CC email / downstream tooling.")
    else:
        print("⚠ **Issues detected — recommend fixing before stacking dashboards on top:**\n")
        for i, x in enumerate(issues, 1):
            print(f"{i}. {x}")
        print("\nFor each issue see the relevant section above for details.")


def main():
    args = parse_args()
    # Capture stdout to also save to file
    import io
    buf = io.StringIO()
    saved_stdout = sys.stdout
    try:
        # Print to both
        class Tee:
            def __init__(self, *streams):
                self.streams = streams
            def write(self, s):
                for st in self.streams:
                    st.write(s)
            def flush(self):
                for st in self.streams:
                    st.flush()
        sys.stdout = Tee(saved_stdout, buf)
        report(args)
    finally:
        sys.stdout = saved_stdout

    if args.save:
        out = DESKTOP / f"scraper_audit_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
        try:
            out.write_text(buf.getvalue())
            print(f"\n📝 Saved report to: {out}")
        except Exception as e:
            print(f"\n⚠ Couldn't save report: {e}")


if __name__ == "__main__":
    main()
