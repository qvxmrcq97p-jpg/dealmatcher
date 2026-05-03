#!/usr/bin/env python3
"""
build_automation_map_pdf.py
────────────────────────────
Generates the Daily Automation Map PDF — every cron, every webhook, every
notification path, and every gap. Saves to:

  ~/dealmatcher/docs/automation_map.pdf
  ~/Desktop/automation_map.pdf   (mirror so it's easy to find)

Run:
  cd ~/dealmatcher && python3 tools/build_automation_map_pdf.py
"""

from __future__ import annotations
import datetime as dt
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    KeepTogether,
)

# ── Palette (matches master_plan.pdf) ────────────────────────────────
NAVY  = colors.HexColor("#0F2540")
GOLD  = colors.HexColor("#C8A446")
GREEN = colors.HexColor("#2A8B5F")
RED   = colors.HexColor("#B83B3B")
GREY  = colors.HexColor("#5C6470")
BG    = colors.HexColor("#F5F2EA")
WHITE = colors.white

# ── Styles ──────────────────────────────────────────────────────────
ss = getSampleStyleSheet()
TITLE = ParagraphStyle(
    "Title", parent=ss["Title"],
    fontName="Helvetica-Bold", fontSize=22, leading=26,
    textColor=NAVY, alignment=TA_LEFT, spaceAfter=4,
)
SUBTITLE = ParagraphStyle(
    "Subtitle", parent=ss["Normal"],
    fontName="Helvetica", fontSize=11, textColor=GREY,
    alignment=TA_LEFT, spaceAfter=14,
)
H1 = ParagraphStyle(
    "H1", parent=ss["Heading1"],
    fontName="Helvetica-Bold", fontSize=15, leading=19,
    textColor=NAVY, spaceBefore=14, spaceAfter=8,
)
H2 = ParagraphStyle(
    "H2", parent=ss["Heading2"],
    fontName="Helvetica-Bold", fontSize=12, leading=16,
    textColor=NAVY, spaceBefore=10, spaceAfter=6,
)
BODY = ParagraphStyle(
    "Body", parent=ss["Normal"],
    fontName="Helvetica", fontSize=10, leading=14,
    textColor=colors.HexColor("#222222"), spaceAfter=6,
)
BODY_S = ParagraphStyle(
    "BodyS", parent=BODY, fontSize=9, leading=12, spaceAfter=4,
)
TBL_HDR = ParagraphStyle(
    "TblHdr", parent=ss["Normal"],
    fontName="Helvetica-Bold", fontSize=9, leading=11,
    textColor=WHITE, alignment=TA_LEFT,
)
TBL_CELL = ParagraphStyle(
    "TblCell", parent=ss["Normal"],
    fontName="Helvetica", fontSize=8.5, leading=11,
    textColor=colors.HexColor("#222222"), alignment=TA_LEFT,
)
TBL_CELL_BOLD = ParagraphStyle(
    "TblCellBold", parent=TBL_CELL,
    fontName="Helvetica-Bold",
)


# ── Footer / page number ────────────────────────────────────────────
def _footer(canv, doc):
    canv.saveState()
    canv.setFont("Helvetica", 8)
    canv.setFillColor(GREY)
    canv.drawString(0.75 * inch, 0.45 * inch,
                    "Christopher Johnson · Johnson Buys + CheapHomesFLA · Daily Automation Map")
    canv.drawRightString(LETTER[0] - 0.75 * inch, 0.45 * inch, f"Page {doc.page}")
    canv.restoreState()


def _hbar(width=6.5 * inch, height=2, color=GOLD):
    """Horizontal divider."""
    t = Table([[""]], colWidths=[width], rowHeights=[height])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), color)]))
    return t


