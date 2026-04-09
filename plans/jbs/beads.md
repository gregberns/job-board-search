# jbs Implementation Beads

## Dependency Graph

```
L0 (Foundation — no dependencies)
├── 0a: Package Scaffold (pyproject.toml, __init__, config.toml)
├── 0b: Data Models (jbs/models.py)
└── 0c: Utilities (jbs/util.py)

L1 (Core — depends on L0)
├── 1a: Store (jbs/store.py) ← 0b, 0c
└── 1b: Scraper Plugin System (scrapers/__init__, base, ats_base) ← 0b

L2 (Scrapers + early L3 — depends on L1, can run in parallel)
├── 2a: Greenhouse Scraper ← 1b, 0c
├── 2b: Lever Scraper ← 1b, 0c
├── 2c: Ashby Scraper ← 1b, 0c
├── 2d: RemoteOK Scraper ← 1b, 0c
├── 2e: HN Scraper ← 1b, 0c
├── 3b: Enrichment Pipeline (jbs/enrich.py + supporting modules) ← 1a
├── 3c: HN Token Discovery (jbs/discover.py) ← 1a, 0c
└── 4a: FTS5 Search + Ranking ← 1a  (Store extension, no CLI dep)

L3 (Integration — depends on L2)
├── 3a: Orchestrator (jbs/orchestrator.py) ← 1a, 1b, 2a-2e
└── 3d: CLI (jbs/cli.py) ← 1a, 3a, 3b, 3c

L4 (Integration Test — depends on L3)
└── 4b: Data Migration + Integration Test ← all above
```

## Inter-Package Import Map

```
jbs/cli.py          → config, store, orchestrator, enrich, models
jbs/orchestrator.py → store, scrapers, models, config
jbs/enrich.py       → store, models, util, llm_backend
jbs/store.py        → models, util (normalize_company_name)
jbs/scrapers/*      → base, models, util
jbs/models.py       → (no internal deps — leaf)
jbs/util.py         → (no internal deps — leaf)
jbs/config.py       → (no internal deps — leaf)
```

No import cycles. Leaf packages: `models`, `util`, `config`.

## Cross-Cutting Concerns

### CC1: Company Resolution
- **What:** Every job upsert resolves to a company_id via ATS token match → name match → create
- **Beads:** 1a (Store implements algorithm), 3a (Orchestrator calls it during upsert)
- **Spec:** 02-data-model.md "Company Resolution Algorithm"

### CC2: Error Isolation
- **What:** Per-board and per-source error isolation. Scrapers never raise.
- **Beads:** 1b (base classes enforce), 2a-2e (each scraper follows pattern), 3a (orchestrator catches source-level)
- **Spec:** 01-architecture.md sections 10, 11

### CC3: Token Lifecycle
- **What:** unchecked → valid/stale lifecycle, stale tokens skipped, 404s during scrape mark stale
- **Beads:** 1a (Store token methods), 3a (Orchestrator marks stale after scrape)
- **Spec:** 01-architecture.md section 9, 02-data-model.md "Token Import"

### CC4: Enrichment Watermark
- **What:** `enriched_at` on jobs/companies, `--force` for re-enrichment, stage-specific queries
- **Beads:** 1a (Store queries), 3b (Enrichment pipeline)
- **Spec:** 05-enrichment.md "Enrichment Watermark"

### CC5: Idempotent Schema Migration
- **What:** `_ensure_schema()` runs on every Store init, handles old → new schema gracefully
- **Beads:** 1a (Store implements), 4b (verified with real data)
- **Spec:** 02-data-model.md "Migration Strategy"

---

## Per-Bead Specifications

