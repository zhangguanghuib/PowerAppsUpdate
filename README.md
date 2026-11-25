# Power Apps and Power Automate documentation update monitors

Separate GitHub Actions workflows collect new or updated English articles from
these Microsoft Learn directories.

### Power Apps

- <https://learn.microsoft.com/en-us/power-apps/>
- <https://learn.microsoft.com/en-us/troubleshoot/power-platform/power-apps/>

Model-driven apps and Dataverse are excluded using URL paths, article titles,
and Microsoft Learn `ms.subservice` metadata. This covers the maker/developer
`model-driven-apps` and `data-platform` sections, plus individual articles labeled
with model-driven, Dataverse, or the legacy Common Data Service name. Incidental
mentions in otherwise relevant articles do not exclude those articles. Shared
Power Apps content remains included unless its path, title, or metadata matches
an excluded topic.

### Power Automate

- <https://learn.microsoft.com/en-us/power-automate/>
- <https://learn.microsoft.com/en-us/troubleshoot/power-platform/power-automate/>

All topics under these roots are included, including cloud and desktop flows.
The Power Apps model-driven/Dataverse exclusions do not apply to Power Automate.
Each product has its own PDF filenames, release tags, and report branding; scanning
one product does not include articles from the other.

Generate a concise PDF containing each article's **clickable URL, title, modification
timestamp, and short summary**. Reports are committed under [output/pdf](output/pdf)
and also uploaded as GitHub Release attachments. No email, Azure service, or AI key
is required.

## Manual trigger and lookback

1. Push this code to your GitHub repository's default branch.
2. Open **Actions**, choose **Power Apps documentation monitor** or
   **Power Automate documentation monitor**, then select **Run workflow**.
3. Choose a branch and enter **days**: a positive integer, default **7**
   (for example, `1`, `14`, or `30`). The input is not limited to 7 days.
4. After success, open the PDF in that branch's `output/pdf` directory or download
   it from **Releases > Assets**.

Both workflows run daily at `01:00 UTC` (09:00 Beijing time) and use
7 days. Runs targeting the same branch are serialized across both workflows to
avoid concurrent PDF commits and push conflicts. GitHub may delay scheduled runs.
Manual runs work independently of the
schedule. Each run produces a PDF, including an explicit no-results report when
no articles match.

The repository must permit Actions `contents: write`, commits to the selected
branch, and Release creation. Branch protection can block automatic commits;
use an allowed branch or adjust repository rules deliberately. The workflow uses
its built-in `GITHUB_TOKEN`, not a stored personal token. Diagnostic artifacts
are retained for 30 days; committed PDFs and Release assets do not expire
automatically. If Release upload fails after the PDF commit, the PDF remains
available in the repository and the workflow fails visibly.

## Latest reports for OneDrive synchronization

Each workflow commits [output/latest.json](output/latest.json) together with its PDF.
This JSON array contains the newest Power Apps report and newest Power Automate
report separately, with `product`, `name`, `path`, `created_at`, `size`, `type`,
and `download_url` fields. Selection uses recorded creation time, not filename
sorting, checkout file timestamps, or a fixed exclusion list.

For existing reports, creation time is the earliest recorded Git addition time.
New reports record their generation time before being committed; later updates
or regeneration of the same filename do not reset that time. Complete Git history
is required, so both workflows use `fetch-depth: 0`. Timestamp ties are resolved
deterministically by filename. The index is rebuilt from the current PDF folder;
missing history or missing product reports fail explicitly.

The OneDrive flow polls this index every five minutes and processes only these
two latest reports. It preserves `/CopilotStudioWhatIsNew` as the destination,
skips existing equal-size files, and verifies downloaded sizes. It does not backfill
intermediate reports when several are generated between checks.

The flow reads the GitHub Contents API for `output/latest.json` and decodes its
`content` with `json(base64ToString(body('List_latest_reports')?['content']))`.
GitHub folder listings themselves do not provide file creation times. To rebuild
the index manually from complete Git history:

```powershell
uv run python latest_reports.py --repository zhangguanghuib/PowerAppsUpdate --branch main
```

## Selection and summary accuracy

- Discover the complete current inventory from both official sitemap groups,
  then fetch every page. Select articles whose HTML `updated_at` falls within
  the inclusive UTC interval `[run time - days, run time]`. Use sitemap `lastmod`
  only if `updated_at` is absent. Missing/invalid dates fail the run rather than
  silently skipping articles. Future timestamps are excluded.
- Sitemap entries can remain after an article moves. If an entry redirects to
  an HTTPS Microsoft Learn page outside the selected product's monitored roots,
  log a warning with both URLs and skip it without aborting the scan. The
  destination is not included under the original article's URL. Excluded
  Power Apps topic redirects are also skipped. Redirects to other hosts or
  non-HTTPS destinations, HTTP failures, and article parsing errors still fail
  the run; monitoring scope is not broadened to follow moved pages.
- Every run recomputes its requested window; previous scans do not suppress
  articles. Only the selected product's scope above is monitored; no persistent scan baseline
  is needed.
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
  run time. Updated documents show **Before / After** excerpts together for each
  changed passage, labeled **Added content**, **Removed content**, or **Revised
  content**, with the section heading for context. Added/removed passages are
  described as documentation additions/removals, not newly available/removed
  product capabilities.
- Comparisons normalize paragraph soft wrapping and common inline Markdown
  formatting, while retaining code indentation and link targets. Each updated
  document shows up to three changed passages in source order; omitted passages
  are explicitly counted. Each side is limited to approximately 320 characters,
  focused near its first differing text so a long unchanged introduction does
  not hide the edit. These remain representative extracts, not exhaustive
  changes, AI interpretations, or inferred statements of user impact.
- Newly created documents receive a short **Document summary** extracted from
  their current content, without Before / After labels or a claim that the
  documented feature itself is new. No model API, API key, or AI inference
  charges are introduced.
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
uv run python monitor.py --product power-automate --days 7
uv run python monitor.py --product power-automate --days 30
```

Power Apps is the default when `--product` is omitted. Final PDFs are written to
`output\pdf\power-apps-updates-*.pdf` or `output\pdf\power-automate-updates-*.pdf`.
The manifest in the same directory describes the latest local run and records the
product, exact UTC window, scanned count, match count, and report path.
Local execution saves files but does not commit or push them.
For public GitHub history, set `GH_TOKEN` to an authorized token to avoid anonymous
API limits; do not commit credentials.

```powershell
uv run pytest
uv run ruff check .
uv run python monitor.py --days 7 --limit 3 --no-history --output tmp\smoke
uv run python monitor.py --product power-automate --days 7 --limit 3 --no-history --output tmp\smoke-automate
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
