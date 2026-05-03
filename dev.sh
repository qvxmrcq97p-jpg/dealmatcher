#!/usr/bin/env bash
# dev.sh — one-stop shell for common dev tasks.
#
# Usage:
#   ./dev.sh              # show this help
#   ./dev.sh test         # run all unit tests
#   ./dev.sh pdfs         # regenerate all 5 PDFs
#   ./dev.sh verify       # hit all 5 CF Worker /health endpoints
#   ./dev.sh kpi          # print today's KPI snapshot (no email)
#   ./dev.sh health       # cloud-health probe (print, no email)
#   ./dev.sh investors    # build investor list CSV from SF + senders
#   ./dev.sh push         # add + commit + push (auto-message from staged files)
#   ./dev.sh deploy-cf    # deploy ALL Cloudflare Workers (uses wrangler)
#   ./dev.sh tail <svc>   # tail Railway logs for a service
#   ./dev.sh logs <svc>   # last 100 Railway log lines for a service
#   ./dev.sh sf-test      # confirm SF login works locally
#   ./dev.sh smoke        # full pre-deploy smoke test (SF + Twilio + SendGrid + FLS)
#
# Each command runs from repo root regardless of where you invoke it.

set -e
cd "$(dirname "${BASH_SOURCE[0]}")"

cmd="${1:-help}"
shift || true

bold()   { printf "\033[1;34m%s\033[0m\n" "$*"; }
green()  { printf "\033[0;32m%s\033[0m\n" "$*"; }
red()    { printf "\033[0;31m%s\033[0m\n" "$*"; }

case "$cmd" in
    help|"")
        sed -n '2,18p' "$0" | sed 's/^# //; s/^#//'
        ;;

    test)
        bold "Running unit tests..."
        python3 -m unittest discover tests/ -v
        ;;

    pdfs)
        bold "Regenerating all PDFs..."
        for builder in build_master_plan_pdf build_automation_map_pdf \
                       build_sf_dashboards_pdf build_user_actions_pdf \
                       build_today_checklist_pdf; do
            echo "→ $builder"
            python3 "tools/${builder}.py"
        done
        green "✓ all PDFs in docs/ + ~/Desktop/"
        ;;

    verify)
        bash tools/verify_workers.sh "$@"
        ;;

    kpi)
        python3 tools/daily_kpi_email.py --print
        ;;

    health)
        python3 tools/cloud_health_check.py --report
        ;;

    investors)
        python3 tools/build_investor_list.py
        ;;

    push)
        if ! git diff --cached --quiet 2>/dev/null || ! git diff --quiet 2>/dev/null; then
            git add -A
            # Auto-message from changed file types
            changed=$(git diff --cached --name-only | head -3 | tr '\n' ' ')
            msg="${1:-update: $changed}"
            git commit -m "$msg"
            git push
            green "✓ pushed — Railway + Cloudflare auto-deploying"
        else
            echo "Nothing to commit."
        fi
        ;;

    deploy-cf)
        bold "Deploying all Cloudflare Workers..."
        for d in cloudflare/*/; do
            if [ -f "$d/wrangler.toml" ]; then
                echo "→ $d"
                (cd "$d" && wrangler deploy)
            fi
        done
        ;;

    tail)
        svc="${1:-scraper}"
        bold "Tailing Railway logs for: $svc"
        railway logs --service "$svc" --tail
        ;;

    logs)
        svc="${1:-scraper}"
        railway logs --service "$svc" 2>&1 | tail -100
        ;;

    smoke)
        python3 tools/sf_smoke_test.py
        ;;

    sf-test)
        bold "Testing SF login..."
        python3 -c "
import os, urllib.request, re
from pathlib import Path
env = Path('.env.cheaphomesfla')
if env.exists():
    for ln in env.read_text().splitlines():
        if '=' in ln and not ln.strip().startswith('#'):
            k, v = ln.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())
user = os.environ['SF_USERNAME']
pw = os.environ['SF_PASSWORD']
tok = os.environ['SF_SECURITY_TOKEN']
domain = os.environ.get('SF_DOMAIN', 'johnsonshomes2.my')
soap = f'<?xml version=\"1.0\"?><soapenv:Envelope xmlns:soapenv=\"http://schemas.xmlsoap.org/soap/envelope/\" xmlns:urn=\"urn:partner.soap.sforce.com\"><soapenv:Body><urn:login><urn:username>{user}</urn:username><urn:password>{pw}{tok}</urn:password></urn:login></soapenv:Body></soapenv:Envelope>'
req = urllib.request.Request(f'https://{domain}.salesforce.com/services/Soap/u/58.0', data=soap.encode(), headers={'Content-Type': 'text/xml', 'SOAPAction': 'login'}, method='POST')
with urllib.request.urlopen(req, timeout=30) as r:
    body = r.read().decode()
m = re.search(r'<sessionId>(.+?)</sessionId>', body)
if m:
    print('✓ SF login OK')
else:
    print('✗ SF login FAILED')
    print(body[:500])
"
        ;;

    *)
        red "Unknown command: $cmd"
        echo "Run ./dev.sh for help."
        exit 1
        ;;
esac
