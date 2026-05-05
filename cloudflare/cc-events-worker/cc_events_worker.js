/**
 * Constant Contact Events Webhook (Cloudflare Worker)
 *
 * Receives webhook POSTs from Constant Contact when subscribers interact
 * with email campaigns: open, click, bounce, unsubscribe, opt-out.
 *
 * Each event is parsed for:
 *   - Contact email + name
 *   - Campaign ID + send timestamp
 *   - For clicks: full URL with UTM params (county, zip, deal-id)
 *
 * Then synced to Salesforce as a Task on the matching Contact (creates the
 * Contact if it doesn't exist yet, with LeadSource = "Constant Contact").
 *
 * UTM-derived insights captured per click:
 *   - utm_term  → county (e.g., miami-dade)
 *   - utm_content → date_deal-N (e.g., 2026-05-04_deal_3)
 *   - deal_id, deal_zip, deal_county → custom fields on the Activity
 *
 * Wrangler secrets to set:
 *   SF_USERNAME, SF_PASSWORD, SF_SECURITY_TOKEN, SF_LOGIN_DOMAIN
 *   CC_WEBHOOK_SECRET — random; CC sends as Authorization header
 *
 * Webhook URL to set in Constant Contact dashboard:
 *   https://cc-events-worker.cbfcalcio5.workers.dev/?secret=<CC_WEBHOOK_SECRET>
 *
 * Events to subscribe (in CC dashboard → Webhooks):
 *   email.opens, email.clicks, email.bounces, email.unsubscribes
 */

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // ── /health endpoint ──
    if (url.pathname === "/health" && request.method === "GET") {
      const lastEventAt = env.LAST_EVENT_AT ? await env.LAST_EVENT_AT.get("ts") : null;
      return jsonResp({
        ok: true,
        worker: "cc-events-worker",
        last_event_at: lastEventAt,
        bindings: {
          sf_username: !!env.SF_USERNAME,
          cc_secret: !!env.CC_WEBHOOK_SECRET,
          last_event_kv: !!env.LAST_EVENT_AT,
        },
        time_utc: new Date().toISOString(),
      }, 200);
    }

    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    // ── Auth: shared secret via query param OR Authorization header ──
    if (env.CC_WEBHOOK_SECRET) {
      const headerSecret = (request.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "");
      const querySecret = url.searchParams.get("secret") || "";
      const supplied = headerSecret || querySecret;
      if (supplied !== env.CC_WEBHOOK_SECRET) {
        return new Response("Unauthorized", { status: 401 });
      }
    }

    // ── Parse payload ──
    let payload;
    try {
      payload = await request.json();
    } catch (e) {
      return new Response("Invalid JSON", { status: 400 });
    }

    // CC event shape (verified via their docs):
    // {
    //   "event_type": "open" | "click" | "bounce" | "unsubscribe" | "spam",
    //   "campaign_id": "abc-123",
    //   "campaign_name": "Daily Deals 2026-05-05",
    //   "contact": {
    //     "email": "user@example.com",
    //     "first_name": "Sarah",
    //     "last_name": "Johnson"
    //   },
    //   "occurred_at": "2026-05-05T12:34:56Z",
    //   "url": "https://cheaphomesfla.com/...?utm_..." // for clicks
    // }
    //
    // Sometimes CC sends batched events as { "events": [...] }
    const events = Array.isArray(payload?.events) ? payload.events : [payload];

    let processed = 0;
    let failed = 0;
    let sf = null;

    for (const event of events) {
      try {
        if (!sf) sf = await sfLogin(env);
        await processEvent(event, sf, env);
        processed++;
      } catch (err) {
        console.error(`CC event process failed: ${err.message}`, JSON.stringify(event).slice(0, 300));
        failed++;
      }
    }

    if (env.LAST_EVENT_AT && processed > 0) {
      try {
        await env.LAST_EVENT_AT.put("ts", new Date().toISOString());
      } catch (_) {}
    }

    return jsonResp({ ok: true, processed, failed, total: events.length }, 200);
  },
};


// ─────────────────────────────────────────────────────────────────────────
// Salesforce helpers
// ─────────────────────────────────────────────────────────────────────────

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
  if (!r.ok) throw new Error(`SF login HTTP ${r.status}: ${text.slice(0, 300)}`);
  const sessionMatch = text.match(/<sessionId>([^<]+)<\/sessionId>/);
  const serverUrlMatch = text.match(/<serverUrl>([^<]+)<\/serverUrl>/);
  if (!sessionMatch || !serverUrlMatch) {
    throw new Error("SF login parse failed");
  }
  return {
    sessionId: sessionMatch[1],
    instanceUrl: serverUrlMatch[1].replace(/\/services\/Soap.*/, ""),
  };
}


