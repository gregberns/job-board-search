# Spec 07: Workable ATS Scraper

## 1. Overview

Add Workable as the sixth scraper source. Workable is an ATS platform like Greenhouse, Lever, and Ashby. Companies host job boards at `https://apply.workable.com/{token}/`. The scraper follows the same ATSBoardScraper pattern: token-based, concurrent, error-isolated.

**Scope:** New file `jbs/scrapers/workable.py`, registration wiring, CLI/config integration, token import, test fixture, tests.

## 2. Workable Public API

### 2.1 API Endpoints Discovered

Workable exposes two public API tiers. We use **both** in a two-pass pattern (like Greenhouse):

| Endpoint | Method | Purpose | Auth |
|----------|--------|---------|------|
| `https://apply.workable.com/api/v2/accounts/{token}/jobs` | POST | List all jobs for a board (lightweight, no description) | None |
| `https://apply.workable.com/api/v2/accounts/{token}/jobs/{shortcode}` | GET | Full job detail (description, requirements, benefits HTML) | None |

There is also a v1 widget endpoint (`/api/v1/widget/accounts/{token}`) that returns jobs with metadata but no full description. We use v2 exclusively because it provides richer data and the detail endpoint includes structured HTML sections.

### 2.2 Listing Endpoint (Pass 1)

**Request:**

```
POST https://apply.workable.com/api/v2/accounts/{token}/jobs
Content-Type: application/json
Body: {}
```

An empty JSON object `{}` returns all published jobs. No pagination is needed -- the endpoint returns all jobs for a board in a single response (boards typically have 5-50 jobs).

**Response:**

```json
{
  "total": 7,
  "results": [
    {
      "id": 5692006,
      "shortcode": "66FF2331A3",
      "title": "Analytics Engineer",
      "remote": true,
      "location": {
        "country": "United States",
        "countryCode": "US",
        "city": "",
        "region": null
      },
      "locations": [
        {
          "country": "United States",
          "countryCode": "US",
          "city": "",
          "region": null,
          "hidden": false
        }
      ],
      "state": "published",
      "isInternal": false,
      "code": null,
      "published": "2026-04-03T00:00:00.000Z",
      "type": "full",
      "language": "en",
      "department": ["Analytics Engineering"],
      "accountUid": "55c96070-dc05-4efb-baf3-3a71fbc4e6ee",
      "approvalStatus": "approved",
      "workplace": "remote"
    }
  ]
}
```

**Key listing fields:**

| Field | Type | Notes |
|-------|------|-------|
| `id` | int | Workable internal numeric ID |
| `shortcode` | string | 10-char hex code, used in URLs and detail fetch |
| `title` | string | Job title |
| `remote` | bool | Whether job is remote |
| `location` | object | Primary location: `{country, countryCode, city, region}` |
| `locations` | array | All locations (multi-location jobs have multiple entries) |
| `published` | ISO 8601 | Publication date |
| `type` | string | `"full"`, `"part"`, `"contract"`, or null |
| `department` | array of string | Department names |
| `workplace` | string | `"remote"`, `"on_site"`, `"hybrid"` |
| `state` | string | Always `"published"` for public jobs |
| `isInternal` | bool | Skip internal postings |

### 2.3 Detail Endpoint (Pass 2)

**Request:**

```
GET https://apply.workable.com/api/v2/accounts/{token}/jobs/{shortcode}
```

**Response:** Same fields as listing, plus:

| Field | Type | Notes |
|-------|------|-------|
| `description` | HTML string | Full job description (can be 2000+ chars) |
| `requirements` | HTML string | Requirements/qualifications section |
| `benefits` | HTML string | Benefits/perks section |
| `baseCompensation` | string or null | Free-text salary, e.g. `"$98,000 USD"` (rare) |

### 2.4 Error Behavior

