# Spec 00: Project Vision & Getting Started

## 1. Vision

A local-first CLI tool for discerning software engineers to find the right job at the right company. The pipeline: scrape job boards, store in SQLite, enrich with LLM classification, search and filter, annotate with opinions, track applications. User feedback (ratings, pros, cons) helps surface better matches over time.

Single-user. No web UI. No server. Runs from a project directory.

## 2. Prerequisites

- **Python 3.12+**
- **Claude Code installed** -- the default LLM backend (Agent SDK) uses your existing Claude subscription for enrichment. No API key needed.
- **Optional: `ANTHROPIC_API_KEY` env var** -- only needed for the Batch API fast path (faster, more accurate enrichment). See [spec 05](05-enrichment.md) for details.

Everything except LLM enrichment (`jbs enrich` stages 2-3) works without any API key or subscription.

## 3. Installation

```bash
git clone <repo>
cd job-board-search
python -m venv .venv && source .venv/bin/activate
pip install -e .   # installs jbs CLI + dependencies (click, rich, requests, markdownify)
```

After install, the `jbs` command is available in your shell. All state lives in the project directory -- there is nothing global to configure.

## 4. First Run

```bash
jbs init            # create DB, import tokens from flat files
jbs scrape          # run scrapers
jbs search          # browse results
```

### `jbs init`

Creates the database and imports ATS board tokens from flat files into the `companies` table.

```
$ jbs init
  Imported 540 greenhouse tokens from tokens/greenhouse_raw.txt
  Imported 251 lever tokens from tokens/lever_raw.txt
  Imported 25 ashby tokens from tokens/ashby.txt
Database initialized.
```

Safe to re-run (idempotent). Existing tokens are not duplicated. After `jbs init`, the DB is the source of truth for tokens -- flat files are not read again by scrapers.

### `jbs scrape`

Runs scrapers and writes jobs to the database. Tokens are loaded from the `companies` table, not from flat files.

```
$ jbs scrape
Scraping 5 sources...

  greenhouse  1907 jobs from 298 boards (42 not found, 0 errors)  (34.2s)
  lever        325 jobs from 41 boards (6 not found, 0 errors)    (12.1s)
  ashby        200 jobs from 25 boards (0 not found, 0 errors)    (8.4s)
  remoteok      55 jobs (0.6s)
  hn           274 jobs (0.9s)

Run complete: 2761 jobs scraped, 2761 new
Run ID: 2026-04-05_091500
```

If `jbs scrape` is run without `jbs init` (no database exists), it prints an error suggesting `jbs init` first:

```
$ jbs scrape
Error: No database found at data/jobs.db
Run 'jbs init' to create the database and import tokens.
```

Sources with no tokens in the DB are skipped silently (logged at `--verbose` level), never errored.

### `jbs search`

Browse what you got:

```
$ jbs search "infrastructure"
  3 results (active jobs only)

  gh-881901  Senior Infrastructure Engineer   Anthropic   Remote   $250-350k
  gh-445102  Platform Engineer                Scale AI    Hybrid   $200-280k
  lever-x98  Site Reliability Engineer         Ramp        NYC     $180-250k
```

## 5. Token Management

Greenhouse, Lever, and Ashby are ATS (applicant tracking system) platforms. Each company has a "board token" -- a slug like `anthropic` or `ramp` -- that identifies its job board. To scrape these sources, you need lists of tokens.

### How tokens get into the DB

**Import from flat files (initial setup):**

`jbs init` reads token files from `tokens/` and imports them into the `companies` table. For each platform, it prefers validated files over raw files:

| Platform   | Validated file            | Raw fallback               |
|-----------|--------------------------|---------------------------|
| Greenhouse | `tokens/greenhouse.txt`  | `tokens/greenhouse_raw.txt` |
| Lever      | `tokens/lever.txt`       | `tokens/lever_raw.txt`     |
| Ashby      | `tokens/ashby.txt`       | (no raw file)              |

Flat files are a one-time import source. After `jbs init`, the `companies` table is the source of truth.

**Manual additions:**