### Bead 0a — Package Scaffold
**Specs:** 01-architecture.md (sections 2, 5)
**Package:** project root + jbs/
**Deliverables:**
- `pyproject.toml` with `[project.scripts] jbs = "jbs.cli:main"`, dependencies (click, rich, requests, tomli/tomllib, claude-agent-sdk), optional deps `[project.optional-dependencies] fast-enrich = ["anthropic>=0.40"]`
- `jbs/__init__.py` (empty or version string)
- `jbs/config.py` — `Config` dataclass, `load_config()` from TOML, defaults
- `config.toml` — default config file
- `tests/__init__.py`, `tests/conftest.py` (shared fixtures)
**Tests:** `load_config()` with missing file returns defaults; custom values override

### Bead 0b — Data Models
**Specs:** 01-architecture.md (section 3)
**Package:** `jbs/models.py`
**Deliverables:**
- `WorkArrangement` enum
- `Location` dataclass
- `Compensation` dataclass
- `Job` dataclass (with all fields from spec)
- `ScrapeResult` dataclass
- `SearchQuery` dataclass (from spec 04, after revision)
**Tests:** Construction, defaults, serialization round-trip

### Bead 0c — Utilities
**Specs:** 01-architecture.md (section 12), 02-data-model.md (normalization), 05-enrichment.md (stage 0)
**Package:** `jbs/util.py`
**Deliverables:**
- `create_session()` — requests.Session with retry, timeout, User-Agent
- `html_to_markdown(html)` — HTML to markdown conversion
- `filter_jobs(jobs, search_term, hours_old, is_remote)` — client-side filtering
- `extract_salary_from_text(text)` — regex salary extraction
- `normalize_company_name(name)` — company name dedup key (spec 02 algorithm)
- `parse_location(raw)` — location string parsing
- `strip_boilerplate(text)` — legal boilerplate removal (spec 05 stage 0c)
- `fix_mojibake(text)` — UTF-8 encoding fix (spec 05 stage 0b)
**Tests:** Each function with edge cases; normalize_company_name with spec 02 examples

### Bead 1a — Store
**Specs:** 01-architecture.md (section 6), 02-data-model.md (full schema), 04-search-ranking.md (FTS5)
**Package:** `jbs/store.py`
**Deliverables:**
- `Store` class with `__init__(db_path)`, lazy `_conn()`, WAL mode, FK enforcement
- `_ensure_schema()` — all 8 tables, all indexes, all migrations (spec 02)
- Run tracking: `start_run()`, `finish_run()`
- Job writes: `upsert_jobs()`, `mark_stale_jobs()`
- Token management: `get_tokens()`, `get_tokens_by_status()`, `get_all_tokens()`, `mark_tokens_stale()`, `mark_tokens_valid()`, `import_tokens()`, `add_token()`, `get_token_counts()`
- HN career pages: `get_unprocessed_hn_urls()`, `upsert_hn_career_page()`, `update_hn_career_page()`, `get_hn_pages_by_status()`, `get_hn_discovery_summary()`
- Enrichment stage 0 queries: `get_greenhouse_html_jobs()`, `get_remoteok_mojibake_jobs()`, `update_description()`
- Company resolution: `resolve_company()`, `maybe_update_company_name()`
- Reads: `search()` (query builder from spec 04), `get_job()`, `get_stats()`
- Enrichment: `get_unenriched_jobs()`, `get_unenriched_companies()`, `update_job_enrichment()`, `update_company_enrichment()`, `record_enrichment_run()`
- Annotations: `annotate()`, `add_tag()`, `remove_tag()`, `set_interest()`
- FTS5: virtual table, triggers, backfill, `rebuild_fts()`
**Tests:** `:memory:` DB. Exercise upsert, resolve_company, search, annotate, token lifecycle, idempotent schema, migration from old schema

