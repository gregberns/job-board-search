# CLAUDE.md

## Project Overview

`jbs` — local-first CLI tool for finding engineering jobs. Scrapes 5 sources (Greenhouse, Lever, Ashby, RemoteOK, HN), stores in SQLite, enriches with LLM classification, provides search/filter/annotation.

## Quick Start

```bash
# Activate the venv
source JobSpy/.venv/bin/activate

# Install jbs CLI
pip install -e .

# Initialize DB and import tokens
jbs init

# Scrape all sources
jbs scrape

# Enrich (free rules, then LLM via subscription)
jbs enrich --stage rules
jbs enrich --stage jobs
jbs enrich --stage companies

# Search
jbs search --engineering --seniority senior,staff --ai-native 0.7
jbs search "infrastructure" --remote --salary-min 200000
```

## Architecture

### Package Layout

```
jbs/
├── cli.py              # Click CLI, all commands
├── config.py           # TOML config, defaults
├── store.py            # All SQLite access (Store class)
├── models.py           # Job, ScrapeResult, SearchQuery dataclasses
├── orchestrator.py     # Sequential source execution
├── enrich.py           # 4-stage enrichment pipeline
├── enrich_rules.py     # Stage 1: seniority, salary, visa, llm_filter
├── enrich_prompts.py   # LLM prompt templates
├── llm_backend.py      # Claude CLI + Batch API backends
├── discover.py         # HN token discovery
├── util.py             # Shared helpers (normalize, parse, filter)
└── scrapers/
    ├── __init__.py     # @register decorator, plugin registry
    ├── base.py         # ScraperPlugin ABC, PluginMeta, ScrapeContext
    ├── ats_base.py     # ATSBoardScraper (threads, rate limiting)
    ├── greenhouse.py   # Two-pass fetch, 10 workers
    ├── lever.py        # Rate-limited, 2 workers
    ├── ashby.py        # JSON sanitization, structured compensation
    ├── remoteok.py     # Single API call
    └── hn.py           # Algolia search, comment parsing
```

### Key Patterns

- **Store** handles all DB access — no raw SQL elsewhere
- **ATSBoardScraper** base for Greenhouse/Lever/Ashby with ThreadPoolExecutor, rate limiting, error isolation per board
- **Scrapers never raise** — errors go in `ScrapeResult.errors`
- **Company resolution at upsert time**: ATS token match → normalized name match → create new
- **LLM pre-filter**: `llm_filter` column tags jobs as send/skip before LLM enrichment
- **LLM backend**: Claude CLI (subscription) by default, Anthropic Batch API if ANTHROPIC_API_KEY set
- **FTS5** for full-text search with content table triggers

## Running Tests

```bash
source JobSpy/.venv/bin/activate
python -m pytest tests/ --tb=short        # 518 tests
python -m pytest tests/test_store.py -v   # Store only
python -m pytest tests/test_enrich_rules.py -v  # Enrichment rules
```

## CLI Commands

```
jbs init                          # Create DB, import tokens
jbs scrape [--sources X]          # Run scrapers
jbs enrich [--stage rules|jobs|companies] [--force] [--dry-run]
jbs search [QUERY] [--engineering] [--seniority X] [--domain X] [--ai-native N] [--remote] [--salary-min N]
jbs show <job-id> [--no-desc]     # Full job details
jbs annotate <job-id> [--tag X] [--rating N] [--note X]
jbs apply <job-id> [--stage X] [--list]
jbs stats [--runs N]
jbs tokens list|add|validate|discover
```

## Planning with kerf

This project uses kerf for structured planning. Before implementing non-trivial
changes (new features, refactors, bug investigations), create a kerf work:

  kerf new <codename>

This creates a work on the bench and shows the process to follow. The jig
(process template) guides you through structured passes — problem space,
decomposition, research, detailed spec, integration, and tasks.

### Key commands

  kerf new <codename>              Create a new work
  kerf show <codename>             See current state + jig instructions for next steps
  kerf status <codename>           Check current status
  kerf status <codename> <status>  Advance to next pass
  kerf shelve <codename>           Save progress when ending a session
  kerf resume <codename>           Pick up where you left off
  kerf square <codename>           Verify the work is complete
  kerf finalize <codename> --branch <name>  Package for implementation

### When to use kerf

- New features or subsystems → kerf new --jig plan (or spec)
- Bug investigations → kerf new --jig bug
- Trivial changes (typos, one-line fixes) → skip kerf, just make the change

### Workflow

1. kerf new <codename> — read the output, it tells you exactly what to do
2. Follow each pass: write the artifacts, advance status
3. kerf show <codename> — if you lose context, this shows where you are
4. kerf shelve / kerf resume — for multi-session work
5. kerf square — verify everything is complete
6. kerf finalize — package into a git branch for implementation

Don't skip the planning process. Measure twice, cut once.

## Development Process

See `plans/PROCESS.md`. Use `/spec` command for new features.

## Company Research

Research and pipeline tracking live in `company-research/` (git-tracked, unlike `data/`).

### Layout

```
company-research/
├── batch-01-top-picks.md           # Agent research + user feedback
├── batch-02-industrial-ops.md      # Agent research + user feedback
├── batch-03-legal-health-climate-fp.md  # Agent research + user feedback
├── raw-agent-*.txt                 # Raw agent output (provenance)
└── pipeline/
    ├── README.md                   # Funnel stages and conventions
    ├── discovered.md               # Identified as interesting
    ├── investigating.md            # Actively researching
    ├── reaching-out.md             # Preparing contact
    ├── contacted.md                # Outreach sent
    ├── interviewing.md             # Active interviews
    └── passed.md                   # Not pursuing (with reasons)
```

### Conventions

- **Batch files have user feedback** (the "Your take:" sections) -- never overwrite or regenerate them.
- **Pipeline stage files are append-only logs** -- add dated entries, never remove.
- **Raw agent files** are kept for provenance, not meant for direct reading.
- **Framework reference**: Job search criteria and recruiter brief live at `/Users/gb/github/job-search/what-im-looking-for/` (context.md, framework.md, recruiter-brief.md).

### Token Files

- `tokens/` directory contains ATS token files (greenhouse, lever, ashby, workable) used as import source by `jbs init`.
- After init, the database is the source of truth -- token files are just the seed.
- New tokens discovered during research get added to the token files first, then imported via `jbs init`.

## Important Notes

- **Venv** is at `JobSpy/.venv/` (historical, from the submodule era)
- **JobSpy is a git submodule** — don't commit JobSpy changes to this repo
- **Token files** in `tokens/` are an import source for `jbs init` — after init, DB is source of truth
- **LLM enrichment** uses Claude subscription via `claude` CLI — no API key needed
- **data/jobs.db** is in `.gitignore` — it's runtime data, not checked in
