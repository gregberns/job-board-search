"""Tests for jbs.store.Store using :memory: SQLite."""

import tempfile
from datetime import date
from pathlib import Path

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
        **kwargs,
    )


def _seed_run(store: Store, run_id: str = "run-1") -> str:
    store.start_run(run_id, "greenhouse", None)
    return run_id


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class TestSchema:
    def test_all_8_tables_created(self):
        store = _make_store()
        conn = store._conn()
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        tables = {r["name"] for r in rows}
        expected = {
            "runs", "companies", "jobs", "company_preferences",
            "job_annotations", "job_tags", "hn_career_pages", "enrichment_runs",
        }
        assert expected.issubset(tables), f"Missing tables: {expected - tables}"

    def test_idempotent_schema(self):
        """Calling _ensure_schema twice should not error."""
        store = _make_store()
        store._ensure_schema()
        store._ensure_schema()

    def test_wal_mode(self):
        store = _make_store()
        mode = store._conn().execute("PRAGMA journal_mode").fetchone()[0]
        # :memory: may not support WAL, but the pragma shouldn't error
        assert mode in ("wal", "memory")

    def test_foreign_keys_enabled(self):
        store = _make_store()
        fk = store._conn().execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1


# ---------------------------------------------------------------------------
# Run tracking
# ---------------------------------------------------------------------------

class TestRunTracking:
    def test_start_and_finish_run(self):
        store = _make_store()
        store.start_run("run-1", "greenhouse,lever", "python")
        row = store._conn().execute("SELECT * FROM runs WHERE run_id = 'run-1'").fetchone()
        assert row["status"] == "running"
        assert row["sources"] == "greenhouse,lever"
        assert row["search_term"] == "python"

        store.finish_run("run-1", 42)
        row = store._conn().execute("SELECT * FROM runs WHERE run_id = 'run-1'").fetchone()
        assert row["status"] == "completed"
        assert row["total_jobs"] == 42
        assert row["finished_at"] is not None


# ---------------------------------------------------------------------------
# Company resolution
# ---------------------------------------------------------------------------

class TestResolveCompany:
    def test_ats_token_match(self):
        store = _make_store()
        conn = store._conn()
        conn.execute(
            """INSERT INTO companies (name, name_normalized, ats_platform, ats_token, token_status)
               VALUES ('Anthropic', 'anthropic', 'greenhouse', 'anthropic', 'valid')"""
        )
        conn.commit()

        job = _make_job(source="greenhouse", company="Anthropic, Inc.", board_token="anthropic")
        cid = store.resolve_company(job)
        assert cid is not None

        row = conn.execute("SELECT name FROM companies WHERE id = ?", (cid,)).fetchone()
        assert row["name"] == "Anthropic"

    def test_normalized_name_match(self):
        store = _make_store()
        conn = store._conn()
        conn.execute(
            """INSERT INTO companies (name, name_normalized)
               VALUES ('Ramp Technologies', 'ramptechnologies')"""
        )
        conn.commit()

        job = _make_job(id="rok-1", source="remoteok", company="Ramp Technologies, Inc.", board_token=None)
        cid = store.resolve_company(job)
        assert cid is not None

    def test_name_match_backfills_ats(self):
        """When name-matched, should backfill ATS info if company didn't have it."""
        store = _make_store()
        conn = store._conn()
        conn.execute(
            """INSERT INTO companies (name, name_normalized)
               VALUES ('Ramp', 'ramp')"""
        )
        conn.commit()

        job = _make_job(id="gh-ramp", source="greenhouse", company="Ramp", board_token="ramp")
        cid = store.resolve_company(job)
        assert cid is not None

        row = conn.execute("SELECT ats_platform, ats_token FROM companies WHERE id = ?", (cid,)).fetchone()
        assert row["ats_platform"] == "greenhouse"
        assert row["ats_token"] == "ramp"

    def test_create_new_company(self):
        store = _make_store()
        job = _make_job(id="gh-new", source="greenhouse", company="NewCo AI", board_token="newco-ai")
        cid = store.resolve_company(job)
        assert cid is not None

        row = store._conn().execute("SELECT * FROM companies WHERE id = ?", (cid,)).fetchone()
        assert row["name"] == "NewCo AI"
        assert row["name_normalized"] == "newcoai"
        assert row["ats_platform"] == "greenhouse"
        assert row["ats_token"] == "newco-ai"
        assert row["token_status"] == "valid"

    def test_no_company_returns_none(self):
        store = _make_store()
        job = _make_job(id="hn-1", source="hn", company=None, board_token=None)
        cid = store.resolve_company(job)
        assert cid is None

    def test_non_ats_creates_without_token(self):
        store = _make_store()
        job = _make_job(id="rok-1", source="remoteok", company="SomeCompany", board_token=None)
        cid = store.resolve_company(job)
        assert cid is not None

        row = store._conn().execute("SELECT * FROM companies WHERE id = ?", (cid,)).fetchone()
        assert row["ats_platform"] is None
        assert row["ats_token"] is None


