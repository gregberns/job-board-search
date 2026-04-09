# Spec 01: Architecture

## 1. System Overview

`jbs` is a local-first CLI tool that scrapes job listings from five sources, stores them in SQLite, enriches with LLM classification, and provides search/filter/annotation. Single-user, no server.

```
CLI (scrape / search / show / enrich / annotate / apply / stats / tokens / init)
  |
  +-- ScraperOrchestrator  -->  Scraper Plugins (GH / Lever / Ashby / RemoteOK / HN)
  +-- Store                -->  SQLite (data/jobs.db)
  +-- Enricher             -->  Claude Haiku
```

## 2. Directory Layout

```
job-board-search/
├── pyproject.toml          # [project.scripts] jbs = "jbs.cli:main"
├── config.toml             # Project-root config (tokens, defaults)
├── jbs/
│   ├── cli.py              # Click CLI, subcommand routing
│   ├── config.py           # TOML -> dataclass
│   ├── store.py            # All SQLite access (Store class)
│   ├── models.py           # Job, ScrapeResult, enums
│   ├── orchestrator.py     # Runs scrapers, writes to store
│   ├── enrich.py           # LLM enrichment pipeline
│   ├── util.py             # Inlined helpers (see section 12)
│   └── scrapers/
│       ├── __init__.py     # Registry (@register decorator, explicit imports)
│       ├── base.py         # ScraperPlugin ABC, PluginMeta, ScrapeContext
│       ├── ats_base.py     # ATSBoardScraper (shared ATS logic)
│       ├── greenhouse.py   # Two-pass fetch, 10 workers
│       ├── lever.py        # Rate-limited (500ms, 2 workers)
│       ├── ashby.py        # JSON sanitization, structured compensation
│       ├── remoteok.py     # Single API call, all-remote
│       └── hn.py           # Algolia search, comment parsing
├── tokens/                 # Board token files (import source, not source of truth)
├── data/                   # Runtime (jobs.db created here)
├── scripts/                # Token bootstrap/validation utilities
└── tests/
    ├── fixtures/           # Saved HTTP responses per scraper
    ├── test_scrapers.py
    ├── test_store.py
    └── test_cli.py
```

**No JobSpy submodule.** The utilities we need (`create_session`, `html_to_markdown`, `filter_jobs`, `extract_salary_from_text`) are inlined into `jbs/util.py`. All scrapers are rewritten as `jbs/scrapers/*.py`.

## 3. Data Models (In-Memory)

Plain dataclasses. Scrapers return `list[Job]`. The `Store` handles mapping between `Job` and SQL rows (see spec 02 for the full DB schema).

```python
# jbs/models.py
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum

class WorkArrangement(Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"

@dataclass
class Location:
    city: str | None = None
    state: str | None = None
    country: str | None = None
    raw: str | None = None
    work_arrangement: WorkArrangement = WorkArrangement.UNKNOWN

@dataclass
class Compensation:
    min_amount: float | None = None
    max_amount: float | None = None
    currency: str = "USD"
    interval: str = "yearly"

@dataclass
class Job:
    id: str                         # Prefixed: gh-123, lever-abc, rok-456
    source: str                     # greenhouse, lever, ashby, remoteok, hn
    title: str
    company: str | None             # Raw company name from scraper (stored as company_raw)
    url: str
    location: Location
    url_direct: str | None = None
    compensation: Compensation | None = None
    description: str | None = None
    date_posted: date | None = None
    job_type: str | None = None     # full-time, part-time, contract, intern
    job_function: str | None = None
    board_token: str | None = None  # ATS board slug this came from
    is_remote: bool = False
    scraped_at: datetime | None = None

@dataclass
class ScrapeResult:
    source: str
    jobs: list[Job]
    failed_tokens: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
```

**Key mapping rules between `Job` dataclass and DB:**
- `Job.company` is stored as `jobs.company_raw` (debug string).
- `jobs.company_id` (FK to `companies`) is resolved by `Store.resolve_company()` at upsert time -- scrapers never set it.
- `jobs.first_seen_run`, `last_seen_run`, `miss_count`, `is_active` are managed by `Store.upsert_jobs()`, never set by scrapers.
- Enrichment fields (`engineering_role`, `seniority`, `domain`, `tech_stack`, `salary_usd_min/max`) live only in the DB, set by `jbs enrich`.

