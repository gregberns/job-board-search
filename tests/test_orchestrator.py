"""Tests for jbs.orchestrator.ScraperOrchestrator."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from jbs.config import Config
from jbs.models import Job, Location, ScrapeResult
from jbs.orchestrator import ScraperOrchestrator
from jbs.scrapers.base import PluginMeta, ScraperPlugin, ScrapeContext
from jbs.store import Store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store() -> Store:
    return Store(":memory:")


def _make_job(id: str = "gh-1", source: str = "greenhouse", **kwargs) -> Job:
    defaults = dict(
        title="Engineer",
        company="TestCo",
        url="https://example.com/job/1",
        location=Location(),
    )
    defaults.update(kwargs)
    return Job(id=id, source=source, **defaults)


class FakeScraper(ScraperPlugin):
    """Non-ATS scraper returning fixed results."""
    meta = PluginMeta(name="fake", id_prefix="fk", requires_tokens=False)

    def __init__(self, jobs=None, failed_tokens=None, errors=None):
        self._jobs = jobs or []
        self._failed_tokens = failed_tokens or []
        self._errors = errors or []

    def scrape(self, ctx: ScrapeContext) -> ScrapeResult:
        return ScrapeResult(
            source=self.meta.name,
            jobs=self._jobs,
            failed_tokens=self._failed_tokens,
            errors=self._errors,
            elapsed_seconds=0.5,
        )


class FakeATSScraper(ScraperPlugin):
    """ATS scraper that requires tokens."""
    meta = PluginMeta(name="fake_ats", id_prefix="fa", requires_tokens=True)

    def __init__(self, jobs=None, failed_tokens=None):
        self._jobs = jobs or []
        self._failed_tokens = failed_tokens or []

    def scrape(self, ctx: ScrapeContext) -> ScrapeResult:
        return ScrapeResult(
            source=self.meta.name,
            jobs=self._jobs,
            failed_tokens=self._failed_tokens,
            elapsed_seconds=1.0,
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRunTracking:
    def test_start_and_finish_run(self):
        store = _make_store()
        config = Config(db_path=":memory:")
        orch = ScraperOrchestrator(config, store)
        fake = FakeScraper(jobs=[_make_job(source="remoteok")])

        with patch("jbs.orchestrator.get_scraper", return_value=fake):
            result = orch.run(["fake"])

        run_id = result["run_id"]
        conn = store._conn()
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        assert row is not None
        assert row["status"] == "completed"
        assert row["total_jobs"] == 1

    def test_run_returns_run_id_and_total(self):
        store = _make_store()
        config = Config(db_path=":memory:")
        orch = ScraperOrchestrator(config, store)
        jobs = [_make_job(id="rok-1", source="remoteok"), _make_job(id="rok-2", source="remoteok")]
        fake = FakeScraper(jobs=jobs)

        with patch("jbs.orchestrator.get_scraper", return_value=fake):
            result = orch.run(["fake"])

        assert "run_id" in result
        assert result["total"] == 2


class TestUpsertJobs:
    def test_upsert_called_with_correct_run_id(self):
        store = _make_store()
        store.upsert_jobs = MagicMock(return_value=3)
        config = Config(db_path=":memory:")
        orch = ScraperOrchestrator(config, store)
        jobs = [_make_job()]
        fake = FakeScraper(jobs=jobs)

        with patch("jbs.orchestrator.get_scraper", return_value=fake):
            result = orch.run(["fake"])

        store.upsert_jobs.assert_called_once()
        call_args = store.upsert_jobs.call_args
        assert call_args[0][0] == jobs  # first arg: jobs list
        assert call_args[0][1] == result["run_id"]  # second arg: run_id


class TestFailedTokens:
    def test_failed_tokens_marked_stale(self):
        store = _make_store()
        # Seed a company with a token
        conn = store._conn()
        conn.execute(
            "INSERT INTO companies (name, name_normalized, ats_platform, ats_token, token_status) "
            "VALUES (?, ?, ?, ?, ?)",
            ("TestCo", "testco", "greenhouse", "bad-token", "valid"),
        )
        conn.commit()

        config = Config(db_path=":memory:")
        orch = ScraperOrchestrator(config, store)
        # Simulate a greenhouse scraper that returns no jobs but one failed token
        fake = FakeATSScraper(failed_tokens=["bad-token"])
        fake.meta = PluginMeta(name="greenhouse", id_prefix="gh", requires_tokens=True)

        with patch("jbs.orchestrator.get_scraper", return_value=fake):
            orch.run(["greenhouse"])

        # Verify token was marked stale
        row = conn.execute(
            "SELECT token_status FROM companies WHERE ats_token = 'bad-token'"
        ).fetchone()
        assert row["token_status"] == "stale"


class TestTokenSkipping:
    def test_ats_source_skipped_when_no_tokens(self):
        store = _make_store()
        config = Config(db_path=":memory:")
        orch = ScraperOrchestrator(config, store)
        fake = FakeATSScraper()

        with patch("jbs.orchestrator.get_scraper", return_value=fake):
            result = orch.run(["fake_ats"])

        # No jobs should have been inserted
        assert result["total"] == 0
        # Scraper should not have been called (we'd get an error if it was
        # called without tokens, but let's verify via DB)
        conn = store._conn()
        count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        assert count == 0

    def test_non_ats_source_runs_without_tokens(self):
        store = _make_store()
        config = Config(db_path=":memory:")
        orch = ScraperOrchestrator(config, store)
        fake = FakeScraper(jobs=[_make_job(id="rok-1", source="remoteok")])

        with patch("jbs.orchestrator.get_scraper", return_value=fake):
            result = orch.run(["fake"])

        assert result["total"] == 1


class TestDryRun:
    def test_dry_run_does_not_write_to_db(self):
        store = _make_store()
        config = Config(db_path=":memory:")
        orch = ScraperOrchestrator(config, store)
        fake = FakeScraper(jobs=[_make_job()])

        with patch("jbs.orchestrator.get_scraper", return_value=fake):
            result = orch.run(["fake"], dry_run=True)

        assert result["total"] == 0
        conn = store._conn()
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0

    def test_dry_run_returns_run_id(self):
        store = _make_store()
        config = Config(db_path=":memory:")
        orch = ScraperOrchestrator(config, store)
        fake = FakeScraper()

        with patch("jbs.orchestrator.get_scraper", return_value=fake):
            result = orch.run(["fake"], dry_run=True)

        assert "run_id" in result


class TestStaleJobs:
    def test_mark_stale_jobs_called(self):
        store = _make_store()
        store.mark_stale_jobs = MagicMock(return_value=0)
        config = Config(db_path=":memory:")
        orch = ScraperOrchestrator(config, store)
        fake = FakeScraper(jobs=[_make_job()])

        with patch("jbs.orchestrator.get_scraper", return_value=fake):
            result = orch.run(["fake"])

        store.mark_stale_jobs.assert_called_once_with(result["run_id"], "fake")


class TestBuildContext:
    def test_context_uses_config_hours_old(self):
        store = _make_store()
        config = Config(db_path=":memory:", hours_old=72)
        orch = ScraperOrchestrator(config, store)

        ctx = orch._build_context("remoteok", None, None)
        assert ctx.hours_old == 72
        assert ctx.tokens is None

    def test_context_overrides_hours_old(self):
        store = _make_store()
        config = Config(db_path=":memory:", hours_old=72)
        orch = ScraperOrchestrator(config, store)

        ctx = orch._build_context("remoteok", "python", 24)
        assert ctx.hours_old == 24
        assert ctx.search_term == "python"

    def test_context_loads_tokens_for_ats_source(self):
        store = _make_store()
        # Seed tokens
        conn = store._conn()
        conn.execute(
            "INSERT INTO companies (name, name_normalized, ats_platform, ats_token, token_status) "
            "VALUES (?, ?, ?, ?, ?)",
            ("Acme", "acme", "greenhouse", "acme-co", "valid"),
        )
        conn.execute(
            "INSERT INTO companies (name, name_normalized, ats_platform, ats_token, token_status) "
            "VALUES (?, ?, ?, ?, ?)",
            ("StaleInc", "staleinc", "greenhouse", "stale-co", "stale"),
        )
        conn.commit()

        config = Config(db_path=":memory:")
        orch = ScraperOrchestrator(config, store)

        ctx = orch._build_context("greenhouse", None, None)
        assert ctx.tokens == ["acme-co"]  # stale token excluded


class TestMultipleSources:
    def test_sequential_sources(self):
        store = _make_store()
        config = Config(db_path=":memory:")
        orch = ScraperOrchestrator(config, store)

        call_order = []

        def mock_get_scraper(name):
            call_order.append(name)
            # Use valid site values for DB constraint
            jobs = [_make_job(id=f"rok-{name}", source="remoteok")]
            return FakeScraper(jobs=jobs)

        with patch("jbs.orchestrator.get_scraper", side_effect=mock_get_scraper):
            result = orch.run(["remoteok", "hn"])

        assert call_order == ["remoteok", "hn"]
        assert result["total"] == 2
