#!/usr/bin/env bash
# Set GitHub Actions secrets for the CF Worker auto-deploy workflow.
# Tries gh CLI first; falls back to opening the browser.

set -e

# Reads CLOUDFLARE_API_TOKEN from environment or prompts. Never hardcode secrets.
if [ -z "${CLOUDFLARE_API_TOKEN:-}" ]; then
    read -rsp "Cloudflare API Token: " CF_TOKEN
    echo
else
    CF_TOKEN="$CLOUDFLARE_API_TOKEN"
fi
CF_ACCOUNT="${CLOUDFLARE_ACCOUNT_ID:-7c8851172228e9e446dbfb4c53e8badf}"
REPO="cbfcalcio5/dealmatcher"

echo ""
echo "═══ SETTING GITHUB ACTIONS SECRETS ═══"
echo ""

if ! command -v gh &>/dev/null; then
    echo "✗ gh CLI not installed. Falling back to manual browser flow..."
    echo ""
    echo "Opening Chrome to the GitHub secrets page..."
    open -a "Google Chrome" "https://github.com/$REPO/settings/secrets/actions"
    sleep 2
    echo ""
    echo "Click 'New repository secret' twice — once for each:"
    echo ""
    echo "  Name:  CLOUDFLARE_API_TOKEN"
    echo "  Value: $CF_TOKEN"
    echo ""
    echo "  Name:  CLOUDFLARE_ACCOUNT_ID"
    echo "  Value: $CF_ACCOUNT"
    echo ""
    exit 0
fi

# Check gh auth
if ! gh auth status &>/dev/null; then
    echo "gh installed but not authenticated. Run 'gh auth login' first."
    echo "Falling back to browser..."
    open -a "Google Chrome" "https://github.com/$REPO/settings/secrets/actions"
    exit 0
fi

# Try the configured repo first; if that 404s, try the alt org name
try_set() {
    local repo="$1"
    echo "Trying repo: $repo"
    if gh secret set CLOUDFLARE_API_TOKEN --body "$CF_TOKEN" --repo "$repo" 2>&1 | grep -q "Set"; then
        gh secret set CLOUDFLARE_ACCOUNT_ID --body "$CF_ACCOUNT" --repo "$repo"
        echo ""
        echo "✓ Both secrets set in $repo"
        return 0
    fi
    return 1
}

# First try the cbfcalcio5 username
if gh secret set CLOUDFLARE_API_TOKEN --body "$CF_TOKEN" --repo "$REPO" 2>/tmp/gh_err; then
    gh secret set CLOUDFLARE_ACCOUNT_ID --body "$CF_ACCOUNT" --repo "$REPO"
    echo ""
    echo "✓ Both secrets set in $REPO"
else
    err=$(cat /tmp/gh_err)
    echo "✗ Failed on $REPO:"
    echo "$err"
    # Try alt repo
    if echo "$err" | grep -qiE "not found|404"; then
        ALT="qvxmrcq97p-jpg/dealmatcher"
        echo ""
        echo "Trying alt repo: $ALT"
        if gh secret set CLOUDFLARE_API_TOKEN --body "$CF_TOKEN" --repo "$ALT"; then
            gh secret set CLOUDFLARE_ACCOUNT_ID --body "$CF_ACCOUNT" --repo "$ALT"
            echo ""
            echo "✓ Both secrets set in $ALT"
        fi
    fi
fi

echo ""
echo "═══ DONE — verifying ═══"
gh secret list --repo "$REPO" 2>/dev/null || gh secret list --repo "qvxmrcq97p-jpg/dealmatcher" 2>/dev/null
