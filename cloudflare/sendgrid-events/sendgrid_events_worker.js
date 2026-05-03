/**
 * SendGrid Event Webhook → Salesforce Tasks (Cloudflare Worker)
 *
 * Receives SendGrid event POSTs (open, click, bounce, dropped, spamreport,
 * unsubscribe) and creates a Salesforce Task on the matching Lead/Contact.
 * Auto-creates a CHF Contact for unknown openers (a person who got the
 * email but isn't in your CRM yet — typically a forward recipient or
 * someone who clicked while logged in elsewhere).
 *
 * Why this exists:
 *   You currently have no visibility into who actually opens your drip
 *   emails. Without this you can't tell:
 *     - which subject lines work
 *     - which leads are hot vs ghost
 *     - when to escalate to a phone call
 *
 * After this is live:
 *   - Every open/click logs a Task on the Lead/Contact (visible on their
 *     timeline in SF)
 *   - SendGrid event volume becomes a key reportable signal
 *   - Hot leads can be auto-promoted to "Hot" status when they open 2+
 *     emails in a week (future enhancement; not in v1)
 *
 * Webhook URL to paste into SendGrid:
 *   https://sendgrid-events.cbfcalcio5.workers.dev/
 *
 * SendGrid Event Webhook configuration (Settings → Mail Settings →
 * Event Webhook):
 *   - HTTP Post URL: <your worker URL>
 *   - Select events: Open, Click, Bounce, Spam Report, Unsubscribe,
 *     Dropped, Group Unsubscribe
 *   - Click "Test Your Integration" before saving — a sample POST should
 *     return 200 OK from this Worker.
 *
 * Wrangler secrets:
 *   SF_USERNAME           — info@johnsonbuys.com
 *   SF_PASSWORD
 *   SF_SECURITY_TOKEN
 *   SF_LOGIN_DOMAIN       — "login" (prod)
 *   SHARED_SECRET         — optional. If set, SendGrid must include
 *                           ?secret=<value> in the webhook URL.
 *
 * Always returns 200 to SendGrid (their docs strongly request this even
 * on partial failure — they retry aggressively otherwise).
 */

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // ── /health ─────────────────────────────────────────────────────
    if (url.pathname === "/health" && request.method === "GET") {
      const lastEventAt = env.LAST_EVENT_AT
        ? await env.LAST_EVENT_AT.get("ts")
        : null;
      return jsonResp({
        ok: true,
        worker: "sendgrid-events",
        deployed_from: "github:dealmatcher/cloudflare/sendgrid-events",
        last_event_at: lastEventAt,
        bindings: {
          sf_username: !!env.SF_USERNAME,
          last_event_kv: !!env.LAST_EVENT_AT,
        },
        time_utc: new Date().toISOString(),
      }, 200);
    }

    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    // Optional shared-secret auth (URL query)
    if (env.SHARED_SECRET) {
      const supplied = url.searchParams.get("secret") || "";
      if (supplied !== env.SHARED_SECRET) {
        return new Response("Unauthorized", { status: 401 });
      }
    }

    let events;
    try {
      events = await request.json();
    } catch {
      return new Response("Invalid JSON", { status: 400 });
    }
    if (!Array.isArray(events)) {
      // SendGrid always sends an array
      return new Response("Expected JSON array", { status: 400 });
    }

    const sfAuth = await sfLogin(env);
    if (!sfAuth) {
      console.error("SF login failed — events dropped:", events.length);
      // Still return 200 so SendGrid doesn't retry — we'll re-process
      // via daily reconciliation if we miss events. Logged for visibility.
      return new Response("OK (sf login failed, events logged to console)", { status: 200 });
    }
    const { sessionId, instance } = sfAuth;

    let processed = 0;
    for (const ev of events) {
      try {
        await handleEvent(ev, sessionId, instance, env);
        processed++;
      } catch (err) {
        console.error("Event handler failed:", err.message, "for event:", JSON.stringify(ev).slice(0, 200));
      }
    }

    if (env.LAST_EVENT_AT && processed > 0) {
      try {
        await env.LAST_EVENT_AT.put("ts", new Date().toISOString());
      } catch (_) {}
    }

    return jsonResp({ ok: true, processed, total: events.length }, 200);
  },
};

// ─── Event router ────────────────────────────────────────────────────
async function handleEvent(ev, sessionId, instance, env) {
  const eventType = (ev.event || "").toLowerCase();
  const email = (ev.email || "").trim().toLowerCase();
  if (!email) return;

  // Find the matching Lead or Contact
  const target = await findContactOrLead(email, sessionId, instance);

  // For openers/clickers we don't have a record for, auto-create a CHF Contact
  if (!target && (eventType === "open" || eventType === "click")) {
    const newId = await createCHFContact(email, sessionId, instance);
    if (newId) {
      await createTask(newId, "Contact", eventType, ev, sessionId, instance);
      return;
    }
    return;
  }

  if (!target) {
    // Bounce/spam/etc on someone we don't have — log to console only
    console.log(`Event ${eventType} for unknown ${email} — skipping`);
    return;
  }

  // Status updates for hard signals
  if (eventType === "bounce" && target.type === "Lead") {
    await patchLeadStatus(target.id, "Doesn't own anymore", sessionId, instance);
  }
  if (eventType === "spamreport" || eventType === "unsubscribe" || eventType === "group_unsubscribe") {
    if (target.type === "Lead") {
      await patchLeadStatus(target.id, "Take me off the list", sessionId, instance);
    }
  }

  await createTask(target.id, target.type, eventType, ev, sessionId, instance);
}