| Scenario | HTTP Status | Response Body |
|----------|-------------|--------------|
| Valid board, has jobs | 200 | `{"total": N, "results": [...]}` |
| Valid board, no jobs | 200 | `{"total": 0, "results": []}` |
| Board does not exist | 404 | `"Not Found"` (plain text) |
| Malformed POST body | 400 | Field-level error JSON |
| Rate limited | 429 | Standard 429 (handled by retry adapter) |

### 2.5 Rate Limiting

No explicit rate limit headers observed. Workable is behind Cloudflare. Conservative approach: 100ms min interval, 5 workers (same ballpark as Greenhouse but slightly more conservative since we have less data on their limits).

### 2.6 Deduplication of Multi-Location Jobs

The v1 widget API returns one row per location for multi-location jobs (same `shortcode` repeated). The v2 listing endpoint deduplicates by returning one entry per job with a `locations` array. No special dedup logic is needed.

## 3. Data Mapping

### 3.1 Job ID

Format: `wk-{shortcode}`

The `shortcode` is a 10-character hex string (e.g. `66FF2331A3`) that uniquely identifies a job across Workable. It is stable, appears in URLs, and is used for the detail endpoint. Using it instead of the numeric `id` because it is the canonical public identifier.

**PluginMeta:** `PluginMeta(name="workable", id_prefix="wk", requires_tokens=True)`

### 3.2 Field Mapping

| Job field | Workable source (listing) | Workable source (detail) |
|-----------|--------------------------|-------------------------|
| `id` | `f"wk-{shortcode}"` | -- |
| `source` | `"workable"` | -- |
| `title` | `title` | -- |
| `company` | `company_name` (from board-level, see 3.3) | -- |
| `url` | `f"https://apply.workable.com/{token}/j/{shortcode}/"` | -- |
| `url_direct` | `f"https://apply.workable.com/{token}/j/{shortcode}/apply/"` | -- |
| `location` | See section 3.4 | -- |
| `description` | -- | `description + requirements + benefits` (HTML -> markdown) |
| `date_posted` | `published` (ISO 8601 -> date) | -- |
| `job_type` | `type` mapped (see 3.5) | -- |
| `job_function` | `department` (joined with ", ") | -- |
| `compensation` | -- | Extract from `benefits` HTML via `extract_salary_from_text` |
| `is_remote` | `remote` bool or `workplace == "remote"` | -- |
| `board_token` | token slug | -- |

### 3.3 Company Name

The v2 listing endpoint does not include a company name field. We get it from the v1 widget endpoint, which we call once per board:

```
GET https://apply.workable.com/api/v1/widget/accounts/{token}
```

This returns `{"name": "Company Name", "description": "...", "jobs": [...]}`. We extract only the `name` field. This request also serves as the board-exists check (404 for nonexistent boards).

**Fallback:** If the widget request fails (non-404), derive from token slug: `token.replace("-", " ").title()`

**Why both v1 and v2:** The v2 POST listing provides richer per-job data (`locations` array, `workplace` field, `type` field) that v1 lacks. The v1 widget provides the company name that v2 lacks. One extra GET per board is negligible overhead.

### 3.4 Location

Primary location from listing response:

```python
location = Location(
    city=raw_location.get("city") or None,
    state=raw_location.get("region") or None,
    country=raw_location.get("country") or None,
    raw=_build_location_raw(raw_location),
    work_arrangement=WorkArrangement.REMOTE if is_remote else WorkArrangement.UNKNOWN,
)
```

Build `raw` string from components: `"{city}, {region}, {country}"` (omitting empty parts).

If `locations` array has multiple entries, use the first non-hidden location as primary. The `raw` field should include all locations for searchability.

### 3.5 Employment Type Mapping

| Workable `type` | Job `job_type` |
|-----------------|----------------|
| `"full"` | `"full-time"` |
| `"part"` | `"part-time"` |
| `"contract"` | `"contract"` |
| `"temporary"` | `"contract"` |
| `"internship"` | `"intern"` |
| null / missing | `None` |