### Bead 1b — Scraper Plugin System
**Specs:** 01-architecture.md (sections 4.1, 4.2, 4.3)
**Package:** `jbs/scrapers/__init__.py`, `jbs/scrapers/base.py`, `jbs/scrapers/ats_base.py`
**Deliverables:**
- `PluginMeta` frozen dataclass
- `ScrapeContext` dataclass
- `ScraperPlugin` ABC with `meta` and `scrape()` method
- `BoardNotFoundError` exception
- `ATSBoardScraper` base class — ThreadPoolExecutor, rate limiting via Lock, error isolation per board
- `_REGISTRY` dict, `@register` decorator, `get_scraper()`, `available_scrapers()`
- Explicit imports at bottom of `__init__.py` (triggers registration). All 5 import lines are present from the start; each L2 scraper bead creates its .py file to satisfy the import. No __init__.py edits needed during L2.
**Tests:** Registry test (register/get), ATSBoardScraper with mock fetch (success, 404, error isolation)

### Bead 2a — Greenhouse Scraper
**Specs:** 01-architecture.md (section 4), existing `JobSpy/jobspy/greenhouse/` for logic
**Package:** `jbs/scrapers/greenhouse.py`
**Deliverables:**
- `GreenhouseScraper(ATSBoardScraper)` with `meta = PluginMeta(name="greenhouse", id_prefix="gh", requires_tokens=True)`
- `max_workers = 10`, `min_interval = 0.05`
- `fetch_and_map()` — two-pass: lightweight metadata first (`GET /v1/boards/{token}/jobs`), then full content (`?content=true`) only for matched jobs
- Job mapping: API response → `Job` dataclass with `gh-{id}` prefix
- HTML description handling (store as-is, cleanup happens in enrichment stage 0)
**Tests:** Fixture-based: saved API responses → assert Job fields

### Bead 2b — Lever Scraper
**Specs:** 01-architecture.md, existing `JobSpy/jobspy/lever/`
**Package:** `jbs/scrapers/lever.py`
**Deliverables:**
- `LeverScraper(ATSBoardScraper)` with `meta = PluginMeta(name="lever", id_prefix="lever", requires_tokens=True)`
- `max_workers = 2`, `min_interval = 0.5`
- `fetch_and_map()` — `GET /v0/postings/{token}`, epoch-ms date handling
- Job mapping with `lever-{id}` prefix
**Tests:** Fixture-based

### Bead 2c — Ashby Scraper
**Specs:** 01-architecture.md, existing `JobSpy/jobspy/ashby/`
**Package:** `jbs/scrapers/ashby.py`
**Deliverables:**
- `AshbyScraper(ATSBoardScraper)` with `meta = PluginMeta(name="ashby", id_prefix="ashby", requires_tokens=True)`
- `max_workers = 10`, `min_interval = 0.0`
- `fetch_and_map()` — `GET /posting-api/job-board/{token}`, JSON control-char sanitization
- **Structured compensation extraction** from `compensationTiers` (fix from spec 05 stage 0d)
- Job mapping with `ashby-{id}` prefix
**Tests:** Fixture-based, including compensation extraction

### Bead 2d — RemoteOK Scraper
**Specs:** 01-architecture.md, existing `JobSpy/jobspy/remoteok/`
**Package:** `jbs/scrapers/remoteok.py`
**Deliverables:**
- `RemoteOKScraper(ScraperPlugin)` (NOT ATSBoardScraper — single API call)
- `meta = PluginMeta(name="remoteok", id_prefix="rok", requires_tokens=False)`
- `scrape()` — `GET https://remoteok.com/api`, all-remote, salary/location parsing
- Job mapping with `rok-{id}` prefix
- Proper User-Agent header, 429 handling
**Tests:** Fixture-based

### Bead 2e — HN Scraper
**Specs:** 01-architecture.md, existing `JobSpy/jobspy/hn/`
**Package:** `jbs/scrapers/hn.py`
**Deliverables:**
- `HNScraper(ScraperPlugin)` (NOT ATSBoardScraper — Algolia API)
- `meta = PluginMeta(name="hn", id_prefix="hn", requires_tokens=False)`
- `scrape()` — Algolia `search_by_date`, pipe-delimited comment parsing
- Job mapping with `hn-{id}` prefix
- Extract: company name (~60%), location (~50%), salary (~30%) from unstructured comments
**Tests:** Fixture-based with sample HN comments

