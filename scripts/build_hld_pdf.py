#!/usr/bin/env python3
"""Build the submission HLD PDF from the version-controlled Markdown sources."""

from __future__ import annotations

import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether, PageBreak, Paragraph, Preformatted, SimpleDocTemplate,
    Spacer, Table, TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "submission/Netra_HLD.pdf"
SOURCES = [
    ("High-Level Design", ROOT / "HLD.md"),
    ("Scalability and Capacity Plan", ROOT / "SCALABILITY.md"),
    ("API and Integration Contract", ROOT / "API.md"),
    ("Requirements Traceability", ROOT / "REQUIREMENTS_TRACEABILITY.md"),
]


def ascii_safe(value: str) -> str:
    replacements = {
        "—": "-", "–": "-", "‑": "-", "→": "->", "←": "<-",
        "≥": ">=", "≤": "<=", "₹": "INR ", "·": " | ", "×": "x",
        "…": "...", "“": '"', "”": '"', "’": "'", "•": "-",
        "▪": "-", "■": "-", "§": "Section ",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    for char in "┌┐└┘├┤┬┴┼╔╗╚╝╠╣╦╩╬":
        value = value.replace(char, "+")
    for char in "─━═":
        value = value.replace(char, "-")
    for char in "│┃║":
        value = value.replace(char, "|")
    return value.encode("ascii", "replace").decode()


def inline(value: str) -> str:
    value = html.escape(ascii_safe(value.strip()))
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<u>\1</u>", value)
    value = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"`(.+?)`", r"<font name='Courier'>\1</font>", value)
    return value


