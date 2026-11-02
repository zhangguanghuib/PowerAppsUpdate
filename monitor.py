from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import os
import re
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, Comment
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOTS = (
    "https://learn.microsoft.com/en-us/power-apps/",
    "https://learn.microsoft.com/en-us/troubleshoot/power-platform/power-apps/",
)
SITEMAP_INDEX = "https://learn.microsoft.com/_sitemaps/sitemapindex.xml"
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
LOG = logging.getLogger(__name__)
_LOCAL = threading.local()


@dataclass(frozen=True)
class Article:
    url: str
    title: str
    text: str
    modified: str
    source_path: str


@dataclass(frozen=True)
class Change:
    title: str
    url: str
    kind: str
    before: str
    after: str
    evidence: str


@dataclass
class Snapshot:
    checked_at: str
    articles: dict[str, Article]
    missing: dict[str, int]


def session() -> requests.Session:
    if not hasattr(_LOCAL, "session"):
        client = requests.Session()
        client.headers["User-Agent"] = "PowerAppsDocsMonitor/0.1 (daily documentation checks)"
        retry = Retry(
            total=4,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            respect_retry_after_header=True,
        )
        client.mount("https://", HTTPAdapter(max_retries=retry))
        _LOCAL.session = client
    return _LOCAL.session


def get(url: str, *, github: bool = False) -> requests.Response:
    headers = {"Accept": "application/vnd.github+json"} if github else {}
    if github and os.environ.get("GH_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GH_TOKEN']}"
    response = session().get(url, headers=headers, timeout=(15, 90))
    response.raise_for_status()
    response.encoding = "utf-8"
    return response


def canonical_url(value: str, base: str) -> str | None:
    parsed = urlsplit(urljoin(base, value))
    if parsed.scheme != "https" or parsed.netloc.lower() != "learn.microsoft.com":
        return None
    url = urlunsplit(("https", "learn.microsoft.com", parsed.path.rstrip("/"), "", ""))
    if any(url == root.rstrip("/") or url.startswith(root) for root in ROOTS):
        return url
    return None


def discover() -> dict[str, str]:
    index = ET.fromstring(get(SITEMAP_INDEX).content)
    maps = [
        node.text
        for node in index.findall("s:sitemap/s:loc", NS)
        if node.text
        and re.fullmatch(
            r"https://learn\.microsoft\.com/_sitemaps/"
            r"(power-apps|troubleshoot)_en-us_\d+\.xml",
            node.text,
        )
    ]
    if not any("/power-apps_" in url for url in maps) or not any(
        "/troubleshoot_" in url for url in maps
    ):
        raise RuntimeError("Both official sitemap groups are required; discovery is incomplete.")
    inventory: dict[str, str] = {}
    for map_url in maps:
        tree = ET.fromstring(get(map_url).content)
        for node in tree.findall("s:url", NS):
            location = node.findtext("s:loc", "", NS)
            url = canonical_url(location, map_url)
            if url:
                inventory[url] = node.findtext("s:lastmod", "", NS)
    if not all(any(url.startswith(root) for url in inventory) for root in ROOTS):
        raise RuntimeError("A monitored documentation directory is empty.")
    for root in ROOTS:
        inventory.setdefault(root.rstrip("/"), "")
    LOG.info("Discovered %d URLs from %d official sitemaps", len(inventory), len(maps))
    return inventory


def parse_article(url: str, html: str, lastmod: str) -> Article:
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find("h1")
    main = soup.select_one("main")
    if main is None:
        raise ValueError(f"No article body found: {url}")
    title = heading.get_text(" ", strip=True) if heading else ""
    if not title:
        metadata_title = soup.find("meta", attrs={"property": "og:title"})
        page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
        candidates = [
            str(metadata_title.get("content", "")).strip() if metadata_title else "",
            re.sub(r"\s*\|\s*Microsoft Learn\s*$", "", page_title).strip(),
            urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1],
        ]
        title = next(candidate for candidate in candidates if candidate)
        LOG.warning("No article heading found: %s; using fallback title %r", url, title)
    containers = main.select(".content")
    # Learn renders the title and article in separate .content siblings.
    body = (
        BeautifulSoup("".join(str(container) for container in containers), "html.parser")
        if containers
        else main
    )
    for noise in body.select(
        "script, style, nav, button, .metadata, .feedback-section, "
        ".feedback-archived, .contributors, .visually-hidden, "
        "#article-header, #article-metadata, #ms--additional-resources, "
        ".content-footer"
    ):
        noise.decompose()
    # Keep link targets and image references as part of the comparable body.
    for link in body.find_all("a", href=True):
        href = str(link["href"])
        if href.startswith("#"):
            continue
        link.replace_with(f"{link.get_text(' ', strip=True)} ({urljoin(url, href)})")
    for image in body.find_all("img"):
        image.replace_with(
            f"[Image: {image.get('alt', '')}] ({urljoin(url, str(image.get('src', '')))})"
        )
    code_blocks: list[str] = []
    for pre in body.find_all("pre"):
        code_blocks.append(pre.get_text().rstrip("\n"))
        pre.replace_with(f"\nMONITOR_CODE_BLOCK_{len(code_blocks) - 1}\n")
    for node in list(body.find_all(string=True)):
        if isinstance(node, Comment):
            node.extract()
        else:
            node.replace_with(re.sub(r"\s+", " ", str(node)))
    for cell in body.find_all(["th", "td"]):
        cell.append(" | ")
    for block in body.find_all(
        [
            "p",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "div",
            "li",
            "blockquote",
            "tr",
            "ul",
            "ol",
            "table",
            "section",
            "dl",
            "dt",
            "dd",
            "hr",
            "br",
        ]
    ):
        block.insert_before("\n")
        block.insert_after("\n")
    text = "\n".join(
        re.sub(r"[ \t\r\f\v]+", " ", line).strip()
        for line in body.get_text("").splitlines()
        if line.strip()
    )
    for index, code in enumerate(code_blocks):
        text = text.replace(f"MONITOR_CODE_BLOCK_{index}", f"[Code]\n{code}\n[/Code]")
    if len(text) < 40:
        raise ValueError(f"Unexpectedly empty body: {url}")
    modified = soup.find("meta", attrs={"name": "updated_at"})
    source = soup.find("meta", attrs={"name": "original_content_git_url"})
    return Article(
        url=url,
        title=title,
        text=text,
        modified=str(modified.get("content", "")) if modified else lastmod,
        source_path=str(source.get("content", "")) if source else "",
    )