## 4. Scraper Plugin System

### 4.1 Plugin Interface

```python
# jbs/scrapers/base.py
@dataclass(frozen=True)
class PluginMeta:
    name: str              # e.g. "greenhouse"
    id_prefix: str         # e.g. "gh"
    requires_tokens: bool = False

@dataclass
class ScrapeContext:
    search_term: str | None = None
    hours_old: int | None = None
    is_remote: bool = False
    results_wanted: int = 99999
    tokens: list[str] | None = None

class ScraperPlugin(ABC):
    meta: PluginMeta  # subclasses set as class variable

    @abstractmethod
    def scrape(self, ctx: ScrapeContext) -> ScrapeResult:
        """Must not raise. All errors go in ScrapeResult.errors."""
```

**Note on tokens:** The `ScrapeContext.tokens` list is populated by the orchestrator from the DB, not from flat files. Only tokens with `token_status != 'stale'` are included (see section 8).

### 4.2 ATS Base

Shared concurrency, rate limiting, and error isolation for Greenhouse/Lever/Ashby. Parameters are hardcoded as class constants on each subclass. Threads, not asyncio (requests is synchronous; thread pools fit I/O-bound HTTP).

```python
# jbs/scrapers/ats_base.py
class BoardNotFoundError(Exception):
    """Raised when an ATS board returns 404. Triggers token_status -> 'stale'."""

class ATSBoardScraper(ScraperPlugin):
    max_workers: int = 10       # override per subclass
    min_interval: float = 0.0   # seconds between requests

    def scrape(self, ctx: ScrapeContext) -> ScrapeResult:
        """ThreadPoolExecutor over tokens. BoardNotFoundError -> failed_tokens.
        Other exceptions -> errors list. Never raises."""
        tokens = ctx.tokens or []
        # pool.submit(self.fetch_and_map, token, ctx) for each token
        # client-side filter via util.filter_jobs
        return ScrapeResult(source=self.meta.name, jobs=filtered, ...)

    @abstractmethod
    def fetch_and_map(self, token: str, ctx: ScrapeContext) -> list[Job]:
        """Fetch all jobs from one board. Raise BoardNotFoundError on 404."""
```

### 4.3 Registration

`@register` decorator plus explicit imports. No pkgutil discovery, no entry_points.

```python
# jbs/scrapers/__init__.py
_REGISTRY: dict[str, type[ScraperPlugin]] = {}

def register(cls):
    _REGISTRY[cls.meta.name] = cls
    return cls

def get_scraper(name: str) -> ScraperPlugin:
    return _REGISTRY[name]()

def available_scrapers() -> list[str]:
    return list(_REGISTRY)

# Explicit imports trigger @register on class definition
from jbs.scrapers import greenhouse, lever, ashby, remoteok, hn  # noqa
```

Example scraper:

```python
@register
class GreenhouseScraper(ATSBoardScraper):
    meta = PluginMeta(name="greenhouse", id_prefix="gh", requires_tokens=True)
    max_workers = 10
    min_interval = 0.05  # 50ms between detail fetches

    def fetch_and_map(self, token, ctx):
        # Two-pass: lightweight metadata first, full content=true only for matches
        ...
```

## 5. Configuration

`config.toml` at project root. Missing file = all defaults. Minimal settings only. No per-scraper config sections (scraper tuning is hardcoded in each class).

```toml
[general]
db_path = "data/jobs.db"
default_sources = ["greenhouse", "lever", "ashby", "remoteok", "hn"]
hours_old = 168
```

```python
# jbs/config.py
@dataclass
class Config:
    db_path: Path = Path("data/jobs.db")
    default_sources: list[str] = field(default_factory=lambda:
        ["greenhouse", "lever", "ashby", "remoteok", "hn"])
    hours_old: int = 168

def load_config(path: Path = Path("config.toml")) -> Config:
    """Load from TOML. Missing file = all defaults."""
```

**Token paths are not in config.** Tokens live in the `companies` table. Flat files under `tokens/` are only an import source, consumed by `jbs init` or `jbs tokens add`.

## 6. Storage Layer

