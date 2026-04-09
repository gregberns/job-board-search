"""Tests for the RemoteOK scraper plugin."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jbs.models import ScrapeResult, WorkArrangement
from jbs.scrapers.base import ScrapeContext
from jbs.scrapers.remoteok import RemoteOKScraper

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def api_response():
    return json.loads((FIXTURES / "remoteok_response.json").read_text())


@pytest.fixture
def scraper():
    return RemoteOKScraper()


def _mock_response(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    return resp


class TestRemoteOKScraper:
    def test_meta(self, scraper):
        assert scraper.meta.name == "remoteok"
        assert scraper.meta.id_prefix == "rok"
        assert scraper.meta.requires_tokens is False

    @patch("jbs.scrapers.remoteok.create_session")
    def test_scrape_returns_jobs(self, mock_session_factory, scraper, api_response):
        session = MagicMock()
        session.headers = {}
        session.get.return_value = _mock_response(json_data=api_response)
        mock_session_factory.return_value = session

        result = scraper.scrape(ScrapeContext())

        assert isinstance(result, ScrapeResult)
        assert result.source == "remoteok"
        assert len(result.jobs) == 4
        assert result.errors == []

    @patch("jbs.scrapers.remoteok.create_session")
    def test_id_prefix(self, mock_session_factory, scraper, api_response):
        session = MagicMock()
        session.headers = {}
        session.get.return_value = _mock_response(json_data=api_response)
        mock_session_factory.return_value = session

        result = scraper.scrape(ScrapeContext())

        for job in result.jobs:
            assert job.id.startswith("rok-"), f"Job ID {job.id} missing rok- prefix"

        ids = [j.id for j in result.jobs]
        assert "rok-101" in ids
        assert "rok-102" in ids

    @patch("jbs.scrapers.remoteok.create_session")
    def test_all_jobs_remote(self, mock_session_factory, scraper, api_response):
        session = MagicMock()
        session.headers = {}
        session.get.return_value = _mock_response(json_data=api_response)
        mock_session_factory.return_value = session

        result = scraper.scrape(ScrapeContext())

        for job in result.jobs:
            assert job.is_remote is True
            assert job.location.work_arrangement == WorkArrangement.REMOTE

    @patch("jbs.scrapers.remoteok.create_session")
    def test_salary_from_structured_fields(self, mock_session_factory, scraper, api_response):
        session = MagicMock()
        session.headers = {}
        session.get.return_value = _mock_response(json_data=api_response)
        mock_session_factory.return_value = session

        result = scraper.scrape(ScrapeContext())

        # rok-101 has salary_min=150000, salary_max=200000
        job_101 = next(j for j in result.jobs if j.id == "rok-101")
        assert job_101.compensation is not None
        assert job_101.compensation.min_amount == 150000.0
        assert job_101.compensation.max_amount == 200000.0
        assert job_101.compensation.currency == "USD"

    @patch("jbs.scrapers.remoteok.create_session")
    def test_salary_fallback_to_text(self, mock_session_factory, scraper, api_response):
        session = MagicMock()
        session.headers = {}
        session.get.return_value = _mock_response(json_data=api_response)
        mock_session_factory.return_value = session

        result = scraper.scrape(ScrapeContext())

        # rok-102 has salary_min=0, salary_max=0 but "$120k-$160k" in description
        job_102 = next(j for j in result.jobs if j.id == "rok-102")
        assert job_102.compensation is not None
        assert job_102.compensation.min_amount == 120000.0
        assert job_102.compensation.max_amount == 160000.0

    @patch("jbs.scrapers.remoteok.create_session")
    def test_429_returns_empty_with_error(self, mock_session_factory, scraper):
        session = MagicMock()
        session.headers = {}
        session.get.return_value = _mock_response(status_code=429)
        mock_session_factory.return_value = session

        result = scraper.scrape(ScrapeContext())

        assert result.jobs == []
        assert any("429" in e for e in result.errors)

    @patch("jbs.scrapers.remoteok.create_session")
    def test_empty_response(self, mock_session_factory, scraper):
        session = MagicMock()
        session.headers = {}
        session.get.return_value = _mock_response(json_data=[{"legal": "notice"}])
        mock_session_factory.return_value = session

        result = scraper.scrape(ScrapeContext())

        assert result.jobs == []
        assert result.errors == []

    @patch("jbs.scrapers.remoteok.create_session")
    def test_network_error(self, mock_session_factory, scraper):
        session = MagicMock()
        session.headers = {}
        session.get.side_effect = ConnectionError("timeout")
        mock_session_factory.return_value = session

        result = scraper.scrape(ScrapeContext())

        assert result.jobs == []
        assert len(result.errors) == 1
        assert "Network error" in result.errors[0]

    @patch("jbs.scrapers.remoteok.create_session")
    def test_date_parsing(self, mock_session_factory, scraper, api_response):
        session = MagicMock()
        session.headers = {}
        session.get.return_value = _mock_response(json_data=api_response)
        mock_session_factory.return_value = session

        result = scraper.scrape(ScrapeContext())

        from datetime import date
        job_101 = next(j for j in result.jobs if j.id == "rok-101")
        assert job_101.date_posted == date(2026, 4, 7)

    @patch("jbs.scrapers.remoteok.create_session")
    def test_job_url_and_apply_url(self, mock_session_factory, scraper, api_response):
        session = MagicMock()
        session.headers = {}
        session.get.return_value = _mock_response(json_data=api_response)
        mock_session_factory.return_value = session

        result = scraper.scrape(ScrapeContext())

        job_101 = next(j for j in result.jobs if j.id == "rok-101")
        assert job_101.url == "https://remoteok.com/remote-jobs/101"
        assert job_101.url_direct == "https://acme.com/apply/101"

        # rok-103 has no apply_url
        job_103 = next(j for j in result.jobs if j.id == "rok-103")
        assert job_103.url_direct is None

    @patch("jbs.scrapers.remoteok.create_session")
    def test_search_term_filtering(self, mock_session_factory, scraper, api_response):
        session = MagicMock()
        session.headers = {}
        session.get.return_value = _mock_response(json_data=api_response)
        mock_session_factory.return_value = session

        result = scraper.scrape(ScrapeContext(search_term="python"))

        titles = [j.title for j in result.jobs]
        assert "Senior Python Engineer" in titles
        # Data Scientist has "python" in tags but not in title/description mapped
        # Frontend Developer shouldn't match
        assert "Frontend Developer" not in titles
