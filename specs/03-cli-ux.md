# Spec: `jbs` CLI

## Overview

Unified CLI replacing `python run_search.py`, `python scripts/validate_tokens.py`, and raw SQLite queries. Built with `click` + `rich`.

**9 commands:** `init`, `scrape`, `search`, `show`, `enrich`, `annotate`, `apply`, `stats`, `tokens` (subcommand group with `validate`, `add`, `list`).

## Command Tree

```
jbs [--db PATH] [--format table|json|csv] [--no-color] [--verbose]
 |
 +-- init                           # Create DB, import tokens from flat files
 +-- scrape                         # Run scrapers, write to DB
 |     --sources, --search-term, --hours-old, --classify, --dry-run
 +-- search                         # Query the job database
 |     QUERY, --new, --company, --remote, --source, --salary-min, --days,
 |     --ai-native, --seniority, --domain, --tag, --interest, --sort, --limit
 +-- show <job-id>                  # Full details for one job
 |     --no-desc, --open
 +-- enrich                         # Run classification pipeline
 |     --stage (rules|jobs|companies), --dry-run, --source, --force
 +-- annotate <job-id>              # Tag, rate, note a job
 |     --tag, --untag, --note, --rating, --pros, --cons
 +-- apply <job-id>                 # Track application status
 |     --stage, --note, --list
 +-- stats                          # DB statistics, scrape history
 |     --runs
 +-- tokens                         # Token management subcommands
       +-- validate                 # Ping live APIs, update token_status
       |     --platform, --status (unchecked|all)
       +-- add <platform> <token>   # Add a single token manually
       |     --name
       +-- list                     # Show token counts by platform and status
       +-- discover                 # Discover ATS tokens from HN comments
             --phase (harvest|find-careers|detect-ats), --status
```

## Global Options

```
jbs [--db PATH] [--format table|json|csv] [--no-color] [--verbose] <command>
```

- `--db` (default `data/jobs.db`) -- SQLite database path
- `--format` (default `table`) -- output format; all commands respect this
- `--no-color` -- disable colors/formatting
- `--verbose` -- debug output

When stdout is not a TTY, `--no-color` is implied and `--format` defaults to `json`.

---

### `jbs init`

Create the database and import tokens from flat files. Safe to re-run (idempotent).

Creates `data/jobs.db` with the full schema (spec 02: `runs`, `companies`, `jobs`, `company_preferences`, `job_annotations`, `job_tags`, `hn_career_pages`, `enrichment_runs`). Then imports tokens from `tokens/*.txt` into the `companies` table.

**Import rules:**
- For each platform, prefers the validated file over the raw file (e.g., `tokens/greenhouse.txt` over `tokens/greenhouse_raw.txt`)
- Derives company names from token slugs (e.g., `anthropic` → `Anthropic`)
- Tokens imported with `token_status = 'unchecked'`
- Imports 404 blocklists (`tokens/*_404.txt`) as stale tokens
- Existing `(ats_platform, ats_token)` pairs are skipped (idempotent)

```bash
jbs init                    # create DB, import all token files
```

**Output:**
```
Creating data/jobs.db... done.
Importing tokens:
  greenhouse  298 tokens from tokens/greenhouse.txt
  lever        41 tokens from tokens/lever.txt
  ashby        25 tokens from tokens/ashby.txt
  blocklists   82 tokens marked stale (44 greenhouse, 36 lever, 2 ashby)
Database initialized. 364 tokens imported.
```

**Output (re-run, DB already exists):**
```
Database already exists at data/jobs.db.
Importing tokens:
  greenhouse  0 new (298 already in DB)
  lever       0 new (41 already in DB)
  ashby       0 new (25 already in DB)
Done. No new tokens to import.
```

---

### `jbs scrape`

Run scrapers, write results to the database.

