#!/usr/bin/env bash
# Updates SF_SECURITY_TOKEN across all 3 Cloudflare Workers + .env.cheaphomesfla.
# Run after SF password reset (which invalidates the old token).
#
# Usage:
#   bash tools/update_sf_security_token.sh
#   (Will prompt for the new token. Or pass via SF_SECURITY_TOKEN env var.)

set -e

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO/.env.cheaphomesfla"

if [ -z "${SF_SECURITY_TOKEN:-}" ]; then
    echo "Paste the NEW SF security token (from the email SF just sent you):"
    read -rs NEW_TOKEN
    echo
else
    NEW_TOKEN="$SF_SECURITY_TOKEN"
fi

if [ -z "$NEW_TOKEN" ]; then
    echo "✗ No token provided — aborting"
    exit 1
fi

echo ""
echo "═══ UPDATING SF_SECURITY_TOKEN ═══"
echo ""

# 1. Update .env.cheaphomesfla
if grep -q "^SF_SECURITY_TOKEN=" "$ENV_FILE"; then
    # Use a different delimiter since tokens can contain forward slashes
    sed -i.bak "s|^SF_SECURITY_TOKEN=.*|SF_SECURITY_TOKEN=$NEW_TOKEN|" "$ENV_FILE"
    rm -f "$ENV_FILE.bak"
    echo "✓ Updated .env.cheaphomesfla"
else
    echo "SF_SECURITY_TOKEN=$NEW_TOKEN" >> "$ENV_FILE"
    echo "✓ Appended SF_SECURITY_TOKEN to .env.cheaphomesfla"
fi

# 2. Update each Cloudflare Worker that uses SF
WORKERS=(
    "cloudflare/propertyleads-worker"
    "cloudflare/motivatedsellers-worker"
    "cloudflare/sendgrid-events"
)

for w in "${WORKERS[@]}"; do
    if [ -d "$REPO/$w" ]; then
        echo ""
        echo "→ $w"
        echo "$NEW_TOKEN" | (cd "$REPO/$w" && wrangler secret put SF_SECURITY_TOKEN 2>&1 | tail -3)
    else
        echo "  ! $w not found — skipping"
    fi
done

echo ""
echo "═══ TESTING ═══"
echo ""

# 3. Test SF auth via the Python simple_salesforce client
python3 -c "
import os
from pathlib import Path
env = {}
for line in Path('$ENV_FILE').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, _, v = line.partition('=')
        env[k.strip()] = v.strip()

try:
    from simple_salesforce import Salesforce
    sf = Salesforce(
        username=env['SF_USERNAME'],
        password=env['SF_PASSWORD'],
        security_token=env['SF_SECURITY_TOKEN'],
        domain=env.get('SF_DOMAIN', 'login'),
    )
    r = sf.query('SELECT Id FROM Lead LIMIT 1')
    print(f'✓ SF auth works — query returned {r[\"totalSize\"]} record(s)')
except Exception as e:
    print(f'✗ SF auth still failing: {e}')
    exit(1)
"

echo ""
echo "═══ DONE ═══"
echo ""
echo "All 3 Workers + .env.cheaphomesfla now have the new token."
echo ""
echo "Verify by sending a test lead:"
echo "  curl -X POST https://motivatedsellers-ppl-worker.cbfcalcio5.workers.dev/ \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"first_name\":\"Test\",\"last_name\":\"Recovery\",\"email_address\":\"test@example.com\",\"phone\":\"5555555555\",\"address\":\"123 Test St\",\"city\":\"Miami\",\"state\":\"FL\",\"zip_code\":\"33012\",\"lead_id\":\"test-recovery\"}'"
echo ""
echo "Then check Salesforce — you should see the test lead created."