### Bead 3a — Orchestrator
**Specs:** 01-architecture.md (section 8)
**Package:** `jbs/orchestrator.py`
**Deliverables:**
- `ScraperOrchestrator` class with `__init__(config, store)`
- `run(sources, search_term, hours_old)` — sequential sources, with:
  - Token loading from DB for ATS sources
  - Scraper instantiation via registry
  - `store.upsert_jobs()` after each source
  - `store.mark_tokens_stale()` for failed tokens
  - `store.mark_stale_jobs()` for unseen jobs
  - Run tracking (start_run / finish_run)
  - Per-source summary logging
- `_build_context()` — ScrapeContext from config + DB tokens
**Tests:** Mock scrapers, verify orchestration flow, token stale marking, run tracking

### Bead 3b — Enrichment Pipeline
**Specs:** 05-enrichment.md (full spec)
**Package:** `jbs/enrich.py`, `jbs/enrich_prompts.py`, `jbs/enrich_rules.py`, `jbs/llm_backend.py`
**Deliverables:**
- `EnrichmentPipeline` class orchestrating all 4 stages
- `jbs/enrich_rules.py`:
  - `extract_seniority(title)` — keyword patterns
  - `extract_is_management(title)` — management patterns
  - `normalize_salary_to_usd(min, max, currency, interval)` — static FX
  - `extract_visa(description)` — visa sponsorship regex
  - `extract_years_experience(description)` — years regex
- `jbs/enrich_prompts.py`:
  - Job classification system prompt + user message formatter
  - Company classification system prompt + user message formatter
- `jbs/llm_backend.py`:
  - `LLMBackend` ABC with `classify_jobs()`, `classify_companies()`
  - `AgentSDKBackend` — batched 20/call, 2KB truncation
  - `BatchAPIBackend` — individual calls, full descriptions, Batch API
  - `get_llm_backend()` — auto-select based on ANTHROPIC_API_KEY
- `normalize_tech_stack()` — alias map post-processing
- Stage 0: `fix_greenhouse_html()`, `fix_remoteok_encoding()`, boilerplate stripping (in memory)
- Integration with `enrichment_runs` table for cost tracking
**Tests:** Rule extraction with edge cases; mock LLM backend for pipeline flow; tech_stack normalization

### Bead 3c — HN Token Discovery
**Specs:** hn-careers-pipeline.md (full spec)
**Package:** `jbs/discover.py`
**Deliverables:**
- `run_discovery(store, phase, verbose)` — orchestrates all 3 phases
- Phase 1: `harvest_ats_tokens()` — regex ATS URL patterns, `Store.add_token()`, `Store.upsert_hn_career_page()`
- Phase 2: `discover_careers_pages()` — probe common paths, scan `<a>` tags, classify dead_ends
- Phase 3: `detect_ats_on_careers()` — scan HTML for ATS embeds (iframes, scripts), extract tokens
- `_ATS_PATTERNS` regex list for URL matching
- `_CAREERS_PATHS` list for probing
- Rate limiting: 1 req/sec per domain
**Tests:** URL pattern matching; mock HTTP responses for careers discovery; Store integration

