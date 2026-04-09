# Project Status — jbs

## What This Is

`jbs` — a local-first CLI tool for finding the right engineering job. Scrapes 5 job board sources, stores in SQLite, enriches with LLM classification, and provides search/filter/annotation. Python 3.12, Click + Rich CLI, Claude Haiku for enrichment via subscription.

## Current State: Operational

The `jbs` package is fully built and running. All 5 scrapers work, enrichment pipeline runs end-to-end, search with FTS5 is functional.

### Database (data/jobs.db)
- **4,801 jobs** (4,292 active, 509 inactive)
- **1,212 companies** (1,181 enriched with ai_native, industry, description)
- **1,253 engineering roles** identified by LLM
- **1,070 job summaries** generated
- **584 valid tokens**, 279 stale, 0 unchecked
- Sources: Greenhouse (3,239), HN (624), Lever (557), Ashby (301), RemoteOK (80)

### LLM Pre-Filter
Jobs are pre-classified before LLM enrichment to reduce cost:
- 2,227 pass → sent to LLM
- 1,211 skip_mgmt, 920 skip_title, 296 skip_salary, 147 skip_seniority

### What Works
- `jbs init` — create DB, import tokens from flat files
- `jbs scrape` — all 5 sources (Greenhouse, Lever, Ashby, RemoteOK, HN)
- `jbs enrich --stage rules` — free rule-based extraction (seniority, salary, visa, years_exp, management, llm_filter)
- `jbs enrich --stage jobs` — LLM job classification via Claude CLI (engineering_role, domain, tech_stack, job_summary)
- `jbs enrich --stage companies` — LLM company enrichment (ai_native, industry, funding_stage, description)
- `jbs search` — FTS5 + structured filters (--engineering, --seniority, --domain, --ai-native, --salary-min, --remote, etc.)
- `jbs show <job-id>` — full job details
- `jbs annotate` — tags, rating, notes, pros/cons
- `jbs apply` — application tracking
- `jbs stats` — database overview
- `jbs tokens list/add/validate` — token management

### Known Issues
- Salary regex overmatch on some Greenhouse postings (e.g. SimpliSafe `$172,000,000`)
- Some company names are slug-derived (not yet updated from API responses)
- `jbs tokens validate` not yet tested end-to-end
- `jbs tokens discover` not yet tested end-to-end
- 518 tests passing, 1 skipped (migration test on corrupted DB)

## Specs

All 7 specs finalized in `specs/`:
- 00-overview, 01-architecture, 02-data-model, 03-cli-ux, 04-search-ranking, 05-enrichment, hn-careers-pipeline

Pre-filter spec in `specs/2026-04-pre-filter/`.

## Implementation

16 beads completed, tracked in `bd`. See `plans/jbs/beads.md` for the breakdown.

Post-build fixes:
- FTS5 content table (was contentless, broke UPDATE triggers)
- Salary magnitude heuristic ($154-190,000 → $154k-$190k)
- Token valid-after-scrape marking
- Claude CLI backend (replaces broken Agent SDK)
- CLI comma-separated filter parsing
- Incremental DB commits during enrichment

## Development Process

See `plans/PROCESS.md`. Commands in `.claude/commands/`:
- `/spec` — collaborative spec pipeline (problem space → decompose → research → spec → assembly)
- `/plan-implementation` — break specs into beads
- `/implement-beads` — execute beads with worker pairs
- `/spawn-workers` — ntm worker management

## What Could Come Next

- **Daily scrape cron** — `jbs scrape && jbs enrich --stage rules` on a schedule
- **Token discovery** — `jbs tokens discover` to harvest new ATS tokens from HN
- **Token validation** — `jbs tokens validate` to clean up stale tokens
- **Salary regex fix** — handle Greenhouse salary format edge cases
- **Search UX polish** — better table formatting, `--format table` column widths
- **v2 features** — user preference profiles from annotations, saved searches, HN careers page extraction
