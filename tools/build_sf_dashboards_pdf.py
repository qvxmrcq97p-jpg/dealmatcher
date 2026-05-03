#!/usr/bin/env python3
"""
build_sf_dashboards_pdf.py
──────────────────────────
Builds a printable PDF version of docs/SF_DASHBOARDS.md so Christopher
can sit down with it on a screen or paper and execute every click.

Saves to:
  ~/dealmatcher/docs/sf_dashboards_guide.pdf
  ~/Desktop/sf_dashboards_guide.pdf

Run:
  cd ~/dealmatcher && python3 tools/build_sf_dashboards_pdf.py
"""

from __future__ import annotations
import datetime as dt
import re
import shutil
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
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
)

NAVY  = colors.HexColor("#0F2540")
GOLD  = colors.HexColor("#C8A446")
GREEN = colors.HexColor("#2A8B5F")
GREY  = colors.HexColor("#5C6470")
BG    = colors.HexColor("#F5F2EA")
WHITE = colors.white

ss = getSampleStyleSheet()

TITLE = ParagraphStyle("T", parent=ss["Title"], fontName="Helvetica-Bold",
                       fontSize=22, leading=26, textColor=NAVY, spaceAfter=4,
                       alignment=TA_LEFT)
SUBT  = ParagraphStyle("S", parent=ss["Normal"], fontSize=11, leading=14,
                       textColor=GREY, spaceAfter=12, alignment=TA_LEFT)
H1    = ParagraphStyle("H1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                       fontSize=15, leading=19, textColor=NAVY,
                       spaceBefore=16, spaceAfter=8)
H2    = ParagraphStyle("H2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                       fontSize=12, leading=15, textColor=NAVY,
                       spaceBefore=10, spaceAfter=4)
H3    = ParagraphStyle("H3", parent=ss["Heading3"], fontName="Helvetica-Bold",
                       fontSize=10.5, leading=13, textColor=NAVY,
                       spaceBefore=6, spaceAfter=3)
BODY  = ParagraphStyle("B", parent=ss["Normal"], fontName="Helvetica",
                       fontSize=10, leading=13.5,
                       textColor=colors.HexColor("#222222"), spaceAfter=4)
BULLET= ParagraphStyle("Bul", parent=BODY, leftIndent=14, bulletIndent=2,
                       fontSize=9.5, leading=12.5, spaceAfter=2)
CODE  = ParagraphStyle("Code", parent=ss["Code"], fontName="Courier",
                       fontSize=9, leading=11.5, leftIndent=10,
                       backColor=BG, borderPadding=4,
                       textColor=colors.HexColor("#1a1a1a"), spaceAfter=4)


def _footer(canv, doc):
    canv.saveState()
    canv.setFont("Helvetica", 8)
    canv.setFillColor(GREY)
    canv.drawString(0.75*inch, 0.45*inch,
                    "Christopher Johnson · Salesforce Dashboard Build Guide")
    canv.drawRightString(LETTER[0]-0.75*inch, 0.45*inch, f"Page {doc.page}")
    canv.restoreState()


def _hbar(width=6.5*inch, h=2, color=GOLD):
    t = Table([[""]], colWidths=[width], rowHeights=[h])
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),color)]))
    return t


def _md_inline_to_html(text: str) -> str:
    """Tiny MD→HTML for the few tags ReportLab supports inside Paragraph."""
    # bold **x**
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # italics *x* (avoid double-star false positives — done first above)
    text = re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)', r'<i>\1</i>', text)
    # inline code `x`
    text = re.sub(r'`([^`]+)`', r'<font face="Courier" color="#1a1a1a">\1</font>', text)
    # & < > escaping (only after we've inserted our tags)
    # ReportLab's Paragraph handles & and < specially; we'll let our tags pass
    return text


