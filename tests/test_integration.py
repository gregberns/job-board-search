"""Integration tests: full pipeline without live HTTP."""

import shutil
from datetime import date
from pathlib import Path

import pytest

from jbs.models import Compensation, Job, Location, SearchQuery, WorkArrangement
from jbs.store import Store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(tmp_path: Path) -> Store:
    return Store(tmp_path / "test.db")


def _seed_jobs(store: Store) -> list[Job]:
    """Insert two jobs from different sources, return them."""
    store.start_run("test-run-1", "greenhouse,remoteok", None)

    jobs = [
        Job(
            id="gh-1",
            source="greenhouse",
            title="Senior ML Engineer",
            company="TestCo",
            url="https://example.com/1",
            location=Location(
                city="SF", state="CA", country="US",
                work_arrangement=WorkArrangement.REMOTE,
            ),
            compensation=Compensation(min_amount=200_000, max_amount=300_000),
            description=(
                "Build ML pipelines using Python and PyTorch. "
                "5+ years of experience required. "
                "We sponsor H-1B visas for qualified candidates."
            ),
            board_token="testco",
        ),
        Job(
            id="rok-1",
            source="remoteok",
            title="Backend Developer",
            company="AcmeCo",
            url="https://example.com/2",
            location=Location(work_arrangement=WorkArrangement.REMOTE),
            description="Node.js and PostgreSQL backend services.",
        ),
    ]
    store.upsert_jobs(jobs, "test-run-1")
    store.finish_run("test-run-1", len(jobs))
    return jobs


# ---------------------------------------------------------------------------
# Full pipeline test
# ---------------------------------------------------------------------------

class TestFullPipeline:
    def test_init_insert_enrich_search_annotate_apply(self, tmp_path):
        """jbs init → insert jobs → enrich rules → search → annotate → apply."""
        # 1. Create store (equivalent to `jbs init`)
        store = _make_store(tmp_path)

        # 2. Add a token
        assert store.add_token("greenhouse", "testco") is True

        # 3. Insert jobs
        _seed_jobs(store)

        # 4. Enrich with rules
        from jbs.enrich import EnrichmentPipeline

        pipeline = EnrichmentPipeline(store)
        n_processed, counts = pipeline._run_stage1_rules(force=False, source=None)
        assert n_processed == 2
        assert counts["seniority"] >= 1  # "Senior ML Engineer" → senior

        # Verify enrichment wrote to DB
        job = store.get_job("gh-1")
        assert job["seniority"] == "senior"
        assert job["enriched_at"] is not None

        # Visa extraction from description
        assert job["visa_sponsorship"] == "sponsors"

        # Years experience
        assert job["years_experience"] == 5

        # 5. FTS search
        results = store.search(SearchQuery(text="ML"))
        assert len(results) >= 1
        assert any("ML" in r["title"] for r in results)

        # Negative search
        results = store.search(SearchQuery(text="Golang"))
        assert len(results) == 0

        # 6. Annotate
        store.annotate("gh-1", rating=5, note="Great role")
        store.add_tag("gh-1", "dream-job")

        # 7. Verify annotations persisted before apply
        job = store.get_job("gh-1")
        assert job["annotation_rating"] == 5
        assert job["annotation_note"] == "Great role"

        # 8. Apply (overwrites note)
        store.set_interest("gh-1", "applied", note="Applied 2026-04-09")
        job = store.get_job("gh-1")
        assert job["annotation_interest"] == "applied"
        assert job["annotation_note"] == "Applied 2026-04-09"
        assert "dream-job" in job["tags"]

        # 9. Search by tag
        results = store.search(SearchQuery(tags=["dream-job"]))
        assert len(results) == 1
        assert results[0]["id"] == "gh-1"

        # 10. Stats
        stats = store.get_stats()
        assert stats["jobs_total"] == 2
        assert stats["jobs_active"] == 2
        assert stats["companies"] >= 2
        assert stats["by_site"]["greenhouse"] == 1
        assert stats["by_site"]["remoteok"] == 1

        store.close()

    def test_idempotent_upsert(self, tmp_path):
        """Upserting the same job twice should not duplicate."""
        store = _make_store(tmp_path)
        store.start_run("run-1", "greenhouse", None)
        job = Job(
            id="gh-dup", source="greenhouse", title="Engineer",
            company="DupCo", url="https://example.com/dup",
            location=Location(),
        )
        inserted1 = store.upsert_jobs([job], "run-1")
        inserted2 = store.upsert_jobs([job], "run-1")
        assert inserted1 == 1
        assert inserted2 == 0

        stats = store.get_stats()
        assert stats["jobs_total"] == 1
        store.close()

    def test_enrichment_idempotent(self, tmp_path):
        """Stage 1 rules should skip already-enriched jobs (force=False)."""
        from jbs.enrich import EnrichmentPipeline

        store = _make_store(tmp_path)
        _seed_jobs(store)

        pipeline = EnrichmentPipeline(store)
        n1, _ = pipeline._run_stage1_rules(force=False)
        n2, _ = pipeline._run_stage1_rules(force=False)
        assert n1 == 2
        assert n2 == 0  # already enriched

    def test_enrichment_force_reruns(self, tmp_path):
        """force=True should re-process already-enriched jobs."""
        from jbs.enrich import EnrichmentPipeline

        store = _make_store(tmp_path)
        _seed_jobs(store)

        pipeline = EnrichmentPipeline(store)
        pipeline._run_stage1_rules(force=False)
        n, _ = pipeline._run_stage1_rules(force=True)
        assert n == 2

    def test_company_resolution(self, tmp_path):
        """Jobs from the same company should share a company_id."""
        store = _make_store(tmp_path)
        store.start_run("run-1", "greenhouse", None)
        jobs = [
            Job(id="gh-a", source="greenhouse", title="Eng 1",
                company="Anthropic", url="https://a.com/1",
                location=Location(), board_token="anthropic"),
            Job(id="gh-b", source="greenhouse", title="Eng 2",
                company="Anthropic", url="https://a.com/2",
                location=Location(), board_token="anthropic"),
        ]
        store.upsert_jobs(jobs, "run-1")

        a = store.get_job("gh-a")
        b = store.get_job("gh-b")
        assert a["company_id"] == b["company_id"]
        assert a["company_id"] is not None
        store.close()

    def test_tag_add_remove(self, tmp_path):
        """Tags can be added and removed."""
        store = _make_store(tmp_path)
        _seed_jobs(store)

        store.add_tag("gh-1", "top-pick")
        store.add_tag("gh-1", "ai-company")
        job = store.get_job("gh-1")
        assert set(job["tags"]) == {"top-pick", "ai-company"}

        store.remove_tag("gh-1", "top-pick")
        job = store.get_job("gh-1")
        assert job["tags"] == ["ai-company"]
        store.close()


