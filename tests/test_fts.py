"""Tests for FTS5 search and ranking in jbs.store.Store."""

from datetime import date

import pytest

from jbs.models import Compensation, Job, Location, SearchQuery, WorkArrangement
from jbs.store import Store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store() -> Store:
    return Store(":memory:")


def _make_job(
    id: str = "gh-1",
    source: str = "greenhouse",
    title: str = "Senior Engineer",
    company: str = "Anthropic",
    url: str = "https://example.com/job/1",
    board_token: str | None = "anthropic",
    date_posted: date | None = None,
    location: Location | None = None,
    compensation: Compensation | None = None,
    description: str | None = None,
    **kwargs,
) -> Job:
    return Job(
        id=id,
        source=source,
        title=title,
        company=company,
        url=url,
        location=location or Location(),
        board_token=board_token,
        date_posted=date_posted,
        compensation=compensation,
        description=description,
        **kwargs,
    )


def _seed_run(store: Store, run_id: str = "run-1") -> str:
    store.start_run(run_id, "greenhouse", None)
    return run_id


def _seed_jobs(store: Store) -> str:
    """Seed store with a few jobs for FTS testing. Returns run_id."""
    run_id = _seed_run(store)
    jobs = [
        _make_job(
            id="gh-1", title="Senior ML Engineer",
            company="Anthropic", description="Build large language models and RLHF systems.",
            date_posted=date(2026, 4, 1),
        ),
        _make_job(
            id="gh-2", title="Backend Engineer",
            company="Stripe", description="Work on payment infrastructure with Python and Go.",
            board_token="stripe", date_posted=date(2026, 4, 2),
        ),
        _make_job(
            id="gh-3", title="Staff ML Researcher",
            company="DeepMind", description="Advance reinforcement learning research.",
            board_token="deepmind", date_posted=date(2026, 4, 3),
        ),
        _make_job(
            id="lever-1", source="lever", title="Frontend Engineer",
            company="Vercel", description="Build React components for the dashboard.",
            board_token="vercel", date_posted=date(2026, 3, 30),
        ),
    ]
    store.upsert_jobs(jobs, run_id)
    return run_id


# ---------------------------------------------------------------------------
# FTS5 table creation
# ---------------------------------------------------------------------------

class TestFTSSchema:
    def test_fts_table_created(self):
        store = _make_store()
        conn = store._conn()
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='jobs_fts'"
        ).fetchall()
        assert len(rows) == 1

    def test_triggers_created(self):
        store = _make_store()
        conn = store._conn()
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
        names = {r["name"] for r in rows}
        assert {"jobs_ai", "jobs_ad", "jobs_au"}.issubset(names)

    def test_idempotent_fts_schema(self):
        store = _make_store()
        store._ensure_schema()
        store._ensure_schema()


# ---------------------------------------------------------------------------
# Text search
# ---------------------------------------------------------------------------

class TestFTSSearch:
    def test_text_search_returns_matching_jobs(self):
        store = _make_store()
        _seed_jobs(store)
        results = store.search(SearchQuery(text="reinforcement learning"))
        ids = {r["id"] for r in results}
        assert "gh-3" in ids

    def test_text_search_excludes_non_matching(self):
        store = _make_store()
        _seed_jobs(store)
        results = store.search(SearchQuery(text="React components"))
        ids = {r["id"] for r in results}
        assert "lever-1" in ids
        assert "gh-1" not in ids

    def test_fts_or_syntax(self):
        store = _make_store()
        _seed_jobs(store)
        results = store.search(SearchQuery(text="RLHF OR reinforcement"))
        ids = {r["id"] for r in results}
        assert "gh-1" in ids
        assert "gh-3" in ids

    def test_fts_not_syntax(self):
        store = _make_store()
        _seed_jobs(store)
        # ML jobs but NOT reinforcement
        results = store.search(SearchQuery(text="ML NOT reinforcement"))
        ids = {r["id"] for r in results}
        assert "gh-1" in ids
        assert "gh-3" not in ids

    def test_fts_column_prefix(self):
        store = _make_store()
        _seed_jobs(store)
        # Search only in company column
        results = store.search(SearchQuery(text="company:Anthropic"))
        ids = {r["id"] for r in results}
        assert "gh-1" in ids
        assert "gh-2" not in ids

    def test_no_text_returns_all_active(self):
        store = _make_store()
        _seed_jobs(store)
        results = store.search(SearchQuery())
        assert len(results) == 4

    def test_text_with_structured_filter(self):
        store = _make_store()
        _seed_jobs(store)
        results = store.search(SearchQuery(text="engineer", sites=["greenhouse"]))
        ids = {r["id"] for r in results}
        # lever-1 is "Frontend Engineer" but from lever, should be excluded
        assert "lever-1" not in ids
        # gh-1 and gh-2 have "Engineer" in title, gh-3 doesn't but has ML Researcher
        assert "gh-1" in ids
        assert "gh-2" in ids