| Option | Default | Description |
|--------|---------|-------------|
| `--sources` | all | Comma-separated: greenhouse,lever,ashby,remoteok,hn |
| `--search-term` | none | Filter scraped results by keyword |
| `--hours-old` | 168 | Only keep jobs posted within N hours |
| `--classify` | false | Run enrichment pipeline after scraping |
| `--dry-run` | false | Show what would be scraped without running |

Tokens are loaded from the `companies` table (`token_status != 'stale'`). ATS sources with no tokens in the DB are skipped.

```bash
jbs scrape                                    # all sources, default weekly
jbs scrape --sources remoteok --classify      # single source + enrich after
jbs scrape --sources hn --hours-old 24        # quick HN check
```

**Output:**
```
Scraping 5 sources...
  greenhouse  ████████████████████  512 jobs (3.2s)
  lever       ████████████████████  325 jobs (8.1s)
  ashby       ████████████████████  200 jobs (1.4s)
  remoteok    ████████████████████   55 jobs (0.6s)
  hn          ████████████████████  274 jobs (0.9s)
Run complete: 1,366 jobs scraped, 891 new, 475 duplicates
```

**First-run output (no DB):**
```
$ jbs scrape
No database found. Run `jbs init` to create the database and import tokens.
  Quick start:
    jbs init                # create DB + import tokens from tokens/*.txt
    jbs scrape              # run all scrapers
    jbs search --new        # browse what was found
```

**First-run output (DB exists, no tokens):**
```
$ jbs scrape
Scraping 2 sources (no ATS tokens in DB — skipping greenhouse, lever, ashby)...
  remoteok    ████████████████████   55 jobs (0.6s)
  hn          ████████████████████  274 jobs (0.9s)
Run complete: 329 jobs scraped, 329 new
Next steps:
  jbs search --new               # browse what was found
  jbs tokens validate            # validate tokens and unlock ATS sources
  jbs enrich --stage rules       # classify jobs (free, no API key needed)
```

---

### `jbs search`

Query the job database. Also serves as export: `jbs search --format csv > file.csv`.

By default, only active jobs (`is_active = 1`) are shown.

| Option | Default | Description |
|--------|---------|-------------|
| `QUERY` | none | Full-text search across title + description |
| `--new` | false | Jobs from latest run, not yet annotated |
| `--company` | none | Filter by company name (substring match) |
| `--location` | none | Filter by location |
| `--remote` / `--onsite` | none | Work arrangement filter |
| `--source` | none | Filter by source |
| `--salary-min` | none | Minimum salary (uses normalized USD yearly values when available) |
| `--days` | none | Posted within N days |
| `--ai-native` | none | Minimum ai_native score (0.0-1.0, from companies table) |
| `--seniority` | none | intern, junior, mid, senior, staff, principal |
| `--domain` | none | backend, frontend, fullstack, ml, infra, etc. |
| `--industry` | none | Filter by company industry |
| `--tag` | none | Filter by tag (repeatable) |
| `--interest` | none | Filter by interest level |
| `--engineering` | false | Only show engineering roles (engineering_role = 1) |
| `--include-inactive` | false | Include deactivated jobs (miss_count >= 2) |
| `--sort` | date | date, salary, company, ai-native |
| `--limit` | 50 | Max results |
| `--offset` | 0 | Skip first N results |

```bash
jbs search --new                                          # what's new?
jbs search "machine learning" --ai-native 0.7 --remote   # ML + AI-native
jbs search --seniority senior --salary-min 200000         # senior, high comp
jbs search --company anthropic                            # company lookup
jbs search --format csv --remote > remote-jobs.csv        # export to CSV
jbs search "rust" --format json | jq '.[].id'            # pipe IDs
jbs search --include-inactive --company acme              # include old postings
```

**Table output:** Columns: ID, Title, Company, Location, Salary, Source, Posted, Summary (when `job_summary` is available, shown as a truncated one-liner). Footer: "Showing N of M results."

**JSON output:** Array of objects with `id`, `title`, `company`, `location`, `work_arrangement`, `min_amount`, `max_amount`, `currency`, `salary_usd_min`, `salary_usd_max`, `site`, `date_posted`, `job_url`, `ai_native`, `seniority`, `domain`, `job_summary`.

