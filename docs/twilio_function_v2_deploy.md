# Deploy: johnson-buys-sms /sms v2 (smart classifier + auto-opt-out)

**What this changes:** the inbound SMS handler stops forwarding "I don't want to sell" / "STOP" / "wrong number" replies to your phone. Instead it auto-updates Salesforce, sends a polite confirmation, and silently suppresses. Only genuinely interested replies and ambiguous ones reach you.

**Estimated deploy time:** 10 minutes.

**Prerequisite:** you've already enabled Twilio Advanced Opt-Out (separate task). If you haven't, deploy this first — Advanced Opt-Out can come later.

---

## Step 1 — Test the classifier locally first (1 min)

```bash
cd ~/dealmatcher/twilio-functions
python3 test_classifier.py
```

Should print `✓ All 27 tests passed`. If any fail, paste me the output before deploying.

---

## Step 2 — Open the Twilio Function in Console (2 min)

1. Open https://console.twilio.com
2. Left sidebar → **Functions and Assets** → **Services**
3. Click **`johnson-buys-sms`**
4. In the left tree, click **`/sms`** (the existing v1 handler)
5. Take a screenshot of the existing code OR copy it to a backup file before replacing — emergency rollback in case v2 misbehaves

---

## Step 3 — Verify environment variables (2 min)

Same Functions service → click the **gear icon** (Environment variables, top-left of the service).

Confirm these are set:

| Variable | Expected value |
|---|---|
| `SF_USERNAME` | `info@johnsonbuys.com` |
| `SF_PASSWORD` | (your SF password) |
| `SF_SECURITY_TOKEN` | (your SF security token) |
| `SF_DOMAIN` | `johnsonshomes2.my` |
| `CHRIS_PHONE` | `+13055759040` *(add this if not present)* |

If `CHRIS_PHONE` isn't there, click **Add** → Key: `CHRIS_PHONE`, Value: `+13055759040` → Save.

---

## Step 4 — Replace the /sms code (3 min)

1. Open `~/dealmatcher/twilio-functions/sms_v2.js` on your Mac
2. Copy ALL of it
3. In Twilio Console (with `/sms` open), select all the existing code (`Cmd+A`) and paste over with the v2 contents
4. Click **Save**
5. Click **Deploy All** (top right of the service page)

Wait ~30 seconds for deploy to complete. You'll see a green confirmation.

---

## Step 5 — Verify the webhook is still pointing at /sms (1 min)

1. Twilio Console → **Phone Numbers** → **Manage** → **Active numbers**
2. Click `+1 (954) 953-4554`
3. Under **Messaging** section, confirm:
   - **A MESSAGE COMES IN**: `Function`
   - **Service**: `johnson-buys-sms`
   - **Environment**: `ui` (or whatever the default is)
   - **Function Path**: `/sms`
4. If anything looks different from above, fix it and click **Save**

---

## Step 6 — Test from your own phone (3 min)

Send a test text to **+1 (954) 953-4554** from a number that's NOT in your Salesforce as a Lead. (Easiest: text from a friend's phone, or use a Google Voice number.)

Send: **"Stop"**

Expected behavior:
- You DO receive an auto-reply: *"You're off our list. Apologies for the bother. — Chris @ Johnson Buys"*
- Your iPhone (305) does NOT get a forwarded notification
- Twilio Console → **Functions** → **Logs** should show:
  ```
  Inbound from +1XXXXXXXXXX to +19549534554: Stop
  Classification: negative / opt_out
  SF Lead NOT matched for +1XXXXXXXXXX  (expected — test phone isn't in SF)
  ```

Then send: **"What's your offer?"**

Expected:
- You do NOT receive an auto-reply
- Your iPhone (305) DOES get a forwarded notification with prefix `🔥 HOT REPLY`

If both work — you're live. ✅

---

## Step 7 — Verify with a real lead reply (24 hours)

After tomorrow's 8:15 AM SMS campaign run, watch your phone. Within a few hours you should see:

- Far fewer notifications overall (negative replies suppressed)
- Any notifications you DO get are tagged with `🔥 HOT REPLY` or `❓ NEW REPLY`
- Open Salesforce → search Leads with `Status = "Take me off the list"` AND `SMS_Opt_Out__c = TRUE` AND `LastModifiedDate = TODAY` — should see new ones flowing in

If everything looks right after 24-48 hours of real traffic, this is permanent.

---

## Rollback (if something breaks)

If v2 misbehaves:
1. Twilio Console → Functions → johnson-buys-sms → /sms
2. Replace the code with the v1 backup you saved in Step 2
3. Click Save → Deploy All
4. You're back to "forward everything" behavior in 30 seconds

---

## What this fixes vs doesn't fix

✅ Fixed:
- Negative replies no longer flood your phone
- "STOP" replies auto-suppress + SF opt-out (you stop texting them next campaign run)
- Different negative reasons get different Salesforce statuses (Wrong Number / Doesn't own / Not Interested / Take me off the list)
- Interested replies get clear `🔥 HOT REPLY` flagging

❌ Not fixed:
- People who reply via call instead of text — those still go to your phone via the existing voice forwarder
- Email replies — those go to info@cheaphomesFLA.com (different pipeline)
- Bulk-rejected campaign messages — Twilio Advanced Opt-Out (separate task) handles those
- Tone of the auto-reply — edit `NEGATIVE_RULES[*].autoreply` in `sms_v2.js` if you want a different message

---

## Future enhancement (optional, future task)

Right now, "interested" is detected with simple keyword matching. Could be upgraded to use Claude or another LLM for nuanced classification (e.g., "I might be interested in 6 months" → still interested, just deferred). Defer this until you actually feel the keyword approach is missing things.