# ---------------------------------------------------------------------------
# Ranking with company preferences
# ---------------------------------------------------------------------------

class TestFTSRanking:
    def test_fts_score_present(self):
        store = _make_store()
        _seed_jobs(store)
        results = store.search(SearchQuery(text="engineer"))
        assert all("score" in r for r in results)

    def test_high_rating_company_gets_bonus(self):
        store = _make_store()
        _seed_jobs(store)
        conn = store._conn()

        # Get company_id for Anthropic
        row = conn.execute(
            "SELECT id FROM companies WHERE name_normalized = 'anthropic'"
        ).fetchone()
        assert row is not None
        company_id = row["id"]

        # Rate Anthropic highly
        conn.execute(
            "INSERT INTO company_preferences (company_id, rating) VALUES (?, 5)",
            (company_id,),
        )
        conn.commit()

        results = store.search(SearchQuery(text="engineer"))
        # Anthropic's job should get +0.1 bonus from high rating
        anthropic_result = next(r for r in results if r["id"] == "gh-1")
        stripe_result = next(r for r in results if r["id"] == "gh-2")
        assert anthropic_result["score"] > stripe_result["score"]

    def test_low_rating_company_gets_penalty(self):
        store = _make_store()
        _seed_jobs(store)
        conn = store._conn()

        # Get company_id for Stripe
        row = conn.execute(
            "SELECT id FROM companies WHERE name_normalized = 'stripe'"
        ).fetchone()
        assert row is not None
        company_id = row["id"]

        # Rate Stripe poorly
        conn.execute(
            "INSERT INTO company_preferences (company_id, rating) VALUES (?, 1)",
            (company_id,),
        )
        conn.commit()

        results = store.search(SearchQuery(text="engineer"))
        stripe_result = next(r for r in results if r["id"] == "gh-2")
        anthropic_result = next(r for r in results if r["id"] == "gh-1")
        assert stripe_result["score"] < anthropic_result["score"]

    def test_no_text_score_is_bonus_only(self):
        """Without FTS, score should be just bonuses (no FTS rank component)."""
        store = _make_store()
        _seed_jobs(store)
        results = store.search(SearchQuery())
        # No salary, no ai_native, no prefs => score should be 0
        for r in results:
            assert r["score"] == pytest.approx(0.0)

    def test_salary_bonus(self):
        store = _make_store()
        run_id = _seed_run(store)
        job_with_salary = _make_job(
            id="gh-10", title="ML Engineer", company="SalaryCo",
            compensation=Compensation(min_amount=100000, max_amount=200000),
            date_posted=date(2026, 4, 1),
        )
        job_without = _make_job(
            id="gh-11", title="ML Developer", company="NoSalaryCo",
            date_posted=date(2026, 4, 1),
        )
        store.upsert_jobs([job_with_salary, job_without], run_id)

        results = store.search(SearchQuery(text="ML"))
        salary_result = next(r for r in results if r["id"] == "gh-10")
        no_salary_result = next(r for r in results if r["id"] == "gh-11")
        assert salary_result["score"] > no_salary_result["score"]


# ---------------------------------------------------------------------------
# find_similar
# ---------------------------------------------------------------------------

