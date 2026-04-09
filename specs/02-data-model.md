# Spec 02: Data Model

## Problem

The current schema has loose coupling between jobs and companies (bare string match, no FK), stores ATS tokens in flat files separate from the DB, and provides no way to record opinions about jobs or companies. This spec defines the complete data model for `jbs`.

## Design Principles

1. **Companies are first-class.** Jobs reference companies by FK. Company data persists across scrape runs.
2. **Tokens live in the DB.** The `companies` table IS the token list. Flat files are an import source, not the source of truth.
3. **Objective vs subjective separation.** Scraper-derived facts in `jobs` and `companies`. User opinions in `job_annotations` and `company_preferences`. Re-scraping never overwrites user data.
4. **Annotations are mutable single-row.** One row per job. UPDATE when you change your mind. No audit trail needed for personal notes.
5. **Tags are just strings.** No tag definition table, no colors, no metadata. Jobs use a separate `job_tags` table (queryable via `--tag` filter). Companies use a JSON array on `company_preferences` (no independent query need).
6. **No application tracker table.** Status lives in `job_annotations.interest`. Full pipeline tracking belongs in a spreadsheet.
7. **Migration is additive.** New tables and columns only; existing data is preserved.
8. **CHECK constraints on enums.** All columns with a fixed set of valid values get CHECK constraints for data integrity.

## Entity Relationships

```
runs 1───* jobs *───1 companies
                jobs 1───1 job_annotations
                jobs 1───* job_tags
           companies 1───1 company_preferences
           companies 1───* hn_career_pages
```

## Schema

### runs

Tracks each scrape execution.

```sql
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,       -- e.g. '2026-04-05_091500'
    started_at  TEXT NOT NULL,          -- ISO 8601
    finished_at TEXT,                   -- ISO 8601, NULL if still running
    sources     TEXT,                   -- comma-separated: 'greenhouse,lever,hn'
    search_term TEXT,
    total_jobs  INTEGER,               -- jobs inserted/updated in this run
    status      TEXT DEFAULT 'running'  -- running, completed, failed
                CHECK(status IN ('running', 'completed', 'failed'))
);
```

### companies

First-class entity. Also serves as the ATS token registry.

```sql
CREATE TABLE IF NOT EXISTS companies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,          -- display name, as first seen (updated on first real scrape)
    name_normalized TEXT NOT NULL UNIQUE,   -- dedup key (see normalization function)

    -- ATS identity (at most one platform per company)
    ats_platform    TEXT                    -- 'greenhouse', 'lever', 'ashby', or NULL
                    CHECK(ats_platform IN ('greenhouse', 'lever', 'ashby') OR ats_platform IS NULL),
    ats_token       TEXT,                   -- board slug, e.g. 'anthropic', 'ramp'
    token_status    TEXT DEFAULT 'unchecked'
                    CHECK(token_status IN ('valid', 'stale', 'unchecked')),
    token_checked_at TEXT,                  -- ISO 8601, last validation time

    -- Objective facts (scraped or enriched)
    website         TEXT,                   -- company URL, enriched later
    description     TEXT,                   -- 1-sentence summary
    industry        TEXT,                   -- AI/ML, FinTech, etc.
    ai_native       REAL                    -- 0.0 to 1.0
                    CHECK(ai_native IS NULL OR (ai_native >= 0.0 AND ai_native <= 1.0)),
    funding_stage   TEXT,                   -- seed, series_a, ..., public, unknown
    size_estimate   TEXT,                   -- 1-10, 11-50, 51-200, 201-1000, 1000+
    hq_country      TEXT,
    tech_stack      TEXT,                   -- JSON array, aggregated from jobs

    -- Resolution tracking
    match_status    TEXT DEFAULT 'auto'
                    CHECK(match_status IN ('auto', 'verified', 'unlinked')),

    -- Enrichment tracking
    enriched_at     TEXT,                   -- ISO 8601, NULL = not yet enriched

    -- Meta
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,

    -- Enforce at most one token per (platform, token) pair.
    -- This is the critical dedup constraint for token import.
    UNIQUE(ats_platform, ats_token)
);
```

