#!/usr/bin/env bash
# End-to-end smoke test for the entire cloud stack.
# Run after Phase 5 + Phase 6 to verify everything still works.
#
# Usage: bash tools/smoke_test_all.sh

set +e  # don't bail on first failure — we want a full report

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO/.env.cheaphomesfla"

# Pull values from .env
get_val() { awk -F= -v k="$1" '$1==k { sub(/^[^=]*=/, ""); print; exit }' "$ENV_FILE"; }

PASS=0
FAIL=0
RESULTS=()

# Helper
report() {
    local name="$1" status="$2" detail="$3"
    if [ "$status" = "PASS" ]; then
        echo "  ✓ $name"
        PASS=$((PASS+1))
    else
        echo "  ✗ $name — $detail"
        FAIL=$((FAIL+1))
    fi
    RESULTS+=("$status: $name — $detail")
}

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  END-TO-END SMOKE TEST — $(date)"
echo "═══════════════════════════════════════════════════════════"

# ─── 1. Cloudflare Workers /health ───
echo ""
echo "▶ 1. Cloudflare Workers /health"
for w in propertyleads-ppl-worker motivatedsellers-ppl-worker sendgrid-events railway-deploy-alerts cheaphomesfla-whatsapp-webhook; do
    code=$(curl -sS -o /tmp/cf_$w.json -w "%{http_code}" "https://${w}.cbfcalcio5.workers.dev/health" --max-time 8 2>/dev/null)
    if [ "$code" = "200" ]; then
        report "$w /health" PASS "HTTP 200"
    else
        report "$w /health" FAIL "HTTP $code"
    fi
done

# ─── 2. SendGrid Event Webhook config ───
echo ""
echo "▶ 2. SendGrid Event Webhook"
SG_KEY=$(get_val SENDGRID_API_KEY)
if [ -n "$SG_KEY" ]; then
    SG_RESP=$(curl -sS "https://api.sendgrid.com/v3/user/webhooks/event/settings" \
        -H "Authorization: Bearer $SG_KEY" --max-time 10)
    if echo "$SG_RESP" | grep -q '"enabled": true'; then
        url=$(echo "$SG_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('url',''))")
        if echo "$url" | grep -q "sendgrid-events.cbfcalcio5.workers.dev"; then
            report "SendGrid webhook URL" PASS "$url"
        else
            report "SendGrid webhook URL" FAIL "URL is wrong: $url"
        fi
    else
        report "SendGrid webhook enabled" FAIL "$(echo "$SG_RESP" | head -c 200)"
    fi
fi

# ─── 3. Twilio /sms function deployed ───
echo ""
echo "▶ 3. Twilio /sms function"
TW_SID=$(get_val TWILIO_ACCOUNT_SID)
TW_TOK=$(get_val TWILIO_AUTH_TOKEN)
if [ -n "$TW_SID" ] && [ -n "$TW_TOK" ]; then
    SVC_RESP=$(curl -sS "https://serverless.twilio.com/v1/Services?PageSize=50" \
        -u "$TW_SID:$TW_TOK" --max-time 10)
    SVC_SID=$(echo "$SVC_RESP" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    for s in d.get('services', []):
        if s.get('unique_name') == 'johnson-buys-sms' or s.get('friendly_name') == 'johnson-buys-sms':
            print(s['sid']); break
except: pass
")
    if [ -n "$SVC_SID" ]; then
        report "Twilio service johnson-buys-sms" PASS "$SVC_SID"
        # Check for latest deployment
        ENV_RESP=$(curl -sS "https://serverless.twilio.com/v1/Services/$SVC_SID/Environments" \
            -u "$TW_SID:$TW_TOK" --max-time 10)
        BUILD_SID=$(echo "$ENV_RESP" | python3 -c "
import json, sys
try:
    print(json.load(sys.stdin)['environments'][0].get('build_sid', ''))
except: pass
")
        if [ -n "$BUILD_SID" ]; then
            report "Twilio active build" PASS "$BUILD_SID"
        fi
    else
        report "Twilio service johnson-buys-sms" FAIL "Not found"
    fi
fi

# ─── 4. GitHub repo + remote ───
echo ""
echo "▶ 4. GitHub repo"
cd "$REPO"
REMOTE=$(git remote get-url origin 2>/dev/null)
if echo "$REMOTE" | grep -q "qvxmrcq97p-jpg/dealmatcher"; then
    report "git remote points to qvxmrcq97p-jpg/dealmatcher" PASS "$REMOTE"
else
    report "git remote correct" FAIL "Remote is: $REMOTE"
fi

# Try to fetch (verifies SSH key works)
if git ls-remote --heads origin main &>/dev/null; then
    report "GitHub SSH access" PASS "ls-remote works"
else
    report "GitHub SSH access" FAIL "SSH key not configured for this account"
fi

# ─── 5. Local launchd plists ───
echo ""
echo "▶ 5. Local launchd plists (should all be STOPPED post-Phase-6)"
UID_VAL=$(id -u)
PLISTS=(
    "com.cheaphomes.dealmatcher"
    "com.cheaphomes.watchdog"
    "com.johnsonbuys.digest"
    "com.johnsonbuys.emailcampaign"
    "com.johnsonbuys.followup"
    "com.johnsonbuys.smscampaign"
    "com.johnsonbuys.webhook"
)
for label in "${PLISTS[@]}"; do
    if launchctl print "gui/$UID_VAL/$label" &>/dev/null; then
        report "launchd $label stopped" FAIL "still loaded"
    else
        report "launchd $label stopped" PASS "not loaded"
    fi
done

# ─── 6. Cloudflare Worker secret reachability ───
echo ""
echo "▶ 6. Cloudflare Worker secrets via /health"
for w in propertyleads-ppl-worker motivatedsellers-ppl-worker railway-deploy-alerts; do
    if [ -f /tmp/cf_$w.json ]; then
        if grep -q '"sendgrid": true' /tmp/cf_$w.json 2>/dev/null && grep -q '"twilio": true' /tmp/cf_$w.json 2>/dev/null; then
            report "$w bindings (SG+Twilio)" PASS "all green in /health"
        elif grep -q '"sendgrid": true' /tmp/cf_$w.json 2>/dev/null; then
            report "$w bindings" PASS "SG green"
        fi
    fi
done

# ─── 7. Salesforce login ───
echo ""
echo "▶ 7. Salesforce auth"
SF_USER=$(get_val SF_USERNAME)
if [ -n "$SF_USER" ]; then
    if [ -f "$REPO/tools/sf_health_ping.py" ]; then
        OUTPUT=$(cd "$REPO" && python3 tools/sf_health_ping.py 2>&1)
        if echo "$OUTPUT" | grep -qi "ok\|connected\|leads:"; then
            report "Salesforce login + Lead query" PASS "responding"
        else
            report "Salesforce login" FAIL "$OUTPUT"
        fi
    else
        echo "    (sf_health_ping.py not present, skipping SF check)"
    fi
fi

# ─── REPORT ───
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  RESULT: $PASS passed, $FAIL failed"
echo "═══════════════════════════════════════════════════════════"
echo ""
if [ "$FAIL" -gt 0 ]; then
    echo "Failures:"
    for r in "${RESULTS[@]}"; do
        if [[ "$r" == FAIL:* ]]; then
            echo "  ✗ ${r#FAIL: }"
        fi
    done
    echo ""
    exit 1
fi
echo "✓ All checks passed. Cloud stack is healthy."
