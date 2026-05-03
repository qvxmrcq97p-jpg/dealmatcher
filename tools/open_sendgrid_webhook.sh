#!/usr/bin/env bash
# Opens SendGrid's Mail Settings page and copies the webhook URL to clipboard.
echo ""
echo "→ Opening SendGrid Mail Settings..."
open -a "Google Chrome" "https://app.sendgrid.com/settings/mail_settings"
sleep 1
open -a "Google Chrome" "https://app.sendgrid.com/settings/mail_settings/webhook_settings/event_webhook"
sleep 2
printf "%s" "https://sendgrid-events.cbfcalcio5.workers.dev/" | pbcopy
echo "✓ Webhook URL copied to clipboard:"
echo "  https://sendgrid-events.cbfcalcio5.workers.dev/"
echo ""
echo "In SendGrid:"
echo "  1. Click 'Event Webhook' (or 'Event Settings')"
echo "  2. Toggle webhook ON"
echo "  3. Paste (Cmd+V) into the HTTP Post URL field"
echo "  4. Check: Delivered, Opened, Clicked, Bounced, Spam Reports, Unsubscribed, Group Unsubscribes"
echo "  5. Click Save"
echo ""
