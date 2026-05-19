#!/usr/bin/env python3
"""
cc_blast_pipeline.py — daily Bucket B orchestrator.

Called at the end of cheaphomesfla_scraper.py main() (after Bucket A SendGrid).
Does, in order:

  1) Dedup: pull SF buyer emails (LeadSource IN our 3 values), remove each
     from the CC master list so they don't get the mass blast on top of
     their personalized Bucket A.
  2) Build the CC statewide HTML from the same deals payload the scraper
     just parsed.
  3) Create a CC v3 email campaign with that HTML, associated with the
     master list (CC_LIST_ID env var).
  4) If CC_AUTO_SEND=true, schedule the campaign to send immediately.
     Otherwise leave as DRAFT for Chris to review + manually send the
     first day or two until we trust the pipeline.

Failure modes are caught locally so a CC outage doesn't crash the
whole scraper — Bucket A still ships.
"""
from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

log = logging.getLogger(__name__)


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "y", "on")


def run(scraper_deals: list[dict], buyer_emails: list[str]) -> dict:
    """Run the full Bucket B pipeline.

    Args:
        scraper_deals: list of deal dicts as produced by cheaphomesfla_scraper
            (the same `all_deals` after collapse_cross_posted).
        buyer_emails: list of buyer email strings (Bucket A audience from SF)
            that should be removed from the CC master list before sending.

    Returns a status dict with what happened.
    """
    status: dict = {
        "ok": False,
        "step": None,
        "dedup": None,
        "campaign": None,
        "auto_send": _truthy(os.environ.get("CC_AUTO_SEND")),
        "error": None,
    }

    list_id = os.environ.get("CC_LIST_ID", "").strip()
    if not list_id:
        status["step"] = "config"
        status["error"] = "CC_LIST_ID not set — skipping Bucket B."
        log.warning(status["error"])
        return status

    # 1) Dedup buyers from CC list
    try:
        status["step"] = "dedup"
        from tools.cc_v3 import dedup_sf_buyers_from_cc_list
        status["dedup"] = dedup_sf_buyers_from_cc_list(buyer_emails, list_id)
        log.info("Bucket B dedup: %s", status["dedup"])
    except Exception as e:  # noqa: BLE001
        log.warning("Bucket B dedup failed: %s", e)
        status["dedup"] = {"error": str(e)}
        # Don't abort — continue to send

    # 2) Build HTML
    try:
        status["step"] = "render"
        from tools.cc_html_builder import build_cc_html, deals_from_scraper_payload
        deal_objs = deals_from_scraper_payload(scraper_deals)
        if not deal_objs:
            status["step"] = "render"
            status["error"] = "No deals to render — skipping Bucket B send."
            log.warning(status["error"])
            return status
        subject, html = build_cc_html(deal_objs)
    except Exception:
        status["error"] = f"HTML render failed: {traceback.format_exc()}"
        log.error(status["error"])
        return status

    # 3) Create campaign (and maybe send)
    try:
        status["step"] = "send"
        from tools.cc_v3 import send_bucket_b
        result = send_bucket_b(
            html=html,
            subject=subject,
            list_id=list_id,
            auto_send=status["auto_send"],
        )
        status["campaign"] = result
        status["ok"] = True
        if status["auto_send"]:
            log.info("Bucket B sent live: campaign_id=%s", result.get("campaign_id"))
        else:
            log.info("Bucket B draft created (CC_AUTO_SEND=false): campaign_id=%s — review + send manually",
                     result.get("campaign_id"))
    except Exception:
        status["error"] = f"CC send failed: {traceback.format_exc()}"
        log.error(status["error"])
        return status

    return status


if __name__ == "__main__":
    # Allow manual test from the command line. Reads deals from the JSON
    # dumped by the scraper's last run.
    import json
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    dump = Path.home() / "Desktop" / "deal_scraper_last_run_deals.json"
    if not dump.exists():
        print(f"No deals dump at {dump}. Run the scraper first.")
        sys.exit(1)
    deals = json.loads(dump.read_text())

    # Buyer emails arg optional; for a one-off test we can pass [] to skip dedup
    buyer_emails = []
    print(json.dumps(run(deals, buyer_emails), indent=2, default=str))
