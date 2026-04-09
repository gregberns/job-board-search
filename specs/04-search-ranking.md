# Spec: Search and Ranking

## Problem

3,000+ jobs in SQLite with classification data (seniority, domain, ai_native, industry) spread across `jobs` and `companies` tables, but no way to search or filter without hand-writing SQL.

## Goal

FTS5 search + structured filters + a simple hardcoded ranking formula. Filters do the heavy lifting; ranking is a tiebreaker.

## Schema Additions

### FTS5 Virtual Table

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5(
    title, company, description, domain,
    content='jobs', content_rowid='rowid',
    tokenize='porter unicode61'
);

-- Keep FTS in sync via triggers
-- Note: FTS column "company" is sourced from jobs.company_raw
CREATE TRIGGER IF NOT EXISTS jobs_ai AFTER INSERT ON jobs BEGIN
    INSERT INTO jobs_fts(rowid, title, company, description, domain)
    VALUES (new.rowid, new.title, new.company_raw, new.description, new.domain);
END;
CREATE TRIGGER IF NOT EXISTS jobs_ad AFTER DELETE ON jobs BEGIN
    INSERT INTO jobs_fts(jobs_fts, rowid, title, company, description, domain)
    VALUES ('delete', old.rowid, old.title, old.company_raw, old.description, old.domain);
END;
CREATE TRIGGER IF NOT EXISTS jobs_au AFTER UPDATE ON jobs BEGIN
    INSERT INTO jobs_fts(jobs_fts, rowid, title, company, description, domain)
    VALUES ('delete', old.rowid, old.title, old.company_raw, old.description, old.domain);
    INSERT INTO jobs_fts(rowid, title, company, description, domain)
    VALUES (new.rowid, new.title, new.company_raw, new.description, new.domain);
END;
```

Backfill: `INSERT INTO jobs_fts(rowid, title, company, description, domain) SELECT rowid, title, company_raw, description, domain FROM jobs;`

**Why `industry` is not in FTS:** `industry` lives on the `companies` table, not `jobs`. It's a structured enum field better used as a filter (`--industry AI/ML`) than full-text searched. The FTS table only indexes columns from `jobs`.

### Supporting Tables

Defined in spec 02: `job_annotations` (single-row per job), `job_tags` (flat strings), `company_preferences` (per company, joined via `company_id`). Not redefined here.

## SearchQuery Dataclass

```python
@dataclass
class SearchQuery:
    text: str | None = None              # FTS5 syntax: '"machine learning" OR pytorch'
    sites: list[str] | None = None       # ["greenhouse", "lever"]
    companies: list[str] | None = None   # matched against companies.name
    seniority: list[str] | None = None   # ["senior", "staff", "principal"]
    domains: list[str] | None = None     # ["ml_ai", "backend"]
    industries: list[str] | None = None  # ["ai_ml", "fintech"] — from companies.industry
    work_arrangement: list[str] | None = None  # ["remote", "hybrid"]
    country: str | None = None
    state: str | None = None
    city: str | None = None
    min_salary: float | None = None      # filters on COALESCE(salary_usd_max, max_amount) >= this
    max_salary: float | None = None      # filters on COALESCE(salary_usd_min, min_amount) <= this
    engineering_only: bool = False        # filter to engineering_role = 1 (opt-in via --engineering)
    ai_native_min: float | None = None   # filters on companies.ai_native >= this
    hours_old: int | None = None
    new_only: bool = False               # jobs from latest run, not yet annotated
    include_inactive: bool = False       # include deactivated jobs (is_active = 0)
    tags: list[str] | None = None        # annotation tags
    rating: int | None = None            # filter to specific job_annotations.rating
    limit: int = 50
    offset: int = 0