# ---------------------------------------------------------------------------
# maybe_update_company_name
# ---------------------------------------------------------------------------

class TestMaybeUpdateCompanyName:
    def test_updates_slug_derived_name(self):
        store = _make_store()
        conn = store._conn()
        conn.execute(
            """INSERT INTO companies (name, name_normalized, ats_platform, ats_token)
               VALUES ('Anthropic', 'anthropic', 'greenhouse', 'anthropic')"""
        )
        conn.commit()
        cid = conn.execute("SELECT id FROM companies WHERE name_normalized = 'anthropic'").fetchone()["id"]

        store.maybe_update_company_name(cid, "Anthropic, Inc.")
        row = conn.execute("SELECT name FROM companies WHERE id = ?", (cid,)).fetchone()
        assert row["name"] == "Anthropic, Inc."

    def test_does_not_update_different_company(self):
        store = _make_store()
        conn = store._conn()
        conn.execute(
            """INSERT INTO companies (name, name_normalized)
               VALUES ('Acme', 'acme')"""
        )
        conn.commit()
        cid = conn.execute("SELECT id FROM companies WHERE name_normalized = 'acme'").fetchone()["id"]

        store.maybe_update_company_name(cid, "Totally Different Corp")
        row = conn.execute("SELECT name FROM companies WHERE id = ?", (cid,)).fetchone()
        assert row["name"] == "Acme"


# ---------------------------------------------------------------------------
# upsert_jobs
# ---------------------------------------------------------------------------