**Note on UNIQUE(ats_platform, ats_token):** SQLite treats each NULL as distinct in UNIQUE constraints, so rows with `ats_platform IS NULL` will not conflict with each other. This is the desired behavior -- only rows with actual ATS identities are deduplicated.

**Token queries replace flat files:**
```sql
-- Get all Greenhouse tokens to scrape
SELECT ats_token FROM companies WHERE ats_platform = 'greenhouse' AND token_status != 'stale';

-- Mark a token as dead
UPDATE companies SET token_status = 'stale', token_checked_at = CURRENT_TIMESTAMP
WHERE ats_platform = 'greenhouse' AND ats_token = 'deadcompany';

-- Import a newly discovered token from HN
INSERT INTO companies (name, name_normalized, ats_platform, ats_token, token_status, match_status)
VALUES ('Acme AI', 'acmeai', 'ashby', 'acme-ai', 'unchecked', 'auto');
```

### jobs

One row per job posting, identified by prefixed ID.

```sql
CREATE TABLE IF NOT EXISTS jobs (
    id                TEXT PRIMARY KEY,     -- prefixed: 'gh-12345', 'lever-abc', 'rok-456'
    run_id            TEXT NOT NULL,        -- FK to runs; the run that last upserted this job
    site              TEXT NOT NULL         -- 'greenhouse', 'lever', 'ashby', 'remoteok', 'hn'
                      CHECK(site IN ('greenhouse', 'lever', 'ashby', 'remoteok', 'hn')),

    -- Company link
    company_id        INTEGER REFERENCES companies(id),
    company_raw       TEXT,                -- original string from scraper, for debugging

    -- Core fields
    title             TEXT,
    board_token       TEXT,                -- traces which ATS board this came from

    -- Location (raw + parsed)
    location_raw      TEXT,
    country           TEXT,
    state             TEXT,
    city              TEXT,
    work_arrangement  TEXT                 -- 'remote', 'hybrid', 'onsite', 'unknown'
                      CHECK(work_arrangement IS NULL OR
                            work_arrangement IN ('remote', 'hybrid', 'onsite', 'unknown')),

    -- Job details
    date_posted       TEXT,                -- ISO 8601 date
    job_url           TEXT,
    job_url_direct    TEXT,
    description       TEXT,
    job_type          TEXT,                -- full-time, part-time, contract, intern
    job_function      TEXT,

    -- Compensation (as reported by source)
    min_amount        REAL,
    max_amount        REAL,
    currency          TEXT,
    salary_interval   TEXT,                -- yearly, monthly, hourly

    -- Normalized compensation (enrichment)
    salary_usd_min    REAL,                -- normalized to USD yearly
    salary_usd_max    REAL,

    -- Classification (enrichment)
    engineering_role  BOOLEAN,
    seniority         TEXT,                -- intern, junior, mid, senior, staff, principal
    domain            TEXT,                -- backend, frontend, fullstack, ml, infra, etc.
    tech_stack        TEXT,                -- JSON array: ["python","react","postgres"]
    job_summary       TEXT,                -- 1-2 sentence LLM-generated summary
    visa_sponsorship  TEXT                 -- visa sponsorship status
                      CHECK(visa_sponsorship IS NULL OR
                            visa_sponsorship IN ('sponsors', 'no_sponsorship', 'unknown')),
    years_experience  INTEGER,             -- minimum years of experience mentioned
    is_management     BOOLEAN,             -- whether the role is management

    -- Activity tracking
    first_seen_run    TEXT,                -- run_id when first inserted
    last_seen_run     TEXT,                -- run_id when last seen in a scrape
    miss_count        INTEGER DEFAULT 0,   -- consecutive scrapes where job wasn't found
    is_active         BOOLEAN DEFAULT 1,   -- false after 2 consecutive misses

    -- Enrichment tracking
    enriched_at       TEXT,                -- ISO 8601, NULL = not yet enriched

    -- Meta
    scraped_at        TEXT DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
```

**Clarification on `run_id` vs `first_seen_run` vs `last_seen_run`:**
- `run_id`: the run that last upserted this job (changes on each re-scrape). Useful for "what did this run touch?"
- `first_seen_run`: the run that originally inserted this job (never changes). Provenance.
- `last_seen_run`: the most recent run where this job was found (for staleness tracking). Updated even if no fields changed.