class TestFindSimilar:
    def test_find_similar_returns_results(self):
        store = _make_store()
        run_id = _seed_run(store)
        conn = store._conn()

        jobs = [
            _make_job(id="gh-100", title="Senior ML Engineer", company="A"),
            _make_job(id="gh-101", title="Senior Backend Engineer", company="B"),
            _make_job(id="gh-102", title="Junior Designer", company="C"),
        ]
        store.upsert_jobs(jobs, run_id)

        # Enrich with domain/seniority
        conn.execute("UPDATE jobs SET domain='ml_ai', seniority='senior' WHERE id='gh-100'")
        conn.execute("UPDATE jobs SET domain='backend', seniority='senior' WHERE id='gh-101'")
        conn.execute("UPDATE jobs SET domain='design', seniority='junior' WHERE id='gh-102'")
        conn.commit()

        results = store.find_similar("gh-100", limit=10)
        assert len(results) > 0
        # Should not include the reference job itself
        ids = {r["id"] for r in results}
        assert "gh-100" not in ids

    def test_find_similar_ranks_by_similarity(self):
        store = _make_store()
        run_id = _seed_run(store)
        conn = store._conn()

        jobs = [
            _make_job(id="gh-200", title="Senior ML Engineer", company="A"),
            _make_job(id="gh-201", title="Senior ML Researcher", company="B"),
            _make_job(id="gh-202", title="Junior Frontend Dev", company="C"),
        ]
        store.upsert_jobs(jobs, run_id)

        conn.execute(
            "UPDATE jobs SET domain='ml_ai', seniority='senior', work_arrangement='remote' WHERE id='gh-200'"
        )
        conn.execute(
            "UPDATE jobs SET domain='ml_ai', seniority='senior', work_arrangement='remote' WHERE id='gh-201'"
        )
        conn.execute(
            "UPDATE jobs SET domain='frontend', seniority='junior', work_arrangement='onsite' WHERE id='gh-202'"
        )
        conn.commit()

        results = store.find_similar("gh-200", limit=10)
        # gh-201 should be most similar (same domain, seniority, work_arrangement)
        assert results[0]["id"] == "gh-201"
        assert results[0]["similarity"] > results[-1]["similarity"]

    def test_find_similar_nonexistent_job(self):
        store = _make_store()
        results = store.find_similar("nonexistent-id")
        assert results == []


# ---------------------------------------------------------------------------
# rebuild_fts
# ---------------------------------------------------------------------------

class TestRebuildFTS:
    def test_rebuild_fts_repopulates(self):
        store = _make_store()
        _seed_jobs(store)

        # Verify FTS works before rebuild
        results = store.search(SearchQuery(text="RLHF"))
        assert len(results) == 1

        # Rebuild and verify still works
        count = store.rebuild_fts()
        assert count == 4

        results = store.search(SearchQuery(text="RLHF"))
        assert len(results) == 1

    def test_rebuild_fts_on_empty_db(self):
        store = _make_store()
        count = store.rebuild_fts()
        assert count == 0

    def test_rebuild_fts_picks_up_direct_inserts(self):
        """If rows were inserted bypassing triggers, rebuild should fix FTS."""
        store = _make_store()
        run_id = _seed_run(store)
        conn = store._conn()

        # Drop triggers temporarily to simulate a broken state
        conn.execute("DROP TRIGGER IF EXISTS jobs_ai")
        conn.execute("DROP TRIGGER IF EXISTS jobs_ad")
        conn.execute("DROP TRIGGER IF EXISTS jobs_au")

        # Direct insert without trigger
        conn.execute(
            """INSERT INTO jobs (id, run_id, site, company_raw, title, description,
                                first_seen_run, last_seen_run)
               VALUES ('direct-1', ?, 'greenhouse', 'TestCo', 'Secret Job',
                       'This is a hidden job about quantum computing', ?, ?)""",
            (run_id, run_id, run_id),
        )
        conn.commit()

        # FTS won't find it
        results = store.search(SearchQuery(text="quantum"))
        assert len(results) == 0

        # Recreate triggers via _ensure_schema, then rebuild
        store._ensure_schema()
        store.rebuild_fts()

        results = store.search(SearchQuery(text="quantum"))
        assert len(results) == 1
        assert results[0]["id"] == "direct-1"
