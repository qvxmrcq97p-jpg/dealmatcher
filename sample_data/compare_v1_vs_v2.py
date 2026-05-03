"""
A/B comparison: feed every dirty v1 property_address back through the
v2 parser to see what the new parser does with the noise.

Imperfect because v1's `property_address` field IS itself the OUTPUT of
broken parsing — not the original email body. But it's the closest
real-world sample we have without re-fetching from Microsoft Graph.

Categorizes each v1 record:
  - RECOVERED:  v2 produced a clean address from the dirty v1 string
  - FILTERED:   v2 produced no deal (correctly rejected as garbage)
  - DIRTY:      v2 still produced a problematic-looking address
  - UNCHANGED:  v1 was already clean, v2 confirms

Outputs:
  - sample_data/v1_vs_v2_summary.txt   — counts + examples
  - sample_data/v1_vs_v2_detail.csv    — every row with side-by-side
"""
import csv
import json
import os
import re
import sys

# add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parser import parse_email_body  # noqa: E402

# V1 dump path: production = ~/Desktop, sandbox runs = /sessions/.../mnt/Desktop
_DEFAULT_DUMP = os.path.expanduser("~/Desktop/deal_scraper_last_run_deals.json")
_SANDBOX_DUMP = "/sessions/jolly-bold-hypatia/mnt/Desktop/deal_scraper_last_run_deals.json"
V1_DUMP = _DEFAULT_DUMP if os.path.exists(_DEFAULT_DUMP) else _SANDBOX_DUMP
SUMMARY_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v1_vs_v2_summary.txt")
DETAIL_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v1_vs_v2_detail.csv")


def is_dirty(addr: str) -> bool:
    if not addr:
        return False
    a = addr.lower()
    if "nbsp" in a or "&nbsp;" in a:
        return True
    if "*" in addr:
        return True
    if "new deal" in a:
        return True
    if "call" in a or "text" in a:
        return True
    if re.match(r"^\d{3}[).-]", addr):  # phone-like prefix
        return True
    if re.search(r"\bsold\b|\bcomp\b|\bsale price\b", a):
        return True
    return False


def main() -> None:
    with open(V1_DUMP) as f:
        v1_deals = json.load(f)

    counts = {"RECOVERED": 0, "FILTERED": 0, "DIRTY": 0, "UNCHANGED": 0}
    examples: dict[str, list[tuple[str, str]]] = {k: [] for k in counts}
    detail_rows: list[dict] = []

    for d in v1_deals:
        v1_addr = d.get("property_address") or ""
        v1_was_dirty = is_dirty(v1_addr)

        # Treat the v1 dirty string AS IF it were body text, run v2 on it
        v2_deals = parse_email_body(v1_addr)
        v2_addr = v2_deals[0].address if v2_deals else ""
        v2_is_dirty = is_dirty(v2_addr)

        if not v1_was_dirty and v2_addr:
            category = "UNCHANGED"
        elif v1_was_dirty and not v2_addr:
            category = "FILTERED"
        elif v1_was_dirty and v2_addr and not v2_is_dirty:
            category = "RECOVERED"
        else:
            category = "DIRTY"

        counts[category] += 1
        if len(examples[category]) < 6:
            examples[category].append((v1_addr[:120], v2_addr[:120]))

        detail_rows.append({
            "category": category,
            "v1_address": v1_addr,
            "v2_address": v2_addr,
            "v2_zip": v2_deals[0].zip_code if v2_deals else "",
            "v2_price": v2_deals[0].asking_price if v2_deals else "",
            "v2_warnings": "|".join(v2_deals[0].parse_warnings) if v2_deals else "",
        })

    # Write summary
    total = sum(counts.values())
    lines = [
        f"v1-vs-v2 parser comparison ({total} deals from Apr 28 production sample)",
        "=" * 76,
        "",
        f"  RECOVERED   {counts['RECOVERED']:>4}  ({100*counts['RECOVERED']/total:.0f}%)  "
        "v1 was dirty → v2 produced a clean address",
        f"  FILTERED    {counts['FILTERED']:>4}  ({100*counts['FILTERED']/total:.0f}%)  "
        "v1 was dirty → v2 correctly rejected (no deal emitted)",
        f"  UNCHANGED   {counts['UNCHANGED']:>4}  ({100*counts['UNCHANGED']/total:.0f}%)  "
        "v1 was clean → v2 confirms clean",
        f"  DIRTY       {counts['DIRTY']:>4}  ({100*counts['DIRTY']/total:.0f}%)  "
        "v2 still produced something dirty (regression — investigate)",
        "",
    ]
    for cat, samples in examples.items():
        lines.append(f"--- {cat} examples ---")
        for v1a, v2a in samples:
            lines.append(f"  v1: {v1a or '(empty)'}")
            lines.append(f"  v2: {v2a or '(no deal emitted)'}")
            lines.append("")

    summary = "\n".join(lines)
    with open(SUMMARY_OUT, "w") as f:
        f.write(summary)
    print(summary)

    # Write detail CSV
    with open(DETAIL_OUT, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=detail_rows[0].keys())
        writer.writeheader()
        writer.writerows(detail_rows)
    print(f"\nDetail CSV: {DETAIL_OUT}")


if __name__ == "__main__":
    main()