# ── Section 1: Architecture diagram (text-art) ──────────────────────
def section_architecture(story):
    story.append(Paragraph("Architecture — three layers, one source of truth", H1))
    story.append(Paragraph(
        "GitHub holds every line of code. Either Mac (mini OR MacBook Air) "
        "<i>git clones</i> the same repo, edits via Cowork, and pushes. "
        "Within ~2 minutes Railway redeploys the cron jobs and Cloudflare "
        "redeploys the webhook receivers. <b>No machine is special.</b> If one "
        "Mac is unavailable, the other works identically.",
        BODY,
    ))
    story.append(Spacer(1, 6))

    diagram = [
        ["", "GITHUB (private repo)", ""],
        ["", "single source of truth — code, configs, docs", ""],
        ["⬇ push from either Mac via Cowork", "", "⬇ auto-deploy on push to main"],
        ["", "", ""],
        ["RAILWAY", "", "CLOUDFLARE WORKERS"],
        ["Python cron jobs", "", "always-on webhook URLs"],
        ["• cheaphomes scraper (3×/day)", "", "• motivatedsellers-ppl-worker"],
        ["• jb_email (8 AM Mon-Sat)", "", "• propertyleads-ppl-worker"],
        ["• jb_sms (8:15 AM Mon-Sat)", "", "• whatsapp-worker"],
        ["• jb_followup (8 AM daily)", "", "• sendgrid-events (to build)"],
        ["• jb_digest (8:30 AM daily)", "", ""],
        ["• watchdog (9 AM daily)", "", "TWILIO FUNCTIONS"],
        ["• cloud_health (hourly)", "", "• /sms (inbound classifier)"],
        ["", "", "• /buyer-webhook"],
    ]
    t = Table(diagram, colWidths=[2.4 * inch, 1.6 * inch, 2.5 * inch])
    t.setStyle(TableStyle([
        # Title row
        ("SPAN", (0, 0), (2, 0)),
        ("SPAN", (0, 1), (2, 1)),
        ("BACKGROUND", (0, 0), (2, 1), NAVY),
        ("TEXTCOLOR",  (0, 0), (2, 1), WHITE),
        ("FONTNAME",   (0, 0), (2, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (2, 0), 12),
        ("FONTSIZE",   (0, 1), (2, 1), 9),
        ("ALIGN",      (0, 0), (2, 1), "CENTER"),
        # Arrows row
        ("FONTSIZE",   (0, 2), (2, 2), 8),
        ("ALIGN",      (0, 2), (2, 2), "CENTER"),
        ("TEXTCOLOR",  (0, 2), (2, 2), GREY),
        # Lower section headers
        ("BACKGROUND", (0, 4), (0, 4), GREEN),
        ("BACKGROUND", (2, 4), (2, 4), GOLD),
        ("TEXTCOLOR",  (0, 4), (0, 4), WHITE),
        ("TEXTCOLOR",  (2, 4), (2, 4), WHITE),
        ("FONTNAME",   (0, 4), (2, 4), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 4), (2, 4), 11),
        ("ALIGN",      (0, 4), (2, 4), "CENTER"),
        # Subheaders italic
        ("FONTNAME",   (0, 5), (2, 5), "Helvetica-Oblique"),
        ("TEXTCOLOR",  (0, 5), (2, 5), GREY),
        ("FONTSIZE",   (0, 5), (2, 5), 9),
        ("ALIGN",      (0, 5), (2, 5), "CENTER"),
        # Items
        ("FONTSIZE",   (0, 6), (2, 13), 9),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
        # Twilio Functions header on right column
        ("FONTNAME",   (2, 11), (2, 11), "Helvetica-Bold"),
        ("TEXTCOLOR",  (2, 11), (2, 11), NAVY),
    ]))
    story.append(t)
    story.append(Spacer(1, 14))