```bash
jbs tokens add greenhouse anthropic                    # derives name "Anthropic"
jbs tokens add lever ramp --name "Ramp Technologies"   # explicit name
```

**Automated discovery (from HN):**

```bash
jbs tokens discover         # harvest ATS tokens from HN Who's Hiring comments
```

See [HN token discovery](hn-careers-pipeline.md) for details.

### Validating tokens

Newly imported tokens have status `unchecked`. Validate them against live APIs:

```bash
jbs tokens validate                         # validate unchecked tokens, all platforms
jbs tokens validate --platform greenhouse   # one platform only
jbs tokens validate --status all            # re-validate everything including valid
```

Validation pings each token's API endpoint. Valid tokens are marked `valid`; dead boards are marked `stale`. Stale tokens are skipped by scrapers but never deleted from the DB.

### Token status lifecycle

```
                      jbs init / jbs tokens add / jbs tokens discover
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

### Checking token counts

```bash
$ jbs tokens list

Platform     Valid   Stale   Unchecked   Total
greenhouse     298      42         200     540
lever           41       6          12      59
ashby           25       0           0      25
Total          364      48         212     624
```

## 6. Core Workflow

The full loop in seven commands:

```bash
# 1. Initialize -- create DB, import tokens (once)
jbs init

# 2. Scrape -- pull fresh jobs into the database
jbs scrape --hours-old 48

# 3. Enrich -- classify jobs and companies with LLM
jbs enrich

# 4. Search -- find what matters
jbs search "infrastructure" --remote --ai-native 0.7

# 5. Show -- read the full posting
jbs show gh-881901

# 6. Annotate -- record your opinion
jbs annotate gh-881901 --rating 5 --tag interesting --pros "Great team"

# 7. Apply -- track your application
jbs apply gh-881901
```

Run `jbs scrape` daily or weekly (via cron, launchd, or manually). Jobs accumulate. After scraping, run `jbs enrich` to classify new jobs -- or use `jbs scrape --classify` to enrich inline. Enrichment and annotations persist across scrape runs.

**Enrichment is optional but valuable.** Without it, you can still search by text, source, company name, and location. With it, you get `--ai-native`, `--seniority`, `--domain`, salary normalization, and 1-2 sentence job summaries.

## 7. Data Lifecycle

- **Setup:** `jbs init` creates the database with the full schema (see [spec 02](02-data-model.md)) and imports tokens from flat files. The DB is created at `data/jobs.db` by default.
- **Jobs accumulate** across scrape runs. The database grows over time. Each job has a unique prefixed ID (`gh-12345`, `lever-abc`, `rok-456`) so duplicates are upserted, not duplicated.
- **`is_active` tracking**: when a source is re-scraped but a previously-seen job is not found, a miss counter increments. After 2 consecutive misses, the job is marked `is_active = false`. It remains in the database and is searchable, but `jbs search` excludes inactive jobs by default (use `--include-inactive` to see them).
- **Enrichment**: `jbs enrich` processes unclassified jobs through a four-stage pipeline: data cleanup, rule-based extraction, LLM job classification, and LLM company enrichment. See [spec 05](05-enrichment.md).
- **`jbs stats`** shows DB file size, total jobs (active/inactive), job counts by source, enrichment coverage, and token health.
- **Backups**: the SQLite file is fully portable. `cp data/jobs.db backup.db` is a valid backup. No external dependencies, no server state.
- **Pruning**: old unannotated inactive jobs could be pruned to keep the DB lean, but this is a future feature, not v1. For now, jobs are never deleted.

## 8. Project Structure

The `jbs/` package (detailed in [spec 01](01-architecture.md)):

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
│   ├── util.py             # Inlined helpers (see spec 01 section 12)
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
├── tests/
│   ├── fixtures/           # Saved HTTP responses per scraper
│   ├── test_scrapers.py
│   ├── test_store.py
│   └── test_cli.py
└── specs/                  # These spec documents
```

No JobSpy submodule. The utilities we need (`create_session`, `html_to_markdown`, `filter_jobs`, `extract_salary_from_text`) are inlined into `jbs/util.py`. All scrapers are rewritten as `jbs/scrapers/*.py`.
