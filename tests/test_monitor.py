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
from products import POWER_APPS, POWER_AUTOMATE, Product

URL = monitor.ROOTS[0] + "test-article"
NOW = datetime(2026, 11, 2, 1, tzinfo=UTC)
HTML = """
<html><head>
<meta name="updated_at" content="2026-10-25T01:00:00Z">
<meta name="original_content_git_url"
 content="https://github.com/MicrosoftDocs/powerapps-docs-pr/blob/live/powerapps-docs/a.md">
</head><body><main>
<div id="article-header">Share and edit this page</div>
<div class="content"><h1>Example article</h1></div>
<div id="article-metadata">Contributor count 99</div>
<div class="content"><p>Body explaining a detailed Power Apps feature.</p>
<a href="other">Related content</a><img src="media/example.png" alt="Example diagram">
<pre><code>if True:
    print("hello")
</code></pre>
<p class="nextstepaction">Next: publish your app</p>
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
    assert "Next: publish your app" in parsed.text
    assert monitor.source_location(parsed) == (
        "MicrosoftDocs/powerapps-docs",
        "powerapps-docs/a.md",
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
        "Body explaining a detailed Power Apps feature.",
        "Body explaining a <strong>detailed</strong> Power Apps\n feature.",
    )
    parsed = parse_article(URL, html, "")
    assert "Body explaining a detailed Power Apps feature." in parsed.text


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
        "https://learn.microsoft.com/en-us/power-apps-elsewhere/test",
        "https://learn.microsoft.com/zh-cn/power-apps/test",
        "https://learn.microsoft.com/en-us/troubleshoot/power-platform/power-apps-other/test",
    ],
)
def test_inventory_stays_in_scope(value: str) -> None:
    assert canonical_url(value, URL) is None


def test_canonicalization() -> None:
    assert canonical_url(URL + "?view=dataverse-latest#fragment", URL) == URL
    assert canonical_url(monitor.ROOTS[0], URL) == monitor.ROOTS[0].rstrip("/")


@pytest.mark.parametrize(
    "path",
    [
        "maker/model-driven-apps",
        "maker/model-driven-apps/create-app",
        "developer/model-driven-apps/clientapi/reference",
        "maker/data-platform/create-table",
        "developer/data-platform/webapi/overview",
        "teams/overview-data-platform",
        "teams/dataverse-for-teams-table-permissions",
        "maker/canvas-apps/connections/connection-common-data-service",
        "mobile/use-custom-model-driven-app-on-mobile",
        "maker/%64ata-platform/create-table",
    ],
)
def test_excluded_topic_urls(path: str) -> None:
    assert canonical_url(monitor.ROOTS[0] + path, URL) is None


@pytest.mark.parametrize(
    "url",
    [
        monitor.ROOTS[0] + "maker/canvas-apps/create-app",
        monitor.ROOTS[0] + "developer/code-apps/overview",
        monitor.ROOTS[0] + "developer/component-framework/overview",
        monitor.ROOTS[1] + "connections/troubleshoot-http-0-responses",
    ],
)
def test_relevant_power_apps_urls_remain_in_scope(url: str) -> None:
    assert canonical_url(url, URL) == url


@pytest.mark.parametrize(
    ("title", "subservice", "excluded"),
    [
        ("Sorting fails in a model-driven app", "", True),
        ("Create a table in Microsoft Dataverse", "", True),
        ("Use the Common Data Service", "", True),
        ("Table access troubleshooting", "dataverse-developer", True),
        ("Troubleshoot a grid", "model-driven-apps", True),
        ("Create a canvas app", "canvas-maker", False),
        ("Power Apps component framework overview", "pcf", False),
    ],
)
def test_fetch_filters_article_topics_not_incidental_body_mentions(
    monkeypatch: pytest.MonkeyPatch, title: str, subservice: str, excluded: bool
) -> None:
    html = HTML.replace("Example article", title).replace(
        "</head>", f'<meta name="ms.subservice" content="{subservice}"></head>'
    ).replace("Power Apps feature.", "Power Apps feature that can connect to Dataverse.")
    monkeypatch.setattr(monitor, "get", lambda url: Mock(url=url, text=html))
    result = monitor.fetch_article((URL, ""))
    assert (result is None) is excluded
    if result is not None:
        assert result.subservice == subservice


@pytest.mark.parametrize(
    ("target", "excluded"),
    [
        (monitor.ROOTS[0] + "maker/data-platform/overview", True),
        (monitor.ROOTS[1] + "model-driven-apps/test", True),
        ("https://example.com/dataverse/test", False),
        ("https://learn.microsoft.com/en-us/power-platform/dataverse/test", False),
    ],
)
def test_excluded_redirects_are_skipped_but_out_of_scope_redirects_fail(
    monkeypatch: pytest.MonkeyPatch, target: str, excluded: bool
) -> None:
    monkeypatch.setattr(monitor, "get", lambda url: Mock(url=target, text=HTML))
    if excluded:
        assert monitor.fetch_article((URL, "")) is None
    else:
        with pytest.raises(ValueError, match="outside monitored directories"):
            monitor.fetch_article((URL, ""))


def test_scan_omits_excluded_articles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monitor, "fetch_article", lambda item, **kwargs: None)
    history = Mock()
    monkeypatch.setattr(monitor, "historical_change", history)
    changes, articles = monitor.scan({URL: ""}, now=NOW)
    assert changes == []
    assert articles == {}
    history.assert_not_called()


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
    monkeypatch.setattr(monitor, "fetch_article", lambda item, **kwargs: articles[item[0]])
    changes, scanned = monitor.scan(
        dict.fromkeys(articles, ""), now=NOW, history=False, days=days
    )
    assert {change.url for change in changes} == {URL, URL + "/now"}
    assert changes[0].before == ""
    assert all(change.category == "Unclassified" for change in changes)
    assert "not a feature release date" in changes[0].evidence
    assert scanned == articles


def test_failed_fetch_does_not_produce_report(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monitor, "fetch_article", Mock(side_effect=requests.Timeout("offline")))
    with pytest.raises(requests.Timeout):
        monitor.scan({URL: ""}, now=NOW)


def test_unavailable_historical_source_labeled() -> None:
    change = monitor.historical_change(article("Current only"), NOW - timedelta(days=30))
    assert not change.before
    assert change.category == "Unclassified"
    assert "unavailable" in change.evidence


def test_source_metadata_only_changes_ignored() -> None:
    assert monitor.source_body("---\nms.date: old\n---\nBody\n<!-- note -->") == "Body"
    assert monitor.source_body("---\nms.date: new\n---\nBody") == "Body"


def test_historical_source_uses_cutoff_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    parsed = parse_article(URL, HTML, "")
    responses = [
        Mock(status_code=200, text="---\nms.date: old\n---\nOld source body"),
        Mock(status_code=200, text="---\nms.date: new\n---\nNew source body"),
    ]
    client = Mock()
    client.get.side_effect = responses
    monkeypatch.setattr(monitor, "session", lambda: client)
    monkeypatch.setattr(
        monitor, "source_history",
        Mock(side_effect=[
            Mock(json=lambda: [{"sha": "baseline-sha"}]),
            Mock(json=lambda: [{"sha": "current-sha"}]),
        ]),
    )
    change = monitor.historical_change(parsed, NOW - timedelta(days=30))
    assert change.before == "Old source body"
    assert change.after == "New source body"
    assert "baseline-sha" in change.evidence
    assert "current-sha" in change.evidence
    assert "NOT a verified historical website difference" in change.evidence
    assert change.category == "Updated"


@pytest.mark.parametrize(
    ("created", "status", "expected"),
    [
        (NOW - timedelta(days=7), "added", "Newly created"),
        (NOW, "added", "Newly created"),
        (NOW - timedelta(days=7, microseconds=1), "added", "Unclassified"),
        (NOW + timedelta(microseconds=1), "added", "Unclassified"),
        (NOW - timedelta(days=1), "renamed", "Unclassified"),
        (NOW - timedelta(days=1), "modified", "Unclassified"),
    ],
)
def test_new_source_requires_an_in_window_file_addition(
    monkeypatch: pytest.MonkeyPatch, created: datetime, status: str, expected: str
) -> None:
    parsed = parse_article(URL, HTML, "")
    history = Mock(side_effect=[
        Mock(json=lambda: []),
        Mock(
            links={},
            json=lambda: [{
                "sha": "first-sha",
                "commit": {"committer": {"date": created.isoformat()}},
            }],
        ),
        Mock(json=lambda: {"files": [{"filename": "powerapps-docs/a.md", "status": status}]}),
    ])
    monkeypatch.setattr(monitor, "source_history", history)
    change = monitor.historical_change(parsed, NOW - timedelta(days=7), until=NOW)
    assert change.category == expected
    if expected == "Newly created":
        assert change.kind == "New source document"
        assert "first-sha" in change.evidence
        assert "not its website publication date" in change.evidence
        assert change.after == parsed.text
    else:
        assert change.kind == "Historical candidate"
    baseline_url = history.call_args_list[0].args[0]
    assert "2026-10-26T00%3A59%3A59.999999Z" in baseline_url


def test_creation_checks_oldest_commit_and_paginated_commit_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed = parse_article(URL, HTML, "")
    oldest_url = "https://api.github.com/repos/MicrosoftDocs/powerapps-docs/commits?page=2"
    files_url = "https://api.github.com/repos/MicrosoftDocs/powerapps-docs/commits/first?page=2"
    history = Mock(side_effect=[
        Mock(json=lambda: []),
        Mock(json=lambda: [{"sha": "latest"}], links={"last": {"url": oldest_url}}),
        Mock(json=lambda: [{
            "sha": "first",
            "commit": {"committer": {"date": (NOW - timedelta(days=1)).isoformat()}},
        }]),
        Mock(
            json=lambda: {"files": [{"filename": "other.md", "status": "added"}]},
            links={"next": {"url": files_url}},
        ),
        Mock(json=lambda: {
            "files": [{"filename": "powerapps-docs/a.md", "status": "added"}],
        }),
    ])
    monkeypatch.setattr(monitor, "source_history", history)
    change = monitor.historical_change(parsed, NOW - timedelta(days=7), until=NOW)
    assert change.category == "Newly created"
    assert "/commit/first " in change.evidence
    assert history.call_args_list[2].args == (oldest_url,)
    assert history.call_args_list[4].args == (files_url,)


@pytest.mark.parametrize("status", [404, 409])
def test_inaccessible_source_history_is_unclassified(
    monkeypatch: pytest.MonkeyPatch, status: int, caplog: pytest.LogCaptureFixture
) -> None:
    response = requests.Response()
    response.status_code = status
    client = Mock()
    client.get.return_value = response
    monkeypatch.setattr(monitor, "session", lambda: client)
    change = monitor.historical_change(parse_article(URL, HTML, ""), NOW)
    assert change.category == "Unclassified"
    assert "No accessible public source history" in caplog.text


def test_missing_source_bodies_do_not_assert_a_verified_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        monitor, "source_history",
        Mock(side_effect=[
            Mock(json=lambda: [{"sha": "baseline"}]),
            Mock(json=lambda: [{"sha": "current"}]),
        ]),
    )
    client = Mock()
    client.get.return_value = Mock(status_code=404)
    monkeypatch.setattr(monitor, "session", lambda: client)
    change = monitor.historical_change(parse_article(URL, HTML, ""), NOW)
    assert change.category == "Unclassified"


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
    <sitemap><loc>https://learn.microsoft.com/_sitemaps/power-apps_en-us_1.xml</loc></sitemap>
    <sitemap><loc>https://learn.microsoft.com/_sitemaps/troubleshoot_en-us_1.xml</loc></sitemap>
    <sitemap><loc>https://learn.microsoft.com/_sitemaps/power-apps_zh-cn_1.xml</loc></sitemap>
    <sitemap><loc>https://learn.microsoft.com/_sitemaps/microsoft-copilot-studio_en-us_1.xml</loc></sitemap>
    </sitemapindex>"""
    urls = [
        URL,
        monitor.ROOTS[1] + "test",
        "https://learn.microsoft.com/en-us/windows/test",
        monitor.ROOTS[0] + "maker/model-driven-apps/test",
        monitor.ROOTS[0] + "developer/data-platform/test",
        monitor.ROOTS[1] + "dataverse/test",
    ]
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
    assert inventory == dict.fromkeys(urls[:2], "2026-11-01")
    assert monitor.ROOTS[1].rstrip("/") not in inventory


