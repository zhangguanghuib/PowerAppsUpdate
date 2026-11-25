from datetime import UTC, datetime
from pathlib import Path

import pytest
from pypdf import PdfReader

from monitor import Article, Change
from products import POWER_APPS, POWER_AUTOMATE, Product
from report import changed_blocks, excerpt, generate_pdf, summarize

URL = "https://learn.microsoft.com/en-us/power-apps/test"


def test_full_diff_no_truncation() -> None:
    assert changed_blocks("Same\nOld value\nSame ending", "Same\nNew value\nSame ending") == [
        ("replace", "Old value", "New value")
    ]


def test_summary_uses_changed_text_not_unchanged_intro() -> None:
    change = Change(
        "Example", URL, "Historical source comparison",
        "# Example\n\nUnchanged introduction\n\n## Settings\n\nOld setting",
        "# Example\n\nUnchanged introduction\n\n## Settings\n\nNew setting", "Evidence",
    )
    summary = summarize(change)
    assert "Section: Example > Settings" in summary
    assert "Before: Old setting" in summary
    assert "After: New setting" in summary
    assert "Unchanged introduction" not in summary
    assert "may differ" in summary


def test_summary_keeps_each_before_after_pair_together() -> None:
    change = Change(
        "Example", URL, "Historical source comparison",
        "## Timeout\n\nWait 30 seconds.\n\n## Access\n\nUse an administrator account.",
        "## Timeout\n\nWait 60 seconds.\n\n## Access\n\nUse a standard user account.",
        "Evidence", category="Updated",
    )
    summary = summarize(change)
    positions = [
        summary.index(value) for value in [
            "Section: Timeout", "Before: Wait 30 seconds.", "After: Wait 60 seconds.",
            "Section: Access", "Before: Use an administrator account.",
            "After: Use a standard user account.",
        ]
    ]
    assert positions == sorted(positions)


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (
            "## Setup\n\nInstall the console.",
            "## Setup\n\nInstall the console.\n\nEnable confirmation prompts.",
            ["Added content", "Before: No corresponding passage", "After: Enable confirmation"],
        ),
        (
            "## Setup\n\nInstall the console.\n\nEnable confirmation prompts.",
            "## Setup\n\nInstall the console.",
            ["Removed content", "Before: Enable confirmation", "After: Passage removed"],
        ),
    ],
)
def test_summary_distinguishes_added_and_removed_passages(
    before: str, after: str, expected: list[str]
) -> None:
    summary = summarize(
        Change("Example", URL, "Historical source comparison", before, after, "Evidence")
    )
    assert all(value in summary for value in expected)
    assert "feature was unavailable" not in summary


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (
            "# Example\n\nRun **desktop flows** using a URL\nor a desktop shortcut.",
            "# Example\n\nRun desktop flows using a URL or a desktop shortcut.",
        ),
        (
            "## Execution\n\n> [!Note] Only one flow can run at a time.",
            "## Execution\n\n>[!NOTE] Only one flow can run at a time.",
        ),
    ],
)
def test_summary_ignores_soft_wrapping_and_inline_formatting_changes(
    before: str, after: str
) -> None:
    summary = summarize(Change(
        "Example", URL, "Historical source comparison", before, after, "Evidence",
    ))
    assert "No readable-text differences" in summary
    assert "Before:" not in summary


def test_summary_preserves_changed_admonition_guidance() -> None:
    summary = summarize(Change(
        "Example", URL, "Historical source comparison",
        "> [!Note] Only one flow can run at a time.",
        ">[!NOTE] Only two flows can run at a time.", "Evidence",
    ))
    assert "Before: Note: Only one flow" in summary
    assert "After: Note: Only two flows" in summary


def test_summary_focuses_on_changes_beyond_the_start_of_a_long_paragraph() -> None:
    common = "Shared background guidance. " * 35
    summary = summarize(Change(
        "Example", URL, "Historical source comparison",
        common + "Set the timeout to 30 seconds.",
        common + "Set the timeout to 60 seconds.", "Evidence",
    ))
    assert "30 seconds" in summary
    assert "60 seconds" in summary
    assert common not in summary
    assert len(summary) < 1400


@pytest.mark.parametrize(
    ("before", "after", "old_value", "new_value"),
    [
        (
            "```python\nif enabled:\n    run()\n```",
            "```python\nif enabled:\nrun()\n```",
            "    run()", "\nrun()",
        ),
        (
            "| Setting | Value |\n| --- | --- |\n| Timeout | 30 seconds |",
            "| Setting | Value |\n| --- | --- |\n| Timeout | 60 seconds |",
            "30 seconds", "60 seconds",
        ),
        (
            "Use [the endpoint](https://old.example/api).",
            "Use [the endpoint](https://new.example/api).",
            "https://old.example/api", "https://new.example/api",
        ),
    ],
)
def test_summary_preserves_code_table_and_link_target_changes(
    before: str, after: str, old_value: str, new_value: str
) -> None:
    summary = summarize(
        Change("Example", URL, "Historical source comparison", before, after, "Evidence")
    )
    old, new = summary.split("Before:", 1)[1].split("After:", 1)
    assert old_value in old
    assert new_value in new


