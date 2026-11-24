# Power Apps documentation update monitor

Collect new or updated English articles from these Microsoft Learn directories:

- <https://learn.microsoft.com/en-us/power-apps/>
- <https://learn.microsoft.com/en-us/troubleshoot/power-platform/power-apps/>

Model-driven apps and Dataverse are excluded using URL paths, article titles,
and Microsoft Learn `ms.subservice` metadata. This covers the maker/developer
`model-driven-apps` and `data-platform` sections, plus individual articles labeled
with model-driven, Dataverse, or the legacy Common Data Service name. Incidental
mentions in otherwise relevant articles do not exclude those articles. Shared
Power Apps content remains included unless its path, title, or metadata matches
an excluded topic.

Generate a concise PDF containing each article's **clickable URL, title, modification
timestamp, and short summary**. Reports are committed under [output/pdf](output/pdf)
and also uploaded as GitHub Release attachments. No email, Azure service, or AI key
is required.

## Manual trigger and lookback

1. Push this code to your GitHub repository's default branch.
2. Open **Actions > Power Apps documentation monitor > Run workflow**.
3. Choose a branch and enter **days**: a positive integer, default **7**
   (for example, `1`, `14`, or `30`). The input is not limited to 7 days.
4. After success, open the PDF in that branch's `output/pdf` directory or download
   it from **Releases > Assets**.

The daily schedule remains enabled at `01:00 UTC` (09:00 Beijing time) and uses
7 days. GitHub may delay scheduled runs. Manual runs work independently of the
schedule. Each run produces a PDF, including an explicit no-results report when
no articles match.

The repository must permit Actions `contents: write`, commits to the selected
branch, and Release creation. Branch protection can block automatic commits;
use an allowed branch or adjust repository rules deliberately. The workflow uses
its built-in `GITHUB_TOKEN`, not a stored personal token. Diagnostic artifacts
are retained for 30 days; committed PDFs and Release assets do not expire
automatically. If Release upload fails after the PDF commit, the PDF remains
available in the repository and the workflow fails visibly.

## Selection and summary accuracy

- Discover the complete current inventory from both official sitemap groups,
  then fetch every page. Select articles whose HTML `updated_at` falls within
  the inclusive UTC interval `[run time - days, run time]`. Use sitemap `lastmod`
  only if `updated_at` is absent. Missing/invalid dates fail the run rather than
  silently skipping articles. Future timestamps are excluded.
- Every run recomputes its requested window; previous scans do not suppress
  articles. Only the Power Apps scope above is monitored; no persistent scan baseline is needed.
- PDF sections show **Newly created**, **Updated**, then **Unclassified** documents,
  retaining the scan's newest-modification-first order within each section.
  Classification uses public GitHub source history, not modification dates.
  "Newly created" requires that the first available commit for the source path
  added the file within the observation window. Renames are not treated as additions.
  This identifies new public source files, not verified website publication dates;
  repository imports and copies can look like new documents.
  "Updated" requires an accessible source-body comparison with a version predating
  the window. Missing history, missing source files, or ambiguous first commits
  remain explicitly unclassified rather than being guessed as new or updated.
- When public GitHub source history is accessible, compare the last source
  version before the window start against the latest version at/before the
  run time. Summaries contain the number of changed blocks and short
  representative added/updated and removed/replaced excerpts, not an AI-written
  interpretation or full article reproduction.
- If source history or a baseline is unavailable, clearly label a short current
  article overview instead. **That overview is not a claim about what changed.**
  Metadata-only changes can yield no source-body differences and are labeled.
  HTTP failures/rate limits other than explicitly unavailable source history
  fail the run.
- Public source history can lag or differ from the published page. Includes and
  publishing transformations are not expanded. Dates can be inaccurate or
  unchanged despite an edit; removed pages and intermediate edits are not a
  complete historical audit. Documentation updates are not feature releases.
- Summaries normalize formatting and omit images. PDFs retain attribution,
  source links, and historical limitations.

## Local use (Windows / PowerShell)

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```powershell
uv sync --locked
uv run python monitor.py --days 7
uv run python monitor.py --days 30
```

Final PDFs are written to `output\pdf\power-apps-updates-*.pdf`. The manifest
in the same directory records the exact UTC window, scanned count, match count,
and report path. Local execution saves files but does not commit or push them.
For public GitHub history, set `GH_TOKEN` to an authorized token to avoid anonymous
API limits; do not commit credentials.

```powershell
uv run pytest
uv run ruff check .
uv run python monitor.py --days 7 --limit 3 --no-history --output tmp\smoke
```

`--limit` is a partial smoke test and marks its PDF as incomplete.
`--no-history` explicitly disables history lookup; all summaries are labeled
current overviews, not verified changes, and all entries are unclassified.
Neither flag is used by the workflow.
The default PDF font is Windows Arial or Linux DejaVu Sans. Set `PDF_FONT` to
another Unicode TrueType font if necessary; unsupported characters appear as
`[U+XXXX]` instead of silently disappearing.

Full scans may take several minutes. HTTP timeouts, finite retries, four default
workers, and a 180-minute workflow timeout bound execution. Failed discovery,
fetching, PDF generation, commits, or uploads fail visibly.

## Attribution and license

Microsoft and Microsoft Learn contributors retain attribution. Public
documentation sources declare CC BY 4.0; PDFs link to original articles,
source comparisons where available, and <https://creativecommons.org/licenses/by/4.0/>.
Excerpts are shortened/reformatted; third-party material may have separate terms.
No images are reproduced.