All DB access through `Store`. No raw SQL elsewhere. Full schema is defined in spec 02.

```python
class Store:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_schema()   # idempotent CREATE/ALTER, see spec 02

    # --- Run tracking ---
    def start_run(self, run_id: str, sources: str, search_term: str | None) -> None: ...
    def finish_run(self, run_id: str, total_jobs: int) -> None: ...

    # --- Job writes ---
    def upsert_jobs(self, jobs: list[Job], run_id: str) -> int:
        """Upsert jobs by prefixed ID. For each job:
        1. resolve_company() -> company_id
        2. maybe_update_company_name() if ATS source
        3. INSERT OR UPDATE job row
        4. Set first_seen_run on INSERT, last_seen_run on every upsert
        Returns count of newly inserted jobs."""

    def mark_stale_jobs(self, run_id: str, source: str) -> int:
        """After scraping a source, increment miss_count for jobs from that
        source that were NOT seen in this run. Set is_active=0 when
        miss_count >= 2. Returns count of newly deactivated jobs."""

    # --- Token management ---
    def get_tokens(self, platform: str) -> list[str]:
        """SELECT ats_token FROM companies
        WHERE ats_platform = ? AND token_status != 'stale'"""

    def mark_tokens_stale(self, platform: str, tokens: list[str]) -> None:
        """UPDATE companies SET token_status = 'stale', token_checked_at = ...
        WHERE ats_platform = ? AND ats_token IN (...)"""

    def mark_tokens_valid(self, platform: str, tokens: list[str]) -> None:
        """UPDATE companies SET token_status = 'valid', token_checked_at = ...
        WHERE ats_platform = ? AND ats_token IN (...)"""

    def import_tokens(self, platform: str, filepath: str) -> int:
        """Import from flat file. See spec 02 import_tokens_from_file(). Returns count."""

    def add_token(self, platform: str, token: str, company_name: str | None = None) -> bool:
        """Add a single token. Derives company name from slug if not provided.
        Returns True if newly created, False if already existed."""

    def get_token_counts(self) -> dict[str, dict[str, int]]:
        """Token counts grouped by platform and status.
        Returns e.g. {'greenhouse': {'valid': 298, 'stale': 42, 'unchecked': 0}}"""

    # --- Company resolution (spec 02 algorithm) ---
    def resolve_company(self, job: Job) -> int | None:
        """Resolve a job to a company_id. Algorithm:
        1. ATS token match: if job.board_token and job.source in ATS platforms,
           look up by (ats_platform, ats_token). Definitive match.
        2. Normalized name match: normalize job.company, look up by name_normalized.
           Backfill ATS info if the company didn't have it.
        3. No match: create new company record. Return None if no company name.
        See spec 02 for full implementation."""

    def maybe_update_company_name(self, company_id: int, api_name: str) -> None:
        """Update display name if current name looks slug-derived and new name
        normalizes to the same value. Does NOT change name_normalized.
        Called after successful ATS API response. See spec 02."""

    # --- Reads ---
    def search(self, **filters) -> list[Job]: ...   # see spec 04
    def get_job(self, job_id: str) -> Job | None: ...
    def get_stats(self) -> dict: ...

    # --- Enrichment ---
    def get_unenriched_jobs(self, limit: int = 100) -> list[Job]: ...
    def update_enrichment(self, job_id: str, **fields) -> None: ...

    # --- Annotations ---
    def annotate(self, job_id: str, **kwargs) -> None: ...
    def add_tag(self, job_id: str, tag: str) -> None: ...
    def remove_tag(self, job_id: str, tag: str) -> None: ...

    # --- Private ---
    def _conn(self) -> sqlite3.Connection:
        """Returns connection with WAL mode, foreign keys enabled."""
    def _ensure_schema(self) -> None:
        """See spec 02 migration strategy."""
```

**DB connection management:** One connection per `Store` instance, created lazily. WAL mode for concurrent reads during long scrape writes. Foreign keys enabled via `PRAGMA foreign_keys = ON`.

```python
def _conn(self) -> sqlite3.Connection:
    if self._connection is None:
        self._connection = sqlite3.connect(self.db_path)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.row_factory = sqlite3.Row
    return self._connection
```

## 7. CLI Command Tree

