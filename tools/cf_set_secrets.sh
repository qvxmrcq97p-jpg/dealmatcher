#!/usr/bin/env bash
# cf_set_secrets.sh — set all Wrangler secrets for the 5 Cloudflare Workers.
#
# Reads values from your existing .env.cheaphomesfla, generates a fresh
# SHARED_SECRET for the railway-deploy-alerts webhook auth, and pipes
# each value into `wrangler secret put` non-interactively.
#
# Run:
#   cd ~/dealmatcher && bash tools/cf_set_secrets.sh

set -e
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO/.env.cheaphomesfla"

if [ ! -f "$ENV_FILE" ]; then
    echo "✗ Missing $ENV_FILE"
    exit 1
fi

# Pull values from .env (line-by-line — works with values that contain spaces)
get_val() {
    local key="$1"
    awk -F= -v k="$key" '$1==k { sub(/^[^=]*=/, ""); print; exit }' "$ENV_FILE"
}

SF_USER=$(get_val SF_USERNAME)
SF_PASS=$(get_val SF_PASSWORD)
SF_TOK=$(get_val SF_SECURITY_TOKEN)
SG_KEY=$(get_val SENDGRID_API_KEY)
TW_SID=$(get_val TWILIO_ACCOUNT_SID)
TW_TOK=$(get_val TWILIO_AUTH_TOKEN)

# Generate a random shared secret for railway-deploy-alerts webhook auth
SHARED_SECRET=$(openssl rand -hex 16)
echo "Generated SHARED_SECRET (save this — Railway needs it later):"
echo "  $SHARED_SECRET"
echo

# Helper — set one secret via stdin
set_secret() {
    local dir="$1"
    local name="$2"
    local value="$3"
    if [ -z "$value" ]; then
        echo "  · skipping $name (empty value)"
        return
    fi
    echo -n "  → $name: "
    echo "$value" | (cd "$REPO/$dir" && wrangler secret put "$name" 2>&1 | tail -1)
}

# ── 1. propertyleads-ppl-worker ──
echo "═══ propertyleads-ppl-worker ═══"
set_secret cloudflare/propertyleads-worker SF_USERNAME      "$SF_USER"
set_secret cloudflare/propertyleads-worker SF_PASSWORD      "$SF_PASS"
set_secret cloudflare/propertyleads-worker SF_SECURITY_TOKEN "$SF_TOK"
set_secret cloudflare/propertyleads-worker SF_LOGIN_DOMAIN  "login"
set_secret cloudflare/propertyleads-worker SENDGRID_API_KEY "$SG_KEY"
set_secret cloudflare/propertyleads-worker FROM_EMAIL       "info@johnsonbuys.com"
set_secret cloudflare/propertyleads-worker FROM_NAME        "Chris @ Johnson Buys"
set_secret cloudflare/propertyleads-worker ALERT_TO         "info@johnsonbuys.com"
set_secret cloudflare/propertyleads-worker TWILIO_ACCOUNT_SID "$TW_SID"
set_secret cloudflare/propertyleads-worker TWILIO_AUTH_TOKEN  "$TW_TOK"
set_secret cloudflare/propertyleads-worker TWILIO_FROM        "+19549534554"
echo

# ── 2. motivatedsellers-ppl-worker ──
echo "═══ motivatedsellers-ppl-worker ═══"
set_secret cloudflare/motivatedsellers-worker SF_USERNAME      "$SF_USER"
set_secret cloudflare/motivatedsellers-worker SF_PASSWORD      "$SF_PASS"
set_secret cloudflare/motivatedsellers-worker SF_SECURITY_TOKEN "$SF_TOK"
set_secret cloudflare/motivatedsellers-worker SF_LOGIN_DOMAIN  "login"
set_secret cloudflare/motivatedsellers-worker SENDGRID_API_KEY "$SG_KEY"
set_secret cloudflare/motivatedsellers-worker FROM_EMAIL       "info@johnsonbuys.com"
set_secret cloudflare/motivatedsellers-worker FROM_NAME        "Chris @ Johnson Buys"
set_secret cloudflare/motivatedsellers-worker ALERT_TO         "info@johnsonbuys.com"
set_secret cloudflare/motivatedsellers-worker TWILIO_ACCOUNT_SID "$TW_SID"
set_secret cloudflare/motivatedsellers-worker TWILIO_AUTH_TOKEN  "$TW_TOK"
set_secret cloudflare/motivatedsellers-worker TWILIO_FROM        "+19549534554"
echo

# ── 3. sendgrid-events ──
echo "═══ sendgrid-events ═══"
set_secret cloudflare/sendgrid-events SF_USERNAME       "$SF_USER"
set_secret cloudflare/sendgrid-events SF_PASSWORD       "$SF_PASS"
set_secret cloudflare/sendgrid-events SF_SECURITY_TOKEN "$SF_TOK"
set_secret cloudflare/sendgrid-events SF_LOGIN_DOMAIN   "login"
echo

# ── 4. railway-deploy-alerts ──
echo "═══ railway-deploy-alerts ═══"
set_secret cloudflare/railway-deploy-alerts SHARED_SECRET     "$SHARED_SECRET"
set_secret cloudflare/railway-deploy-alerts SENDGRID_API_KEY  "$SG_KEY"
set_secret cloudflare/railway-deploy-alerts FROM_EMAIL        "info@johnsonbuys.com"
set_secret cloudflare/railway-deploy-alerts ALERT_TO          "info@johnsonbuys.com"
set_secret cloudflare/railway-deploy-alerts TWILIO_ACCOUNT_SID "$TW_SID"
set_secret cloudflare/railway-deploy-alerts TWILIO_AUTH_TOKEN  "$TW_TOK"
set_secret cloudflare/railway-deploy-alerts TWILIO_FROM        "+19549534554"
set_secret cloudflare/railway-deploy-alerts ALERT_SMS_TO       "+13055759040"
echo

# ── whatsapp-worker — secret already set during Desktop deploy, skip ──

echo "═══ DONE ═══"
echo "Save this SHARED_SECRET — you'll paste it into Railway's webhook URL:"
echo "  $SHARED_SECRET"
echo
echo "Webhook URL for Railway → Project Settings → Notifications → Webhooks:"
echo "  https://railway-deploy-alerts.cbfcalcio5.workers.dev/?secret=$SHARED_SECRET"
