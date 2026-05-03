/**
 * Railway Deploy-Failure Alerts (Cloudflare Worker)
 *
 * Receives webhook POSTs from Railway when a deployment finishes (success
 * or failure). Sends an SMS + email alert if a deploy FAILED so Chris
 * knows within 60 seconds that a git push broke production.
 *
 * Closes alert-map gap "h": currently a failed Railway build silently
 * keeps the previous deploy live and you'd never know unless you check
 * the dashboard.
 *
 * Webhook setup (Railway side):
 *   1. Railway → Project → Settings → Notifications → Webhooks
 *   2. Add: https://railway-deploy-alerts.<your-subdomain>.workers.dev/?secret=<your-secret>
 *   3. Trigger on: "Deployment Failed" (and optionally "Deployment Crashed")
 *   4. Save
 *
 * Wrangler secrets:
 *   SHARED_SECRET           — random string; Railway must include
 *                             ?secret=<value> in the webhook URL above
 *   SENDGRID_API_KEY        — same key the rest of the stack uses
 *   FROM_EMAIL              — info@johnsonbuys.com
 *   ALERT_TO                — info@johnsonbuys.com
 *   TWILIO_ACCOUNT_SID
 *   TWILIO_AUTH_TOKEN
 *   TWILIO_FROM             — +19549534554
 *   ALERT_SMS_TO            — Chris's phone, e.g. +13055759040
 *
 * Behavior:
 *   - Always returns 200 to Railway (so they don't retry on a slow SMS)
 *   - On FAILURE: sends 1 SMS + 1 email
 *   - On SUCCESS or any other event: silent (logs only)
 *   - On REPEATED failure for same service in <30min: still alerts (Chris
 *     needs to know each individual failure during a fix-it loop)
 */

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // ── /health ─────────────────────────────────────────────────────
    if (url.pathname === "/health" && request.method === "GET") {
      const lastAlertAt = env.LAST_ALERT_AT
        ? await env.LAST_ALERT_AT.get("ts")
        : null;
      return jsonResp({
        ok: true,
        worker: "railway-deploy-alerts",
        deployed_from: "github:dealmatcher/cloudflare/railway-deploy-alerts",
        last_alert_at: lastAlertAt,
        bindings: {
          sendgrid: !!env.SENDGRID_API_KEY,
          twilio: !!env.TWILIO_ACCOUNT_SID,
          last_alert_kv: !!env.LAST_ALERT_AT,
        },
        time_utc: new Date().toISOString(),
      }, 200);
    }

    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    // Shared-secret auth via URL query
    if (env.SHARED_SECRET) {
      const supplied = url.searchParams.get("secret") || "";
      if (supplied !== env.SHARED_SECRET) {
        console.error("Unauthorized webhook attempt");
        return new Response("Unauthorized", { status: 401 });
      }
    }

    let payload;
    try {
      payload = await request.json();
    } catch {
      return new Response("Invalid JSON", { status: 400 });
    }

    // Railway payload shape (as of 2025):
    //   {
    //     "type": "DEPLOY",
    //     "status": "FAILED" | "SUCCESS" | "BUILDING" | "CRASHED" | etc.,
    //     "project": { "name": "..." },
    //     "service": { "name": "..." },
    //     "deployment": { "id": "...", "url": "...", "createdAt": "..." },
    //     "environment": { "name": "production" }
    //   }
    const status = (payload.status || "").toUpperCase();
    const isFailure = ["FAILED", "CRASHED", "REMOVED"].includes(status);

    if (!isFailure) {
      console.log(`Railway event ${status} for service ${payload?.service?.name} — silent`);
      return jsonResp({ ok: true, action: "ignored", reason: "not a failure" }, 200);
    }

    const service = payload?.service?.name || "unknown-service";
    const project = payload?.project?.name || "unknown-project";
    const deployUrl = payload?.deployment?.url || "https://railway.app";
    const ts = new Date().toISOString();

    const subject = `🚨 Railway deploy ${status}: ${service}`;
    const body =
      `Railway deploy ${status}\n\n` +
      `Project: ${project}\n` +
      `Service: ${service}\n` +
      `When: ${ts}\n` +
      `URL: ${deployUrl}\n\n` +
      `Action:\n` +
      `1. Open Railway dashboard → ${service} → Deployments\n` +
      `2. Click the failed deploy → View Logs\n` +
      `3. Fix the bug locally → git push → redeploys automatically\n` +
      `   OR roll back: pick the previous green deploy → Redeploy`;

    const smsBody =
      `🚨 Railway ${status}: ${service}. ` +
      `Check railway.app → ${service} → Deployments for the build error.`;

    // Fire both alerts in parallel
    const tasks = [];
    if (env.SENDGRID_API_KEY) tasks.push(sendEmail(subject, body, env));
    if (env.TWILIO_ACCOUNT_SID && env.ALERT_SMS_TO) tasks.push(sendSms(smsBody, env));

    const results = await Promise.allSettled(tasks);
    for (const r of results) {
      if (r.status === "rejected") console.error("Alert dispatch failed:", r.reason);
    }

    if (env.LAST_ALERT_AT) {
      try {
        await env.LAST_ALERT_AT.put("ts", ts);
      } catch (_) {}
    }

    return jsonResp({
      ok: true,
      action: "alerted",
      service,
      status,
      email_sent: results[0]?.status === "fulfilled",
      sms_sent: results[1]?.status === "fulfilled",
    }, 200);
  },
};

// ─── Helpers ─────────────────────────────────────────────────────────
async function sendEmail(subject, body, env) {
  const r = await fetch("https://api.sendgrid.com/v3/mail/send", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.SENDGRID_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      personalizations: [{ to: [{ email: env.ALERT_TO || "info@johnsonbuys.com" }] }],
      from: {
        email: env.FROM_EMAIL || "info@johnsonbuys.com",
        name: "Railway Alerts",
      },
      subject,
      content: [{ type: "text/plain", value: body }],
    }),
  });
  if (!r.ok) throw new Error(`SendGrid ${r.status}: ${await r.text()}`);
}

async function sendSms(body, env) {
  const params = new URLSearchParams({
    From: env.TWILIO_FROM,
    To: env.ALERT_SMS_TO,
    Body: body,
  });
  const r = await fetch(
    `https://api.twilio.com/2010-04-01/Accounts/${env.TWILIO_ACCOUNT_SID}/Messages.json`,
    {
      method: "POST",
      headers: {
        "Authorization": "Basic " + btoa(`${env.TWILIO_ACCOUNT_SID}:${env.TWILIO_AUTH_TOKEN}`),
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: params.toString(),
    }
  );
  if (!r.ok) throw new Error(`Twilio ${r.status}: ${await r.text()}`);
}

function jsonResp(obj, status) {
  return new Response(JSON.stringify(obj, null, 2), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
