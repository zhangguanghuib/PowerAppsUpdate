from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

import monitor
from monitor import Article, canonical_url, parse_article

URL = monitor.ROOTS[0] + "test-article"
NOW = datetime(2026, 11, 2, 1, tzinfo=UTC)
HTML = """
<html><head>
<meta name="updated_at" content="2026-10-25T01:00:00Z">
<meta name="original_content_git_url"
 content="https://github.com/MicrosoftDocs/businessapps-copilot-docs-pr/blob/live/copilot-studio/a.md">
</head><body><main>
<div id="article-header">Share and edit this page</div>
<div class="content"><h1>Example article</h1></div>
<div id="article-metadata">Contributor count 99</div>
<div class="content"><p>Body explaining a detailed Copilot Studio feature.</p>
<a href="other">Related content</a><img src="media/example.png" alt="Example diagram">
<pre><code>if True:
    print("hello")
</code></pre>
<p class="nextstepaction">Next: publish your agent</p>
</div><footer class="content-footer">Feedback changes daily</footer>
</main></body></html>
"""


def article(text: str = "Original body", url: str = URL, modified: str = "") -> Article:
    return Article(url, "Example article", text, modified, "")


def test_actual_learn_sibling_content_containers() -> None:
    parsed = parse_article(URL, HTML, "")
    assert parsed.title == "Example article"
    assert "Body explaining" in parsed.text
    assert "Contributor" not in parsed.text
    assert "Share and edit" not in parsed.text
    assert "Feedback" not in parsed.text
    assert monitor.ROOTS[0] + "other" in parsed.text
    assert "media/example.png" in parsed.text
    assert '    print("hello")' in parsed.text
    assert "Next: publish your agent" in parsed.text
    assert monitor.source_location(parsed) == (
        "MicrosoftDocs/businessapps-copilot-docs",
        "copilot-studio/a.md",
    )


