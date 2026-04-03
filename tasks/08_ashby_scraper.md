# Task 08: Ashby Scraper

## Objective
Build the Ashby scraper. Ashby has the best structured compensation data among the ATS platforms but requires JSON sanitization due to control characters.

## Files to Create
- `JobSpy/jobspy/ashby/__init__.py` (replace stub from Task 03)
- `JobSpy/jobspy/ashby/constant.py` (optional)

## Design
Extends `ATSBoardScraper` from `ats_base.py`.

### API
`GET https://api.ashbyhq.com/posting-api/job-board/{board_name}?includeCompensation=true`

### Configuration
- `max_concurrent = 10`
- Starts with small token list (~20-30 manually curated from Task 04)

### JSON Sanitization (critical)
Response JSON may contain control characters. Before `json.loads()`:
```python
raw_text = re.sub(r'[\x00-\x1f\x7f]', ' ', raw_text)
```

### Data Mapping
| Ashby field | JobPost field | Notes |
|---|---|---|
| `id` | `id` | Prefix as `ashby-{id}` |
| `title` | `title` | |
| company name | `company_name` | From board context or response |
| `jobUrl` | `job_url` | |
| `applyUrl` | `job_url_direct` | |
| `location` / `secondaryLocations` | `location` | |
| `department` / `team` | `job_function` | |
| `employmentType` | `job_type` | |
| `descriptionHtml` or `descriptionPlain` | `description` | |
| `publishedAt` | `date_posted` | |
| `compensationTiers[].components[]` | `compensation` | Extract `minValue`, `maxValue`, `currencyCode`, `interval` |
| `scrapeableCompensationSalarySummary` | _(fallback)_ | Fallback for compensation parsing |
| `isRemote` / `workplaceType` | `is_remote` | |

### Compensation Parsing
Ashby provides excellent structured compensation when available:
```python
# From compensationTiers[].components[]:
# minValue, maxValue, currencyCode, interval
# Build Compensation object directly (no regex needed)
```
Fall back to `scrapeableCompensationSalarySummary` text if structured data is empty.

## Acceptance Criteria
- `scrape_jobs(site_name="ashby", ashby_board_names=["linear", "ramp"])` returns jobs
- JSON with control characters is handled without crashing
- Structured compensation data is correctly parsed when present
- Falls back to text-based compensation parsing when structured data is empty
- Invalid board names are skipped with warning
- `board_token` is populated with the board name

## Dependencies
- Task 01 (model changes)
- Task 02 (ATSBoardScraper, filter_jobs)
- Task 03 (registration)
- Task 04 (ashby.txt token file)

## Blocked By
- Tasks 01, 02, 03
