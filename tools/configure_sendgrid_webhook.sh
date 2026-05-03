#!/usr/bin/env bash
# Configure the SendGrid Event Webhook via API (bypasses the UI redirect to Marketing Campaigns).
# Uses your existing SENDGRID_API_KEY from .env.cheaphomesfla.

set -e

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO/.env.cheaphomesfla"

if [ ! -f "$ENV_FILE" ]; then
    echo "✗ Missing $ENV_FILE"
    exit 1
fi

# Pull SENDGRID_API_KEY
SG_KEY=$(awk -F= '$1=="SENDGRID_API_KEY" { sub(/^[^=]*=/, ""); print; exit }' "$ENV_FILE")

if [ -z "$SG_KEY" ]; then
    echo "✗ SENDGRID_API_KEY not found in $ENV_FILE"
    exit 1
fi

WEBHOOK_URL="https://sendgrid-events.cbfcalcio5.workers.dev/"

echo ""
echo "═══ CONFIGURING SENDGRID EVENT WEBHOOK ═══"
echo ""
echo "→ Webhook URL: $WEBHOOK_URL"
echo ""

# PATCH the event webhook settings
RESPONSE=$(curl -sS -X PATCH \
  "https://api.sendgrid.com/v3/user/webhooks/event/settings" \
  -H "Authorization: Bearer $SG_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"enabled\": true,
    \"url\": \"$WEBHOOK_URL\",
    \"group_resubscribe\": true,
    \"delivered\": true,
    \"group_unsubscribe\": true,
    \"spam_report\": true,
    \"bounce\": true,
    \"deferred\": false,
    \"unsubscribe\": true,
    \"processed\": false,
    \"open\": true,
    \"click\": true,
    \"dropped\": true
  }")

echo "API response:"
echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
echo ""

# Verify
echo "═══ VERIFYING ═══"
curl -sS "https://api.sendgrid.com/v3/user/webhooks/event/settings" \
  -H "Authorization: Bearer $SG_KEY" | python3 -m json.tool 2>/dev/null || echo "(verify call failed)"
echo ""

# Test the integration — sends a test event to your URL
echo "═══ SENDING TEST EVENT ═══"
TEST_RESPONSE=$(curl -sS -X POST \
  "https://api.sendgrid.com/v3/user/webhooks/event/test" \
  -H "Authorization: Bearer $SG_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"url\": \"$WEBHOOK_URL\"}")
echo "$TEST_RESPONSE"
echo ""

echo "═══ DONE ═══"
echo ""
echo "Check the Worker received the test event:"
echo "  curl https://sendgrid-events.cbfcalcio5.workers.dev/health"
echo ""
