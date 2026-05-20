#!/usr/bin/env python3
"""
cloud_morning_runner.py — orchestrates the daily CHF morning blast for the
``daily-blast.yml`` GitHub Action.

The full play, in order:

  STAGE 1 — Bucket A (SendGrid per-investor filtered brief)
    Calls ``cheaphomesfla_scraper.main()`` which scrapes the
    info@cheaphomesFLA.com mailbox via Microsoft Graph, parses
    wholesaler emails into structured deals, loads opted-in buyer
    Contacts from Salesforce, matches each deal to the buyers whose
    Buyer_Counties_of_Interest__c covers the property's county, and
    fires per-buyer SendGrid emails. The scraper's DRY_RUN env-var
    decides whether it actually sends or just logs.

  STAGE 2 — Bucket B (Constant Contact statewide brief)
    Calls ``build_daily_cc_email.main()`` which queries today's
    scraper-generated Salesforce Tasks, picks the top-N outlier
    deals, renders the CC composer-ready HTML, and (in live mode)
    emails it to Chris so he can paste it into the CC web UI and
    click Send. Future v2 will push to the CC API directly when
    the secrets are present.

CLI:
    --send         Live send. Stage 1 SendGrid is real, Stage 2 emails the
                   CC HTML to Chris. Without ``--send``, Stage 1 forces
                   DRY_RUN=1 and Stage 2 passes ``--no-send`` to the CC
                   builder (HTML still saved to disk for review).
    --skip-scrape  Skip Stage 1 entirely (e.g. reusing yesterday's deals
                   dump). Stage 2 still runs.

Exit code: 0 on success, non-zero if Stage 1 raises. Stage 2 failures
are reported but non-fatal — losing the CC HTML preview shouldn't kill
the per-investor SendGrid track that already shipped.

Invocation by daily-blast.yml:
    python tools/cloud_morning_runner.py [--send] [--skip-scrape]
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Make the scraper (top-level) and other tools/ modules importable.
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))


def _ensure_desktop_dir() -> None:
    """The cheaphomesfla_scraper.py module was written for Chris's Mac and
    hardcodes ``~/Desktop`` for state, ledger, dump, and log file paths
    (STATE_FILE, DEAL_LEDGER_FILE, DEALS_DUMP_FILE, LOG_FILE, etc.).

    On the GitHub Actions ubuntu-latest runner ``~`` is ``/home/runner``
    and there is no Desktop directory there by default. Most file writes
    in the scraper are wrapped in try/except, but a few (token cache,
    state load) are not — and even the suppressed ones generate noisy
    log lines. Creating the directory eagerly here makes the runtime
    look like a Mac as far as the scraper is concerned, with zero risk
    on the Mac itself (mkdir(exist_ok=True) is a no-op).
    """
    desktop = Path.home() / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)


def _banner(text: str) -> None:
    line = "=" * 70
    print(line, flush=True)
    print(f"  {text}", flush=True)
    print(line, flush=True)


def _stage_1_scrape_and_send(live: bool) -> None:
    """Run the scraper. DRY_RUN env-var is the lever that decides whether
    SendGrid actually fires — cheaphomesfla_scraper reads it at module
    import time, so we set it BEFORE import."""
    if live:
        os.environ.pop("DRY_RUN", None)
    else:
        os.environ["DRY_RUN"] = "1"
    _banner(
        f"STAGE 1 — Scrape + Bucket A SendGrid (DRY_RUN="
        f"{'0 (LIVE)' if live else '1 (dry)'})"
    )
    # Late import so the env var above is honored.
    import cheaphomesfla_scraper  # noqa: E402  (intentional late import)
    cheaphomesfla_scraper.main()


def _stage_2_build_cc_html(live: bool) -> None:
    """Build the CC statewide brief HTML. In dry mode pass --no-send so the
    builder just saves the HTML to disk; in live mode let it email the HTML
    to Chris (who pastes into CC web UI and clicks Send)."""
    _banner(
        f"STAGE 2 — Bucket B CC statewide HTML "
        f"({'LIVE — emails HTML to Chris' if live else 'DRY — HTML to disk only'})"
    )
    # build_daily_cc_email.main() reads sys.argv via its own argparse, so we
    # monkey-patch the argv into the right shape for the duration of the call.
    saved_argv = sys.argv
    try:
        sys.argv = ["build_daily_cc_email.py", "--top", "5"]
        if not live:
            sys.argv.append("--no-send")
        import build_daily_cc_email  # noqa: E402
        build_daily_cc_email.main()
    finally:
        sys.argv = saved_argv


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="cloud_morning_runner",
        description="Daily CHF morning blast — scrape + SendGrid + CC HTML.",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Live mode. Without it, both stages run safely without sending.",
    )
    parser.add_argument(
        "--skip-scrape",
        action="store_true",
        help="Skip Stage 1 (e.g. reuse yesterday's deal dump for testing).",
    )
    args = parser.parse_args()
    live = args.send

    _banner(
        f"cloud_morning_runner — mode="
        f"{'LIVE (--send)' if live else 'DRY (no --send)'}"
        + (" — skip-scrape" if args.skip_scrape else "")
    )

    # ── STAGE 1 ───────────────────────────────────────────────────────────
    if args.skip_scrape:
        print("Stage 1 SKIPPED via --skip-scrape.", flush=True)
    else:
        try:
            _stage_1_scrape_and_send(live)
        except Exception:
            print("\n❌ STAGE 1 FAILED — full traceback below:\n", flush=True)
            traceback.print_exc()
            print(
                "\nStage 1 is the per-investor SendGrid send. Failing here means "
                "no Bucket A emails went out. Aborting before Stage 2 — the CC "
                "broadcast preview is no use if there's no scrape behind it.",
                flush=True,
            )
            return 1

    # ── STAGE 2 ───────────────────────────────────────────────────────────
    try:
        _stage_2_build_cc_html(live)
    except Exception:
        print("\n⚠️ STAGE 2 had an error — non-fatal, Stage 1 already shipped:\n", flush=True)
        traceback.print_exc()
        # Don't fail the whole run on a Stage 2 issue — Bucket A is the
        # higher-value pipeline and it already fired.
        return 0

    print("", flush=True)
    _banner("✅ cloud_morning_runner complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