class TestUpsertJobs:
    def test_insert_new_jobs(self):
        store = _make_store()
        run_id = _seed_run(store)
        jobs = [
            _make_job(id="gh-1", company="Anthropic", board_token="anthropic"),
            _make_job(id="gh-2", company="Scale AI", board_token="scaleai"),
        ]
        inserted = store.upsert_jobs(jobs, run_id)
        assert inserted == 2

        row = store._conn().execute("SELECT * FROM jobs WHERE id = 'gh-1'").fetchone()
        assert row["site"] == "greenhouse"
        assert row["company_raw"] == "Anthropic"
        assert row["first_seen_run"] == run_id
        assert row["last_seen_run"] == run_id
        assert row["miss_count"] == 0
        assert row["is_active"] == 1

    def test_upsert_existing_job(self):
        store = _make_store()
        run1 = _seed_run(store, "run-1")
        job = _make_job(id="gh-1", title="Engineer v1")
        store.upsert_jobs([job], run1)

        store.start_run("run-2", "greenhouse", None)
        job2 = _make_job(id="gh-1", title="Engineer v2")
        inserted = store.upsert_jobs([job2], "run-2")
        assert inserted == 0  # no new insert

        row = store._conn().execute("SELECT * FROM jobs WHERE id = 'gh-1'").fetchone()
        assert row["title"] == "Engineer v2"
        assert row["first_seen_run"] == "run-1"
        assert row["last_seen_run"] == "run-2"

    def test_company_resolution_during_upsert(self):
        store = _make_store()
        run_id = _seed_run(store)
        job = _make_job(id="gh-1", source="greenhouse", company="Anthropic", board_token="anthropic")
        store.upsert_jobs([job], run_id)

        row = store._conn().execute("SELECT company_id FROM jobs WHERE id = 'gh-1'").fetchone()
        assert row["company_id"] is not None

    def test_compensation_stored(self):
        store = _make_store()
        run_id = _seed_run(store)
        comp = Compensation(min_amount=150000, max_amount=200000, currency="USD", interval="yearly")
        job = _make_job(id="gh-1", compensation=comp)
        store.upsert_jobs([job], run_id)

        row = store._conn().execute("SELECT min_amount, max_amount, currency FROM jobs WHERE id = 'gh-1'").fetchone()
        assert row["min_amount"] == 150000
        assert row["max_amount"] == 200000
        assert row["currency"] == "USD"

    def test_location_stored(self):
        store = _make_store()
        run_id = _seed_run(store)
        loc = Location(city="SF", state="CA", country="USA", raw="SF, CA", work_arrangement=WorkArrangement.REMOTE)
        job = _make_job(id="gh-1", location=loc)
        store.upsert_jobs([job], run_id)

        row = store._conn().execute("SELECT city, state, country, work_arrangement FROM jobs WHERE id = 'gh-1'").fetchone()
        assert row["city"] == "SF"
        assert row["state"] == "CA"
        assert row["work_arrangement"] == "remote"


# ---------------------------------------------------------------------------
# Staleness tracking
# ---------------------------------------------------------------------------

class TestStaleness:
    def test_miss_count_increment(self):
        store = _make_store()
        run1 = _seed_run(store, "run-1")
        store.upsert_jobs([_make_job(id="gh-1")], run1)

        store.start_run("run-2", "greenhouse", None)
        # Don't upsert gh-1 in run-2 -> it's a miss
        store.mark_stale_jobs("run-2", "greenhouse")

        row = store._conn().execute("SELECT miss_count, is_active FROM jobs WHERE id = 'gh-1'").fetchone()
        assert row["miss_count"] == 1
        assert row["is_active"] == 1  # not yet deactivated

    def test_deactivation_after_2_misses(self):
        store = _make_store()
        run1 = _seed_run(store, "run-1")
        store.upsert_jobs([_make_job(id="gh-1")], run1)

        # Miss 1
        store.start_run("run-2", "greenhouse", None)
        store.mark_stale_jobs("run-2", "greenhouse")

        # Miss 2
        store.start_run("run-3", "greenhouse", None)
        deactivated = store.mark_stale_jobs("run-3", "greenhouse")
        assert deactivated == 1

        row = store._conn().execute("SELECT miss_count, is_active FROM jobs WHERE id = 'gh-1'").fetchone()
        assert row["miss_count"] == 2
        assert row["is_active"] == 0

    def test_reseen_resets_miss_count(self):
        store = _make_store()
        run1 = _seed_run(store, "run-1")
        store.upsert_jobs([_make_job(id="gh-1")], run1)

        # Miss 1
        store.start_run("run-2", "greenhouse", None)
        store.mark_stale_jobs("run-2", "greenhouse")

        # Re-seen in run-3
        store.start_run("run-3", "greenhouse", None)
        store.upsert_jobs([_make_job(id="gh-1")], "run-3")

        row = store._conn().execute("SELECT miss_count, is_active FROM jobs WHERE id = 'gh-1'").fetchone()
        assert row["miss_count"] == 0
        assert row["is_active"] == 1


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------

