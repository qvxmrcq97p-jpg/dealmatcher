#!/usr/bin/env bash
# Walks through pasting GitHub Action secrets one at a time using the clipboard.
# Run: bash tools/paste_gh_secrets.sh

# Reads CLOUDFLARE_API_TOKEN from environment or prompts. Never hardcode secrets.
if [ -z "${CLOUDFLARE_API_TOKEN:-}" ]; then
    read -rsp "Cloudflare API Token: " CF_TOKEN
    echo
else
    CF_TOKEN="$CLOUDFLARE_API_TOKEN"
fi
CF_ACCOUNT="${CLOUDFLARE_ACCOUNT_ID:-7c8851172228e9e446dbfb4c53e8badf}"
URL="https://github.com/qvxmrcq97p-jpg/dealmatcher/settings/secrets/actions"

clear
echo ""
echo "════════════════════════════════════════════════════════════"
echo "  GITHUB ACTIONS SECRETS — STEP-BY-STEP CLIPBOARD HELPER"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "I'll copy each value to your clipboard. You just paste it (Cmd+V)"
echo "into the right field in Chrome. Press Return between each step."
echo ""
echo "Press Return to begin..."
read -r

# Step 1: open Chrome
echo ""
echo "→ Opening Chrome to the GitHub secrets page..."
open -a "Google Chrome" "$URL"
sleep 2

# Step 2: secret #1 name
echo ""
echo "════════ SECRET 1 of 2 ════════"
echo ""
echo "1. In Chrome, click the green 'New repository secret' button (top right)"
echo "2. In the 'Name' field at the top of the form, type EXACTLY:"
echo ""
echo "      CLOUDFLARE_API_TOKEN"
echo ""
echo "3. Then click in the 'Secret' field below it"
echo "4. Press Cmd+V to paste — I've put the token on your clipboard NOW"
echo "5. Click the green 'Add secret' button"
echo ""
printf "%s" "$CF_TOKEN" | pbcopy
echo "✓ Token copied to clipboard."
echo ""
echo "Press Return when you've clicked 'Add secret'..."
read -r

# Step 3: secret #2 name
echo ""
echo "════════ SECRET 2 of 2 ════════"
echo ""
echo "1. Click 'New repository secret' AGAIN"
echo "2. In the 'Name' field, type EXACTLY:"
echo ""
echo "      CLOUDFLARE_ACCOUNT_ID"
echo ""
echo "3. Click in the 'Secret' field"
echo "4. Press Cmd+V — I've put the account ID on your clipboard NOW"
echo "5. Click 'Add secret'"
echo ""
printf "%s" "$CF_ACCOUNT" | pbcopy
echo "✓ Account ID copied to clipboard."
echo ""
echo "Press Return when you've clicked 'Add secret'..."
read -r

echo ""
echo "════════ DONE ════════"
echo ""
echo "You should see both secrets listed on the page:"
echo "   CLOUDFLARE_API_TOKEN     • Updated now"
echo "   CLOUDFLARE_ACCOUNT_ID    • Updated now"
echo ""
echo "Switch back to the Claude chat and tell me you see both."
echo ""