---

### `jbs show <job-id>`

Display full details for a single job. Options: `--no-desc`, `--open` (opens URL in browser).

```
Sr. ML Engineer
Anthropic  ·  San Francisco, CA  ·  Hybrid  ·  greenhouse
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Salary       $300,000 - $400,000/yr (USD)
  Seniority    senior          Domain     ml
  Posted       2026-04-03 (2 days ago)
  URL          https://boards.greenhouse.io/anthropic/jobs/401298
  Company      Anthropic — AI safety research company.
  AI-Native    0.95            Industry   AI/ML
  Tags         #interesting    Interest   applied
  Notes        "Phone screen on Apr 10."
  Summary      Building RLHF infrastructure for large language model training at a leading AI safety lab.
───────────────────────────────────────────────────────────
## About the role
[full markdown-rendered description]
```

Partial ID matching: `jbs show gh-881` matches `gh-881901` if unambiguous.

---

### `jbs enrich`

Run the classification/enrichment pipeline on unprocessed jobs.

| Option | Default | Description |
|--------|---------|-------------|
| `--stage` | all | `rules` (free, Stage 0+1), `jobs` (LLM job classification, Stage 2), or `companies` (LLM company enrichment, Stage 3) |
| `--dry-run` | false | Show pending counts and cost estimate |
| `--source` | none | Only enrich jobs from this source (e.g., `--source greenhouse`) |
| `--force` | false | Re-enrich jobs even if they already have `enriched_at` set |

Without `--force`, only jobs where `enriched_at IS NULL` (or `engineering_role IS NULL` for Stage 2) are processed. With `--force`, all matching jobs are re-processed.

When `--stage` is omitted, all stages run in order: rules → jobs → companies.

**LLM backend selection (Stages 2 and 3):**
- **Default:** Claude Agent SDK — uses the user's existing Claude subscription (Pro/Max). No API key needed. Jobs batched ~20 per call with descriptions truncated to ~2KB.
- **Fast path:** If `ANTHROPIC_API_KEY` is set, uses the Anthropic Batch API instead. Individual calls with full descriptions. Faster and more accurate.

`--stage rules` never requires any API key or subscription — it's pure regex/keyword extraction.

```bash
jbs enrich                              # full pipeline, unprocessed only
jbs enrich --stage rules                # rule-based only (free, no LLM)
jbs enrich --stage jobs                 # LLM job classification only
jbs enrich --stage companies            # LLM company enrichment only
jbs enrich --dry-run                    # show pending counts + cost estimate
jbs enrich --force                      # re-process everything
jbs enrich --source greenhouse          # only enrich greenhouse jobs
jbs enrich --force --stage jobs         # re-classify all jobs via LLM
```

**Output:**
```
Enriching 891 unprocessed jobs...
  Stage 0: cleanup     891 descriptions fixed  (0.3s)
    html_to_md: 450   encoding: 43   boilerplate: stripped
  Stage 1: rules       891 jobs processed      (1.2s)
    seniority: 624   visa: 178   salary: 89   years_exp: 534
  Stage 2: jobs        891 jobs classified      (12.4s, $0.15)
    engineering_role: 891   seniority: 157 refined   domain: 891
  Stage 3: companies    63 companies classified (3.1s, $0.03)
    ai_native: 63   industry: 63
Enrichment complete. Total cost: $0.18
```

**Output (--dry-run):**
```
Pending enrichment:
  Stage 0: 450 Greenhouse HTML descriptions to convert
  Stage 1: 891 jobs for rule-based extraction     (free)
  Stage 2: 891 jobs for LLM classification        (~$0.15, Haiku)
  Stage 3:  63 companies for LLM classification   (~$0.03, Haiku)
  Estimated total: ~$0.18
  Backend: Agent SDK (Claude subscription)
```

