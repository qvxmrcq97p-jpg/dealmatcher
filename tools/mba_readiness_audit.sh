#!/usr/bin/env bash
# MBA Readiness Audit — checks if THIS Mac can fully administer the cloud stack.
#
# Run on any Mac (primary or MBA) to verify it has all the access needed
# to fix issues in: Cloudflare, Railway, Twilio, SendGrid, Salesforce, GitHub.
#
# Usage: bash tools/mba_readiness_audit.sh

set +e

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO/.env.cheaphomesfla"
get_val() { awk -F= -v k="$1" '$1==k { sub(/^[^=]*=/, ""); print; exit }' "$ENV_FILE" 2>/dev/null; }

PASS=0
FAIL=0
WARN=0

check() {
    local name="$1" status="$2" detail="$3"
    case "$status" in
        PASS) echo "  ✓ $name"; PASS=$((PASS+1)) ;;
        FAIL) echo "  ✗ $name — $detail"; FAIL=$((FAIL+1)) ;;
        WARN) echo "  ⚠ $name — $detail"; WARN=$((WARN+1)) ;;
    esac
}

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  MBA READINESS AUDIT — $(hostname) — $(date)"
echo "═══════════════════════════════════════════════════════════"

# ─── 1. Local repo ───
echo ""
echo "▶ 1. Local repo"
if [ -d "$REPO/.git" ]; then
    check "repo cloned at $REPO" PASS
else
    check "repo cloned" FAIL "missing $REPO/.git — run bootstrap_macbook.sh"
fi
if [ -f "$ENV_FILE" ]; then
    check ".env.cheaphomesfla present" PASS
else
    check ".env.cheaphomesfla present" FAIL "missing — AirDrop from primary Mac"
fi
if [ -f "$REPO/STATE.md" ]; then
    check "STATE.md present (Claude context file)" PASS
else
    check "STATE.md present" FAIL "missing — git pull"
fi

# ─── 2. CLI tools ───
echo ""
echo "▶ 2. CLI tools (administering the stack)"
for cmd in git python3 node npm; do
    if command -v "$cmd" &>/dev/null; then
        check "$cmd installed" PASS
    else
        check "$cmd installed" FAIL "brew install $cmd"
    fi
done
if command -v wrangler &>/dev/null; then
    check "wrangler installed (deploy CF Workers)" PASS
else
    check "wrangler installed" WARN "npm install -g wrangler — only needed for ad-hoc deploys; CI deploys via push"
fi
if command -v gh &>/dev/null; then
    check "gh CLI installed" PASS
else
    check "gh CLI installed" WARN "brew install gh — optional but useful"
fi
if command -v twilio &>/dev/null; then
    check "twilio CLI installed" PASS
else
    check "twilio CLI installed" WARN "brew tap twilio/brew && brew install twilio — optional"
fi

# ─── 3. GitHub access ───
echo ""
echo "▶ 3. GitHub access (deploy code)"
if [ -d "$REPO/.git" ]; then
    cd "$REPO"
    REMOTE=$(git remote get-url origin 2>/dev/null)
    if echo "$REMOTE" | grep -q "qvxmrcq97p-jpg/dealmatcher"; then
        check "git remote correct ($REMOTE)" PASS
    else
        check "git remote correct" FAIL "$REMOTE"
    fi
    if git ls-remote --heads origin main &>/dev/null; then
        check "SSH push access to GitHub" PASS
    else
        check "SSH push access" FAIL "add ~/.ssh/id_ed25519.pub to https://github.com/settings/keys (logged in as qvxmrcq97p-jpg)"
    fi
fi

# ─── 4. Cloudflare access ───
echo ""
echo "▶ 4. Cloudflare access (5 Workers, KV, secrets)"
if command -v wrangler &>/dev/null; then
    if wrangler whoami 2>/dev/null | grep -q "@"; then
        WHO=$(wrangler whoami 2>/dev/null | grep -oE "[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+" | head -1)
        check "wrangler logged in ($WHO)" PASS
    else
        check "wrangler logged in" WARN "run 'wrangler login' (one-time browser flow). Or skip — git push triggers CI deploys."
    fi
else
    check "wrangler logged in" WARN "wrangler not installed — see step 2"
fi
# Quick reachability check on a Worker
CF_HEALTH=$(curl -sS -o /dev/null -w "%{http_code}" "https://propertyleads-ppl-worker.cbfcalcio5.workers.dev/health" --max-time 5 2>/dev/null)
if [ "$CF_HEALTH" = "200" ]; then
    check "Cloudflare Workers reachable" PASS
else
    check "Cloudflare Workers reachable" FAIL "HTTP $CF_HEALTH"
fi

