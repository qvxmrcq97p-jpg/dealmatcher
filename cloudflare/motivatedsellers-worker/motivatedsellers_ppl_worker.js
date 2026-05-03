/**
 * Motivated Sellers PPL → Salesforce Lead  (Cloudflare Worker)
 *
 * Replaces the Zapier flow that sat in the held-runs queue with broken
 * LeadConnector. Receives the webhook from motivatedsellers.com's
 * Lead Delivery → HTTP POST setting and synchronously:
 *
 *   1. Creates a Salesforce Lead (with duplicate-rule bypass) — LeadSource =
 *      "Motivated Sellers PPL", Company = "Website Lead", Status = "New"
 *   2. Sends Twilio SMS intro to the seller's phone (speed-to-lead)
 *   3. Sends SendGrid email intro to the seller's email
 *   4. If SF write fails, emails Chris a FAILURE ALERT with the raw payload
 *      so the lead can be manually recovered. Lead is never lost.
 *
 * Always returns HTTP 200 to motivatedsellers.com so they don't retry on
 * partial failures (the failure alert covers recovery).
 *
 * Wrangler secrets to set (`wrangler secret put <NAME>`):
 *   SF_USERNAME           — info@johnsonbuys.com
 *   SF_PASSWORD           — Salesforce password
 *   SF_SECURITY_TOKEN     — Salesforce security token
 *   SF_LOGIN_DOMAIN       — usually "login" (prod) or "test" (sandbox)
 *
 *   SENDGRID_API_KEY      — same key the seller-campaign script uses
 *   FROM_EMAIL            — default "info@johnsonbuys.com"
 *   FROM_NAME             — default "Chris @ Johnson Buys"
 *   ALERT_TO              — failure alerts and notifications go here;
 *                           default "info@johnsonbuys.com"
 *
 *   TWILIO_ACCOUNT_SID    — from console.twilio.com (Johnson Buys account)
 *   TWILIO_AUTH_TOKEN
 *   TWILIO_FROM           — Twilio phone number, e.g. "+19549534554"
 *
 *   SHARED_SECRET         — optional; if set, motivatedsellers.com would
 *                           need to send "X-Webhook-Secret" header. They
 *                           don't support custom headers, so leave unset
 *                           and rely on URL obscurity (the workers.dev URL
 *                           is unguessable).
 */

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Health endpoint — used by tools/cloud_health_check.py for hourly uptime
    // probes. Safe to call freely (no SF/Twilio/SendGrid network calls).
    if (url.pathname === "/health" && request.method === "GET") {
      const lastLeadAt = env.LAST_LEAD_AT
        ? await env.LAST_LEAD_AT.get("ts")
        : null;
      return jsonResp({
        ok: true,
        worker: "motivatedsellers-ppl-worker",
        deployed_from: "github:dealmatcher/cloudflare/motivatedsellers-worker",
        last_lead_at: lastLeadAt,
        bindings: {
          sf_username: !!env.SF_USERNAME,
          sendgrid_key: !!env.SENDGRID_API_KEY,
          twilio_sid: !!env.TWILIO_ACCOUNT_SID,
          last_lead_kv: !!env.LAST_LEAD_AT,
        },
        time_utc: new Date().toISOString(),
      }, 200);
    }

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }
    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405, headers: corsHeaders() });
    }

    if (env.SHARED_SECRET) {
      const provided = request.headers.get("X-Webhook-Secret") || "";
      if (provided !== env.SHARED_SECRET) {
        return new Response("Unauthorized", { status: 401, headers: corsHeaders() });
      }
    }

    const payload = await parseBody(request);
    if (!payload) {
      return jsonResp({ ok: false, error: "Bad payload" }, 400);
    }

    const lead = normalizeLead(payload);

    const status = {
      sf_lead_id:           null,
      sms_sent:             false,
      welcome_email_sent:   false,
      notification_sent:    false,
      errors:               [],
      received_at:          new Date().toISOString(),
    };

    // 1. Salesforce Lead create — with duplicate-rule bypass header
    try {
      const sf = await sfLogin(env);
      status.sf_lead_id = await sfCreateLead(sf, lead);
    } catch (err) {
      status.errors.push(`SF: ${err.message}`);
    }

    // 2. Twilio SMS intro — only if we have a phone and Twilio creds
    if (lead.phone && env.TWILIO_ACCOUNT_SID && env.TWILIO_AUTH_TOKEN && env.TWILIO_FROM) {
      try {
        await sendTwilioSms(lead, env);
        status.sms_sent = true;
      } catch (err) {
        status.errors.push(`SMS: ${err.message}`);
      }
    }

    // 3. SendGrid welcome email — only if we have an email
    if (lead.email) {
      try {
        await sendWelcomeEmail(lead, env);
        status.welcome_email_sent = true;
      } catch (err) {
        status.errors.push(`Welcome: ${err.message}`);
      }
    }

    // 4. Notification email to Chris (always — this is his record of every lead)
    try {
      await sendNotificationEmail(lead, status, env);
      status.notification_sent = true;
    } catch (err) {
      status.errors.push(`Notify: ${err.message}`);
    }

    // 5. Failure alert if SF didn't land
    if (!status.sf_lead_id) {
      try {
        await sendFailureAlert(lead, payload, status, env);
      } catch (err) {
        console.error("Failure-alert send failed:", err);
      }
    } else if (env.LAST_LEAD_AT) {
      // 6. Successful lead → write timestamp for /health endpoint
      try {
        await env.LAST_LEAD_AT.put("ts", new Date().toISOString());
      } catch (err) {
        console.error("LAST_LEAD_AT KV write failed:", err);
      }
    }

    return jsonResp({ ok: true, ...status }, 200);
  },
};

