# Task 05: RemoteOK Scraper

## Objective
Build the RemoteOK scraper as the simplest new scraper. This validates the extension pattern end-to-end before tackling the more complex ATS scrapers.

## Files to Create
- `JobSpy/jobspy/remoteok/__init__.py` (replace stub from Task 03)

## Design
Standard `Scraper` subclass (NOT `ATSBoardScraper` — this is a single API call, not a board iterator).

### API
`GET https://remoteok.com/api`
- Returns JSON array
- `item[0]` is a legal notice — skip it
- `items[1:]` are job postings
- All jobs are remote by definition

### Data Mapping
| RemoteOK field | JobPost field | Notes |
|---|---|---|
| `id` | `id` | Prefix as `rok-{id}` |
| `position` | `title` | |
| `company` | `company_name` | |
| `url` (construct) | `job_url` | Build as `https://remoteok.com/remote-jobs/{id}` |
| `apply_url` | `job_url_direct` | |
| `location` | `location` | Often "Worldwide" or "US"; best-effort parse |
| `tags` | _(scan)_ | Scan for job type keywords |
| `description` (HTML) | `description` | Convert HTML to markdown |
| `date` | `date_posted` | |
| `salary_min`, `salary_max` | `compensation` | Treat 0 as None (no data) |
| _(always)_ | `is_remote` | Always `True` |

### Implementation Notes
- Use `filter_jobs()` from util.py for client-side filtering
- Set appropriate User-Agent header
- Handle rate limiting (429) with backoff
- Convert HTML description to markdown (use markdownify or simple regex strip)

## Acceptance Criteria
- `scrape_jobs(site_name="remoteok", search_term="python")` returns a non-empty DataFrame
- All returned jobs have `is_remote=True`
- Job URLs are valid and point to real RemoteOK listings
- `salary_min`/`salary_max` of 0 are converted to `None`, not included as 0
- Filtering by `search_term` and `hours_old` works correctly
- Graceful handling if RemoteOK is unreachable or returns non-200

## Dependencies
- Task 01 (model changes)
- Task 02 (filter_jobs utility)
- Task 03 (registration in SCRAPER_MAPPING)

## Blocked By
- Tasks 01, 02, 03