def parse_md_to_story(md: str) -> list:
    """Convert the dashboard markdown into a ReportLab story.
    Handles headings, paragraphs, bullets, numbered lists, tables (--- pipe).
    Code fences are rendered as preformatted blocks.
    """
    story = []
    lines = md.splitlines()
    i = 0
    in_code = False
    code_buf: list[str] = []

    def flush_code():
        nonlocal code_buf
        if code_buf:
            story.append(Paragraph("<br/>".join(code_buf), CODE))
            code_buf = []

    table_rows: list[list[str]] = []

    def flush_table():
        nonlocal table_rows
        if not table_rows:
            return
        if len(table_rows) >= 2 and all(set(c.strip()) <= set("-:|") for c in table_rows[1]):
            header = table_rows[0]
            rows = table_rows[2:]
        else:
            header, rows = table_rows[0], table_rows[1:]
        data = [[Paragraph(_md_inline_to_html(c.strip()),
                          ParagraphStyle("th", parent=BODY, textColor=WHITE,
                                          fontName="Helvetica-Bold", fontSize=9))
                 for c in header]]
        for r in rows:
            data.append([Paragraph(_md_inline_to_html(c.strip()),
                         ParagraphStyle("td", parent=BODY, fontSize=9, leading=11))
                         for c in r])
        col_widths = [6.5*inch / max(1, len(header))] * len(header)
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0), NAVY),
            ("VALIGN",(0,0),(-1,-1),"TOP"),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE, BG]),
            ("LEFTPADDING",(0,0),(-1,-1), 5),
            ("RIGHTPADDING",(0,0),(-1,-1), 5),
            ("TOPPADDING",(0,0),(-1,-1), 4),
            ("BOTTOMPADDING",(0,0),(-1,-1), 4),
        ]))
        story.append(t)
        story.append(Spacer(1, 6))
        table_rows = []

    while i < len(lines):
        line = lines[i]
        # code fence
        if line.strip().startswith("```"):
            if in_code:
                flush_code()
                in_code = False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(line.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;"))
            i += 1
            continue
        # table row
        if line.lstrip().startswith("|") and line.rstrip().endswith("|"):
            cells = [c for c in line.strip().strip("|").split("|")]
            table_rows.append(cells)
            i += 1
            continue
        else:
            flush_table()

        # headings
        if line.startswith("# "):
            story.append(Paragraph(_md_inline_to_html(line[2:].strip()), TITLE))
        elif line.startswith("## "):
            story.append(PageBreak())
            story.append(Paragraph(_md_inline_to_html(line[3:].strip()), H1))
        elif line.startswith("### "):
            story.append(Paragraph(_md_inline_to_html(line[4:].strip()), H2))
        elif line.startswith("#### "):
            story.append(Paragraph(_md_inline_to_html(line[5:].strip()), H3))
        elif line.startswith("---"):
            story.append(_hbar())
            story.append(Spacer(1, 4))
        elif re.match(r"^\d+\.\s+", line):
            num, rest = re.match(r"^(\d+)\.\s+(.+)", line).groups()
            story.append(Paragraph(f"<b>{num}.</b> {_md_inline_to_html(rest)}", BULLET))
        elif line.startswith("- "):
            story.append(Paragraph(f"• {_md_inline_to_html(line[2:].strip())}", BULLET))
        elif line.strip() == "":
            story.append(Spacer(1, 4))
        else:
            story.append(Paragraph(_md_inline_to_html(line.strip()), BODY))
        i += 1
    flush_code()
    flush_table()
    return story


def main() -> None:
    md_path  = Path(__file__).resolve().parent.parent / "docs" / "SF_DASHBOARDS.md"
    pdf_path = Path(__file__).resolve().parent.parent / "docs" / "sf_dashboards_guide.pdf"
    desk_pdf = Path.home() / "Desktop" / "sf_dashboards_guide.pdf"

    md = md_path.read_text()
    today = dt.date.today().strftime("%A, %B %-d, %Y")

    story = []
    story.append(Paragraph("Salesforce Dashboards — Build Guide", TITLE))
    story.append(Paragraph(
        f"Christopher Johnson &nbsp;·&nbsp; Johnson Buys + CheapHomesFLA "
        f"&nbsp;·&nbsp; {today} &nbsp;·&nbsp; "
        "10 dashboards · ~60 min · click-by-click",
        SUBT,
    ))
    story.append(_hbar())
    story.append(Spacer(1, 8))

    # parse the rest, skipping the H1 we already showed manually
    md_no_h1 = re.sub(r"^# .+\n+", "", md, count=1)
    story.extend(parse_md_to_story(md_no_h1))

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(
        str(pdf_path), pagesize=LETTER,
        leftMargin=0.75*inch, rightMargin=0.75*inch,
        topMargin=0.7*inch, bottomMargin=0.7*inch,
        title="Salesforce Dashboards — Build Guide",
        author="Christopher Johnson",
    ).build(story, onFirstPage=_footer, onLaterPages=_footer)

    print(f"✓ {pdf_path}")
    try:
        shutil.copyfile(pdf_path, desk_pdf)
        print(f"✓ {desk_pdf}")
    except Exception as e:
        print(f"⚠️  Desktop copy failed: {e}")


if __name__ == "__main__":
    main()
