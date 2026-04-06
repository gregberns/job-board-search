#!/usr/bin/env python3
"""Initialize the SQLite jobs database."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "jobs.db"


def init_db(db_path: Path = DB_PATH):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id      TEXT PRIMARY KEY,
            started_at  TEXT,
            sources     TEXT,
            search_term TEXT,
            total_jobs  INTEGER
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id                TEXT PRIMARY KEY,
            run_id            TEXT NOT NULL,
            site              TEXT,
            title             TEXT,
            company           TEXT,
            board_token       TEXT,

            -- Location (raw + parsed)
            location_raw      TEXT,
            country           TEXT,
            state             TEXT,
            city              TEXT,
            work_arrangement  TEXT,  -- remote, hybrid, onsite, unknown

            -- Job details
            date_posted       TEXT,
            job_url           TEXT,
            job_url_direct    TEXT,
            description       TEXT,
            job_type          TEXT,
            job_function      TEXT,

            -- Compensation
            min_amount        REAL,
            max_amount        REAL,
            currency          TEXT,
            salary_interval   TEXT,

            -- Classification
            engineering_role  BOOLEAN,
            ai_native         REAL,    -- 0.0 to 1.0 confidence
            seniority         TEXT,
            domain            TEXT,
            industry          TEXT,

            -- Meta
            scraped_at        TEXT DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (run_id) REFERENCES runs(run_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            name_normalized TEXT NOT NULL UNIQUE,
            board_token     TEXT,
            site            TEXT,         -- primary source (greenhouse, lever, etc.)
            description     TEXT,         -- what the company does
            industry        TEXT,         -- e.g. AI/ML, FinTech, Healthcare
            ai_native       REAL,         -- 0.0 to 1.0 confidence
            url             TEXT,
            hq_country      TEXT,
            num_employees   TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS hn_career_pages (
            hn_job_id       TEXT PRIMARY KEY REFERENCES jobs(id),
            company_name    TEXT,
            company_url     TEXT,
            careers_url     TEXT,
            ats_platform    TEXT,
            ats_token       TEXT,
            page_type       TEXT,     -- ats, static_html, spa, dead_end, unknown
            status          TEXT DEFAULT 'pending',
            last_checked    TEXT,
            error           TEXT
        )
    """)

    c.execute("CREATE INDEX IF NOT EXISTS idx_hn_careers_status ON hn_career_pages(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_hn_careers_ats ON hn_career_pages(ats_platform)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_companies_norm ON companies(name_normalized)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_companies_ai ON companies(ai_native)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_run ON jobs(run_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_site ON jobs(site)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_eng ON jobs(engineering_role)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_ai ON jobs(ai_native)")

    conn.commit()
    conn.close()
    print(f"Database initialized at {db_path}")


if __name__ == "__main__":
    init_db()
