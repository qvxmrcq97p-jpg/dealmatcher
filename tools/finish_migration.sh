#!/usr/bin/env bash
# Master script — runs Phase 5 (Twilio deploy) → Phase 6 (plist cutover) → smoke test.
# Stops at any failure with clear error message.
#
# Usage:
#   bash tools/finish_migration.sh           # walks through with prompts
#   bash tools/finish_migration.sh --auto    # no prompts, just run

set -e
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

AUTO=false
[ "${1:-}" = "--auto" ] && AUTO=true

confirm() {
    if $AUTO; then return 0; fi
    echo ""
    read -p "$1 [y/N] " yn
    [[ "$yn" == "y" || "$yn" == "Y" ]]
}

step() {
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo "  $1"
    echo "═══════════════════════════════════════════════════════════"
}

# ─── PHASE 5 — Twilio /sms v2 deploy ─────────────────
step "PHASE 5 — Twilio /sms v2 deploy"
echo ""
echo "Dry-run first to verify your Twilio creds + service can be found..."
echo ""
python3 tools/deploy_twilio_sms.py --dry-run

if ! confirm "Dry-run looks good. Deploy v2 for real?"; then
    echo "Skipping Phase 5. You can run later: python3 tools/deploy_twilio_sms.py"
    exit 0
fi

python3 tools/deploy_twilio_sms.py

if ! confirm "Phase 5 deployed. Continue to Phase 6 (plist cutover)?"; then
    echo "Stopping here. Run later: bash tools/cutover_to_cloud.sh"
    exit 0
fi

# ─── PHASE 6 — Mac plist cutover ─────────────────────
step "PHASE 6 — Mac plist cutover (DRY-RUN)"
bash tools/cutover_to_cloud.sh

echo ""
echo "Above is a dry-run preview. Now applying for real..."
if ! confirm "Apply the cutover (boot out 7 launch agents, move plists to backup)?"; then
    echo "Skipping Phase 6. You can run later: bash tools/cutover_to_cloud.sh --apply"
    exit 0
fi

bash tools/cutover_to_cloud.sh --apply

# ─── SMOKE TEST ──────────────────────────────────────
step "FULL SMOKE TEST"
bash tools/smoke_test_all.sh

# ─── COMMIT + PUSH ───────────────────────────────────
step "COMMITTING + PUSHING TO GITHUB"
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    git add -A
    git commit -m "Phase 5+6 complete: Twilio v2 deployed, local launchd cut over to Railway" || true
    git push origin main || echo "  ! push failed — resolve manually"
else
    echo "  (no changes to commit)"
fi

# ─── DONE ────────────────────────────────────────────
step "MIGRATION COMPLETE"
echo ""
echo "✓ All cloud services running. Local launchd jobs disabled."
echo ""
echo "Watch tonight at 8 PM ET — CheapHomesFLA scrape auto-fires from Railway."
echo "Watch tomorrow at 8 AM ET — Johnson Buys email + SMS campaigns from Railway."
echo ""
echo "If anything breaks: bash tools/cutover_to_cloud.sh --rollback"
echo ""