// =============================================================================
// HELPERS
// =============================================================================

function corsHeaders() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Webhook-Secret",
  };
}

function jsonResp(obj, status) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders() },
  });
}

async function parseBody(request) {
  const ct = (request.headers.get("Content-Type") || "").toLowerCase();
  try {
    if (ct.includes("application/json")) {
      return await request.json();
    }
    if (ct.includes("application/x-www-form-urlencoded") || ct.includes("multipart/form-data")) {
      const fd = await request.formData();
      return Object.fromEntries(fd.entries());
    }
    return await request.json();
  } catch {
    return null;
  }
}

/**
 * Map motivatedsellers.com's payload to the lead shape we use internally.
 * Their JSON keys (verified live in their Lead Delivery dashboard):
 *   first_name, last_name, email_address, phone, address, address_2,
 *   city, state, zip_code, county, lead_id, bedrooms, bathrooms,
 *   timeframe, estimated_value, account, price
 */
function normalizeLead(p) {
  const get = (...keys) => {
    for (const k of keys) {
      if (p[k] !== undefined && p[k] !== null && String(p[k]).trim() !== "") {
        return String(p[k]).trim();
      }
    }
    return "";
  };

  const firstName = get("first_name", "firstName", "First Name");
  const lastName  = get("last_name",  "lastName",  "Last Name") || firstName || "Lead";
  const street    = [get("address", "Address"), get("address_2", "Address_2")]
                      .filter(Boolean).join(", ");

  return {
    first_name:    firstName,
    last_name:     lastName,
    email:         get("email_address", "email", "Email"),
    phone:         get("phone", "Phone"),
    street:        street,
    city:          get("city",  "City"),
    state:         get("state", "State") || "FL",
    postal_code:   get("zip_code", "zipcode", "zip"),
    county:        get("county", "County"),
    lead_id:       get("lead_id", "key", "id"),
    bedrooms:      get("bedrooms",  "Bedrooms"),
    bathrooms:     get("bathrooms", "Bathrooms"),
    timeframe:     get("timeframe", "Timeframe"),
    est_value:     get("estimated_value", "estimatedValue"),
    account:       get("account"),
    price:         get("price"),
  };
}