**Output (--dry-run with ANTHROPIC_API_KEY set):**
```
Pending enrichment:
  Stage 0: 450 Greenhouse HTML descriptions to convert
  Stage 1: 891 jobs for rule-based extraction     (free)
  Stage 2: 891 jobs for LLM classification        (~$0.89, Haiku Batch API)
  Stage 3:  63 companies for LLM classification   (~$0.08, Haiku Batch API)
  Estimated total: ~$0.97
  Backend: Batch API (ANTHROPIC_API_KEY set)
```

---

### `jbs annotate <job-id>`

Add metadata to a job: tags, notes, rating, pros/cons. Writes to `job_annotations` and `job_tags` tables (spec 02).

| Option | Description |
|--------|-------------|
| `--tag` | Add a tag (repeatable) |
| `--untag` | Remove a tag (repeatable) |
| `--note` | Free-text note |
| `--rating` | Set rating 1-5 |
| `--pros` | Add a pro (repeatable) |
| `--cons` | Add a con (repeatable) |

```bash
jbs annotate gh-401298 --tag interesting --tag ai-safety
jbs annotate gh-401298 --note "Strong match — team works on RLHF"
jbs annotate ashby-9f3c --rating 4 --pros "Great comp" --cons "NYC onsite"
```

```
Updated gh-401298 (Sr. ML Engineer @ Anthropic)
  + tag: interesting
  + tag: ai-safety
```

---

### `jbs apply`

Track application status. Sets the `interest` field in `job_annotations` -- no separate applications table.

| Option | Default | Description |
|--------|---------|-------------|
| `--stage` | applied | interested, applied, phone-screen, take-home, onsite, offer, rejected, withdrawn |
| `--note` | none | Note about this status change |
| `--list` | false | Show all jobs with active application interest |

```bash
jbs apply gh-401298                                        # sets interest = "applied"
jbs apply gh-401298 --stage phone-screen --note "Apr 10"   # update stage
jbs apply --list                                           # view pipeline
```

**Output:**
```
Applied to gh-401298 (Sr. ML Engineer @ Anthropic)
  interest: applied
```

**Output (`--list`):** Table grouped by status (applied/phone-screen/take-home/onsite/offer/rejected) with count and company names per row.

---

### `jbs stats`

Database statistics, scrape history, classification coverage.

| Option | Default | Description |
|--------|---------|-------------|
| `--runs` | 5 | Number of recent runs to show |

Shows: total jobs/companies/runs, jobs-by-source breakdown, classification coverage percentages, and recent run history (run ID, new count, sources).

---

### `jbs tokens validate`

Validate ATS tokens against live APIs. Updates `token_status` and `token_checked_at` in the `companies` table.

| Option | Default | Description |
|--------|---------|-------------|
| `--platform` | all | Only validate one platform: greenhouse, lever, ashby |
| `--status` | unchecked | Which tokens to check: `unchecked` (default) or `all` (re-validate everything) |

```bash
jbs tokens validate                          # validate unchecked tokens, all platforms
jbs tokens validate --platform greenhouse    # one platform only
jbs tokens validate --status all             # re-validate everything including valid
```

**Output:**
```
Validating tokens...
  greenhouse  ████████████████████  298/298 checked
    256 valid, 42 stale
  lever       ████████████████████   41/41 checked
    35 valid, 6 stale
  ashby       ████████████████████   25/25 checked
    25 valid, 0 stale
Validation complete. 316 valid, 48 stale.
```

### `jbs tokens add <platform> <token>`

Add a single token manually. Creates a company record with `token_status = 'unchecked'`.

| Option | Default | Description |
|--------|---------|-------------|
| `--name` | derived from slug | Explicit company name |

```bash
jbs tokens add greenhouse anthropic                    # derives name "Anthropic"
jbs tokens add lever ramp --name "Ramp Technologies"   # explicit name
```

**Output:**
```
Added greenhouse token: anthropic (Anthropic)
  Status: unchecked — run `jbs tokens validate` to verify.
```

