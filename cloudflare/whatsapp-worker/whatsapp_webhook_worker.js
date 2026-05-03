/**
 * WhatsApp → Email Webhook Forwarder  (Cloudflare Worker)
 *
 * Purpose: receive Green-API (or compatible) webhook POSTs for new WhatsApp
 * group messages, re-format each message as an email, and deliver to
 * info@cheaphomesFLA.com via SendGrid so the existing deal-scraper pipeline
 * ingests WhatsApp deal blasts the same way it ingests email blasts.
 *
 * Flow:
 *   WhatsApp group message
 *     → Green-API webhook POST (JSON)
 *     → this Worker
 *     → SendGrid HTTP API
 *     → info@cheaphomesFLA.com inbox
 *     → daily scraper at 11 AM / 6 PM picks it up
 *
 * Secrets (set via `wrangler secret put`):
 *   SENDGRID_API_KEY   — reuse the same key as the seller email campaign
 *   SHARED_SECRET      — random string; Green-API sends it in header
 *                        `X-Webhook-Secret` on every request; Worker rejects
 *                        requests without a match so a leaked URL can't be
 *                        spammed.
 *
 * Optional vars (set via wrangler.toml or `wrangler secret put`):
 *   FROM_EMAIL         — default: whatsapp-deals@cheaphomesfla.com
 *   TO_EMAIL           — default: info@cheaphomesFLA.com
 *   DEBUG              — if "1", log the full webhook body to worker logs
 */

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Health endpoint — used by tools/cloud_health_check.py for hourly probes.
    if (url.pathname === "/health" && request.method === "GET") {
      const lastMsgAt = env.LAST_MSG_AT
        ? await env.LAST_MSG_AT.get("ts")
        : null;
      return new Response(JSON.stringify({
        ok: true,
        worker: "whatsapp-worker",
        deployed_from: "github:dealmatcher/cloudflare/whatsapp-worker",
        last_message_at: lastMsgAt,
        bindings: {
          shared_secret: !!env.SHARED_SECRET,
          last_msg_kv: !!env.LAST_MSG_AT,
        },
        time_utc: new Date().toISOString(),
      }, null, 2), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }

    // Only accept POST from Green-API
    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    // Shared-secret auth — accept the secret via:
    //   1. X-Webhook-Secret header        (custom-header providers)
    //   2. Authorization: Bearer <secret> (Green-API's webhookUrlToken)
    //   3. ?secret=<secret> URL query     (universally supported)
    // If env.SHARED_SECRET is unset (or empty), auth is skipped entirely
    // so the Worker accepts all POSTs (open mode — risk = email spam).
    if (env.SHARED_SECRET) {
      const headerSecret = request.headers.get("X-Webhook-Secret") || "";
      const bearer = (request.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "");
      const querySecret = new URL(request.url).searchParams.get("secret") || "";
      const supplied = headerSecret || bearer || querySecret;
      if (supplied !== env.SHARED_SECRET) {
        return new Response("Unauthorized", { status: 401 });
      }
    }

    let payload;
    try {
      payload = await request.json();
    } catch (err) {
      return new Response("Invalid JSON", { status: 400 });
    }

    if (env.DEBUG === "1") {
      console.log("Green-API payload:", JSON.stringify(payload));
    }

    // We only care about incoming messages that contain text.
    // Green-API webhook `typeWebhook` values include: incomingMessageReceived,
    // outgoingMessageReceived, stateInstanceChanged, etc. Filter to inbound text + media.
    const t = payload.typeWebhook;
    if (t !== "incomingMessageReceived") {
      return new Response("Ignored non-inbound", { status: 200 });
    }

    const msgData = payload.messageData || {};
    const senderData = payload.senderData || {};

    // Extract message text from whichever shape Green-API delivered
    let messageText = "";
    let mediaCaption = "";
    let mediaUrl = "";
    const typeMessage = msgData.typeMessage;

    if (typeMessage === "textMessage" || typeMessage === "extendedTextMessage") {
      messageText =
        msgData.textMessageData?.textMessage ||
        msgData.extendedTextMessageData?.text ||
        "";
    } else if (
      typeMessage === "imageMessage" ||
      typeMessage === "documentMessage" ||
      typeMessage === "videoMessage"
    ) {
      mediaCaption = msgData.fileMessageData?.caption || "";
      mediaUrl = msgData.fileMessageData?.downloadUrl || "";
      messageText = mediaCaption;
    } else {
      // audio, location, contact, sticker — not useful for deals
      return new Response("Ignored non-text message", { status: 200 });
    }

    // Only forward messages that mention an address, price, or other real-estate signals.
    // Keeps pure chatter ("thanks", "lol", "on my way") out of the scraper inbox.
    if (!looksLikePropertyMessage(messageText)) {
      return new Response("Ignored non-deal message", { status: 200 });
    }

    const senderName = senderData.senderName || senderData.senderContactName || "Unknown Sender";
    const chatName = senderData.chatName || senderData.senderName || "Direct Chat";
    const chatId = senderData.chatId || "";
    const isGroup = chatId.endsWith("@g.us");
    const timestamp = payload.timestamp
      ? new Date(payload.timestamp * 1000).toISOString()
      : new Date().toISOString();

    const fromEmail = env.FROM_EMAIL || "whatsapp-deals@cheaphomesfla.com";
    const toEmail = env.TO_EMAIL || "info@cheaphomesFLA.com";

    // Build a subject and body the downstream scraper can parse with its existing regexes.
    // Tag the subject with [WA] so you can filter/flag in the inbox.
    const subject = isGroup
      ? `[WA-Group] ${chatName} — ${senderName}`
      : `[WA-DM] ${senderName}`;

    const bodyLines = [
      `Forwarded from WhatsApp via Green-API`,
      ``,
      `Sender:     ${senderName}`,
      `Chat:       ${chatName} ${isGroup ? "(group)" : "(direct)"}`,
      `Chat ID:    ${chatId}`,
      `Received:   ${timestamp}`,
      ``,
      `From: ${senderName} <wa-${chatId.replace(/@.+$/, "")}@whatsapp>`,
      ``,
      `--- MESSAGE ---`,
      messageText || "(no text)",
      `--- END MESSAGE ---`,
    ];
    if (mediaUrl) {
      bodyLines.push("", `Media URL: ${mediaUrl}`);
    }
    const bodyPlain = bodyLines.join("\n");

    // Send through SendGrid. Reusing the seller campaign's API key keeps spend + quota unified.
    const sgPayload = {
      personalizations: [{ to: [{ email: toEmail }] }],
      from: { email: fromEmail, name: "WhatsApp Deal Forwarder" },
      reply_to: { email: toEmail },
      subject,
      content: [{ type: "text/plain", value: bodyPlain }],
      // Custom args surface in SendGrid's Activity logs for debugging
      custom_args: { source: "whatsapp-webhook", chat_id: chatId },
    };

    const sg = await fetch("https://api.sendgrid.com/v3/mail/send", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.SENDGRID_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(sgPayload),
    });

    if (!sg.ok) {
      const errText = await sg.text();
      console.error("SendGrid send failed:", sg.status, errText);
      return new Response(`SendGrid error ${sg.status}`, { status: 502 });
    }

    // Write timestamp of last successful forward for /health endpoint
    if (env.LAST_MSG_AT) {
      try {
        await env.LAST_MSG_AT.put("ts", new Date().toISOString());
      } catch (err) {
        console.error("LAST_MSG_AT KV write failed:", err);
      }
    }

    return new Response("OK", { status: 200 });
  },
};

