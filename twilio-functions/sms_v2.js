/**
 * johnson-buys-sms  /sms  handler — v2 (smart classifier + auto-opt-out)
 *
 * REPLACES the v1 "forward-everything" handler with intelligent routing:
 *   - NEGATIVE replies (stop / not interested / wrong number / doesnt own):
 *       1. Auto-update SF Lead Status (specific to negative type)
 *       2. Auto-set SMS_Opt_Out__c = true so future campaigns skip
 *       3. Send polite auto-reply confirming opt-out
 *       4. DO NOT forward to Chris — silent suppression
 *
 *   - INTERESTED replies (yes / how much / tell me more / etc.):
 *       1. Forward to Chris with 🔥 HOT REPLY prefix
 *       2. Include name + address + current status from SF
 *
 *   - AMBIGUOUS replies (everything else):
 *       1. Forward to Chris with ❓ NEW REPLY prefix
 *
 *   - Chris's own outbound (from CHRIS_PHONE):
 *       Pass-through (preserves any existing reply-routing behavior)
 *
 * REQUIRED ENVIRONMENT VARS in Twilio Function service settings:
 *   SF_USERNAME       e.g. info@johnsonbuys.com
 *   SF_PASSWORD       Salesforce password
 *   SF_SECURITY_TOKEN Salesforce security token
 *   SF_DOMAIN         e.g. johnsonshomes2.my
 *   CHRIS_PHONE       e.g. +13055759040
 *
 * DEPENDENCIES (Twilio Functions auto-provides):
 *   - getTwilioClient() — for outbound SMS via the same Twilio number
 *   - global fetch — Twilio's Node 18 runtime
 */

// =============================================================================
// CLASSIFIER  — keyword-based; tuned to common motivated-seller campaign replies
// =============================================================================

// Each rule: tested in order. First match wins.
// "status" is the SF Lead.Status to write when this rule fires.
// "autoreply" is the message back to the sender (or null = silent suppress).
const NEGATIVE_RULES = [
    {
        name: 'wrong_number',
        keywords: ['wrong number', 'wrong #', 'wrong person', "don't know who", 'not me', 'not my number'],
        status: 'Wrong Number',
        autoreply: "Apologies — we'll remove this number from our list. — Chris @ Johnson Buys"
    },
    {
        name: 'doesnt_own',
        keywords: ["don't own", 'dont own', 'no longer own', 'sold the house', 'sold this house',
                   'sold it', 'previous owner', "doesn't belong to me"],
        status: "Doesn't own anymore",
        autoreply: "Got it — thanks for letting us know. We'll update our records. — Chris @ Johnson Buys"
    },
    {
        name: 'not_interested',
        keywords: ['not interested', "don't want to sell", 'dont want to sell', 'not selling',
                   'never selling', "not gonna sell", 'no thanks', 'no thank you', "i'm not interested"],
        status: 'Not Interested',
        autoreply: "No problem — we'll take you off our list. Have a good day. — Chris @ Johnson Buys"
    },
    {
        name: 'opt_out',
        keywords: ['stop', 'stopped', 'unsubscribe', 'remove me', 'remove from', 'take me off',
                   'do not contact', 'opt out', 'opt-out', 'quit', 'cancel', 'leave me alone',
                   'stop texting', 'lose my number', 'fuck off', 'fck off', 'block', 'spam', 'harassment'],
        status: 'Take me off the list',
        autoreply: "You're off our list. Apologies for the bother. — Chris @ Johnson Buys"
    }
];

const INTERESTED_KEYWORDS = [
    'yes', 'interested', 'tell me more', 'how much', "what's your offer", 'whats your offer',
    'make an offer', 'send offer', 'send me', 'details', 'more info', 'more information',
    'still available', 'available?', 'call me', "let's talk", 'lets talk',
    'when can', 'i would like', "i'd like", "id like", 'curious', 'open to', 'considering',
    'how does this work', 'how would', 'price?', 'offer?', 'need cash', 'need to sell'
];


function classify(body) {
    const lower = (body || '').toLowerCase().trim();
    if (!lower) return { type: 'empty' };

    // Check negative rules first (specific → general order in the array)
    for (const rule of NEGATIVE_RULES) {
        if (rule.keywords.some(k => lower.includes(k))) {
            return {
                type: 'negative',
                rule_name: rule.name,
                status: rule.status,
                autoreply: rule.autoreply
            };
        }
    }

    // Check interested
    if (INTERESTED_KEYWORDS.some(k => lower.includes(k))) {
        return { type: 'interested' };
    }

    // Anything else
    return { type: 'ambiguous' };
}


// =============================================================================
// SALESFORCE   — SOAP login + REST query/update
// =============================================================================

async function sfLogin(context) {
    const soap = `<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:urn="urn:partner.soap.sforce.com">
  <soapenv:Body>
    <urn:login>
      <urn:username>${context.SF_USERNAME}</urn:username>
      <urn:password>${context.SF_PASSWORD}${context.SF_SECURITY_TOKEN}</urn:password>
    </urn:login>
  </soapenv:Body>
</soapenv:Envelope>`;
    const url = `https://${context.SF_DOMAIN}.salesforce.com/services/Soap/u/58.0`;
    const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'text/xml', 'SOAPAction': 'login' },
        body: soap
    });
    const text = await resp.text();
    const sessionMatch = text.match(/<sessionId>(.+?)<\/sessionId>/);
    const serverMatch = text.match(/<serverUrl>(.+?)<\/serverUrl>/);
    if (!sessionMatch || !serverMatch) {
        throw new Error('SF login failed: ' + text.substring(0, 200));
    }
    const instance = serverMatch[1].match(/(https:\/\/[^/]+)/)[1];
    return { sessionId: sessionMatch[1], instance };
}