class TestTokenManagement:
    def test_import_tokens(self):
        store = _make_store()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("anthropic\nscaleai\n# comment\n\nramp\n")
            f.flush()
            count = store.import_tokens("greenhouse", f.name)

        assert count == 3
        tokens = store.get_tokens("greenhouse")
        assert set(tokens) == {"anthropic", "scaleai", "ramp"}

    def test_import_idempotent(self):
        store = _make_store()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("anthropic\nscaleai\n")
            f.flush()
            count1 = store.import_tokens("greenhouse", f.name)
            count2 = store.import_tokens("greenhouse", f.name)

        assert count1 == 2
        assert count2 == 0

    def test_mark_stale_excludes_from_get_tokens(self):
        store = _make_store()
        store.add_token("greenhouse", "alive")
        store.add_token("greenhouse", "dead")
        store.mark_tokens_stale("greenhouse", ["dead"])

        tokens = store.get_tokens("greenhouse")
        assert "alive" in tokens
        assert "dead" not in tokens

    def test_mark_valid(self):
        store = _make_store()
        store.add_token("greenhouse", "tok1")
        assert store.get_tokens_by_status("greenhouse", "unchecked") == ["tok1"]

        store.mark_tokens_valid("greenhouse", ["tok1"])
        assert store.get_tokens_by_status("greenhouse", "valid") == ["tok1"]
        assert store.get_tokens_by_status("greenhouse", "unchecked") == []

    def test_add_token_new(self):
        store = _make_store()
        assert store.add_token("greenhouse", "anthropic") is True
        assert store.add_token("greenhouse", "anthropic") is False  # already exists

    def test_add_token_with_name(self):
        store = _make_store()
        store.add_token("lever", "ramp", company_name="Ramp Technologies")
        row = store._conn().execute(
            "SELECT name FROM companies WHERE ats_token = 'ramp'"
        ).fetchone()
        assert row["name"] == "Ramp Technologies"

    def test_get_token_counts(self):
        store = _make_store()
        store.add_token("greenhouse", "a")
        store.add_token("greenhouse", "b")
        store.add_token("lever", "c")
        store.mark_tokens_valid("greenhouse", ["a"])
        store.mark_tokens_stale("greenhouse", ["b"])

        counts = store.get_token_counts()
        assert counts["greenhouse"]["valid"] == 1
        assert counts["greenhouse"]["stale"] == 1
        assert counts["lever"]["unchecked"] == 1

    def test_get_all_tokens(self):
        store = _make_store()
        store.add_token("greenhouse", "a")
        store.add_token("greenhouse", "b")
        store.mark_tokens_stale("greenhouse", ["b"])

        all_tokens = store.get_all_tokens("greenhouse")
        assert set(all_tokens) == {"a", "b"}

    def test_import_backfills_existing_company(self):
        """If a company exists by name but without ATS info, import should backfill."""
        store = _make_store()
        conn = store._conn()
        conn.execute(
            "INSERT INTO companies (name, name_normalized) VALUES ('Anthropic', 'anthropic')"
        )
        conn.commit()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("anthropic\n")
            f.flush()
            count = store.import_tokens("greenhouse", f.name)

        assert count == 1
        row = conn.execute("SELECT ats_platform, ats_token FROM companies WHERE name_normalized = 'anthropic'").fetchone()
        assert row["ats_platform"] == "greenhouse"
        assert row["ats_token"] == "anthropic"


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class TestSearch:
    def _seed_jobs(self, store: Store) -> str:
        run_id = _seed_run(store)
        jobs = [
            _make_job(
                id="gh-1", title="Senior ML Engineer", company="Anthropic",
                board_token="anthropic", date_posted=date(2026, 4, 1),
                compensation=Compensation(min_amount=200000, max_amount=300000),
                location=Location(work_arrangement=WorkArrangement.REMOTE),
            ),
            _make_job(
                id="gh-2", title="Junior Frontend Dev", company="Scale AI",
                board_token="scaleai", date_posted=date(2026, 3, 15),
                location=Location(work_arrangement=WorkArrangement.ONSITE, city="SF", state="CA"),
            ),
            _make_job(
                id="rok-1", source="remoteok", title="Backend Engineer",
                company="SomeStartup", board_token=None, date_posted=date(2026, 4, 5),
                location=Location(work_arrangement=WorkArrangement.REMOTE),
            ),
        ]
        store.upsert_jobs(jobs, run_id)

        # Enrich one job with seniority
        store.update_job_enrichment("gh-1", seniority="senior", domain="ml_ai")
        store.update_job_enrichment("gh-2", seniority="junior", domain="frontend")

        return run_id

    def test_basic_search_returns_all_active(self):
        store = _make_store()
        self._seed_jobs(store)
        results = store.search(SearchQuery())
        assert len(results) == 3

    def test_text_search(self):
        store = _make_store()
        self._seed_jobs(store)
        results = store.search(SearchQuery(text="ML"))
        assert len(results) == 1
        assert results[0]["id"] == "gh-1"

    def test_filter_by_site(self):
        store = _make_store()
        self._seed_jobs(store)
        results = store.search(SearchQuery(sites=["remoteok"]))
        assert len(results) == 1
        assert results[0]["id"] == "rok-1"

    def test_filter_by_seniority(self):
        store = _make_store()
        self._seed_jobs(store)
        results = store.search(SearchQuery(seniority=["senior"]))
        assert len(results) == 1
        assert results[0]["id"] == "gh-1"

    def test_filter_by_domain(self):
        store = _make_store()
        self._seed_jobs(store)
        results = store.search(SearchQuery(domains=["ml_ai"]))
        assert len(results) == 1
        assert results[0]["id"] == "gh-1"

    def test_filter_by_work_arrangement(self):
        store = _make_store()
        self._seed_jobs(store)
        results = store.search(SearchQuery(work_arrangement=["remote"]))
        assert len(results) == 2
        ids = {r["id"] for r in results}
        assert ids == {"gh-1", "rok-1"}

    def test_filter_by_salary(self):
        store = _make_store()
        self._seed_jobs(store)
        results = store.search(SearchQuery(min_salary=150000))
        assert len(results) == 1
        assert results[0]["id"] == "gh-1"

    def test_filter_by_company(self):
        store = _make_store()
        self._seed_jobs(store)
        results = store.search(SearchQuery(companies=["Anthropic"]))
        # Company name stored is "Anthropic" after resolution
        assert len(results) >= 1
        assert any(r["id"] == "gh-1" for r in results)

    def test_include_inactive(self):
        store = _make_store()
        run_id = self._seed_jobs(store)

        # Deactivate one job
        store._conn().execute("UPDATE jobs SET is_active = 0 WHERE id = 'gh-2'")
        store._conn().commit()

        # Default: only active
        results = store.search(SearchQuery())
        assert len(results) == 2

        # include_inactive
        results = store.search(SearchQuery(include_inactive=True))
        assert len(results) == 3

    def test_limit_and_offset(self):
        store = _make_store()
        self._seed_jobs(store)
        results = store.search(SearchQuery(limit=1))
        assert len(results) == 1

        results = store.search(SearchQuery(limit=1, offset=1))
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Annotations & Tags
# ---------------------------------------------------------------------------

