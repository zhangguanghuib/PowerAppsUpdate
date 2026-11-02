from __future__ import annotations

import os
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Flowable,
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

if TYPE_CHECKING:
    from monitor import Article, Change


def register_font() -> str:
    candidates = [
        os.environ.get("PDF_FONT", ""),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            pdfmetrics.registerFont(TTFont("Body", candidate))
            return "Body"
    raise FileNotFoundError("Set PDF_FONT to a Unicode TrueType font (e.g. DejaVuSans.ttf).")


def safe_text(value: str, font: str) -> str:
    value = re.sub("[\u2010-\u2015\u2212]", "-", value)
    glyphs = pdfmetrics.getFont(font).face.charToGlyph
    return "".join(
        character
        if ord(character) in glyphs or character in "\n\t"
        else f"[U+{ord(character):04X}]"
        for character in value
    )


def changed_blocks(before: str, after: str) -> list[tuple[str, str, str]]:
    old, new = before.splitlines(), after.splitlines()
    return [
        (kind, "\n".join(old[i:j]), "\n".join(new[start:end]))
        for kind, i, j, start, end in SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
        if kind != "equal"
    ]


def generate_pdf(
    changes: list[Change],
    destination: Path,
    *,
    now: datetime,
    since: str,
    articles: dict[str, Article],
    initial: bool,
) -> None:
    font = register_font()
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = font
    body = ParagraphStyle(
        "ReportBody",
        parent=styles["BodyText"],
        fontName=font,
        fontSize=9,
        leading=14,
        spaceAfter=7,
        alignment=TA_LEFT,
        splitLongWords=True,
    )
    small = ParagraphStyle("ReportSmall", parent=body, fontSize=8, leading=12)
    heading = ParagraphStyle(
        "ReportHeading",
        parent=styles["Heading2"],
        fontName=font,
        textColor=colors.HexColor("#114B5F"),
        spaceAfter=10,
    )
    story: list[Flowable] = []

    def paragraph(text: str, style: ParagraphStyle = body) -> None:
        value = escape(safe_text(text.expandtabs(4), font)).replace("\n", "<br/>")
        indent = len(value) - len(value.lstrip(" "))
        if indent:
            value = "&#160;" * indent + value[indent:]
        story.append(Paragraph(value, style))

    def block(label: str, content: str, color: str) -> None:
        paragraph(label, heading)
        story.append(HRFlowable(width="100%", color=colors.HexColor(color)))
        # Separate paragraphs allow page splitting even for very long articles and source lines.
        for line in content.splitlines():
            paragraph(line or " ", small)

    paragraph("POWER APPS", styles["Title"])
    paragraph("Documentation change report", styles["Heading1"])
    paragraph(f"Generated (UTC): {now.isoformat()}")
    paragraph(f"Observation window: {since} to {now.isoformat()}")
    paragraph(
        f"{len(changes)} entries | {'Initial 30-day review' if initial else 'Snapshot comparison'}"
    )
    story.append(Spacer(1, 6 * mm))
    paragraph(
        "Scope: English Microsoft Learn Power Apps documentation and Power Apps troubleshooting. "
        "Documentation changes are not necessarily new product features. Modification timestamps "
        "are not feature release dates. No AI interpretation is used."
    )
    paragraph(
        "Initial reports select candidates using published modification timestamps. Public source "
        "history is auxiliary and can lag or differ from publication; "
        "incomplete history is labeled. "
        "Later reports compare fetched, normalized published text, links and image references."
    )
    paragraph(
        "Attribution: Microsoft and Microsoft Learn contributors. Source text is reproduced or "
        "reformatted for comparison; links identify each original. Public documentation sources: "
        "https://github.com/MicrosoftDocs/powerapps-docs and "
        "https://github.com/MicrosoftDocs/SupportArticles-docs . "
        "Documentation text licensed under CC BY 4.0: "
        "https://creativecommons.org/licenses/by/4.0/ . "
        "Third-party materials may have separate terms. No images are reproduced.",
        small,
    )
    paragraph(
        "Text formatting: unsupported font glyphs are represented as [U+XXXX] to preserve their "
        "identity. Image references are monitored, not image binary contents. This report does not "
        "claim to capture every intermediate edit between scans.",
        small,
    )
    paragraph("Contents", heading)
    for index, change in enumerate(changes, 1):
        paragraph(f"{index}. {change.title} - {change.kind}", small)
    for index, change in enumerate(changes, 1):
        story.append(PageBreak())
        paragraph(f"{index}. {change.title}", heading)
        paragraph(change.kind)
        story.append(
            Paragraph(
                f'<link href="{escape(change.url, {chr(34): "&quot;"})}" color="#126782">'
                f"{escape(change.url)}</link>",
                small,
            )
        )
        paragraph(change.evidence, small)
        blocks = changed_blocks(change.before, change.after)
        if not blocks:
            paragraph("No normalized source-body difference found.")
        for number, (kind, before, after) in enumerate(blocks, 1):
            paragraph(f"Change block {number}: {kind}", heading)
            if before:
                block("Before / removed", before, "#B54747")
            if after:
                block("After / added", after, "#2B7D62")
        if change.kind == "Historical source comparison":
            block(
                "Current published article (not historical)", articles[change.url].text, "#126782"
            )

    def footer(canvas: Canvas, document: SimpleDocTemplate) -> None:
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#D7E1E5"))
        canvas.line(18 * mm, 17 * mm, 192 * mm, 17 * mm)
        canvas.setFont(font, 8)
        canvas.drawString(18 * mm, 12 * mm, "Power Apps | Microsoft Learn change monitor")
        canvas.drawRightString(192 * mm, 12 * mm, f"Page {document.page}")
        canvas.restoreState()

    destination.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(destination),
        pagesize=(210 * mm, 297 * mm),
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=23 * mm,
        title="Power Apps documentation changes",
        author="Power Apps documentation monitor",
    )
    document.build(story, onFirstPage=footer, onLaterPages=footer)