async function findOrCreateContact(sf, email, firstName, lastName) {
  // Search SF for existing Contact by email
  const q = `SELECT Id, Email FROM Contact WHERE Email = '${email.replace(/'/g, "\\'")}' LIMIT 1`;
  const r = await fetch(`${sf.instanceUrl}/services/data/v60.0/query/?q=${encodeURIComponent(q)}`, {
    headers: { "Authorization": `Bearer ${sf.sessionId}` },
  });
  const data = await r.json();
  if (data.records && data.records.length > 0) {
    return data.records[0].Id;
  }

  // Not found — create new Contact
  const fields = {
    Email: email,
    FirstName: firstName || null,
    LastName: lastName || (firstName ? firstName : "Investor"),
    LeadSource: "Constant Contact",
  };
  for (const k of Object.keys(fields)) {
    if (fields[k] === null || fields[k] === "") delete fields[k];
  }
  const cr = await fetch(`${sf.instanceUrl}/services/data/v60.0/sobjects/Contact/`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${sf.sessionId}`,
      "Content-Type": "application/json",
      "Sforce-Duplicate-Rule-Header": "allowSave=true",
    },
    body: JSON.stringify(fields),
  });
  const cd = await cr.json();
  if (!cd.success) throw new Error(`Contact create failed: ${JSON.stringify(cd)}`);
  return cd.id;
}


async function logActivity(sf, contactId, subject, description) {
  const fields = {
    WhoId: contactId,
    Subject: subject.slice(0, 255),
    Description: description.slice(0, 32000),
    Status: "Completed",
    ActivityDate: new Date().toISOString().split("T")[0],
  };
  const r = await fetch(`${sf.instanceUrl}/services/data/v60.0/sobjects/Task/`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${sf.sessionId}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(fields),
  });
  if (!r.ok) {
    throw new Error(`Task create failed: HTTP ${r.status}`);
  }
}


// ─────────────────────────────────────────────────────────────────────────
// Event processor
// ─────────────────────────────────────────────────────────────────────────

async function processEvent(event, sf, env) {
  const contact = event.contact || {};
  const email = (contact.email || event.email || "").trim().toLowerCase();
  if (!email || !email.includes("@")) {
    throw new Error("Event has no valid email");
  }

  const contactId = await findOrCreateContact(
    sf,
    email,
    contact.first_name || event.first_name || "",
    contact.last_name || event.last_name || ""
  );

  const eventType = (event.event_type || event.type || "").toLowerCase();
  const campaignName = event.campaign_name || event.campaign || "(no campaign)";
  const occurredAt = event.occurred_at || new Date().toISOString();

  let subject, description;

  if (eventType === "open" || eventType === "opens") {
    subject = `📬 Email Opened: ${campaignName}`;
    description = `Constant Contact: email opened\nCampaign: ${campaignName}\nWhen: ${occurredAt}`;
  } else if (eventType === "click" || eventType === "clicks" || eventType === "url_click") {
    const clickUrl = event.url || event.link || "";
    const utm = parseUtmFromUrl(clickUrl);
    subject = `🔗 Email Click: ${utm.county || "general"} (${campaignName})`;
    description = [
      "Constant Contact: URL clicked",
      `Campaign: ${campaignName}`,
      `When: ${occurredAt}`,
      `URL: ${clickUrl}`,
      utm.county ? `County: ${utm.county}` : "",
      utm.deal_id ? `Deal ID: ${utm.deal_id}` : "",
      utm.deal_zip ? `Deal ZIP: ${utm.deal_zip}` : "",
      utm.deal_address ? `Deal address: ${utm.deal_address}` : "",
      utm.utm_content ? `UTM content: ${utm.utm_content}` : "",
    ].filter(Boolean).join("\n");
  } else if (eventType === "bounce" || eventType === "bounces") {
    subject = `⚠️ Email Bounced: ${campaignName}`;
    description = `Constant Contact: bounce\nCampaign: ${campaignName}\nReason: ${event.reason || event.bounce_reason || "unknown"}\nWhen: ${occurredAt}`;
  } else if (eventType === "unsubscribe" || eventType === "unsubscribes") {
    subject = `🚫 Unsubscribed: ${campaignName}`;
    description = `Constant Contact: unsubscribed\nCampaign: ${campaignName}\nWhen: ${occurredAt}`;
  } else if (eventType === "spam" || eventType === "complaint") {
    subject = `⚠️ Spam Complaint: ${campaignName}`;
    description = `Constant Contact: spam complaint\nCampaign: ${campaignName}\nWhen: ${occurredAt}`;
  } else {
    subject = `Event: ${eventType} (${campaignName})`;
    description = `Constant Contact event: ${eventType}\nWhen: ${occurredAt}\nRaw: ${JSON.stringify(event).slice(0, 1000)}`;
  }

  await logActivity(sf, contactId, subject, description);
}


function parseUtmFromUrl(rawUrl) {
  if (!rawUrl) return {};
  try {
    const u = new URL(rawUrl);
    const p = u.searchParams;
    return {
      utm_source: p.get("utm_source") || "",
      utm_medium: p.get("utm_medium") || "",
      utm_campaign: p.get("utm_campaign") || "",
      utm_content: p.get("utm_content") || "",
      utm_term: p.get("utm_term") || "",
      county: (p.get("utm_term") || p.get("deal_county") || "").replace(/\+/g, " "),
      deal_id: p.get("deal_id") || "",
      deal_zip: p.get("deal_zip") || "",
      deal_address: (p.get("deal_address") || "").replace(/\+/g, " "),
    };
  } catch {
    return {};
  }
}


function escapeXml(s) {
  return String(s).replace(/[<>&'"]/g, c => ({
    "<": "&lt;", ">": "&gt;", "&": "&amp;", "'": "&apos;", '"': "&quot;"
  }[c]));
}


function jsonResp(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
