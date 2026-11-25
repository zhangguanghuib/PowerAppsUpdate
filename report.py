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

from products import POWER_APPS, Product

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


def document_blocks(text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    headings: list[tuple[int, str]] = []
    lines: list[str] = []
    code_fence = ""

    def flush() -> None:
        value = "\n".join(lines) if code_fence else " ".join(lines)
        if value.strip():
            section = " > ".join(title for _, title in headings) or "Document body"
            blocks.append((section, f"Code:\n{value}" if code_fence else value))
        lines.clear()

    for raw in text.splitlines():
        fence = re.match(r"^\s*(`{3,}|~{3,})", raw)
        if code_fence:
            if fence and fence[1][0] == code_fence[0] and len(fence[1]) >= len(code_fence):
                flush()
                code_fence = ""
            else:
                lines.append(raw)
            continue
        if fence:
            flush()
            code_fence = fence[1]
            continue
        line = re.sub(r"^(?:>\s*)+", "", raw.strip())
        if not line:
            flush()
            continue
        note = re.match(r"^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(.*)", line, re.IGNORECASE)
        if note:
            line = f"{note[1].capitalize()}: {note[2]}".rstrip()
        elif line.startswith(("[!", ":::")):
            flush()
            continue
        line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)
        line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", line)
        line = re.sub(r"(\*\*|__|`)(.+?)\1", r"\2", line)
        line = re.sub(r"\s+", " ", line).strip()
        heading = re.match(r"^(#{1,6})\s+(.+?)(?:\s+#+)?$", line)
        if heading:
            flush()
            level, title = len(heading[1]), heading[2]
            while headings and headings[-1][0] >= level:
                headings.pop()
            section = " > ".join(title for _, title in headings) or "Document body"
            blocks.append((section, f"Heading: {title}"))
            headings.append((level, title))
        else:
            if re.match(r"^(?:[-*+]|\d+[.)])\s+|^\|", line):
                flush()
            lines.append(line)
            if line.startswith("|"):
                flush()
    flush()
    return blocks


