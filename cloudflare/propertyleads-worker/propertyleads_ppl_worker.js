/**
 * Property Leads PPL → Salesforce Lead  (Cloudflare Worker)
 *
 * Sibling worker to motivatedsellers-ppl-worker. Receives webhook POSTs
 * from propertyleads.com and synchronously:
 *
 *   1. Creates a Salesforce Lead (with duplicate-rule bypass) — LeadSource =
 *      "Property Leads PPL", Company = "Website Lead", Status = "New"
 *   2. Sends Twilio SMS intro to the seller's phone (speed-to-lead)
 *   3. Sends SendGrid email intro to the seller's email
 *   4. Emails Chris a copy of every inbound lead
 *   5. If SF write fails, emails Chris a FAILURE ALERT with the raw payload
 *      so the lead can be manually recovered. Lead is never lost.
 *
 * Always returns HTTP 200 to propertyleads.com so they don't retry on
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
 *   SHARED_SECRET         — optional; if set, propertyleads.com would
 *                           need to send "X-Webhook-Secret" header. Most
 *                           PPL providers don't support custom headers,
 *                           so leave unset and rely on URL obscurity (the
 *                           workers.dev URL is unguessable).
 *
 * NOTE on field mapping:
 *   propertyleads.com may send slightly different field names than
 *   motivatedsellers.com. The normalizeLead() function below accepts a
 *   broad set of synonyms. After deploying, send a real test lead and
 *   check the worker logs (Cloudflare → Workers → propertyleads-ppl-worker
 *   → Logs) to confirm all fields parsed. If any field came through as
 *   empty when it shouldn't have, add the actual field name to the
 *   appropriate `get(...)` call and re-deploy.
 */

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Health endpoint — used by tools/cloud_health_check.py for hourly uptime
    // probes. Returns 200 + JSON describing recent activity. Hitting this is
    // safe and rate-limit-friendly (no SF/Twilio/SendGrid calls).
    if (url.pathname === "/health" && request.method === "GET") {
      const lastLeadAt = env.LAST_LEAD_AT
        ? await env.LAST_LEAD_AT.get("ts")
        : null;
      return jsonResp({
        ok: true,
        worker: "propertyleads-ppl-worker",
        deployed_from: "github:dealmatcher/cloudflare/propertyleads-worker",
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

    // Log raw payload to worker logs for debugging on first lead
    if (env.DEBUG === "1") {
      console.log("[propertyleads] raw payload:", JSON.stringify(payload));
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
        console.error("[propertyleads] Failure-alert send failed:", err);
      }
    } else {
      // 6. Write timestamp of last successful lead to KV so /health can
      //    report it. Used by tools/cloud_health_check.py to detect a
      //    silent stoppage (PPL provider stopped sending) within ~1 hour.
      if (env.LAST_LEAD_AT) {
        try {
          await env.LAST_LEAD_AT.put("ts", new Date().toISOString());
        } catch (err) {
          console.error("[propertyleads] LAST_LEAD_AT KV write failed:", err);
        }
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
 * Map propertyleads.com's payload to the lead shape we use internally.
 *
 * Their exact field names will be confirmed once a real test lead lands
 * (check worker logs with DEBUG=1). The synonyms below cover the most
 * common PPL-vendor naming conventions.
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

  const firstName = get("first_name", "firstName", "First Name", "fname", "FirstName");
  const lastName  = get("last_name", "lastName", "Last Name", "lname", "LastName") || firstName || "Lead";
  const street    = [
    get("address", "Address", "property_address", "PropertyAddress", "street", "Street", "address1"),
    get("address_2", "Address_2", "address2", "Address2", "unit", "suite"),
  ].filter(Boolean).join(", ");

  return {
    first_name:    firstName,
    last_name:     lastName,
    email:         get("email_address", "email", "Email", "email_1", "EmailAddress"),
    phone:         get("phone", "Phone", "phone_number", "PhoneNumber", "phone1", "primary_phone"),
    street:        street,
    city:          get("city", "City", "property_city", "PropertyCity"),
    state:         get("state", "State", "property_state", "PropertyState") || "FL",
    postal_code:   get("zip_code", "zipcode", "zip", "Zip", "PostalCode", "postal_code", "property_zip"),
    county:        get("county", "County"),
    lead_id:       get("lead_id", "leadId", "key", "id", "tracking_id", "ref_id"),
    bedrooms:      get("bedrooms", "Bedrooms", "beds", "Beds"),
    bathrooms:     get("bathrooms", "Bathrooms", "baths", "Baths"),
    timeframe:     get("timeframe", "Timeframe", "timeline", "Timeline", "selling_timeframe"),
    est_value:     get("estimated_value", "estimatedValue", "home_value", "HomeValue", "EstimatedValue"),
    motivation:    get("motivation", "Motivation", "reason", "Reason", "reason_to_sell"),
    condition:     get("condition", "Condition", "property_condition", "PropertyCondition"),
    notes:         get("notes", "Notes", "comments", "Comments", "message", "Message"),
    account:       get("account", "campaign", "Campaign"),
    price:         get("price", "Price", "lead_cost", "LeadCost"),
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
  const propertyAddress = [
    lead.street,
    [lead.city, lead.state].filter(Boolean).join(", "),
    lead.postal_code,
  ].filter(Boolean).join(" ").trim();

  const descLines = [];
  if (lead.lead_id)    descLines.push(`Source lead_id: ${lead.lead_id}`);
  if (lead.county)     descLines.push(`County: ${lead.county}`);
  if (lead.bedrooms)   descLines.push(`Bedrooms: ${lead.bedrooms}`);
  if (lead.bathrooms)  descLines.push(`Bathrooms: ${lead.bathrooms}`);
  if (lead.timeframe)  descLines.push(`Timeframe: ${lead.timeframe}`);
  if (lead.est_value)  descLines.push(`Estimated value: $${lead.est_value}`);
  if (lead.motivation) descLines.push(`Motivation: ${lead.motivation}`);
  if (lead.condition)  descLines.push(`Condition: ${lead.condition}`);
  if (lead.notes)      descLines.push(`Notes: ${lead.notes}`);
  if (lead.price)      descLines.push(`PPL price: $${lead.price}`);

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
    LeadSource:              "Property Leads PPL",                    // <— differs from motivatedsellers
    Status:                  "New",
    Property_Address__c:     propertyAddress || null,
    Description:             descLines.join("\n") || null,
  };
  for (const k of Object.keys(fields)) {
    if (fields[k] === null || fields[k] === "") delete fields[k];
  }

  const r = await fetch(`${sf.instanceUrl}/services/data/v60.0/sobjects/Lead/`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${sf.sessionId}`,
      "Content-Type": "application/json",
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
// TWILIO + SENDGRID  — same plumbing as motivatedsellers worker
// =============================================================================

async function sendTwilioSms(lead, env) {
  const to = formatPhoneE164(lead.phone);
  if (!to) return;

  const firstName = (lead.first_name || "there").split(" ")[0];
  const propAddr = lead.street ? ` about ${lead.street}` : "";
  const body = `Hi ${firstName}, this is Chris from Johnson Buys. ` +
    `Got your inquiry${propAddr} — happy to make a fair cash offer with no obligation. ` +
    `When's a good time to chat? Reply STOP to opt out.`;

  const url = `https://api.twilio.com/2010-04-01/Accounts/${env.TWILIO_ACCOUNT_SID}/Messages.json`;
  const auth = btoa(`${env.TWILIO_ACCOUNT_SID}:${env.TWILIO_AUTH_TOKEN}`);
  const params = new URLSearchParams({ From: env.TWILIO_FROM, To: to, Body: body });

  const r = await fetch(url, {
    method: "POST",
    headers: {
      "Authorization": `Basic ${auth}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: params.toString(),
  });
  if (!r.ok) {
    const txt = await r.text();
    throw new Error(`Twilio HTTP ${r.status}: ${txt.slice(0, 200)}`);
  }
}

function formatPhoneE164(p) {
  if (!p) return null;
  const digits = String(p).replace(/\D/g, "");
  if (digits.length === 10) return `+1${digits}`;
  if (digits.length === 11 && digits.startsWith("1")) return `+${digits}`;
  if (digits.length >= 10) return `+${digits}`;
  return null;
}

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
  if (!r.ok && r.status !== 202) {
    const txt = await r.text();
    throw new Error(`SendGrid HTTP ${r.status}: ${txt.slice(0, 200)}`);
  }
}

async function sendWelcomeEmail(lead, env) {
  const firstName = (lead.first_name || "there").split(" ")[0];
  const propAddr  = lead.street || "your property";
  const html = `
    <p>Hi ${firstName},</p>
    <p>Thanks for reaching out about <b>${propAddr}</b>. I'm Chris with Johnson Buys —
       we make fair cash offers on homes in any condition, with no obligation.</p>
    <p>I'll review your property today and reach out shortly with next steps.
       In the meantime, you can reply to this email or call/text me directly at
       <a href="tel:+13055759040">(305) 575-9040</a> if you have questions.</p>
    <p>Talk soon,<br>Chris<br>Johnson Buys</p>
  `;
  const text = `Hi ${firstName}, thanks for reaching out about ${propAddr}. ` +
    `I'm Chris with Johnson Buys. I'll review your property today and follow up shortly. ` +
    `Reach me at (305) 575-9040 if you have questions. — Chris`;
  await sgSend(env, {
    to: lead.email,
    subject: `Got your inquiry about ${propAddr} — Chris @ Johnson Buys`,
    html,
    text,
    replyTo: env.FROM_EMAIL || "info@johnsonbuys.com",
  });
}

async function sendNotificationEmail(lead, status, env) {
  const alertTo = env.ALERT_TO || env.FROM_EMAIL || "info@johnsonbuys.com";
  const propAddr = [lead.street, lead.city, lead.state, lead.postal_code]
    .filter(Boolean).join(", ");
  const lines = [
    `New PROPERTY LEADS PPL lead — ${new Date().toISOString()}`,
    "",
    `Name:            ${lead.first_name} ${lead.last_name}`,
    `Phone:           ${lead.phone || "(none)"}`,
    `Email:           ${lead.email || "(none)"}`,
    `Property:        ${propAddr || "(no addr)"}`,
    `County:          ${lead.county || "(none)"}`,
    `Bedrooms:        ${lead.bedrooms || "?"}`,
    `Bathrooms:       ${lead.bathrooms || "?"}`,
    `Timeframe:       ${lead.timeframe || "?"}`,
    `Est. Value:      ${lead.est_value || "?"}`,
    `Motivation:      ${lead.motivation || "(none)"}`,
    `Notes:           ${lead.notes || "(none)"}`,
    `Lead price:      $${lead.price || "?"}`,
    "",
    `SF Lead ID:      ${status.sf_lead_id || "(create FAILED)"}`,
    `SMS sent:        ${status.sms_sent}`,
    `Welcome email:   ${status.welcome_email_sent}`,
    "",
    `Errors: ${status.errors.join(" | ") || "(none)"}`,
  ];
  await sgSend(env, {
    to: alertTo,
    subject: `📋 New Property Leads PPL: ${lead.first_name} ${lead.last_name} — ${propAddr || "no addr"}`,
    text: lines.join("\n"),
  });
}

async function sendFailureAlert(lead, rawPayload, status, env) {
  const alertTo = env.ALERT_TO || env.FROM_EMAIL || "info@johnsonbuys.com";
  const lines = [
    "⚠️  PROPERTY LEADS PPL — Salesforce write FAILED",
    `Time: ${new Date().toISOString()}`,
    "",
    "Lead data (use to manually create in SF):",
    `  ${lead.first_name} ${lead.last_name} / ${lead.phone || "(no phone)"} / ${lead.email || "(no email)"}`,
    `  ${lead.street}, ${lead.city}, ${lead.state} ${lead.postal_code}`,
    "",
    `Errors: ${status.errors.join(" | ")}`,
    "",
    "Raw payload from propertyleads.com:",
    JSON.stringify(rawPayload, null, 2),
  ];
  await sgSend(env, {
    to: alertTo,
    subject: `⚠️ Property Leads PPL → SF Lead create FAILED — ${lead.first_name} ${lead.last_name}`,
    text: lines.join("\n"),
  });
}
