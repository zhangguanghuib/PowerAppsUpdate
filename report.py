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
    KeepTogether,
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


def excerpt(text: str, *, limit: int = 320) -> str:
    lines = []
    in_code = False
    for line in text.splitlines():
        if line.strip().startswith(("```", "[Code]", "[/Code]")):
            in_code = not in_code
            continue
        if in_code or line.lstrip().startswith(("[Image:", "<", "[!", ":::")):
            continue
        if line.strip() in {"Note", "Important", "Tip", "In this article"}:
            continue
        if line.startswith("This article describes features used in agents or agent flows"):
            continue
        line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)
        line = re.sub(r"\s*\(https?://[^)\s]+\)", "", line)
        line = re.sub(r"https?://\S+", "", line)
        line = re.sub(r"^[#>*\s-]+", "", line).strip("` |")
        if line:
            lines.append(line)
    text = re.sub(r"\s+", " ", " ".join(lines)).strip()
    if len(text) > limit:
        return text[:limit].rsplit(" ", 1)[0] + "..."
    return text


def summarize(change: Change) -> str:
    if change.kind != "Historical source comparison":
        overview = excerpt("\n".join(change.after.splitlines()[1:])) or excerpt(change.after)
        return (
            "Current article overview (not a change claim; history unavailable or disabled): "
            f"{overview or 'See the linked article.'}"
        )
    blocks = changed_blocks(change.before, change.after)
    if not blocks:
        return (
            "The modification timestamp is in range, but no public source-body changes were "
            "found. The update may be metadata-only or differ from public source publication."
        )
    added = "\n".join(after for _, _, after in blocks if after)
    removed = "\n".join(before for _, before, _ in blocks if before)
    parts = [f"Public source comparison: {len(blocks)} changed block(s)."]
    if added:
        parts.append(f"Added/updated excerpt: {excerpt(added) or 'Non-prose source changes.'}")
    if removed:
        parts.append(f"Removed/replaced excerpt: {excerpt(removed) or 'Non-prose source changes.'}")
    parts.append("Representative excerpts only; source changes may differ from the live page.")
    return " ".join(parts)


def generate_pdf(
    changes: list[Change],
    destination: Path,
    *,
    now: datetime,
    since: str,
    articles: dict[str, Article],
    partial: bool = False,
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

    paragraph("MICROSOFT COPILOT STUDIO", styles["Title"])
    paragraph("Documentation update digest", styles["Heading1"])
    paragraph(f"Generated (UTC): {now.isoformat()}")
    paragraph(f"Observation window: {since} to {now.isoformat()}")
    paragraph(f"{len(changes)} new or updated document candidates")
    if partial:
        paragraph("PARTIAL SMOKE TEST - not a complete directory report", heading)
    story.append(Spacer(1, 6 * mm))
    paragraph(
        "Scope: English Microsoft Learn Copilot Studio documentation and troubleshooting. "
        "Documentation changes are not necessarily new product features. Modification timestamps "
        "are not feature release dates. No AI interpretation is used."
    )
    paragraph(
        "Every run independently selects articles using their published updated_at timestamp "
        "(sitemap lastmod when absent), within the inclusive UTC window above. "
        "New and updated articles are combined: a recent modification date alone does not prove "
        "that an article is newly created. Summaries use representative public source changes "
        "since the window start, not AI interpretation. If history is unavailable, an overview "
        "of the current article is explicitly labeled instead of claiming unverified changes."
    )
    paragraph(
        "Attribution: Microsoft and Microsoft Learn contributors. Source text is reproduced or "
        "reformatted into short extracts; links identify each original. "
        "Public GitHub source history is used only when accessible. "
        "Documentation text licensed under CC BY 4.0: "
        "https://creativecommons.org/licenses/by/4.0/ . "
        "Third-party materials may have separate terms. No images are reproduced.",
        small,
    )
    paragraph(
        "Text formatting: unsupported font glyphs are represented as [U+XXXX] to preserve their "
        "identity. Images are not reproduced. This report does not "
        "claim to capture every intermediate edit between scans.",
        small,
    )
    if not changes:
        paragraph("No new or updated documents found in this time window.", heading)
    for index, change in enumerate(changes, 1):
        start = len(story)
        story.append(Spacer(1, 4 * mm))
        story.append(HRFlowable(width="100%", color=colors.HexColor("#D7E1E5")))
        paragraph(f"{index}. {change.title}", heading)
        paragraph(f"Updated (UTC): {articles[change.url].modified}", small)
        paragraph(
            "Troubleshooting" if "/troubleshoot/" in change.url else "Official documentation",
            small,
        )
        story.append(
            Paragraph(
                f'<link href="{escape(change.url, {chr(34): "&quot;"})}" color="#126782">'
                f"{escape(change.url)}</link>",
                small,
            )
        )
        paragraph(summarize(change))
        if change.kind == "Historical source comparison":
            paragraph(f"Evidence: {change.evidence}", small)
        story[start:] = [KeepTogether(story[start:])]

    def footer(canvas: Canvas, document: SimpleDocTemplate) -> None:
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#D7E1E5"))
        canvas.line(18 * mm, 17 * mm, 192 * mm, 17 * mm)
        canvas.setFont(font, 8)
        canvas.drawString(18 * mm, 12 * mm, "Copilot Studio | Microsoft Learn update digest")
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
        title="Copilot Studio documentation updates",
        author="Copilot Studio documentation monitor",
    )
    document.build(story, onFirstPage=footer, onLaterPages=footer)
