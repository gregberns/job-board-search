"""Tests for Greenhouse scraper."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from jbs.models import Job, WorkArrangement
from jbs.scrapers.greenhouse import GreenhouseScraper, _map_job
from jbs.scrapers.ats_base import BoardNotFoundError
from jbs.scrapers.base import ScrapeContext

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def board_response():
    with open(FIXTURES / "greenhouse_board.json") as f:
        return json.load(f)


@pytest.fixture
def detail_response():
    with open(FIXTURES / "greenhouse_job_detail.json") as f:
        return json.load(f)


@pytest.fixture
def scraper():
    return GreenhouseScraper()


# ---------------------------------------------------------------------------
# Two-pass fetch
# ---------------------------------------------------------------------------

class TestTwoPassFetch:
    def test_metadata_then_detail(self, scraper, board_response, detail_response):
        """Pass 1 fetches board listing, pass 2 fetches detail for each candidate."""
        board_resp = MagicMock()
        board_resp.status_code = 200
        board_resp.json.return_value = board_response
        board_resp.raise_for_status = MagicMock()

        detail_resp = MagicMock()
        detail_resp.ok = True
        detail_resp.json.return_value = detail_response

        mock_get = MagicMock(side_effect=[board_resp, detail_resp, detail_resp, detail_resp])
        with patch.object(scraper.session, "get", mock_get):
            jobs = scraper.fetch_and_map("acme", ScrapeContext())

        # 1 board call + 3 detail calls
        assert mock_get.call_count == 4
        assert len(jobs) == 3

    def test_detail_has_content(self, scraper, board_response, detail_response):
        """Detail response includes HTML content field."""
        board_resp = MagicMock()
        board_resp.status_code = 200
        board_resp.json.return_value = {"jobs": [board_response["jobs"][0]]}
        board_resp.raise_for_status = MagicMock()

        detail_resp_mock = MagicMock()
        detail_resp_mock.ok = True
        detail_resp_mock.json.return_value = detail_response

        with patch.object(scraper.session, "get", side_effect=[board_resp, detail_resp_mock]):
            jobs = scraper.fetch_and_map("acme", ScrapeContext())

        assert len(jobs) == 1
        assert jobs[0].description is not None
        assert "<strong>" in jobs[0].description

    def test_fallback_to_metadata_on_detail_failure(self, scraper, board_response):
        """If detail fetch fails, fall back to metadata (no description)."""
        board_resp = MagicMock()
        board_resp.status_code = 200
        board_resp.json.return_value = {"jobs": [board_response["jobs"][0]]}
        board_resp.raise_for_status = MagicMock()

        detail_resp = MagicMock()
        detail_resp.ok = False
        detail_resp.status_code = 500

        with patch.object(scraper.session, "get", side_effect=[board_resp, detail_resp]):
            jobs = scraper.fetch_and_map("acme", ScrapeContext())

        assert len(jobs) == 1
        assert jobs[0].description is None  # metadata has no content

    def test_prefilter_by_search_term(self, scraper, board_response, detail_response):
        """Only jobs matching search_term in title get detail-fetched."""
        board_resp = MagicMock()
        board_resp.status_code = 200
        board_resp.json.return_value = board_response
        board_resp.raise_for_status = MagicMock()

        detail_resp = MagicMock()
        detail_resp.ok = True
        detail_resp.json.return_value = detail_response

        ctx = ScrapeContext(search_term="Software Engineer")
        with patch.object(scraper.session, "get", side_effect=[board_resp, detail_resp]):
            jobs = scraper.fetch_and_map("acme", ctx)

        # Only "Senior Software Engineer" matches
        assert len(jobs) == 1
        assert "Software Engineer" in jobs[0].title

    def test_empty_board_returns_empty(self, scraper):
        """Board with no jobs returns empty list."""
        board_resp = MagicMock()
        board_resp.status_code = 200
        board_resp.json.return_value = {"jobs": []}
        board_resp.raise_for_status = MagicMock()

        with patch.object(scraper.session, "get", return_value=board_resp):
            jobs = scraper.fetch_and_map("empty", ScrapeContext())
        assert jobs == []


# ---------------------------------------------------------------------------
# ID prefix
# ---------------------------------------------------------------------------

class TestIDPrefix:
    def test_id_prefix_gh(self, detail_response):
        job = _map_job(detail_response, "acme")
        assert job.id == "gh-4012345"

    def test_all_ids_start_with_gh(self, board_response):
        for raw in board_response["jobs"]:
            job = _map_job(raw, "acme")
            assert job is not None
            assert job.id.startswith("gh-")


# ---------------------------------------------------------------------------
# HTML description preserved
# ---------------------------------------------------------------------------

class TestDescription:
    def test_html_stored_as_is(self, detail_response):
        """Description is raw HTML, not converted to markdown."""
        job = _map_job(detail_response, "acme")
        assert job.description is not None
        assert "<p>" in job.description
        assert "<strong>" in job.description
        assert "<ul>" in job.description

    def test_no_content_returns_none(self, board_response):
        """Metadata-only job (no content field) has None description."""
        job = _map_job(board_response["jobs"][0], "acme")
        assert job.description is None


# ---------------------------------------------------------------------------
# board_token
# ---------------------------------------------------------------------------

class TestBoardToken:
    def test_board_token_set(self, detail_response):
        job = _map_job(detail_response, "myboard")
        assert job.board_token == "myboard"

    def test_all_jobs_have_board_token(self, scraper, board_response, detail_response):
        board_resp = MagicMock()
        board_resp.status_code = 200
        board_resp.json.return_value = board_response
        board_resp.raise_for_status = MagicMock()

        detail_mock = MagicMock()
        detail_mock.ok = True
        detail_mock.json.return_value = detail_response

        with patch.object(scraper.session, "get", side_effect=[board_resp, detail_mock, detail_mock, detail_mock]):
            jobs = scraper.fetch_and_map("acme", ScrapeContext())
        assert all(j.board_token == "acme" for j in jobs)


# ---------------------------------------------------------------------------
# 404 raises BoardNotFoundError
# ---------------------------------------------------------------------------

class TestBoardNotFound:
    def test_404_raises(self, scraper):
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch.object(scraper.session, "get", return_value=mock_resp):
            with pytest.raises(BoardNotFoundError):
                scraper.fetch_and_map("badboard", ScrapeContext())

    def test_429_returns_empty(self, scraper):
        mock_resp = MagicMock()
        mock_resp.status_code = 429

        with patch.object(scraper.session, "get", return_value=mock_resp):
            jobs = scraper.fetch_and_map("ratelimited", ScrapeContext())
        assert jobs == []

    def test_request_exception_returns_empty(self, scraper):
        with patch.object(scraper.session, "get", side_effect=ConnectionError("timeout")):
            jobs = scraper.fetch_and_map("failing", ScrapeContext())
        assert jobs == []


# ---------------------------------------------------------------------------
# Location parsing
# ---------------------------------------------------------------------------

class TestLocation:
    def test_city_state_parsed(self, detail_response):
        job = _map_job(detail_response, "acme")
        assert job.location.city == "San Francisco"
        assert job.location.state == "CA"
        assert job.location.country == "USA"

    def test_remote_detected(self, board_response):
        job = _map_job(board_response["jobs"][1], "acme")  # location "Remote"
        assert job.is_remote is True
        assert job.location.work_arrangement == WorkArrangement.REMOTE

    def test_non_remote(self, detail_response):
        job = _map_job(detail_response, "acme")
        assert job.is_remote is False


# ---------------------------------------------------------------------------
# Source and company
# ---------------------------------------------------------------------------

class TestSourceAndCompany:
    def test_source_is_greenhouse(self, detail_response):
        job = _map_job(detail_response, "acme")
        assert job.source == "greenhouse"

    def test_company_from_api(self, detail_response):
        job = _map_job(detail_response, "acme")
        assert job.company == "Acme Corp"

    def test_company_none_when_not_in_response(self, board_response):
        """Metadata responses don't include company_name."""
        job = _map_job(board_response["jobs"][0], "acme")
        assert job.company is None