// ─── SF helpers ──────────────────────────────────────────────────────
async function sfLogin(env) {
  const domain = env.SF_LOGIN_DOMAIN || "login";
  const soap = `<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:urn="urn:partner.soap.sforce.com">
  <soapenv:Body>
    <urn:login>
      <urn:username>${esc(env.SF_USERNAME)}</urn:username>
      <urn:password>${esc(env.SF_PASSWORD + env.SF_SECURITY_TOKEN)}</urn:password>
    </urn:login>
  </soapenv:Body>
</soapenv:Envelope>`;
  const r = await fetch(`https://${domain}.salesforce.com/services/Soap/u/58.0`, {
    method: "POST",
    headers: { "Content-Type": "text/xml", SOAPAction: "login" },
    body: soap,
  });
  const body = await r.text();
  const sid = body.match(/<sessionId>(.+?)<\/sessionId>/);
  const srv = body.match(/<serverUrl>(.+?)<\/serverUrl>/);
  if (!sid || !srv) return null;
  const inst = srv[1].match(/(https:\/\/[^/]+)/);
  if (!inst) return null;
  return { sessionId: sid[1], instance: inst[1] };
}

async function sfQuery(soql, sessionId, instance) {
  const url = `${instance}/services/data/v58.0/query?q=${encodeURIComponent(soql)}`;
  const r = await fetch(url, {
    headers: { Authorization: `Bearer ${sessionId}` },
  });
  if (!r.ok) return [];
  const data = await r.json();
  return data.records || [];
}

async function findContactOrLead(email, sessionId, instance) {
  // Contact first (CHF buyers — higher value)
  const c = await sfQuery(
    `SELECT Id FROM Contact WHERE Email = '${esc(email)}' LIMIT 1`,
    sessionId, instance
  );
  if (c.length) return { id: c[0].Id, type: "Contact" };

  // Then Lead (JB sellers)
  const l = await sfQuery(
    `SELECT Id FROM Lead WHERE Email = '${esc(email)}' AND IsConverted = false LIMIT 1`,
    sessionId, instance
  );
  if (l.length) return { id: l[0].Id, type: "Lead" };

  return null;
}

async function createCHFContact(email, sessionId, instance) {
  const url = `${instance}/services/data/v58.0/sobjects/Contact`;
  const r = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${sessionId}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      Email: email,
      LastName: email.split("@")[0],
      LeadSource: "Email Engagement (auto-created)",
      Description: "Auto-created from SendGrid event webhook — opened or clicked an email but wasn't in CRM yet.",
    }),
  });
  if (!r.ok) {
    console.error("Auto-create Contact failed:", await r.text());
    return null;
  }
  const data = await r.json();
  return data.id;
}

async function patchLeadStatus(id, status, sessionId, instance) {
  const url = `${instance}/services/data/v58.0/sobjects/Lead/${id}`;
  const r = await fetch(url, {
    method: "PATCH",
    headers: {
      Authorization: `Bearer ${sessionId}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ Status: status }),
  });
  if (!r.ok) console.error("Status PATCH failed:", await r.text());
}

async function createTask(whoId, whoType, eventType, ev, sessionId, instance) {
  const url = `${instance}/services/data/v58.0/sobjects/Task`;
  const subject = subjectFor(eventType, ev);
  const body = {
    Subject: subject,
    Status: "Completed",
    Priority: "Normal",
    Description: descriptionFor(eventType, ev),
    ActivityDate: new Date().toISOString().slice(0, 10),
  };
  if (whoType === "Contact") {
    body.WhoId = whoId;
  } else {
    body.WhoId = whoId; // Leads also use WhoId
  }
  const r = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${sessionId}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!r.ok) console.error("Task create failed:", await r.text(), "for", whoId);
}

// ─── Misc ────────────────────────────────────────────────────────────
function subjectFor(eventType, ev) {
  const subj = ev.subject ? ` — ${ev.subject.slice(0, 40)}` : "";
  switch (eventType) {
    case "open":             return `Email-Open${subj}`;
    case "click":            return `Email-Click${subj}`;
    case "bounce":           return `Email-Bounce${subj}`;
    case "dropped":          return `Email-Dropped${subj}`;
    case "spamreport":       return `Email-SpamReport${subj}`;
    case "unsubscribe":      return `Email-Unsubscribe${subj}`;
    case "group_unsubscribe":return `Email-GroupUnsubscribe${subj}`;
    case "delivered":        return `Email-Delivered${subj}`;
    case "processed":        return `Email-Processed${subj}`;
    default:                 return `Email-${eventType}${subj}`;
  }
}

function descriptionFor(eventType, ev) {
  const lines = [`Event: ${eventType}`];
  if (ev.email)     lines.push(`Email: ${ev.email}`);
  if (ev.timestamp) lines.push(`When:  ${new Date(ev.timestamp * 1000).toISOString()}`);
  if (ev.url)       lines.push(`URL:   ${ev.url}`);
  if (ev.useragent) lines.push(`Agent: ${ev.useragent.slice(0, 200)}`);
  if (ev.ip)        lines.push(`IP:    ${ev.ip}`);
  if (ev.reason)    lines.push(`Reason: ${ev.reason}`);
  if (ev.response)  lines.push(`Response: ${String(ev.response).slice(0, 200)}`);
  return lines.join("\n");
}

function esc(s) {
  return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
                       .replace(/>/g, "&gt;").replace(/'/g, "\\'");
}

function jsonResp(obj, status) {
  return new Response(JSON.stringify(obj, null, 2), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