### 3.6 Remote Detection

A job is remote if any of:
- `remote` field is `true`
- `workplace` field is `"remote"`

Hybrid detection:
- `workplace` field is `"hybrid"` -> `WorkArrangement.HYBRID`

### 3.7 Compensation

Workable does not have structured compensation fields in the public API. The `baseCompensation` field exists in the detail response but is rare and free-text.

Strategy (same as Greenhouse):
1. If `baseCompensation` is present, pass it to `extract_salary_from_text()`
2. Fall back to `extract_salary_from_text()` on the combined description + requirements + benefits text

### 3.8 Description Assembly

Combine three HTML sections from the detail response into one markdown description:

```python
parts = []
if description_html:
    parts.append(html_to_markdown(description_html))
if requirements_html:
    parts.append("## Requirements\n" + html_to_markdown(requirements_html))
if benefits_html:
    parts.append("## Benefits\n" + html_to_markdown(benefits_html))
description = "\n\n".join(parts) if parts else None
```

## 4. Implementation

### 4.1 New File: `jbs/scrapers/workable.py`

```python
"""Workable ATS scraper — two-pass fetch (listing then detail)."""

from __future__ import annotations

import logging
import time
from datetime import date, datetime

from jbs.models import Compensation, Job, Location, WorkArrangement
from jbs.scrapers import register
from jbs.scrapers.ats_base import ATSBoardScraper, BoardNotFoundError
from jbs.scrapers.base import PluginMeta, ScrapeContext
from jbs.util import create_session, extract_salary_from_text, html_to_markdown

logger = logging.getLogger(__name__)

LIST_URL = "https://apply.workable.com/api/v2/accounts/{token}/jobs"
DETAIL_URL = "https://apply.workable.com/api/v2/accounts/{token}/jobs/{shortcode}"
WIDGET_URL = "https://apply.workable.com/api/v1/widget/accounts/{token}"
```

### 4.2 Class Definition

```python
@register
class WorkableScraper(ATSBoardScraper):
    meta = PluginMeta(name="workable", id_prefix="wk", requires_tokens=True)
    max_workers = 5
    min_interval = 0.1  # 100ms between requests

    def __init__(self):
        self.session = create_session()

    def fetch_and_map(self, token: str, ctx: ScrapeContext) -> list[Job]:
        """Two-pass: list jobs via v2 POST, fetch details via v2 GET."""
        ...
```

### 4.3 fetch_and_map Algorithm

```
1. POST to v2 listing endpoint with empty body {}
   - 404 -> raise BoardNotFoundError
   - 429/403 -> log warning, return []
   - Other error -> log warning, return []

2. Parse response: total, results[]
   - If results is empty, return []

3. Get company name:
   - GET v1 widget endpoint -> extract "name" field
   - Fallback: token.replace("-", " ").title()

4. For each job in results:
   a. Skip if isInternal is true
   b. Pre-filter on ctx.search_term (title match) and ctx.hours_old (published date)
   c. Sleep min_interval
   d. GET v2 detail endpoint for shortcode
      - If detail fetch fails, map from listing data (no description)
   e. Map to Job dataclass

5. Return list[Job]
```

### 4.4 Key Implementation Details

**Two-pass justification:** The listing endpoint does not include `description`, `requirements`, or `benefits`. These are only available from the detail endpoint. This mirrors Greenhouse's two-pass pattern where the listing is lightweight and the detail provides the full content.

**Pre-filter before detail fetch:** Like Greenhouse, filter on title and date before making detail requests. This avoids unnecessary HTTP calls for jobs that will be filtered out anyway.

**Internal jobs:** Skip jobs where `isInternal` is `true`. These are not publicly accessible.

**Error isolation per job:** If a detail fetch fails for one job, fall back to mapping from listing data (the job will lack a description but still be usable). Do not fail the entire board.

### 4.5 Helper Functions

