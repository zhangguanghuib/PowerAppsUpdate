from datetime import UTC, datetime
from pathlib import Path

from pypdf import PdfReader

from monitor import Article, Change
from report import changed_blocks, excerpt, generate_pdf, summarize

URL = "https://learn.microsoft.com/en-us/microsoft-copilot-studio/test"


def test_full_diff_no_truncation() -> None:
    assert changed_blocks("Same\nOld value\nSame ending", "Same\nNew value\nSame ending") == [
        ("replace", "Old value", "New value")
    ]


def test_summary_uses_changed_text_not_unchanged_intro() -> None:
    change = Change(
        "Example", URL, "Historical source comparison",
        "Unchanged introduction\nOld setting", "Unchanged introduction\nNew setting", "Evidence",
    )
    summary = summarize(change)
    assert "New setting" in summary
    assert "Old setting" in summary
    assert "Unchanged introduction" not in summary
    assert "1 changed block" in summary
    assert "may differ" in summary


def test_missing_history_summary_is_not_a_change_claim() -> None:
    change = Change(
        "Example", URL, "Historical candidate", "", "Example\nConfigure agents with tools.",
        "Historical published body unavailable.",
    )
    summary = summarize(change)
    assert "history unavailable or disabled" in summary
    assert "not a change claim" in summary
    assert "Configure agents with tools." in summary


def test_metadata_only_summary() -> None:
    change = Change("Example", URL, "Historical source comparison", "Same", "Same", "Evidence")
    assert "no public source-body changes" in summarize(change)


def test_excerpts_bounded_and_markdown_links_cleaned() -> None:
    assert excerpt("[Tools](https://example.com) are available.") == "Tools are available."
    assert excerpt("Tools (https://example.com) are available.") == "Tools are available."
    assert excerpt(
        "Note\nThis article describes features used in agents or agent flows powered by a harness."
        "\nConfigure billing for agents."
    ) == "Configure billing for agents."
    assert len(excerpt("Long prose " * 1000)) <= 323
    assert excerpt("```python\nsecret = 42\n```\nUseful prose") == "Useful prose"


def test_pdf_is_concise_with_urls_summaries_and_pagination(tmp_path: Path) -> None:
    changes = [
        Change(
            f"Feature & <example> {index}", f"{URL}/{index}", "Historical source comparison",
            "Old documentation",
            "New setting enabled.\n" + "\n".join(f"Detail {i}" for i in range(300)),
            "Public source history, not verified historical website differences.",
        )
        for index in range(18)
    ]
    articles = {
        change.url: Article(change.url, change.title, change.after, "2026-11-08T00:00:00Z", "")
        for change in changes
    }
    destination = tmp_path / "test.pdf"
    generate_pdf(
        changes, destination, now=datetime(2026, 11, 10, tzinfo=UTC),
        since="2026-11-03T00:00:00+00:00", articles=articles,
    )
    pdf = PdfReader(destination)
    text = "\n".join(page.extract_text() for page in pdf.pages)
    normalized_text = " ".join(text.split())
    assert 2 < len(pdf.pages) < 18
    for value in [
        "Old documentation", "New setting enabled.", "CC BY 4.0", "MICROSOFT COPILOT STUDIO",
        "not necessarily new product features", "2026-11-03", "2026-11-08", URL + "/17",
    ]:
        assert value in normalized_text
    assert "Detail 299" not in text
    assert all(f"Page {index}" in page.extract_text() for index, page in enumerate(pdf.pages, 1))
    assert sum(len(page.get("/Annots", [])) for page in pdf.pages) == len(changes)


def test_empty_pdf_and_partial_warning(tmp_path: Path) -> None:
    destination = tmp_path / "empty.pdf"
    generate_pdf(
        [], destination, now=datetime(2026, 11, 10, tzinfo=UTC), since="2026-11-03",
        articles={}, partial=True,
    )
    text = PdfReader(destination).pages[0].extract_text()
    assert "No new or updated documents found" in text
    assert "PARTIAL SMOKE TEST" in text
