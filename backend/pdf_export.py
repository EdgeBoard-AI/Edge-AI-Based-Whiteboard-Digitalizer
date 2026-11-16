from __future__ import annotations

import html
import os
import re
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

from config import CLASS_NOTES_DIR


class PDFExportError(RuntimeError):
    pass


def _register_fonts() -> tuple[str, str]:
    windows_fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    candidates = [
        (windows_fonts / "arial.ttf", windows_fonts / "arialbd.ttf"),
        (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ),
    ]
    for regular_path, bold_path in candidates:
        if not regular_path.is_file():
            continue
        regular_name = "EdgeBoardSans"
        bold_name = "EdgeBoardSans-Bold"
        if regular_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(regular_name, str(regular_path)))
        if bold_path.is_file() and bold_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(bold_name, str(bold_path)))
        else:
            bold_name = regular_name
        pdfmetrics.registerFontFamily(
            regular_name,
            normal=regular_name,
            bold=bold_name,
            italic=regular_name,
            boldItalic=bold_name,
        )
        return regular_name, bold_name
    return "Helvetica", "Helvetica-Bold"


def _inline_markup(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", escaped)
    return escaped


def _markdown_story(markdown: str, regular_font: str, bold_font: str) -> list:
    base = getSampleStyleSheet()["BodyText"]
    styles = {
        "title": ParagraphStyle(
            "ClassNotesTitle",
            parent=base,
            fontName=bold_font,
            fontSize=22,
            leading=28,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#183153"),
            spaceAfter=8,
        ),
        "subtitle": ParagraphStyle(
            "ClassNotesSubtitle",
            parent=base,
            fontName=regular_font,
            fontSize=9,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#52657a"),
            spaceAfter=18,
        ),
        "h1": ParagraphStyle(
            "ClassNotesH1",
            parent=base,
            fontName=bold_font,
            fontSize=17,
            leading=22,
            textColor=colors.HexColor("#183153"),
            spaceBefore=12,
            spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "ClassNotesH2",
            parent=base,
            fontName=bold_font,
            fontSize=13,
            leading=17,
            textColor=colors.HexColor("#24527a"),
            spaceBefore=10,
            spaceAfter=5,
        ),
        "h3": ParagraphStyle(
            "ClassNotesH3",
            parent=base,
            fontName=bold_font,
            fontSize=11,
            leading=15,
            spaceBefore=8,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "ClassNotesBody",
            parent=base,
            fontName=regular_font,
            fontSize=10,
            leading=15,
            spaceAfter=5,
        ),
        "bullet": ParagraphStyle(
            "ClassNotesBullet",
            parent=base,
            fontName=regular_font,
            fontSize=10,
            leading=15,
            leftIndent=16,
            firstLineIndent=-10,
            spaceAfter=3,
        ),
    }

    story = [
        Paragraph("EdgeBoard AI — Class Notes", styles["title"]),
        Paragraph(
            f"Generated {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')}",
            styles["subtitle"],
        ),
        HRFlowable(width="100%", color=colors.HexColor("#c8d4e3"), thickness=0.8),
        Spacer(1, 10),
    ]
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            story.append(Spacer(1, 4))
        elif line == "---":
            story.append(HRFlowable(width="100%", color=colors.HexColor("#c8d4e3")))
            story.append(Spacer(1, 6))
        elif line.startswith("### "):
            story.append(Paragraph(_inline_markup(line[4:]), styles["h3"]))
        elif line.startswith("## "):
            story.append(Paragraph(_inline_markup(line[3:]), styles["h2"]))
        elif line.startswith("# "):
            story.append(Paragraph(_inline_markup(line[2:]), styles["h1"]))
        elif re.match(r"^[-*+]\s+", line):
            story.append(Paragraph("• " + _inline_markup(line[2:]), styles["bullet"]))
        elif re.match(r"^\d+[.)]\s+", line):
            story.append(Paragraph(_inline_markup(line), styles["bullet"]))
        else:
            story.append(Paragraph(_inline_markup(line), styles["body"]))
    return story


def save_class_notes_pdf(markdown: str) -> Path:
    CLASS_NOTES_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    output_path = CLASS_NOTES_DIR / f"class_notes_{timestamp}.pdf"
    regular_font, bold_font = _register_fonts()
    document = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=54,
        leftMargin=54,
        topMargin=54,
        bottomMargin=48,
        title="EdgeBoard AI Class Notes",
        author="EdgeBoard AI",
    )

    def add_page_number(canvas, doc):
        canvas.saveState()
        canvas.setFont(regular_font, 8)
        canvas.setFillColor(colors.HexColor("#52657a"))
        canvas.drawRightString(A4[0] - doc.rightMargin, 24, f"Page {doc.page}")
        canvas.restoreState()

    try:
        document.build(
            _markdown_story(markdown, regular_font, bold_font),
            onFirstPage=add_page_number,
            onLaterPages=add_page_number,
        )
    except (OSError, ValueError) as exc:
        raise PDFExportError(f"Could not create class notes PDF: {exc}") from exc
    return output_path