Click-based. Thin layer: creates `Config` + `Store`, delegates. Full option details in spec 03.

```
jbs [--db PATH] [--format table|json|csv] [--no-color] [--verbose]
 |
 +-- init                           # Create DB, import tokens from flat files
 +-- scrape                         # Run scrapers, write to DB
 |     --sources, --search-term, --hours-old, --classify, --dry-run
 +-- search                         # Query the job database
 |     QUERY, --new, --company, --remote, --source, --salary-min, --days,
 |     --ai-native, --seniority, --domain, --tag, --interest, --sort, --limit
 +-- show <job-id>                  # Full details for one job
 |     --no-desc, --open
 +-- enrich                         # Run classification pipeline
 |     --stage (rules|jobs|companies), --dry-run, --source, --force
 +-- annotate <job-id>              # Tag, rate, note a job
 |     --tag, --untag, --note, --rating, --pros, --cons
 +-- apply <job-id>                 # Track application status
 |     --stage, --note, --list
 +-- stats                          # DB statistics, scrape history
 |     --runs
 +-- tokens                         # Token management subcommands
       +-- validate                 # Ping live APIs, update token_status
       |     --platform, --status (unchecked|all)
       +-- add <platform> <token>   # Add a single token manually
       |     --name
       +-- list                     # Show token counts by platform and status
```

```python
@click.group()
@click.option("--db", default=None, help="SQLite database path")
@click.option("--format", "output_format", type=click.Choice(["table", "json", "csv"]), default="table")
@click.option("--no-color", is_flag=True)
@click.option("--verbose", is_flag=True)
@click.pass_context
def cli(ctx, db, output_format, no_color, verbose):
    cfg = load_config()
    if db:
        cfg.db_path = Path(db)
    ctx.obj = {"config": cfg, "format": output_format, "verbose": verbose}
```

## 8. Orchestrator and Data Flow

Sources run sequentially (clean logging, predictable resources). Each ATS scraper is internally concurrent via ThreadPoolExecutor.

### 8.1 Scrape Flow

```python
class ScraperOrchestrator:
    def __init__(self, config: Config, store: Store): ...

    def run(self, sources: list[str], search_term=None, hours_old=None) -> dict:
        run_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.store.start_run(run_id, ",".join(sources), search_term)
        total = 0

        for name in sources:
            scraper = get_scraper(name)
            ctx = self._build_context(name, search_term, hours_old)

            if scraper.meta.requires_tokens and not ctx.tokens:
                log(f"  {name}: skipped (no tokens in DB)")
                continue

            result = scraper.scrape(ctx)
            inserted = self.store.upsert_jobs(result.jobs, run_id)
            total += inserted

            # Mark tokens that returned 404 as stale
            if result.failed_tokens:
                self.store.mark_tokens_stale(name, result.failed_tokens)

            # Mark jobs not seen in this run (staleness tracking)
            self.store.mark_stale_jobs(run_id, name)

            self._print_source_summary(name, result, inserted)

        self.store.finish_run(run_id, total)
        return {"run_id": run_id, "total": total}

    def _build_context(self, source: str, search_term, hours_old) -> ScrapeContext:
        """Build ScrapeContext. For ATS sources, load tokens from DB."""
        tokens = None
        if source in ("greenhouse", "lever", "ashby"):
            tokens = self.store.get_tokens(source)
        return ScrapeContext(
            search_term=search_term,
            hours_old=hours_old or self.config.hours_old,
            tokens=tokens,
        )
```

### 8.2 Sequence Diagram

```
User          CLI           Orchestrator     Store              Scraper
 |             |                |              |                   |
 | jbs scrape  |                |              |                   |
 |------------>|                |              |                   |
 |             | run(sources)   |              |                   |
 |             |--------------->|              |                   |
 |             |                | start_run()  |                   |
 |             |                |------------->|                   |
 |             |                |              |                   |
 |             |                | get_tokens("greenhouse")         |
 |             |                |------------->|                   |
 |             |                |   [tokens]   |                   |
 |             |                |<-------------|                   |
 |             |                |              |                   |
 |             |                | scrape(ctx)                      |
 |             |                |--------------------------------->|
 |             |                |                  ScrapeResult     |
 |             |                |<---------------------------------|
 |             |                |              |                   |
 |             |                | upsert_jobs()|                   |
 |             |                |------------->|                   |
 |             |                |  resolve_company() per job       |
 |             |                |  maybe_update_company_name()     |
 |             |                |  INSERT/UPDATE jobs              |
 |             |                |              |                   |
 |             |                | mark_tokens_stale(failed)        |
 |             |                |------------->|                   |
 |             |                |              |                   |
 |             |                | mark_stale_jobs(run_id, source)  |
 |             |                |------------->|                   |
 |             |                |              |                   |
 |             |                | [next source...]                 |
 |             |                |              |                   |
 |             |                | finish_run() |                   |
 |             |                |------------->|                   |
```