class TestAnnotations:
    def _seed(self, store: Store):
        run_id = _seed_run(store)
        store.upsert_jobs([_make_job(id="gh-1")], run_id)
        return run_id

    def test_annotate_creates_and_updates(self):
        store = _make_store()
        self._seed(store)

        store.annotate("gh-1", rating=4, note="Great role")
        row = store._conn().execute("SELECT * FROM job_annotations WHERE job_id = 'gh-1'").fetchone()
        assert row["rating"] == 4
        assert row["note"] == "Great role"

        store.annotate("gh-1", rating=5)
        row = store._conn().execute("SELECT * FROM job_annotations WHERE job_id = 'gh-1'").fetchone()
        assert row["rating"] == 5
        assert row["note"] == "Great role"  # unchanged

    def test_add_and_remove_tag(self):
        store = _make_store()
        self._seed(store)

        store.add_tag("gh-1", "dream job")
        store.add_tag("gh-1", "ai")
        tags = store._conn().execute("SELECT tag FROM job_tags WHERE job_id = 'gh-1'").fetchall()
        assert {t["tag"] for t in tags} == {"dream job", "ai"}

        store.remove_tag("gh-1", "ai")
        tags = store._conn().execute("SELECT tag FROM job_tags WHERE job_id = 'gh-1'").fetchall()
        assert {t["tag"] for t in tags} == {"dream job"}

    def test_add_tag_idempotent(self):
        store = _make_store()
        self._seed(store)
        store.add_tag("gh-1", "ai")
        store.add_tag("gh-1", "ai")  # should not error

    def test_set_interest(self):
        store = _make_store()
        self._seed(store)
        store.set_interest("gh-1", "applied", note="Applied on 2026-04-01")

        row = store._conn().execute("SELECT * FROM job_annotations WHERE job_id = 'gh-1'").fetchone()
        assert row["interest"] == "applied"
        assert row["note"] == "Applied on 2026-04-01"

    def test_search_by_tag(self):
        store = _make_store()
        run_id = _seed_run(store)
        store.upsert_jobs([
            _make_job(id="gh-1", date_posted=date(2026, 4, 1)),
            _make_job(id="gh-2", company="Scale AI", board_token="scaleai", date_posted=date(2026, 4, 1)),
        ], run_id)
        store.add_tag("gh-1", "dream")

        results = store.search(SearchQuery(tags=["dream"]))
        assert len(results) == 1
        assert results[0]["id"] == "gh-1"

    def test_search_by_rating(self):
        store = _make_store()
        run_id = _seed_run(store)
        store.upsert_jobs([
            _make_job(id="gh-1", date_posted=date(2026, 4, 1)),
            _make_job(id="gh-2", company="Scale AI", board_token="scaleai", date_posted=date(2026, 4, 1)),
        ], run_id)
        store.annotate("gh-1", rating=5)

        results = store.search(SearchQuery(rating=5))
        assert len(results) == 1
        assert results[0]["id"] == "gh-1"


