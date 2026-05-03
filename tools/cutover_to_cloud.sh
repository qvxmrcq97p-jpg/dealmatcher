#!/usr/bin/env bash
# Phase 6 — Cut over from local launchd → Railway/cloud.
#
# Boots out the 7 local launch agents that have been running the dealmatcher
# stack, moves the plist files to a backup folder so they don't auto-reload,
# and prints a status report.
#
# Run modes:
#   bash tools/cutover_to_cloud.sh           # DRY-RUN (default — no changes)
#   bash tools/cutover_to_cloud.sh --apply   # actually do it
#   bash tools/cutover_to_cloud.sh --rollback # restore from backup

set -e

LAUNCH_DIR="$HOME/Library/LaunchAgents"
BACKUP_DIR="$HOME/Library/LaunchAgents.cutover-backup"
USER_UID=$(id -u)

# All 7 plists that run the local-Mac side of the stack
PLISTS=(
    "com.cheaphomes.dealmatcher.plist"
    "com.cheaphomes.watchdog.plist"
    "com.johnsonbuys.digest.plist"
    "com.johnsonbuys.emailcampaign.plist"
    "com.johnsonbuys.followup.plist"
    "com.johnsonbuys.smscampaign.plist"
    "com.johnsonbuys.webhook.plist"
)

MODE="dry-run"
case "${1:-}" in
    --apply)    MODE="apply" ;;
    --rollback) MODE="rollback" ;;
    "")         MODE="dry-run" ;;
    *)          echo "Usage: $0 [--apply|--rollback]"; exit 1 ;;
esac

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  PHASE 6 — CUT LOCAL LAUNCHD → RAILWAY"
echo "  Mode: $MODE"
echo "═══════════════════════════════════════════════════════════"
echo ""

# ── ROLLBACK MODE ─────────────────────────────────────
if [ "$MODE" = "rollback" ]; then
    if [ ! -d "$BACKUP_DIR" ]; then
        echo "✗ No backup at $BACKUP_DIR — nothing to roll back."
        exit 1
    fi
    echo "→ Restoring plists from $BACKUP_DIR..."
    for p in "${PLISTS[@]}"; do
        if [ -f "$BACKUP_DIR/$p" ]; then
            cp "$BACKUP_DIR/$p" "$LAUNCH_DIR/$p"
            launchctl bootstrap gui/$USER_UID "$LAUNCH_DIR/$p" 2>&1 || true
            echo "  ✓ Restored $p"
        else
            echo "  · $p not in backup — skipped"
        fi
    done
    echo ""
    echo "✓ Rollback complete. Local launchd jobs are running again."
    exit 0
fi

# ── PRE-FLIGHT: which plists are currently loaded? ───
echo "→ Current state:"
for p in "${PLISTS[@]}"; do
    label="${p%.plist}"
    if launchctl print "gui/$USER_UID/$label" &>/dev/null; then
        echo "  ● $p  — LOADED"
    elif [ -f "$LAUNCH_DIR/$p" ]; then
        echo "  ○ $p  — file exists but NOT loaded"
    else
        echo "  · $p  — file does not exist"
    fi
done
echo ""

# ── DRY RUN ──────────────────────────────────────────
if [ "$MODE" = "dry-run" ]; then
    echo "═══ DRY RUN — what --apply would do ═══"
    echo ""
    echo "1. Create backup at $BACKUP_DIR"
    echo "2. For each loaded plist: launchctl bootout gui/$USER_UID/<label>"
    echo "3. Move the .plist file to backup dir"
    echo "4. Verify each is no longer running"
    echo "5. Print final status"
    echo ""
    echo "Re-run with --apply to execute."
    echo ""
    echo "Pre-flight checks for the cloud side:"
    echo ""

    echo "→ Cloudflare Workers /health endpoints:"
    for w in propertyleads-ppl-worker motivatedsellers-ppl-worker sendgrid-events railway-deploy-alerts cheaphomesfla-whatsapp-webhook; do
        host="${w}.cbfcalcio5.workers.dev"
        code=$(curl -sS -o /dev/null -w "%{http_code}" "https://${host}/health" --max-time 5 2>/dev/null || echo "000")
        if [ "$code" = "200" ]; then
            echo "  ✓ $host  — HTTP 200"
        else
            echo "  ✗ $host  — HTTP $code"
        fi
    done
    echo ""

    echo "If all cloud workers return 200, you're safe to --apply."
    exit 0
fi

# ── APPLY MODE ────────────────────────────────────────
echo "═══ APPLYING — booting out local launch agents ═══"
echo ""

# Backup
mkdir -p "$BACKUP_DIR"
echo "→ Backing up plists to $BACKUP_DIR..."
for p in "${PLISTS[@]}"; do
    if [ -f "$LAUNCH_DIR/$p" ]; then
        cp "$LAUNCH_DIR/$p" "$BACKUP_DIR/$p"
        echo "  ✓ Backed up $p"
    fi
done
echo ""

# Boot out + move
echo "→ Booting out + moving plists..."
for p in "${PLISTS[@]}"; do
    label="${p%.plist}"
    if launchctl print "gui/$USER_UID/$label" &>/dev/null; then
        if launchctl bootout "gui/$USER_UID/$label" 2>&1; then
            echo "  ✓ Booted out $label"
        else
            echo "  ! Bootout warning for $label (may be benign)"
        fi
    fi
    if [ -f "$LAUNCH_DIR/$p" ]; then
        mv "$LAUNCH_DIR/$p" "$BACKUP_DIR/${p}.disabled"
        echo "  ✓ Moved $p → backup (won't auto-reload on Mac restart)"
    fi
done
echo ""

# Verify
echo "→ Verifying all are stopped..."
all_clear=true
for p in "${PLISTS[@]}"; do
    label="${p%.plist}"
    if launchctl print "gui/$USER_UID/$label" &>/dev/null; then
        echo "  ✗ $label  — STILL RUNNING"
        all_clear=false
    else
        echo "  ✓ $label  — stopped"
    fi
done
echo ""

if $all_clear; then
    echo "═══ CUTOVER COMPLETE ═══"
    echo ""
    echo "All 7 local launch agents are stopped + disabled."
    echo "Backup saved to: $BACKUP_DIR"
    echo ""
    echo "Cloud side is now running everything:"
    echo "  • Cron jobs:  Railway luminous-spontaneity (8 services)"
    echo "  • Webhooks:   5 Cloudflare Workers"
    echo "  • Inbound SMS: Twilio Function /sms (post-Phase-5)"
    echo ""
    echo "Tomorrow morning watch for:"
    echo "  • 8:00 AM ET — Johnson Buys email campaign fires from Railway"
    echo "  • 8:15 AM ET — Johnson Buys SMS campaign fires from Railway"
    echo "  • 9:00 AM ET — daily KPI email lands in your inbox"
    echo ""
    echo "If anything fails: bash tools/cutover_to_cloud.sh --rollback"
else
    echo "═══ INCOMPLETE — some daemons still running ═══"
    echo ""
    echo "Manual cleanup may be needed. Try:"
    echo "  launchctl bootout gui/$USER_UID/<label>"
    exit 2
fi