### company_preferences

User's subjective overlay on companies. Separate table so re-scraping never overwrites opinions.

```sql
CREATE TABLE IF NOT EXISTS company_preferences (
    company_id  INTEGER PRIMARY KEY REFERENCES companies(id),
    interest    TEXT                   -- 'love', 'like', 'neutral', 'avoid' (NULL = no opinion)
                CHECK(interest IS NULL OR interest IN ('love', 'like', 'neutral', 'avoid')),
    rating      INTEGER                -- 1-5 stars (NULL = unrated)
                CHECK(rating IS NULL OR (rating >= 1 AND rating <= 5)),
    note        TEXT,                  -- free-text
    tags        TEXT,                  -- JSON array of strings, e.g. '["target","dream"]'
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
);
```

**Why `tags` is a JSON column here but `job_tags` is a separate table:** Job tags are queried independently via `jbs search --tag`, which needs an indexed lookup. Company tags are only displayed, never filtered on. At ~50 rows, JSON is simpler and adequate.

### job_annotations

One row per job, mutable. User's subjective data about a specific job posting.

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
    note        TEXT,                  -- free-text
    pros        TEXT,                  -- JSON array of strings
    cons        TEXT,                  -- JSON array of strings
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### job_tags

Flat strings, no definition table.

```sql
CREATE TABLE IF NOT EXISTS job_tags (
    job_id      TEXT NOT NULL REFERENCES jobs(id),
    tag         TEXT NOT NULL,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (job_id, tag)
);
```

### hn_career_pages

Tracks HN company career page discovery and ATS token extraction. This table records the *discovery process* -- which HN comments led to which careers pages and tokens. The `companies` table is the authoritative token registry; when a token is discovered here, it must be copied to `companies.ats_platform`/`ats_token` to take effect.

```sql
CREATE TABLE IF NOT EXISTS hn_career_pages (
    hn_job_id       TEXT PRIMARY KEY REFERENCES jobs(id),
    company_name    TEXT,
    company_url     TEXT,          -- URL from HN comment
    careers_url     TEXT,          -- discovered careers page
    ats_platform    TEXT           -- greenhouse, lever, ashby, or NULL
                    CHECK(ats_platform IS NULL OR
                          ats_platform IN ('greenhouse', 'lever', 'ashby')),
    ats_token       TEXT,          -- extracted board token
    page_type       TEXT           -- ats, static_html, spa, dead_end, unknown
                    CHECK(page_type IS NULL OR
                          page_type IN ('ats', 'static_html', 'spa', 'dead_end', 'unknown')),
    status          TEXT DEFAULT 'pending'
                    CHECK(status IN ('pending', 'discovered', 'scraped', 'failed', 'skipped')),
    last_checked    TEXT,
    error           TEXT
);
```

**Relationship to `companies` table:** The `ats_platform` and `ats_token` columns here are a snapshot of what was discovered. They overlap with the same columns on `companies`, but serve different purposes: `hn_career_pages` is the audit trail of how a token was found; `companies` is where scrapers look for tokens. The HN careers pipeline is responsible for copying discovered tokens into `companies` (see spec hn-careers-pipeline).

### enrichment_runs

Tracks LLM enrichment batches for cost accounting.

```sql
CREATE TABLE IF NOT EXISTS enrichment_runs (
    run_id        TEXT PRIMARY KEY,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,            -- ISO 8601, NULL if still running
    stage         TEXT,            -- 'rules', 'jobs', 'companies'
    items         INTEGER,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd      REAL,
    model         TEXT DEFAULT 'claude-haiku'
);
```

## Indexes

Only indexes that support actual queries we run.