# ---------------------------------------------------------------------------
# get_job
# ---------------------------------------------------------------------------

class TestGetJob:
    def test_get_job_with_annotations(self):
        store = _make_store()
        run_id = _seed_run(store)
        store.upsert_jobs([_make_job(id="gh-1")], run_id)
        store.annotate("gh-1", rating=4)
        store.add_tag("gh-1", "dream")

        result = store.get_job("gh-1")
        assert result is not None
        assert result["annotation_rating"] == 4
        assert "dream" in result["tags"]

    def test_get_job_not_found(self):
        store = _make_store()
        assert store.get_job("nonexistent") is None


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class TestStats:
    def test_get_stats(self):
        store = _make_store()
        run_id = _seed_run(store)
        store.upsert_jobs([
            _make_job(id="gh-1"),
            _make_job(id="rok-1", source="remoteok", company="X", board_token=None),
        ], run_id)
        store.finish_run(run_id, 2)

        stats = store.get_stats()
        assert stats["jobs_total"] == 2
        assert stats["jobs_active"] == 2
        assert stats["companies"] >= 1
        assert "greenhouse" in stats["by_site"]
        assert stats["latest_run"]["run_id"] == run_id


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

class TestEnrichment:
    def test_get_unenriched_jobs(self):
        store = _make_store()
        run_id = _seed_run(store)
        store.upsert_jobs([
            _make_job(id="gh-1"),
            _make_job(id="gh-2", company="Scale AI", board_token="scaleai"),
        ], run_id)

        unenriched = store.get_unenriched_jobs()
        assert len(unenriched) == 2

        store.update_job_enrichment("gh-1", seniority="senior", domain="ml_ai")
        unenriched = store.get_unenriched_jobs()
        assert len(unenriched) == 1
        assert unenriched[0]["id"] == "gh-2"

    def test_get_unenriched_companies(self):
        store = _make_store()
        run_id = _seed_run(store)
        store.upsert_jobs([_make_job(id="gh-1")], run_id)

        unenriched = store.get_unenriched_companies()
        assert len(unenriched) >= 1

    def test_update_company_enrichment(self):
        store = _make_store()
        conn = store._conn()
        conn.execute(
            "INSERT INTO companies (name, name_normalized) VALUES ('Anthropic', 'anthropic')"
        )
        conn.commit()
        cid = conn.execute("SELECT id FROM companies WHERE name_normalized = 'anthropic'").fetchone()["id"]

        store.update_company_enrichment(cid, industry="AI/ML", ai_native=0.95)
        row = conn.execute("SELECT industry, ai_native, enriched_at FROM companies WHERE id = ?", (cid,)).fetchone()
        assert row["industry"] == "AI/ML"
        assert row["ai_native"] == 0.95
        assert row["enriched_at"] is not None

    def test_record_enrichment_run(self):
        store = _make_store()
        store.record_enrichment_run(
            run_id="enrich-1", started_at="2026-04-01T00:00:00Z",
            stage="jobs", items=50, input_tokens=1000, output_tokens=500, cost_usd=0.05,
        )
        row = store._conn().execute("SELECT * FROM enrichment_runs WHERE run_id = 'enrich-1'").fetchone()
        assert row["items"] == 50
        assert row["cost_usd"] == 0.05


