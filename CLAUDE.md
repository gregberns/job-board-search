# CLAUDE.md

## Project Overview

Job board scraper extending [JobSpy](https://github.com/Bunsly/JobSpy) with 5 new sources targeting small-to-medium businesses: **Greenhouse**, **Lever**, **Ashby**, **RemoteOK**, and **HN Who's Hiring**. Outputs JSONL files for downstream filtering.

## Quick Start

```bash
# Activate the venv
source JobSpy/.venv/bin/activate

# Run all scrapers (uses tokens/ directory for ATS board lists)
python run_search.py

# Run a single source
python run_search.py --sources remoteok

# Validate ATS tokens against live APIs (produces tokens/greenhouse.txt, tokens/lever.txt)
python scripts/validate_tokens.py

# Deduplicate a JSONL output file
python scripts/dedup.py data/jobs_2026-04-01.jsonl
```

## Architecture

### Directory Layout

```
job-board-search/
├── CLAUDE.md              # This file
├── PLAN.md                # Full implementation plan with architecture decisions
├── RESEARCH.md            # API research for all job board sources
├── STATUS.md              # Task completion status and E2E test results
├── run_search.py          # Main entry point — runs scrapers, writes JSONL, dedup
├── scripts/
│   ├── bootstrap_tokens.py  # Extract ATS tokens from awesome-easy-apply repo
│   ├── validate_tokens.py   # Validate tokens against live APIs
│   └── dedup.py             # Post-processing deduplication by (company, title)
├── tokens/
│   ├── greenhouse_raw.txt   # Raw tokens (540, unvalidated)
│   ├── lever_raw.txt        # Raw tokens (251, unvalidated)
│   └── ashby.txt            # Curated Ashby board names (25)
├── data/                    # Output directory (created at runtime)
└── JobSpy/                  # Forked JobSpy library (git submodule)
    └── jobspy/
        ├── __init__.py        # scrape_jobs() — main API, SCRAPER_MAPPING
        ├── model.py           # Site enum, ScraperInput, JobPost, Scraper base
        ├── ats_base.py        # ATSBoardScraper — shared base for ATS scrapers
        ├── util.py            # filter_jobs, parse_location, extract_salary_from_text, html_to_markdown
        ├── exception.py       # ScraperException + legacy per-site exceptions
        ├── greenhouse/        # Two-pass fetch (metadata then detail), 20 workers
        ├── lever/             # Rate-limited (0.5s, 2 workers), epoch-ms dates
        ├── ashby/             # JSON control-char sanitization, structured compensation
        ├── remoteok/          # Single API call, all-remote, salary/location parsing
        └── hn/                # Algolia search_by_date, pipe-delimited comment parsing
```

### Key Patterns

- **ATSBoardScraper** (`ats_base.py`): Shared base for Greenhouse/Lever/Ashby. Subclasses implement `get_tokens()`, `fetch_board()`, `map_job()`. Base handles concurrency, rate limiting, error isolation per board.
- **Client-side filtering**: All new scrapers fetch everything then filter via `filter_jobs()` in `util.py` (search_term, hours_old, is_remote).
- **Incremental JSONL writes**: `run_search.py` writes after each source completes so partial results survive crashes.
- **Two-pass Greenhouse**: Lightweight metadata first, full `content=true` only for matched jobs (saves ~90% bandwidth).
- **ID prefixes**: Each scraper prefixes IDs (`gh-`, `lever-`, `ashby-`, `rok-`, `hn-`) for cross-source dedup.

### Token Management

ATS scrapers (Greenhouse, Lever, Ashby) require board token files in `tokens/`. The pipeline is:
1. `scripts/bootstrap_tokens.py` — extracts raw tokens from awesome-easy-apply README
2. `scripts/validate_tokens.py` — pings live APIs, writes validated `tokens/greenhouse.txt` and `tokens/lever.txt`
3. `tokens/ashby.txt` — manually curated (no automated source)

`run_search.py` prefers validated files and falls back to raw files.

## Conventions

- **Python 3.12** with the venv at `JobSpy/.venv/`
- All new scrapers follow the existing JobSpy pattern: subclass `Scraper` (or `ATSBoardScraper`), implement `scrape()`, return `JobResponse`
- `scrape_jobs()` in `JobSpy/jobspy/__init__.py` is the main API; new params are explicit kwargs (not buried in `**kwargs`)
- JobPost IDs are prefixed with source name (e.g., `gh-12345`, `lever-abc123`)
- Compensation is extracted from structured API data when available, falling back to `extract_salary_from_text()` on description
- The `board_token` field on JobPost traces which ATS board a job came from

## Running Tests

No formal test suite yet. Verification is done via E2E runs:
```bash
python run_search.py --sources remoteok --results-wanted 10
```

## Important Notes

- **JobSpy is a git submodule** (has its own `.git`). Don't commit JobSpy changes to this repo's git — they're local modifications to the fork.
- **Token files may contain stale entries** — expect 30-50% Greenhouse 404s and ~80% Lever 404s from raw tokens. Validated files are much cleaner.
- **HN parsing is best-effort** — ~60% company name, ~50% location, ~30% salary extraction from unstructured comment text.
- **RemoteOK can rate-limit** — uses proper User-Agent header; returns empty on 429.