```python
_TYPE_MAP = {
    "full": "full-time",
    "part": "part-time",
    "contract": "contract",
    "temporary": "contract",
    "internship": "intern",
}

def _parse_date(date_str: str | None) -> date | None:
    """Parse ISO 8601 date string to date object."""
    ...

def _build_location_raw(loc: dict) -> str | None:
    """Build location string from {city, region, country} dict."""
    parts = [loc.get("city"), loc.get("region"), loc.get("country")]
    raw = ", ".join(p for p in parts if p)
    return raw or None

def _map_job(
    listing: dict,
    detail: dict | None,
    token: str,
    company_name: str,
) -> Job | None:
    """Map Workable listing + optional detail to Job model."""
    ...
```

The `_map_job` function takes both the listing data and the optional detail data. If detail is None (fetch failed), it maps what it can from the listing.

## 5. Integration Points

### 5.1 Scraper Registration

Add import to `jbs/scrapers/__init__.py`:

```python
from jbs.scrapers import greenhouse, lever, ashby, remoteok, hn, workable  # noqa
```

### 5.2 Config: Default Sources

Add `"workable"` to `default_sources` in `jbs/config.py`:

```python
default_sources: list[str] = field(default_factory=lambda:
    ["greenhouse", "lever", "ashby", "workable", "remoteok", "hn"])
```

### 5.3 Orchestrator: Token Loading

Add `"workable"` to the ATS source set in `jbs/orchestrator.py` `_build_context()`:

```python
if source in ("greenhouse", "lever", "ashby", "workable"):
    tokens = self.store.get_tokens(source)
```

### 5.4 CLI: Token Import (`jbs init`)

Add workable to the `token_files` list in `jbs/cli.py`:

```python
token_files = [
    ("greenhouse", "tokens/greenhouse.txt", "tokens/greenhouse_raw.txt"),
    ("lever", "tokens/lever.txt", "tokens/lever_raw.txt"),
    ("ashby", "tokens/ashby.txt", None),
    ("workable", "tokens/workable.txt", None),
]
```

### 5.5 CLI: Token Validation

Add workable to the `ats_sources` set in the `scrape` command:

```python
ats_sources = {"greenhouse", "lever", "ashby", "workable"}
```

Add workable to the `tokens add` command choices:

```python
@click.argument("platform", type=click.Choice(["greenhouse", "lever", "ashby", "workable"]))
```

Add workable to the `tokens validate` command:

```python
platforms = [platform] if platform else ["greenhouse", "lever", "ashby", "workable"]
```

And the platform choice:

```python
@click.option("--platform", type=click.Choice(["greenhouse", "lever", "ashby", "workable"]), default=None)
```

Add workable to `_token_check_url()`:

```python
elif platform == "workable":
    return f"https://apply.workable.com/api/v1/widget/accounts/{token}"
```

The v1 widget endpoint returns 200 for valid boards and 404 for nonexistent ones -- ideal for validation.

### 5.6 CLI: Blocklist Import

Add workable to the blocklist import loop in `jbs init`:

```python
for platform in ("greenhouse", "lever", "ashby", "workable"):
```

## 6. Token File

The file `tokens/workable.txt` already exists with 29 curated tokens. No changes needed.

## 7. Test Plan

### 7.1 Test Fixture

Create `tests/fixtures/workable_listing.json`:

```json
{
  "total": 3,
  "results": [
    {
      "id": 5001,
      "shortcode": "ABC1234567",
      "title": "Senior Backend Engineer",
      "remote": false,
      "location": {"country": "United States", "countryCode": "US", "city": "San Francisco", "region": "California"},
      "locations": [{"country": "United States", "countryCode": "US", "city": "San Francisco", "region": "California", "hidden": false}],
      "state": "published",
      "isInternal": false,
      "code": null,
      "published": "2026-04-01T00:00:00.000Z",
      "type": "full",
      "language": "en",
      "department": ["Engineering"],
      "accountUid": "test-uid",
      "approvalStatus": "approved",
      "workplace": "on_site"
    },
    {
      "id": 5002,
      "shortcode": "DEF7654321",
      "title": "Product Designer",
      "remote": true,
      "location": {"country": "United States", "countryCode": "US", "city": "", "region": null},
      "locations": [{"country": "United States", "countryCode": "US", "city": "", "region": null, "hidden": false}],
      "state": "published",
      "isInternal": false,
      "code": null,
      "published": "2026-04-05T00:00:00.000Z",
      "type": "part",
      "language": "en",
      "department": ["Design", "Product"],
      "accountUid": "test-uid",
      "approvalStatus": "approved",
      "workplace": "remote"
    },
    {
      "id": 5003,
      "shortcode": "GHI1112222",
      "title": "Engineering Intern",
      "remote": false,
      "location": {"country": "United Kingdom", "countryCode": "GB", "city": "London", "region": "England"},
      "locations": [{"country": "United Kingdom", "countryCode": "GB", "city": "London", "region": "England", "hidden": false}],
      "state": "published",
      "isInternal": false,
      "code": null,
      "published": "2026-03-15T00:00:00.000Z",
      "type": "internship",
      "language": "en",
      "department": ["Engineering"],
      "accountUid": "test-uid",
      "approvalStatus": "approved",
      "workplace": "on_site"
    }
  ]
}
```

Create `tests/fixtures/workable_detail.json`:

```json
{
  "id": 5001,
  "shortcode": "ABC1234567",
  "title": "Senior Backend Engineer",
  "remote": false,
  "location": {"country": "United States", "countryCode": "US", "city": "San Francisco", "region": "California"},
  "locations": [{"country": "United States", "countryCode": "US", "city": "San Francisco", "region": "California", "hidden": false}],
  "state": "published",
  "isInternal": false,
  "code": null,
  "published": "2026-04-01T00:00:00.000Z",
  "type": "full",
  "language": "en",
  "department": ["Engineering"],
  "accountUid": "test-uid",
  "approvalStatus": "approved",
  "workplace": "on_site",
  "description": "<p>We are looking for a <strong>Senior Backend Engineer</strong> to join our platform team.</p>",
  "requirements": "<ul><li>5+ years Python experience</li><li>Distributed systems knowledge</li></ul>",
  "benefits": "<ul><li>Competitive salary: $180,000 - $240,000</li><li>Equity package</li><li>Unlimited PTO</li></ul>"
}
```

Create `tests/fixtures/workable_widget.json`:

```json
{
  "name": "Acme Corp",
  "description": "Acme Corp builds developer tools.",
  "jobs": []
}
```

### 7.2 Test File: `tests/test_workable.py`

Test classes following the Ashby test pattern:

**TestFetchAndMap:**
- `test_normal_fetch_returns_jobs` -- mock v2 POST + detail GETs, assert Job list
- `test_404_raises_board_not_found` -- mock 404 from listing, assert BoardNotFoundError
- `test_429_returns_empty` -- mock 429, assert empty list
- `test_request_exception_returns_empty` -- mock ConnectionError, assert empty list
- `test_detail_failure_falls_back_to_listing` -- mock listing OK, detail 500, assert jobs still returned (without description)
- `test_internal_jobs_skipped` -- mock job with `isInternal: true`, assert not in results

**TestIDPrefix:**
- `test_id_prefix_is_wk` -- all IDs start with `wk-`
- `test_id_contains_shortcode` -- ID is `wk-{shortcode}`

**TestCompensation:**
- `test_salary_from_benefits_html` -- extract salary from benefits section
- `test_no_salary_returns_none` -- description/benefits without salary

**TestLocation:**
- `test_onsite_location_parsed` -- city, region, country extracted
- `test_remote_detected` -- `remote: true` and `workplace: "remote"`
- `test_hybrid_detected` -- `workplace: "hybrid"` -> WorkArrangement.HYBRID
- `test_empty_location_fields` -- empty city/region handled gracefully