### Bead 3d — CLI
**Specs:** 01-architecture.md (section 7), 03-cli-ux.md (full spec), hn-careers-pipeline.md (tokens discover)
**Package:** `jbs/cli.py`
**Deliverables:**
- `cli` Click group with global options (--db, --format, --no-color, --verbose)
- `jbs init` — create DB, import tokens from flat files
- `jbs scrape` — wire to orchestrator, --sources, --search-term, --hours-old, --classify, --dry-run
- `jbs search` — wire to store.search(), all filter options, table/json/csv output via Rich
- `jbs show <job-id>` — full job display, --no-desc, --open
- `jbs enrich` — wire to enrichment pipeline, --stage, --dry-run, --force, --source
- `jbs annotate <job-id>` — --tag, --untag, --note, --rating, --pros, --cons
- `jbs apply <job-id>` — --stage, --note, --list
- `jbs stats` — DB stats, --runs
- `jbs tokens` subgroup: validate, add, list, discover
- Rich table formatting, JSON/CSV output, progress bars
**Tests:** Click CliRunner tests with `:memory:` Store

### Bead 4a — FTS5 Search + Ranking
**Specs:** 04-search-ranking.md (full spec after revision)
**Package:** Additions to `jbs/store.py` (clearly delimited FTS section — appended to _ensure_schema, new methods at end of file)
**Dependencies:** 1a only (Store extension, no CLI dependency)
**Deliverables:**
- FTS5 virtual table creation in `_ensure_schema()`
- FTS5 triggers (insert/update/delete sync)
- `rebuild_fts()` — full rebuild from jobs table
- `_build_search_query()` — the query builder from spec 04
- `find_similar()` — structured field matching
- Ranking formula with company_preferences bonuses/penalties
- `search()` method integration
**Tests:** FTS search with various queries; ranking with preferences; similar job matching

### Bead 4b — Data Migration + Integration Test
**Specs:** 02-data-model.md (migration), 01-architecture.md (section 14)
**Package:** Migration scripts + integration tests
**Deliverables:**
- Verify `_ensure_schema()` correctly migrates existing `data/jobs.db`
- Backfill: `company_raw` from `company`, `company_id` from name match, ATS info on companies, run tracking
- End-to-end test: `jbs init` → `jbs scrape --sources remoteok` → `jbs enrich --stage rules` → `jbs search`
- Verify existing 3,061 jobs survive migration with correct company links
**Tests:** Integration test with copy of real DB; full pipeline E2E test

---

## Parallelization Plan

| Phase | Beads | Workers | Dependencies |
|-------|-------|---------|-------------|
| Phase 0 | 0a, 0b, 0c | 3 parallel | None |
| Phase 1 | 1a, 1b | 2 parallel | Phase 0 complete |
| Phase 2 | 2a-2e, 3b, 3c, 4a | 8 parallel | 1b for scrapers; 1a for 3b, 3c, 4a |
| Phase 3 | 3a, then 3d | serial | 3a needs 2a-2e; 3d needs 3a+3b+3c |
| Phase 4 | 4b | 1 | All above |

**Key optimizations (from review):**
- 4a (FTS) moves to Phase 2 — it only needs Store (1a), not CLI. Off the critical path.
- 3b (Enrichment) and 3c (Discovery) start in Phase 2 alongside scrapers.
- Scrapers (2a-2e) depend on 1b only, NOT 1a — they don't import Store.

**Critical path:**
```
Phase 0 → 1a → max(3b, 2a-2e + 3a) → 3d → 4b
```
If 3b (enrichment) takes longer than (slowest scraper + 3a), it becomes the bottleneck.

**Actual schedule:**
```
Phase 0: 0a, 0b, 0c              (3 parallel)
Phase 1: 1a, 1b                  (2 parallel)
Phase 2: 2a-2e, 3b, 3c, 4a      (8 parallel at peak — 2d/2e finish fast)
Phase 3: 3a → 3d                 (serial)
Phase 4: 4b                      (integration test)
```

**`__init__.py` strategy:** Bead 1b creates `jbs/scrapers/__init__.py` with all 5 import lines already present. Each scraper bead (2a-2e) creates its .py file to satisfy the import. No worktree conflicts on `__init__.py`.

Total beads: 16
Max concurrent workers: 8 (Phase 2), practical minimum: 3-4 worker pairs
Estimated worker pairs needed: 4 (handles all phases with reasonable throughput)
