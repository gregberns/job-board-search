"""Tests for Ashby scraper."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jbs.models import Job, Location, WorkArrangement
from jbs.scrapers.ashby import (
    AshbyScraper,
    _CTRL_CHAR_RE,
    _extract_compensation,
    _map_job,
)
from jbs.scrapers.ats_base import BoardNotFoundError
from jbs.scrapers.base import ScrapeContext

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def board_response():
    with open(FIXTURES / "ashby_board_response.json") as f:
        return json.load(f)


@pytest.fixture
def board_response_text():
    with open(FIXTURES / "ashby_board_response.json") as f:
        return f.read()


@pytest.fixture
def scraper():
    return AshbyScraper()


# ---------------------------------------------------------------------------
# fetch_and_map
# ---------------------------------------------------------------------------

class TestFetchAndMap:
    def test_normal_fetch_returns_jobs(self, scraper, board_response_text, board_response):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = board_response_text
        mock_resp.raise_for_status = MagicMock()

        with patch.object(scraper.session, "get", return_value=mock_resp):
            jobs = scraper.fetch_and_map("acme", ScrapeContext())

        assert len(jobs) == 4
        assert all(isinstance(j, Job) for j in jobs)

    def test_404_raises_board_not_found(self, scraper):
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
# ID prefix
# ---------------------------------------------------------------------------

class TestIDPrefix:
    def test_id_prefix_is_ashby(self, board_response):
        jobs_data = board_response["jobs"]
        company = board_response["organizationName"]
        for raw in jobs_data:
            job = _map_job(raw, "acme", company)
            assert job is not None
            assert job.id.startswith("ashby-")

    def test_id_contains_original_id(self, board_response):
        raw = board_response["jobs"][0]
        job = _map_job(raw, "acme", "Acme Corp")
        assert job.id == "ashby-job-001"


# ---------------------------------------------------------------------------
# Structured compensation
# ---------------------------------------------------------------------------

class TestCompensation:
    def test_compensation_from_tiers(self, board_response):
        raw = board_response["jobs"][0]  # has compensationTiers
        comp = _extract_compensation(raw)
        assert comp is not None
        assert comp.min_amount == 150000
        assert comp.max_amount == 200000
        assert comp.currency == "USD"
        assert comp.interval == "yearly"

    def test_compensation_from_top_level_field(self, board_response):
        raw = board_response["jobs"][3]  # has top-level compensation
        comp = _extract_compensation(raw)
        assert comp is not None
        assert comp.min_amount == 80
        assert comp.max_amount == 120
        assert comp.currency == "USD"
        assert comp.interval == "hourly"

    def test_no_compensation_returns_none(self):
        raw = {"title": "Test"}
        comp = _extract_compensation(raw)
        assert comp is None

    def test_salary_summary_fallback(self):
        raw = {"scrapeableCompensationSalarySummary": "$100k - $150k"}
        comp = _extract_compensation(raw)
        assert comp is not None
        assert comp.min_amount == 100000
        assert comp.max_amount == 150000

    def test_salary_from_description_fallback(self, board_response):
        """Job 2 has no structured comp but description mentions salary."""
        raw = board_response["jobs"][1]
        job = _map_job(raw, "acme", "Acme Corp")
        assert job is not None
        assert job.compensation is not None
        assert job.compensation.min_amount == 120000
        assert job.compensation.max_amount == 160000


# ---------------------------------------------------------------------------
# JSON control character sanitization
# ---------------------------------------------------------------------------

class TestControlCharSanitization:
    def test_strips_null_byte(self):
        assert _CTRL_CHAR_RE.sub(" ", "hello\x00world") == "hello world"

    def test_strips_various_control_chars(self):
        text = "line1\x01\x02\x03end"
        assert _CTRL_CHAR_RE.sub(" ", text) == "line1   end"

    def test_preserves_newline_and_tab(self):
        text = "line1\nline2\ttab"
        assert _CTRL_CHAR_RE.sub(" ", text) == text

    def test_full_json_with_control_chars(self, scraper):
        payload = '{"organizationName": "Test", "jobs": [{"id": "1", "title": "Eng\\u0000ineer", "jobUrl": "https://x.com"}]}'
        # Replace the escaped unicode with actual null byte
        payload = payload.replace("\\u0000", "\x00")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = payload
        mock_resp.raise_for_status = MagicMock()

        with patch.object(scraper.session, "get", return_value=mock_resp):
            jobs = scraper.fetch_and_map("test", ScrapeContext())
        assert len(jobs) == 1
        assert "Eng" in jobs[0].title


# ---------------------------------------------------------------------------
# board_token
# ---------------------------------------------------------------------------

class TestBoardToken:
    def test_board_token_set(self, board_response):
        raw = board_response["jobs"][0]
        job = _map_job(raw, "myboard", "Acme Corp")
        assert job.board_token == "myboard"

    def test_all_jobs_have_board_token(self, scraper, board_response_text):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = board_response_text
        mock_resp.raise_for_status = MagicMock()

        with patch.object(scraper.session, "get", return_value=mock_resp):
            jobs = scraper.fetch_and_map("acme", ScrapeContext())
        assert all(j.board_token == "acme" for j in jobs)


# ---------------------------------------------------------------------------
# Location / remote detection
# ---------------------------------------------------------------------------

class TestLocation:
    def test_remote_detected(self, board_response):
        raw = board_response["jobs"][1]  # isRemote=true, location="Remote"
        job = _map_job(raw, "acme", "Acme Corp")
        assert job.is_remote is True
        assert job.location.work_arrangement == WorkArrangement.REMOTE

    def test_non_remote(self, board_response):
        raw = board_response["jobs"][0]  # SF, not remote
        job = _map_job(raw, "acme", "Acme Corp")
        assert job.is_remote is False
        assert job.location.city == "San Francisco"

    def test_source_is_ashby(self, board_response):
        raw = board_response["jobs"][0]
        job = _map_job(raw, "acme", "Acme Corp")
        assert job.source == "ashby"


# ---------------------------------------------------------------------------
# Job type mapping
# ---------------------------------------------------------------------------

class TestJobType:
    def test_fulltime(self, board_response):
        job = _map_job(board_response["jobs"][0], "t", "C")
        assert job.job_type == "full-time"

    def test_internship(self, board_response):
        job = _map_job(board_response["jobs"][2], "t", "C")
        assert job.job_type == "intern"

    def test_contract(self, board_response):
        job = _map_job(board_response["jobs"][3], "t", "C")
        assert job.job_type == "contract"


# ---------------------------------------------------------------------------
# Job function (department + team)
# ---------------------------------------------------------------------------

class TestJobFunction:
    def test_dept_and_team(self, board_response):
        job = _map_job(board_response["jobs"][0], "t", "C")
        assert job.job_function == "Engineering, Platform"

    def test_dept_only(self, board_response):
        job = _map_job(board_response["jobs"][1], "t", "C")
        assert job.job_function == "Design"

    def test_dept_and_team_ml(self, board_response):
        job = _map_job(board_response["jobs"][2], "t", "C")
        assert job.job_function == "Data, ML"


# ---------------------------------------------------------------------------
# Company name
# ---------------------------------------------------------------------------

class TestCompanyName:
    def test_company_from_org_name(self, board_response):
        raw = board_response["jobs"][0]
        job = _map_job(raw, "acme", "Acme Corp")
        assert job.company == "Acme Corp"

    def test_fallback_company_from_token(self):
        raw = {"id": "1", "title": "Eng", "jobUrl": "https://x.com"}
        job = _map_job(raw, "my-startup", "My Startup")
        assert job.company == "My Startup"


# ---------------------------------------------------------------------------
# Meta / registration
# ---------------------------------------------------------------------------

class TestMeta:
    def test_meta_name(self):
        assert AshbyScraper.meta.name == "ashby"

    def test_meta_id_prefix(self):
        assert AshbyScraper.meta.id_prefix == "ashby"

    def test_meta_requires_tokens(self):
        assert AshbyScraper.meta.requires_tokens is True

    def test_registered(self):
        from jbs.scrapers import available_scrapers
        assert "ashby" in available_scrapers()
