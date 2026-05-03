#!/usr/bin/env bash
# Opens the Cloudflare API token page in Chrome and prints the next steps.
# Run with: bash tools/open_cf_token_page.sh

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  OPENING CLOUDFLARE API TOKEN PAGE IN CHROME..."
echo "═══════════════════════════════════════════════════════"
echo ""

# Open the create-token page directly in Chrome
open -a "Google Chrome" "https://dash.cloudflare.com/profile/api-tokens"

sleep 2

echo "Chrome should now be on the API Tokens page."
echo ""
echo "DO THIS IN CHROME (not Terminal):"
echo ""
echo "  1. Click the blue 'Create Token' button"
echo "  2. Find the 'Edit Cloudflare Workers' row, click 'Use template'"
echo "  3. Scroll to bottom (don't change anything), click 'Continue to summary'"
echo "  4. Click 'Create Token'"
echo "  5. COPY the token shown on the green confirmation screen"
echo "  6. Paste that token back into the Claude chat (NOT Terminal)"
echo ""
echo "═══════════════════════════════════════════════════════"
echo ""