# ---------------------------------------------------------------------------
# Date and departments
# ---------------------------------------------------------------------------

class TestDateAndDepartments:
    def test_date_from_first_published(self, detail_response):
        from datetime import date
        job = _map_job(detail_response, "acme")
        assert job.date_posted == date(2026, 4, 1)

    def test_departments_to_job_function(self, detail_response):
        job = _map_job(detail_response, "acme")
        assert job.job_function == "Engineering"

    def test_multiple_departments(self, board_response):
        job = _map_job(board_response["jobs"][2], "acme")  # Data, Analytics
        assert job.job_function == "Data, Analytics"


# ---------------------------------------------------------------------------
# Compensation from description
# ---------------------------------------------------------------------------

class TestCompensation:
    def test_salary_extracted_from_html(self, detail_response):
        job = _map_job(detail_response, "acme")
        assert job.compensation is not None
        assert job.compensation.min_amount == 180000
        assert job.compensation.max_amount == 250000
        assert job.compensation.currency == "USD"

    def test_no_compensation_without_description(self, board_response):
        job = _map_job(board_response["jobs"][0], "acme")
        assert job.compensation is None


# ---------------------------------------------------------------------------
# Meta / registration
# ---------------------------------------------------------------------------

class TestMeta:
    def test_meta_name(self):
        assert GreenhouseScraper.meta.name == "greenhouse"

    def test_meta_id_prefix(self):
        assert GreenhouseScraper.meta.id_prefix == "gh"

    def test_meta_requires_tokens(self):
        assert GreenhouseScraper.meta.requires_tokens is True

    def test_registered(self):
        from jbs.scrapers import available_scrapers
        assert "greenhouse" in available_scrapers()