def fetch_article(item: tuple[str, str]) -> Article:
    url, lastmod = item
    response = get(url)
    target = canonical_url(response.url, url)
    if target is None:
        raise ValueError(
            f"Article redirected outside monitored directories: {url} -> {response.url}"
        )
    return parse_article(url, response.text, lastmod)


def load_snapshot(path: Path) -> Snapshot | None:
    if not path.exists():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as file:
        data = json.load(file)
    if data["version"] != 1:
        raise ValueError("Unsupported snapshot version.")
    articles = {url: Article(**article) for url, article in data["articles"].items()}
    if not articles:
        raise ValueError("Existing snapshot is empty; refusing to re-bootstrap.")
    return Snapshot(data["checked_at"], articles, data["missing"])


def save_snapshot(snapshot: Snapshot, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8") as file:
        json.dump({"version": 1, **asdict(snapshot)}, file, ensure_ascii=False, sort_keys=True)
    temporary.replace(path)


def date_value(value: str) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def source_location(article: Article) -> tuple[str, str] | None:
    parsed = urlsplit(article.source_path)
    match = re.fullmatch(
        r"/MicrosoftDocs/(powerapps-docs(?:-pr)?|SupportArticles-docs(?:-pr)?)/blob/[^/]+/(.+)",
        parsed.path,
        re.IGNORECASE,
    )
    if parsed.netloc.lower() != "github.com" or not match:
        return None
    repo = re.sub(r"-pr$", "", match[1], flags=re.IGNORECASE)
    return f"MicrosoftDocs/{repo}", match[2]


def source_body(text: str) -> str:
    text = re.sub(r"\A---\r?\n.*?\r?\n---(?:\r?\n|$)", "", text, flags=re.DOTALL)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def historical_change(article: Article, cutoff: datetime) -> Change:
    unavailable = (
        "Historical published body unavailable. This is the current published article, "
        "selected by a documentation modification timestamp, not a feature release date. "
        "No historical published-body difference is asserted."
    )
    location = source_location(article)
    if location is None:
        return Change(
            article.title, article.url, "Historical candidate", "", article.text, unavailable
        )
    repo, path = location
    until = cutoff.isoformat().replace("+00:00", "Z")
    endpoint = (
        f"https://api.github.com/repos/{repo}/commits?"
        f"path={quote(path, safe='')}&until={quote(until, safe='')}&per_page=1"
    )
    response = session().get(
        endpoint,
        headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}"}
        if os.environ.get("GH_TOKEN")
        else {},
        timeout=(15, 90),
    )
    if response.status_code in (404, 409):
        LOG.warning("No accessible public source history for %s", article.url)
        return Change(
            article.title, article.url, "Historical candidate", "", article.text, unavailable
        )
    response.raise_for_status()
    commits = response.json()
    if not commits:
        LOG.warning("No public source baseline before cutoff: %s", article.url)
        return Change(
            article.title, article.url, "Historical candidate", "", article.text, unavailable
        )
    before_url = f"https://raw.githubusercontent.com/{repo}/{commits[0]['sha']}/{quote(path)}"
    # Pin both source versions instead of comparing against a moving branch.
    current_commits = get(
        f"https://api.github.com/repos/{repo}/commits?path={quote(path, safe='')}&per_page=1",
        github=True,
    ).json()
    if not current_commits:
        return Change(
            article.title, article.url, "Historical candidate", "", article.text, unavailable
        )
    after_url = (
        f"https://raw.githubusercontent.com/{repo}/{current_commits[0]['sha']}/{quote(path)}"
    )
    before_response = session().get(before_url, timeout=(15, 90))
    after_response = session().get(after_url, timeout=(15, 90))
    if 404 in (before_response.status_code, after_response.status_code):
        LOG.warning("Public historical source file missing: %s", article.url)
        return Change(
            article.title, article.url, "Historical candidate", "", article.text, unavailable
        )
    before_response.raise_for_status()
    after_response.raise_for_status()
    before_response.encoding = "utf-8"
    after_response.encoding = "utf-8"
    before = source_body(before_response.text)
    after = source_body(after_response.text)
    evidence = (
        "Public repository source comparison, NOT a verified historical website difference. "
        "Metadata/comments excluded; includes and publishing transformations are not expanded. "
        f"Baseline: {before_url} ; Current source: {after_url} . "
        "The full current published body follows the source comparison."
    )
    if before == after:
        evidence += " No public source-body changes were found; publication changes may differ."
    return Change(
        article.title,
        article.url,
        "Historical source comparison",
        before,
        after,
        evidence,
    )


