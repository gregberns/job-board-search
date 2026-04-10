"""SQLite storage layer. All DB access goes through Store — no raw SQL elsewhere."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from jbs.models import Job, SearchQuery
from jbs.util import normalize_company_name

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_vec(conn: sqlite3.Connection) -> bool:
    """Try to load sqlite-vec extension. Returns True on success."""
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        return True
    except (ImportError, Exception) as exc:
        log.debug("sqlite-vec not available: %s", exc)
        return False


class Store:
    def __init__(self, db_path: Path | str):
        self.db_path = str(db_path)
        self._connection: sqlite3.Connection | None = None
        self._vec_loaded = False
        self._ensure_schema()

    def _conn(self) -> sqlite3.Connection:
        """Lazy connection. WAL mode, FK enforcement, Row factory."""
        if self._connection is None:
            self._connection = sqlite3.connect(self.db_path)
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.row_factory = sqlite3.Row
            self._vec_loaded = _load_vec(self._connection)
        return self._connection

    def has_vec(self) -> bool:
        """Return True if sqlite-vec extension is loaded."""
        self._conn()  # ensure connection (and vec loading) has happened
        return self._vec_loaded

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _ensure_schema(self):
        """Idempotent: CREATE TABLE IF NOT EXISTS, ALTER TABLE ADD COLUMN,
        CREATE INDEX IF NOT EXISTS, and backfills. Safe to call every startup."""
        conn = self._conn()

        # --- Create tables ---
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id      TEXT PRIMARY KEY,
                started_at  TEXT NOT NULL,
                finished_at TEXT,
                sources     TEXT,
                search_term TEXT,
                total_jobs  INTEGER,
                status      TEXT DEFAULT 'running'
                            CHECK(status IN ('running', 'completed', 'failed'))
            );

            CREATE TABLE IF NOT EXISTS companies (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL,
                name_normalized TEXT NOT NULL UNIQUE,
                ats_platform    TEXT
                                CHECK(ats_platform IN ('greenhouse', 'lever', 'ashby') OR ats_platform IS NULL),
                ats_token       TEXT,
                token_status    TEXT DEFAULT 'unchecked'
                                CHECK(token_status IN ('valid', 'stale', 'unchecked')),
                token_checked_at TEXT,
                website         TEXT,
                description     TEXT,
                industry        TEXT,
                ai_native       REAL
                                CHECK(ai_native IS NULL OR (ai_native >= 0.0 AND ai_native <= 1.0)),
                funding_stage   TEXT,
                size_estimate   TEXT,
                hq_country      TEXT,
                tech_stack      TEXT,
                match_status    TEXT DEFAULT 'auto'
                                CHECK(match_status IN ('auto', 'verified', 'unlinked')),
                enriched_at     TEXT,
                created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(ats_platform, ats_token)
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id                TEXT PRIMARY KEY,
                run_id            TEXT NOT NULL,
                site              TEXT NOT NULL
                                  CHECK(site IN ('greenhouse', 'lever', 'ashby', 'remoteok', 'hn')),
                company_id        INTEGER REFERENCES companies(id),
                company_raw       TEXT,
                title             TEXT,
                board_token       TEXT,
                location_raw      TEXT,
                country           TEXT,
                state             TEXT,
                city              TEXT,
                work_arrangement  TEXT
                                  CHECK(work_arrangement IS NULL OR
                                        work_arrangement IN ('remote', 'hybrid', 'onsite', 'unknown')),
                date_posted       TEXT,
                job_url           TEXT,
                job_url_direct    TEXT,
                description       TEXT,
                job_type          TEXT,
                job_function      TEXT,
                min_amount        REAL,
                max_amount        REAL,
                currency          TEXT,
                salary_interval   TEXT,
                salary_usd_min    REAL,
                salary_usd_max    REAL,
                engineering_role  BOOLEAN,
                seniority         TEXT,
                domain            TEXT,
                tech_stack        TEXT,
                job_summary       TEXT,
                visa_sponsorship  TEXT
                                  CHECK(visa_sponsorship IS NULL OR
                                        visa_sponsorship IN ('sponsors', 'no_sponsorship', 'unknown')),
                years_experience  INTEGER,
                is_management     BOOLEAN,
                first_seen_run    TEXT,
                last_seen_run     TEXT,
                miss_count        INTEGER DEFAULT 0,
                is_active         BOOLEAN DEFAULT 1,
                enriched_at       TEXT,
                scraped_at        TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS company_preferences (
                company_id  INTEGER PRIMARY KEY REFERENCES companies(id),
                interest    TEXT
                            CHECK(interest IS NULL OR interest IN ('love', 'like', 'neutral', 'avoid')),
                rating      INTEGER
                            CHECK(rating IS NULL OR (rating >= 1 AND rating <= 5)),
                note        TEXT,
                tags        TEXT,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS job_annotations (
                job_id      TEXT PRIMARY KEY REFERENCES jobs(id),
                rating      INTEGER
                            CHECK(rating IS NULL OR (rating >= 1 AND rating <= 5)),
                interest    TEXT
                            CHECK(interest IS NULL OR interest IN
                                  ('interested', 'applied', 'phone_screen', 'take_home',
                                   'onsite', 'offer', 'rejected', 'withdrawn')),
                note        TEXT,
                pros        TEXT,
                cons        TEXT,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS job_tags (
                job_id      TEXT NOT NULL REFERENCES jobs(id),
                tag         TEXT NOT NULL,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (job_id, tag)
            );

            CREATE TABLE IF NOT EXISTS hn_career_pages (
                hn_job_id       TEXT PRIMARY KEY REFERENCES jobs(id),
                company_name    TEXT,
                company_url     TEXT,
                careers_url     TEXT,
                ats_platform    TEXT
                                CHECK(ats_platform IS NULL OR
                                      ats_platform IN ('greenhouse', 'lever', 'ashby')),
                ats_token       TEXT,
                page_type       TEXT
                                CHECK(page_type IS NULL OR
                                      page_type IN ('ats', 'static_html', 'spa', 'dead_end', 'unknown')),
                status          TEXT DEFAULT 'pending'
                                CHECK(status IN ('pending', 'discovered', 'scraped', 'failed', 'skipped')),
                last_checked    TEXT,
                error           TEXT
            );

            CREATE TABLE IF NOT EXISTS enrichment_runs (
                run_id        TEXT PRIMARY KEY,
                started_at    TEXT NOT NULL,
                finished_at   TEXT,
                stage         TEXT,
                items         INTEGER,
                input_tokens  INTEGER,
                output_tokens INTEGER,
                cost_usd      REAL,
                model         TEXT DEFAULT 'claude-haiku'
            );
        """)

        # --- Add columns to existing tables (migration) ---
        migrations = [
            ("jobs", "company_id", "INTEGER REFERENCES companies(id)"),
            ("jobs", "company_raw", "TEXT"),
            ("jobs", "first_seen_run", "TEXT"),
            ("jobs", "last_seen_run", "TEXT"),
            ("jobs", "miss_count", "INTEGER DEFAULT 0"),
            ("jobs", "is_active", "BOOLEAN DEFAULT 1"),
            ("jobs", "tech_stack", "TEXT"),
            ("jobs", "salary_usd_min", "REAL"),
            ("jobs", "salary_usd_max", "REAL"),
            ("jobs", "enriched_at", "TEXT"),
            ("jobs", "job_summary", "TEXT"),
            ("jobs", "visa_sponsorship", "TEXT"),
            ("jobs", "years_experience", "INTEGER"),
            ("jobs", "is_management", "BOOLEAN"),
            ("jobs", "llm_filter", "TEXT"),
            ("companies", "ats_platform", "TEXT"),
            ("companies", "ats_token", "TEXT"),
            ("companies", "token_status", "TEXT DEFAULT 'unchecked'"),
            ("companies", "token_checked_at", "TEXT"),
            ("companies", "website", "TEXT"),
            ("companies", "match_status", "TEXT DEFAULT 'auto'"),
            ("companies", "funding_stage", "TEXT"),
            ("companies", "size_estimate", "TEXT"),
            ("companies", "tech_stack", "TEXT"),
            ("companies", "enriched_at", "TEXT"),
            ("companies", "created_at", "TEXT DEFAULT CURRENT_TIMESTAMP"),
            ("companies", "updated_at", "TEXT DEFAULT CURRENT_TIMESTAMP"),
            ("runs", "finished_at", "TEXT"),
            ("runs", "status", "TEXT DEFAULT 'running'"),
        ]
        for table, col, typedef in migrations:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
            except sqlite3.OperationalError:
                pass  # column already exists

        # --- Create indexes ---
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_jobs_company_id ON jobs(company_id);
            CREATE INDEX IF NOT EXISTS idx_jobs_site ON jobs(site);
            CREATE INDEX IF NOT EXISTS idx_jobs_active ON jobs(is_active) WHERE is_active = 1;
            CREATE INDEX IF NOT EXISTS idx_jobs_posted ON jobs(date_posted);
            CREATE INDEX IF NOT EXISTS idx_jobs_seniority ON jobs(seniority) WHERE seniority IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_jobs_eng_role ON jobs(engineering_role) WHERE engineering_role = 1;

            CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_ats
                ON companies(ats_platform, ats_token)
                WHERE ats_platform IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_companies_norm ON companies(name_normalized);
            CREATE INDEX IF NOT EXISTS idx_companies_ai ON companies(ai_native) WHERE ai_native IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_companies_token_st ON companies(ats_platform, token_status)
                WHERE ats_platform IS NOT NULL;

            CREATE INDEX IF NOT EXISTS idx_annotations_interest ON job_annotations(interest)
                WHERE interest IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_annotations_rating ON job_annotations(rating)
                WHERE rating IS NOT NULL;

            CREATE INDEX IF NOT EXISTS idx_job_tags_tag ON job_tags(tag);

            CREATE INDEX IF NOT EXISTS idx_hn_careers_status ON hn_career_pages(status);
        """)

        # --- Drop stale FTS artifacts before backfills ---
        # Old DBs may have broken FTS tables/triggers from prior migrations.
        # Drop them; we recreate clean ones after backfills.
        for obj in ['jobs_ai', 'jobs_ad', 'jobs_au']:
            conn.execute(f"DROP TRIGGER IF EXISTS {obj}")
        for tbl in ['jobs_fts', 'jobs_fts_config', 'jobs_fts_data',
                     'jobs_fts_docsize', 'jobs_fts_idx']:
            try:
                conn.execute(f"DROP TABLE IF EXISTS {tbl}")
            except sqlite3.OperationalError:
                pass

        # --- Backfill company_raw from company ---
        # NOTE: FTS5 triggers are created AFTER all backfills (below) to avoid
        # trigger-firing during migration UPDATEs on a contentless FTS table.
        try:
            conn.execute("""
                UPDATE jobs SET company_raw = company
                WHERE company_raw IS NULL AND company IS NOT NULL
            """)
        except sqlite3.OperationalError:
            pass  # 'company' column may not exist on fresh DBs

        # --- Backfill company_id from company name ---
        self._backfill_company_ids(conn)

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

        # --- FTS5 (after all backfills to avoid trigger issues) ---
        # Use content='jobs' so FTS reads from the jobs table directly.
        # This avoids contentless FTS issues with DELETE operations.
        conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5(
            title, company, description, domain,
            content='jobs', content_rowid='rowid',
            tokenize='porter unicode61'
        )""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS jobs_ai AFTER INSERT ON jobs BEGIN
            INSERT INTO jobs_fts(rowid, title, company, description, domain)
            VALUES (new.rowid, new.title, new.company_raw, new.description, new.domain);
        END""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS jobs_ad AFTER DELETE ON jobs BEGIN
            INSERT INTO jobs_fts(jobs_fts, rowid, title, company, description, domain)
            VALUES ('delete', old.rowid, old.title, old.company_raw, old.description, old.domain);
        END""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS jobs_au AFTER UPDATE ON jobs BEGIN
            INSERT INTO jobs_fts(jobs_fts, rowid, title, company, description, domain)
            VALUES ('delete', old.rowid, old.title, old.company_raw, old.description, old.domain);
            INSERT INTO jobs_fts(rowid, title, company, description, domain)
            VALUES (new.rowid, new.title, new.company_raw, new.description, new.domain);
        END""")

        # Rebuild FTS index to catch existing rows
        self.rebuild_fts()

        # --- Vector tables (sqlite-vec) ---
        if self._vec_loaded:
            from jbs.embeddings import SUMMARY_DIM, DESC_DIM
            conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_summaries "
                f"USING vec0(embedding float[{SUMMARY_DIM}] distance_metric=cosine)"
            )
            conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_descriptions "
                f"USING vec0(embedding float[{DESC_DIM}] distance_metric=cosine)"
            )

        conn.commit()

    @staticmethod
    def _backfill_company_ids(conn: sqlite3.Connection):
        """Backfill company_id on jobs that have a company name but no FK link."""
        c = conn.cursor()
        try:
            rows = c.execute(
                "SELECT id, company_raw FROM jobs WHERE company_id IS NULL AND company_raw IS NOT NULL"
            ).fetchall()
        except sqlite3.OperationalError:
            return

        if not rows:
            return

        companies = c.execute("SELECT id, name_normalized FROM companies").fetchall()
        norm_to_id = {row["name_normalized"]: row["id"] for row in companies}

        for row in rows:
            norm = normalize_company_name(row["company_raw"])
            if norm and norm in norm_to_id:
                c.execute(
                    "UPDATE jobs SET company_id = ? WHERE id = ?",
                    (norm_to_id[norm], row["id"]),
                )

    # ------------------------------------------------------------------
    # FTS5
    # ------------------------------------------------------------------

    def rebuild_fts(self) -> int:
        """Full rebuild of FTS5 index from jobs table. Returns row count."""
        conn = self._conn()
        conn.execute("INSERT INTO jobs_fts(jobs_fts) VALUES('delete-all')")
        conn.execute(
            "INSERT INTO jobs_fts(rowid, title, company, description, domain) "
            "SELECT rowid, title, company_raw, description, domain FROM jobs"
        )
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE 1=1"
        ).fetchone()["n"]
        conn.commit()
        return count

    # ------------------------------------------------------------------
    # Run tracking
    # ------------------------------------------------------------------

    def start_run(self, run_id: str, sources: str, search_term: str | None) -> None:
        conn = self._conn()
        conn.execute(
            "INSERT INTO runs (run_id, started_at, sources, search_term, status) VALUES (?, ?, ?, ?, 'running')",
            (run_id, _now_iso(), sources, search_term),
        )
        conn.commit()

    def finish_run(self, run_id: str, total_jobs: int) -> None:
        conn = self._conn()
        conn.execute(
            "UPDATE runs SET finished_at = ?, total_jobs = ?, status = 'completed' WHERE run_id = ?",
            (_now_iso(), total_jobs, run_id),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Job writes
    # ------------------------------------------------------------------

    def upsert_jobs(self, jobs: list[Job], run_id: str) -> int:
        """Upsert jobs. Returns count of newly inserted jobs."""
        conn = self._conn()
        inserted = 0
        for job in jobs:
            company_id = self.resolve_company(job)

            if company_id and job.source in ("greenhouse", "lever", "ashby") and job.company:
                self.maybe_update_company_name(company_id, job.company)

            # Check if job already exists
            existing = conn.execute("SELECT id FROM jobs WHERE id = ?", (job.id,)).fetchone()

            loc = job.location
            comp = job.compensation

            params = {
                "id": job.id,
                "run_id": run_id,
                "site": job.source,
                "company_id": company_id,
                "company_raw": job.company,
                "title": job.title,
                "board_token": job.board_token,
                "location_raw": loc.raw if loc else None,
                "country": loc.country if loc else None,
                "state": loc.state if loc else None,
                "city": loc.city if loc else None,
                "work_arrangement": loc.work_arrangement.value if loc else "unknown",
                "date_posted": str(job.date_posted) if job.date_posted else None,
                "job_url": job.url,
                "job_url_direct": job.url_direct,
                "description": job.description,
                "job_type": job.job_type,
                "job_function": job.job_function,
                "min_amount": comp.min_amount if comp else None,
                "max_amount": comp.max_amount if comp else None,
                "currency": comp.currency if comp else None,
                "salary_interval": comp.interval if comp else None,
                "scraped_at": job.scraped_at.isoformat() if job.scraped_at else _now_iso(),
                "last_seen_run": run_id,
            }

            if existing:
                # UPDATE — preserve first_seen_run, reset miss_count
                conn.execute(
                    """UPDATE jobs SET
                        run_id = :run_id, site = :site, company_id = :company_id,
                        company_raw = :company_raw, title = :title, board_token = :board_token,
                        location_raw = :location_raw, country = :country, state = :state,
                        city = :city, work_arrangement = :work_arrangement,
                        date_posted = :date_posted, job_url = :job_url,
                        job_url_direct = :job_url_direct, description = :description,
                        job_type = :job_type, job_function = :job_function,
                        min_amount = :min_amount, max_amount = :max_amount,
                        currency = :currency, salary_interval = :salary_interval,
                        scraped_at = :scraped_at, last_seen_run = :last_seen_run,
                        miss_count = 0, is_active = 1
                    WHERE id = :id""",
                    params,
                )
            else:
                # INSERT — set first_seen_run
                params["first_seen_run"] = run_id
                conn.execute(
                    """INSERT INTO jobs (
                        id, run_id, site, company_id, company_raw, title, board_token,
                        location_raw, country, state, city, work_arrangement,
                        date_posted, job_url, job_url_direct, description,
                        job_type, job_function, min_amount, max_amount,
                        currency, salary_interval, scraped_at,
                        first_seen_run, last_seen_run, miss_count, is_active
                    ) VALUES (
                        :id, :run_id, :site, :company_id, :company_raw, :title, :board_token,
                        :location_raw, :country, :state, :city, :work_arrangement,
                        :date_posted, :job_url, :job_url_direct, :description,
                        :job_type, :job_function, :min_amount, :max_amount,
                        :currency, :salary_interval, :scraped_at,
                        :first_seen_run, :last_seen_run, 0, 1
                    )""",
                    params,
                )
                inserted += 1

        conn.commit()
        return inserted

    def mark_stale_jobs(self, run_id: str, source: str) -> int:
        """Increment miss_count for jobs from this source not seen in this run.
        Deactivate after 2 consecutive misses. Returns count of newly deactivated."""
        conn = self._conn()

        # Increment miss_count for active jobs from this source not seen in this run
        conn.execute(
            """UPDATE jobs SET miss_count = miss_count + 1
            WHERE site = ? AND last_seen_run != ? AND is_active = 1""",
            (source, run_id),
        )

        # Deactivate jobs that have missed 2+ times
        cursor = conn.execute(
            """UPDATE jobs SET is_active = 0
            WHERE site = ? AND miss_count >= 2 AND is_active = 1""",
            (source,),
        )
        deactivated = cursor.rowcount
        conn.commit()
        return deactivated

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def get_tokens(self, platform: str) -> list[str]:
        """Get active tokens (not stale) for a platform."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT ats_token FROM companies WHERE ats_platform = ? AND token_status != 'stale'",
            (platform,),
        ).fetchall()
        return [r["ats_token"] for r in rows]

    def get_tokens_by_status(self, platform: str, status: str) -> list[str]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT ats_token FROM companies WHERE ats_platform = ? AND token_status = ?",
            (platform, status),
        ).fetchall()
        return [r["ats_token"] for r in rows]

    def get_all_tokens(self, platform: str) -> list[str]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT ats_token FROM companies WHERE ats_platform = ?",
            (platform,),
        ).fetchall()
        return [r["ats_token"] for r in rows]

    def mark_tokens_stale(self, platform: str, tokens: list[str]) -> None:
        if not tokens:
            return
        conn = self._conn()
        placeholders = ",".join("?" * len(tokens))
        conn.execute(
            f"""UPDATE companies SET token_status = 'stale', token_checked_at = CURRENT_TIMESTAMP
            WHERE ats_platform = ? AND ats_token IN ({placeholders})""",
            [platform] + tokens,
        )
        conn.commit()

    def mark_tokens_valid(self, platform: str, tokens: list[str]) -> None:
        if not tokens:
            return
        conn = self._conn()
        placeholders = ",".join("?" * len(tokens))
        conn.execute(
            f"""UPDATE companies SET token_status = 'valid', token_checked_at = CURRENT_TIMESTAMP
            WHERE ats_platform = ? AND ats_token IN ({placeholders})""",
            [platform] + tokens,
        )
        conn.commit()

    def import_tokens(self, platform: str, filepath: str) -> int:
        """Import tokens from a flat file. Returns count of newly imported."""
        conn = self._conn()
        imported = 0

        with open(filepath) as f:
            for line in f:
                token = line.strip()
                if not token or token.startswith("#"):
                    continue

                # Check if (platform, token) already exists
                existing = conn.execute(
                    "SELECT id FROM companies WHERE ats_platform = ? AND ats_token = ?",
                    (platform, token),
                ).fetchone()
                if existing:
                    continue

                # Derive display name from slug
                name = token.replace("-", " ").replace("_", " ").title()
                norm = normalize_company_name(name)

                # Check for normalized name collision
                existing_by_name = conn.execute(
                    "SELECT id FROM companies WHERE name_normalized = ?", (norm,)
                ).fetchone()

                if existing_by_name:
                    # Backfill ATS info on existing company
                    conn.execute(
                        """UPDATE companies SET ats_platform = ?, ats_token = ?,
                           token_status = 'unchecked', updated_at = CURRENT_TIMESTAMP
                           WHERE id = ? AND ats_platform IS NULL""",
                        (platform, token, existing_by_name["id"]),
                    )
                else:
                    conn.execute(
                        """INSERT INTO companies
                           (name, name_normalized, ats_platform, ats_token, token_status, match_status)
                           VALUES (?, ?, ?, ?, 'unchecked', 'auto')""",
                        (name, norm, platform, token),
                    )
                imported += 1

        conn.commit()
        return imported

    def add_token(self, platform: str, token: str, company_name: str | None = None) -> bool:
        """Add a single token. Returns True if newly created, False if already existed."""
        conn = self._conn()

        existing = conn.execute(
            "SELECT id FROM companies WHERE ats_platform = ? AND ats_token = ?",
            (platform, token),
        ).fetchone()
        if existing:
            return False

        name = company_name or token.replace("-", " ").replace("_", " ").title()
        norm = normalize_company_name(name)

        # Check for normalized name collision
        existing_by_name = conn.execute(
            "SELECT id FROM companies WHERE name_normalized = ?", (norm,)
        ).fetchone()

        if existing_by_name:
            conn.execute(
                """UPDATE companies SET ats_platform = ?, ats_token = ?,
                   token_status = 'unchecked', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND ats_platform IS NULL""",
                (platform, token, existing_by_name["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO companies
                   (name, name_normalized, ats_platform, ats_token, token_status, match_status)
                   VALUES (?, ?, ?, ?, 'unchecked', 'auto')""",
                (name, norm, platform, token),
            )

        conn.commit()
        return True

    def get_token_counts(self) -> dict[str, dict[str, int]]:
        """Token counts grouped by platform and status."""
        conn = self._conn()
        rows = conn.execute(
            """SELECT ats_platform, token_status, COUNT(*) AS cnt
            FROM companies WHERE ats_platform IS NOT NULL
            GROUP BY ats_platform, token_status"""
        ).fetchall()
        result: dict[str, dict[str, int]] = {}
        for row in rows:
            platform = row["ats_platform"]
            if platform not in result:
                result[platform] = {"valid": 0, "stale": 0, "unchecked": 0}
            result[platform][row["token_status"]] = row["cnt"]
        return result

    # ------------------------------------------------------------------
    # Company resolution
    # ------------------------------------------------------------------

    def resolve_company(self, job: Job) -> int | None:
        """Resolve a job to a company_id using the spec 02 algorithm."""
        conn = self._conn()
        c = conn.cursor()

        # Step 1: ATS token match
        if job.board_token and job.source in ("greenhouse", "lever", "ashby"):
            row = c.execute(
                "SELECT id FROM companies WHERE ats_platform = ? AND ats_token = ?",
                (job.source, job.board_token),
            ).fetchone()
            if row:
                return row["id"]

        # Step 2: Normalized name match
        if job.company:
            norm = normalize_company_name(job.company)
            if norm:
                row = c.execute(
                    "SELECT id FROM companies WHERE name_normalized = ?",
                    (norm,),
                ).fetchone()
                if row:
                    company_id = row["id"]
                    # Backfill ATS info if missing
                    if job.board_token and job.source in ("greenhouse", "lever", "ashby"):
                        c.execute(
                            """UPDATE companies SET ats_platform = ?, ats_token = ?,
                               token_status = 'valid', updated_at = CURRENT_TIMESTAMP
                               WHERE id = ? AND ats_platform IS NULL""",
                            (job.source, job.board_token, company_id),
                        )
                    return company_id

        # Step 3: Create new company
        if not job.company:
            return None

        norm = normalize_company_name(job.company)
        if not norm:
            return None

        ats_platform = job.source if job.source in ("greenhouse", "lever", "ashby") else None
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
                "valid" if ats_token else "unchecked",
            ),
        )
        return c.lastrowid

    def maybe_update_company_name(self, company_id: int, api_name: str) -> None:
        """Update display name if current name looks slug-derived."""
        conn = self._conn()
        row = conn.execute(
            "SELECT name, name_normalized FROM companies WHERE id = ?",
            (company_id,),
        ).fetchone()
        if not row:
            return

        current_name = row["name"]
        current_norm = row["name_normalized"]

        new_norm = normalize_company_name(api_name)
        if new_norm != current_norm:
            return  # different company, don't touch

        # Only update if current name looks slug-derived
        if " " not in current_name.strip() or current_name == current_name.title():
            conn.execute(
                "UPDATE companies SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (api_name.strip(), company_id),
            )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def search(self, query: SearchQuery) -> list[dict]:
        """Search jobs with structured filters and FTS5 full-text search.
        Dispatches to hybrid_search when vec_query is provided."""
        if getattr(query, 'vec_query', None) and self._vec_loaded:
            return self.hybrid_search(query)
        conn = self._conn()
        params: list = []
        where: list[str] = []
        joins = [
            "LEFT JOIN companies c ON c.id = j.company_id",
            "LEFT JOIN company_preferences cp ON cp.company_id = j.company_id",
            "LEFT JOIN job_annotations a ON a.job_id = j.id",
        ]

        # Active filter
        if not query.include_inactive:
            where.append("j.is_active = 1")

        # FTS5 text search
        if query.text:
            joins.append("JOIN jobs_fts ON jobs_fts.rowid = j.rowid")
            where.append("jobs_fts MATCH ?")
            params.append(query.text)

        # Structured filters on jobs
        for field, vals in [
            ("j.site", query.sites),
            ("j.seniority", query.seniority),
            ("j.domain", query.domains),
            ("j.work_arrangement", query.work_arrangement),
        ]:
            if vals:
                placeholders = ",".join("?" * len(vals))
                where.append(f"{field} IN ({placeholders})")
                params.extend(vals)

        # Structured filters on companies
        if query.industries:
            placeholders = ",".join("?" * len(query.industries))
            where.append(f"c.industry IN ({placeholders})")
            params.extend(query.industries)

        if query.companies:
            placeholders = ",".join("?" * len(query.companies))
            where.append(f"LOWER(c.name) IN ({placeholders})")
            params.extend(c.lower() for c in query.companies)

        if query.country:
            where.append("j.country = ?")
            params.append(query.country)
        if query.state:
            where.append("j.state = ?")
            params.append(query.state)
        if query.city:
            where.append("LOWER(j.city) = LOWER(?)")
            params.append(query.city)

        # Salary filters
        if query.min_salary is not None:
            where.append("COALESCE(j.salary_usd_max, j.max_amount) >= ?")
            params.append(query.min_salary)
        if query.max_salary is not None:
            where.append("COALESCE(j.salary_usd_min, j.min_amount) <= ?")
            params.append(query.max_salary)

        if query.engineering_only:
            where.append("j.engineering_role = 1")

        if query.ai_native_min is not None:
            where.append("COALESCE(c.ai_native, 0) >= ?")
            params.append(query.ai_native_min)

        if query.hours_old:
            where.append("j.date_posted >= datetime('now', ?)")
            params.append(f"-{query.hours_old} hours")

        if query.new_only:
            where.append("j.last_seen_run = (SELECT MAX(run_id) FROM runs)")
            where.append("a.job_id IS NULL")

        if query.tags:
            for tag in query.tags:
                where.append("j.id IN (SELECT jt.job_id FROM job_tags jt WHERE jt.tag = ?)")
                params.append(tag)

        if query.rating is not None:
            where.append("a.rating = ?")
            params.append(query.rating)

        where_clause = " AND ".join(where) if where else "1=1"

        # Ranking score
        if query.text:
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
        params.extend([query.limit, query.offset])

        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_job(self, job_id: str) -> dict | None:
        conn = self._conn()
        row = conn.execute(
            """SELECT j.*, COALESCE(c.name, j.company_raw) AS company_name,
                      c.industry, c.ai_native, c.website AS company_website,
                      c.description AS company_description,
                      a.rating AS annotation_rating, a.interest AS annotation_interest,
                      a.note AS annotation_note, a.pros, a.cons
               FROM jobs j
               LEFT JOIN companies c ON c.id = j.company_id
               LEFT JOIN job_annotations a ON a.job_id = j.id
               WHERE j.id = ?""",
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        # Attach tags
        tags = conn.execute(
            "SELECT tag FROM job_tags WHERE job_id = ?", (job_id,)
        ).fetchall()
        result["tags"] = [t["tag"] for t in tags]
        return result

    def find_similar(self, job_id: str, limit: int = 20) -> list[dict]:
        """Find structurally similar jobs based on domain, seniority, work_arrangement."""
        conn = self._conn()
        ref = conn.execute(
            "SELECT domain, seniority, work_arrangement FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if ref is None:
            return []

        domain, seniority, work_arr = ref["domain"], ref["seniority"], ref["work_arrangement"]

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
        rows = conn.execute(sql, [domain, seniority, work_arr, job_id, limit]).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Hybrid search (vector + FTS5 + structured filters)
    # ------------------------------------------------------------------

    def hybrid_search(self, query: SearchQuery) -> list[dict]:
        """Vector + FTS5 + structured filters combined via RRF and re-ranking.

        1. Structured filters -> candidate ID set
        2. FTS5 keyword ranking (if query.text)
        3. Vector KNN on summaries + descriptions (query.vec_query)
        4. RRF to merge ranked lists
        5. Cross-encoder re-rank top 50
        6. Fetch full results for top-N
        """
        from jbs.embeddings import get_embedder, rrf_combine

        conn = self._conn()

        # --- Build structured WHERE clause (no FTS, no scoring) ---
        params: list = []
        where: list[str] = []

        if not query.include_inactive:
            where.append("j.is_active = 1")

        for field, vals in [
            ("j.site", query.sites),
            ("j.seniority", query.seniority),
            ("j.domain", query.domains),
            ("j.work_arrangement", query.work_arrangement),
        ]:
            if vals:
                placeholders = ",".join("?" * len(vals))
                where.append(f"{field} IN ({placeholders})")
                params.extend(vals)

        if query.industries:
            placeholders = ",".join("?" * len(query.industries))
            where.append(f"c.industry IN ({placeholders})")
            params.extend(query.industries)

        if query.companies:
            placeholders = ",".join("?" * len(query.companies))
            where.append(f"LOWER(c.name) IN ({placeholders})")
            params.extend(c.lower() for c in query.companies)

        if query.min_salary is not None:
            where.append("COALESCE(j.salary_usd_max, j.max_amount) >= ?")
            params.append(query.min_salary)
        if query.max_salary is not None:
            where.append("COALESCE(j.salary_usd_min, j.min_amount) <= ?")
            params.append(query.max_salary)

        if query.engineering_only:
            where.append("j.engineering_role = 1")

        if query.ai_native_min is not None:
            where.append("COALESCE(c.ai_native, 0) >= ?")
            params.append(query.ai_native_min)

        if query.hours_old:
            where.append("j.date_posted >= datetime('now', ?)")
            params.append(f"-{query.hours_old} hours")

        if query.new_only:
            where.append("j.last_seen_run = (SELECT MAX(run_id) FROM runs)")

        if query.tags:
            for tag in query.tags:
                where.append("j.id IN (SELECT jt.job_id FROM job_tags jt WHERE jt.tag = ?)")
                params.append(tag)

        where_clause = " AND ".join(where) if where else "1=1"

        # Get candidate IDs passing structured filters
        candidate_sql = f"""SELECT j.id FROM jobs j
            LEFT JOIN companies c ON c.id = j.company_id
            WHERE {where_clause}"""
        candidate_ids = {r["id"] for r in conn.execute(candidate_sql, params).fetchall()}

        if not candidate_ids:
            return []

        # --- Gather ranked lists ---
        ranked_lists: list[list[tuple[str, float]]] = []

        # FTS5 keyword ranking
        if query.text:
            fts_results = self._fts_rank(query.text, limit=500)
            fts_filtered = [(jid, score) for jid, score in fts_results if jid in candidate_ids]
            if fts_filtered:
                ranked_lists.append(fts_filtered)

        # Vector KNN
        embedder = get_embedder()

        summary_q = embedder.query_summary(query.vec_query)
        summary_results = self._vec_knn("vec_summaries", summary_q, k=500)
        summary_filtered = [(jid, dist) for jid, dist in summary_results if jid in candidate_ids]
        if summary_filtered:
            ranked_lists.append(summary_filtered)

        desc_q = embedder.query_description(query.vec_query)
        desc_results = self._vec_knn("vec_descriptions", desc_q, k=500)
        desc_filtered = [(jid, dist) for jid, dist in desc_results if jid in candidate_ids]
        if desc_filtered:
            ranked_lists.append(desc_filtered)

        if not ranked_lists:
            return []

        # --- RRF combine ---
        combined = rrf_combine(*ranked_lists)

        # --- Cross-encoder re-rank top 50 ---
        rerank_count = min(50, len(combined))
        rerank_ids = [jid for jid, _score in combined[:rerank_count]]

        # Fetch job data for re-ranking text
        placeholders = ",".join("?" * len(rerank_ids))
        rerank_rows = conn.execute(
            f"""SELECT j.id, j.title, j.job_summary, j.description,
                       COALESCE(c.name, j.company_raw) AS company_name
                FROM jobs j
                LEFT JOIN companies c ON c.id = j.company_id
                WHERE j.id IN ({placeholders})""",
            rerank_ids,
        ).fetchall()
        id_to_rerank = {r["id"]: r for r in rerank_rows}

        # Build rerank documents
        rerank_docs = []
        rerank_doc_ids = []
        for jid in rerank_ids:
            r = id_to_rerank.get(jid)
            if r:
                title = r["title"] or ""
                company = r["company_name"] or ""
                summary = r["job_summary"] or (r["description"] or "")[:500]
                rerank_docs.append(f"{title} at {company}. {summary}")
                rerank_doc_ids.append(jid)

        if rerank_docs:
            reranked = embedder.rerank(query.vec_query, rerank_docs, top_n=rerank_count)
            final_order = [rerank_doc_ids[idx] for idx, _score in reranked]
            # Append any RRF results beyond the reranked set
            reranked_set = set(final_order)
            for jid, _score in combined[rerank_count:]:
                if jid not in reranked_set:
                    final_order.append(jid)
        else:
            final_order = [jid for jid, _score in combined]

        # Apply offset/limit
        page = final_order[query.offset:query.offset + query.limit]
        if not page:
            return []

        # --- Fetch full details ---
        placeholders = ",".join("?" * len(page))
        rows = conn.execute(
            f"""SELECT j.*, COALESCE(c.name, j.company_raw) AS company_name,
                       c.industry, c.ai_native, j.job_summary
                FROM jobs j
                LEFT JOIN companies c ON c.id = j.company_id
                WHERE j.id IN ({placeholders})""",
            page,
        ).fetchall()

        # Preserve ordering
        id_to_row = {dict(r)["id"]: dict(r) for r in rows}
        rrf_scores = {jid: score for jid, score in combined}
        result = []
        for jid in page:
            if jid in id_to_row:
                row = id_to_row[jid]
                row["score"] = rrf_scores.get(jid, 0)
                result.append(row)
        return result

    # ------------------------------------------------------------------
    # Vector search
    # ------------------------------------------------------------------

    def has_vec(self) -> bool:
        """Check if sqlite-vec is loaded and vec tables exist."""
        return self._vec_loaded

    def get_vec_counts(self) -> dict[str, int]:
        """Count of embeddings in each vec table."""
        conn = self._conn()
        counts = {}
        for tbl in ("vec_summaries", "vec_descriptions"):
            try:
                counts[tbl] = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            except sqlite3.OperationalError:
                counts[tbl] = 0
        return counts

    def get_unembedded_jobs(self, limit: int = 500) -> list[dict]:
        """Get active jobs that don't yet have summary embeddings."""
        conn = self._conn()
        rows = conn.execute(
            """SELECT j.rowid, j.id, j.title, j.company_raw, j.description,
                      j.job_summary, j.domain, j.tech_stack,
                      COALESCE(c.name, j.company_raw) AS company_name,
                      c.description AS company_description
               FROM jobs j
               LEFT JOIN companies c ON c.id = j.company_id
               WHERE j.is_active = 1
                 AND j.description IS NOT NULL
                 AND j.rowid NOT IN (SELECT rowid FROM vec_summaries)
               ORDER BY j.date_posted DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def store_embeddings(
        self,
        rows: list[tuple[int, np.ndarray | None, np.ndarray | None]],
    ) -> int:
        """Store embedding vectors. rows: [(rowid, summary_vec, desc_vec), ...].
        Returns count stored."""
        conn = self._conn()
        stored = 0
        for rowid, summary_vec, desc_vec in rows:
            if summary_vec is not None:
                blob = summary_vec.astype(np.float32).tobytes()
                conn.execute(
                    "INSERT OR REPLACE INTO vec_summaries(rowid, embedding) VALUES (?, ?)",
                    (rowid, blob),
                )
                stored += 1
            if desc_vec is not None:
                blob = desc_vec.astype(np.float32).tobytes()
                conn.execute(
                    "INSERT OR REPLACE INTO vec_descriptions(rowid, embedding) VALUES (?, ?)",
                    (rowid, blob),
                )
        conn.commit()
        return stored

    def _vec_knn(self, table: str, query_vec: np.ndarray, k: int = 200) -> list[tuple[str, float]]:
        """Run KNN on a vec table. Returns [(job_id, distance), ...]."""
        conn = self._conn()
        blob = query_vec.astype(np.float32).tobytes()
        rows = conn.execute(
            f"""SELECT v.rowid, v.distance, j.id
                FROM {table} v
                JOIN jobs j ON j.rowid = v.rowid
                WHERE v.embedding MATCH ? AND k = ?
                ORDER BY v.distance""",
            (blob, k),
        ).fetchall()
        return [(r["id"], r["distance"]) for r in rows]

    def _fts_rank(self, text: str, limit: int = 200) -> list[tuple[str, float]]:
        """Run FTS5 search. Returns [(job_id, rank_score), ...]."""
        conn = self._conn()
        rows = conn.execute(
            """SELECT j.id, (1.0 / (1.0 + ABS(jobs_fts.rank))) AS score
               FROM jobs_fts
               JOIN jobs j ON j.rowid = jobs_fts.rowid
               WHERE jobs_fts MATCH ?
               ORDER BY score DESC
               LIMIT ?""",
            (text, limit),
        ).fetchall()
        return [(r["id"], r["score"]) for r in rows]

    def get_stats(self) -> dict:
        conn = self._conn()

        jobs_total = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]
        jobs_active = conn.execute("SELECT COUNT(*) AS n FROM jobs WHERE is_active = 1").fetchone()["n"]
        companies_total = conn.execute("SELECT COUNT(*) AS n FROM companies").fetchone()["n"]

        site_counts = conn.execute(
            "SELECT site, COUNT(*) AS n FROM jobs WHERE is_active = 1 GROUP BY site"
        ).fetchall()

        latest_run = conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()

        return {
            "jobs_total": jobs_total,
            "jobs_active": jobs_active,
            "companies": companies_total,
            "by_site": {r["site"]: r["n"] for r in site_counts},
            "latest_run": dict(latest_run) if latest_run else None,
            "token_counts": self.get_token_counts(),
        }

    # ------------------------------------------------------------------
    # Enrichment
    # ------------------------------------------------------------------

    def get_unenriched_jobs(self, limit: int = 100) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            """SELECT j.*, COALESCE(c.name, j.company_raw) AS company_name
               FROM jobs j
               LEFT JOIN companies c ON c.id = j.company_id
               WHERE j.enriched_at IS NULL AND j.is_active = 1
               ORDER BY j.date_posted DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_unenriched_companies(self, limit: int = 100) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            """SELECT * FROM companies
               WHERE enriched_at IS NULL
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_job_enrichment(self, job_id: str, **fields) -> None:
        conn = self._conn()
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values())
        conn.execute(
            f"UPDATE jobs SET {sets}, enriched_at = CURRENT_TIMESTAMP WHERE id = ?",
            vals + [job_id],
        )
        conn.commit()

    def update_company_enrichment(self, company_id: int, **fields) -> None:
        conn = self._conn()
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values())
        conn.execute(
            f"UPDATE companies SET {sets}, enriched_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            vals + [company_id],
        )
        conn.commit()

    def record_enrichment_run(self, **fields) -> None:
        conn = self._conn()
        cols = ", ".join(fields.keys())
        placeholders = ", ".join("?" * len(fields))
        conn.execute(
            f"INSERT INTO enrichment_runs ({cols}) VALUES ({placeholders})",
            list(fields.values()),
        )
        conn.commit()

    def get_greenhouse_html_jobs(self) -> list[tuple[str, str]]:
        """Get Greenhouse jobs with HTML descriptions for cleanup."""
        conn = self._conn()
        rows = conn.execute(
            """SELECT id, description FROM jobs
               WHERE site = 'greenhouse' AND description LIKE '%<%>%'
               AND is_active = 1"""
        ).fetchall()
        return [(r["id"], r["description"]) for r in rows]

    def get_remoteok_mojibake_jobs(self) -> list[tuple[str, str]]:
        """Get RemoteOK jobs with potential mojibake descriptions."""
        conn = self._conn()
        rows = conn.execute(
            r"""SELECT id, description FROM jobs
               WHERE site = 'remoteok' AND description LIKE '%Ã%'
               AND is_active = 1"""
        ).fetchall()
        return [(r["id"], r["description"]) for r in rows]

    def update_description(self, job_id: str, description: str) -> None:
        conn = self._conn()
        conn.execute(
            "UPDATE jobs SET description = ? WHERE id = ?",
            (description, job_id),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Annotations
    # ------------------------------------------------------------------

    def annotate(self, job_id: str, **kwargs) -> None:
        """Insert or update job_annotations. Pass any subset of: rating, interest, note, pros, cons."""
        conn = self._conn()
        existing = conn.execute(
            "SELECT job_id FROM job_annotations WHERE job_id = ?", (job_id,)
        ).fetchone()

        if existing:
            sets = ", ".join(f"{k} = ?" for k in kwargs)
            vals = list(kwargs.values())
            conn.execute(
                f"UPDATE job_annotations SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE job_id = ?",
                vals + [job_id],
            )
        else:
            kwargs["job_id"] = job_id
            cols = ", ".join(kwargs.keys())
            placeholders = ", ".join("?" * len(kwargs))
            conn.execute(
                f"INSERT INTO job_annotations ({cols}) VALUES ({placeholders})",
                list(kwargs.values()),
            )
        conn.commit()

    def add_tag(self, job_id: str, tag: str) -> None:
        conn = self._conn()
        conn.execute(
            "INSERT OR IGNORE INTO job_tags (job_id, tag) VALUES (?, ?)",
            (job_id, tag),
        )
        conn.commit()

    def remove_tag(self, job_id: str, tag: str) -> None:
        conn = self._conn()
        conn.execute(
            "DELETE FROM job_tags WHERE job_id = ? AND tag = ?",
            (job_id, tag),
        )
        conn.commit()

    def set_interest(self, job_id: str, interest: str, note: str | None = None) -> None:
        """Convenience wrapper for annotate with interest + optional note."""
        kwargs: dict = {"interest": interest}
        if note is not None:
            kwargs["note"] = note
        self.annotate(job_id, **kwargs)

    # ------------------------------------------------------------------
    # HN Career Pages
    # ------------------------------------------------------------------

    def get_unprocessed_hn_urls(self) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            """SELECT j.id, j.job_url, j.company_raw
               FROM jobs j
               LEFT JOIN hn_career_pages h ON h.hn_job_id = j.id
               WHERE j.site = 'hn' AND j.job_url IS NOT NULL AND h.hn_job_id IS NULL"""
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_hn_career_page(self, hn_job_id: str, **fields) -> None:
        conn = self._conn()
        existing = conn.execute(
            "SELECT hn_job_id FROM hn_career_pages WHERE hn_job_id = ?", (hn_job_id,)
        ).fetchone()

        if existing:
            if fields:
                sets = ", ".join(f"{k} = ?" for k in fields)
                vals = list(fields.values())
                conn.execute(
                    f"UPDATE hn_career_pages SET {sets} WHERE hn_job_id = ?",
                    vals + [hn_job_id],
                )
        else:
            fields["hn_job_id"] = hn_job_id
            cols = ", ".join(fields.keys())
            placeholders = ", ".join("?" * len(fields))
            conn.execute(
                f"INSERT INTO hn_career_pages ({cols}) VALUES ({placeholders})",
                list(fields.values()),
            )
        conn.commit()

    def update_hn_career_page(self, hn_job_id: str, **fields) -> None:
        conn = self._conn()
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values())
        conn.execute(
            f"UPDATE hn_career_pages SET {sets} WHERE hn_job_id = ?",
            vals + [hn_job_id],
        )
        conn.commit()

    def get_hn_pages_by_status(self, status: str) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM hn_career_pages WHERE status = ?", (status,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_hn_discovery_summary(self) -> dict:
        conn = self._conn()
        status_counts = conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM hn_career_pages GROUP BY status"
        ).fetchall()
        platform_counts = conn.execute(
            """SELECT ats_platform, COUNT(*) AS cnt FROM hn_career_pages
               WHERE ats_platform IS NOT NULL GROUP BY ats_platform"""
        ).fetchall()
        return {
            "total": sum(r["cnt"] for r in status_counts),
            "by_status": {r["status"]: r["cnt"] for r in status_counts},
            "by_platform": {r["ats_platform"]: r["cnt"] for r in platform_counts},
        }
