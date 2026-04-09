# Project Status — jbs Rewrite

## What This Is

Rewriting a haphazard job board scraper (JobSpy submodule + scripts + flat files) into `jbs`, a clean local-first CLI tool for finding the right engineering job. Python 3.12, SQLite, Click + Rich CLI.

**Current state:** The old scraper pipeline works (5 sources, 3,061 jobs in DB, enrichment via Haiku subagents). We are now designing the clean rewrite via specs before implementation.

## Spec Status

| Spec | File | Status | Summary |
|------|------|--------|---------|
| 00 - Overview | `specs/00-overview.md` | **Done** | Vision, prerequisites, first-run (`jbs init` → `jbs scrape` → `jbs search`), token management, core workflow, data lifecycle. Updated for DB-based tokens and dual LLM backend. |
| 01 - Architecture | `specs/01-architecture.md` | **Done** | Package structure (`jbs/`), scraper plugin system, orchestrator, token-in-DB architecture, CLI command tree, error handling, migration path. No JobSpy submodule. |
| 02 - Data Model | `specs/02-data-model.md` | **Done** | 8 tables. Companies are first-class (ATS tokens as columns). Objective/subjective data separation. Company resolution algorithm. Token lifecycle. Full schema + indexes + migration. |
| 03 - CLI UX | `specs/03-cli-ux.md` | **Done** | 10 commands: init, scrape, search, show, enrich, annotate, apply, stats, tokens (validate/add/list/discover). Aligned with specs 01/02/05. Dual LLM backend, DB-based tokens, `job_annotations`/`company_preferences`. |
| 04 - Search & Ranking | `specs/04-search-ranking.md` | **Done** | FTS5 + structured filters + ranking formula. JOINs through company_id for industry/ai_native. `company_preferences` for ranking. `engineering_only` opt-in. `include_inactive`. Normalized salary. `job_summary` in results. |
| 05 - Enrichment | `specs/05-enrichment.md` | **Done** | 4-stage pipeline: cleanup, rules, LLM jobs, LLM companies. Dual LLM backend: Agent SDK (default, uses subscription) + Batch API (optional fast path with API key). Individual classification with full descriptions via Batch API; batched 20/call with 2KB truncation via Agent SDK. |
| HN Careers | `specs/hn-careers-pipeline.md` | **Done** | Token discovery as `jbs tokens discover`. 3 phases: harvest ATS tokens, discover careers pages, detect ATS on careers pages. Integrated into jbs architecture. Phase 4 (custom extraction) deferred to v2. |

## Key Design Decisions Made

### Data Model (Spec 02)
- **Companies are first-class entities** with `id`, `name`, `name_normalized` (dedup key)
- **One ATS platform per company**: `ats_platform` (greenhouse/lever/ashby) + `ats_token` (board slug), with `UNIQUE(ats_platform, ats_token)`
- **Tokens live in the DB**, not flat files. `companies` table IS the token registry. `token_status`: unchecked → valid / stale
- **Objective vs subjective separation**: `companies` (facts) vs `company_preferences` (user opinions). `jobs` (facts) vs `job_annotations` + `job_tags` (user opinions)
- **Company resolution at scrape time**: ATS token match → normalized name match → create new record
- **`name_normalized`**: lowercase, strip corporate suffixes (Inc/LLC/Ltd/Corp/PBC/GmbH), remove non-alphanumeric
- **No `company_aliases` table** — one normalized name per company, keep it simple
- **`company_raw` on jobs** — keep original scraper string for debugging

