# Task 06: Greenhouse Scraper

## Objective
Build the Greenhouse scraper using the two-pass fetch strategy to keep bandwidth manageable across hundreds of boards.

## Files to Create
- `JobSpy/jobspy/greenhouse/__init__.py` (replace stub from Task 03)
- `JobSpy/jobspy/greenhouse/constant.py` (optional, for any constants)

## Design
Extends `ATSBoardScraper` from `ats_base.py`.

### API
- List jobs: `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs`
- Single job: `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}?questions=true`

### Two-Pass Strategy (critical for performance)
1. **First pass:** Fetch all boards WITHOUT `content=true` (~100KB/board, ~200ms/board)
   - Gets titles, locations, dates — enough for filtering
2. **Client-side filter** by `search_term` and `hours_old` on lightweight data
3. **Second pass:** Fetch full job details only for matching jobs via individual job endpoint with `questions=true`
   - This turns a potential 2-4GB download into ~200MB

### Configuration
- `max_concurrent = 20` (no rate limits observed at this level)
- Per-token try/except: log and skip 404s (expect 30-50% failure rate from stale tokens)
- Exponential backoff on 429/403
- Circuit breaker: stop after 10 consecutive failures per run

### Data Mapping
| Greenhouse field | JobPost field | Notes |
|---|---|---|
| `id` | `id` | Prefix as `gh-{id}` |
| `title` | `title` | |
| `company_name` | `company_name` | Exists directly in response (not derived from token) |
| `absolute_url` | `job_url` | |
| `location.name` | `location` | Parse city/state; detect "Remote" |
| `offices[].name` + `offices[].location` | _(fallback)_ | Enriched location if `location.name` is vague |
| `content` (HTML, 2nd pass) | `description` | Convert to markdown |
| `first_published` | `date_posted` | NOT `updated_at` — use actual posting date |
| `departments[].name` | `job_function` | |
| description text | `compensation` | Use `extract_salary()` on text — no structured comp in public API |
| board token | `board_token` | For traceability |

### Key Corrections (from practitioner review)
- `company_name` is in the API response directly — do NOT derive from token
- Use `first_published` for `date_posted`, NOT `updated_at`
- No structured compensation in public API — parse from description text
- `metadata` contains internal fields only, not useful for us

## Acceptance Criteria
- `scrape_jobs(site_name="greenhouse", greenhouse_board_tokens=["stripe", "discord"])` returns jobs
- Two-pass strategy measurably reduces data transfer (log byte counts)
- Stale/invalid tokens are skipped with a warning, not a crash
- `board_token` is populated on all returned jobs
- `date_posted` uses `first_published`, not `updated_at`
- Works with the validated token list from Task 04

## Dependencies
- Task 01 (model changes)
- Task 02 (ATSBoardScraper, filter_jobs)
- Task 03 (registration)
- Task 04 (token files for testing)

## Blocked By
- Tasks 01, 02, 03 (Task 04 needed for full testing but can test with a few hardcoded tokens)
