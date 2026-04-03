# Implementation Plan: Extend JobSpy for SMB Job Collection

## Goal
Extend the JobSpy framework with new scrapers targeting sources where small-to-medium businesses actually post jobs. Skip the giant job boards (Indeed, LinkedIn, etc.) that are anti-bot heavy and large-company dominated. Output JSONL files for easy downstream filtering/querying.

---

## Architecture Decisions (informed by review)

### A1. Shared `ATSBoardScraper` base class for Greenhouse/Lever/Ashby

All three ATS scrapers follow the same algorithm: iterate board tokens → fetch JSON API → map to JobPost → client-side filter. Rather than duplicating this across three scrapers, we create a shared base:

```python
class ATSBoardScraper(Scraper):
    """Base for scrapers that enumerate company boards and fetch all jobs."""

    max_concurrent: int = 10          # overridable per subclass
    min_request_interval: float = 0.0 # overridable (e.g., 0.5 for Lever)

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        tokens = self.get_tokens(scraper_input)
        if not tokens:
            log.info(f"{self.site.value}: no board tokens provided, skipping")
            return JobResponse(jobs=[])

        # Parallel fetch across tokens with bounded concurrency
        results = []
        with ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
            futures = {executor.submit(self._scrape_board, t, scraper_input): t for t in tokens}
            for future in as_completed(futures):
                token = futures[future]
                try:
                    jobs = future.result()
                    results.extend(jobs)
                except Exception as e:
                    log.warning(f"{self.site.value}: board '{token}' failed: {e}")

        # Client-side filtering (shared across all ATS scrapers)
        filtered = filter_jobs(results, scraper_input)
        return JobResponse(jobs=filtered[:scraper_input.results_wanted])

    def _scrape_board(self, token: str, scraper_input: ScraperInput) -> list[JobPost]:
        """Fetch and map jobs from one board. Handles per-token errors."""
        time.sleep(self.min_request_interval)  # rate limiting
        raw_jobs = self.fetch_board(token)
        return [self.map_job(raw, token) for raw in raw_jobs if raw]

    @abstractmethod
    def get_tokens(self, scraper_input: ScraperInput) -> list[str]: ...

    @abstractmethod
    def fetch_board(self, token: str) -> list[dict]: ...

    @abstractmethod
    def map_job(self, raw: dict, token: str) -> JobPost | None: ...
```

Each concrete ATS scraper only implements `get_tokens()`, `fetch_board()`, and `map_job()`.

### A2. ATS config stays in ScraperInput (pragmatic choice)

The architect review (I1/I4) suggested a separate `ATSSourceConfig` or grouped config object. While architecturally cleaner, this would require refactoring the existing `scrape_jobs()` calling convention and all downstream code. Since this is a personal tool (not a library), we keep it simple: add `greenhouse_board_tokens`, `lever_company_slugs`, `ashby_board_names` to `ScraperInput`, and pass them through `scrape_jobs()` kwargs. The `**kwargs` on `scrape_jobs()` already exists — we'll use it.

If the API stabilizes and we want to upstream, we refactor then.

### A3. Shared `filter_jobs()` utility

All new scrapers (ATS + RemoteOK + HN) need client-side filtering since they fetch all jobs then filter, unlike existing scrapers that use server-side search. Create a shared utility:

```python
def filter_jobs(jobs: list[JobPost], scraper_input: ScraperInput) -> list[JobPost]:
    """Apply search_term, hours_old, is_remote, and location filters client-side."""
    filtered = jobs
    if scraper_input.search_term:
        term = scraper_input.search_term.lower()
        filtered = [j for j in filtered if term in (j.title or "").lower()
                     or term in (j.description or "").lower()]
    if scraper_input.hours_old:
        cutoff = date.today() - timedelta(hours=scraper_input.hours_old)
        filtered = [j for j in filtered if j.date_posted and j.date_posted >= cutoff.date()]
    if scraper_input.is_remote:
        filtered = [j for j in filtered if j.is_remote]
    return filtered
```

### A4. Incremental JSONL writes (resume-from-failure)

Instead of accumulating all jobs in memory and writing once at the end, the runner script writes JSONL incrementally after each source completes. If the process crashes at Lever, Greenhouse results are already on disk.

### A5. Two-pass Greenhouse fetching (bandwidth optimization)