### 8.3 Full Pipeline Overview

```
jbs init
  |
  +-- Create data/jobs.db (full schema from spec 02)
  +-- Import tokens from tokens/*.txt -> companies table
  +-- Report: "Imported N greenhouse, M lever, K ashby tokens"

jbs scrape
  |
  +-- For each source (sequential):
  |     1. Load tokens from companies table (token_status != 'stale')
  |     2. Run scraper plugin (internally concurrent for ATS sources)
  |     3. For each returned Job:
  |          a. resolve_company() -> company_id (token match -> name match -> create)
  |          b. maybe_update_company_name() if ATS source provided real name
  |          c. Upsert job row (first_seen_run on INSERT, last_seen_run always)
  |     4. Mark failed tokens as stale in companies table
  |     5. Increment miss_count for unseen jobs; deactivate after 2 misses
  |
  +-- jbs scrape --classify triggers enrichment after scrape

jbs enrich (separate step or via --classify)
  |
  +-- Stage 1: rules (free) -- seniority (partial), salary normalization, visa_sponsorship, years_experience, is_management
  +-- Stage 2: jobs (Haiku) -- engineering_role, seniority, domain
  +-- Stage 3: companies (Haiku) -- description, industry, ai_native, funding_stage

jbs search / show / annotate / apply
  |
  +-- Operate on stored data only (no scraping)
```

## 9. Token Architecture

### 9.1 Tokens Live in the DB

The `companies` table IS the token registry (spec 02). Flat files under `tokens/` are an import source consumed by `jbs init` or `jbs tokens add`. Once imported, the DB is the source of truth.

**Token status lifecycle:**

```
                          jbs init / jbs tokens add
                                   |
                                   v
                            +-------------+
                            |  unchecked  |
                            +------+------+
                                   |
                        jbs tokens validate
                          (ping live API)
                                   |
                     +-------------+-------------+
                     |                           |
                     v                           v
              +------------+              +------------+
              |   valid    |              |   stale    |
              +-----+------+              +------------+
                    |                           ^
                    |    API returns 404         |
                    |    during scrape           |
                    +---------------------------+
```

- **`unchecked`**: Newly imported, never validated. Scrapers will attempt these.
- **`valid`**: Confirmed working via API ping or successful scrape.
- **`stale`**: API returned 404 or validation failed. Scrapers skip these. Stale tokens are never deleted from the DB -- they remain as a record that the company exists (and may have other data attached).
- Scrapers load tokens with: `SELECT ats_token FROM companies WHERE ats_platform = ? AND token_status != 'stale'`

### 9.2 `jbs init` Flow

Creates the database and imports tokens from flat files. Safe to re-run (idempotent).

```python
@cli.command()
@click.pass_context
def init(ctx):
    """Initialize the database and import tokens from flat files."""
    cfg = ctx.obj["config"]
    store = Store(cfg.db_path)  # creates DB + schema via _ensure_schema()

    # Import tokens from flat files (spec 02 algorithm)
    # For each platform, prefer validated file over raw file
    TOKEN_FILES = {
        "greenhouse": ["tokens/greenhouse.txt", "tokens/greenhouse_raw.txt"],
        "lever":      ["tokens/lever.txt", "tokens/lever_raw.txt"],
        "ashby":      ["tokens/ashby.txt"],
    }

    for platform, candidates in TOKEN_FILES.items():
        for path in candidates:
            if os.path.exists(path):
                count = store.import_tokens(platform, path)
                click.echo(f"  Imported {count} {platform} tokens from {path}")
                break  # don't import raw if validated exists

    # Import 404 blocklists as stale tokens
    for platform in ("greenhouse", "lever", "ashby"):
        blocklist = f"tokens/{platform}_404.txt"
        if os.path.exists(blocklist):
            # mark matching tokens as stale
            ...

    click.echo("Database initialized.")
```

