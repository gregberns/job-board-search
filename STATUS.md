# Project Status — jbs

## What This Is

`jbs` — a local-first CLI tool for finding the right engineering job. Scrapes 5 job board sources, stores in SQLite, enriches with LLM classification + local embeddings, and provides keyword + semantic search/filter/annotation. Python 3.12, Click + Rich CLI, Claude Haiku for enrichment via subscription, MLX for local embeddings on Apple Silicon.

## Current State: Company Research Phase (2026-04-14)

Core tool fully operational. Now in active company research — searching, evaluating, and building a pipeline of target companies.

### Database (data/jobs.db)
- **4,801 jobs** (4,292 active, 509 inactive)
- **1,212 companies** (1,181 enriched with ai_native, industry, description)
- **1,253 engineering roles** identified by LLM
- **4,292 summary embeddings** (BGE-small 384d via MLX)
- **4,292 description embeddings** (nomic-v1.5 768d via MLX)
- Sources: Greenhouse (3,239), HN (624), Lever (557), Ashby (301), RemoteOK (80)

### What Works
- `jbs init` — create DB, import tokens from flat files
- `jbs scrape` — all 5 sources (Greenhouse, Lever, Ashby, RemoteOK, HN)
- `jbs enrich --stage rules` — free rule-based extraction (seniority, salary, visa, llm_filter)
- `jbs enrich --stage jobs` — LLM job classification via Claude CLI
- `jbs enrich --stage companies` — LLM company enrichment
- `jbs enrich --stage embeddings` — local embedding generation (MLX, ~15 min for 4,292 jobs, 1.7GB RSS)
- `jbs search` — FTS5 + structured filters
- `jbs search --vec "query"` — hybrid semantic search (FTS5 + KNN + RRF + cross-encoder re-rank)
- `jbs models list` — shows cached model status
- `jbs models download` — downloads embedding models
- `jbs show`, `jbs annotate`, `jbs apply`, `jbs stats`, `jbs tokens` — all working
- **527 tests passing**

### Company Research Pipeline
- **6 batches** of companies researched (35+ from batches 1-3 with user feedback, 18 AI-first, 16 Rust, 18 remote-first)
- **Pipeline structure** at `company-research/pipeline/` — discovered → investigating → reaching-out → contacted → interviewing → passed
- **Framework** at `/Users/gb/github/job-search/what-im-looking-for/` — four-filter flywheel (Dead Inside? → Hard Problem? → Software = Lever? → Compounds?)
- **Pass patterns** documented at `company-research/pass-patterns.md`
- **Framework search criteria** at `company-research/framework-search-criteria.md`

### Pipeline Status (as of 2026-04-14)
- **ADVANCE (3):** PermitFlow, Kallikor, Foxglove
- **MAYBE (10):** Hasura, Nominal, V7, Pylon, Augury, SewerAI, Tractian, Duffel, Slip Robotics, Sylvera
- **BLOCKED (8):** Gecko Robotics, Terminal Industries, Vorto, Ambience, Abridge, Deeptune (location), Ahrefs (not hiring), Imandra (no response)
- **PASS (12+):** Legal x4, consumer x2, infra, BI, climate/energy x2, healthcare, defense
- **Batch 4-6 pending review:** user reviewed batch 4 (all robotics misses), batch 5 (mostly robotics misses), batch 6 (remote-first, pending)

### Token Coverage
- **Greenhouse:** 580 tokens (22 added 2026-04-13)
- **Lever:** 271 tokens (15 added 2026-04-13)
- **Ashby:** 99 tokens (28 added 2026-04-13)
- **Workable:** 29 tokens (new, scraper not yet built)
- **Not scraped:** Gem (Nominal), Comeet (Darrow), custom career pages

### Key Lessons from Research
- Standard ATS boards over-represent devtools, fintech, and enterprise SaaS
- "AI + physical world" searches pull toward robotics (wrong) — need platform/data layer
- On-site/hybrid blocks many otherwise-interesting companies — filter remote-first early
- User's skillset is backend systems, data platforms, APIs, business logic — NOT robotics, CV, embedded, materials science
- FP stacks (Elixir, Haskell, Rust, Scala, OCaml) are a strong positive signal but can't save a bad domain fit
- The flywheel framework (Value → Lever → Compound → More Value) is the best discriminator

---

## What Was Done This Session (2026-04-10 through 2026-04-14)

### Company Research
- Ran 10+ semantic vector searches across the job database
- Spawned 8 research agents covering: LLM-compounds-product, FP languages, ATS tokens, broad discovery, Workable tokens, AI-first, Rust/systems, remote-first
- Created 6 batch review files with 100+ companies researched
- User reviewed batches 1-3 (35 companies with detailed feedback) and batch 4 (18 companies, all robotics misses)
- Established pipeline structure and pass-pattern documentation

### Infrastructure
- Added ~100 new ATS tokens across 4 platforms
- Created `tokens/workable.txt` with 29 Workable tokens
- Wrote Workable scraper spec (`specs/07-workable-scraper.md`)
- Moved research to tracked `company-research/` directory
- Updated CLAUDE.md with research pipeline docs
- Created private GitHub repo and pushed: https://github.com/gregberns/job-board-search

---

## Specs

All specs in `specs/`, **in sync with code** as of 2026-04-10:
- 00-overview, 01-architecture, 02-data-model, 03-cli-ux
- 04-search-ranking, 05-enrichment, 06-vector-search
- 07-workable-scraper (new, not yet implemented)
- hn-careers-pipeline

## Known Issues
- Salary regex overmatch on some Greenhouse postings
- Some company names are slug-derived
- `jbs tokens validate` not tested end-to-end
- `jbs tokens discover` not tested end-to-end
- mlx-embedding-models progress bars are noisy (tqdm output during search)
- Workable scraper not yet built (spec ready)
- Many new tokens not yet scraped (added 2026-04-13, last scrape 2026-04-09)

## Development Process

See `plans/PROCESS.md` and `CLAUDE.md`. Use kerf for non-trivial features. Delegate implementation via beads to worker agents. Don't implement directly — orchestrate.
