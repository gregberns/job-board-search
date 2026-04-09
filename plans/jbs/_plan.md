# jbs Implementation Plan

## Goal

Rewrite the job-board-search codebase from a haphazard collection of scripts + JobSpy submodule into `jbs`, a clean local-first CLI tool. Python 3.12, SQLite, Click + Rich.

## Source Specs

| Spec | File | What It Defines |
|------|------|-----------------|
| 00 - Overview | `specs/00-overview.md` | Vision, prerequisites, first-run, workflows |
| 01 - Architecture | `specs/01-architecture.md` | Package structure, plugin system, orchestrator, Store, CLI tree, error handling |
| 02 - Data Model | `specs/02-data-model.md` | 8 tables, indexes, company resolution, token lifecycle, migration |
| 03 - CLI UX | `specs/03-cli-ux.md` | All CLI commands, options, output formats, error messages |
| 04 - Search & Ranking | `specs/04-search-ranking.md` | FTS5, structured filters, ranking formula, SearchQuery |
| 05 - Enrichment | `specs/05-enrichment.md` | 4-stage pipeline, dual LLM backend, cost tracking |
| HN Careers | `specs/hn-careers-pipeline.md` | Token discovery from HN, careers page crawling |

## Architecture Summary

```
jbs/
├── cli.py              # Click CLI entry point
├── config.py           # TOML config loading
├── store.py            # All SQLite access
├── models.py           # Dataclasses (Job, ScrapeResult, SearchQuery, etc.)
├── orchestrator.py     # Sequential source execution, concurrent boards
├── enrich.py           # 4-stage enrichment pipeline
├── util.py             # Inlined helpers from JobSpy
└── scrapers/
    ├── __init__.py     # @register decorator, plugin registry
    ├── base.py         # ScraperPlugin ABC, PluginMeta, ScrapeContext
    ├── ats_base.py     # ATSBoardScraper (threads, rate limiting, error isolation)
    ├── greenhouse.py   # Two-pass fetch, 10 workers, 50ms interval
    ├── lever.py        # Rate-limited, 2 workers, 500ms interval
    ├── ashby.py        # JSON sanitization, structured compensation
    ├── remoteok.py     # Single API call
    └── hn.py           # Algolia search, comment parsing
```

Supporting files:
```
pyproject.toml          # [project.scripts] jbs = "jbs.cli:main"
config.toml             # Optional user config
tokens/                 # Import source for jbs init
data/                   # jobs.db lives here
tests/
├── fixtures/           # Saved HTTP responses
├── test_store.py
├── test_scrapers.py
└── test_cli.py
```

## Key Design Decisions

1. **No JobSpy submodule** — inline utilities, rewrite scrapers
2. **Tokens in DB** — `companies` table is the token registry
3. **Companies first-class** — FK from jobs, objective/subjective separation
4. **Sequential sources, concurrent boards** — clean logging, thread pools for I/O
5. **Scrapers never raise** — errors in ScrapeResult
6. **Dual LLM backend** — Agent SDK (subscription) default, Batch API optional
7. **FTS5 for search** — with structured filters and simple ranking formula
8. **Idempotent migration** — `_ensure_schema()` on every Store init

## Implementation Beads

See [beads.md](beads.md) for the full implementation task breakdown.

## Migration Path

1. Build `jbs/` package alongside existing code
2. `jbs init` migrates existing `data/jobs.db` (additive schema changes)
3. Verify parity with old pipeline
4. Remove JobSpy submodule, run_search.py, scripts/
