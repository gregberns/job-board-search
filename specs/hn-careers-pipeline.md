# Spec: HN Careers Token Discovery (`jbs tokens discover`)

## Problem

HN Who's Hiring posts are one-per-company -- they tell us a company is hiring but not the individual roles. We get ~270 entries like "LiveKit | Engineers | Remote | $150-250k" with a URL, but no structured job listings.

Meanwhile, many of these companies:
- Use ATS platforms we already scrape (20 Ashby, 11 Greenhouse, 3 Lever) but their tokens aren't in the `companies` table
- Link to careers pages with full job listings we could parse
- Are exactly the AI-native startups we care about most

## Goal

Given HN company URLs already in `jobs.db`, automatically:
1. Discover and extract ATS tokens -> insert into `companies` table for existing scrapers
2. Find careers pages -> record in `hn_career_pages` for future extraction
3. Detect ATS embeds on careers pages -> extract additional tokens

## Current Data (from initial HN scrape)

| Category | Count | Description |
|----------|-------|-------------|
| Total HN jobs | 272 | One per company |
| ATS URLs (Ashby) | 20 | 20 NEW tokens not in DB |
| ATS URLs (Greenhouse) | 11 | 7 NEW tokens not in DB |
| ATS URLs (Lever) | 3 | 3 NEW tokens not in DB |
| ATS URLs (other) | 4 | Dover (2), Teamtailor (1), Workable (1) |
| Direct careers/jobs pages | 63 | URL contains /careers, /jobs, etc. |
| HN comment fallbacks | 38 | No URL found in comment |
| Other URLs (homepages etc.) | 133 | Need careers page discovery |

## Architecture

Part of the `jbs` CLI, not a standalone script. Implemented as a `jbs tokens discover` subcommand that operates on the existing database. Uses `Store` for all DB access. Discovered tokens go directly into the `companies` table.

### Tables Used

- **`companies`** (spec 02) -- destination for discovered tokens. `Store.add_token()` creates company records.
- **`hn_career_pages`** (spec 02) -- audit trail of how tokens were found. Tracks the discovery process: which HN comments led to which careers pages and tokens.
- **`jobs`** -- source of HN job URLs to process.

### Relationship Between Tables

`hn_career_pages` records the discovery process. `companies` is where scrapers look for tokens. When a token is discovered:

```python
# 1. Record the discovery (audit trail)
store.upsert_hn_career_page(hn_job_id, ats_platform="ashby", ats_token="acme-ai", ...)

# 2. Add the token to the companies table (actionable)
store.add_token("ashby", "acme-ai", company_name="Acme AI")
```

The next `jbs scrape` picks up the new token automatically.

## CLI Interface

```bash
jbs tokens discover                       # run all phases (1-3)
jbs tokens discover --phase harvest       # Phase 1: extract ATS tokens from URLs
jbs tokens discover --phase find-careers  # Phase 2: discover careers pages
jbs tokens discover --phase detect-ats    # Phase 3: detect ATS on careers pages
jbs tokens discover --status              # show discovery progress summary
```

### Normal Output

```
$ jbs tokens discover

Phase 1: Harvest ATS tokens from HN URLs...
  Found 30 ATS tokens in job URLs
    ashby: 20 new   greenhouse: 7 new   lever: 3 new
  Updated 30 hn_career_pages rows

Phase 2: Discover careers pages...
  Processing 133 homepage URLs...
  Found 47 careers pages (12 probed, 35 from link scan)
  Classified 22 as dead_end (LinkedIn, YouTube, etc.)
  64 URLs still unresolved

Phase 3: Detect ATS on careers pages...
  Scanned 47 careers pages
  Found 8 additional ATS tokens
    greenhouse: 5   ashby: 2   lever: 1
  Classified 22 as static_html, 9 as spa, 8 as dead_end

Summary:
  38 new tokens added to companies table
  47 careers pages cataloged
  Run 'jbs scrape' to scrape the newly discovered boards
```

### Status Output

```
$ jbs tokens discover --status

HN Career Pages: 272 total
  Status:
    scraped:     34 (ATS token extracted and working)
    discovered:  47 (careers page found, no ATS token)
    pending:    133 (homepage URL, not yet processed)
    dead_end:    22 (LinkedIn, YouTube, etc.)
    failed:       7 (network errors)
    skipped:     29 (no URL in HN comment)
  ATS tokens found: 38
    ashby: 22   greenhouse: 12   lever: 4
```