Practitioner review (P12) showed that `content=true` multiplies response size 10-20x. Strategy:
1. First pass: fetch all boards WITHOUT `content=true` (~200ms/board, ~100KB/board) — get titles, locations, dates
2. Client-side filter by `search_term` and `hours_old` on the lightweight data
3. Second pass: fetch full descriptions only for matching jobs via `GET /v1/boards/{token}/jobs/{job_id}` with `questions=true`

This turns a 2-4GB download into ~200MB.

### A6. Single `ScraperException` replaces per-site exception classes

```python
class ScraperException(Exception):
    def __init__(self, site: Site, message: str, *, status_code: int | None = None, token: str | None = None):
        self.site = site
        self.status_code = status_code
        self.token = token
        super().__init__(f"[{site.value}] {message}")
```

### A7. New `board_token` field on JobPost

Add `board_token: str | None = None` to `JobPost` to trace which company board a job came from. Essential for debugging stale tokens and for grouping jobs by company.

---

## Phase 1: Foundation (Model & Registration)

### 1.1 Extend `Site` enum (`jobspy/model.py`)

```python
class Site(Enum):
    # existing...
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    REMOTEOK = "remoteok"
    HN = "hn"
```

### 1.2 Extend `ScraperInput` (`jobspy/model.py`)

```python
class ScraperInput(BaseModel):
    # existing fields...

    # ATS board tokens
    greenhouse_board_tokens: list[str] | None = None
    lever_company_slugs: list[str] | None = None
    ashby_board_names: list[str] | None = None

    # HN Who's Hiring
    hn_thread_id: str | None = None
```

### 1.3 Add `board_token` to `JobPost` (`jobspy/model.py`)

```python
class JobPost(BaseModel):
    # existing fields...
    board_token: str | None = None  # ATS board token/slug this job came from
```

### 1.4 Replace per-site exceptions with `ScraperException` (`jobspy/exception.py`)

Add the unified `ScraperException` class (see A6). Keep existing per-site exceptions for backward compat but don't add new ones.

### 1.5 Update `desired_order` (`jobspy/util.py`)

Add `board_token` to the column list.

### 1.6 Register scrapers (`jobspy/__init__.py`)

- Add imports for new scraper classes
- Add entries to `SCRAPER_MAPPING`
- Wire new `ScraperInput` fields through `scrape_jobs()` → pass via `**kwargs`
- **Critical:** ATS scrapers that receive `None` for their token list return empty `JobResponse` immediately — safe to include in default `list(Site)` behavior

### 1.7 Create shared utilities

- `filter_jobs()` in `jobspy/util.py` (see A3)
- `ATSBoardScraper` base class in `jobspy/model.py` or new `jobspy/ats_base.py`
- Location parsing utility: detect remote keywords, parse "City, ST" patterns

---

## Phase 2: Token Bootstrapping & Validation

