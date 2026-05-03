#!/usr/bin/env bash
# Bootstraps the dealmatcher repo on a NEW Mac (e.g. MacBook Air).
# Idempotent — safe to re-run.
#
# Usage on the new Mac:
#   curl -O https://raw.githubusercontent.com/qvxmrcq97p-jpg/dealmatcher/main/tools/bootstrap_macbook.sh
#   bash bootstrap_macbook.sh
#
# OR (after manually cloning the repo):
#   bash tools/bootstrap_macbook.sh

set -e

REPO_URL="git@github.com:qvxmrcq97p-jpg/dealmatcher.git"
REPO_HTTPS="https://github.com/qvxmrcq97p-jpg/dealmatcher.git"
REPO_DIR="$HOME/dealmatcher"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  MACBOOK BOOTSTRAP — dealmatcher dev environment"
echo "═══════════════════════════════════════════════════════════"
echo ""

# ─── 1. Homebrew ─────────────────────────────────────
if ! command -v brew &>/dev/null; then
    echo "→ Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    if [ -d /opt/homebrew/bin ]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
else
    echo "✓ Homebrew installed"
fi

# ─── 2. CLI tools ────────────────────────────────────
echo ""
echo "→ Installing CLI tools (git, python3, node, gh, wrangler, twilio)..."
for pkg in git python@3.11 node gh; do
    if brew list "$pkg" &>/dev/null; then
        echo "  ✓ $pkg already installed"
    else
        echo "  · installing $pkg..."
        brew install "$pkg" --quiet || echo "  ! $pkg install failed (continuing)"
    fi
done

# Wrangler via npm
if ! command -v wrangler &>/dev/null; then
    echo "  · installing wrangler globally..."
    npm install -g wrangler@latest || echo "  ! wrangler install failed"
else
    echo "  ✓ wrangler already installed"
fi

# Twilio CLI via brew tap
if ! command -v twilio &>/dev/null; then
    echo "  · installing twilio CLI..."
    brew tap twilio/brew && brew install twilio || echo "  ! twilio CLI install failed (optional)"
else
    echo "  ✓ twilio CLI already installed"
fi

# ─── 3. SSH key for GitHub ──────────────────────────
echo ""
echo "→ Checking SSH key..."
if [ -f "$HOME/.ssh/id_ed25519" ]; then
    echo "  ✓ SSH key already exists at ~/.ssh/id_ed25519"
else
    echo "  · generating ed25519 key..."
    ssh-keygen -t ed25519 -C "cbfcalcio5@me.com" -N "" -f "$HOME/.ssh/id_ed25519"
    echo ""
    echo "  ⚠ NEW SSH KEY — add to GitHub:"
    echo ""
    cat "$HOME/.ssh/id_ed25519.pub"
    echo ""
    echo "  Copy the line above. Open https://github.com/settings/keys"
    echo "  Click 'New SSH key', name it 'MacBook Air <date>', paste, save."
    echo ""
    echo "  Press Return when done..."
    read -r
fi

# Add SSH key to agent
eval "$(ssh-agent -s)" >/dev/null 2>&1 || true
ssh-add --apple-use-keychain "$HOME/.ssh/id_ed25519" 2>/dev/null || ssh-add "$HOME/.ssh/id_ed25519" 2>/dev/null || true

# Test GitHub SSH
echo ""
echo "→ Testing GitHub SSH access..."
SSH_RESULT=$(ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -T git@github.com 2>&1 || true)
if echo "$SSH_RESULT" | grep -qi "successfully authenticated"; then
    echo "  ✓ GitHub SSH works ($(echo "$SSH_RESULT" | grep -oE 'Hi [^!]+' | head -1))"
else
    echo "  ! GitHub SSH not yet working — may need to add key first"
fi

# ─── 4. Clone repo ──────────────────────────────────
echo ""
if [ -d "$REPO_DIR/.git" ]; then
    echo "→ Repo already exists at $REPO_DIR — pulling latest..."
    cd "$REPO_DIR"
    git pull --rebase || echo "  ! pull failed (resolve manually)"
else
    echo "→ Cloning repo to $REPO_DIR..."
    if git clone "$REPO_URL" "$REPO_DIR" 2>/dev/null; then
        echo "  ✓ Cloned via SSH"
    elif git clone "$REPO_HTTPS" "$REPO_DIR" 2>/dev/null; then
        echo "  ✓ Cloned via HTTPS (you'll need PAT for pushes)"
    else
        echo "  ✗ Clone failed. Add your SSH key to GitHub first (see above)."
        exit 1
    fi
fi

# ─── 5. .env.cheaphomesfla ──────────────────────────
echo ""
echo "→ Checking for credentials file..."
ENV_FILE="$REPO_DIR/.env.cheaphomesfla"
if [ -f "$ENV_FILE" ]; then
    echo "  ✓ $ENV_FILE present"
else
    echo "  ⚠ $ENV_FILE NOT found"
    echo ""
    echo "  This file holds all the API credentials and is never committed to GitHub."
    echo "  Transfer it from your primary Mac:"
    echo ""
    echo "    From primary Mac:"
    echo "      open -a 'AirDrop' ~/dealmatcher/.env.cheaphomesfla"
    echo ""
    echo "    Then on this Mac, save the AirDropped file to:"
    echo "      $ENV_FILE"
    echo ""
    echo "    OR via scp (if both Macs are on the same network):"
    echo "      scp <user>@<primary-mac>.local:~/dealmatcher/.env.cheaphomesfla $ENV_FILE"
    echo ""
    echo "  Press Return when the file is in place..."
    read -r
    if [ ! -f "$ENV_FILE" ]; then
        echo "  ! Still missing. Some scripts will fail without it."
    fi
fi

# ─── 6. Wrangler login ──────────────────────────────
echo ""
echo "→ Wrangler login (opens browser for OAuth)..."
if cd "$REPO_DIR" && wrangler whoami 2>/dev/null | grep -q "@"; then
    echo "  ✓ Wrangler already logged in"
else
    echo "  · run 'wrangler login' to authenticate"
    echo "  · skipping for now — auto-deploy via GitHub Actions still works"
fi

# ─── 7. gh CLI auth ─────────────────────────────────
echo ""
echo "→ GitHub CLI auth..."
if gh auth status &>/dev/null; then
    echo "  ✓ gh CLI already authenticated"
else
    echo "  · run 'gh auth login' to authenticate (optional)"
fi

# ─── 8. Final status ────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  BOOTSTRAP COMPLETE"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "Next:"
echo "  1. cd ~/dealmatcher"
echo "  2. Open Cowork → select ~/dealmatcher folder"
echo "  3. First prompt to Claude: 'Read STATE.md and continue.'"
echo ""
echo "Verify with:"
echo "  bash tools/smoke_test_all.sh"
echo ""
echo "Note: this Mac doesn't run any cron jobs — all scheduling is on Railway."
echo "      Use this Mac for: code edits, ad-hoc scripts, browsing dashboards."
echo ""
