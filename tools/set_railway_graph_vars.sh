#!/usr/bin/env bash
# One-shot: set all 3 Microsoft Graph env vars on the Railway dealmatcher service.
# Requires Railway CLI installed + logged in (railway login).
# Token cache base64 is read from ~/Desktop/graph_token_cache_b64.txt.
#
# Run on Mac Mini (where the token cache file exists):
#   bash tools/set_railway_graph_vars.sh

set -e

CACHE_FILE="$HOME/Desktop/graph_token_cache_b64.txt"
SERVICE="dealmatcher"

if [ ! -f "$CACHE_FILE" ]; then
    echo "✗ Token cache base64 not found at $CACHE_FILE"
    echo "Generate it first:"
    echo "  base64 -i ~/Desktop/.graph_token_cache.bin > $CACHE_FILE"
    exit 1
fi

if ! command -v railway &>/dev/null; then
    echo "✗ Railway CLI not installed."
    echo "Install: brew install railway   (or: curl -fsSL cli.new | sh)"
    echo ""
    echo "ALTERNATIVELY do it manually in the Railway dashboard:"
    echo "  1. https://railway.com/dashboard → luminous-spontaneity → service '$SERVICE' → Variables"
    echo "  2. + New Variable three times:"
    echo "     GRAPH_CLIENT_ID = b2143511-d5e1-49d9-a121-8df37116b895"
    echo "     GRAPH_TENANT_ID = 8dd6dc0e-8291-438e-b64f-57dbd2854c38"
    echo "     GRAPH_TOKEN_CACHE_B64 = (paste contents of $CACHE_FILE)"
    echo "  3. Save → Railway redeploys"
    exit 1
fi

# Verify we're linked to the right project
if ! railway status 2>&1 | grep -qi "luminous"; then
    echo "→ Linking to Railway project luminous-spontaneity..."
    railway link
fi

CACHE_VALUE=$(cat "$CACHE_FILE")
echo "→ Token cache base64 length: ${#CACHE_VALUE} chars"
echo ""

echo "→ Setting GRAPH_CLIENT_ID..."
railway variables --service "$SERVICE" --set "GRAPH_CLIENT_ID=b2143511-d5e1-49d9-a121-8df37116b895" 2>&1 | tail -3

echo ""
echo "→ Setting GRAPH_TENANT_ID..."
railway variables --service "$SERVICE" --set "GRAPH_TENANT_ID=8dd6dc0e-8291-438e-b64f-57dbd2854c38" 2>&1 | tail -3

echo ""
echo "→ Setting GRAPH_TOKEN_CACHE_B64..."
railway variables --service "$SERVICE" --set "GRAPH_TOKEN_CACHE_B64=$CACHE_VALUE" 2>&1 | tail -3

echo ""
echo "═══ DONE ═══"
echo ""
echo "Railway should auto-redeploy in ~30s. Verify by:"
echo "  1. Open https://railway.com/dashboard → luminous-spontaneity → $SERVICE → Logs"
echo "  2. Wait for next scheduled run (every 4h) OR click 'Restart' to fire one immediately"
echo "  3. Look for: '=== DEAL SCRAPER RUN STARTED ===' followed by 'Pulled N new emails'"
echo ""
echo "If you don't have Railway CLI installed, do it via the dashboard:"
echo "  Settings instructions printed above (re-run this script with no Railway CLI)"