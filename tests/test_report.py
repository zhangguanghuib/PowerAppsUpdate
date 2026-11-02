from datetime import UTC, datetime
from pathlib import Path

from pypdf import PdfReader

from monitor import Article, Change
from report import changed_blocks, generate_pdf


def test_full_diff_no_truncation() -> None:
    old = "Same\nOld value\nSame ending"
    new = "Same\nNew value\nSame ending"
    assert changed_blocks(old, new) == [("replace", "Old value", "New value")]


def test_pdf_long_content_sources_attribution_and_pagination(tmp_path: Path) -> None:
    url = "https://learn.microsoft.com/en-us/power-apps/test"
    after = (
        "\n".join(
            f"Line {index}: detailed documentation <tag> & a long sample value."
            for index in range(300)
        )
        + "\nEND_OF_COMPLETE_CONTENT"
    )
    changes = [
        Change(
            "Feature & <example>",
            url,
            "Published body changed",
            "Old documentation",
            after,
            "Compared saved published bodies.",
        ),
        Change(
            "Historical article",
            url,
            "Historical source comparison",
            "Old source",
            "New source",
            "Source history, not published history.",
        ),
    ]
    destination = tmp_path / "test.pdf"
    generate_pdf(
        changes,
        destination,
        now=datetime(2026, 11, 2, tzinfo=UTC),
        since="2026-10-03",
        articles={url: Article(url, "Title", "Current published body", "", "")},
        initial=True,
    )
    pdf = PdfReader(destination)
    text = "\n".join(page.extract_text() for page in pdf.pages)
    assert len(pdf.pages) > 4
    for value in [
        "Old documentation",
        "Line 299",
        "END_OF_COMPLETE_CONTENT",
        "CC BY 4.0",
        "not necessarily new product features",
        "Current published body",
        url,
    ]:
        assert value in text
    assert all(f"Page {index}" in page.extract_text() for index, page in enumerate(pdf.pages, 1))
    assert any("/Annots" in page for page in pdf.pages)
