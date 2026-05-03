#!/usr/bin/env bash
# verify_workers.sh — Phase 3 verification helper.
#
# After you `wrangler deploy` the 5 workers + create their KV namespaces,
# run this to confirm each one responds correctly. Hits /health on every
# worker, then optionally POSTs the test payload from each worker dir.
#
# Run:
#     bash tools/verify_workers.sh             # health-only (safe, no SF writes)
#     bash tools/verify_workers.sh --full      # also POSTs test payloads
#                                                (creates 1 SF Lead per PPL worker
#                                                 + 1 Task per SG event — clean up after)
#     bash tools/verify_workers.sh --secret=XYZ  # required for some workers
#
# Each test prints PASS or FAIL. Exit code = number of FAILs.

set -u

red()    { printf "\033[0;31m%s\033[0m\n" "$*"; }
yellow() { printf "\033[0;33m%s\033[0m\n" "$*"; }
green()  { printf "\033[0;32m%s\033[0m\n" "$*"; }
hdr()    { echo; printf "\033[1;34m──── %s ────\033[0m\n" "$*"; }

mode="health"
secret=""
for arg in "$@"; do
    case "$arg" in
        --full) mode="full" ;;
        --secret=*) secret="${arg#*=}" ;;
    esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Worker registry: name | base URL | needs_secret_for_post
workers=(
    "propertyleads-ppl-worker|https://propertyleads-ppl-worker.cbfcalcio5.workers.dev|0"
    "motivatedsellers-ppl-worker|https://motivatedsellers-ppl-worker.cbfcalcio5.workers.dev|0"
    "cheaphomesfla-whatsapp-webhook|https://cheaphomesfla-whatsapp-webhook.cbfcalcio5.workers.dev|1"
    "sendgrid-events|https://sendgrid-events.cbfcalcio5.workers.dev|0"
    "railway-deploy-alerts|https://railway-deploy-alerts.cbfcalcio5.workers.dev|1"
)

# Map worker name → test_payload.json relative path
declare -A payload_path=(
    ["propertyleads-ppl-worker"]="cloudflare/propertyleads-worker/test_payload.json"
    ["motivatedsellers-ppl-worker"]="cloudflare/motivatedsellers-worker/test_payload.json"
    ["cheaphomesfla-whatsapp-webhook"]="cloudflare/whatsapp-worker/test_payload.json"
    ["sendgrid-events"]="cloudflare/sendgrid-events/test_payload.json"
    ["railway-deploy-alerts"]="cloudflare/railway-deploy-alerts/test_payload.json"
)

fails=0

# ── 1. Health checks (safe, no side effects) ────────────────────────
hdr "Health probes (5 workers)"
for entry in "${workers[@]}"; do
    IFS="|" read -r name url needs_secret <<< "$entry"
    body=$(curl -s -m 10 -o /tmp/health_resp -w "%{http_code}" "$url/health")
    if [ "$body" = "200" ]; then
        ok=$(jq -r '.ok // false' /tmp/health_resp 2>/dev/null || echo "false")
        last=$(jq -r '.last_lead_at // .last_message_at // .last_event_at // .last_alert_at // "none"' /tmp/health_resp 2>/dev/null)
        if [ "$ok" = "true" ]; then
            green "✓ $name — /health OK (last activity: $last)"
        else
            red "✗ $name — /health 200 but ok=false"
            fails=$((fails+1))
        fi
    else
        red "✗ $name — /health HTTP $body"
        cat /tmp/health_resp
        fails=$((fails+1))
    fi
done

if [ "$mode" != "full" ]; then
    echo
    if [ $fails -eq 0 ]; then
        green "ALL 5 WORKERS HEALTHY"
        echo "(Run with --full to also POST test payloads — creates SF Leads + Tasks.)"
    else
        red "$fails health probe(s) failed."
    fi
    exit $fails
fi

# ── 2. Full POST tests ───────────────────────────────────────────────
hdr "POST tests (creates real SF records — clean up after)"

for entry in "${workers[@]}"; do
    IFS="|" read -r name url needs_secret <<< "$entry"
    payload_file="$REPO_ROOT/${payload_path[$name]}"

    if [ ! -f "$payload_file" ]; then
        yellow "⚠ $name — no test payload, skipping POST"
        continue
    fi

    target_url="$url"
    if [ "$needs_secret" = "1" ]; then
        if [ -z "$secret" ]; then
            yellow "⚠ $name — needs --secret=, skipping POST"
            continue
        fi
        target_url="$url/?secret=$secret"
    fi

    echo
    echo "POST → $name"
    code=$(curl -s -m 30 -o /tmp/post_resp -w "%{http_code}" \
        -X POST "$target_url" \
        -H "Content-Type: application/json" \
        --data @"$payload_file")
    body=$(cat /tmp/post_resp)
    if [ "$code" = "200" ]; then
        green "  ✓ HTTP 200"
        echo "  Response: $body" | head -c 300
        echo
    else
        red "  ✗ HTTP $code"
        echo "  Response: $body" | head -c 500
        echo
        fails=$((fails+1))
    fi
done

echo
if [ $fails -eq 0 ]; then
    green "ALL POST TESTS PASSED"
    yellow "Cleanup: in Salesforce, delete any Leads with LastName = '*_TEST*'."
    yellow "         In SF Tasks, delete any with Subject containing 'test+' email."
else
    red "$fails test(s) failed."
fi
exit $fails