/**
 * Heuristic filter — returns true if the message LOOKS like a real-estate
 * deal blast (contains an address pattern, a dollar price, or common
 * wholesale-speak). Keeps pure chat noise out of the scraper inbox.
 *
 * Tune as needed; false positives just send more mail to the parser (which
 * will reject junk without extractable address/price fields anyway).
 */
function looksLikePropertyMessage(text) {
  if (!text) return false;
  const t = text.toLowerCase();

  // Explicit dollar sign + digits
  if (/\$\s?\d[\d,]{2,}/.test(text)) return true;

  // Street suffix after a number: "1234 Main St", "5678 NW 12th Ave"
  if (/\d+\s+[^\n]{2,60}\b(st|ave|rd|blvd|dr|ln|ct|pl|way|cir|ter|pkwy|trl|hwy|loop)\b/i.test(text)) {
    return true;
  }

  // 5-digit zip standalone
  if (/\b\d{5}\b/.test(text)) return true;

  // Real-estate vocabulary
  const vocab = [
    "arv", "rehab", "wholesale", "sfr", "duplex", "triplex", "multi family",
    "multifamily", "for sale", "asking", "cash deal", "cash only", "hard money",
    "off market", "off-market", "fix and flip", "fix & flip", "buy and hold",
    "b&h", "brrrr", "novation", "contract", "under contract",
    "bd/", "bd /", "beds", "bath", "sqft", "sq ft",
  ];
  for (const word of vocab) {
    if (t.includes(word)) return true;
  }

  return false;
}