### 9.3 `jbs tokens validate` Flow

Pings live ATS APIs to check whether board tokens are still active. Updates `token_status` and `token_checked_at` in the `companies` table.

```
jbs tokens validate                          # validate unchecked tokens, all platforms
jbs tokens validate --platform greenhouse    # one platform only
jbs tokens validate --status all             # re-validate everything including valid
```

```python
@tokens.command()
@click.option("--platform", type=click.Choice(["greenhouse", "lever", "ashby"]))
@click.option("--status", "filter_status", default="unchecked",
              type=click.Choice(["unchecked", "all"]))
@click.pass_context
def validate(ctx, platform, filter_status):
    """Ping live APIs and update token_status."""
    store = Store(ctx.obj["config"].db_path)
    platforms = [platform] if platform else ["greenhouse", "lever", "ashby"]

    for plat in platforms:
        # Get tokens to validate
        if filter_status == "unchecked":
            tokens = store.get_tokens_by_status(plat, "unchecked")
        else:
            tokens = store.get_all_tokens(plat)  # includes valid, stale, unchecked

        if not tokens:
            click.echo(f"  {plat}: no tokens to validate")
            continue

        # Ping each token's API endpoint (concurrent, with rate limiting)
        valid, stale = validate_tokens_against_api(plat, tokens)

        store.mark_tokens_valid(plat, valid)
        store.mark_tokens_stale(plat, stale)

        click.echo(f"  {plat}: {len(valid)} valid, {len(stale)} stale (of {len(tokens)} checked)")
```

**API validation endpoints:**

| Platform   | Check URL                                           | Valid if         |
|-----------|-----------------------------------------------------|------------------|
| Greenhouse | `https://boards-api.greenhouse.io/v1/boards/{token}/jobs` | 200 + non-empty |
| Lever      | `https://api.lever.co/v0/postings/{token}`          | 200              |
| Ashby      | `https://api.ashbyhq.com/posting-api/job-board/{token}` | 200              |

### 9.4 `jbs tokens add` Flow

```bash
jbs tokens add greenhouse anthropic                    # derives name "Anthropic"
jbs tokens add lever ramp --name "Ramp Technologies"   # explicit name
```

Creates a company record with `token_status = 'unchecked'`. If the `(ats_platform, ats_token)` pair already exists, reports that and does nothing.

### 9.5 `jbs tokens list` Flow

```bash
jbs tokens list
```

```
Platform     Valid   Stale   Unchecked   Total
greenhouse     298      42         200     540
lever           41       6          12      59
ashby           25       0           0      25
Total          364      48         212     624
```

## 10. Error Handling

**Principle:** scrapers never raise. Errors go in `ScrapeResult.errors`. One board failing does not abort the source. One source failing does not abort the run.

### 10.1 Three Levels of Isolation

1. **Per-board isolation (ATS scrapers):** Each board token runs in its own thread. A `BoardNotFoundError` adds the token to `failed_tokens`. Any other exception is caught, logged to `errors`, and the next board continues.