**This must happen BEFORE building ATS scrapers** (you can't test without tokens).

### 2.1 Parse awesome-easy-apply

The source repo has a `README.md` with markdown table rows containing URLs like `boards.greenhouse.io/companyname` and `jobs.lever.co/companyname`. Write a script `scripts/bootstrap_tokens.py` that:
1. Fetches the raw README.md from GitHub
2. Extracts Greenhouse tokens from `boards.greenhouse.io/{token}` URLs (expect ~540)
3. Extracts Lever slugs from `jobs.lever.co/{slug}` URLs (expect ~251)
4. Writes to `tokens/greenhouse_raw.txt` and `tokens/lever_raw.txt`

### 2.2 Validate tokens

Script `scripts/validate_tokens.py`:
1. For each token, make a lightweight GET request (no `content=true`)
2. Record HTTP status (200=valid, 404=dead, 429=rate-limited)
3. Write valid tokens to `tokens/greenhouse.txt` and `tokens/lever.txt`
4. Log stats: "Greenhouse: 340/540 valid (63%)"

Based on practitioner testing:
- **Greenhouse:** expect 50-70% validity → ~270-380 valid tokens
- **Lever:** expect only ~20% validity → ~50 valid tokens (Lever has high attrition)

### 2.3 Ashby tokens — manual curation

The awesome-easy-apply repo has **zero** Ashby tokens. We'll manually curate a starter list from known Ashby companies (linear, ramp, notion, etc.) and Common Crawl results. Start small (~20-30 tokens), expand later.

Write to `tokens/ashby.txt`.

---

## Phase 3: Scrapers (in order of value and complexity)

### 3.1 RemoteOK Scraper (`jobspy/remoteok/__init__.py`)

**Why first:** Simplest possible scraper. Validates that our extension pattern works end-to-end before tackling the ATS base class.

**API:** `GET https://remoteok.com/api`

**Design:**
- Single GET returns JSON array; item[0] is a legal notice (skip it), items[1:] are jobs
- Client-side filtering via shared `filter_jobs()`
- All jobs are remote by definition → `is_remote=True`
- `salary_min`/`salary_max` of 0 means "no data" (treat as None)
- Standard `Scraper` subclass (not `ATSBoardScraper`)

**Data mapping (verified against live API):**
| RemoteOK field | JobPost field |
|---|---|
| `id` | `id` (prefixed `rok-{id}`) |
| `position` | `title` |
| `company` | `company_name` |
| `url` (construct: `https://remoteok.com/remote-jobs/{id}`) | `job_url` |
| `apply_url` | `job_url_direct` |
| `location` | `location` (best-effort parse; often "Worldwide" or "US") |
| `tags` | scan for job type keywords |
| `description` (HTML) | `description` (convert to markdown) |
| `date` | `date_posted` |
| `salary_min`, `salary_max` (ignore if 0) | `compensation` |
| always `True` | `is_remote` |

### 3.2 Greenhouse Scraper (`jobspy/greenhouse/`)

**API:** `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs`

**Design (two-pass, per A5):**
1. Extends `ATSBoardScraper`
2. `get_tokens()` reads from `scraper_input.greenhouse_board_tokens`
3. `fetch_board(token)` — first pass: GET without `content=true` (lightweight)
4. Client-side filter by title/location/hours_old
5. For matching jobs, fetch full content via individual job endpoint
6. `max_concurrent = 20` (practitioner confirmed no rate limits at this level)
7. Per-token try/except: log and skip 404s (expect 30-50% failure rate from stale tokens)

**Data mapping (verified against live API — Discord, Stripe, Cloudflare):**
| Greenhouse field | JobPost field |
|---|---|
| `id` | `id` (prefixed `gh-{id}`) |
| `title` | `title` |
| `company_name` (exists directly in response!) | `company_name` |
| `absolute_url` | `job_url` |
| `location.name` | `location` (parse city/state; detect "Remote") |
| `offices[].name` + `offices[].location` | enriched location data (fallback) |
| `content` (HTML, from 2nd pass) | `description` (convert to markdown) |
| **`first_published`** (NOT `updated_at`) | `date_posted` |
| `departments[].name` | `job_function` |
| `description` text → `extract_salary()` | `compensation` (no structured comp in public API) |
| board token | `board_token` |

**Key corrections from review:**
- ~~`company name from board token context`~~ → `company_name` is in the response directly (P4)
- ~~`updated_at` → `date_posted`~~ → use `first_published` for actual posting date (P10)
- ~~`metadata` for compensation~~ → metadata has internal fields only, not compensation. Use `extract_salary()` on description text (P5)

### 3.3 Lever Scraper (`jobspy/lever/`)

**API:** `GET https://api.lever.co/v0/postings/{company_slug}?mode=json`

**Design:**
- Extends `ATSBoardScraper`
- `min_request_interval = 0.5` (rate limit: documented as 10 req/10s/IP)
- `max_concurrent = 2` (conservative given rate limits)
- **Deprioritized:** Practitioner found 80% token failure rate (P1). Still worth building since the API works for valid tokens, but expect ~50 valid tokens, not 251.

**Data mapping (verified against live API — Spotify, Aircall):**
| Lever field | JobPost field |
|---|---|
| `id` | `id` (prefixed `lever-{id}`) |
| `text` | `title` |
| company name (derive from slug or first posting) | `company_name` |
| `hostedUrl` | `job_url` |
| `applyUrl` | `job_url_direct` |
| `categories.location` / `categories.allLocations` | `location` |
| `categories.commitment` | `job_type` (map "Permanent"→FULL_TIME, not "Full-time") |
| `categories.team` / `categories.department` | `job_function` |
| `descriptionBody` (richest) or `description` (HTML) | `description` (convert to markdown) |
| `createdAt` (**epoch milliseconds**, divide by 1000) | `date_posted` |
| `additional`/`additionalPlain` → `extract_salary()` | `compensation` (no structured `salaryRange` field!) |
| `workplaceType` ("remote"/"hybrid"/"onsite") | `is_remote` |
| `country` (2-letter code) | `location.country` |

**Key corrections from review:**
- ~~`salaryRange` field~~ → does not exist. Salary is in `additional` text (P6)
- ~~`categories.commitment` = "Full-time"~~ → actual values are "Permanent", "Intern" etc. (P6)
- ~~`createdAt` is epoch seconds~~ → epoch milliseconds (P16)
- ~~`description` is the main field~~ → `descriptionBody` is richer; also `lists` array has structured sections (P6)

### 3.4 Ashby Scraper (`jobspy/ashby/`)

**API:** `GET https://api.ashbyhq.com/posting-api/job-board/{board_name}?includeCompensation=true`

**Design:**
- Extends `ATSBoardScraper`
- `max_concurrent = 10`
- Response JSON may contain control characters — sanitize with `re.sub(r'[\x00-\x1f\x7f]', ' ', raw_text)` before `json.loads()` (P18)
- Compensation data is excellent when present but often empty (varies by company)
- Starts with small token list (~20-30 manually curated)

**Data mapping (verified against live API — Linear, Ramp):**
| Ashby field | JobPost field |
|---|---|
| `id` | `id` (prefixed `ashby-{id}`) |
| `title` | `title` |
| company name (from board context or response) | `company_name` |
| `jobUrl` | `job_url` |
| `applyUrl` | `job_url_direct` |
| `location` / `secondaryLocations` | `location` |
| `department` / `team` | `job_function` |
| `employmentType` | `job_type` |
| `descriptionHtml` or `descriptionPlain` | `description` |
| `publishedAt` | `date_posted` |
| `compensationTiers[].components[]` → `minValue`, `maxValue`, `currencyCode`, `interval` | `compensation` |
| `scrapeableCompensationSalarySummary` | fallback for compensation parsing |
| `isRemote` / `workplaceType` | `is_remote` |

### 3.5 HN Who's Hiring Scraper (`jobspy/hn/`)

**Design (scoped down per C5):**

The HN parser is best-effort. We **do not promise** structured data from unstructured text. Expected parse success: ~60% for company name, ~50% for location, ~30% for salary. The primary value is the raw description text + direct URLs.

**API (corrected per P2):**
- Find latest thread: `GET https://hn.algolia.com/api/v1/search_by_date?query="who is hiring"&tags=story,author_whoishiring&hitsPerPage=1`
  - **MUST use `search_by_date`**, not `search`. The `search` endpoint returns relevance-ranked results and gives 2020 threads instead of current ones.
- Fetch full thread: `GET https://hn.algolia.com/api/v1/items/{thread_id}`
- Only process `children` entries (top-level comments). Skip replies to comments.

**Comment text is HTML** (P9): contains `<a>` tags, `<p>` tags, and HTML entities (`&#x2F;` for `/`, `&amp;` for `&`). Must decode HTML entities before parsing.

**Parsing strategy (pipe-delimited header):**
1. Decode HTML entities, strip tags from first line
2. Split first line on `|`
3. First segment → `company_name`
4. Scan remaining segments for:
   - Location patterns (city/state, "Remote", "ONSITE/REMOTE")
   - Salary patterns (`$xxx,xxx` or `$xxxk`)
   - URLs
5. Everything after first line → `description` (full HTML → markdown)
6. Extract emails from full text
7. If no `|` found in first line, set `company_name` = first 80 chars, `title` = None

**Standard `Scraper` subclass** (not ATSBoardScraper — it's a single-source fetch, closer to Google/Bayt pattern).

---

## Phase 4: JSONL Output & Runner Script

### 4.1 Runner Script (`run_search.py`)

```python
import json
from pathlib import Path
from datetime import date
from jobspy import scrape_jobs

def load_tokens(filepath: str) -> list[str]:
    """Load board tokens from a text file, one per line, skip comments/blanks."""
    path = Path(filepath)
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text().splitlines()
            if line.strip() and not line.startswith("#")]

output_dir = Path("data")
output_dir.mkdir(exist_ok=True)
today = date.today()

# Run each source separately for incremental saves (resume-from-failure)
sources = {
    "remoteok": {"site_name": "remoteok"},
    "greenhouse": {
        "site_name": "greenhouse",
        "greenhouse_board_tokens": load_tokens("tokens/greenhouse.txt"),
    },
    "lever": {
        "site_name": "lever",
        "lever_company_slugs": load_tokens("tokens/lever.txt"),
    },
    "ashby": {
        "site_name": "ashby",
        "ashby_board_names": load_tokens("tokens/ashby.txt"),
    },
    "hn": {"site_name": "hn"},
}

total = 0
output_file = output_dir / f"jobs_{today}.jsonl"

for name, kwargs in sources.items():
    try:
        df = scrape_jobs(
            search_term="software engineer",
            results_wanted=1000,
            hours_old=168,
            **kwargs,
        )
        if not df.empty:
            # Append to JSONL (incremental write)
            df.to_json(output_file, orient="records", lines=True,
                       mode="a")  # append mode
            total += len(df)
            print(f"{name}: {len(df)} jobs")
        else:
            print(f"{name}: 0 jobs")
    except Exception as e:
        print(f"{name}: FAILED - {e}")

print(f"\nTotal: {total} jobs → {output_file}")
```

### 4.2 Deduplication (post-processing)

After all sources write to JSONL, run a dedup pass:
- Normalize company name (lowercase, strip Inc/LLC/etc.)
- Normalize title (lowercase, strip whitespace)
- Dedup key: `(company_name_normalized, title_normalized)`
- Keep the record with the richest data (most non-null fields)

This is a separate post-processing step, not baked into the scrapers. Simple script or function in the runner.

---

## Implementation Order (corrected per C17/C18)

1. **Model changes** — Site enum, ScraperInput fields, JobPost.board_token, ScraperException
2. **Shared utilities** — `ATSBoardScraper` base class, `filter_jobs()`, location parser
3. **Registration & wiring** — SCRAPER_MAPPING, scrape_jobs() param passthrough (with stubs)
4. **Token bootstrapping** — Parse awesome-easy-apply, validate, write token files
5. **RemoteOK scraper** — build + test end-to-end immediately
6. **Greenhouse scraper** — build + test with real tokens
7. **Lever scraper** — build + test (expect high 404 rate)
8. **Ashby scraper** — build + test with manually curated tokens
9. **HN scraper** — build + test (best-effort parsing)
10. **Runner script** — tie it all together with incremental writes
11. **Dedup utility** — post-processing pass
12. **End-to-end test** — full run across all sources

Each scraper is tested immediately after creation. No building in the dark.

---

## What We're NOT Doing

- **Not touching existing scrapers** — Indeed, LinkedIn, Glassdoor, etc. remain as-is
- **Not building a web UI** — JSONL files are the output for now
- **Not implementing token auto-discovery** — curated lists first, discovery scripts later
- **Not adding a database** — JSONL is sufficient for initial collection
- **Not building filtering/ranking** — that's a separate phase after collection works
- **Not writing unit tests with fixtures** — good idea but deferred; we test against live APIs

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Greenhouse rate limits at high concurrency | Tested: 20 concurrent requests worked fine. Add exponential backoff on 429/403. Circuit breaker: stop after 10 consecutive failures. |
| Stale tokens (30-50% for Greenhouse, 80% for Lever) | Validation script in Phase 2. Per-token try/except with logging. Log summary: "280/340 boards succeeded, 45 returned 404, 15 timed out" |
| HN parsing unreliable | Scoped to best-effort. Primary value is raw text + URLs. Accept 40%+ will have null company/title. |
| Ashby JSON control characters | `re.sub(r'[\x00-\x1f\x7f]', ' ', raw)` before `json.loads()` |
| Process crashes mid-run | Incremental JSONL writes per source. Partial results preserved. |
| Large Greenhouse responses (2-4GB with content) | Two-pass: metadata first, content only for matching jobs |
| RemoteOK blocks us | VPN, proper User-Agent, respectful rate limiting |

---

## File Change Summary

**New files:**
- `jobspy/ats_base.py` — `ATSBoardScraper` base class
- `jobspy/greenhouse/__init__.py`, `jobspy/greenhouse/constant.py`
- `jobspy/lever/__init__.py`, `jobspy/lever/constant.py`
- `jobspy/ashby/__init__.py`, `jobspy/ashby/constant.py`
- `jobspy/remoteok/__init__.py`
- `jobspy/hn/__init__.py`
- `tokens/greenhouse.txt`, `tokens/lever.txt`, `tokens/ashby.txt`
- `scripts/bootstrap_tokens.py`, `scripts/validate_tokens.py`
- `run_search.py`

**Modified files:**
- `jobspy/model.py` — Site enum, ScraperInput fields, JobPost.board_token
- `jobspy/__init__.py` — SCRAPER_MAPPING, scrape_jobs() param passthrough, imports
- `jobspy/exception.py` — add ScraperException
- `jobspy/util.py` — `filter_jobs()`, `desired_order` update, location parsing utils
