# Task 02: Shared Utilities

## Objective
Create the shared base class and utility functions that the ATS scrapers (Greenhouse, Lever, Ashby) and other new scrapers will use.

## Files to Create
- `JobSpy/jobspy/ats_base.py`

## Files to Modify
- `JobSpy/jobspy/util.py`

## Changes

### 1. Create `ATSBoardScraper` base class in `ats_base.py`
Abstract base extending `Scraper` that implements the common pattern: iterate board tokens, fetch JSON API, map to JobPost, client-side filter.

Key design:
- `max_concurrent: int = 10` (overridable per subclass)
- `min_request_interval: float = 0.0` (overridable, e.g. 0.5 for Lever)
- `scrape()` method: gets tokens, fans out with `ThreadPoolExecutor`, collects results, applies `filter_jobs()`, truncates to `results_wanted`
- `_scrape_board(token, scraper_input)`: fetches one board with rate limiting
- Three abstract methods subclasses must implement:
  - `get_tokens(scraper_input) -> list[str]`
  - `fetch_board(token) -> list[dict]`
  - `map_job(raw, token) -> JobPost | None`
- Per-token try/except with logging (skip failures, don't abort the run)

### 2. Add `filter_jobs()` to `util.py`
Client-side filtering function used by all new scrapers:
```python
def filter_jobs(jobs: list[JobPost], scraper_input: ScraperInput) -> list[JobPost]:
```
Filters by:
- `search_term`: case-insensitive match in title or description
- `hours_old`: filter by `date_posted` vs cutoff date
- `is_remote`: only keep jobs where `is_remote=True`

### 3. Add location parsing utility to `util.py`
Helper function(s) to:
- Detect remote keywords ("Remote", "Anywhere", "Worldwide", "Distributed")
- Parse "City, ST" / "City, State" patterns into structured location
- Handle common ATS location formats

### 4. Add `extract_salary()` to `util.py`
Regex-based salary extraction from free-text description/additional fields. Used by Greenhouse (Task 06), Lever (Task 07), and Ashby (Task 08) as a fallback when structured compensation data is unavailable.
```python
def extract_salary(text: str) -> Compensation | None:
```
Should detect patterns like:
- `$120,000 - $160,000`
- `$120k - $160k`
- `120K-160K USD`
- Return a `Compensation` object or `None` if no salary found

### 5. Add HTML-to-markdown conversion utility to `util.py`
All five new scrapers need to convert HTML descriptions to markdown. Add a utility:
```python
def html_to_markdown(html: str) -> str:
```
Use the `markdownify` library (add to dependencies) or a lightweight regex-based approach. Must handle `<a>`, `<p>`, `<ul>/<li>`, `<br>`, and HTML entities.

### Important: `ATSBoardScraper.__init__()` signature
The existing `Scraper` base class accepts `proxies`, `ca_cert`, and `user_agent` parameters. The `ATSBoardScraper` must accept and forward these:
```python
def __init__(self, site: Site, proxies=None, ca_cert=None, user_agent=None):
    super().__init__(site, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)
```
This is required because `scrape_jobs()` in `__init__.py` instantiates scrapers with these keyword arguments.

## Acceptance Criteria
- `ATSBoardScraper` is importable from `jobspy.ats_base`
- `ATSBoardScraper.__init__()` accepts `proxies`, `ca_cert`, `user_agent` and forwards them to `Scraper`
- `filter_jobs()` correctly filters on search_term, hours_old, and is_remote
- `extract_salary()` detects common salary patterns in free text
- `html_to_markdown()` converts HTML to clean markdown
- Location parser handles common formats: "San Francisco, CA", "Remote", "New York, NY / Remote"
- Base class handles token errors gracefully (logs warning, continues to next token)

## Dependencies
- Task 01 (needs `Site`, `ScraperInput`, `JobPost`, `Scraper` types)

## Blocked By
- Task 01