# ---------------------------------------------------------------------------
# HN Career Pages
# ---------------------------------------------------------------------------

class TestHNCareerPages:
    def _seed_hn_job(self, store: Store) -> str:
        run_id = _seed_run(store)
        job = _make_job(
            id="hn-1", source="hn", company="CoolStartup",
            board_token=None, url="https://coolstartup.com",
        )
        store.upsert_jobs([job], run_id)
        return run_id

    def test_get_unprocessed_hn_urls(self):
        store = _make_store()
        self._seed_hn_job(store)
        urls = store.get_unprocessed_hn_urls()
        assert len(urls) == 1
        assert urls[0]["id"] == "hn-1"
        assert urls[0]["job_url"] == "https://coolstartup.com"

    def test_upsert_hn_career_page(self):
        store = _make_store()
        self._seed_hn_job(store)

        store.upsert_hn_career_page("hn-1", company_name="CoolStartup", status="pending")
        rows = store.get_hn_pages_by_status("pending")
        assert len(rows) == 1

        # Update
        store.upsert_hn_career_page("hn-1", status="scraped", ats_platform="greenhouse", ats_token="coolstartup")
        rows = store.get_hn_pages_by_status("scraped")
        assert len(rows) == 1
        assert rows[0]["ats_token"] == "coolstartup"

    def test_update_hn_career_page(self):
        store = _make_store()
        self._seed_hn_job(store)

        store.upsert_hn_career_page("hn-1", status="pending")
        store.update_hn_career_page("hn-1", careers_url="https://coolstartup.com/careers", status="discovered")

        rows = store.get_hn_pages_by_status("discovered")
        assert len(rows) == 1
        assert rows[0]["careers_url"] == "https://coolstartup.com/careers"

    def test_unprocessed_excludes_processed(self):
        store = _make_store()
        self._seed_hn_job(store)

        store.upsert_hn_career_page("hn-1", status="pending")
        urls = store.get_unprocessed_hn_urls()
        assert len(urls) == 0  # already in hn_career_pages

    def test_discovery_summary(self):
        store = _make_store()
        self._seed_hn_job(store)
        store.upsert_hn_career_page("hn-1", status="scraped", ats_platform="greenhouse")

        summary = store.get_hn_discovery_summary()
        assert summary["total"] == 1
        assert summary["by_status"]["scraped"] == 1
        assert summary["by_platform"]["greenhouse"] == 1


# ---------------------------------------------------------------------------
# Description helpers
# ---------------------------------------------------------------------------

class TestDescriptionHelpers:
    def test_update_description(self):
        store = _make_store()
        run_id = _seed_run(store)
        store.upsert_jobs([_make_job(id="gh-1", description="<b>old</b>")], run_id)

        store.update_description("gh-1", "**new**")
        row = store._conn().execute("SELECT description FROM jobs WHERE id = 'gh-1'").fetchone()
        assert row["description"] == "**new**"