```sql
-- Jobs: the main search dimensions
CREATE INDEX IF NOT EXISTS idx_jobs_company_id     ON jobs(company_id);
CREATE INDEX IF NOT EXISTS idx_jobs_site           ON jobs(site);
CREATE INDEX IF NOT EXISTS idx_jobs_active         ON jobs(is_active) WHERE is_active = 1;
CREATE INDEX IF NOT EXISTS idx_jobs_posted         ON jobs(date_posted);
CREATE INDEX IF NOT EXISTS idx_jobs_seniority      ON jobs(seniority) WHERE seniority IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_jobs_eng_role       ON jobs(engineering_role) WHERE engineering_role = 1;

-- Companies: token lookups and search
-- Note: UNIQUE(ats_platform, ats_token) on the table enforces uniqueness;
-- this index optimizes lookups.
CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_ats
    ON companies(ats_platform, ats_token)
    WHERE ats_platform IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_companies_norm      ON companies(name_normalized);
CREATE INDEX IF NOT EXISTS idx_companies_ai        ON companies(ai_native) WHERE ai_native IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_companies_token_st  ON companies(ats_platform, token_status)
                                                   WHERE ats_platform IS NOT NULL;

-- Annotations: pipeline queries
CREATE INDEX IF NOT EXISTS idx_annotations_interest ON job_annotations(interest)
                                                    WHERE interest IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_annotations_rating   ON job_annotations(rating)
                                                    WHERE rating IS NOT NULL;

-- Tags
CREATE INDEX IF NOT EXISTS idx_job_tags_tag        ON job_tags(tag);

-- HN career pages
CREATE INDEX IF NOT EXISTS idx_hn_careers_status   ON hn_career_pages(status);
```

## Company Name Normalization

The `name_normalized` column is the dedup key. Two company strings that normalize to the same value are considered the same company.

```python
import re

# Suffixes to strip (case-insensitive, with optional trailing period)
_SUFFIXES = re.compile(
    r',?\s*\b(inc|llc|ltd|corp|co|pbc|gmbh|ag|sa|plc|pty|limited|incorporated|corporation)\.?\s*$',
    re.IGNORECASE,
)

def normalize_company_name(name: str) -> str:
    """Normalize a company name for deduplication.

    Steps:
    1. Strip whitespace
    2. Remove common corporate suffixes (Inc, LLC, Ltd, Corp, PBC, GmbH, etc.)
    3. Lowercase
    4. Remove all non-alphanumeric characters

    Examples:
        'Anthropic, Inc.'  -> 'anthropic'
        'Ramp Technologies' -> 'ramptechnologies'  (not a suffix)
        'Scale AI'          -> 'scaleai'
        'Acme Corp.'        -> 'acme'
        'ACME'              -> 'acme'
        'O\'Reilly Media'   -> 'oreillymedia'
    """
    s = name.strip()
    s = _SUFFIXES.sub('', s)
    s = s.lower()
    s = re.sub(r'[^a-z0-9]', '', s)
    return s
```

## Company Name Update on First Real Scrape

When tokens are imported from flat files, company names are derived from slugs (e.g., "anthropic" becomes "Anthropic" via `.title()`). When the scraper later hits the ATS API and gets the real company name (e.g., "Anthropic, Inc."), the orchestrator should update the display name:

```python
def maybe_update_company_name(conn, company_id: int, api_name: str):
    """Update a company's display name if the current name looks slug-derived.

    Called by the orchestrator after a successful ATS API response provides
    the real company name. Only updates if:
    1. The new name normalizes to the same value (safety check)
    2. The current name looks auto-generated (single word, title-cased)

    The name_normalized column is NOT changed -- it's the stable dedup key.
    """
    c = conn.cursor()
    c.execute("SELECT name, name_normalized FROM companies WHERE id = ?", (company_id,))
    row = c.fetchone()
    if not row:
        return
    current_name, current_norm = row

    new_norm = normalize_company_name(api_name)
    if new_norm != current_norm:
        return  # different company, don't touch

    # Only update if current name looks slug-derived
    # (single word matching the token, or title-cased slug)
    if ' ' not in current_name.strip() or current_name == current_name.title():
        c.execute(
            "UPDATE companies SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (api_name.strip(), company_id),
        )
```

## Company Resolution Algorithm

When a scraper returns a job, the system resolves which company record it belongs to. This runs at upsert time.

