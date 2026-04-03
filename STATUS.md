# Project Status

## Overview
Extending JobSpy with 5 new scrapers (Greenhouse, Lever, Ashby, RemoteOK, HN Who's Hiring) targeting SMB job sources, with JSONL output and dedup.

## Task Status

| # | Task | Status | Notes |
|---|------|--------|-------|
| 01 | Model Changes | Done | Site enum, ScraperInput fields, JobPost.board_token, ScraperException |
| 02 | Shared Utilities | Done | ATSBoardScraper base, filter_jobs, parse_location, extract_salary_from_text, html_to_markdown |
| 03 | Registration & Wiring | Done | All 5 scrapers registered in SCRAPER_MAPPING, params wired through scrape_jobs() |
| 04 | Token Bootstrapping | Done | 540 Greenhouse + 251 Lever raw tokens extracted; ashby.txt (25 curated); validation script ready |
| 05 | RemoteOK Scraper | Done | Single API call, all-remote, salary/location parsing |
| 06 | Greenhouse Scraper | Done | Two-pass fetch (lightweight list then detail), 20 concurrent workers |
| 07 | Lever Scraper | Done | Rate-limited (0.5s, 2 workers), epoch-ms dates, commitment mapping |
| 08 | Ashby Scraper | Done | JSON control-char sanitization, structured compensation with fallback |
| 09 | HN Scraper | Done | Algolia search_by_date, pipe-delimited comment parsing |
| 10 | Runner Script | Done | run_search.py with incremental JSONL, CLI args, token loading |
| 11 | Dedup Utility | Done | Normalized company+title key, richest-record retention |
| 12 | End-to-End Test | Done | All 5 sources return data, all quality checks pass |

## E2E Test Results (2026-04-01)
- All 5 sources returned jobs in a combined scrape (50 jobs, 10 per source)
- No null IDs, all URLs valid HTTP(S), 100% description population
- No duplicate IDs within any source
- All 13 compensation values positive
- JSONL output valid, dedup runs clean

## Files Created/Modified

### New files
- `JobSpy/jobspy/ats_base.py` — ATSBoardScraper base class
- `JobSpy/jobspy/greenhouse/__init__.py` — Greenhouse scraper
- `JobSpy/jobspy/lever/__init__.py` — Lever scraper
- `JobSpy/jobspy/ashby/__init__.py` — Ashby scraper
- `JobSpy/jobspy/remoteok/__init__.py` — RemoteOK scraper
- `JobSpy/jobspy/hn/__init__.py` — HN scraper
- `scripts/bootstrap_tokens.py` — Token extraction from awesome-easy-apply
- `scripts/validate_tokens.py` — Token validation against live APIs
- `scripts/dedup.py` — Post-processing deduplication
- `scripts/__init__.py` — Package init for imports
- `tokens/ashby.txt` — Curated Ashby board names (25)
- `tokens/greenhouse_raw.txt` — Raw Greenhouse tokens (540)
- `tokens/lever_raw.txt` — Raw Lever tokens (251)
- `run_search.py` — Main runner script

### Modified files
- `JobSpy/jobspy/model.py` — Site enum (+5), ScraperInput (+4 fields), JobPost (+board_token)
- `JobSpy/jobspy/exception.py` — Added ScraperException
- `JobSpy/jobspy/util.py` — Added filter_jobs, parse_location, extract_salary_from_text, html_to_markdown, board_token to desired_order
- `JobSpy/jobspy/__init__.py` — Registered 5 scrapers, wired new params

## Next Steps

1. **Validate tokens** — Run `python scripts/validate_tokens.py` to produce `tokens/greenhouse.txt` and `tokens/lever.txt` (validated against live APIs). Raw tokens are extracted but haven't been validated yet.

2. **Full production run** — Run `python run_search.py` with all 5 sources using validated tokens. Review output quality and volume at scale (expect 1000+ jobs).

3. **Tune scraper behavior** — After a production run, review:
   - Greenhouse two-pass filtering effectiveness (are we fetching too many/few details?)
   - Lever 404 rate (expected ~80% failures from stale tokens)
   - HN comment parse rates (company ~60%, location ~50%, salary ~30%)
   - RemoteOK result volume and relevance

4. **Build filtering/ranking layer** — The raw JSONL output needs a consumer: keyword scoring, location filtering for US-based SMB roles, dedup across days, etc.

5. **Schedule recurring runs** — Set up a cron or similar to run `run_search.py` daily/weekly to build up a historical dataset.

6. **Expand token lists** — Grow the Ashby list beyond 25, discover new Greenhouse/Lever boards over time.