**Output (already exists):**
```
Token already exists: greenhouse/anthropic (Anthropic)
  Status: valid (last checked 2026-04-05)
```

### `jbs tokens list`

Show token counts by platform and status.

```bash
jbs tokens list
```

**Output:**
```
Platform     Valid   Stale   Unchecked   Total
greenhouse     256      42         0       298
lever           35       6         0        41
ashby           25       0         0        25
Total          316      48         0       364
```

### `jbs tokens discover`

Discover ATS tokens from HN Who's Hiring comments. Runs a multi-phase pipeline against existing HN job data in the DB. See [HN careers spec](hn-careers-pipeline.md) for full details.

| Option | Default | Description |
|--------|---------|-------------|
| `--phase` | all | `harvest` (extract ATS tokens from URLs), `find-careers` (probe for careers pages), `detect-ats` (scan careers pages for ATS embeds) |
| `--status` | false | Show discovery progress summary instead of running |

```bash
jbs tokens discover                       # run all phases
jbs tokens discover --phase harvest       # just extract tokens from URLs
jbs tokens discover --status              # show progress
```

**Output:**
```
Phase 1: Harvest ATS tokens from HN URLs...
  Found 30 ATS tokens in job URLs
    ashby: 20 new   greenhouse: 7 new   lever: 3 new
Phase 2: Discover careers pages...
  Found 47 careers pages
Phase 3: Detect ATS on careers pages...
  Found 8 additional ATS tokens
Summary: 38 new tokens added to companies table
  Run 'jbs scrape' to scrape the newly discovered boards
```

---

## Error Output

Errors print to stderr with a source prefix. Non-zero exit codes for all failures.

**No database (jbs scrape without jbs init):**
```
$ jbs scrape
No database found. Run `jbs init` to create the database and import tokens.
  Quick start:
    jbs init                # create DB + import tokens from tokens/*.txt
    jbs scrape              # run all scrapers
    jbs search --new        # browse what was found
```

**No tokens in DB for a requested source:**
```
$ jbs scrape --sources greenhouse
  greenhouse: skipped (no tokens in DB)
  Tip: Run `jbs init` to import tokens from tokens/*.txt
       or `jbs tokens add greenhouse <token>` to add one manually.
```

**RemoteOK rate limit:**
```
$ jbs scrape --sources remoteok
  remoteok    ✗ 429 Too Many Requests
Warning: remoteok returned 0 jobs. Try again later.
```

**LLM enrichment — no subscription or API key:**
```
$ jbs enrich --stage jobs
Stage 0: cleanup... done (0.3s)
Stage 1: rules... done (1.2s)
Stage 2: Could not connect to Claude. Check your Claude subscription (Pro/Max).
  Alternatively, set ANTHROPIC_API_KEY for the Batch API fast path:
    export ANTHROPIC_API_KEY=sk-ant-...
  Or run rules only:
    jbs enrich --stage rules
```

**LLM enrichment — Batch API requested but no key:**
```
$ ANTHROPIC_API_KEY= jbs enrich --stage jobs
Stage 0: cleanup... done (0.3s)
Stage 1: rules... done (1.2s)
Stage 2: ANTHROPIC_API_KEY is empty. Using Agent SDK backend (Claude subscription)...
```

**Rules-only enrichment — always works, no auth needed:**
```
$ jbs enrich --stage rules
Stage 1: rules       891 jobs processed      (1.2s)
    seniority: 624   visa: 178   salary: 89   years_exp: 534
Enrichment complete. (free, no LLM used)
```

**All tokens stale:**
```
$ jbs scrape --sources lever
  lever       ████████████████████  41/41 tokens — 0 valid (all stale)
Warning: All 41 lever tokens are stale. Run `jbs tokens validate --status all` to re-check.
```

---

## DB Schema Additions

Application tracking uses `interest` on `job_annotations` -- no separate `applications` table. User opinions on companies use `company_preferences`. Full schema in spec 02.

