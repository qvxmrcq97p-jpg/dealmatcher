#!/usr/bin/env bash
# Set ALL required secrets on the WhatsApp worker from .env.cheaphomesfla.
# This was previously skipped in cf_set_secrets.sh under the assumption that
# the secrets were already set during desktop deploy. Apparently not — at
# least SENDGRID_API_KEY came back with HTTP 401.

set -e

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO/.env.cheaphomesfla"

get_val() { awk -F= -v k="$1" '$1==k { sub(/^[^=]*=/, ""); print; exit }' "$ENV_FILE"; }

SG_KEY=$(get_val SENDGRID_API_KEY)
FROM_EMAIL="${FROM_EMAIL:-whatsapp-deals@cheaphomesfla.com}"
TO_EMAIL="${TO_EMAIL:-info@cheaphomesFLA.com}"
SHARED_SECRET=$(get_val WA_SHARED_SECRET)

if [ -z "$SG_KEY" ]; then echo "✗ SENDGRID_API_KEY missing from .env"; exit 1; fi
if [ -z "$SHARED_SECRET" ]; then echo "✗ WA_SHARED_SECRET missing from .env"; exit 1; fi

cd "$REPO/cloudflare/whatsapp-worker"

echo ""
echo "═══ SETTING WHATSAPP WORKER SECRETS ═══"
echo ""

echo "→ SENDGRID_API_KEY..."
echo "$SG_KEY" | wrangler secret put SENDGRID_API_KEY 2>&1 | tail -3
echo ""

echo "→ FROM_EMAIL..."
echo "$FROM_EMAIL" | wrangler secret put FROM_EMAIL 2>&1 | tail -3
echo ""

echo "→ TO_EMAIL..."
echo "$TO_EMAIL" | wrangler secret put TO_EMAIL 2>&1 | tail -3
echo ""

echo "→ SHARED_SECRET..."
echo "$SHARED_SECRET" | wrangler secret put SHARED_SECRET 2>&1 | tail -3
echo ""

echo "═══ VERIFYING ═══"
echo ""
sleep 3
curl -s https://cheaphomesfla-whatsapp-webhook.cbfcalcio5.workers.dev/health | python3 -m json.tool
echo ""
echo "═══ TESTING WITH FAKE WEBHOOK ═══"
echo ""
RESPONSE=$(curl -sS -X POST https://cheaphomesfla-whatsapp-webhook.cbfcalcio5.workers.dev/ \
  -H "Authorization: Bearer $SHARED_SECRET" \
  -H 'Content-Type: application/json' \
  -d '{
    "typeWebhook": "incomingMessageReceived",
    "senderData": {"chatId": "test@g.us", "chatName": "Test Deal Group", "sender": "test@c.us", "senderName": "Tester"},
    "messageData": {"typeMessage": "textMessage", "textMessageData": {"textMessage": "Just listed: 123 Test St, Miami FL 33012, 3/2 1450 sqft, asking $245,000, ARV $385K"}}
  }')
echo "Worker response: $RESPONSE"
echo ""

if echo "$RESPONSE" | grep -q "ok.*true\|forwarded"; then
    echo "✓ Worker accepted webhook and forwarded — check info@cheaphomesFLA.com inbox in 30s for [WA-Group:Test Deal Group] email."
else
    echo "✗ Worker still failing — see response above."
fi