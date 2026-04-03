# Task 07: Lever Scraper

## Objective
Build the Lever scraper with conservative rate limiting. Expect high token failure rate (~80%) but the API works well for valid tokens.

## Files to Create
- `JobSpy/jobspy/lever/__init__.py` (replace stub from Task 03)
- `JobSpy/jobspy/lever/constant.py` (optional)

## Design
Extends `ATSBoardScraper` from `ats_base.py`.

### API
`GET https://api.lever.co/v0/postings/{company_slug}?mode=json`

### Configuration
- `min_request_interval = 0.5` (rate limit: 10 req/10s/IP)
- `max_concurrent = 2` (conservative given rate limits)
- Expect ~50 valid tokens out of ~251 raw tokens

### Data Mapping
| Lever field | JobPost field | Notes |
|---|---|---|
| `id` | `id` | Prefix as `lever-{id}` |
| `text` | `title` | |
| company name | `company_name` | Derive from slug or first posting |
| `hostedUrl` | `job_url` | |
| `applyUrl` | `job_url_direct` | |
| `categories.location` / `categories.allLocations` | `location` | |
| `categories.commitment` | `job_type` | Map "Permanent" -> FULL_TIME (NOT "Full-time") |
| `categories.team` / `categories.department` | `job_function` | |
| `descriptionBody` (preferred) or `description` (HTML) | `description` | `descriptionBody` is richer; also check `lists` array |
| `createdAt` | `date_posted` | **Epoch milliseconds** — divide by 1000 |
| `additional`/`additionalPlain` text | `compensation` | Use `extract_salary()` — no structured `salaryRange` field |
| `workplaceType` | `is_remote` | "remote" -> True, "hybrid"/"onsite" -> False |
| `country` | `location.country` | 2-letter country code |

### Key Corrections (from practitioner review)
- `salaryRange` field does NOT exist — salary is in `additional` text
- `categories.commitment` values are "Permanent", "Intern", etc. — NOT "Full-time"
- `createdAt` is epoch **milliseconds**, not seconds — must divide by 1000
- `descriptionBody` is richer than `description`; also has `lists` array with structured sections

## Acceptance Criteria
- `scrape_jobs(site_name="lever", lever_company_slugs=["spotify"])` returns jobs
- Rate limiting is respected (no 429 errors in normal operation)
- `createdAt` is correctly converted from epoch ms to date
- `workplaceType` correctly maps to `is_remote`
- Invalid/dead slugs are skipped with warning, not crash
- `board_token` is populated with the company slug

## Dependencies
- Task 01 (model changes)
- Task 02 (ATSBoardScraper, filter_jobs)
- Task 03 (registration)
- Task 04 (token files for full testing)

## Blocked By
- Tasks 01, 02, 03