## Phases

### Phase 1: Harvest ATS Tokens from URLs

**Input:** HN job URLs from the `jobs` table.
**Output:** New tokens in `companies` table, `hn_career_pages` rows updated.

Logic:
1. Query all HN jobs with URLs that haven't been processed:
   ```python
   rows = store.get_unprocessed_hn_urls()
   # SELECT j.id, j.job_url, j.company_raw
   # FROM jobs j
   # LEFT JOIN hn_career_pages h ON h.hn_job_id = j.id
   # WHERE j.site = 'hn' AND j.job_url IS NOT NULL AND h.hn_job_id IS NULL
   ```
2. Regex-match against known ATS URL patterns:
   ```python
   _ATS_PATTERNS = [
       (r'jobs\.ashbyhq\.com/([^/?#]+)', 'ashby'),
       (r'boards\.greenhouse\.io/([^/?#]+)', 'greenhouse'),
       (r'job-boards\.greenhouse\.io/([^/?#]+)', 'greenhouse'),
       (r'jobs\.lever\.co/([^/?#]+)', 'lever'),
   ]
   # Special case: grnh.se/ short URLs -- follow redirect to get full greenhouse URL
   ```
3. For each match, add the token to the DB:
   ```python
   company_name = normalize_company_name(job.company_raw) if job.company_raw else None
   store.add_token(platform, token, company_name)
   store.upsert_hn_career_page(
       hn_job_id=job.id,
       company_name=job.company_raw,
       company_url=job.job_url,
       ats_platform=platform,
       ats_token=token,
       page_type='ats',
       status='scraped',
   )
   ```
4. For non-ATS URLs, insert a `pending` row in `hn_career_pages`:
   ```python
   store.upsert_hn_career_page(
       hn_job_id=job.id,
       company_name=job.company_raw,
       company_url=job.job_url,
       status='pending',
   )
   ```
5. Backfill `companies.website` from HN job URLs where the company already exists.

**Dependencies:** None. Pure Python + regex + `Store`.
**Expected yield:** ~30 new ATS tokens -> hundreds of job listings on next `jbs scrape`.

### Phase 2: Careers Page Discovery

**Input:** HN companies with non-ATS URLs (homepages, unknown pages) from `hn_career_pages` where `status = 'pending'`.
**Output:** Discovered careers page URLs in `hn_career_pages`.

Logic:
1. For URLs already containing `/careers`, `/jobs`, `/hiring` -> mark as `discovered` directly.
2. Classify non-scrapeable URLs (LinkedIn, YouTube, Google Docs, PDF) as `page_type = 'dead_end'`.
3. For homepage URLs, probe common paths with HEAD requests:
   ```python
   _CAREERS_PATHS = [
       '/careers', '/jobs', '/join', '/about/careers', '/company/careers',
       '/work-with-us', '/hiring', '/open-positions', '/join-us',
   ]
   ```
4. If no careers path found, GET the homepage and scan `<a>` tags for careers-related links.
5. Update `hn_career_pages.careers_url` and `status = 'discovered'`.

**Rate limiting:** 1 req/sec per domain, 0.5s between different domains. Uses `create_session()` from `jbs/util.py` for retry/timeout/User-Agent.

**Timeout:** ~10 min for 200 companies at rate-limited pace.

### Phase 3: ATS Detection on Careers Pages

**Input:** Discovered careers pages from Phase 2 (`status = 'discovered'`, `ats_platform IS NULL`).
**Output:** Additional ATS tokens in `companies` table.

Logic:
1. GET the careers page HTML using `create_session()`.
2. Scan for ATS indicators:
   - `<iframe src="...greenhouse.io...">` -> extract token from src
   - `<iframe src="...lever.co...">` -> extract slug
   - `<iframe src="...ashbyhq.com...">` -> extract board
   - `id="grnhse_app"` -> Greenhouse embed, look for `data-url` or script tag with token
   - `<script src="...lever.co/embed...">` -> Lever widget
   - Links (`<a href>`) to ATS job listings (same patterns as Phase 1)
3. If ATS detected -> extract token, add to `companies` via `Store.add_token()`, update `hn_career_pages`:
   ```python
   store.add_token(platform, token, company_name)
   store.update_hn_career_page(hn_job_id,
       ats_platform=platform, ats_token=token,
       page_type='ats', status='scraped')
   ```
