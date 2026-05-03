#!/usr/bin/env bash
# Send a fake "Deployment Failed" event to the Worker to verify SMS+email pipeline.
# Run: bash tools/test_railway_alert.sh

URL="https://railway-deploy-alerts.cbfcalcio5.workers.dev/?secret=cd2d3a8ba58bff1d3d159ba713e7b802"

echo ""
echo "→ POSTing fake FAILED event to: $URL"
echo ""

curl -sS -X POST "$URL" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "DEPLOY",
    "status": "FAILED",
    "project": {"name": "luminous-spontaneity"},
    "service": {"name": "test-fake-service"},
    "deployment": {
      "id": "fake-deploy-123",
      "url": "https://railway.app/dashboard",
      "createdAt": "2026-05-03T16:00:00Z"
    },
    "environment": {"name": "production"}
  }'

echo ""
echo ""
echo "Expected response: {\"ok\":true,\"action\":\"alerted\",\"service\":\"test-fake-service\",\"status\":\"FAILED\",\"email_sent\":true,\"sms_sent\":true}"
echo ""
echo "If you see email_sent:true + sms_sent:true → pipeline is GOOD."
echo "Your phone (+13055759040) should get an SMS in 5-30 seconds."
echo "Your inbox (info@johnsonbuys.com) should get an email shortly after."
echo ""
echo "Verifying /health endpoint last_alert_at:"
sleep 3
curl -sS "https://railway-deploy-alerts.cbfcalcio5.workers.dev/health" | python3 -m json.tool 2>/dev/null
echo ""
