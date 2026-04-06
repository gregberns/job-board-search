# Spec: HN Careers Page Pipeline

## Problem

HN Who's Hiring posts are one-per-company — they tell us a company is hiring but not the individual roles. We get 272 entries like "LiveKit | Engineers | Remote | $150-250k" with a URL, but no structured job listings.

Meanwhile, many of these companies:
- Use ATS platforms we already scrape (20 Ashby, 11 Greenhouse, 3 Lever) but their tokens aren't in our token files
- Link to careers pages with full job listings we could parse
- Are exactly the AI-native startups we care about most

## Goal

Given HN company URLs, automatically:
1. Discover and extract ATS tokens → feed to existing scrapers
2. Find careers pages → extract individual job listings
3. Load structured job data into `jobs.db`

## Current Data

| Category | Count | Description |
|----------|-------|-------------|
| Total HN jobs | 272 | One per company |
| ATS URLs (Ashby) | 20 | 20 NEW tokens not in ashby.txt |
| ATS URLs (Greenhouse) | 11 | 7 NEW tokens not in greenhouse_raw.txt |
| ATS URLs (Lever) | 3 | 3 NEW tokens not in lever_raw.txt |
| ATS URLs (other) | 4 | Dover (2), Teamtailor (1), Workable (1) |
| Direct careers/jobs pages | 63 | URL contains /careers, /jobs, etc. |
| HN comment fallbacks | 38 | No URL found in comment |
| Other URLs (homepages etc.) | 133 | Need careers page discovery |

## Architecture

Single script: `scripts/hn_careers.py` with subcommands. Writes to the same `jobs.db`. Separate from `run_search.py` — this enriches existing HN data rather than scraping fresh.

### New DB Table

```sql
CREATE TABLE IF NOT EXISTS hn_career_pages (
    hn_job_id       TEXT PRIMARY KEY REFERENCES jobs(id),
    company_name    TEXT,
    company_url     TEXT,          -- URL from HN comment
    careers_url     TEXT,          -- discovered careers page
    ats_platform    TEXT,          -- greenhouse, lever, ashby, or NULL
    ats_token       TEXT,          -- extracted board token
    page_type       TEXT,          -- ats, static_html, spa, dead_end, unknown
    status          TEXT DEFAULT 'pending',
    last_checked    TEXT,
    error           TEXT
);
```

**Status values:** `pending` → `discovered` → `scraped` → `failed` / `skipped`

## Phases

### Phase 1: Harvest ATS Tokens

**Input:** HN job URLs already in `jobs.db`
**Output:** New tokens appended to `tokens/*.txt`, `hn_career_pages` rows updated

Logic:
1. Query all HN job URLs from DB
2. Regex-match against known ATS URL patterns:
   - Ashby: `jobs.ashbyhq.com/{token}`
   - Greenhouse: `boards.greenhouse.io/{token}`, `job-boards.greenhouse.io/{token}`, `grnh.se/` (follow redirect)
   - Lever: `jobs.lever.co/{slug}`
3. Check which tokens are NOT already in token files
4. Append new tokens to `tokens/{ats}_raw.txt`
5. Insert/update `hn_career_pages` with `ats_platform`, `ats_token`, `status='discovered'`
6. Backfill `companies.url` from HN job URLs

**Dependencies:** None. Pure Python + sqlite3 + re.
**Expected yield:** 30 new ATS tokens → hundreds of job listings on next `run_search.py`.

### Phase 2: Careers Page Discovery

**Input:** HN companies with non-ATS URLs (homepages, unknown pages)
**Output:** Discovered careers page URLs in `hn_career_pages`

Logic:
1. For URLs already containing /careers, /jobs, /hiring → mark as `discovered` directly
2. For homepage URLs, probe common paths with HEAD requests:
   ```
   /careers, /jobs, /join, /about/careers, /company/careers,
   /work-with-us, /hiring, /open-positions, /join-us
   ```
3. If no careers path found, GET the homepage and scan `<a>` tags for careers-related links
4. Rate limit: 1 req/sec per domain, 0.5s between different domains
5. Update `hn_career_pages.careers_url` and `status='discovered'`
6. Classify non-scrapeable URLs (LinkedIn, YouTube, Google Docs, PDF) as `page_type='dead_end'`

**Dependencies:** `requests` (already installed).
**Timeout:** ~10 min for 200 companies at rate-limited pace.

### Phase 3: ATS Detection on Careers Pages

**Input:** Discovered careers pages from Phase 2
**Output:** Additional ATS tokens extracted from page HTML

Logic:
1. GET the careers page HTML
2. Scan for ATS indicators:
   - `<iframe src="...greenhouse.io...">` → extract token from src
   - `<iframe src="...lever.co...">` → extract slug
   - `<iframe src="...ashbyhq.com...">` → extract board
   - `id="grnhse_app"` → Greenhouse embed, look for `data-url` or script tag with token
   - `<script src="...lever.co/embed...">` → Lever widget
   - Links (`<a href>`) to ATS job listings
3. If ATS detected → extract token, update `hn_career_pages`, append to token files
4. If no ATS → mark `page_type='static_html'` or `page_type='spa'` based on content analysis:
   - If HTML body has job-like content (titles, "apply" links) → `static_html`
   - If body is empty shell (`<div id="root"></div>`) → `spa`

**Dependencies:** `requests`, `re` (already installed).

### Phase 4: Custom Careers Page Extraction

**Input:** Careers pages marked `static_html` or `spa`
**Output:** Individual job listings in `jobs` table

Logic:
1. For `static_html` pages: GET HTML, convert to markdown via `html_to_markdown()`
2. For `spa` pages: skip for now (would need Playwright — defer)
3. Send markdown to Haiku subagent in batches with prompt:
   ```
   Extract job listings from this careers page. Return JSON array:
   [{"title": "...", "url": "...", "location": "...", "department": "..."}]
   If no jobs found, return [].
   ```
4. Map extracted jobs to DB rows:
   - `id`: `hn-careers-{company_slug}-{hash(title+url)}`
   - `site`: `hn` (same source, these are HN-discovered companies)
   - `run_id`: current timestamp
   - `board_token`: `hn-{hn_job_id}` (traces back to source comment)
5. Insert into `jobs` table, create/update `companies` entries

**Dependencies:** Haiku subagents (Claude Code), `html_to_markdown()` from util.py.

## CLI Interface

```bash
# Run individual phases
python scripts/hn_careers.py harvest-ats
python scripts/hn_careers.py discover
python scripts/hn_careers.py detect-ats
python scripts/hn_careers.py extract

# Run all phases in sequence
python scripts/hn_careers.py run-all

# Show status summary
python scripts/hn_careers.py status
```

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `scripts/hn_careers.py` | Create | Main pipeline script |
| `scripts/init_db.py` | Modify | Add `hn_career_pages` table |
| `tokens/ashby.txt` | Modify | Append ~20 new tokens |
| `tokens/greenhouse_raw.txt` | Modify | Append ~7 new tokens |
| `tokens/lever_raw.txt` | Modify | Append ~3 new tokens |

## Non-Goals (for now)

- **Playwright/headless browser** — deferred until we know how many high-value companies need it
- **Recurring scheduling** — this is a one-shot enrichment; can re-run after new HN threads are scraped
- **Full job descriptions from careers pages** — we get titles and URLs, not full descriptions (those come when ATS tokens are scraped via existing scrapers)
- **Non-ATS job board platforms** (Workday, BambooHR, etc.) — small volume, complex scraping, low ROI