// =============================================================================
// SALESFORCE — SOAP login then REST Lead create with duplicate bypass
// =============================================================================

async function sfLogin(env) {
  for (const k of ["SF_USERNAME", "SF_PASSWORD", "SF_SECURITY_TOKEN"]) {
    if (!env[k]) throw new Error(`Missing env var ${k}`);
  }
  const loginDomain = env.SF_LOGIN_DOMAIN || "login";
  const url = `https://${loginDomain}.salesforce.com/services/Soap/u/60.0`;
  const body = `<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:urn="urn:partner.soap.sforce.com">
  <soapenv:Body>
    <urn:login>
      <urn:username>${escapeXml(env.SF_USERNAME)}</urn:username>
      <urn:password>${escapeXml(env.SF_PASSWORD + env.SF_SECURITY_TOKEN)}</urn:password>
    </urn:login>
  </soapenv:Body>
</soapenv:Envelope>`;

  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "text/xml; charset=utf-8", "SOAPAction": "login" },
    body,
  });

  const text = await r.text();
  if (!r.ok) throw new Error(`SF login HTTP ${r.status}: ${text.slice(0, 400)}`);
  const sessionMatch = text.match(/<sessionId>([^<]+)<\/sessionId>/);
  const serverUrlMatch = text.match(/<serverUrl>([^<]+)<\/serverUrl>/);
  if (!sessionMatch || !serverUrlMatch) {
    throw new Error(`SF login parse failed: ${text.slice(0, 400)}`);
  }
  const sessionId = sessionMatch[1];
  const instanceUrl = serverUrlMatch[1].replace(/\/services\/Soap.*/, "");
  return { sessionId, instanceUrl };
}