### Architecture (Spec 01)
- **No JobSpy submodule** — inline ~6 utilities, rewrite scrapers as `jbs/scrapers/*.py`
- **`@register` decorator** with explicit imports, no magic discovery
- **Sequential sources, concurrent boards** — sources run one at a time (clean logging), each ATS source uses ThreadPoolExecutor internally
- **Threads, not asyncio** — requests is synchronous, thread pools fit I/O-bound HTTP
- **Scrapers never raise** — errors go in `ScrapeResult.errors`
- **Rate limiting hardcoded per scraper**: Greenhouse 50ms/10 workers, Lever 500ms/2 workers, Ashby 0ms/10 workers
- **`jbs init`** imports tokens from flat files (one-time). `jbs tokens validate` pings APIs. `jbs tokens add` for manual additions.
- **Store class** handles all DB access — no raw SQL elsewhere

### Enrichment (Spec 05)
- **Dual LLM backend**: Claude Agent SDK (default, uses subscription) + Anthropic Batch API (optional, requires API key)
- **Agent SDK**: batches 20 jobs per call, 2KB description truncation, ~7 min for 3000 jobs
- **Batch API**: individual calls with full descriptions, ~5 min for 3000 jobs, ~$1.20
- **Stage 0**: Fix Greenhouse HTML (stored as raw HTML), RemoteOK encoding (78% broken Unicode), boilerplate stripping (in memory, not persisted)
- **Stage 1 (rules, free)**: seniority from title, is_management, salary normalization + FX conversion, visa_sponsorship (~10 regex patterns), years_experience
- **Stage 2 (LLM jobs)**: engineering_role, seniority refinement, domain, tech_stack, job_summary (1-2 sentence summary — highest-value new feature)
- **Stage 3 (LLM companies)**: description, industry, ai_native (0.0-1.0), funding_stage, size_estimate
- **Tech stack extraction by LLM**, not regex — catches semantic references regex misses
- **`enriched_at` watermark** on jobs and companies. `--force` flag for re-enrichment.
- **User feedback loop deferred to v2** — store annotations now, compute preference profile after 50+ annotations

### Filtering (Spec 04 — needs revision)
- Replace boolean `engineering_only` with generic category-based filtering
- User should be able to set default filters (e.g., "never show sales/marketing jobs") that persist
- Unknown values should be ranked neutrally, not penalized or hidden
- FTS5 for text search, structured filters for everything else
- Simple hardcoded ranking formula (not configurable)

## What Needs To Happen Next

### All specs are finalized. Implementation is next.

**Implementation plan:** See `plans/jbs/beads.md` for the full bead breakdown — 16 beads across 5 layers.

**Summary of layers:**
- **L0 (Foundation):** Package scaffold, data models, utilities
- **L1 (Core):** Store (full schema), scraper plugin system
- **L2 (Scrapers):** Greenhouse, Lever, Ashby, RemoteOK, HN (parallel)
- **L3 (Integration):** Orchestrator, enrichment, HN discovery, CLI
- **L4 (Polish):** FTS5 search + ranking, data migration + E2E test

## Existing Codebase (what works today)

### Database
- `data/jobs.db` — 3,061 jobs, 575+ companies, 5 runs
- Sources: Greenhouse (1,907), HN (574), Lever (325), Ashby (200), RemoteOK (55)
- 1,795 jobs classified (engineering_role, seniority, domain)
- 572 companies enriched (description, industry, ai_native)

### Scrapers (in JobSpy submodule, will be rewritten)
- All 5 sources working: Greenhouse, Lever, Ashby, RemoteOK, HN
- Token files: 540 Greenhouse raw, 251 Lever raw, 25 Ashby curated
- 404 tracking: greenhouse_404.txt (44), lever_404.txt (36), ashby_404.txt (2)
- HN careers pipeline discovered 64 additional ATS tokens

### Known Data Quality Issues (to fix during rewrite)
- Greenhouse descriptions stored as raw HTML (not markdown)
- RemoteOK ~78% broken Unicode encoding
- Ashby structured salary not being captured (API has it, scraper doesn't extract)
- Salary extraction only captures 8-27% depending on source
- Two different company normalization functions with different behavior
- HN 53% NULL descriptions (inherent to source — comments, not postings)
- 42-71% of Greenhouse/Ashby descriptions have legal boilerplate
