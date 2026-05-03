#!/usr/bin/env bash
# deploy.sh — one-command deploy of propertyleads-ppl-worker
#
# Reads secrets from ~/dealmatcher/.env.cheaphomesfla, pushes them to
# Cloudflare via `wrangler secret bulk`, then deploys the worker.
#
# Run:
#     cd ~/Desktop/propertyleads-worker
#     chmod +x deploy.sh    # first time only
#     ./deploy.sh

set -e

cd "$(dirname "$0")"

# ---------------------------------------------------------------------------
# Sanity checks
# ---------------------------------------------------------------------------

ENV_FILE="$HOME/dealmatcher/.env.cheaphomesfla"
if [ ! -f "$ENV_FILE" ]; then
    echo "❌ Cannot find $ENV_FILE"
    echo "   This script reads secrets from there. Aborting."
    exit 1
fi

if ! command -v wrangler &>/dev/null; then
    echo "❌ wrangler not installed."
    echo "   Run: npm install -g wrangler"
    exit 1
fi

# Confirm wrangler is logged in
if ! wrangler whoami &>/dev/null; then
    echo "ℹ️  Not logged into Cloudflare. Running 'wrangler login' (browser opens)..."
    wrangler login
fi

# ---------------------------------------------------------------------------
# Build the secrets JSON
#
# Read the env file via Python (NOT shell `source`) — the file has values
# with spaces (Gmail app passwords) that break `source` but Python parses
# them correctly line-by-line.
# ---------------------------------------------------------------------------
SECRETS_FILE="$(mktemp -t propertyleads-secrets.XXXXXX.json)"

python3 - "$ENV_FILE" <<'PYEOF' > "$SECRETS_FILE"
import json, sys
env_path = sys.argv[1]
env = {}
with open(env_path) as f:
    for line in f:
        line = line.rstrip("\n")
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        env[k.strip()] = v.strip()

required = ["SF_USERNAME", "SF_PASSWORD", "SF_SECURITY_TOKEN",
            "SENDGRID_API_KEY", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"]
missing = [k for k in required if not env.get(k)]
if missing:
    sys.stderr.write(f"ERROR: missing required vars in env file: {missing}\n")
    sys.exit(2)

secrets = {
    "SF_USERNAME":        env["SF_USERNAME"],
    "SF_PASSWORD":        env["SF_PASSWORD"],
    "SF_SECURITY_TOKEN":  env["SF_SECURITY_TOKEN"],
    "SF_LOGIN_DOMAIN":    "login",
    "SENDGRID_API_KEY":   env["SENDGRID_API_KEY"],
    "FROM_EMAIL":         "info@johnsonbuys.com",
    "FROM_NAME":          "Chris @ Johnson Buys",
    "ALERT_TO":           "info@johnsonbuys.com",
    "TWILIO_ACCOUNT_SID": env["TWILIO_ACCOUNT_SID"],
    "TWILIO_AUTH_TOKEN":  env["TWILIO_AUTH_TOKEN"],
    "TWILIO_FROM":        "+19549534554",
}
print(json.dumps(secrets))
PYEOF

echo
echo "📤 Pushing 11 secrets to Cloudflare..."
# wrangler secret bulk reads JSON from stdin, applies all secrets at once
wrangler secret bulk "$SECRETS_FILE"

# Cleanup secrets file immediately
shred -u "$SECRETS_FILE" 2>/dev/null || rm -f "$SECRETS_FILE"

echo
echo "🚀 Deploying worker..."
wrangler deploy

echo
echo "═══════════════════════════════════════════════════════════════════"
echo "✅ DEPLOY COMPLETE"
echo "═══════════════════════════════════════════════════════════════════"
echo
echo "Your worker URL is in the deploy output above (https://propertyleads-ppl-worker.<subdomain>.workers.dev)"
echo
echo "Next steps:"
echo "  1. Test with curl (see DEPLOY.md for the exact command)"
echo "  2. Verify a test Lead lands in Salesforce with LeadSource='Property Leads PPL'"
echo "  3. Delete the test Lead"
echo "  4. Paste the worker URL into propertyleads.com webhook config"
echo "  5. Unpause propertyleads.com lead delivery"
echo