```python
def resolve_company(conn, job) -> int | None:
    """Resolve a job to a company_id. Returns the company ID, or None if
    no company info is available.

    Resolution order:
    1. ATS token match (exact, highest confidence)
    2. Normalized name match
    3. No match -> create new record (unless company is unknown)

    Args:
        conn: sqlite3 connection
        job: a Job object with .company, .board_token, .site
    """
    c = conn.cursor()

    # --- Step 1: ATS token match ---
    # If the job came from an ATS scraper with a known token, that's definitive.
    if job.board_token and job.site in ('greenhouse', 'lever', 'ashby'):
        c.execute(
            "SELECT id FROM companies WHERE ats_platform = ? AND ats_token = ?",
            (job.site, job.board_token),
        )
        row = c.fetchone()
        if row:
            return row[0]

    # --- Step 2: Normalized name match ---
    if job.company:
        norm = normalize_company_name(job.company)
        if norm:
            c.execute(
                "SELECT id FROM companies WHERE name_normalized = ?",
                (norm,),
            )
            row = c.fetchone()
            if row:
                company_id = row[0]
                # Backfill ATS info if this company didn't have it
                if job.board_token and job.site in ('greenhouse', 'lever', 'ashby'):
                    c.execute(
                        """UPDATE companies SET ats_platform = ?, ats_token = ?,
                           token_status = 'valid', updated_at = CURRENT_TIMESTAMP
                           WHERE id = ? AND ats_platform IS NULL""",
                        (job.site, job.board_token, company_id),
                    )
                return company_id

    # --- Step 3: No match -> create new company ---
    if not job.company:
        return None  # Don't create a placeholder "Unknown" company

    norm = normalize_company_name(job.company)
    if not norm:
        return None  # Empty after normalization (shouldn't happen with real names)

    ats_platform = job.site if job.site in ('greenhouse', 'lever', 'ashby') else None
    ats_token = job.board_token if ats_platform else None

    c.execute(
        """INSERT INTO companies (name, name_normalized, ats_platform, ats_token,
           token_status, match_status)
           VALUES (?, ?, ?, ?, ?, 'auto')""",
        (
            job.company,
            norm,
            ats_platform,
            ats_token,
            'valid' if ats_token else 'unchecked',
        ),
    )
    return c.lastrowid
```