4. If no ATS -> classify based on content analysis:
   - HTML body has job-like content (titles, "apply" links) -> `page_type = 'static_html'`
   - Body is empty shell (`<div id="root"></div>`) -> `page_type = 'spa'`

### Phase 4: Custom Careers Page Extraction (v2, deferred)

**Deferred.** Extracting individual job listings from non-ATS careers pages (`static_html` and `spa` types) requires either LLM-based HTML parsing or a headless browser (Playwright). This is a v2 feature.

For now, Phases 1-3 capture the high-value tokens that feed into existing ATS scrapers. The `hn_career_pages` table retains the discovered careers URLs so Phase 4 can build on them later.

**What v2 would look like:**
- For `static_html` pages: GET HTML, convert to markdown via `html_to_markdown()`, send to Haiku for structured extraction.
- For `spa` pages: headless browser (Playwright), then same extraction.
- Extracted jobs go into the `jobs` table with `id = hn-careers-{company_slug}-{hash}` and `site = 'hn'`.

## Store Methods

All DB access goes through `Store`. The following methods support the discovery pipeline:

```python
class Store:
    # --- HN Career Pages ---
    def get_unprocessed_hn_urls(self) -> list[dict]:
        """HN jobs with URLs not yet in hn_career_pages."""

    def upsert_hn_career_page(self, hn_job_id: str, **fields) -> None:
        """Insert or update an hn_career_pages row."""

    def update_hn_career_page(self, hn_job_id: str, **fields) -> None:
        """Update fields on an existing hn_career_pages row."""

    def get_hn_pages_by_status(self, status: str) -> list[dict]:
        """Get hn_career_pages rows filtered by status."""

    def get_hn_discovery_summary(self) -> dict:
        """Counts by status and platform for --status output."""

    # --- These already exist (spec 01) ---
    def add_token(self, platform: str, token: str, company_name: str | None = None) -> bool:
        """Add a token to companies table. Returns True if new."""

    def resolve_company(self, job: Job) -> int | None:
        """Resolve job to company_id."""
```

## Implementation Notes

### Module Location

The discovery logic lives in `jbs/discover.py`, called by the `jbs tokens discover` CLI command in `jbs/cli.py`. Not in `scripts/`.

```python
# jbs/discover.py
from jbs.store import Store
from jbs.util import create_session, normalize_company_name

def run_discovery(store: Store, phase: str | None = None, verbose: bool = False):
    """Run HN token discovery pipeline."""
    if phase is None or phase == 'harvest':
        harvest_ats_tokens(store, verbose)
    if phase is None or phase == 'find-careers':
        discover_careers_pages(store, verbose)
    if phase is None or phase == 'detect-ats':
        detect_ats_on_careers(store, verbose)
```

### CLI Wiring

```python
# In jbs/cli.py, under the tokens group:
@tokens.command()
@click.option("--phase", type=click.Choice(["harvest", "find-careers", "detect-ats"]))
@click.option("--status", "show_status", is_flag=True, help="Show discovery progress")
@click.pass_context
def discover(ctx, phase, show_status):
    """Discover ATS tokens from HN Who's Hiring comments."""
    store = Store(ctx.obj["config"].db_path)
    if show_status:
        print_discovery_summary(store.get_hn_discovery_summary())
        return
    run_discovery(store, phase=phase, verbose=ctx.obj["verbose"])
```

### When to Run

Token discovery is an on-demand step, not part of every `jbs scrape`. Run it after scraping HN to harvest tokens from new comments:

```bash
jbs scrape --sources hn          # get latest HN Who's Hiring comments
jbs tokens discover              # find ATS tokens in those comments
jbs scrape                       # full scrape now includes newly discovered boards
```

It can also be re-run after new HN threads are posted (monthly).

## Non-Goals (for now)

- **Playwright/headless browser** -- deferred until we know how many high-value companies need it (Phase 4)
- **Recurring scheduling** -- this is an on-demand enrichment step; can re-run after new HN threads are scraped
- **Full job descriptions from careers pages** -- we get tokens that feed into existing scrapers, not full descriptions (Phase 4)
- **Non-ATS job board platforms** (Workday, BambooHR, etc.) -- small volume, complex scraping, low ROI
