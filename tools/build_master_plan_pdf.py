#!/usr/bin/env python3
"""
build_master_plan_pdf.py — generate the comprehensive Johnson Buys +
CheapHomesFLA build spectrum PDF.

One-shot generator. Re-run any time content changes.

Output:
    ~/dealmatcher/docs/master_plan.pdf
    ~/Desktop/master_plan.pdf  (mirror, for easy access)
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


# ═══════════════════════════════════════════════════════════════════════════
# PATH SETUP
# ═══════════════════════════════════════════════════════════════════════════
SCRIPT_DIR = Path(__file__).resolve().parent.parent
DOCS_DIR = SCRIPT_DIR / "docs"
DESKTOP = Path.home() / "Desktop"
DOCS_DIR.mkdir(exist_ok=True)
OUT_PDF = DOCS_DIR / "master_plan.pdf"
DESKTOP_MIRROR = DESKTOP / "master_plan.pdf"


# ═══════════════════════════════════════════════════════════════════════════
# COLOR & STYLE PALETTE
# ═══════════════════════════════════════════════════════════════════════════
NAVY = colors.HexColor("#0F2540")
GOLD = colors.HexColor("#C8A446")
GREEN = colors.HexColor("#2A8B5F")
RED = colors.HexColor("#B83B3B")
GRAY_LIGHT = colors.HexColor("#F2F4F7")
GRAY_BORDER = colors.HexColor("#D0D5DD")
TEXT_DARK = colors.HexColor("#1A1F2E")
TEXT_MUTED = colors.HexColor("#646B7C")


# ═══════════════════════════════════════════════════════════════════════════
# DOCUMENT TEMPLATE WITH HEADER/FOOTER
# ═══════════════════════════════════════════════════════════════════════════
def header_footer(canvas, doc):
    canvas.saveState()
    # Header
    canvas.setFont("Helvetica-Bold", 9)
    canvas.setFillColor(NAVY)
    canvas.drawString(0.75 * inch, 10.3 * inch, "Johnson Buys / CheapHomesFLA — Master Plan")
    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(TEXT_MUTED)
    canvas.drawRightString(7.75 * inch, 10.3 * inch, date.today().strftime("%B %d, %Y"))
    # Header rule
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(0.5)
    canvas.line(0.75 * inch, 10.2 * inch, 7.75 * inch, 10.2 * inch)
    # Footer
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(TEXT_MUTED)
    canvas.drawCentredString(4.25 * inch, 0.5 * inch, f"Page {doc.page}")
    canvas.restoreState()


def make_doc(out_path: Path):
    doc = BaseDocTemplate(
        str(out_path),
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=1.0 * inch,
        bottomMargin=0.75 * inch,
        title="Johnson Buys & CheapHomesFLA — Master Plan",
        author="Chris Johnson",
    )
    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height,
        id="normal",
    )
    template = PageTemplate(id="main", frames=[frame], onPage=header_footer)
    doc.addPageTemplates([template])
    return doc


# ═══════════════════════════════════════════════════════════════════════════
# STYLES
# ═══════════════════════════════════════════════════════════════════════════
def build_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TitleX", parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=24, leading=30,
            textColor=NAVY,
            alignment=TA_CENTER,
            spaceAfter=10,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle", parent=base["Normal"],
            fontName="Helvetica",
            fontSize=14, leading=20,
            textColor=TEXT_MUTED,
            alignment=TA_CENTER,
            spaceAfter=20,
        ),
        "h1": ParagraphStyle(
            "H1", parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=18, leading=22,
            textColor=NAVY,
            spaceBefore=18, spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "H2", parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13, leading=16,
            textColor=NAVY,
            spaceBefore=12, spaceAfter=6,
        ),
        "h3": ParagraphStyle(
            "H3", parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=11, leading=14,
            textColor=GOLD,
            spaceBefore=8, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "Body", parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10, leading=14,
            textColor=TEXT_DARK,
            spaceAfter=6,
        ),
        "body_small": ParagraphStyle(
            "BodySmall", parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9, leading=12,
            textColor=TEXT_DARK,
            spaceAfter=4,
        ),
        "callout": ParagraphStyle(
            "Callout", parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=10, leading=13,
            textColor=NAVY,
            backColor=GRAY_LIGHT,
            borderPadding=8,
            spaceAfter=8,
            spaceBefore=4,
        ),
        "code": ParagraphStyle(
            "Code", parent=base["Code"],
            fontName="Courier",
            fontSize=9, leading=11,
            textColor=NAVY,
            backColor=GRAY_LIGHT,
            borderPadding=6,
            spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "Bullet", parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10, leading=13,
            textColor=TEXT_DARK,
            spaceAfter=3,
            leftIndent=14,
            bulletIndent=4,
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════
# REUSABLE BUILDERS
# ═══════════════════════════════════════════════════════════════════════════
def make_table(data, col_widths=None, header_color=NAVY,
               header_text_color=colors.white, alt_rows=True,
               font_size=9, header_font_size=10):
    table = Table(data, colWidths=col_widths)
    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header_color),
        ("TEXTCOLOR",  (0, 0), (-1, 0), header_text_color),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, 0), header_font_size),
        ("FONTNAME",   (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",   (0, 1), (-1, -1), font_size),
        ("TEXTCOLOR",  (0, 1), (-1, -1), TEXT_DARK),
        ("VALIGN",     (0, 0), (-1, -1), "TOP"),
        ("ALIGN",      (0, 0), (-1, -1), "LEFT"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING",   (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.4, GRAY_BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, GRAY_LIGHT] if alt_rows else [colors.white]),
    ])
    table.setStyle(style)
    return table


def bullet(text, styles):
    return Paragraph(f"• {text}", styles["bullet"])


def callout(text, styles):
    return Paragraph(text, styles["callout"])


# ═══════════════════════════════════════════════════════════════════════════
# CONTENT BUILDERS
# ═══════════════════════════════════════════════════════════════════════════
def build_cover(story, styles):
    story.append(Spacer(1, 1.5 * inch))
    story.append(Paragraph(
        "Johnson Buys &amp; CheapHomesFLA",
        styles["title"],
    ))
    story.append(Paragraph(
        "Master Build Spectrum &amp; TODO",
        styles["title"],
    ))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph(
        "Complete plan to reach $100k/month net by end of Q2 2026",
        styles["subtitle"],
    ))
    story.append(Spacer(1, 0.6 * inch))
    story.append(Paragraph(
        f"<i>Generated {date.today().strftime('%B %d, %Y')} for Chris Johnson</i>",
        ParagraphStyle("CoverDate", parent=styles["body"],
                       alignment=TA_CENTER, textColor=TEXT_MUTED),
    ))
    story.append(Spacer(1, 0.6 * inch))
    story.append(callout(
        "<b>Where we stand:</b> ~85% of the system is built. Today (Apr 30) "
        "we cleared a Sunbiz deadline, fixed an 11-day silent campaign blackout, "
        "wired Property Leads PPL into Salesforce, deployed v2 of the cheaphomesfla "
        "scraper, and prepared the migration package to Railway so the Mac mini "
        "is no longer a single point of failure. The remaining ~15% breaks "
        "down by phase below.",
        styles,
    ))
    story.append(PageBreak())


def build_status_snapshot(story, styles):
    story.append(Paragraph("Where We Are Right Now", styles["h1"]))
    story.append(Paragraph(
        "Snapshot of every moving part across both businesses as of end-of-day "
        "April 30, 2026.",
        styles["body"],
    ))
    story.append(Spacer(1, 6))

    story.append(Paragraph("Completed today", styles["h2"]))
    completed = [
        "Sunbiz LLC annual reports filed (penalty avoided)",
        "Lead parser rewrite — 36 unit tests passing, 97% junk → 85% clean output",
        "Cheaphomesfla scraper consolidated to ~/dealmatcher/, all paths cleaned up",
        "5 Salesforce custom fields created and FLS-granted (Buyer_Score, Top_Buyer_Zips, "
        "Seller_Score on Contact + Lead, plus Buyer_Target_Zips already present)",
        "Contact + Lead page layouts updated to display all new fields",
        "Buyer zip backfill applied to 4 active CHF buyers",
        "JB email + SMS plist Python-path bug fixed (Xcode CLT → python.org). "
        "11 days of silent failures revived; 111 catchup sends went out today.",
        "SendGrid upgraded to Essentials plan (50,000 emails/month)",
        "2 junk SF buyer Contacts deleted",
        "Property Leads PPL Cloudflare Worker deployed and tested in Salesforce",
        "Twilio /sms v2 (smart-classifier + auto-opt-out) code complete, "
        "ready to deploy",
        "System watchdog tool + plist built (catches breakage within 24 hours)",
        "Ad creative drafts: 3 docs, ~750 lines covering both businesses across "
        "FB / Google / YouTube / LinkedIn / Mail / SMS",
        "Day 8 morning routine SOP doc + new-laptop setup checklist",
        "Morning preflight tool, SF setup helper, dedup tool",
    ]
    for item in completed:
        story.append(bullet(item, styles))

    story.append(Spacer(1, 8))
    story.append(Paragraph("Pending — must complete tomorrow", styles["h2"]))
    pending = [
        "Cheaphomesfla scraper go-live (15 min, install plist + verify)",
        "Twilio /sms v2 deploy (10 min, paste sms_v2.js into Twilio Console)",
        "Railway migration deploy (20 min, run prepared deploy script)",
        "Twilio Advanced Opt-Out enable (5 min)",
        "MD parcels.csv + comparable_sales.csv download (15 min)",
        "ATTOM contact form + BatchLeads signup + Buffer signup (30 min)",
        "MLS RETS phone call (15 min)",
        "Twilio A2P 10DLC Brand registration (40 min)",
        "Build 8-10 Salesforce dashboards (90 min)",
        "Run revenue-tracking custom-fields creation script (5 min)",
        "Reach out to Abe Saldivar for zip preferences (5 min)",
    ]
    for item in pending:
        story.append(bullet(item, styles))

    story.append(Spacer(1, 8))
    story.append(Paragraph("Pending — multi-day approval queues", styles["h2"]))
    pending_long = [
        "ATTOM API key approval (1-2 weeks after submission)",
        "Twilio A2P 10DLC Brand approval (3-5 days after submission)",
        "MLS RETS access approval (varies)",
        "FB Special Ad Category — Housing setup (immediate but adds restrictions)",
    ]
    for item in pending_long:
        story.append(bullet(item, styles))

    story.append(PageBreak())


def build_chf_section(story, styles):
    story.append(Paragraph("CheapHomesFLA — Buyer-Side Business", styles["h1"]))
    story.append(Paragraph(
        "Goal: serve a curated investor list with off-market Miami-Dade deals. "
        "Investors fill out the cheaphomesfla.com form with their buy-box "
        "criteria; we send only deals that match.",
        styles["body"],
    ))

    story.append(Paragraph("What's running today", styles["h2"]))
    chf_running = [
        ["Component", "Status", "Notes"],
        ["Wholesaler email scraper", "Code ready, awaits go-live",
         "3x/day at 10/14/18:00 once plist installed"],
        ["WhatsApp deal forwarder",
         "Live (Cloudflare Worker)",
         "Forwards Green-API messages to scraper inbox"],
        ["Per-buyer email v2",
         "Wired into scraper",
         "Tier-aware (Hot/Warm/Cold), Top-Buyer-In-Zip callouts, strategy hints"],
        ["Property Leads PPL → SF",
         "Live (Cloudflare Worker)",
         "Auto-creates Lead, sends welcome SMS+email"],
        ["Motivated Sellers PPL → SF",
         "Live (Cloudflare Worker)",
         "Same pattern, different LeadSource"],
        ["Existing buyer pipeline", "5 active",
         "4 with target zips set; 1 (Abe Saldivar) pending zip preferences"],
    ]
    story.append(make_table(chf_running, col_widths=[1.7 * inch, 1.6 * inch, 3.4 * inch]))
    story.append(Spacer(1, 8))

    story.append(Paragraph("What's left to build / deploy", styles["h2"]))
    chf_left = [
        ["Item", "Owner", "Time"],
        ["Cheaphomesfla scraper go-live (install plist)", "Chris", "15 min"],
        ["Top 100 Buyers per Zip script run", "Claude (after parcels CSV)", "5 min"],
        ["Below-market seed CSV generation", "Claude", "5 min"],
        ["Buyer Score model run on real data", "Claude (after engagement events flow)", "5 min"],
        ["SendGrid Event Webhook for engagement tracking",
         "Claude tonight + Chris config tomorrow", "30 min"],
        ["Auto-create SF Contact for unknown email openers",
         "Built in same Worker", "(included)"],
        ["Constant Contact transition campaign",
         "Claude tonight + Chris API key tomorrow", "1 hour"],
        ["Buyer-side ad campaigns (FB/Google/YouTube/LinkedIn)",
         "Chris this weekend", "3-4 hours"],
        ["Daily deal cards generation (already built)",
         "Auto-runs after first scraper output", "(included)"],
        ["Sell Score v3 retrospective training", "Claude (after ATTOM API key)",
         "2-3 days"],
    ]
    story.append(make_table(chf_left, col_widths=[3.4 * inch, 2.4 * inch, 0.9 * inch]))
    story.append(PageBreak())


def build_jb_section(story, styles):
    story.append(Paragraph("Johnson Buys — Seller-Side Business", styles["h1"]))
    story.append(Paragraph(
        "Goal: acquire Miami-Dade properties from motivated sellers, contract them, "
        "and sell to CHF buyers (or directly to retail) at a $15-40k average spread. "
        "Drive lead flow via PPL providers + paid ads + direct mail.",
        styles["body"],
    ))

    story.append(Paragraph("What's running today", styles["h2"]))
    jb_running = [
        ["Component", "Status", "Notes"],
        ["JB email drip campaign",
         "Live (Mac mini, 8 AM)",
         "4-touch sequence (Day 1/7/21/45) + zip-specific blasts"],
        ["JB SMS drip campaign",
         "Live (Mac mini, 8:15 AM)",
         "6-touch sequence over 45 days, multi-number distribution"],
        ["JB followup digest",
         "Live (Mac mini, 8:30 AM)",
         "Daily email summary of leads due for callback"],
        ["JB followup task automation",
         "Live", "Updates SF Tasks daily"],
        ["Webhook server (legacy)",
         "Running but deprecated", "Replaced by Twilio Functions Apr 17"],
        ["Twilio /sms forwarder v1",
         "Live, forwards everything to Chris",
         "Will be replaced by v2 tomorrow (smart classifier)"],
        ["Voice call forwarding",
         "Live", "Twilio Function with SF lead-lookup whisper"],
        ["Swipe Pages 234-page SEO engine", "Live",
         "johnsonbuys.com/sell?town=X&problem=Y"],
        ["Cloudflare DNS + redirect rules", "Live",
         "Apex → www → /sell"],
    ]
    story.append(make_table(jb_running, col_widths=[1.9 * inch, 1.7 * inch, 3.1 * inch]))
    story.append(Spacer(1, 8))

    story.append(Paragraph("What's left to build / deploy", styles["h2"]))
    jb_left = [
        ["Item", "Owner", "Time"],
        ["Twilio /sms v2 deploy (smart classifier + auto-opt-out)", "Chris", "10 min"],
        ["Twilio Advanced Opt-Out enable (compliance)", "Chris", "5 min"],
        ["Twilio A2P 10DLC Brand registration", "Chris", "40 min + 3-5 day approval"],
        ["MLS RETS API access (305-468-7000)", "Chris", "15 min call + approval"],
        ["Direct mail campaign (yellow letters via REI Print Mail)",
         "Chris this weekend", "1 hour setup + ongoing"],
        ["Seller-side ad campaigns (FB/Google/YouTube)",
         "Chris this weekend", "3-4 hours"],
        ["7 revenue-tracking custom fields (Purchase, Sale, Spread, etc.)",
         "Claude script tomorrow", "5 min"],
        ["Sell Score v3 lead enrichment",
         "Claude (after ATTOM API key)", "2-3 days"],
        ["Goal tracker formula field on Lead",
         "Created with revenue fields", "(included)"],
        ["SOQL ORDER BY DESC fix in campaign scripts",
         "Awaiting Chris approval", "10 min"],
    ]
    story.append(make_table(jb_left, col_widths=[3.4 * inch, 2.4 * inch, 0.9 * inch]))
    story.append(PageBreak())


def build_shared_infra(story, styles):
    story.append(Paragraph("Shared Infrastructure", styles["h1"]))
    story.append(Paragraph(
        "Both businesses share the same backend services. Tracking everything "
        "in one place avoids surprises like the 11-day Python-path silent failure "
        "we caught and fixed today.",
        styles["body"],
    ))

    infra = [
        ["Service", "Purpose", "Status", "Monthly $"],
        ["Salesforce", "CRM, Leads, Contacts, Tasks, Reports", "Live", "Existing plan"],
        ["Cloudflare", "DNS, 4 Workers (CHF whatsapp, motivated sellers PPL, "
                      "property leads PPL, sendgrid events soon)", "Live", "$0-5"],
        ["SendGrid", "Outbound email (campaigns, drips, deals)",
         "Essentials plan, 50k/mo cap", "$19.95"],
        ["Twilio", "SMS, voice, Functions", "Live (multi-number)", "~$50"],
        ["Constant Contact", "Existing investor email list",
         "Currently sending; pivot to opt-in via transition email", "(check current)"],
        ["Mac mini (production today)", "Runs 5 Python cron jobs",
         "Single point of failure", "$0 (existing)"],
        ["Railway (planned migration)", "Cloud cron host for Python jobs",
         "Migration package ready, deploy tomorrow", "$5-20"],
        ["Buffer", "Social content scheduling (planned)",
         "Signup pending", "$15"],
        ["ATTOM Data (planned)", "70+ data points per property, distress signals",
         "Application pending", "$800-1000"],
        ["BatchLeads (planned)", "Skip-trace contact data",
         "Signup pending", "$97 + per-lookup"],
        ["Mojo Dialer (existing)", "Cold-call dialer", "Existing", "Existing"],
        ["Salesforce DocuSign", "E-signatures on contracts",
         "Connected, MCP available", "Per-envelope"],
    ]
    story.append(make_table(infra, col_widths=[1.5 * inch, 2.6 * inch, 2.0 * inch, 1.0 * inch]))
    story.append(PageBreak())


def build_migration_section(story, styles):
    story.append(Paragraph("Cloud Architecture — GitHub + Railway + Cloudflare", styles["h1"]))
    story.append(Paragraph(
        "Three layers, one source of truth. <b>GitHub holds every line of "
        "code.</b> Either Mac (mini OR MacBook Air) <i>git clones</i> the same "
        "repo, edits via Cowork, and pushes. Within ~2 minutes Railway "
        "redeploys the cron jobs and Cloudflare redeploys the webhook "
        "receivers. <b>No machine is special.</b> If one Mac is unavailable, "
        "the other works identically. Mac mini and MacBook Air are peer "
        "development environments, not production hosts.",
        styles["body"],
    ))
    story.append(callout(
        "<b>Why this split:</b> Cloudflare Workers handle inbound webhook "
        "URLs (always-on, &lt;100ms response, free under 100k req/day). "
        "Railway runs scheduled Python crons (existing scripts as-is, $5/mo). "
        "Both auto-deploy from GitHub on push. Cowork on either Mac edits "
        "either type. No lock-in to any single machine.",
        styles,
    ))

    story.append(Paragraph("What runs on Railway (Python crons)", styles["h2"]))
    railway = [
        ["Service", "Schedule (UTC)", "Schedule (ET)", "Purpose"],
        ["scraper",      "0 14,18,22 * * *",  "10 AM / 2 PM / 6 PM",
         "cheaphomesfla scraper — 3 daily runs"],
        ["jb_email",     "0 12 * * 1-6",       "8:00 AM Mon-Sat",
         "Day 1/7/21/45 email drip"],
        ["jb_sms",       "15 12 * * 1-6",      "8:15 AM Mon-Sat",
         "Master SMS — New + 33127 + 33142"],
        ["jb_followup",  "0 12 * * *",         "8:00 AM daily",
         "Status-driven follow-up SMS"],
        ["jb_digest",    "30 12 * * *",        "8:30 AM daily",
         "Today's overdue follow-up tasks"],
        ["watchdog",     "0 13 * * *",         "9:00 AM daily",
         "6 plists + 4 logs + SF + disk + SG"],
        ["cloud_health", "0 13-1 * * 1-6",     "Hourly 9 AM-9 PM Mon-Sat",
         "CF Worker /health + PPL volume + SG bounce/complaint"],
        ["daily_kpi",    "15 13 * * 1-6",      "9:15 AM Mon-Sat",
         "Morning success summary email"],
    ]
    story.append(make_table(railway, col_widths=[1.0 * inch, 1.3 * inch,
                                                  1.5 * inch, 2.9 * inch],
                            font_size=8, header_font_size=9))

    story.append(Spacer(1, 8))
    story.append(Paragraph("What runs on Cloudflare Workers (webhooks)", styles["h2"]))
    cf = [
        ["Worker", "URL", "Purpose"],
        ["propertyleads-ppl-worker",
         "propertyleads-ppl-worker.cbfcalcio5.workers.dev",
         "Property Leads PPL → SF Lead, SMS, email"],
        ["motivatedsellers-ppl-worker",
         "motivatedsellers-ppl-worker.cbfcalcio5.workers.dev",
         "Motivated Sellers PPL → SF Lead, SMS, email"],
        ["cheaphomesfla-whatsapp-webhook",
         "cheaphomesfla-whatsapp-webhook.cbfcalcio5.workers.dev",
         "Green-API WA → email forward to scraper inbox"],
        ["sendgrid-events",
         "sendgrid-events.cbfcalcio5.workers.dev",
         "Email open/click → SF Tasks, auto-create Contacts"],
        ["railway-deploy-alerts",
         "railway-deploy-alerts.cbfcalcio5.workers.dev",
         "Railway failed-deploy → SMS + email Chris"],
    ]
    story.append(make_table(cf, col_widths=[1.7 * inch, 2.6 * inch, 2.4 * inch],
                            font_size=8, header_font_size=9))

    story.append(Spacer(1, 8))
    story.append(Paragraph("What stays where it is", styles["h2"]))
    stays = [
        "Twilio Functions (/sms, /voice, /buyer-webhook) — Twilio's serverless, no migration needed",
        "Salesforce — SaaS, no migration needed",
        "Mac mini AND MacBook Air — both become peer dev environments. Either runs Cowork; either pushes to GitHub. Neither is required for production.",
        "GitHub repo (private) at github.com/cbfcalcio5/dealmatcher — single source of truth for all code, configs, docs",
    ]
    for item in stays:
        story.append(bullet(item, styles))

    story.append(Spacer(1, 8))
    story.append(Paragraph("Deploy steps (see docs/USER_ACTIONS.md for full click-by-click)", styles["h2"]))
    steps = [
        "Phase 1 — GitHub repo create + push (10 min)",
        "Phase 2 — Railway sign-up + 8 cron services + env vars (60 min)",
        "Phase 3 — Cloudflare Workers re-deploy from new repo paths + KV namespaces (20 min)",
        "Phase 4 — Twilio /sms v2 deploy (15 min)",
        "Phase 5 — Mac plist cutover via launchctl bootout (5 min)",
        "Total Christopher click-time: ~110 min. After this, neither Mac is required for production.",
    ]
    for s in steps:
        story.append(bullet(s, styles))

    story.append(PageBreak())


def build_phased_todo(story, styles):
    story.append(Paragraph("TODO List by Phase", styles["h1"]))
    story.append(Paragraph(
        "Every remaining task, organized by when it gets done. Critical-path items "
        "first; nice-to-haves later.",
        styles["body"],
    ))

    # Phase 1: Tonight
    story.append(Paragraph("Tonight (Claude — autonomous)", styles["h2"]))
    tonight = [
        ["Task", "ETA"],
        ["Build Railway migration package + deploy.sh", "60 min"],
        ["Build SendGrid Event Webhook Cloudflare Worker", "60 min"],
        ["Build investor contact extractor + transition email draft", "45 min"],
        ["Build Constant Contact campaign tool (waits on API key)", "30 min"],
        ["Build daily summary email tool (sent at 7 AM)", "30 min"],
        ["Build weekly KPI report email tool (Sunday 6 PM)", "30 min"],
        ["Build daily automation schedule doc (this PDF's companion)", "30 min"],
        ["Build revenue-tracking custom-fields creation script", "20 min"],
        ["Update sf_setup_helper.py to print all 10 dashboard guides", "20 min"],
        ["Update README index of every tool", "15 min"],
    ]
    story.append(make_table(tonight, col_widths=[5.5 * inch, 1.2 * inch]))

    story.append(Spacer(1, 8))
    story.append(Paragraph("Tomorrow morning (Friday May 1, ~4-5 hours, Chris)", styles["h2"]))
    tomorrow = [
        ["Task", "Time"],
        ["Verify 8 AM JB email + 8:15 AM SMS campaigns delivered", "5 min"],
        ["Run morning_preflight.py + check all green", "5 min"],
        ["Sign up Railway + run deploy.sh", "20 min"],
        ["Cheaphomesfla scraper go-live (4-step walkthrough)", "15 min"],
        ["Deploy Twilio /sms v2 (paste sms_v2.js into Console)", "10 min"],
        ["Twilio: Advanced Opt-Out enable", "5 min"],
        ["Twilio: A2P 10DLC Brand registration submission", "40 min"],
        ["MLS RETS phone call: 305-468-7000", "15 min"],
        ["ATTOM Data contact form (attomdata.com/data/contact-us)", "15 min"],
        ["BatchLeads signup", "10 min"],
        ["Buffer signup", "5 min"],
        ["Download MD parcels.csv + comparable_sales.csv", "15 min"],
        ["Generate Constant Contact API key, paste to Claude", "5 min"],
        ["Approve transition email copy (review draft)", "5 min"],
        ["Run add_revenue_fields.py (creates 7 SF custom fields)", "5 min"],
        ["Run sf_setup_helper.py (creates list views)", "5 min"],
        ["Build 10 Salesforce dashboards (use printed guide)", "90 min"],
        ["Pin top 3 dashboards to Home tab", "5 min"],
        ["Reach out to Abe Saldivar for zip preferences", "5 min"],
        ["Approve SOQL ORDER BY DESC fix on campaign scripts", "1 min"],
    ]
    story.append(make_table(tomorrow, col_widths=[5.5 * inch, 1.2 * inch]))

    story.append(PageBreak())

    # Weekend
    story.append(Paragraph("Weekend (Saturday May 2 - Sunday May 3, ads + creative)",
                           styles["h2"]))
    story.append(Paragraph(
        "Goal: get FB + Google + YouTube ad campaigns built and saved as drafts. "
        "Activate Sunday or after trip return. Use the 3 docs in "
        "~/dealmatcher/docs/ad_copy_*.md and audience_definitions.md as the source.",
        styles["body"],
    ))
    weekend = [
        ["Task", "Time"],
        ["Generate hashed CSVs for FB Custom Audiences (sell + buyer side)", "15 min"],
        ["Upload Custom Audiences to Facebook Ads Manager", "30 min"],
        ["Build 1% Lookalike audiences (sell + buyer side)", "10 min"],
        ["Create 3 FB ad variants for sellers (paste from ad_copy_seller_side.md)", "60 min"],
        ["Create 3 FB ad variants for buyers", "60 min"],
        ["Set Special Ad Category = Housing on FB campaigns", "5 min"],
        ["Save as DRAFT (don't activate yet)", "5 min"],
        ["Open Google Ads + verify domain ownership", "20 min"],
        ["Build Customer Match list in Google Ads", "10 min"],
        ["Create 3 Google search ad groups (sell side) + 3 buyer side", "60 min"],
        ["Create YouTube pre-roll campaign (uses Customer Match)", "30 min"],
        ["Save Google ads as DRAFT", "5 min"],
        ["Sign up REI Print Mail or Lob for direct mail", "20 min"],
        ["Set up first batch: 1,000 yellow letters (test before scaling to 4k)", "30 min"],
    ]
    story.append(make_table(weekend, col_widths=[5.5 * inch, 1.2 * inch]))

    story.append(Spacer(1, 8))
    story.append(Paragraph("Next week (Monday May 4 - Friday May 8)", styles["h2"]))
    nextweek = [
        "BatchLeads API key arrives (likely Monday) — Claude wires the integration",
        "ATTOM API key arrives (likely Mon-Wed) — Claude wires attom_enrich.py",
        "Sell Score v3 retrospective training pass (2-3 days, all Claude work)",
        "Bulk-enrich existing 1,500-2,000 active SF Leads with ATTOM data",
        "Run Sell Score v3 → produce ranked Hot list",
        "Hashed CSV uploaded to FB / Google for paid Custom Audiences",
        "Activate FB ads (sell side first, then buyer side 24h later)",
        "Activate Google ads + YouTube",
        "Constant Contact transition email blast (after API key)",
        "First handwritten letters mail-merged + printed",
        "Daily watchdog confirms everything firing",
    ]
    for item in nextweek:
        story.append(bullet(item, styles))

    story.append(Spacer(1, 8))
    story.append(Paragraph("Travel prep (Tuesday May 5)", styles["h2"]))
    prep = [
        "Buy travel laptop (MacBook Air recommended)",
        "Run new_laptop_setup_checklist.md (~30 min)",
        "iCloud sync of ~/dealmatcher to laptop",
        "iPhone Personal Hotspot test",
        "Verify SSH access to Mac mini from laptop (mini-status alias)",
        "Print day8_morning_routine_sop.md",
        "Pack: laptop, MagSafe, hotspot cable, paper notebook, printed SOP",
    ]
    for item in prep:
        story.append(bullet(item, styles))

    story.append(PageBreak())


def build_daily_schedule(story, styles):
    story.append(Paragraph("Daily Automation Schedule", styles["h1"]))
    story.append(Paragraph(
        "After tomorrow's migration, all of this runs autonomously on Railway. "
        "No Mac mini dependency. Times are local Eastern.",
        styles["body"],
    ))

    schedule = [
        ["Time", "Job", "Side", "What happens"],
        ["08:00 AM", "JB email drip", "Johnson Buys",
         "4-touch sequence (Day 1/7/21/45) + zip blasts. Skips Sundays."],
        ["08:00 AM", "JB followup SMS", "Johnson Buys",
         "Status-driven follow-up SMS to leads in Working/Hot states"],
        ["08:15 AM", "JB SMS drip", "Johnson Buys",
         "6-touch sequence over 45 days. Skips Sundays. Multi-number."],
        ["08:30 AM", "Followup digest", "Johnson Buys",
         "Daily summary of leads due for callback today"],
        ["09:00 AM", "System watchdog", "Both",
         "Health check across plists, logs, scrapers. Emails Chris if any alert."],
        ["09:15 AM", "Daily KPI email", "Both",
         "Green-day morning success summary (lead inflow, pipeline, campaigns, deals)"],
        ["10:00 AM", "Cheaphomesfla scraper #1", "CheapHomesFLA",
         "Pull last 24h of wholesaler emails + WhatsApp, parse, match buyers, send"],
        ["Hourly 9-21", "Cloud health check", "Both",
         "CF Worker /health probes + PPL volume floor + SendGrid bounce/complaint"],
        ["14:00 PM", "Cheaphomesfla scraper #2", "CheapHomesFLA",
         "Same pipeline, midday catch"],
        ["18:00 PM", "Cheaphomesfla scraper #3", "CheapHomesFLA",
         "Same pipeline, end-of-day catch"],
        ["Mon 06:00 AM", "Sell Score weekly refresh", "Both",
         "Re-runs Sell Score v3 on full MD homeowner list (after ATTOM live)"],
        ["Mon 23:00 PM", "Top 100 Buyers per Zip refresh", "CheapHomesFLA",
         "Re-pulls deed transfers + re-ranks investor list"],
        ["Real-time", "Property Leads PPL → SF", "Johnson Buys",
         "On-demand via Cloudflare Worker"],
        ["Real-time", "Motivated Sellers PPL → SF", "Johnson Buys",
         "On-demand via Cloudflare Worker"],
        ["Real-time", "WhatsApp deal forward", "CheapHomesFLA",
         "Green-API → Cloudflare Worker → email forward to scraper inbox"],
        ["Real-time", "Twilio /sms v2", "Both",
         "Inbound SMS classification + auto-reply + SF status update"],
        ["Real-time", "SendGrid Event Webhook", "Both",
         "Email open/click → SF Tasks; auto-create CHF Contact for unknown openers"],
        ["Real-time", "Railway deploy alerts", "Both",
         "Failed deploys → SMS + email to Chris within 60s"],
    ]
    story.append(make_table(schedule, col_widths=[1.0 * inch, 1.6 * inch, 1.0 * inch, 3.1 * inch],
                            font_size=8, header_font_size=9))

    story.append(PageBreak())


def build_costs_roi(story, styles):
    story.append(Paragraph("Costs &amp; ROI Math", styles["h1"]))
    story.append(Paragraph(
        "Honest numbers on what this stack costs to run and what revenue it should "
        "produce at scale.",
        styles["body"],
    ))

    story.append(Paragraph("Monthly recurring costs", styles["h2"]))
    costs = [
        ["Service", "Cost"],
        ["ATTOM Data (Investor Solutions + Distress Indicators)", "$800 - $1,000"],
        ["BatchLeads (skip-trace, ~4k lookups/mo)", "$500 - $700"],
        ["Buffer (content scheduling)", "$15"],
        ["SendGrid Essentials (50k emails/mo)", "$19.95"],
        ["Twilio (SMS + voice usage)", "~$50"],
        ["Cloudflare (Workers free tier)", "$0 - $5"],
        ["Railway (Python cron host)", "$5 - $20"],
        ["Constant Contact (existing, sunset planned)", "(check current)"],
        ["Mojo Dialer (existing)", "(check current)"],
        ["Subtotal — backend stack", "~$1,400 - $1,800"],
        ["", ""],
        ["Marketing budget (Chris's cap)", "$10,000"],
        ["  Direct mail (yellow letters, ~4,000 pieces)", "$5,000"],
        ["  Facebook ads", "$1,500"],
        ["  Google ads", "$1,000"],
        ["  YouTube pre-roll", "$500"],
        ["  Twilio SMS (covered above)", "—"],
        ["  Buffer / organic content", "(included)"],
        ["", ""],
        ["GRAND TOTAL MONTHLY", "$11,400 - $11,800"],
    ]
    story.append(make_table(costs, col_widths=[5.2 * inch, 1.5 * inch]))

    story.append(Spacer(1, 8))
    story.append(Paragraph("Path to $100k/mo NET", styles["h2"]))
    roi_math = [
        ["Scenario", "Deals/mo", "Avg spread", "Gross", "Net (after $11.5k)"],
        ["Conservative", "5", "$20,000", "$100,000", "$88,500"],
        ["Realistic target", "6", "$25,000", "$150,000", "$138,500"],
        ["Optimistic", "8", "$30,000", "$240,000", "$228,500"],
        ["Stretch", "10", "$35,000", "$350,000", "$338,500"],
    ]
    story.append(make_table(roi_math, col_widths=[1.5 * inch, 1.0 * inch,
                                                    1.2 * inch, 1.5 * inch, 1.5 * inch]))

    story.append(Spacer(1, 8))
    story.append(callout(
        "<b>Hitting $100k net requires roughly 5-6 deals/month at $25k average spread.</b> "
        "The data-driven Sell Score + multi-channel marketing should push spreads up "
        "(better-curated leads = better deals at lower prices) and keep deal volume in "
        "the 5-10/month range as the system warms up.",
        styles,
    ))

    story.append(PageBreak())


def build_risks(story, styles):
    story.append(Paragraph("Risks &amp; Backup Plans", styles["h1"]))
    story.append(Paragraph(
        "Honest assessment of what could go wrong and what we do about it.",
        styles["body"],
    ))

    risks = [
        ["Risk", "Likelihood", "Impact", "Mitigation"],
        ["Mac mini hardware failure",
         "Low (~5%/yr)",
         "Used to be HIGH (production halt)",
         "Railway migration (tomorrow) eliminates dependency"],
        ["Cloudflare outage",
         "Very low (~99.99% uptime)",
         "Webhook delivery pauses (1-2 hrs/yr)",
         "Acceptable; CF retries failed deliveries"],
        ["SendGrid daily limit hit",
         "Already handled",
         "Email throttling",
         "Essentials plan = 50k/mo, far above 500/day usage"],
        ["Twilio carrier filtering",
         "Medium",
         "SMS delivery degraded",
         "A2P 10DLC registration in progress; multi-number distribution active"],
        ["FB ad account suspension",
         "Low for housing ads",
         "Loss of FB acquisition channel",
         "Use Special Ad Category (Housing); follow guidelines; backup channel = direct mail"],
        ["ATTOM API contract delays",
         "Medium (1-2 weeks)",
         "Sell Score v3 delayed",
         "Free MD public records cover ~70% of distress signals as bridge"],
        ["Salesforce data corruption",
         "Very low",
         "Loss of leads/contacts",
         "Daily backup via SF native + manual export weekly"],
        ["Wholesaler list dries up",
         "Low",
         "Reduced deal volume",
         "Diversify with auction listings + direct sourcing"],
        ["Lead provider quality drops",
         "Medium",
         "Wasted ad spend",
         "Per-source tracking (LeadSource picklist) shows quality drift fast"],
    ]
    story.append(make_table(risks, col_widths=[1.6 * inch, 1.1 * inch, 1.5 * inch, 2.5 * inch],
                            font_size=8, header_font_size=9))

    story.append(Spacer(1, 8))
    story.append(Paragraph("Emergency contacts (fill in actual numbers)", styles["h2"]))
    emergency = [
        ["Who", "Role", "When to call"],
        ["Hard money lender 1", "Cash close in 7 days", "Deal needs cash close"],
        ["Hard money lender 2", "Backup", "If lender 1 unavailable"],
        ["Title company", "Closing logistics", "Closing or title issue"],
        ["RE attorney", "Contract questions", "Legal dispute or contract review"],
        ["CPA", "Tax / financial questions", "Year-end, structure changes"],
        ["Twilio support", "SMS deliverability", "Mass SMS rejections"],
        ["SendGrid support", "Email deliverability", "Bounce-rate spike"],
        ["Salesforce support", "CRM issues", "Login or data issues"],
    ]
    story.append(make_table(emergency, col_widths=[2.0 * inch, 2.0 * inch, 2.7 * inch]))

    story.append(PageBreak())


def build_tools_index(story, styles):
    story.append(Paragraph("Tools Built (Index)", styles["h1"]))
    story.append(Paragraph(
        "Every script, doc, and config in ~/dealmatcher/. Use this as a "
        "navigation map.",
        styles["body"],
    ))

    tools = [
        ["Path", "Purpose"],
        ["parser.py", "Wholesaler email + WhatsApp parser (clean address extraction)"],
        ["cheaphomesfla_scraper.py",
         "Main scraper — fetches mail, parses, matches buyers, sends per-buyer emails"],
        ["senders.txt", "Approved wholesaler email list (32 entries)"],
        ["mailbox_config.json", "Microsoft Graph mailbox config"],
        ["tools/audit_buyers.py", "Lists all CHF buyers + missing fields"],
        ["tools/backfill_buyer_zips.py",
         "Updates Buyer_Target_Zips__c on Contacts from JSON file"],
        ["tools/add_sf_fields.py + add_sf_fields_v2.py",
         "Creates SF custom fields + grants FLS"],
        ["tools/list_sf_custom_fields.py",
         "Lists all custom fields on Contact and Lead (diagnostic)"],
        ["tools/check_page_layouts.py",
         "Verifies which fields are on which page layouts"],
        ["tools/sell_score.py",
         "Phase 1 motivated-seller scorer using public records"],
        ["tools/buyer_score.py",
         "Buyer Score model (close history + engagement + capital + velocity)"],
        ["tools/build_below_market_seed.py",
         "Finds properties bought ≤60% of comp median"],
        ["tools/top_buyers_by_zip.py",
         "Ranks top 100 buyers per zip + cross-references SF"],
        ["tools/daily_deal_cards.py",
         "1080x1080 branded PNG deal cards for IG/FB content"],
        ["tools/render_per_buyer_email.py",
         "Tier-aware buyer email template (Hot/Warm/Cold)"],
        ["tools/fb_audience_hash.py",
         "SHA256 hash CSV for FB/Google Custom Audience uploads"],
        ["tools/morning_preflight.py",
         "Daily 1-command system status check"],
        ["tools/sf_setup_helper.py",
         "Creates list views via API + prints dashboard build guide"],
        ["tools/sf_state_snapshot.py",
         "Live Salesforce state snapshot (read-only)"],
        ["tools/score_existing_leads.py",
         "Quick Lead-fields-only scorer (deferred per Chris feedback)"],
        ["tools/dedup_leads.py",
         "Duplicate Lead finder + merger (deferred per Chris feedback)"],
        ["tools/system_watchdog.py", "Daily 9 AM health check + email alerts"],
        ["tools/cloud_health_check.py",
         "Hourly: CF Worker /health, PPL volume, SG bounce/complaint"],
        ["tools/daily_kpi_email.py",
         "9:15 AM green-day morning success summary"],
        ["tools/build_investor_list.py",
         "Pulls SF Contacts + senders.txt → dedup'd investor CSV"],
        ["tools/build_master_plan_pdf.py", "This PDF generator"],
        ["tools/build_automation_map_pdf.py", "Automation map PDF generator"],
        ["tools/build_sf_dashboards_pdf.py", "SF dashboards build-guide PDF"],
        ["tools/build_user_actions_pdf.py", "User-actions checklist PDF"],
        ["jb/email_campaign.py",
         "Cloud-ready 4-touch email drip (env-var creds)"],
        ["jb/sms_campaign.py",
         "Cloud-ready master SMS — 4 campaigns, multi-number"],
        ["jb/followup.py", "Cloud-ready status-driven SMS follow-up"],
        ["jb/sms_inbound.py",
         "Flask inbound SMS handler (legacy; Twilio Fn replaces)"],
        ["jb/digest.py", "Cloud-ready daily follow-up digest"],
        ["cloudflare/propertyleads-worker/",
         "Cloudflare Worker — Property Leads PPL → SF Lead"],
        ["cloudflare/motivatedsellers-worker/",
         "Cloudflare Worker — Motivated Sellers PPL → SF Lead"],
        ["cloudflare/whatsapp-worker/",
         "Cloudflare Worker — Green-API WA → email forward"],
        ["cloudflare/sendgrid-events/",
         "Cloudflare Worker — Email events → SF Tasks"],
        ["cloudflare/railway-deploy-alerts/",
         "Cloudflare Worker — Railway failed-deploy → SMS + email"],
        ["twilio-functions/sms_v2.js",
         "Smart inbound SMS classifier (auto-opt-out by negative type)"],
        ["plists/com.cheaphomes.dealmatcher.plist",
         "Cheaphomesfla scraper schedule (3x/day) — Mac fallback only"],
        ["plists/com.cheaphomes.watchdog.plist",
         "Watchdog schedule (9 AM daily) — Mac fallback only"],
        ["requirements.txt + Procfile + railway.json + .env.example",
         "Cloud deploy package — Railway auto-detects + installs"],
        ".gitignore — keeps secrets, logs, state out of git",
        ["docs/CLOUD_DEPLOY.md", "Step-by-step Railway deploy guide"],
        ["docs/USER_ACTIONS.md", "Single source: all 9 phases of clicks"],
        ["docs/SF_DASHBOARDS.md", "Click-by-click 10-dashboard build guide"],
        ["docs/automation_map.pdf", "Every cron, alert, gap visualization"],
        ["docs/day8_morning_routine_sop.md", "Daily ops SOP for traveling"],
        ["docs/new_laptop_setup_checklist.md", "MacBook Air setup steps"],
        ["docs/ad_copy_seller_side.md", "Seller-side ad copy + audiences"],
        ["docs/ad_copy_buyer_side.md", "Buyer-side ad copy + audiences"],
        ["docs/audience_definitions.md", "FB/Google audience definitions"],
        ["docs/twilio_function_v2_deploy.md", "Twilio /sms v2 deploy guide"],
        ["docs/cc_transition_email.html", "Constant Contact transition draft"],
        ["docs/master_plan.pdf", "This document"],
        ["sample_data/v1_vs_v2_summary.txt",
         "Parser improvement validation (97% → 85% clean)"],
    ]
    # Filter out any malformed rows (defensive — reportlab needs exactly 2 cols here)
    tools = [r for r in tools if isinstance(r, list) and len(r) == 2]
    story.append(make_table(tools, col_widths=[3.2 * inch, 3.5 * inch], font_size=8))

    story.append(PageBreak())


def build_summary(story, styles):
    story.append(Paragraph("Bottom Line", styles["h1"]))
    story.append(Paragraph(
        "After tomorrow's ~4-5 hour push, the Johnson Buys + CheapHomesFLA stack is:",
        styles["body"],
    ))
    bullets = [
        "Cloud-native: production runs on Railway + Cloudflare, no Mac mini dependency",
        "Inbound automated: PPL leads, WhatsApp, wholesaler emails all flow into Salesforce",
        "Outbound automated: email + SMS drips firing daily, smart inbound classification",
        "Visibility: 8-10 dashboards covering revenue, conversion, channel ROI, and pipeline health",
        "Resilient: watchdog catches breakage within 24 hours instead of multi-day silent failures",
        "Compliant: A2P 10DLC submitted, Advanced Opt-Out enabled, Special Ad Category set",
        "Income-tracking: 7 new Salesforce fields make $100k/mo measurable in real time",
    ]
    for b in bullets:
        story.append(bullet(b, styles))

    story.append(Spacer(1, 12))
    story.append(callout(
        "<b>Weekend = ad creative + activation.</b> By Sunday May 4, paid traffic is flowing. "
        "By Monday May 5, the Constant Contact transition email has gone out. "
        "By Friday May 8, ATTOM enrichment + retrospective Sell Score v3 turn the seller "
        "pipeline from guess-based to data-driven. Real income generation begins the week "
        "of May 4.",
        styles,
    ))

    story.append(Spacer(1, 16))
    story.append(Paragraph(
        "<i>End of master plan. Re-run "
        "<font face=\"Courier\">tools/build_master_plan_pdf.py</font> any time to "
        "regenerate with updated content.</i>",
        ParagraphStyle("Footer", parent=styles["body"], textColor=TEXT_MUTED,
                       alignment=TA_CENTER, fontSize=9),
    ))


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════
def main():
    styles = build_styles()
    doc = make_doc(OUT_PDF)
    story = []

    build_cover(story, styles)
    build_status_snapshot(story, styles)
    build_chf_section(story, styles)
    build_jb_section(story, styles)
    build_shared_infra(story, styles)
    build_migration_section(story, styles)
    build_phased_todo(story, styles)
    build_daily_schedule(story, styles)
    build_costs_roi(story, styles)
    build_risks(story, styles)
    build_tools_index(story, styles)
    build_summary(story, styles)

    doc.build(story)
    print(f"✓ Built: {OUT_PDF}")

    # Mirror to Desktop for easy access
    import shutil
    shutil.copyfile(OUT_PDF, DESKTOP_MIRROR)
    print(f"✓ Mirror: {DESKTOP_MIRROR}")


if __name__ == "__main__":
    main()