2. **Per-source isolation (orchestrator):** Each source runs sequentially. If a source raises an unexpected exception (shouldn't happen -- scrapers catch everything), the orchestrator catches it, logs it, and continues to the next source.

3. **Per-run isolation (CLI):** The CLI catches exceptions from the orchestrator, prints a summary of what succeeded and what failed, and exits with a non-zero code only if zero sources completed.

### 10.2 What the User Sees

| Scenario | CLI output |
|----------|-----------|
| Missing tokens in DB | `greenhouse: skipped (no tokens in DB)` |
| All tokens 404 | `lever: 0 jobs (47 boards not found, 0 errors)` |
| Partial failures | `greenhouse: 312 jobs from 89 boards (14 not found, 2 errors)` |
| Network timeout | `ashby: 45 jobs from 20 boards (0 not found, 5 errors)` |
| Rate-limited (429) | Scraper backs off internally; if exhausted: appears as error count |
| Source fully down | `remoteok: 0 jobs (1 error: ConnectionError: ...)` |

### 10.3 Rate Limiting (Hardcoded per Scraper)

| Source     | Strategy                       | Values              |
|-----------|-------------------------------|---------------------|
| Greenhouse | Sleep between detail fetches  | 50ms, 10 workers    |
| Lever      | Min interval + low concurrency| 500ms, 2 workers    |
| Ashby      | No throttle needed            | 10 workers          |
| RemoteOK   | Single request, respect 429   | --                  |
| HN         | Single request (Algolia)      | --                  |

## 11. Concurrency Model

**Inter-source: sequential.** Sources run one at a time. This keeps logging clean, makes resource usage predictable, and avoids cross-source rate limiting issues.

**Intra-source: thread pools.** ATS scrapers use `concurrent.futures.ThreadPoolExecutor` to fetch multiple boards in parallel. Each subclass sets `max_workers` and `min_interval` as class constants.

```python
# In ATSBoardScraper.scrape():
with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
    futures = {pool.submit(self._fetch_one, token, ctx): token for token in tokens}
    for future in as_completed(futures):
        token = futures[future]
        try:
            jobs = future.result()
            all_jobs.extend(jobs)
        except BoardNotFoundError:
            failed_tokens.append(token)
        except Exception as e:
            errors.append(f"{token}: {e}")
```

**Rate limiting** is enforced via a shared `threading.Lock` + `time.sleep()` in the base class, not per-thread. The lock ensures `min_interval` seconds between any two requests from the same scraper, regardless of which thread makes them.

**RemoteOK and HN** are single-request scrapers (one API call, no concurrency needed).

## 12. Inlined Utilities

`jbs/util.py` contains helpers extracted from JobSpy, inlined to avoid the submodule dependency:

| Function | Purpose | Origin |
|----------|---------|--------|
| `create_session()` | `requests.Session` with retry, timeout, User-Agent | JobSpy |
| `html_to_markdown(html)` | Convert HTML job descriptions to markdown | JobSpy |
| `filter_jobs(jobs, search_term, hours_old, is_remote)` | Client-side filtering of scraped results | JobSpy |
| `extract_salary_from_text(text)` | Regex salary extraction from description text | JobSpy |
| `normalize_company_name(name)` | Company name normalization for dedup (spec 02) | New |
| `parse_location(raw)` | Parse location string into city/state/country | JobSpy |

## 13. Testing

**pytest.** Three layers:

- **Scrapers:** Saved HTTP response fixtures in `tests/fixtures/`. Patch `requests.Session`, assert `list[Job]` field mapping. No live HTTP.
- **Store:** `:memory:` SQLite. Exercise `upsert_jobs`, `resolve_company`, `search`, `annotate`, idempotent migrations, token operations.
- **CLI:** Click's `CliRunner`. Assert exit codes and output with `:memory:` Store.

## 14. Migration Path from Current Codebase

### What Gets Created

1. `jbs/` package with all modules listed in section 2.
2. `pyproject.toml` with `[project.scripts] jbs = "jbs.cli:main"`.
3. `config.toml` with defaults.
4. `tests/` with fixtures and test modules.

### What Gets Deleted

1. `JobSpy/` submodule (all scraper logic rewritten in `jbs/scrapers/`).
2. `run_search.py` (replaced by `jbs scrape`).
3. `scripts/validate_tokens.py` (replaced by `jbs tokens validate`).
4. `scripts/bootstrap_tokens.py` (replaced by `jbs init`).
5. `scripts/dedup.py` (dedup is now handled by upsert on prefixed IDs).

### What Stays

1. `tokens/` directory with flat files (consumed by `jbs init`).
2. `data/` directory (DB location).
3. `specs/` directory.

### Migration Steps

1. **Package structure:** Create `jbs/`. Inline utilities from JobSpy into `jbs/util.py`. Rewrite scrapers.
2. **Storage:** Implement `Store` with spec 02 schema. `jbs init` imports tokens from flat files.
3. **Config + CLI:** Create `config.toml`. Implement Click CLI. `pip install -e .`
4. **Enrichment:** Implement `jbs/enrich.py`. Wire into `jbs enrich` and `jbs scrape --classify`.