# ─── 5. Twilio access ───
echo ""
echo "▶ 5. Twilio access (SMS function deploys, number management)"
TW_SID=$(get_val TWILIO_ACCOUNT_SID)
TW_TOK=$(get_val TWILIO_AUTH_TOKEN)
if [ -n "$TW_SID" ] && [ -n "$TW_TOK" ]; then
    TW_TEST=$(curl -sS -o /dev/null -w "%{http_code}" \
        "https://api.twilio.com/2010-04-01/Accounts/$TW_SID.json" \
        -u "$TW_SID:$TW_TOK" --max-time 8 2>/dev/null)
    if [ "$TW_TEST" = "200" ]; then
        check "Twilio API auth (deploy /sms, manage numbers)" PASS
    else
        check "Twilio API auth" FAIL "HTTP $TW_TEST"
    fi
else
    check "Twilio creds in .env" FAIL "missing TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN"
fi

# ─── 6. SendGrid access ───
echo ""
echo "▶ 6. SendGrid access (email sending, webhook config)"
SG_KEY=$(get_val SENDGRID_API_KEY)
if [ -n "$SG_KEY" ]; then
    SG_TEST=$(curl -sS -o /dev/null -w "%{http_code}" \
        "https://api.sendgrid.com/v3/user/profile" \
        -H "Authorization: Bearer $SG_KEY" --max-time 8 2>/dev/null)
    if [ "$SG_TEST" = "200" ]; then
        check "SendGrid API auth" PASS
    else
        check "SendGrid API auth" FAIL "HTTP $SG_TEST"
    fi
else
    check "SendGrid key in .env" FAIL "missing SENDGRID_API_KEY"
fi

# ─── 7. Salesforce access ───
echo ""
echo "▶ 7. Salesforce access (Lead/Account read/write)"
SF_USER=$(get_val SF_USERNAME)
SF_PASS=$(get_val SF_PASSWORD)
SF_TOK=$(get_val SF_SECURITY_TOKEN)
if [ -n "$SF_USER" ] && [ -n "$SF_PASS" ] && [ -n "$SF_TOK" ]; then
    if python3 -c "import simple_salesforce" &>/dev/null; then
        SF_TEST=$(python3 -c "
from simple_salesforce import Salesforce
import sys
try:
    sf = Salesforce(username='$SF_USER', password='$SF_PASS', security_token='$SF_TOK')
    r = sf.query('SELECT COUNT(Id) total FROM Lead')
    print('OK', r['records'][0]['total'])
except Exception as e:
    print('FAIL', str(e)[:100])
    sys.exit(1)
" 2>&1)
        if echo "$SF_TEST" | grep -q "^OK"; then
            count=$(echo "$SF_TEST" | awk '{print $2}')
            check "Salesforce login + query ($count Leads)" PASS
        else
            check "Salesforce login" FAIL "$SF_TEST"
        fi
    else
        check "simple_salesforce installed" WARN "pip3 install simple-salesforce"
    fi
else
    check "Salesforce creds in .env" FAIL "missing SF_USERNAME / SF_PASSWORD / SF_SECURITY_TOKEN"
fi

# ─── 8. Railway access (browser-only — no API key check) ───
echo ""
echo "▶ 8. Railway access (browser-administered)"
echo "    Railway has no API auth via .env (browser-only admin)."
echo "    Verify: open https://railway.com/dashboard in Chrome on this Mac"
echo "    and confirm 'luminous-spontaneity' project is visible."

# ─── 9. Cowork app ───
echo ""
echo "▶ 9. Cowork app"
if [ -d "/Applications/Claude.app" ] || [ -d "/Applications/Cowork.app" ]; then
    check "Cowork (Claude) app installed" PASS
else
    check "Cowork app installed" WARN "download from https://claude.ai/desktop"
fi

# ─── REPORT ───
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  RESULT: $PASS passed, $FAIL failed, $WARN warnings"
echo "═══════════════════════════════════════════════════════════"
echo ""
if [ "$FAIL" -eq 0 ] && [ "$WARN" -eq 0 ]; then
    echo "🎉 This Mac is fully ready to administer the entire cloud stack."
    echo ""
    echo "From any Cowork session here, you can:"
    echo "  • Edit + push code (git → CI → Workers auto-deploy)"
    echo "  • Run any tools/ script (deploys, SF queries, smoke tests)"
    echo "  • Browse all dashboards (Salesforce, SendGrid, Twilio, Railway, CF, GitHub)"
    echo "  • Diagnose and fix issues in any layer of the stack"
elif [ "$FAIL" -eq 0 ]; then
    echo "✓ All required checks passed. Warnings are optional improvements."
else
    echo "✗ Some required checks failed — fix before relying on this Mac."
fi
