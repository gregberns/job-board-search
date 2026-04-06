# Project Status

## Overview
Job board scraper extending JobSpy with 5 sources (Greenhouse, Lever, Ashby, RemoteOK, HN Who's Hiring). Scrapes all jobs unfiltered, stores in SQLite (`data/jobs.db`), classifies via Haiku subagents (engineering_role, ai_native, seniority, domain, industry).

## Task Status

| # | Task | Status | Notes |
|---|------|--------|-------|
| 01 | Model Changes | Done | Site enum, ScraperInput fields, JobPost.board_token, ScraperException |
| 02 | Shared Utilities | Done | ATSBoardScraper base, filter_jobs, parse_location, extract_salary_from_text, html_to_markdown |
| 03 | Registration & Wiring | Done | All 5 scrapers registered in SCRAPER_MAPPING, params wired through scrape_jobs() |
| 04 | Token Bootstrapping | Done | 540 Greenhouse + 251 Lever raw tokens extracted; ashby.txt (25 curated); validation script ready |
| 05 | RemoteOK Scraper | Done | Single API call, all-remote, salary/location parsing |
| 06 | Greenhouse Scraper | Done | Two-pass fetch, 10 concurrent workers, 50ms detail throttle |
| 07 | Lever Scraper | Done | Rate-limited (0.5s, 2 workers), epoch-ms dates, commitment mapping |
| 08 | Ashby Scraper | Done | JSON control-char sanitization, structured compensation with fallback |
| 09 | HN Scraper | Done | Algolia search_by_date, pipe-delimited comment parsing |
| 10 | Runner Script | Done | run_search.py: JSONL + SQLite output, timestamped runs, no default search filter |
| 11 | Dedup Utility | Done | Normalized company+title key, richest-record retention |
| 12 | End-to-End Test | Done | All 5 sources return data, all quality checks pass |
| 13 | Remove search_term default | Done | Scrapes everything by default; --search-term available but None by default |
| 14 | 404 token tracking | Done | BoardNotFoundError → tokens/{source}_404.txt, auto-skipped on future runs |
| 15 | Timestamped output files | Done | jobs_{YYYY-MM-DD_HHMMSS}.jsonl — no overwrites between runs |
| 16 | Rate limiting tuning | Done | Greenhouse 20→10 workers + 50ms detail delay; results_wanted caps removed |
| 17 | SQLite database | Done | data/jobs.db with jobs, companies, runs tables |
| 18 | JSONL import script | Done | scripts/import_jsonl.py — loads JSONL into DB with location parsing |
| 19 | Job classification (Haiku) | Done | engineering_role, seniority, domain via parallel Haiku subagents |
| 20 | Company enrichment (Haiku) | Done | description, industry, ai_native (0.0-1.0 confidence) on companies table |
| 21 | Work arrangement enrichment | Done | Haiku-classified remote/hybrid/onsite/unknown on 1,229 jobs |
| 22 | SQLite write from runner | Done | run_search.py writes to both JSONL and jobs.db, upserts companies |
| 23 | HN careers pipeline | Done | scripts/hn_careers.py: harvest-ats, discover, detect-ats, extract |
| 24 | HN ATS token harvest | Done | 64 new tokens (44 Ashby, 17 Greenhouse, 3 Lever) from HN URLs + careers pages |
| 25 | HN careers page discovery | Done | 160 careers pages found from 238 companies |
| 26 | HN ATS embed detection | Done | 33 additional ATS embeds found in careers page HTML |
| 27 | HN custom page extraction | Done | 302 jobs extracted from static careers pages via Haiku |
| 28 | Full scrape with new tokens | Done | 2,761 jobs scraped, 959 new inserted (Greenhouse +512) |

## Current Database Stats (2026-04-05)

- **3,061 jobs** across 5 runs
- **575+ companies** with descriptions, industry, ai_native scores
- Sources: Greenhouse (1,907), HN (574), Lever (325), Ashby (200), RemoteOK (55)
- 67 ATS tokens harvested from HN careers pipeline

## Key Architecture Decisions

- **Scrape everything, filter later** — no search_term filtering at scrape time
- **SQLite over flat files** — queryable, supports incremental enrichment, tracks runs
- **ai_native is company-level** — 0.0-1.0 confidence score on companies table, not per-job
- **Haiku subagents for classification** — batch 50 items, fan out in parallel, merge into DB
- **404 token log** — tokens/{source}_404.txt auto-pruned on each run

## Files Created/Modified

### New files (Phase 3 — HN careers pipeline)
- `scripts/hn_careers.py` — HN careers page pipeline (harvest-ats, discover, detect-ats, extract)
- `specs/hn-careers-pipeline.md` — Spec for the HN careers subsystem

### New files (Phase 2 — SQLite + classification)
- `scripts/init_db.py` — SQLite schema (jobs, companies, runs, hn_career_pages tables)
- `scripts/import_jsonl.py` — JSONL→DB loader with location parsing
- `data/jobs.db` — SQLite database

### New files (Phase 1)
- `JobSpy/jobspy/ats_base.py` — ATSBoardScraper base class + BoardNotFoundError
- `JobSpy/jobspy/greenhouse/__init__.py` — Greenhouse scraper
- `JobSpy/jobspy/lever/__init__.py` — Lever scraper
- `JobSpy/jobspy/ashby/__init__.py` — Ashby scraper
- `JobSpy/jobspy/remoteok/__init__.py` — RemoteOK scraper
- `JobSpy/jobspy/hn/__init__.py` — HN scraper
- `scripts/bootstrap_tokens.py` — Token extraction from awesome-easy-apply
- `scripts/validate_tokens.py` — Token validation against live APIs
- `scripts/dedup.py` — Post-processing deduplication
- `run_search.py` — Main runner script (JSONL + SQLite)

### Modified files
- `JobSpy/jobspy/model.py` — Site enum (+5), ScraperInput, JobPost.board_token, JobResponse.failed_tokens
- `JobSpy/jobspy/__init__.py` — 5 scrapers registered, failed_tokens passthrough via df.attrs
- `JobSpy/jobspy/util.py` — filter_jobs, parse_location, extract_salary_from_text, html_to_markdown

## Next Steps

1. **Classify new jobs** — Run Haiku enrichment on the ~959 new jobs from the latest scrape (engineering_role, seniority, domain, work_arrangement).

2. **Enrich new companies** — Run Haiku on newly discovered companies for description, industry, ai_native scores.

3. **Schedule recurring runs** — Automate daily/weekly scrapes to build historical dataset.

4. **Validate tokens** — Run `python scripts/validate_tokens.py` to prune stale Greenhouse/Lever tokens.

5. **Playwright for SPA pages** — 20 HN company careers pages are JS-rendered SPAs that need headless browser rendering.
