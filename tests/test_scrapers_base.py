"""Tests for scraper plugin system: registry, base classes, ATS base."""

import time

import pytest

from jbs.models import Job, Location, ScrapeResult
from jbs.scrapers import _REGISTRY, available_scrapers, get_scraper, register
from jbs.scrapers.ats_base import ATSBoardScraper, BoardNotFoundError
from jbs.scrapers.base import PluginMeta, ScraperPlugin, ScrapeContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_job(id: str, source: str = "test", title: str = "Engineer") -> Job:
    return Job(
        id=id,
        source=source,
        title=title,
        company="TestCo",
        url=f"https://example.com/{id}",
        location=Location(),
    )


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

class TestRegistry:
    def setup_method(self):
        # Save and restore registry state around each test
        self._saved = dict(_REGISTRY)

    def teardown_method(self):
        _REGISTRY.clear()
        _REGISTRY.update(self._saved)

    def test_register_decorator(self):
        @register
        class FakeScraper(ScraperPlugin):
            meta = PluginMeta(name="fake", id_prefix="fk")

            def scrape(self, ctx):
                return ScrapeResult(source="fake", jobs=[])

        assert "fake" in _REGISTRY
        assert _REGISTRY["fake"] is FakeScraper

    def test_get_scraper_returns_instance(self):
        @register
        class FakeScraper(ScraperPlugin):
            meta = PluginMeta(name="fake2", id_prefix="fk2")

            def scrape(self, ctx):
                return ScrapeResult(source="fake2", jobs=[])

        instance = get_scraper("fake2")
        assert isinstance(instance, FakeScraper)

    def test_get_scraper_unknown_raises(self):
        with pytest.raises(KeyError, match="Unknown scraper: nope"):
            get_scraper("nope")

    def test_available_scrapers(self):
        @register
        class A(ScraperPlugin):
            meta = PluginMeta(name="aaa", id_prefix="a")
            def scrape(self, ctx):
                return ScrapeResult(source="aaa", jobs=[])

        @register
        class B(ScraperPlugin):
            meta = PluginMeta(name="bbb", id_prefix="b")
            def scrape(self, ctx):
                return ScrapeResult(source="bbb", jobs=[])

        names = available_scrapers()
        assert "aaa" in names
        assert "bbb" in names


# ---------------------------------------------------------------------------
# ATSBoardScraper tests
# ---------------------------------------------------------------------------

class TestATSBoardScraper:
    def test_empty_tokens_returns_empty(self):
        class Stub(ATSBoardScraper):
            meta = PluginMeta(name="stub", id_prefix="s", requires_tokens=True)
            def fetch_and_map(self, token, ctx):
                raise AssertionError("should not be called")

        result = Stub().scrape(ScrapeContext(tokens=[]))
        assert result.jobs == []
        assert result.errors == []
        assert result.failed_tokens == []

    def test_none_tokens_returns_empty(self):
        class Stub(ATSBoardScraper):
            meta = PluginMeta(name="stub", id_prefix="s", requires_tokens=True)
            def fetch_and_map(self, token, ctx):
                raise AssertionError("should not be called")

        result = Stub().scrape(ScrapeContext(tokens=None))
        assert result.jobs == []

    def test_normal_returns_jobs_from_multiple_tokens(self):
        class Stub(ATSBoardScraper):
            meta = PluginMeta(name="stub", id_prefix="s", requires_tokens=True)
            max_workers = 2

            def fetch_and_map(self, token, ctx):
                return [_make_job(f"s-{token}-1", source="stub")]

        result = Stub().scrape(ScrapeContext(tokens=["a", "b", "c"]))
        assert len(result.jobs) == 3
        assert result.source == "stub"
        assert result.errors == []
        assert result.failed_tokens == []

    def test_board_not_found_goes_to_failed_tokens(self):
        class Stub(ATSBoardScraper):
            meta = PluginMeta(name="stub", id_prefix="s", requires_tokens=True)
            max_workers = 1

            def fetch_and_map(self, token, ctx):
                if token == "bad":
                    raise BoardNotFoundError("404")
                return [_make_job(f"s-{token}-1", source="stub")]

        result = Stub().scrape(ScrapeContext(tokens=["good", "bad"]))
        assert len(result.jobs) == 1
        assert result.failed_tokens == ["bad"]
        assert result.errors == []

    def test_generic_exception_goes_to_errors(self):
        class Stub(ATSBoardScraper):
            meta = PluginMeta(name="stub", id_prefix="s", requires_tokens=True)
            max_workers = 1

            def fetch_and_map(self, token, ctx):
                if token == "err":
                    raise RuntimeError("connection failed")
                return [_make_job(f"s-{token}-1", source="stub")]

        result = Stub().scrape(ScrapeContext(tokens=["ok", "err"]))
        assert len(result.jobs) == 1
        assert result.failed_tokens == []
        assert len(result.errors) == 1
        assert "err: RuntimeError: connection failed" in result.errors[0]

    def test_mixed_errors(self):
        class Stub(ATSBoardScraper):
            meta = PluginMeta(name="stub", id_prefix="s", requires_tokens=True)
            max_workers = 1

            def fetch_and_map(self, token, ctx):
                if token == "404":
                    raise BoardNotFoundError()
                if token == "err":
                    raise ValueError("bad data")
                return [_make_job(f"s-{token}", source="stub")]

        result = Stub().scrape(ScrapeContext(tokens=["ok", "404", "err"]))
        assert len(result.jobs) == 1
        assert "404" in result.failed_tokens
        assert any("ValueError" in e for e in result.errors)

    def test_client_side_filtering(self):
        class Stub(ATSBoardScraper):
            meta = PluginMeta(name="stub", id_prefix="s", requires_tokens=True)
            max_workers = 1

            def fetch_and_map(self, token, ctx):
                return [
                    _make_job(f"s-{token}-1", source="stub", title="Python Engineer"),
                    _make_job(f"s-{token}-2", source="stub", title="Sales Rep"),
                ]

        result = Stub().scrape(ScrapeContext(tokens=["a"], search_term="python"))
        assert len(result.jobs) == 1
        assert result.jobs[0].title == "Python Engineer"

    def test_rate_limiting(self):
        call_times = []

        class Stub(ATSBoardScraper):
            meta = PluginMeta(name="stub", id_prefix="s", requires_tokens=True)
            max_workers = 4
            min_interval = 0.05  # 50ms between requests

            def fetch_and_map(self, token, ctx):
                call_times.append(time.time())
                return []

        Stub().scrape(ScrapeContext(tokens=["a", "b", "c", "d"]))

        assert len(call_times) == 4
        call_times.sort()
        for i in range(1, len(call_times)):
            gap = call_times[i] - call_times[i - 1]
            # Allow some tolerance (40ms instead of 50ms) for timing jitter
            assert gap >= 0.04, f"Gap {i}: {gap:.4f}s < 0.04s"