def compare(previous: Snapshot, current: dict[str, Article]) -> tuple[list[Change], Snapshot]:
    removed_count = len(previous.articles.keys() - current.keys())
    if removed_count > max(10, len(previous.articles) * 0.2):
        raise RuntimeError(
            "Over 20% of the previous inventory disappeared; refusing partial discovery."
        )
    changes: list[Change] = []
    missing: dict[str, int] = {}
    articles = dict(current)
    for url, article in sorted(current.items()):
        before = previous.articles.get(url)
        if before is None:
            changes.append(
                Change(
                    article.title,
                    url,
                    "Newly observed article",
                    "",
                    article.text,
                    "First observed in this monitor, not necessarily newly published.",
                )
            )
        elif before.text != article.text or before.title != article.title:
            changes.append(
                Change(
                    article.title,
                    url,
                    "Published body changed",
                    before.text,
                    article.text,
                    f"Published snapshots: {previous.checked_at} to this scan.",
                )
            )
    for url in sorted(previous.articles.keys() - current.keys()):
        count = previous.missing.get(url, 0) + 1
        if count < 2:
            missing[url] = count
            articles[url] = previous.articles[url]
        else:
            article = previous.articles[url]
            changes.append(
                Change(
                    article.title,
                    url,
                    "No longer listed",
                    article.text,
                    "",
                    "Absent from official sitemaps for two successful scans; "
                    "deletion not asserted.",
                )
            )
    return changes, Snapshot("", articles, missing)


def scan(
    previous: Snapshot | None,
    inventory: dict[str, str],
    *,
    now: datetime,
    workers: int = 4,
    history: bool = True,
) -> tuple[list[Change], Snapshot, dict[str, Article]]:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        articles = {
            article.url: article for article in pool.map(fetch_article, sorted(inventory.items()))
        }
    if previous is not None:
        changes, snapshot = compare(previous, articles)
    else:
        cutoff = now - timedelta(days=30)
        changes = []
        for article in articles.values():
            modified = date_value(article.modified)
            if modified is not None and cutoff <= modified <= now:
                if history:
                    changes.append(historical_change(article, cutoff))
                else:
                    changes.append(
                        Change(
                            article.title,
                            article.url,
                            "Historical candidate",
                            "",
                            article.text,
                            "History lookup explicitly disabled. Current published body only; "
                            "selected by modification timestamp, not a feature release date.",
                        )
                    )
        snapshot = Snapshot("", articles, {})
    snapshot.checked_at = now.isoformat()
    LOG.info("Fetched %d articles; %d report entries", len(articles), len(changes))
    return changes, snapshot, articles


def run(args: argparse.Namespace) -> None:
    from report import generate_pdf

    now = datetime.now(UTC)
    previous = load_snapshot(args.state)
    inventory = discover()
    if args.limit:
        if args.state.exists() or args.output.joinpath("next-snapshot.json.gz").exists():
            raise ValueError("Smoke-test output/state must be separate from production state.")
        inventory = dict(sorted(inventory.items())[: args.limit])
    changes, snapshot, articles = scan(
        previous, inventory, now=now, workers=args.workers, history=not args.no_history
    )
    args.output.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"changed": bool(changes), "count": len(changes)}
    if changes:
        digest = hashlib.sha256(
            json.dumps([asdict(change) for change in changes], sort_keys=True).encode()
        ).hexdigest()[:16]
        tag = f"docs-{digest}"
        pdf = args.output / f"powerapps-updates-{digest}.pdf"
        generate_pdf(
            changes,
            pdf,
            now=now,
            since=previous.checked_at if previous else (now - timedelta(days=30)).isoformat(),
            articles=articles,
            initial=previous is None,
        )
        manifest.update(tag=tag, pdf=str(pdf))
    save_snapshot(snapshot, args.output / "next-snapshot.json.gz")
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as file:
            for key, value in manifest.items():
                file.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=Path("state-store/snapshot.json.gz"))
    parser.add_argument("--output", type=Path, default=Path("output/pdf"))
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=4)
    parser.add_argument(
        "--limit", type=int, help="Smoke test only; never use with production state."
    )
    parser.add_argument(
        "--no-history", action="store_true", help="Explicitly skip public source history."
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run(args)


if __name__ == "__main__":
    main()