```

**`engineering_only` defaults to False.** By default, search returns all jobs. Pass `--engineering` to limit to engineering roles. This avoids hiding unclassified or borderline roles.

## Ranking

One hardcoded formula. Not configurable, not tunable per search.

**With FTS text search active:** rank by FTS5 score, then date, with small bonuses/penalties.

**Without text search:** rank by date_posted DESC, with the same bonuses/penalties.

Bonuses and penalties (additive on a normalized score):
- Has salary data: **+0.1**
- Company rated positively (`company_preferences.rating` > 3): **+0.1**
- `companies.ai_native > 0.7`: **+0.1**
- Company rated poorly (`company_preferences.rating` <= 2): **-0.3**

## FTS5 Query Syntax

| Intent | `text` value |
|--------|-------------|
| ML roles | `machine learning OR "ML engineer"` |
| Python backend, not Java | `python backend NOT java` |
| Search by company | `company:anthropic` |
| Title only | `title:"staff engineer"` |

Note: The FTS column `company` is sourced from `jobs.company_raw` via triggers.

## Query Builder

```python
def build_query(q: SearchQuery) -> tuple[str, list]:
    params, where, joins = [], [], []

    # Always join companies for name, industry, ai_native
    joins.append("LEFT JOIN companies c ON c.id = j.company_id")

    # Company preferences for ranking bonus/penalty
    joins.append("LEFT JOIN company_preferences cp ON cp.company_id = j.company_id")

    # Annotation join (for new_only filter and rating filter)
    joins.append("LEFT JOIN job_annotations a ON a.job_id = j.id")

    # Active filter (default: only active jobs)
    if not q.include_inactive:
        where.append("j.is_active = 1")

    # FTS5
    if q.text:
        joins.append("JOIN jobs_fts ON jobs_fts.rowid = j.rowid")
        where.append("jobs_fts MATCH ?")
        params.append(q.text)

    # Structured filters on jobs table
    for field, vals in [("j.site", q.sites), ("j.seniority", q.seniority),
                        ("j.domain", q.domains),
                        ("j.work_arrangement", q.work_arrangement)]:
        if vals:
            where.append(f"{field} IN ({','.join('?' * len(vals))})")
            params.extend(vals)

    # Structured filters on companies table
    if q.industries:
        where.append(f"c.industry IN ({','.join('?' * len(q.industries))})")
        params.extend(q.industries)

    if q.companies:
        where.append(f"LOWER(c.name) IN ({','.join('?' * len(q.companies))})")
        params.extend(c.lower() for c in q.companies)

    if q.country: where.append("j.country = ?"); params.append(q.country)
    if q.state:   where.append("j.state = ?");   params.append(q.state)
    if q.city:    where.append("LOWER(j.city) = LOWER(?)"); params.append(q.city)

    # Salary filters: prefer normalized USD amounts, fall back to raw
    if q.min_salary is not None:
        where.append("COALESCE(j.salary_usd_max, j.max_amount) >= ?")
        params.append(q.min_salary)
    if q.max_salary is not None:
        where.append("COALESCE(j.salary_usd_min, j.min_amount) <= ?")
        params.append(q.max_salary)

    if q.engineering_only:
        where.append("j.engineering_role = 1")

    if q.ai_native_min is not None:
        where.append("COALESCE(c.ai_native, 0) >= ?")
        params.append(q.ai_native_min)

    if q.hours_old:
        where.append("j.date_posted >= datetime('now', ?)")
        params.append(f"-{q.hours_old} hours")

    if q.new_only:
        where.append("j.last_seen_run = (SELECT MAX(run_id) FROM runs)")
        where.append("a.job_id IS NULL")

    if q.tags:
        for tag in q.tags:
            where.append("j.id IN (SELECT jt.job_id FROM job_tags jt WHERE jt.tag = ?)")
            params.append(tag)

    if q.rating is not None:
        where.append("a.rating = ?")
        params.append(q.rating)

    # Build WHERE clause
    where_clause = " AND ".join(where) if where else "1=1"

    # Ranking score
    if q.text:
        score = """(
            (1.0 / (1.0 + ABS(jobs_fts.rank)))
          + CASE WHEN j.salary_usd_min IS NOT NULL OR j.min_amount IS NOT NULL THEN 0.1 ELSE 0 END
          + CASE WHEN COALESCE(c.ai_native, 0) > 0.7 THEN 0.1 ELSE 0 END
          + CASE WHEN COALESCE(cp.rating, 0) > 3 THEN 0.1 ELSE 0 END
          - CASE WHEN COALESCE(cp.rating, 99) <= 2 THEN 0.3 ELSE 0 END
        ) AS score"""
        order = "score DESC, j.date_posted DESC"
    else:
        score = """(
            CASE WHEN j.salary_usd_min IS NOT NULL OR j.min_amount IS NOT NULL THEN 0.1 ELSE 0 END
          + CASE WHEN COALESCE(c.ai_native, 0) > 0.7 THEN 0.1 ELSE 0 END
          + CASE WHEN COALESCE(cp.rating, 0) > 3 THEN 0.1 ELSE 0 END
          - CASE WHEN COALESCE(cp.rating, 99) <= 2 THEN 0.3 ELSE 0 END
        ) AS score"""
        order = "j.date_posted DESC, score DESC"

    sql = f"""SELECT j.*, COALESCE(c.name, j.company_raw) AS company_name,
                     c.industry, c.ai_native, j.job_summary, {score}
              FROM jobs j {' '.join(joins)}
              WHERE {where_clause}
              ORDER BY {order}
              LIMIT ? OFFSET ?"""
    params.extend([q.limit, q.offset])
    return sql, params
```

## Similar Jobs

Match on structured fields: domain, seniority, work_arrangement. No salary proximity, no ai_native proximity.

```python
def find_similar(job_id: str, limit: int = 20) -> list[dict]:
    ref = conn.execute("SELECT domain, seniority, work_arrangement "
                       "FROM jobs WHERE id = ?", (job_id,)).fetchone()
    domain, seniority, work_arr = ref

    sql = """SELECT j.*, COALESCE(c.name, j.company_raw) AS company_name,
                    j.job_summary, (
          0.50 * (j.domain = ?)
        + 0.30 * (j.seniority = ?)
        + 0.20 * (j.work_arrangement = ?)
        ) AS similarity
        FROM jobs j
        LEFT JOIN companies c ON c.id = j.company_id
        WHERE j.id != ? AND j.is_active = 1
        ORDER BY similarity DESC, j.date_posted DESC LIMIT ?"""
    return conn.execute(sql, [domain, seniority, work_arr, job_id, limit]).fetchall()
```

## Example Usage

```bash
# Remote ML jobs at AI companies, $150k+, staff level
jbs search "ML" --domain ml_ai --remote --seniority staff,principal --min-salary 150000 --ai-native 0.7

# Only engineering roles
jbs search --engineering --remote

# New jobs from latest scrape, not yet reviewed
jbs search --new

# Jobs I rated positively
jbs search --rating 4

# Include inactive (deactivated) jobs in results
jbs search "python" --include-inactive

# Shell alias for a recurring search
alias jbs-ml='jbs search "ML" --ai-native 0.7 --remote --engineering'
```

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `jbs/store.py` | Modify | Add FTS5 virtual table, triggers, `_build_query()`, `find_similar()` |
| `jbs/models.py` | Modify | Add `SearchQuery` dataclass |

## Non-Goals

- **Saved searches table** -- use shell aliases instead.
- **Discovery mode / preference profiles** -- filters are the discovery mode.
- **Configurable ranking weights** -- one formula, hardcoded.
- **Embeddings** -- structured fields suffice at 3k jobs scale.
- **Multi-user** -- single user, no auth.