async function sfCreateLead(sf, lead) {
  // Build the property-address summary the existing campaign script uses
  const propertyAddress = [
    lead.street,
    [lead.city, lead.state].filter(Boolean).join(", "),
    lead.postal_code
  ].filter(Boolean).join(" ").trim();

  // Pack motivatedsellers.com extras into the Description field for traceability
  const descLines = [];
  if (lead.lead_id)   descLines.push(`Source lead_id: ${lead.lead_id}`);
  if (lead.county)    descLines.push(`County: ${lead.county}`);
  if (lead.bedrooms)  descLines.push(`Bedrooms: ${lead.bedrooms}`);
  if (lead.bathrooms) descLines.push(`Bathrooms: ${lead.bathrooms}`);
  if (lead.timeframe) descLines.push(`Timeframe: ${lead.timeframe}`);
  if (lead.est_value) descLines.push(`Estimated value: $${lead.est_value}`);
  if (lead.price)     descLines.push(`PPL price: $${lead.price}`);

  const fields = {
    FirstName:               lead.first_name || null,
    LastName:                lead.last_name,                          // required
    Email:                   lead.email || null,
    Phone:                   lead.phone || null,
    Street:                  lead.street || null,
    City:                    lead.city || null,
    State:                   lead.state || null,
    PostalCode:              lead.postal_code || null,
    Company:                 "Website Lead",                          // SF Lead requires Company
    LeadSource:              "Motivated Sellers PPL",
    Status:                  "New",
    Property_Address__c:     propertyAddress || null,
    Description:             descLines.join("\n") || null,
  };
  // Strip nulls
  for (const k of Object.keys(fields)) {
    if (fields[k] === null || fields[k] === "") delete fields[k];
  }

  const r = await fetch(`${sf.instanceUrl}/services/data/v60.0/sobjects/Lead/`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${sf.sessionId}`,
      "Content-Type": "application/json",
      // Bypass duplicate-detection rules — same approach the campaign Apex
      // script uses with Database.DMLOptions.DuplicateRuleHeader.AllowSave.
      "Sforce-Duplicate-Rule-Header": "allowSave=true",
    },
    body: JSON.stringify(fields),
  });

  if (r.status >= 400) {
    const errText = await r.text();
    throw new Error(`SF create Lead HTTP ${r.status}: ${errText.slice(0, 400)}`);
  }
  const data = await r.json();
  return data.id;
}

function escapeXml(s) {
  return String(s).replace(/[<>&'"]/g, (c) => (
    { "<": "&lt;", ">": "&gt;", "&": "&amp;", "'": "&apos;", "\"": "&quot;" }[c]
  ));
}

// =============================================================================
// SENDGRID — welcome to seller, notification to Chris, failure alert
// =============================================================================

async function sgSend(env, { to, subject, html, text, replyTo }) {
  if (!env.SENDGRID_API_KEY) throw new Error("SENDGRID_API_KEY missing");
  const fromEmail = env.FROM_EMAIL || "info@johnsonbuys.com";
  const fromName  = env.FROM_NAME  || "Chris @ Johnson Buys";

  const payload = {
    personalizations: [{ to: [{ email: to }] }],
    from: { email: fromEmail, name: fromName },
    subject,
    content: [],
  };
  if (replyTo) payload.reply_to = { email: replyTo };
  if (text) payload.content.push({ type: "text/plain", value: text });
  if (html) payload.content.push({ type: "text/html", value: html });

  const r = await fetch("https://api.sendgrid.com/v3/mail/send", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.SENDGRID_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    const errText = await r.text();
    throw new Error(`SendGrid ${r.status}: ${errText.slice(0, 300)}`);
  }
}

async function sendWelcomeEmail(lead, env) {
  const first = lead.first_name || "there";
  const propAddr = [lead.street, lead.city, lead.state, lead.postal_code]
                     .filter(Boolean).join(" ");
  const html = `<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;max-width:640px;margin:0 auto;color:#111;">
  <p>Hi ${escapeHtml(first)},</p>
  <p>This is Chris from <b>Johnson Buys</b>. I just got your inquiry about your property${propAddr ? ` at <b>${escapeHtml(propAddr)}</b>` : ""}.</p>
  <p>I'll be giving you a call shortly to talk through your timeframe and what you're looking for. We're a local Miami-based cash buyer — no agents, no commissions, no inspections. We can typically close in 7-14 days.</p>
  <p>If you'd rather text, I'm at <a href="tel:+13055759040">(305) 575-9040</a>. Quickest way to reach me.</p>
  <p>Talk soon,<br>
  Chris Johnson<br>
  <b>Johnson Buys</b><br>
  (305) 575-9040<br>
  <a href="mailto:info@johnsonbuys.com">info@johnsonbuys.com</a></p>
  </body></html>`;
  await sgSend(env, {
    to:       lead.email,
    subject:  `Got your message — Chris from Johnson Buys`,
    html,
    replyTo:  env.ALERT_TO || env.FROM_EMAIL || "info@johnsonbuys.com",
  });
}

async function sendNotificationEmail(lead, status, env) {
  const sfStatusLine = status.sf_lead_id
    ? `Salesforce Lead created: ${status.sf_lead_id}`
    : `⚠️ Salesforce CREATE FAILED — see failure alert`;
  const smsLine = status.sms_sent
    ? `Twilio SMS sent ✅`
    : (lead.phone ? `Twilio SMS NOT sent (check Twilio config / lead has no phone)` : `No phone — SMS skipped`);
  const emailLine = status.welcome_email_sent
    ? `Welcome email sent to ${lead.email} ✅`
    : (lead.email ? `Welcome email NOT sent` : `No email — welcome skipped`);

  const text = [
    `New Motivated Sellers PPL lead:`,
    ``,
    `Name:      ${lead.first_name} ${lead.last_name}`.trim(),
    `Phone:     ${lead.phone || "—"}`,
    `Email:     ${lead.email || "—"}`,
    `Address:   ${lead.street || "—"}`,
    `City/Zip:  ${[lead.city, lead.state, lead.postal_code].filter(Boolean).join(", ")}`,
    `County:    ${lead.county || "—"}`,
    `Beds/Bath: ${lead.bedrooms || "?"} / ${lead.bathrooms || "?"}`,
    `Timeframe: ${lead.timeframe || "—"}`,
    `Est value: ${lead.est_value ? `$${lead.est_value}` : "—"}`,
    `Lead ID:   ${lead.lead_id || "—"}`,
    `PPL cost:  ${lead.price ? `$${lead.price}` : "—"}`,
    ``,
    sfStatusLine,
    smsLine,
    emailLine,
  ].join("\n");

  await sgSend(env, {
    to:      env.ALERT_TO || "info@johnsonbuys.com",
    subject: `New Motivated Sellers PPL lead: ${lead.first_name} ${lead.last_name}`.trim(),
    text,
  });
}

async function sendFailureAlert(lead, rawPayload, status, env) {
  const text = [
    `🚨 Motivated Sellers PPL lead failed to land in Salesforce.`,
    ``,
    `Manual recovery needed — paste these fields into a new SF Lead:`,
    ``,
    `Name:      ${lead.first_name} ${lead.last_name}`.trim(),
    `Phone:     ${lead.phone || "—"}`,
    `Email:     ${lead.email || "—"}`,
    `Street:    ${lead.street || "—"}`,
    `City:      ${lead.city || "—"}`,
    `State:     ${lead.state || "—"}`,
    `PostalCode:${lead.postal_code || "—"}`,
    `County:    ${lead.county || "—"}`,
    `Beds/Bath: ${lead.bedrooms || "?"} / ${lead.bathrooms || "?"}`,
    `Timeframe: ${lead.timeframe || "—"}`,
    `Est value: ${lead.est_value ? `$${lead.est_value}` : "—"}`,
    `Lead ID:   ${lead.lead_id || "—"}`,
    ``,
    `Set Company = "Website Lead", LeadSource = "Motivated Sellers PPL", Status = "New".`,
    ``,
    `Errors:`,
    ...status.errors.map((e) => ` - ${e}`),
    ``,
    `Full raw payload:`,
    JSON.stringify(rawPayload, null, 2),
  ].join("\n");
  await sgSend(env, {
    to:      env.ALERT_TO || "info@johnsonbuys.com",
    subject: `🚨 Motivated Sellers PPL FAILURE: ${lead.first_name} ${lead.last_name} — manual recovery`.trim(),
    text,
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c]
  ));
}

// =============================================================================
// TWILIO SMS — speed-to-lead intro to the seller
// =============================================================================

async function sendTwilioSms(lead, env) {
  const first = lead.first_name || "there";
  const propAddr = [lead.street, lead.city].filter(Boolean).join(", ");
  const body = `Hi ${first}, this is Chris from JohnsonBuys.com. Got your inquiry${propAddr ? ` about ${propAddr}` : ""}. I'll be calling you shortly. If you'd rather text first, just reply here. — Chris (305) 575-9040`;

  // Normalize phone to E.164 if not already
  let to = String(lead.phone).trim();
  if (!to.startsWith("+")) {
    const digits = to.replace(/\D/g, "");
    to = digits.length === 10 ? `+1${digits}` : `+${digits}`;
  }

  const url = `https://api.twilio.com/2010-04-01/Accounts/${env.TWILIO_ACCOUNT_SID}/Messages.json`;
  const auth = btoa(`${env.TWILIO_ACCOUNT_SID}:${env.TWILIO_AUTH_TOKEN}`);
  const params = new URLSearchParams({
    From: env.TWILIO_FROM,
    To:   to,
    Body: body,
  });

  const r = await fetch(url, {
    method: "POST",
    headers: {
      "Authorization": `Basic ${auth}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: params.toString(),
  });
  if (!r.ok) {
    const errText = await r.text();
    throw new Error(`Twilio ${r.status}: ${errText.slice(0, 300)}`);
  }
}