def parse_markdown(text: str, styles: dict) -> list:
    lines = text.splitlines()
    story, paragraph, bullets = [], [], []
    in_code, code = False, []

    def flush_paragraph():
        if paragraph:
            story.append(Paragraph(inline(" ".join(paragraph)), styles["BodyNetra"]))
            story.append(Spacer(1, 2.2 * mm))
            paragraph.clear()

    def flush_bullets():
        if bullets:
            for item in bullets:
                story.append(Paragraph(inline(item), styles["BulletNetra"], bulletText="-"))
            story.append(Spacer(1, 1.8 * mm))
            bullets.clear()

    i = 0
    while i < len(lines):
        raw = lines[i].rstrip()
        if raw.startswith("```"):
            flush_paragraph(); flush_bullets()
            if in_code:
                story.append(Preformatted(ascii_safe("\n".join(code)), styles["CodeNetra"]))
                story.append(Spacer(1, 2 * mm)); code.clear(); in_code = False
            else:
                in_code = True
            i += 1; continue
        if in_code:
            code.append(raw); i += 1; continue
        if raw.startswith("|") and i + 1 < len(lines) and re.match(r"^\|?\s*:?-+", lines[i + 1]):
            flush_paragraph(); flush_bullets()
            rows = []
            header = [cell.strip() for cell in raw.strip("|").split("|")]
            rows.append([Paragraph(inline(cell), styles["TableHead"]) for cell in header])
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                cells = [cell.strip() for cell in lines[i].strip("|").split("|")]
                cells += [""] * (len(header) - len(cells))
                rows.append([Paragraph(inline(cell), styles["TableBody"]) for cell in cells[:len(header)]])
                i += 1
            width = 174 * mm / len(header)
            table = Table(rows, colWidths=[width] * len(header), repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#10233D")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F7FB")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.extend([table, Spacer(1, 3 * mm)])
            continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", raw)
        if heading:
            flush_paragraph(); flush_bullets()
            level = len(heading.group(1))
            story.append(Paragraph(inline(heading.group(2)), styles[f"H{level}"]))
            story.append(Spacer(1, 1.5 * mm)); i += 1; continue
        bullet = re.match(r"^\s*[-*]\s+(.+)$", raw)
        if bullet:
            flush_paragraph(); bullets.append(bullet.group(1)); i += 1; continue
        if bullets and raw[:1].isspace():
            bullets[-1] += " " + raw.strip(); i += 1; continue
        if not raw.strip() or raw.strip() == "---":
            flush_paragraph(); flush_bullets(); i += 1; continue
        paragraph.append(raw.strip()); i += 1
    flush_paragraph(); flush_bullets()
    return story


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#CBD5E1")); canvas.line(18 * mm, 14 * mm, 192 * mm, 14 * mm)
    canvas.setFont("Helvetica", 7); canvas.setFillColor(colors.HexColor("#64748B"))
    canvas.drawString(18 * mm, 9 * mm, "Netra - Gujarat Police Innovation Challenge 2026")
    canvas.drawRightString(192 * mm, 9 * mm, str(doc.page))
    canvas.restoreState()


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    base = getSampleStyleSheet()
    styles = {
        "Title": ParagraphStyle("TitleNetra", parent=base["Title"], fontName="Helvetica-Bold", fontSize=28, leading=32, textColor=colors.HexColor("#10233D"), alignment=TA_CENTER, spaceAfter=10),
        "Subtitle": ParagraphStyle("SubtitleNetra", parent=base["BodyText"], fontName="Helvetica", fontSize=12, leading=17, textColor=colors.HexColor("#475569"), alignment=TA_CENTER),
        "H1": ParagraphStyle("H1Netra", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=19, leading=23, textColor=colors.HexColor("#10233D"), spaceBefore=8),
        "H2": ParagraphStyle("H2Netra", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=colors.HexColor("#174A7E"), spaceBefore=6),
        "H3": ParagraphStyle("H3Netra", parent=base["Heading3"], fontName="Helvetica-Bold", fontSize=11.5, leading=15, textColor=colors.HexColor("#0F766E"), spaceBefore=4),
        "H4": ParagraphStyle("H4Netra", parent=base["Heading4"], fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=colors.HexColor("#334155")),
        "BodyNetra": ParagraphStyle("BodyNetra", parent=base["BodyText"], fontName="Helvetica", fontSize=8.8, leading=12.2, textColor=colors.HexColor("#1E293B")),
        "BulletNetra": ParagraphStyle("BulletNetra", parent=base["BodyText"], fontName="Helvetica", fontSize=8.6, leading=11.8, leftIndent=12, firstLineIndent=-7, bulletIndent=3, textColor=colors.HexColor("#1E293B")),
        "CodeNetra": ParagraphStyle("CodeNetra", parent=base["Code"], fontName="Courier", fontSize=6.5, leading=8.2, leftIndent=5, rightIndent=5, backColor=colors.HexColor("#F1F5F9"), borderPadding=6),
        "TableHead": ParagraphStyle("TableHead", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=6.6, leading=8.2, textColor=colors.white),
        "TableBody": ParagraphStyle("TableBody", parent=base["BodyText"], fontName="Helvetica", fontSize=6.3, leading=8.0, textColor=colors.HexColor("#1E293B")),
    }
    doc = SimpleDocTemplate(str(OUT), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=18 * mm, bottomMargin=19 * mm, title="Netra High-Level Design", author="Netra Team")
    story = [Spacer(1, 35 * mm), Paragraph("NETRA", styles["Title"]), Paragraph("Unified CCTV Integration and Intelligence Platform", styles["Subtitle"]), Spacer(1, 8 * mm), Paragraph("High-Level Design, Scalability, API and Requirements Traceability", styles["Subtitle"]), Spacer(1, 12 * mm), Paragraph("Gujarat Police Innovation Challenge 2026", styles["Subtitle"]), PageBreak()]
    for index, (title, path) in enumerate(SOURCES):
        if index:
            story.append(PageBreak())
        story.append(Paragraph(title, styles["H1"]))
        story.extend(parse_markdown(path.read_text(), styles))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(OUT)


if __name__ == "__main__":
    main()
