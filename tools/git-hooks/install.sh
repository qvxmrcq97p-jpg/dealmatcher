#!/usr/bin/env bash
# Install the pre-commit secret-scanning hook into this repo's .git/hooks/
#
# Run once:
#     bash tools/git-hooks/install.sh
#
# Idempotent — safe to re-run.

set -e
REPO_ROOT="$(git rev-parse --show-toplevel)"
SRC="$REPO_ROOT/tools/git-hooks/pre-commit"
DST="$REPO_ROOT/.git/hooks/pre-commit"

if [ ! -f "$SRC" ]; then
    echo "✗ Source hook not found at $SRC"
    exit 1
fi

cp "$SRC" "$DST"
chmod +x "$DST"
echo "✓ pre-commit hook installed at $DST"
echo
echo "Quick test (will refuse a fake secret):"
echo "    cd $REPO_ROOT"
echo "    echo 'SF_PASSWORD = \"realbutfake\"' > /tmp/leak.py"
echo "    git add /tmp/leak.py 2>/dev/null || true"
echo "    git commit -m test  # should be REFUSED"
echo
echo "Bypass (rare, never for real secrets):  git commit --no-verify"