def test_summary_explicitly_bounds_representative_passages() -> None:
    before = "\n\n".join(f"## Section {i}\n\nOld setting {i}." for i in range(4))
    after = before.replace("Old setting", "New setting")
    summary = summarize(
        Change("Example", URL, "Historical source comparison", before, after, "Evidence")
    )
    assert summary.count("Before:") == summary.count("After:") == 3
    assert "Showing 3 of 4" in summary
    assert "New setting 3" not in summary


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


def test_new_document_summary_does_not_claim_missing_history_or_feature_release() -> None:
    change = Change(
        "Example", URL, "New source document", "", "Example\nConfigure a canvas app.",
        "First source addition.", category="Newly created",
    )
    summary = summarize(change)
    assert "Document summary" in summary
    assert "new public source file; publication date unverified" in summary
    assert "Configure a canvas app." in summary
    assert "history unavailable" not in summary
    assert "Before:" not in summary
    assert "After:" not in summary


@pytest.mark.parametrize("product", [POWER_APPS, POWER_AUTOMATE])
def test_pdf_groups_new_updated_and_unclassified_documents(
    tmp_path: Path, product: Product
) -> None:
    url = product.roots[0] + "test"
    changes = [
        Change("Unknown article", url + "/unknown", "Historical candidate", "", "Body", ""),
        Change(
            "Existing article", url + "/updated", "Historical source comparison",
            "Old", "New", "Comparison evidence.", category="Updated",
        ),
        Change(
            "Recent new article", url + "/newer", "New source document", "", "Overview",
            "First source addition evidence.", category="Newly created",
        ),
        Change(
            "Earlier new article", url + "/older", "New source document", "", "Overview",
            "Another addition.", category="Newly created",
        ),
    ]
    articles = {
        change.url: Article(change.url, change.title, change.after, "2026-11-08T00:00:00Z", "")
        for change in changes
    }
    destination = tmp_path / "grouped.pdf"
    generate_pdf(
        changes, destination, now=datetime(2026, 11, 10, tzinfo=UTC),
        since="2026-11-03T00:00:00+00:00", articles=articles, product=product,
    )
    pdf = PdfReader(destination)
    text = " ".join(" ".join(page.extract_text() for page in pdf.pages).split())
    assert f"MICROSOFT {product.name.upper()}" in text
    assert pdf.metadata is not None
    assert pdf.metadata.title == f"{product.name} documentation updates"
    if product == POWER_AUTOMATE:
        assert "excluding model-driven apps and Dataverse topics" not in text
        assert "Power Apps" not in text
    expected_order = [
        "Newly created documents", "1. Recent new article", "2. Earlier new article",
        "Updated documents", "3. Existing article",
        "Unclassified documents", "4. Unknown article",
    ]
    positions = [text.index(value) for value in expected_order]
    assert positions == sorted(positions)
    assert "First source addition evidence." in text
    assert "Comparison evidence." in text
    assert sum(len(page.get("/Annots", [])) for page in pdf.pages) == len(changes)
    for section, title in [
        ("Newly created documents", "Recent new article"),
        ("Updated documents", "Existing article"),
        ("Unclassified documents", "Unknown article"),
    ]:
        assert any(
            section in page.extract_text() and title in page.extract_text()
            for page in pdf.pages
        )


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
        "Old documentation", "New setting enabled.", "CC BY 4.0", "MICROSOFT POWER APPS",
        "excluding model-driven apps and Dataverse topics",
        "not necessarily new product features", "2026-11-03", "2026-11-08", URL + "/17",
        "Before:", "After:",
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


def test_pdf_preserves_indentation_in_paired_code_passages(tmp_path: Path) -> None:
    change = Change(
        "Example", URL, "Historical source comparison",
        "## Script\n\n```python\nif enabled:\n    run()\n```",
        "## Script\n\n```python\nif enabled:\nrun()\n```",
        "Source comparison evidence.", category="Updated",
    )
    destination = tmp_path / "code-comparison.pdf"
    generate_pdf(
        [change], destination, now=datetime(2026, 11, 25, tzinfo=UTC),
        since="2026-11-18", articles={
            URL: Article(URL, change.title, change.after, "2026-11-24T00:00:00Z", ""),
        },
    )
    text = "\n".join(page.extract_text() for page in PdfReader(destination).pages)
    before, after = text.split("Before:", 1)[1].split("After:", 1)
    assert "Section: Script" in text
    assert "    run()" in before
    assert "\nrun()" in after