def comparison_excerpt(text: str, other: str, *, limit: int = 320) -> str:
    if len(text) <= limit:
        return text
    position = next((
        start
        for kind, _, _, start, _ in SequenceMatcher(None, other, text, autojunk=False).get_opcodes()
        if kind != "equal"
    ), 0)
    start = max(0, position - limit // 3)
    if start:
        boundary = text.find(" ", start, position)
        if boundary >= 0:
            start = boundary + 1
    end = min(start + limit, len(text))
    if end < len(text):
        boundary = text.rfind(" ", max(start, position), end)
        if boundary > start:
            end = boundary
    return ("..." if start else "") + text[start:end].rstrip() + (
        "..." if end < len(text) else ""
    )


def summarize(change: Change) -> str:
    if change.kind != "Historical source comparison":
        lines = change.after.splitlines()
        if lines and lines[0].lstrip("# ").strip() == change.title:
            lines = lines[1:]
        overview = excerpt("\n".join(lines)) or excerpt(change.after)
        if change.kind == "New source document":
            return (
                "Document summary (extractive; new public source file; "
                "publication date unverified): "
                f"{overview or 'See the linked article.'}"
            )
        return (
            "Current article overview (not a change claim; history unavailable or disabled): "
            f"{overview or 'See the linked article.'}"
        )
    if change.before == change.after:
        return (
            "The modification timestamp is in range, but no public source-body changes were "
            "found. The update may be metadata-only or differ from public source publication."
        )
    old, new = document_blocks(change.before), document_blocks(change.after)
    blocks = [
        (kind, old[i:j], new[start:end])
        for kind, i, j, start, end in SequenceMatcher(
            None, [text for _, text in old], [text for _, text in new], autojunk=False
        ).get_opcodes()
        if kind != "equal"
    ]
    if not blocks:
        return (
            "No readable-text differences after normalizing paragraph wrapping and common "
            "inline Markdown formatting. Formatting or non-text source content may have changed; "
            "no product behavior change is inferred."
        )
    parts = ["Updated document - before / after (extractive)."]
    if len(blocks) > 3:
        parts.append(f"Showing 3 of {len(blocks)} changed passages; additional passages omitted.")
    labels = {"insert": "Added content", "delete": "Removed content", "replace": "Revised content"}
    for index, (kind, before_blocks, after_blocks) in enumerate(blocks[:3], 1):
        sections = list(dict.fromkeys(section for section, _ in before_blocks + after_blocks))
        before = "\n".join(text for _, text in before_blocks)
        after = "\n".join(text for _, text in after_blocks)
        parts.extend([
            f"{index}. {labels[kind]}",
            f"Section: {'; '.join(sections)}",
            "Before: " + (
                comparison_excerpt(before, after)
                if before else "No corresponding passage in the compared earlier source."
            ),
            "After: " + (
                comparison_excerpt(after, before)
                if after else "Passage removed from the compared current source."
            ),
        ])
    parts.append(
        "Paired source excerpts, not an interpretation of user impact or proof of a product "
        "behavior change; source changes may differ from the live page."
    )
    return "\n".join(parts)


def generate_pdf(
    changes: list[Change],
    destination: Path,
    *,
    now: datetime,
    since: str,
    articles: dict[str, Article],
    partial: bool = False,
    product: Product = POWER_APPS,
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
        lines = []
        for line in safe_text(text.expandtabs(4), font).split("\n"):
            indent = len(line) - len(line.lstrip(" "))
            lines.append("&#160;" * indent + escape(line[indent:]))
        story.append(Paragraph("<br/>".join(lines), style))

    paragraph(f"MICROSOFT {product.name.upper()}", styles["Title"])
    paragraph("Documentation update digest", styles["Heading1"])
    paragraph(f"Generated (UTC): {now.isoformat()}")
    paragraph(f"Observation window: {since} to {now.isoformat()}")
    paragraph(f"{len(changes)} new or updated document candidates")
    if partial:
        paragraph("PARTIAL SMOKE TEST - not a complete directory report", heading)
    story.append(Spacer(1, 6 * mm))
    paragraph(
        f"Scope: English Microsoft Learn {product.name} documentation and troubleshooting"
        f"{product.exclusion_note}. "
        "Documentation changes are not necessarily new product features. Modification timestamps "
        "are not feature release dates. No AI interpretation is used."
    )
    paragraph(
        "Every run independently selects articles using their published updated_at timestamp "
        "(sitemap lastmod when absent), within the inclusive UTC window above. "
        "Documents are grouped by public GitHub source history: newly created source files first, "
        "updated documents second, and unclassified documents last. A source-file addition "
        "does not prove a new website publication; repository imports or copies may look new. "
        "Unavailable history is not treated as proof of creation. "
        "Each updated document shows paired Before / After passages with section labels, using "
        "public source versions spanning the window start. Up to three changed passages are "
        "shown per document, with excerpts focused near the first differing text. "
        "New documents receive an extractive summary, not a Before / After comparison. "
        "No user-impact interpretation is inferred. If history is unavailable, an overview "
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
    ordered_changes = [
        change
        for category in ("Newly created", "Updated", "Unclassified")
        for change in changes
        if change.category == category
    ]
    previous_category = ""
    for index, change in enumerate(ordered_changes, 1):
        start = len(story)
        if change.category != previous_category:
            paragraph(f"{change.category} documents", styles["Heading1"])
            previous_category = change.category
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
        if change.kind in {"Historical source comparison", "New source document"}:
            paragraph(f"Evidence: {change.evidence}", small)
        story[start:] = [KeepTogether(story[start:])]

    def footer(canvas: Canvas, document: SimpleDocTemplate) -> None:
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#D7E1E5"))
        canvas.line(18 * mm, 17 * mm, 192 * mm, 17 * mm)
        canvas.setFont(font, 8)
        canvas.drawString(18 * mm, 12 * mm, f"{product.name} | Microsoft Learn update digest")
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
        title=f"{product.name} documentation updates",
        author=f"{product.name} documentation monitor",
    )
    document.build(story, onFirstPage=footer, onLaterPages=footer)