**Change from original:** Jobs with no company name get `company_id = NULL` instead of creating an "Unknown" company. This avoids a UNIQUE constraint violation on `name_normalized` when multiple unknown-company jobs are inserted (they'd all try to create `name_normalized = 'unknown'`). Jobs with `company_id IS NULL` can be queried separately (`WHERE company_id IS NULL`) and linked later.

**match_status values:**
- `auto` -- system-matched by token or name normalization
- `verified` -- user has confirmed the match is correct
- `unlinked` -- system couldn't match, or user flagged a bad match

## Token Import from Flat Files

On first setup (or when migrating), tokens are imported from `tokens/*.txt` into the `companies` table.

**File preference:** For each platform, the validated file (e.g., `tokens/greenhouse.txt`) is preferred over the raw file (e.g., `tokens/greenhouse_raw.txt`). If the validated file exists, the raw file is skipped. Raw files are only imported as a fallback.

```python
def import_tokens_from_file(conn, platform: str, filepath: str):
    """Import board tokens from a flat file into the companies table.

    For each token, creates a company record if one doesn't already exist
    for that (platform, token) pair. The company name is derived from the
    token (e.g. 'anthropic' -> 'Anthropic').
    """
    c = conn.cursor()
    imported = 0
    for token in load_tokens(filepath):
        c.execute(
            "SELECT id FROM companies WHERE ats_platform = ? AND ats_token = ?",
            (platform, token),
        )
        if c.fetchone():
            continue  # already known

        # Derive a display name from the token slug
        name = token.replace('-', ' ').replace('_', ' ').title()
        norm = normalize_company_name(name)

        # Check if this normalized name already exists (maybe from a different source)
        c.execute("SELECT id FROM companies WHERE name_normalized = ?", (norm,))
        existing = c.fetchone()
        if existing:
            # Company exists but didn't have this ATS info -- backfill
            c.execute(
                """UPDATE companies SET ats_platform = ?, ats_token = ?,
                   token_status = 'unchecked', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND ats_platform IS NULL""",
                (platform, token, existing[0]),
            )
        else:
            c.execute(
                """INSERT INTO companies
                   (name, name_normalized, ats_platform, ats_token, token_status, match_status)
                   VALUES (?, ?, ?, ?, 'unchecked', 'auto')""",
                (name, norm, platform, token),
            )
        imported += 1
    conn.commit()
    return imported
```

## Example Workflows

### Annotating a job: "Great company, but the role is too junior"

```sql
-- Rate the company highly
INSERT OR REPLACE INTO company_preferences (company_id, rating, note, updated_at)
VALUES (42, 4, 'Strong AI-native focus, interesting product', CURRENT_TIMESTAMP);

-- But this specific role isn't a fit
INSERT INTO job_annotations (job_id, rating, interest, cons)
VALUES ('gh-98765', 2, NULL, '["too junior, looking for senior+"]');

-- Tag it for later review
INSERT OR IGNORE INTO job_tags (job_id, tag) VALUES ('gh-98765', 'watch company');
```

### Recording pros and cons: "Love the tech stack, hate the location"

```sql
INSERT INTO job_annotations (job_id, rating, pros, cons)
VALUES ('lever-abc123', 3,
        '["Rust + Python, strong infra team"]',
        '["NYC onsite only, no remote option"]');
```

### Tracking an application through stages

```sql
-- Initial: applied
INSERT INTO job_annotations (job_id, rating, interest, note)
VALUES ('ashby-def456', 4, 'applied', 'Applied 2026-04-01 via company site');

-- Update: phone screen completed
UPDATE job_annotations
SET interest = 'phone_screen',
    note = note || char(10) || '2026-04-05: Phone screen, good culture fit',
    updated_at = CURRENT_TIMESTAMP
WHERE job_id = 'ashby-def456';

-- Update: take-home assigned
UPDATE job_annotations
SET interest = 'take_home',
    note = note || char(10) || '2026-04-08: Take-home assigned, due in 5 days',
    updated_at = CURRENT_TIMESTAMP
WHERE job_id = 'ashby-def456';
```

### Tagging and querying

```sql
-- Tag some jobs
INSERT OR IGNORE INTO job_tags (job_id, tag) VALUES ('gh-11111', 'dream job');
INSERT OR IGNORE INTO job_tags (job_id, tag) VALUES ('lever-22222', 'strong match');

-- Find all dream jobs that are still active
SELECT j.title, c.name, j.job_url
FROM jobs j
JOIN companies c ON c.id = j.company_id
JOIN job_tags jt ON jt.job_id = j.id
WHERE jt.tag = 'dream job' AND j.is_active = 1
ORDER BY j.date_posted DESC;
```

### Dashboard queries

```sql
-- Application pipeline summary
SELECT interest, COUNT(*) FROM job_annotations
WHERE interest IS NOT NULL GROUP BY interest;

-- Highly-rated companies with active open roles
SELECT c.name, cp.rating, COUNT(j.id) AS open_roles
FROM company_preferences cp
JOIN companies c ON c.id = cp.company_id
JOIN jobs j ON j.company_id = c.id
WHERE cp.rating >= 4 AND j.is_active = 1
GROUP BY c.id ORDER BY cp.rating DESC;

-- New jobs at companies you like
SELECT j.id, j.title, c.name, j.work_arrangement, j.date_posted
FROM jobs j
JOIN companies c ON c.id = j.company_id
JOIN company_preferences cp ON cp.company_id = c.id
WHERE cp.interest = 'love' AND j.is_active = 1
ORDER BY j.date_posted DESC;

-- Token health: how many are valid per platform?
SELECT ats_platform, token_status, COUNT(*) AS cnt
FROM companies
WHERE ats_platform IS NOT NULL
GROUP BY ats_platform, token_status;
```

## FTS5 Integration Note

Spec 04 (Search and Ranking) defines a `jobs_fts` FTS5 virtual table with triggers that reference `jobs.company`. Since the old `company` column is not dropped (see "Column Removed from jobs" below), the FTS triggers will continue to work. However, when implementing, consider whether the FTS `company` column should pull from `companies.name` via the FK instead, for better data quality. The canonical table name for user opinions on companies is `company_preferences` (spec 04's `company_ratings` reference is stale and should be updated in that spec).

## Migration Strategy

Purely additive and idempotent. No schema_version table. `_ensure_schema()` runs on every `Store.__init__()`.

```python
def _ensure_schema(self):
    """Create tables and add columns idempotently.

    Safe to call on every startup -- CREATE TABLE IF NOT EXISTS and
    ALTER TABLE ADD COLUMN wrapped in try/except for 'duplicate column'.
    """
    with self._conn() as conn:
        # --- Create tables (IF NOT EXISTS) ---
        conn.execute("""CREATE TABLE IF NOT EXISTS runs (...)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS companies (...)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS jobs (...)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS company_preferences (...)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS job_annotations (...)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS job_tags (...)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS hn_career_pages (...)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS enrichment_runs (...)""")

        # --- Add columns to existing tables ---
        # (for migrating DBs created before this schema version)
        migrations = [
            # jobs table: new columns
            ("jobs", "company_id",      "INTEGER REFERENCES companies(id)"),
            ("jobs", "company_raw",     "TEXT"),
            ("jobs", "first_seen_run",  "TEXT"),
            ("jobs", "last_seen_run",   "TEXT"),
            ("jobs", "miss_count",      "INTEGER DEFAULT 0"),
            ("jobs", "is_active",       "BOOLEAN DEFAULT 1"),
            ("jobs", "tech_stack",      "TEXT"),
            ("jobs", "salary_usd_min",  "REAL"),
            ("jobs", "salary_usd_max",  "REAL"),
            ("jobs", "enriched_at",     "TEXT"),
            ("jobs", "job_summary",     "TEXT"),
            ("jobs", "visa_sponsorship","TEXT"),
            ("jobs", "years_experience","INTEGER"),
            ("jobs", "is_management",   "BOOLEAN"),
            # companies table: new columns
            ("companies", "ats_platform",    "TEXT"),
            ("companies", "ats_token",       "TEXT"),
            ("companies", "token_status",    "TEXT DEFAULT 'unchecked'"),
            ("companies", "token_checked_at","TEXT"),
            ("companies", "website",         "TEXT"),
            ("companies", "match_status",    "TEXT DEFAULT 'auto'"),
            ("companies", "funding_stage",   "TEXT"),
            ("companies", "size_estimate",   "TEXT"),
            ("companies", "tech_stack",      "TEXT"),
            ("companies", "enriched_at",     "TEXT"),
            ("companies", "created_at",      "TEXT DEFAULT CURRENT_TIMESTAMP"),
            ("companies", "updated_at",      "TEXT DEFAULT CURRENT_TIMESTAMP"),
            # runs table: new columns
            ("runs", "finished_at", "TEXT"),
            ("runs", "status",      "TEXT DEFAULT 'running'"),
        ]
        for table, col, typedef in migrations:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
            except sqlite3.OperationalError:
                pass  # column already exists

        # --- Create indexes ---
        # (all use IF NOT EXISTS, safe to re-run)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company_id ...")
        # ... etc, all indexes from the Indexes section above ...

        # --- Backfill company_raw from company ---
        conn.execute("""
            UPDATE jobs SET company_raw = company
            WHERE company_raw IS NULL AND company IS NOT NULL
        """)

        # --- Backfill company_id from company name ---
        # IMPORTANT: Cannot use pure SQL here because normalize_company_name()
        # strips corporate suffixes (Inc, LLC, etc.) which SQL REPLACE cannot do.
        # Use a Python loop instead.
        _backfill_company_ids(conn)

        # --- Backfill ATS info on companies from existing jobs ---
        conn.execute("""
            UPDATE companies SET
                ats_platform = (
                    SELECT j.site FROM jobs j
                    WHERE j.company_id = companies.id
                      AND j.site IN ('greenhouse', 'lever', 'ashby')
                      AND j.board_token IS NOT NULL
                    LIMIT 1
                ),
                ats_token = (
                    SELECT j.board_token FROM jobs j
                    WHERE j.company_id = companies.id
                      AND j.site IN ('greenhouse', 'lever', 'ashby')
                      AND j.board_token IS NOT NULL
                    LIMIT 1
                ),
                token_status = 'valid'
            WHERE ats_platform IS NULL
              AND id IN (
                  SELECT company_id FROM jobs
                  WHERE site IN ('greenhouse', 'lever', 'ashby')
                    AND board_token IS NOT NULL
                    AND company_id IS NOT NULL
              )
        """)

        # --- Backfill run tracking ---
        conn.execute("""
            UPDATE jobs SET first_seen_run = run_id, last_seen_run = run_id
            WHERE first_seen_run IS NULL
        """)


def _backfill_company_ids(conn):
    """Backfill company_id on jobs that have a company name but no FK link.

    Uses Python's normalize_company_name() for correct suffix stripping,
    rather than attempting to replicate the logic in SQL.
    """
    c = conn.cursor()
    rows = c.execute(
        "SELECT id, company FROM jobs WHERE company_id IS NULL AND company IS NOT NULL"
    ).fetchall()

    if not rows:
        return

    # Build a lookup of normalized name -> company_id
    companies = c.execute("SELECT id, name_normalized FROM companies").fetchall()
    norm_to_id = {norm: cid for cid, norm in companies}

    for job_id, company_name in rows:
        norm = normalize_company_name(company_name)
        if norm and norm in norm_to_id:
            c.execute(
                "UPDATE jobs SET company_id = ? WHERE id = ?",
                (norm_to_id[norm], job_id),
            )
    conn.commit()
```

### Migration from flat token files

Run once during initial `jbs` setup. Prefers validated files over raw files for the same platform.

```python
import os

# For each platform, prefer validated file; fall back to raw.
_TOKEN_FILES = {
    'greenhouse': ['tokens/greenhouse.txt', 'tokens/greenhouse_raw.txt'],
    'lever':      ['tokens/lever.txt', 'tokens/lever_raw.txt'],
    'ashby':      ['tokens/ashby.txt'],
}

for platform, candidates in _TOKEN_FILES.items():
    for path in candidates:
        if os.path.exists(path):
            count = import_tokens_from_file(conn, platform, path)
            print(f"Imported {count} {platform} tokens from {path}")
            break  # Don't import the raw file if validated file was found

# Import 404 blocklists as stale tokens
for platform in ('greenhouse', 'lever', 'ashby'):
    blocklist_path = f'tokens/{platform}_404.txt'
    if os.path.exists(blocklist_path):
        for token in load_tokens(blocklist_path):
            conn.execute("""
                UPDATE companies SET token_status = 'stale'
                WHERE ats_platform = ? AND ats_token = ?
            """, (platform, token))
```

## Column Removed from jobs

The old `company` column (bare string) is renamed in intent to `company_raw`. During migration, its value is copied to `company_raw` and `company_id` is backfilled. New code writes `company_raw` (for debugging) and `company_id` (the FK). The old `company` column is not dropped (SQLite doesn't support DROP COLUMN easily), but new code ignores it.

**FTS5 dependency:** The `jobs_fts` triggers (spec 04) reference `new.company` / `old.company`. Since the column is retained, these triggers continue to work. If the column is ever dropped, the FTS5 triggers must be updated to join through `company_id`.

The old `companies.board_token` and `companies.site` columns (if they exist from a pre-migration schema) are superseded by `ats_platform` and `ats_token`. Same approach: not dropped, but new code uses the new columns.

## Performance Notes

At the expected scale (~3,000 jobs, ~500 companies, single user), all queries run in under 10ms. The indexes are sufficient up to 50k+ jobs. WAL mode is enabled for concurrent reads during long scrape writes.

```python
conn.execute("PRAGMA journal_mode=WAL")
```

## Summary of Tables

| Table | Rows (est.) | Purpose |
|-------|-------------|---------|
| `runs` | ~100 | Scrape execution log |
| `companies` | ~500 | Company facts + ATS tokens |
| `jobs` | ~3,000 | Job postings |
| `company_preferences` | ~50 | User opinions on companies |
| `job_annotations` | ~200 | User opinions on jobs |
| `job_tags` | ~300 | Flat string tags on jobs |
| `hn_career_pages` | ~270 | HN careers page tracking (discovery audit trail) |
| `enrichment_runs` | ~50 | LLM cost tracking |
