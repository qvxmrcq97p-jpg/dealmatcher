#!/usr/bin/env python3
"""Render docs/TODAY_CHECKLIST.md → PDF on ~/Desktop with real checkbox glyphs."""
from __future__ import annotations
import datetime as dt, re, shutil
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)

NAVY  = colors.HexColor("#0F2540")
GOLD  = colors.HexColor("#C8A446")
GREEN = colors.HexColor("#2A8B5F")
RED   = colors.HexColor("#B83B3B")
GREY  = colors.HexColor("#5C6470")
BG    = colors.HexColor("#F5F2EA")
WHITE = colors.white
ss = getSampleStyleSheet()

TITLE = ParagraphStyle("T", parent=ss["Title"], fontName="Helvetica-Bold",
                       fontSize=22, leading=26, textColor=NAVY,
                       spaceAfter=4, alignment=TA_LEFT)
SUBT  = ParagraphStyle("S", parent=ss["Normal"], fontSize=11, leading=14,
                       textColor=GREY, spaceAfter=12, alignment=TA_LEFT)
H1    = ParagraphStyle("H1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                       fontSize=16, leading=20, textColor=NAVY,
                       spaceBefore=14, spaceAfter=8)
H2    = ParagraphStyle("H2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                       fontSize=12, leading=15, textColor=NAVY,
                       spaceBefore=10, spaceAfter=4)
BODY  = ParagraphStyle("B", parent=ss["Normal"], fontName="Helvetica",
                       fontSize=10.5, leading=14,
                       textColor=colors.HexColor("#222222"), spaceAfter=4)
CHECKBOX = ParagraphStyle("Cb", parent=BODY, fontSize=11, leading=15,
                          leftIndent=12, spaceAfter=5,
                          textColor=colors.HexColor("#1a1a1a"))
CODE  = ParagraphStyle("Code", parent=ss["Code"], fontName="Courier",
                       fontSize=9, leading=12, leftIndent=14,
                       backColor=BG, borderPadding=4,
                       textColor=colors.HexColor("#1a1a1a"), spaceAfter=4)


def _footer(canv, doc):
    canv.saveState()
    canv.setFont("Helvetica", 8)
    canv.setFillColor(GREY)
    canv.drawString(0.75*inch, 0.45*inch,
                    "Christopher's Today Checklist · Cloud Migration + Launch")
    canv.drawRightString(LETTER[0]-0.75*inch, 0.45*inch, f"Page {doc.page}")
    canv.restoreState()


def _hbar(width=6.5*inch, h=2, color=GOLD):
    t = Table([[""]], colWidths=[width], rowHeights=[h])
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),color)]))
    return t


def md_inline(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"`([^`]+)`", r'<font face="Courier" color="#1a1a1a">\1</font>', text)
    return text


def parse_md(md: str) -> list:
    story = []
    lines = md.splitlines()
    in_code = False
    code_buf: list[str] = []

    def flush_code():
        nonlocal code_buf
        if code_buf:
            story.append(Paragraph("<br/>".join(code_buf), CODE))
            code_buf = []

    i = 0
    while i < len(lines):
        line = lines[i]
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

        if line.startswith("# "):
            story.append(Paragraph(md_inline(line[2:].strip()), TITLE))
        elif line.startswith("## "):
            story.append(Paragraph(md_inline(line[3:].strip()), H1))
        elif line.startswith("### "):
            story.append(Paragraph(md_inline(line[4:].strip()), H2))
        elif line.startswith("---"):
            story.append(_hbar())
            story.append(Spacer(1, 4))
        elif line.startswith("☐ "):
            # Real checkbox — render with bigger, bolder glyph
            text = md_inline(line[2:].strip())
            story.append(Paragraph(
                f'<font size="13" color="#0F2540">☐</font>&nbsp;&nbsp;{text}',
                CHECKBOX,
            ))
        elif line.lstrip().startswith("- "):
            stripped = line.lstrip()
            indent = len(line) - len(stripped)
            extra_indent = "&nbsp;" * (indent * 4 + 4)
            story.append(Paragraph(
                f"{extra_indent}• {md_inline(stripped[2:].strip())}",
                ParagraphStyle("Sub", parent=BODY, fontSize=9.5, leading=12,
                               leftIndent=12, spaceAfter=2,
                               textColor=GREY),
            ))
        elif re.match(r"^\s+\*", line):
            # italic continuation under a checkbox
            text = line.strip().lstrip("*").rstrip("*").strip()
            story.append(Paragraph(
                f"&nbsp;&nbsp;&nbsp;&nbsp;<i>{md_inline(text)}</i>",
                ParagraphStyle("Cont", parent=BODY, fontSize=9.5, leading=12,
                               leftIndent=20, spaceAfter=4, textColor=GREY),
            ))
        elif line.strip() == "":
            story.append(Spacer(1, 4))
        else:
            story.append(Paragraph(md_inline(line.strip()), BODY))
        i += 1
    flush_code()
    return story


def main() -> None:
    md_path = Path(__file__).resolve().parent.parent / "docs" / "TODAY_CHECKLIST.md"
    pdf_path = Path(__file__).resolve().parent.parent / "docs" / "today_checklist.pdf"
    desk = Path.home() / "Desktop" / "today_checklist.pdf"

    md = md_path.read_text()
    today = dt.date.today().strftime("%A, %B %-d, %Y")

    story = []
    story.append(Paragraph("Today's Checklist", TITLE))
    story.append(Paragraph(
        f"Christopher Johnson &nbsp;·&nbsp; {today} &nbsp;·&nbsp; "
        "Check items off as you complete them",
        SUBT,
    ))
    story.append(_hbar())
    story.append(Spacer(1, 8))

    md_no_h1 = re.sub(r"^# .+\n+", "", md, count=1)
    story.extend(parse_md(md_no_h1))

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(
        str(pdf_path), pagesize=LETTER,
        leftMargin=0.75*inch, rightMargin=0.75*inch,
        topMargin=0.7*inch, bottomMargin=0.7*inch,
        title="Today's Checklist",
        author="Christopher Johnson",
    ).build(story, onFirstPage=_footer, onLaterPages=_footer)

    print(f"✓ {pdf_path}")
    try:
        shutil.copyfile(pdf_path, desk)
        print(f"✓ {desk}")
    except Exception as e:
        print(f"⚠️  Desktop copy failed: {e}")


if __name__ == "__main__":
    main()
