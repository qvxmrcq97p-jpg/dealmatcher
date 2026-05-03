#!/usr/bin/env bash
# Opens Railway's project settings page and copies the deploy-alert webhook URL.
echo ""
echo "→ Opening Railway dashboard..."
open -a "Google Chrome" "https://railway.com/dashboard"
sleep 2

WEBHOOK_URL="https://railway-deploy-alerts.cbfcalcio5.workers.dev/?secret=cd2d3a8ba58bff1d3d159ba713e7b802"
printf "%s" "$WEBHOOK_URL" | pbcopy

echo "✓ Webhook URL copied to clipboard:"
echo "  $WEBHOOK_URL"
echo ""
echo "═══════════════════════════════════════════════════"
echo "IN RAILWAY:"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  1. Click your dealmatcher project"
echo "  2. Click 'Settings' tab (top of project view)"
echo "  3. Scroll to 'Webhooks' section in the left sidebar"
echo "     (or look for 'Notifications' if 'Webhooks' isn't visible)"
echo "  4. Click 'New Webhook' or '+ Add Webhook'"
echo "  5. Click in the URL field, press Cmd+V to paste"
echo "  6. Check trigger boxes: 'Deploy Failed' and 'Deploy Crashed'"
echo "     (optionally also 'Deploy Succeeded' if you want green-pings)"
echo "  7. Click 'Create' or 'Save'"
echo ""
echo "When saved, tell Claude in chat. Phase 4 will be COMPLETE."
echo ""