# ── Section 2: Daily timeline table ─────────────────────────────────
def section_daily_timeline(story):
    story.append(Paragraph("Daily timeline — every automation, every alert path", H1))
    story.append(Paragraph(
        "Times are <b>Eastern</b>. Hot rows (red) are missing notification "
        "coverage today and are gaps to close before launch.",
        BODY,
    ))
    story.append(Spacer(1, 6))

    rows = [
        # (time, name, where, what it does, alert)
        ("Always-on", "propertyleads-ppl-worker", "Cloudflare", "Receives PPL leads → SF Lead",        "MISSING"),
        ("Always-on", "motivatedsellers-ppl-worker","Cloudflare", "Receives motivatedsellers → SF Lead", "MISSING"),
        ("Always-on", "whatsapp-worker",          "Cloudflare", "Inbound WA → CHF deal pipeline",      "MISSING"),
        ("Always-on", "Twilio /sms (inbound)",    "Twilio Fn",  "Classifies SMS replies + auto-opt-out", "MISSING"),
        ("Always-on", "johnson_buys_webhook",     "Mac mini",   "Flask + ngrok inbound (legacy)",      "MISSING"),
        ("8:00 AM",  "JB email drip (4-touch)",   "Mac mini",   "Day 1 / 7 / 21 / 45 emails to leads", "Watchdog only @9 AM"),
        ("8:00 AM",  "JB followup SMS",           "Mac mini",   "Status-driven SMS follow-ups",        "MISSING"),
        ("8:15 AM",  "JB master SMS (4 campaigns)","Mac mini",  "New + Nurturing + 33127 + 33142",     "Watchdog only @9 AM"),
        ("8:30 AM",  "JB followup digest",        "Mac mini",   "Today's overdue follow-up tasks",     "Watchdog only @9 AM"),
        ("9:00 AM",  "Watchdog",                  "Mac mini",   "6 plists + 4 logs + SF + disk + SG",  "IS the alerter"),
        ("10:00 AM", "Cheaphomes scraper run 1",  "Mac mini",   "Email + WA → match → buyer emails",   "Watchdog @next 9 AM"),
        ("2:00 PM",  "Cheaphomes scraper run 2",  "Mac mini",   "Same as run 1",                       "Watchdog @next 9 AM"),
        ("6:00 PM",  "Cheaphomes scraper run 3",  "Mac mini",   "Same as run 1",                       "Watchdog @next 9 AM"),
    ]
    header = ["Time (ET)", "Automation", "Where", "What it does", "Failure alert?"]
    data = [[Paragraph(h, TBL_HDR) for h in header]]
    for tm, name, where, what, alert in rows:
        is_missing = alert == "MISSING"
        cell_style = TBL_CELL_BOLD if is_missing else TBL_CELL
        data.append([
            Paragraph(tm, TBL_CELL),
            Paragraph(name, TBL_CELL_BOLD),
            Paragraph(where, TBL_CELL),
            Paragraph(what, TBL_CELL),
            Paragraph(
                f'<font color="#B83B3B"><b>{alert}</b></font>' if is_missing
                else alert,
                TBL_CELL,
            ),
        ])
    t = Table(data, colWidths=[0.85 * inch, 1.65 * inch, 0.85 * inch, 2.0 * inch, 1.15 * inch],
              repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN",     (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW",  (0, 0), (-1, 0), 1, NAVY),
        ("LINEBELOW",  (0, -1), (-1, -1), 0.4, GREY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, BG]),
        ("LEFTPADDING",  (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
    ]
    t.setStyle(TableStyle(style))
    story.append(t)
    story.append(Spacer(1, 10))


# ── Section 3: What watchdog checks ─────────────────────────────────
def section_watchdog(story):
    story.append(Paragraph("Watchdog coverage — current safeguard", H1))
    story.append(Paragraph(
        "<b>tools/system_watchdog.py</b> runs daily at 9:00 AM ET. Sends an "
        "email to <b>info@johnsonbuys.com</b> only when something is yellow or "
        "red. Stays silent on green days.",
        BODY,
    ))
    rows = [
        ("Plists loaded", "All 6 expected plists are in launchctl list. Alerts if any missing or last exit non-zero.", GREEN),
        ("Log freshness", "campaign_log_latest, sms_all_campaigns_log_latest, deal_scraper_log_latest, scraper_stdout. Yellow if older than threshold; red if 2× threshold.", GREEN),
        ("Email campaign run", "Today's log shows ≥1 successful send. Red if SendGrid threw rate-limit. Yellow if more failures than successes.", GREEN),
        ("Scraper output", "Last run within 12h. Yellow if 0 deals last run (could mean parser regression).", GREEN),
        ("Disk space", "Free GB on /. Yellow under 5 GB; red under 2 GB.", GREEN),
        ("Salesforce login", "Test-auths via SOAP. Red if auth fails (token expired, 2FA tripped).", GREEN),
    ]
    data = [[Paragraph("Check", TBL_HDR), Paragraph("What it does", TBL_HDR), Paragraph("Status", TBL_HDR)]]
    for c, d, status in rows:
        data.append([
            Paragraph(c, TBL_CELL_BOLD),
            Paragraph(d, TBL_CELL),
            Paragraph('<font color="#2A8B5F"><b>covered</b></font>', TBL_CELL),
        ])
    t = Table(data, colWidths=[1.3 * inch, 4.5 * inch, 0.7 * inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN",     (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, BG]),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",   (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
    ]))
    story.append(t)


# ── Section 4: Gaps (what to add) ───────────────────────────────────
def section_gaps(story):
    story.append(Paragraph("Gaps — alerts you don't have yet", H1))
    story.append(Paragraph(
        "Each row below is a real failure mode that today produces NO alert. "
        "<b>Build column</b> shows what to build to close the gap. ETAs are conservative.",
        BODY,
    ))
    rows = [
        ("a", "Cloudflare Worker silently 500s",
            "PPL provider POSTs lead → CF Worker errors → no SF Lead created → you find out only when daily lead count drops.",
            "Add /health route to each Worker. Cloud-health-check pings every 15 min.",
            "20 min"),
        ("b", "PPL provider stops sending",
            "Provider's outbound webhook breaks on THEIR side. Volume drops to zero, no error fires here.",
            "Daily SOQL: count Leads where LeadSource='Property Leads PPL' and CreatedDate=TODAY < 50% of 7-day avg → email.",
            "30 min"),
        ("c", "SendGrid bounce / spam complaint rate",
            "Reputation tanks → emails go to spam → you keep paying. Currently no monitoring.",
            "Pull SendGrid stats API daily; alert if bounce > 5% or complaint > 0.1%.",
            "30 min"),
        ("d", "Twilio carrier blocks",
            "Carriers block A2P number; SMS shows 'sent' in log but never delivers. Currently no check.",
            "Pull Twilio Messages API delivery rate hourly; alert if delivered_rate < 90%.",
            "30 min"),
        ("e", "SF Lead inflow floor",
            "Total Lead creation drops sharply across all sources = something upstream is broken.",
            "Daily SOQL count vs 7-day rolling avg; alert if today < 50%.",
            "20 min"),
        ("f", "Watchdog frequency",
            "Watchdog only runs once per day at 9 AM. If 2 PM scraper crashes, you find out 19 hours later.",
            "Migrate to Railway hourly cron 9 AM-9 PM ET on business days.",
            "10 min"),
        ("g", "Watchdog itself fails",
            "Chicken-and-egg: if watchdog can't run, who alerts? External uptime ping needed.",
            "healthchecks.io free tier; watchdog hits its URL each run; healthchecks alerts if it doesn't.",
            "15 min"),
        ("h", "Railway deploy failure",
            "git push that breaks the build silently fails to update production. You think it deployed.",
            "Railway → webhooks → Cloudflare Worker → Twilio SMS to (305) 575-9040.",
            "30 min"),
        ("i", "Daily success summary",
            "You only know when things break. No daily snapshot of 'X emails sent, Y SMS delivered, Z deals scraped, W PPL leads received'.",
            "tools/daily_kpi_email.py at 9:15 AM (after watchdog clears).",
            "45 min"),
    ]
    data = [[
        Paragraph("#", TBL_HDR),
        Paragraph("Failure mode", TBL_HDR),
        Paragraph("What goes wrong", TBL_HDR),
        Paragraph("What to build", TBL_HDR),
        Paragraph("ETA", TBL_HDR),
    ]]
    for k, name, what, build, eta in rows:
        data.append([
            Paragraph(k, TBL_CELL_BOLD),
            Paragraph(name, TBL_CELL_BOLD),
            Paragraph(what, TBL_CELL),
            Paragraph(build, TBL_CELL),
            Paragraph(eta, TBL_CELL),
        ])
    t = Table(data,
              colWidths=[0.3 * inch, 1.55 * inch, 2.0 * inch, 2.05 * inch, 0.6 * inch],
              repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN",     (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, BG]),
        ("LEFTPADDING",  (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Spacer(1, 6))
    total = sum([20, 30, 30, 30, 20, 10, 15, 30, 45])
    hrs = total / 60.0
    story.append(Paragraph(
        f"<b>Total gap-closure work: {total} minutes (~{hrs:.1f} hours).</b> "
        "Order: a + f + g first (cheapest, biggest blast radius), then h (deploy "
        "alerts before launch), then b/c/d/e (volume + carrier alerts), then i "
        "(daily summary — pure morale, low urgency).",
        BODY,
    ))


# ── Section 5: Will the cloud preserve every automation? ────────────
def section_preservation(story):
    story.append(Paragraph("Preservation — will the cloud save every automation?", H1))
    story.append(Paragraph(
        "Yes — everything inside the GitHub repo is preserved automatically. "
        "Either Mac can <i>git clone</i> from anywhere (new laptop, traveling, "
        "drive failure) and have a working development environment in 5 minutes. "
        "Below is what's in the repo as of this writing and what just got moved in.",
        BODY,
    ))

    in_repo = [
        ("cheaphomesfla_scraper.py", "main scraper (3×/day)"),
        ("parser.py", "address + email + WA parser"),
        ("jb/email_campaign.py", "Day 1/7/21/45 email drip — env-var-ready"),
        ("jb/sms_campaign.py", "master SMS — env-var-ready"),
        ("jb/followup.py", "follow-up SMS — env-var-ready (just added)"),
        ("jb/digest.py", "daily digest — env-var-ready (just added)"),
        ("jb/sms_inbound.py", "Flask inbound SMS handler (just added; will move to Twilio Fn)"),
        ("tools/system_watchdog.py", "9 AM health check"),
        ("tools/cloud_health_check.py", "hourly cloud check (to build — closes gaps a/f)"),
        ("tools/daily_kpi_email.py", "morning success summary (to build — closes gap i)"),
        ("tools/build_master_plan_pdf.py", "regenerates master plan PDF"),
        ("tools/build_automation_map_pdf.py", "regenerates THIS PDF"),
        ("tools/sell_score.py", "Sell Score scoring engine"),
        ("tools/buyer_score.py", "Buyer Score scoring engine"),
        ("tools/top_buyers_by_zip.py", "Top 100 buyers per zip"),
        ("tools/build_below_market_seed.py", "below-market FB seed"),
        ("tools/fb_audience_hash.py", "SHA256 hash for FB Custom Audience"),
        ("tools/render_per_buyer_email.py", "tier-aware buyer email template"),
        ("twilio-functions/sms_v2.js", "smart SMS classifier (built; not deployed yet)"),
        ("cloudflare/propertyleads-worker/", "PPL → SF Lead webhook (deployed)"),
        ("cloudflare/motivatedsellers-worker/", "MS → SF Lead webhook (deployed)"),
        ("cloudflare/sendgrid-events/", "open/click tracking webhook (to build)"),
        ("docs/master_plan.pdf", "18-page operating manual"),
        ("docs/automation_map.pdf", "this document"),
        ("docs/CLOUD_DEPLOY.md", "step-by-step Railway + GitHub deploy"),
        ("plists/", "macOS plists (kept for emergency Mac fallback only)"),
    ]
    data = [[Paragraph("File / dir", TBL_HDR), Paragraph("What it is", TBL_HDR)]]
    for name, what in in_repo:
        data.append([Paragraph(name, TBL_CELL_BOLD), Paragraph(what, TBL_CELL)])
    t = Table(data, colWidths=[2.5 * inch, 4.0 * inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN",     (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, BG]),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "<b>What is NOT preserved automatically:</b> the actual <i>contents</i> "
        "of <b>~/Library/LaunchAgents/</b> on a Mac (just the plist sources, "
        "stored in the repo at <b>plists/</b>); the value of secrets in your "
        ".env file (those live in Railway's Shared Variables and you keep a "
        "1Password backup); historical campaign logs (those write to local "
        "disk and to Railway's deploy log retention — about 7 days). None of "
        "those losses break operations — they're either rebuildable or not "
        "needed for go-forward execution.",
        BODY,
    ))


# ── Section 6: Cloudflare vs Railway clarifier ──────────────────────
def section_cf_vs_railway(story):
    story.append(Paragraph("Why both Cloudflare AND Railway?", H1))
    story.append(Paragraph(
        "These solve different problems and share GitHub as their common code "
        "source. You're not migrating <i>off</i> Cloudflare — you're migrating "
        "<i>onto</i> Cloudflare-plus-Railway.",
        BODY,
    ))
    rows = [
        ("Job type", "Inbound webhook URL (stays up 24/7, responds <100ms)",
            "Scheduled Python cron (runs 1×/day or N×/day, then exits)"),
        ("Examples", "PPL provider POSTs a lead. Twilio POSTs an inbound SMS. SendGrid POSTs an open event.",
            "JB email drip at 8 AM. Cheaphomes scraper at 10 AM / 2 PM / 6 PM. Watchdog at 9 AM."),
        ("Where", "Cloudflare Workers", "Railway"),
        ("Language", "JavaScript (CF Workers is JS-native)", "Python 3.11"),
        ("Cost", "Free under 100k requests/day", "$5/mo Hobby plan covers everything we need"),
        ("Source code", "cloudflare/ subdirectory in GitHub", "everything else in GitHub"),
        ("Deploy", "wrangler CLI (auto on push via GitHub Actions, optional)",
            "Railway watches GitHub main branch, redeploys automatically"),
    ]
    data = [[
        Paragraph("Aspect", TBL_HDR),
        Paragraph("Cloudflare Workers", TBL_HDR),
        Paragraph("Railway", TBL_HDR),
    ]]
    for a, cf, rw in rows:
        data.append([
            Paragraph(a, TBL_CELL_BOLD),
            Paragraph(cf, TBL_CELL),
            Paragraph(rw, TBL_CELL),
        ])
    t = Table(data, colWidths=[1.1 * inch, 2.7 * inch, 2.7 * inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN",     (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, BG]),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",   (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
    ]))
    story.append(t)


# ── Section 7: Build order today + tomorrow ─────────────────────────
def section_build_order(story):
    story.append(Paragraph("Build order — today and Sunday", H1))
    story.append(Paragraph(
        "Numbered in the order I'm executing. ✓ = done, → = next, • = queued.",
        BODY,
    ))
    rows = [
        ("✓", "Saturday AM", "Plists copied to ~/Library/LaunchAgents/", "scraper + watchdog ready to load"),
        ("✓", "Saturday AM", "JB email + SMS scripts moved to ~/dealmatcher/jb/, env-var-patched", "now portable"),
        ("✓", "Saturday AM", ".gitignore + .env.example + requirements.txt + railway.json + Procfile", "Railway-ready"),
        ("✓", "Saturday AM", "docs/CLOUD_DEPLOY.md (step-by-step)", "your reference"),
        ("✓", "Saturday AM", "docs/automation_map.pdf (THIS document)", "your reference"),
        ("→", "Saturday PM", "Move johnson_buys_followup.py + johnson_buys_webhook.py + sf_followup_digest.py into repo", "complete the repo"),
        ("•", "Saturday PM", "Twilio /sms v2 deploy (smart classifier)", "stop forwarding noise to your phone"),
        ("•", "Saturday PM", "SendGrid Event Webhook CF Worker", "open/click tracking → SF Tasks"),
        ("•", "Saturday PM", "Investor extractor + Constant Contact transition email draft", "buy-box opt-in launch"),
        ("•", "Saturday PM", "Update master_plan.pdf with cloud architecture", "single canonical doc"),
        ("•", "Sunday AM", "Add /health route to each CF Worker", "closes gap a"),
        ("•", "Sunday AM", "tools/cloud_health_check.py (15-min cron)", "closes gaps a, b, e"),
        ("•", "Sunday AM", "Railway deploy-failure CF Worker", "closes gap h"),
        ("•", "Sunday AM", "tools/daily_kpi_email.py", "closes gap i"),
        ("•", "Sunday — your clicks", "GitHub repo create + push", "30 min"),
        ("•", "Sunday — your clicks", "Railway sign-up + 4 cron services + env vars", "60 min"),
        ("•", "Sunday — your clicks", "Smoke-test each cron in Railway", "15 min"),
        ("•", "Sunday EOD or Mon AM", "Cutover: launchctl bootout the Mac plists", "5 min — only after Railway green"),
    ]
    data = [[
        Paragraph("", TBL_HDR),
        Paragraph("When", TBL_HDR),
        Paragraph("Task", TBL_HDR),
        Paragraph("Outcome", TBL_HDR),
    ]]
    for s, when, task, outcome in rows:
        data.append([
            Paragraph(s, TBL_CELL_BOLD),
            Paragraph(when, TBL_CELL),
            Paragraph(task, TBL_CELL_BOLD),
            Paragraph(outcome, TBL_CELL),
        ])
    t = Table(data, colWidths=[0.3 * inch, 1.5 * inch, 2.6 * inch, 2.1 * inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN",     (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, BG]),
        ("LEFTPADDING",  (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
    ]))
    story.append(t)


# ── Build ───────────────────────────────────────────────────────────
def build_pdf(out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=LETTER,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.65 * inch, bottomMargin=0.7 * inch,
        title="Daily Automation Map",
        author="Christopher Johnson",
    )
    story: list = []

    # Cover
    today = dt.date.today().strftime("%A, %B %-d, %Y")
    story.append(Paragraph("Daily Automation Map", TITLE))
    story.append(Paragraph(
        f"Johnson Buys + CheapHomesFLA &nbsp;·&nbsp; {today} &nbsp;·&nbsp; "
        "Every cron · every webhook · every notification · every gap",
        SUBTITLE,
    ))
    story.append(_hbar())
    story.append(Spacer(1, 12))

    section_architecture(story)
    story.append(PageBreak())
    section_daily_timeline(story)
    story.append(PageBreak())
    section_watchdog(story)
    story.append(Spacer(1, 12))
    section_preservation(story)
    story.append(PageBreak())
    section_gaps(story)
    story.append(PageBreak())
    section_cf_vs_railway(story)
    story.append(Spacer(1, 18))
    section_build_order(story)

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return out_path


def main() -> None:
    repo_pdf = Path(__file__).resolve().parent.parent / "docs" / "automation_map.pdf"
    desktop_pdf = Path.home() / "Desktop" / "automation_map.pdf"

    build_pdf(repo_pdf)
    print(f"✓ {repo_pdf}")

    # Mirror to Desktop
    try:
        import shutil
        shutil.copyfile(repo_pdf, desktop_pdf)
        print(f"✓ {desktop_pdf}")
    except Exception as e:
        print(f"⚠️  Could not mirror to Desktop: {e}")


if __name__ == "__main__":
    main()
