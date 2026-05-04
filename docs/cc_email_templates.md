# Constant Contact Email Templates — Daily Deal Cadence

> Ready-to-paste HTML for the 14k Constant Contact list. Use the re-engagement email tonight/tomorrow as the first send, then the daily template for ongoing cadence.

---

## 🎯 Email #1 — Re-engagement (send TONIGHT or first thing tomorrow)

This is the first email back after the migration silence. Tone: warm, slightly behind-the-scenes, sets up expectations for what's coming next.

### Subject lines (A/B test if possible)
- `Big upgrade. Daily off-market deals incoming. 👇`
- `5 below-market FL properties hit my desk today`
- `[Tampa, Miami, Orlando] Today's outlier deals — first since the upgrade`
- `Back online with 200+ deals/day flowing through our scraper`

### From + Reply-to
- **From:** `Chris @ Cheap Homes FL <info@cheaphomesfla.com>`
- **Reply-to:** `info@cheaphomesfla.com`

### Body (paste this HTML into CC composer's HTML view)

```html
<table cellpadding="0" cellspacing="0" border="0" align="center" width="100%" style="max-width:600px; margin:0 auto; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif; color:#222;">
  <tr><td style="padding:20px 0;">
    <h1 style="margin:0 0 10px; font-size:24px; color:#0a66c2;">Hey [FirstName] — quick update.</h1>
    <p style="font-size:16px; line-height:1.6;">
      You haven't heard from me in a few weeks. Here's why: we've been heads-down rebuilding the deal pipeline.
    </p>
    <p style="font-size:16px; line-height:1.6;">
      <strong>What's new:</strong> our scraper now pulls deals from <strong>30+ wholesale email lists + WhatsApp groups</strong> — over <strong>200 fresh below-market deals per day</strong> flowing through our system. That's roughly 6,000 deals a month, hand-filtered to your local Florida market.
    </p>
    <p style="font-size:16px; line-height:1.6;">
      <strong>What you'll start getting:</strong> a daily email at 11:00 AM ET with the top 5 outlier deals (deepest below-market pricing) — every weekday for the next two weeks while we tune the system.
    </p>
    <div style="margin:25px 0; padding:18px; background:#f5f9ff; border-left:4px solid #0a66c2; border-radius:4px;">
      <strong style="font-size:17px;">Want deals matched to YOUR exact criteria?</strong>
      <p style="font-size:14px; line-height:1.6; margin:8px 0 12px;">
        The 5 daily picks above are general. If you tell us your buy-box (zip codes, price range, beds/baths, investor type), our system sends you a separate email with ONLY deals that match — straight to your inbox the moment a wholesaler posts one.
      </p>
      <a href="https://cheaphomesfla.com/buyer-form?utm_source=cc&utm_medium=email&utm_campaign=reengagement&utm_content=hero_cta"
         style="display:inline-block; padding:12px 22px; background:#0a66c2; color:#fff; text-decoration:none; border-radius:6px; font-weight:bold; font-size:15px;">
        Fill out my buy-box → 2 min
      </a>
    </div>

    <h2 style="font-size:18px; color:#222; margin:25px 0 10px;">Today's 5 below-market picks (hand-filtered today)</h2>
    <p style="font-size:14px; color:#666; margin:0 0 15px;">
      [BUILD_DAILY_CC_EMAIL_PY DEAL ROWS GO HERE — paste output of <code>python3 tools/build_daily_cc_email.py</code> here. The script renders 5 deals with addresses, prices, and clickable links.]
    </p>

    <p style="font-size:15px; line-height:1.6; margin-top:25px;">
      <strong>What about the free toolkit?</strong>
    </p>
    <p style="font-size:14px; line-height:1.6;">
      We're rolling out three free investor tools over the next 14 days. Already live:
    </p>
    <ul style="font-size:14px; line-height:1.7;">
      <li><a href="https://cheaphomesfla.com/tools/comp-lookup?utm_source=cc&utm_medium=email&utm_campaign=reengagement" style="color:#0a66c2;">Comp Houses Lookup Tool</a> — pull recent sold comps for any address</li>
      <li><a href="https://cheaphomesfla.com/tools/flip-calc?utm_source=cc&utm_medium=email&utm_campaign=reengagement" style="color:#0a66c2;">Fix-and-Flip Profit Calculator</a></li>
      <li><a href="https://cheaphomesfla.com/tools/rental-calc?utm_source=cc&utm_medium=email&utm_campaign=reengagement" style="color:#0a66c2;">Rental Cash-Flow + Cap Rate Calculator</a></li>
    </ul>

    <p style="font-size:15px; line-height:1.6; margin-top:25px;">
      Reply to this email if you want to chat about any deal, your buy-box, or the markets you're watching. I read every reply.
    </p>
    <p style="font-size:15px;">
      Talk soon,<br>
      <strong>Chris Johnson</strong><br>
      Cheap Homes FL<br>
      <a href="tel:+13055759040" style="color:#0a66c2;">(305) 575-9040</a>
    </p>
  </td></tr>

  <tr><td style="padding:20px 0; border-top:1px solid #eee; font-size:12px; color:#888; text-align:center;">
    Sent to investors who opted in for FL off-market deals.<br>
    <a href="%%unsubscribe_url%%" style="color:#888;">Unsubscribe</a> • <a href="https://cheaphomesfla.com" style="color:#888;">cheaphomesfla.com</a>
  </td></tr>
</table>
```

---

## 🔁 Email #2 — Daily template (start day after re-engagement)

Tighter version — gets to the deals fast. This runs daily for the next 2 weeks.

### Subject lines (vary day to day)
- `Today's 5 below-market FL deals — [Date]`
- `Fresh outliers: [Top zip] + 4 more deals scraped overnight`
- `Top 5 Florida deals — biggest discount [first deal % below comp]`
- `[Date] daily pick: [primary city/zip] cash-only`

### Body (paste into CC composer — auto-generated by `build_daily_cc_email.py`)

The Python script `tools/build_daily_cc_email.py` already produces this — UTM-tagged, mobile-optimized, includes the 3 free tool CTAs plus a primary "fill out your buy-box" button.

To run daily:
```
cd ~/dealmatcher && python3 tools/build_daily_cc_email.py
```

Output: HTML on Desktop + emailed to you. Paste into CC. Schedule for 11 AM ET. Done in 5 min.

---

## 📈 Performance KPIs to watch

After connecting CC ↔ SF integration, track in SF:

- **Open rate** — target: 18-25% (industry avg for real estate)
- **Click rate** — target: 3-6%
- **Buyer-form conversion** — target: 0.5-1.5% of clicks (so ~50-100 form fills/week from 14k list)
- **Replies** — track inbox; reply rate of 0.1-0.3% is normal

Compare across the 14 days to find:
- Best send time (morning vs afternoon)
- Best subject-line patterns
- Highest-converting deal types (price band, investor type)

After 14 days: refine the daily template based on what's working.

---

## ⚠️ Compliance notes

- Always include working unsubscribe link (CC handles this with `%%unsubscribe_url%%` token)
- Don't send to anyone who has opted out — CC honors this automatically when SF integration is on
- Honor any "remove me" replies within 10 days (CC ↔ SF auto-syncs unsubscribes)
- Keep CAN-SPAM Act compliant: physical address in footer (CC adds this)