def test_date_parsing_assumes_utc() -> None:
    assert monitor.date_value("2026-11-02") == datetime(2026, 11, 2, tzinfo=UTC)
    assert monitor.date_value("2026-11-02T09:00:00+08:00") == NOW


@pytest.mark.parametrize("product", [POWER_APPS, POWER_AUTOMATE])
def test_repeated_runs_recompute_requested_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    product: Product,
) -> None:
    url = product.roots[0] + "test-article"
    discovery = Mock(return_value={url: ""})
    monkeypatch.setattr(monitor, "discover", discovery)
    monkeypatch.setattr(
        monitor, "fetch_article",
        lambda item, **kwargs: article(
            "After", url=url, modified=(datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        ),
    )
    output = tmp_path / "output"
    args = argparse.Namespace(
        days=7, output=output, workers=1, limit=None, no_history=True, product=product.slug,
    )
    monitor.run(args)
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["changed"] is True
    assert Path(manifest["pdf"]).is_file()
    assert manifest["days"] == 7
    assert manifest["scanned"] == 1
    assert not manifest["partial"]
    assert Path(manifest["pdf"]).name.startswith(f"{product.slug}-updates-")
    assert manifest["tag"].startswith(f"{product.slug}-docs-")
    assert manifest["product"] == product.slug
    discovery.assert_called_once_with(product=product)
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

    monkeypatch.setattr(monitor, "discover", lambda **kwargs: {URL: ""})
    monkeypatch.setattr(
        monitor, "fetch_article",
        lambda item, **kwargs: article(
            "After", modified=(datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        ),
    )
    monkeypatch.setattr(report, "generate_pdf", Mock(side_effect=OSError("disk full")))
    output = tmp_path / "output"
    with pytest.raises(OSError, match="disk full"):
        monitor.run(
            argparse.Namespace(
                days=7, output=output, workers=1, limit=None, no_history=True,
                product="power-apps",
            )
        )
    assert not (output / "manifest.json").exists()


@pytest.mark.parametrize("modified", ["", "invalid-date"])
def test_unusable_dates_fail_instead_of_skipping(
    monkeypatch: pytest.MonkeyPatch, modified: str
) -> None:
    monkeypatch.setattr(
        monitor, "fetch_article", lambda item, **kwargs: article(modified=modified)
    )
    with pytest.raises(ValueError):
        monitor.scan({URL: ""}, now=NOW, history=False)


@pytest.mark.parametrize("days", [0, -1])
def test_nonpositive_days_rejected(days: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        monitor.scan({}, now=NOW, days=days)


def test_run_generates_no_results_pdf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monitor, "discover", lambda **kwargs: {URL: ""})
    monkeypatch.setattr(
        monitor, "fetch_article", lambda item, **kwargs: article(modified="2000-01-01")
    )
    monitor.run(
        argparse.Namespace(
            days=7, output=tmp_path, workers=1, limit=None, no_history=True, product="power-apps",
        )
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
    assert run.call_args.args[0].product == "power-apps"


@pytest.mark.parametrize("value", ["power-apps", "power-automate"])
def test_cli_selects_product(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setattr("sys.argv", ["monitor.py", "--product", value])
    run = Mock()
    monkeypatch.setattr(monitor, "run", run)
    monitor.main()
    assert run.call_args.args[0].product == value


def test_cli_rejects_unknown_product(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["monitor.py", "--product", "unknown"])
    run = Mock()
    monkeypatch.setattr(monitor, "run", run)
    with pytest.raises(SystemExit) as error:
        monitor.main()
    assert error.value.code == 2
    run.assert_not_called()


@pytest.mark.parametrize(
    "path",
    ["getting-started", "desktop-flows/run-desktop-flows", "dataverse/create-update-trigger"],
)
def test_power_automate_scope_does_not_inherit_apps_exclusions(path: str) -> None:
    url = POWER_AUTOMATE.roots[0] + path
    assert canonical_url(url, url, product=POWER_AUTOMATE) == url
    assert canonical_url(url, url) is None


@pytest.mark.parametrize(
    "url",
    [
        POWER_APPS.roots[0] + "maker/canvas-apps/test",
        POWER_APPS.roots[1] + "test",
        "https://learn.microsoft.com/en-us/power-automate-other/test",
        "https://learn.microsoft.com/zh-cn/power-automate/test",
    ],
)
def test_power_automate_rejects_other_product_and_locale_urls(url: str) -> None:
    assert canonical_url(url, url, product=POWER_AUTOMATE) is None


def test_power_automate_discovery_uses_its_own_sitemap_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = """<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <sitemap><loc>https://learn.microsoft.com/_sitemaps/power-apps_en-us_1.xml</loc></sitemap>
    <sitemap><loc>https://learn.microsoft.com/_sitemaps/power-automate_en-us_1.xml</loc></sitemap>
    <sitemap><loc>https://learn.microsoft.com/_sitemaps/troubleshoot_en-us_1.xml</loc></sitemap>
    </sitemapindex>"""
    included = [
        POWER_AUTOMATE.roots[0] + "dataverse/create-update-trigger",
        POWER_AUTOMATE.roots[0] + "desktop-flows/run-desktop-flows",
        POWER_AUTOMATE.roots[1] + "flow-run-issues/triggers-troubleshoot",
    ]
    sitemap = (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(
            f"<url><loc>{url}</loc><lastmod>2026-11-01</lastmod></url>"
            for url in [*included, URL, POWER_APPS.roots[1] + "test"]
        )
        + "</urlset>"
    )
    get = Mock(side_effect=[
        Mock(content=index.encode()),
        Mock(content=sitemap.encode()),
        Mock(content=sitemap.encode()),
    ])
    monkeypatch.setattr(monitor, "get", get)
    inventory = monitor.discover(product=POWER_AUTOMATE)
    assert inventory == dict.fromkeys(included, "2026-11-01")
    assert len(get.call_args_list) == 3
    assert all("/power-apps_" not in call.args[0] for call in get.call_args_list)


def test_power_automate_scan_fetches_its_product_and_source_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = POWER_AUTOMATE.roots[0] + "dataverse/create-update-trigger"
    html = HTML.replace("Example article", "Use Dataverse with Power Automate").replace(
        "powerapps-docs-pr/blob/live/powerapps-docs/a.md",
        "power-automate-docs-pr/blob/live/articles/dataverse/create-update-trigger.md",
    ).replace("2026-10-25T01:00:00Z", NOW.isoformat())
    get = Mock(return_value=Mock(url=url, text=html))
    monkeypatch.setattr(monitor, "get", get)
    changes, articles = monitor.scan({url: ""}, now=NOW, history=False, product=POWER_AUTOMATE)
    assert len(changes) == 1
    assert changes[0].url == url
    assert changes[0].title == "Use Dataverse with Power Automate"
    assert monitor.source_location(articles[url]) == (
        "MicrosoftDocs/power-automate-docs", "articles/dataverse/create-update-trigger.md",
    )
    get.assert_called_once_with(url)