```sql
CREATE TABLE IF NOT EXISTS job_annotations (
    job_id      TEXT PRIMARY KEY REFERENCES jobs(id),
    rating      INTEGER                -- 1-5 stars (NULL = unrated)
                CHECK(rating IS NULL OR (rating >= 1 AND rating <= 5)),
    interest    TEXT                   -- interested, applied, phone_screen, take_home,
                                      -- onsite, offer, rejected, withdrawn (NULL = unseen)
                CHECK(interest IS NULL OR interest IN
                      ('interested', 'applied', 'phone_screen', 'take_home',
                       'onsite', 'offer', 'rejected', 'withdrawn')),
    note        TEXT,
    pros        TEXT,             -- JSON array of strings
    cons        TEXT,             -- JSON array of strings
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS job_tags (
    job_id      TEXT NOT NULL REFERENCES jobs(id),
    tag         TEXT NOT NULL,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (job_id, tag)
);

CREATE TABLE IF NOT EXISTS company_preferences (
    company_id  INTEGER PRIMARY KEY REFERENCES companies(id),
    interest    TEXT                   -- 'love', 'like', 'neutral', 'avoid' (NULL = no opinion)
                CHECK(interest IS NULL OR interest IN ('love', 'like', 'neutral', 'avoid')),
    rating      INTEGER                -- 1-5 stars (NULL = unrated)
                CHECK(rating IS NULL OR (rating >= 1 AND rating <= 5)),
    note        TEXT,
    tags        TEXT,                  -- JSON array of strings
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
);
```

---

## Example Session

```bash
# First-time setup
$ pip install -e .
$ jbs init
Creating data/jobs.db... done.
Importing tokens:
  greenhouse  298 tokens from tokens/greenhouse.txt
  lever        41 tokens from tokens/lever.txt
  ashby        25 tokens from tokens/ashby.txt
Database initialized. 364 tokens imported.

# Validate tokens against live APIs
$ jbs tokens validate
  greenhouse: 256 valid, 42 stale (of 298 checked)
  lever: 35 valid, 6 stale (of 41 checked)
  ashby: 25 valid, 0 stale (of 25 checked)

# Run scrapers
$ jbs scrape --sources greenhouse,ashby --hours-old 48
Run complete: 712 jobs scraped, 89 new, 623 duplicates

# Free enrichment (no API key or subscription needed)
$ jbs enrich --stage rules
Enrichment complete. seniority: 71  visa: 23  salary: 32  years_exp: 58

# Browse new jobs
$ jbs search --new --ai-native 0.6 --remote --sort salary
 gh-881901   Sr. Infra Engineer   Anthropic  Remote (US)  $300-400k  greenhouse  1d ago
 ashby-f291  Platform Engineer    Ramp       Remote (US)  $220-300k  ashby       1d ago

# Show details
$ jbs show gh-881901 --no-desc
Sr. Infra Engineer — Anthropic · Remote (US) · $300-400k · senior · AI-Native 0.95
Summary: Building distributed systems infrastructure for large-scale model serving at a leading AI safety company.

# Annotate and apply
$ jbs annotate gh-881901 --tag interesting --rating 5 --pros "Dream role"
$ jbs apply gh-881901
Applied to gh-881901 (Sr. Infra Engineer @ Anthropic) — interest: applied

# Full LLM enrichment (uses Claude subscription by default)
$ jbs enrich
Enrichment complete. Total cost: $0.00 (Agent SDK, subscription)

# Export shortlist
$ jbs search --format csv --ai-native 0.7 --remote > shortlist.csv
```

---

## Implementation Notes

- **Package:** `click` for CLI, `rich` for rendering. Entry point: `jbs = "jbs.cli:main"` in pyproject.toml.
- **Config:** `config.toml` at project root. Edit by hand. Missing file = all defaults.
- **Compat:** When piped, auto-switch to JSON with no colors.
- **Tokens live in the DB** after `jbs init`. Flat files under `tokens/` are only an import source, not the source of truth.