@pytest.mark.parametrize(
    ("metadata", "expected_title"),
    [
        ('<meta property="og:title" content="Media guidance">', "Media guidance"),
        ("<title>Media guidance | Microsoft Learn</title>", "Media guidance"),
        ("<title> | Microsoft Learn</title>", "readme"),
    ],
)
def test_headingless_published_page_keeps_body_and_logs_title_fallback(
    metadata: str,
    expected_title: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    url = monitor.ROOTS[0] + "media/shared/readme"
    html = (
        f"<html><head>{metadata}</head><body><main>"
        '<div class="content"><p>This folder contains media files that are used '
        "in include files across product documentation articles.</p></div>"
        "</main></body></html>"
    )
    parsed = parse_article(url, html, "2026-10-25")
    assert parsed.title == expected_title
    assert "This folder contains media files" in parsed.text
    assert parsed.modified == "2026-10-25"
    assert url in caplog.text
    assert "heading" in caplog.text


@pytest.mark.parametrize(
    "body",
    [
        "<div>No main article container.</div>",
        '<main><div class="content"><p>Empty</p></div></main>',
    ],
)
def test_missing_heading_does_not_hide_missing_or_empty_body(body: str) -> None:
    with pytest.raises(ValueError):
        parse_article(URL, f"<html><head><title>Fallback</title></head>{body}</html>", "")


def test_code_indentation_change_is_observed() -> None:
    before = parse_article(URL, HTML, "")
    after = parse_article(URL, HTML.replace("    print", "        print"), "")
    assert before.text != after.text


def test_inline_markup_does_not_split_paragraphs() -> None:
    html = HTML.replace(
        "Body explaining a detailed Copilot Studio feature.",
        "Body explaining a <strong>detailed</strong> Copilot Studio\n feature.",
    )
    parsed = parse_article(URL, html, "")
    assert "Body explaining a detailed Copilot Studio feature." in parsed.text


def test_utf8_is_not_decoded_as_latin1(monkeypatch: pytest.MonkeyPatch) -> None:
    response = requests.Response()
    response.status_code = 200
    response._content = "Feature \u2014 expanded".encode()
    response.encoding = "iso-8859-1"
    client = Mock()
    client.get.return_value = response
    monkeypatch.setattr(monitor, "session", lambda: client)
    assert monitor.get(URL).text == "Feature \u2014 expanded"


def test_template_metadata_and_timestamp_do_not_change_article_text() -> None:
    before = parse_article(URL, HTML, "")
    after = parse_article(URL, HTML.replace("count 99", "count 100").replace("10-25", "10-26"), "")
    assert before.text == after.text
    assert before.title == after.title
    assert before.modified != after.modified


@pytest.mark.parametrize(
    "value",
    [
        "https://evil.example/en-us/microsoft-copilot-studio/test",
        "https://learn.microsoft.com/en-us/copilot/test",
        "https://learn.microsoft.com/en-us/power-platform/test",
        "https://learn.microsoft.com/en-us/microsoft-copilot-studio-elsewhere/test",
        "https://learn.microsoft.com/zh-cn/microsoft-copilot-studio/test",
        "https://learn.microsoft.com/en-us/troubleshoot/power-platform/copilot-studio-other/test",
    ],
)
def test_inventory_stays_in_scope(value: str) -> None:
    assert canonical_url(value, URL) is None


def test_canonicalization() -> None:
    assert canonical_url(URL + "?view=dataverse-latest#fragment", URL) == URL
    assert canonical_url(monitor.ROOTS[0], URL) == monitor.ROOTS[0].rstrip("/")


@pytest.mark.parametrize("days", [1, 7, 30, 365])
def test_window_boundary_and_no_fake_history(
    monkeypatch: pytest.MonkeyPatch, days: int
) -> None:
    articles = {
        URL: article("Current article", modified=(NOW - timedelta(days=days)).isoformat()),
        URL + "/old": article(
            url=URL + "/old", modified=(NOW - timedelta(days=days, microseconds=1)).isoformat()
        ),
        URL + "/now": article(url=URL + "/now", modified=NOW.isoformat()),
        URL + "/future": article(
            url=URL + "/future", modified=(NOW + timedelta(days=1)).isoformat()
        ),
    }
    monkeypatch.setattr(monitor, "fetch_article", lambda item: articles[item[0]])
    changes, scanned = monitor.scan(
        dict.fromkeys(articles, ""), now=NOW, history=False, days=days
    )
    assert {change.url for change in changes} == {URL, URL + "/now"}
    assert changes[0].before == ""
    assert "not a feature release date" in changes[0].evidence
    assert scanned == articles


def test_failed_fetch_does_not_produce_report(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monitor, "fetch_article", Mock(side_effect=requests.Timeout("offline")))
    with pytest.raises(requests.Timeout):
        monitor.scan({URL: ""}, now=NOW)


def test_unavailable_historical_source_labeled() -> None:
    change = monitor.historical_change(article("Current only"), NOW - timedelta(days=30))
    assert not change.before
    assert "unavailable" in change.evidence


def test_source_metadata_only_changes_ignored() -> None:
    assert monitor.source_body("---\nms.date: old\n---\nBody\n<!-- note -->") == "Body"
    assert monitor.source_body("---\nms.date: new\n---\nBody") == "Body"


def test_historical_source_uses_cutoff_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    parsed = parse_article(URL, HTML, "")
    responses = [
        Mock(status_code=200, json=lambda: [{"sha": "baseline-sha"}]),
        Mock(status_code=200, text="---\nms.date: old\n---\nOld source body"),
        Mock(status_code=200, text="---\nms.date: new\n---\nNew source body"),
    ]
    client = Mock()
    client.get.side_effect = responses
    monkeypatch.setattr(monitor, "session", lambda: client)
    monkeypatch.setattr(
        monitor, "get", lambda *args, **kwargs: Mock(json=lambda: [{"sha": "current-sha"}])
    )
    change = monitor.historical_change(parsed, NOW - timedelta(days=30))
    assert change.before == "Old source body"
    assert change.after == "New source body"
    assert "baseline-sha" in change.evidence
    assert "current-sha" in change.evidence
    assert "NOT a verified historical website difference" in change.evidence


def test_historical_rate_limit_not_silently_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Mock()
    response = Mock(status_code=403)
    response.raise_for_status.side_effect = requests.HTTPError("rate limited")
    client.get.return_value = response
    monkeypatch.setattr(monitor, "session", lambda: client)
    with pytest.raises(requests.HTTPError, match="rate limited"):
        monitor.historical_change(parse_article(URL, HTML, ""), NOW)


def test_discovery_uses_both_sitemap_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    index = """<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <sitemap><loc>https://learn.microsoft.com/_sitemaps/microsoft-copilot-studio_en-us_1.xml</loc></sitemap>
    <sitemap><loc>https://learn.microsoft.com/_sitemaps/troubleshoot_en-us_1.xml</loc></sitemap>
    <sitemap><loc>https://learn.microsoft.com/_sitemaps/microsoft-copilot-studio_zh-cn_1.xml</loc></sitemap>
    </sitemapindex>"""
    urls = [URL, monitor.ROOTS[1] + "test", "https://learn.microsoft.com/en-us/windows/test"]
    sitemap = (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<url><loc>{url}</loc><lastmod>2026-11-01</lastmod></url>" for url in urls)
        + "</urlset>"
    )
    calls: list[str] = []

    def fake_get(url: str) -> Mock:
        calls.append(url)
        return Mock(content=(index if url == monitor.SITEMAP_INDEX else sitemap).encode())

    monkeypatch.setattr(monitor, "get", fake_get)
    inventory = monitor.discover()
    assert len(calls) == 3
    assert urls[0] in inventory
    assert urls[1] in inventory
    assert urls[2] not in inventory
    assert monitor.ROOTS[1].rstrip("/") not in inventory


def test_date_parsing_assumes_utc() -> None:
    assert monitor.date_value("2026-11-02") == datetime(2026, 11, 2, tzinfo=UTC)
    assert monitor.date_value("2026-11-02T09:00:00+08:00") == NOW


def test_repeated_runs_recompute_requested_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(monitor, "discover", lambda: {URL: ""})
    monkeypatch.setattr(
        monitor, "fetch_article",
        lambda item: article(
            "After", modified=(datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        ),
    )
    output = tmp_path / "output"
    args = argparse.Namespace(days=7, output=output, workers=1, limit=None, no_history=True)
    monitor.run(args)
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["changed"] is True
    assert Path(manifest["pdf"]).is_file()
    assert manifest["days"] == 7
    assert manifest["scanned"] == 1
    assert not manifest["partial"]
    args.output = tmp_path / "second"
    monitor.run(args)
    second_manifest = json.loads((args.output / "manifest.json").read_text())
    assert second_manifest["changed"] is True
    assert second_manifest["count"] == 1
    assert len(list(args.output.glob("*.pdf"))) == 1


def test_pdf_failure_does_not_write_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import report

    monkeypatch.setattr(monitor, "discover", lambda: {URL: ""})
    monkeypatch.setattr(
        monitor, "fetch_article",
        lambda item: article(
            "After", modified=(datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        ),
    )
    monkeypatch.setattr(report, "generate_pdf", Mock(side_effect=OSError("disk full")))
    output = tmp_path / "output"
    with pytest.raises(OSError, match="disk full"):
        monitor.run(
            argparse.Namespace(days=7, output=output, workers=1, limit=None, no_history=True)
        )
    assert not (output / "manifest.json").exists()


@pytest.mark.parametrize("modified", ["", "invalid-date"])
def test_unusable_dates_fail_instead_of_skipping(
    monkeypatch: pytest.MonkeyPatch, modified: str
) -> None:
    monkeypatch.setattr(monitor, "fetch_article", lambda item: article(modified=modified))
    with pytest.raises(ValueError):
        monitor.scan({URL: ""}, now=NOW, history=False)


@pytest.mark.parametrize("days", [0, -1])
def test_nonpositive_days_rejected(days: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        monitor.scan({}, now=NOW, days=days)


def test_run_generates_no_results_pdf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monitor, "discover", lambda: {URL: ""})
    monkeypatch.setattr(monitor, "fetch_article", lambda item: article(modified="2000-01-01"))
    monitor.run(
        argparse.Namespace(days=7, output=tmp_path, workers=1, limit=None, no_history=True)
    )
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["count"] == 0
    assert manifest["changed"] is False
    assert Path(manifest["pdf"]).is_file()


@pytest.mark.parametrize("value", ["0", "-1", "abc", "1.5"])
def test_cli_rejects_invalid_day_input(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setattr("sys.argv", ["monitor.py", "--days", value])
    run = Mock()
    monkeypatch.setattr(monitor, "run", run)
    with pytest.raises(SystemExit) as error:
        monitor.main()
    assert error.value.code == 2
    run.assert_not_called()


@pytest.mark.parametrize("value", [None, "14", "365"])
def test_cli_accepts_default_and_custom_days(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    monkeypatch.setattr(
        "sys.argv", ["monitor.py"] + (["--days", value] if value is not None else [])
    )
    run = Mock()
    monkeypatch.setattr(monitor, "run", run)
    monitor.main()
    assert run.call_args.args[0].days == (int(value) if value is not None else 7)
