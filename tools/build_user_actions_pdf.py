#!/usr/bin/env python3
"""Build USER_ACTIONS.md → PDF on ~/Desktop."""
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
                       fontSize=15, leading=19, textColor=NAVY,
                       spaceBefore=14, spaceAfter=8)
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
                       fontSize=8.8, leading=11, leftIndent=10,
                       backColor=BG, borderPadding=4,
                       textColor=colors.HexColor("#1a1a1a"), spaceAfter=4)


def _footer(canv, doc):
    canv.saveState()
    canv.setFont("Helvetica", 8)
    canv.setFillColor(GREY)
    canv.drawString(0.75*inch, 0.45*inch,
                    "Christopher's Action List · Cloud Migration + Launch")
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
    table_rows: list[list[str]] = []

    def flush_code():
        nonlocal code_buf
        if code_buf:
            story.append(Paragraph("<br/>".join(code_buf), CODE))
            code_buf = []

    def flush_table():
        nonlocal table_rows
        if not table_rows:
            return
        if len(table_rows) >= 2 and all(set(c.strip()) <= set("-:|") for c in table_rows[1]):
            header = table_rows[0]
            rows = table_rows[2:]
        else:
            header, rows = table_rows[0], table_rows[1:]
        data = [[Paragraph(md_inline(c.strip()),
                          ParagraphStyle("th", parent=BODY, textColor=WHITE,
                                          fontName="Helvetica-Bold", fontSize=9))
                 for c in header]]
        for r in rows:
            data.append([Paragraph(md_inline(c.strip()),
                         ParagraphStyle("td", parent=BODY, fontSize=9, leading=11))
                         for c in r])
        cw = [6.5*inch / max(1, len(header))] * len(header)
        t = Table(data, colWidths=cw, repeatRows=1)
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
        if line.lstrip().startswith("|") and line.rstrip().endswith("|"):
            cells = line.strip().strip("|").split("|")
            table_rows.append(cells)
            i += 1
            continue
        else:
            flush_table()

        if line.startswith("# "):
            story.append(Paragraph(md_inline(line[2:].strip()), TITLE))
        elif line.startswith("## "):
            story.append(PageBreak())
            story.append(Paragraph(md_inline(line[3:].strip()), H1))
        elif line.startswith("### "):
            story.append(Paragraph(md_inline(line[4:].strip()), H2))
        elif line.startswith("#### "):
            story.append(Paragraph(md_inline(line[5:].strip()), H3))
        elif line.startswith("---"):
            story.append(_hbar())
            story.append(Spacer(1, 4))
        elif re.match(r"^\d+\.\s+", line):
            num, rest = re.match(r"^(\d+)\.\s+(.+)", line).groups()
            story.append(Paragraph(f"<b>{num}.</b> {md_inline(rest)}", BULLET))
        elif line.startswith("- "):
            story.append(Paragraph(f"• {md_inline(line[2:].strip())}", BULLET))
        elif line.strip() == "":
            story.append(Spacer(1, 4))
        else:
            story.append(Paragraph(md_inline(line.strip()), BODY))
        i += 1
    flush_code()
    flush_table()
    return story


def main() -> None:
    md_path = Path(__file__).resolve().parent.parent / "docs" / "USER_ACTIONS.md"
    pdf_path = Path(__file__).resolve().parent.parent / "docs" / "user_actions.pdf"
    desk = Path.home() / "Desktop" / "user_actions.pdf"

    md = md_path.read_text()
    today = dt.date.today().strftime("%A, %B %-d, %Y")

    story = []
    story.append(Paragraph("Christopher's Action List", TITLE))
    story.append(Paragraph(
        f"Cloud Migration + Launch &nbsp;·&nbsp; {today} &nbsp;·&nbsp; "
        "Phases 1-9 &nbsp;·&nbsp; ~3 hours of clicks total",
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
        title="Christopher's Action List",
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
