#!/usr/bin/env bash
# Phase 4d cleanup: fix git remote → push code → open secrets page for verification.
# Run: bash tools/finish_phase4d.sh

set -e

REPO="qvxmrcq97p-jpg/dealmatcher"
NEW_REMOTE="git@github.com:$REPO.git"

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  PHASE 4D CLEANUP"
echo "═══════════════════════════════════════════════════"
echo ""

# 1) Show current remote
echo "→ Current git remote:"
git remote -v
echo ""

# 2) Update remote to point to qvxmrcq97p-jpg
echo "→ Updating remote to $NEW_REMOTE..."
git remote set-url origin "$NEW_REMOTE"
git remote -v
echo ""

# 3) Push to GitHub
echo "→ Pushing main branch..."
if git push -u origin main 2>&1; then
    echo ""
    echo "✓ Code pushed to $REPO"
else
    echo ""
    echo "✗ Push failed. Possible causes:"
    echo "  - Your SSH key isn't added to the qvxmrcq97p-jpg GitHub account"
    echo "  - The repo has an existing different commit history"
    echo ""
    echo "If you see 'Permission denied (publickey)':"
    echo "  → Run: cat ~/.ssh/id_ed25519.pub | pbcopy"
    echo "  → Then add the key at https://github.com/settings/keys"
    echo ""
    echo "If you see '! [rejected]':"
    echo "  → Run: git push -u origin main --force"
    echo "  (This is safe because the remote repo is empty.)"
    exit 1
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo "  OPENING SECRETS PAGE TO VERIFY"
echo "═══════════════════════════════════════════════════"
echo ""

open -a "Google Chrome" "https://github.com/$REPO/settings/secrets/actions"
sleep 2

echo "Chrome should now be on the secrets page."
echo "You should see TWO secrets listed:"
echo ""
echo "   • CLOUDFLARE_API_TOKEN     — Updated <recently>"
echo "   • CLOUDFLARE_ACCOUNT_ID    — Updated <recently>"
echo ""
echo "If both are listed → Phase 4d COMPLETE. Tell Claude in chat."
echo "If only one or zero → re-run paste_gh_secrets.sh to set the missing one(s)."
echo ""
