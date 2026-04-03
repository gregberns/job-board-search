# Task 09: HN Who's Hiring Scraper

## Objective
Build a best-effort parser for Hacker News "Who is Hiring" threads. This scraper has the lowest structured-data expectations — primary value is raw text and direct URLs.

## Files to Create
- `JobSpy/jobspy/hn/__init__.py` (replace stub from Task 03)

## Design
Standard `Scraper` subclass (NOT ATSBoardScraper — single-source fetch).

### API
1. **Find latest thread:**
   `GET https://hn.algolia.com/api/v1/search_by_date?query="who is hiring"&tags=story,author_whoishiring&hitsPerPage=1`
   - **MUST use `search_by_date`**, NOT `search` — the `search` endpoint returns relevance-ranked results and gives old (2020) threads
   - Can be overridden with `hn_thread_id` from `ScraperInput`

2. **Fetch full thread:**
   `GET https://hn.algolia.com/api/v1/items/{thread_id}`
   - Only process `children` entries (top-level comments)
   - Skip replies to comments (nested children)

### Comment Parsing
Comment text is **HTML** containing `<a>` tags, `<p>` tags, and HTML entities (`&#x2F;` for `/`, `&amp;` for `&`).

Parsing strategy (pipe-delimited header):
1. Decode HTML entities, strip tags from first line
2. Split first line on `|`
3. First segment -> `company_name`
4. Scan remaining segments for:
   - Location patterns (city/state, "Remote", "ONSITE/REMOTE")
   - Salary patterns (`$xxx,xxx` or `$xxxk`)
   - URLs (company website, job posting link)
5. Everything after first line -> `description` (full HTML -> markdown)
6. Extract emails from full text
7. If no `|` found in first line: set `company_name` = first 80 chars, `title` = None

### Expected Parse Rates
- Company name: ~60%
- Location: ~50%
- Salary: ~30%
- This is explicitly best-effort. Many comments will have partial data.

### Data Mapping
| Parsed field | JobPost field | Notes |
|---|---|---|
| thread comment id | `id` | Prefix as `hn-{id}` |
| first pipe segment | `company_name` | Best-effort |
| _(not reliably available)_ | `title` | Often absent in HN posts |
| company URL from text | `job_url` | First URL found, or HN comment link |
| email from text | `emails` | If present |
| location segments | `location` | Best-effort parse |
| salary pattern | `compensation` | Regex extract from pipe segments |
| "Remote"/"ONSITE" keywords | `is_remote` | |
| full comment text | `description` | HTML -> markdown |
| comment `created_at` | `date_posted` | |

## Acceptance Criteria
- `scrape_jobs(site_name="hn")` returns jobs from the latest Who's Hiring thread
- `scrape_jobs(site_name="hn", hn_thread_id="12345678")` uses the specified thread
- Pipe-delimited headers are parsed correctly for well-formatted comments
- Malformed comments don't crash the parser (graceful degradation)
- HTML entities are properly decoded
- Uses `search_by_date` (not `search`) for thread discovery
- `filter_jobs()` is applied for search_term filtering

## Dependencies
- Task 01 (model changes)
- Task 02 (filter_jobs utility)
- Task 03 (registration)

## Blocked By
- Tasks 01, 02, 03