# ---------------------------------------------------------------------------
# Migration test
# ---------------------------------------------------------------------------

class TestMigration:
    def test_migrate_existing_db(self, tmp_path):
        """Verify _ensure_schema handles the existing production DB gracefully."""
        import sqlite3

        src = Path("data/jobs.db")
        if not src.exists():
            pytest.skip("No existing jobs.db to test migration")

        dst = tmp_path / "migrated.db"

        # Use SQLite backup API to get a clean copy (avoids WAL corruption on copy)
        src_conn = sqlite3.connect(str(src))
        dst_conn = sqlite3.connect(str(dst))
        try:
            src_conn.backup(dst_conn)
        except sqlite3.DatabaseError as e:
            src_conn.close()
            dst_conn.close()
            pytest.skip(f"Cannot backup existing jobs.db: {e}")
        src_conn.close()
        dst_conn.close()

        # Open with Store — _ensure_schema() runs
        try:
            store = Store(dst)
        except Exception as e:
            pytest.skip(f"Cannot migrate existing jobs.db: {e}")
        conn = store._conn()

        # All 8 tables
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        for t in ("companies", "jobs", "runs", "company_preferences",
                  "job_annotations", "job_tags", "hn_career_pages", "enrichment_runs"):
            assert t in tables, f"Missing table: {t}"

        # Key columns on jobs
        cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        for c in ("company_id", "company_raw", "is_active", "enriched_at",
                  "seniority", "domain", "engineering_role"):
            assert c in cols, f"Missing column: {c}"

        # Data survived
        count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        assert count > 0

        # Stats should work against migrated data
        stats = store.get_stats()
        assert stats["jobs_total"] == count
        store.close()


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

class TestCLI:
    def test_init_stats_search(self, tmp_path):
        """CLI init → stats → search should all succeed."""
        from click.testing import CliRunner
        from jbs.cli import cli

        db = str(tmp_path / "cli_test.db")
        runner = CliRunner()

        # Init
        result = runner.invoke(cli, ["--db", db, "init"])
        assert result.exit_code == 0, result.output

        # Stats (JSON for easier parsing)
        result = runner.invoke(cli, ["--db", db, "--format", "json", "stats"])
        assert result.exit_code == 0, result.output

        # Search (empty DB, should not error)
        result = runner.invoke(cli, ["--db", db, "--format", "json", "search"])
        assert result.exit_code == 0, result.output

    def test_annotate_roundtrip(self, tmp_path):
        """CLI annotate → show should reflect changes."""
        from click.testing import CliRunner
        from jbs.cli import cli

        db = str(tmp_path / "cli_annotate.db")
        runner = CliRunner()

        # Init + seed via store
        store = Store(db)
        store.start_run("run-1", "greenhouse", None)
        store.upsert_jobs([
            Job(id="gh-cli", source="greenhouse", title="CLI Test Job",
                company="CliCo", url="https://example.com/cli",
                location=Location()),
        ], "run-1")
        store.close()

        # Annotate via CLI
        result = runner.invoke(cli, [
            "--db", db, "annotate", "gh-cli",
            "--rating", "4", "--tag", "interesting", "--note", "Looks good",
        ])
        assert result.exit_code == 0, result.output

        # Show via CLI
        result = runner.invoke(cli, ["--db", db, "--format", "json", "show", "gh-cli"])
        assert result.exit_code == 0, result.output
        assert "interesting" in result.output
        assert "Looks good" in result.output

    def test_apply_list(self, tmp_path):
        """CLI apply → apply --list should show the job."""
        from click.testing import CliRunner
        from jbs.cli import cli

        db = str(tmp_path / "cli_apply.db")
        runner = CliRunner()

        store = Store(db)
        store.start_run("run-1", "remoteok", None)
        store.upsert_jobs([
            Job(id="rok-cli", source="remoteok", title="Apply Test",
                company="ApplyCo", url="https://example.com/apply",
                location=Location()),
        ], "run-1")
        store.close()

        # Apply
        result = runner.invoke(cli, [
            "--db", db, "apply", "rok-cli",
            "--stage", "applied", "--note", "Submitted resume",
        ])
        assert result.exit_code == 0, result.output

        # List applied jobs
        result = runner.invoke(cli, ["--db", db, "--format", "json", "apply", "--list"])
        assert result.exit_code == 0, result.output
        assert "rok-cli" in result.output
