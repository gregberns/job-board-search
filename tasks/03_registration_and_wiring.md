# Task 03: Registration and Wiring

## Objective
Register the five new scrapers in the JobSpy framework so they can be invoked through `scrape_jobs()`. Use stub/placeholder scraper classes initially — the real implementations come in later tasks.

## Files to Modify
- `JobSpy/jobspy/__init__.py`

## Files to Create (stubs, replaced in later tasks)
- `JobSpy/jobspy/greenhouse/__init__.py`
- `JobSpy/jobspy/lever/__init__.py`
- `JobSpy/jobspy/ashby/__init__.py`
- `JobSpy/jobspy/remoteok/__init__.py`
- `JobSpy/jobspy/hn/__init__.py`

## Changes

### 1. Create stub scraper modules
Each stub should define a class extending `Scraper` with a `scrape()` method that returns an empty `JobResponse`. This allows wiring to be tested before implementations exist.

**Important:** Stubs must match the existing scraper `__init__` signature. The `scrape_jobs()` function instantiates scrapers with `proxies`, `ca_cert`, and `user_agent` keyword arguments. Stubs that don't accept these will crash at instantiation.

Example stub:
```python
from jobspy.model import Scraper, ScraperInput, JobResponse, Site

class GreenhouseScraper(Scraper):
    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.GREENHOUSE, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        return JobResponse(jobs=[])
```

### 2. Update `__init__.py`
- Add imports for all five new scraper classes
- Add entries to `SCRAPER_MAPPING`:
  ```python
  Site.GREENHOUSE: GreenhouseScraper,
  Site.LEVER: LeverScraper,
  Site.ASHBY: AshbyScraper,
  Site.REMOTEOK: RemoteOKScraper,
  Site.HN: HNScraper,
  ```
- Wire the new `ScraperInput` fields through `scrape_jobs()`: add `greenhouse_board_tokens`, `lever_company_slugs`, `ashby_board_names`, `hn_thread_id` as **explicit named parameters** to `scrape_jobs()` and pass them directly to the `ScraperInput()` constructor. Do NOT rely on `**kwargs` — the existing code does not forward kwargs to ScraperInput.
- ATS scrapers receiving `None` for their token list must return empty `JobResponse` immediately — this makes them safe to include in default `list(Site)` behavior

### 3. Verify safe defaults
Calling `scrape_jobs(site_name="greenhouse")` without tokens must not crash — it should return an empty DataFrame.

## Acceptance Criteria
- `scrape_jobs(site_name="greenhouse")` returns empty DataFrame (no crash)
- `scrape_jobs(site_name=["greenhouse", "remoteok", "hn"])` works
- All five new Site values are in `SCRAPER_MAPPING`
- New `ScraperInput` fields are passed through from `scrape_jobs()` explicit parameters
- Existing scrapers (indeed, linkedin, etc.) are unaffected

## Dependencies
- Task 01 (Site enum, ScraperInput fields)
- Task 02 (ATSBoardScraper base class — needed for non-stub implementations, but stubs don't use it)

## Blocked By
- Task 01