async function sfFindLeadByPhone(sf, fromNumber) {
    // PHONE LOOKUP — robust to all SF phone formats.
    //
    // OLD (broken): SOQL `LIKE '%7863012767%'` only matched if the field had
    // 10 consecutive digits with NO separators. SF stores phones as
    // "(786) 301-2767" or "786-301-2767" or "+1 786 301 2767", which all
    // contain the same 10 digits but with parens/dashes/spaces in the middle.
    // Result: legitimate leads in SF showed as "unknown caller no SF lead match."
    //
    // NEW: query for last-4-digits (catches every format), then post-filter
    // by normalizing each candidate's phone fields to digits-only and matching
    // the last 10. Limit 50 results — collisions on last-4 are rare and bounded.
    const phoneDigits = (fromNumber || '').replace(/[^\d]/g, '');
    if (phoneDigits.length < 10) return null;
    const last10 = phoneDigits.slice(-10);
    const last4 = last10.slice(-4);

    const soql =
        `SELECT Id, FirstName, LastName, Phone, MobilePhone, Phone2__c, ` +
        `Property_Address__c, Status, SMS_Opt_Out__c FROM Lead ` +
        `WHERE Phone LIKE '%${last4}%' OR MobilePhone LIKE '%${last4}%' ` +
        `OR Phone2__c LIKE '%${last4}%' LIMIT 50`;
    const url = `${sf.instance}/services/data/v58.0/query?q=${encodeURIComponent(soql)}`;
    const resp = await fetch(url, {
        headers: { 'Authorization': `Bearer ${sf.sessionId}` }
    });
    if (!resp.ok) return null;
    const data = await resp.json();
    if (!data.records || data.records.length === 0) return null;

    // Post-filter: find the record whose normalized phone matches last10
    const normalize = (s) => (s || '').replace(/[^\d]/g, '').slice(-10);
    for (const r of data.records) {
        if (normalize(r.Phone) === last10 ||
            normalize(r.MobilePhone) === last10 ||
            normalize(r.Phone2__c) === last10) {
            delete r.attributes;
            return r;
        }
    }
    return null;
}


async function sfUpdateLead(sf, leadId, fields) {
    const url = `${sf.instance}/services/data/v58.0/sobjects/Lead/${leadId}`;
    const resp = await fetch(url, {
        method: 'PATCH',
        headers: {
            'Authorization': `Bearer ${sf.sessionId}`,
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(fields)
    });
    return resp.ok;
}


// =============================================================================
// MAIN HANDLER
// =============================================================================

exports.handler = async function (context, event, callback) {
    const fromNumber = event.From || '';
    const toNumber = event.To || '';
    const body = event.Body || '';
    const chrisPhone = context.CHRIS_PHONE || '+13055759040';

    console.log(`Inbound from ${fromNumber} to ${toNumber}: ${body.substring(0, 100)}`);

    // -- Pass-through Chris's own messages (preserves existing reply-route logic
    //    if any; if not, just no-ops with empty TwiML response).
    if (fromNumber === chrisPhone) {
        console.log('Inbound is FROM Chris — pass-through');
        callback(null, '');
        return;
    }

    // -- Classify
    const c = classify(body);
    console.log(`Classification: ${c.type}${c.rule_name ? ' / ' + c.rule_name : ''}`);

    // -- SF lookup (best-effort — failures don't block forwarding)
    let sf = null, lead = null;
    try {
        sf = await sfLogin(context);
        lead = await sfFindLeadByPhone(sf, fromNumber);
        if (lead) console.log(`SF Lead matched: ${lead.Id} (${lead.FirstName || ''} ${lead.LastName || ''})`);
        else console.log(`SF Lead NOT matched for ${fromNumber}`);
    } catch (e) {
        console.error('SF lookup failed:', e.message);
    }

    // ============ NEGATIVE PATH ============
    // Update SF + auto-reply + DO NOT forward to Chris
    if (c.type === 'negative') {
        if (lead && sf) {
            try {
                const ok = await sfUpdateLead(sf, lead.Id, {
                    Status: c.status,
                    SMS_Opt_Out__c: true
                });
                console.log(`SF update ${ok ? 'OK' : 'FAILED'} on Lead ${lead.Id} → Status="${c.status}", SMS_Opt_Out__c=true`);
            } catch (e) {
                console.error('SF update failed:', e.message);
            }
        }

        // TwiML auto-reply — keeps it on-brand
        const twiml = '<?xml version="1.0" encoding="UTF-8"?>' +
            `<Response><Message>${c.autoreply}</Message></Response>`;
        callback(null, twiml);
        return;
    }

    // ============ INTERESTED / AMBIGUOUS PATH ============
    // Forward to Chris with classification prefix
    const prefix = c.type === 'interested' ? '🔥 HOT REPLY' : '❓ NEW REPLY';

    const leadInfo = lead
        ? `${(lead.FirstName || '').trim()} ${(lead.LastName || '').trim()}`.trim() +
        ` | ${lead.Property_Address__c || '(no addr)'} | Status: ${lead.Status || '?'}`
        : '(unknown caller — no SF lead match)';

    const forwardBody =
        `${prefix}\n` +
        `${leadInfo}\n` +
        `From ${fromNumber}:\n` +
        body;

    try {
        const twilioClient = context.getTwilioClient();
        await twilioClient.messages.create({
            from: toNumber,        // forward from the same JB Twilio number
            to: chrisPhone,
            body: forwardBody
        });
        console.log(`Forwarded to ${chrisPhone} with prefix "${prefix}"`);
    } catch (e) {
        console.error('Forward to Chris failed:', e.message);
    }

    // No auto-reply to the sender for interested/ambiguous
    callback(null, '');
};