**TestJobType:**
- `test_full_time` -- `type: "full"` -> `"full-time"`
- `test_part_time` -- `type: "part"` -> `"part-time"`
- `test_internship` -- `type: "internship"` -> `"intern"`
- `test_null_type` -- null -> None

**TestJobFunction:**
- `test_single_department` -- `["Engineering"]` -> `"Engineering"`
- `test_multiple_departments` -- `["Design", "Product"]` -> `"Design, Product"`

**TestDescription:**
- `test_combined_description` -- description + requirements + benefits assembled correctly
- `test_html_to_markdown_conversion` -- HTML tags converted properly

**TestCompanyName:**
- `test_company_from_widget` -- uses v1 widget `name` field
- `test_fallback_from_token` -- derives from token slug when widget fails

**TestBoardToken:**
- `test_board_token_set` -- all jobs have `board_token == token`

**TestMeta:**
- `test_meta_name` -- `"workable"`
- `test_meta_id_prefix` -- `"wk"`
- `test_meta_requires_tokens` -- `True`
- `test_registered` -- `"workable" in available_scrapers()`

### 7.3 Edge Cases

- **Empty board:** v2 POST returns `{"total": 0, "results": []}` -- should return empty list, no error
- **Multi-location job:** Single shortcode with multiple locations in the `locations` array -- should produce one Job with primary location
- **Missing fields:** `type`, `department`, `code` can all be null -- handle gracefully
- **HTML entities in description:** Standard HTML (handled by `html_to_markdown`)
- **Zero-length token list:** ATSBoardScraper base handles this (returns empty ScrapeResult)

## 8. File Changes Summary

| File | Change |
|------|--------|
| `jbs/scrapers/workable.py` | **NEW** -- WorkableScraper class, _map_job, helpers |
| `jbs/scrapers/__init__.py` | Add `workable` to import list |
| `jbs/config.py` | Add `"workable"` to `default_sources` |
| `jbs/orchestrator.py` | Add `"workable"` to ATS source set in `_build_context()` |
| `jbs/cli.py` | Add workable to `token_files`, `ats_sources`, `tokens add` choices, `tokens validate` choices + platforms, `_token_check_url()`, blocklist loop |
| `tests/fixtures/workable_listing.json` | **NEW** -- listing response fixture |
| `tests/fixtures/workable_detail.json` | **NEW** -- detail response fixture |
| `tests/fixtures/workable_widget.json` | **NEW** -- widget response fixture |
| `tests/test_workable.py` | **NEW** -- unit tests |

## 9. Implementation Order

1. **Create fixture files** -- `tests/fixtures/workable_*.json`
2. **Write `jbs/scrapers/workable.py`** -- the scraper implementation
3. **Wire registration** -- add import to `jbs/scrapers/__init__.py`
4. **Wire orchestrator** -- add `"workable"` to ATS set in `_build_context()`
5. **Wire CLI** -- all integration points in `jbs/cli.py`
6. **Wire config** -- add to `default_sources` in `jbs/config.py`
7. **Write tests** -- `tests/test_workable.py`
8. **Run tests** -- `python -m pytest tests/test_workable.py -v`
9. **Smoke test** -- `jbs init && jbs scrape --sources workable`

## 10. Non-Goals

- **Pagination:** Workable boards return all jobs in one response. No pagination needed.
- **Search/filter params in API:** The v2 POST endpoint accepts filter params (`location`, `department`, `remote` as arrays) but we do not use them -- we fetch everything and filter client-side, consistent with other scrapers.
- **Global jobs.workable.com API:** There is a global job search API at `https://jobs.workable.com/api/v1/jobs` that aggregates across all Workable customers. We do not use this. Our model is token-per-company, consistent with the other ATS scrapers.
- **Workable API key authentication:** Workable has a paid API for employers. We use only the public board API (no auth required).
