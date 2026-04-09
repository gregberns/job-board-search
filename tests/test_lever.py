"""Tests for Lever scraper."""

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jbs.models import Job, Location, WorkArrangement
from jbs.scrapers.lever import LeverScraper, _map_job, _parse_commitment
from jbs.scrapers.ats_base import BoardNotFoundError
from jbs.scrapers.base import ScrapeContext

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def postings():
    with open(FIXTURES / "lever_postings.json") as f:
        return json.load(f)


@pytest.fixture
def postings_text():
    with open(FIXTURES / "lever_postings.json") as f:
        return f.read()


@pytest.fixture
def scraper():
    return LeverScraper()


# ---------------------------------------------------------------------------
# fetch_and_map
# ---------------------------------------------------------------------------

class TestFetchAndMap:
    def test_normal_fetch_returns_jobs(self, scraper, postings):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = postings
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
    def test_id_prefix_is_lever(self, postings):
        for raw in postings:
            job = _map_job(raw, "acme")
            assert job is not None
            assert job.id.startswith("lever-")

    def test_id_contains_original_id(self, postings):
        job = _map_job(postings[0], "acme")
        assert job.id == "lever-abc-123-def"


# ---------------------------------------------------------------------------
# Epoch-ms date conversion
# ---------------------------------------------------------------------------

class TestDateConversion:
    def test_epoch_ms_to_date(self, postings):
        job = _map_job(postings[0], "acme")
        assert job.date_posted is not None
        assert isinstance(job.date_posted, date)
        # 1712000000000 ms = 2024-04-01 (approx, depends on tz)
        assert job.date_posted.year == 2024

    def test_missing_created_at(self):
        raw = {"id": "x", "text": "Eng", "hostedUrl": "https://x.com"}
        job = _map_job(raw, "test")
        assert job.date_posted is None


# ---------------------------------------------------------------------------
# Location from categories
# ---------------------------------------------------------------------------

class TestLocation:
    def test_location_from_categories(self, postings):
        job = _map_job(postings[0], "acme")
        assert job.location.city == "San Francisco"
        assert job.location.state == "CA"

    def test_remote_from_workplace_type(self, postings):
        job = _map_job(postings[1], "acme")
        assert job.is_remote is True
        assert job.location.work_arrangement == WorkArrangement.REMOTE

    def test_non_remote(self, postings):
        job = _map_job(postings[0], "acme")
        assert job.is_remote is False

    def test_country_from_response_field(self, postings):
        job = _map_job(postings[0], "acme")
        # First posting has "country": "US"
        assert job.location.country == "US"


# ---------------------------------------------------------------------------
# board_token
# ---------------------------------------------------------------------------

class TestBoardToken:
    def test_board_token_set(self, postings):
        job = _map_job(postings[0], "myboard")
        assert job.board_token == "myboard"

    def test_all_jobs_have_board_token(self, scraper, postings):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = postings
        mock_resp.raise_for_status = MagicMock()

        with patch.object(scraper.session, "get", return_value=mock_resp):
            jobs = scraper.fetch_and_map("acme", ScrapeContext())
        assert all(j.board_token == "acme" for j in jobs)


# ---------------------------------------------------------------------------
# Compensation
# ---------------------------------------------------------------------------

class TestCompensation:
    def test_salary_from_additional_text(self, postings):
        job = _map_job(postings[0], "acme")
        assert job.compensation is not None
        assert job.compensation.min_amount == 180000
        assert job.compensation.max_amount == 220000
        assert job.compensation.currency == "USD"

    def test_salary_from_description_fallback(self, postings):
        job = _map_job(postings[1], "acme")
        assert job.compensation is not None
        assert job.compensation.min_amount == 120000
        assert job.compensation.max_amount == 160000

    def test_salary_range_structured(self, postings):
        job = _map_job(postings[3], "acme")
        assert job.compensation is not None
        assert job.compensation.min_amount == 80
        assert job.compensation.max_amount == 120
        assert job.compensation.interval == "hourly"

    def test_no_compensation_returns_none(self):
        raw = {"id": "x", "text": "Eng", "hostedUrl": "https://x.com", "description": "<p>No salary info</p>"}
        job = _map_job(raw, "test")
        assert job.compensation is None


# ---------------------------------------------------------------------------
# Commitment → job type
# ---------------------------------------------------------------------------

class TestJobType:
    def test_fulltime(self, postings):
        job = _map_job(postings[0], "t")
        assert job.job_type == "full-time"

    def test_internship(self, postings):
        job = _map_job(postings[2], "t")
        assert job.job_type == "intern"

    def test_contract(self, postings):
        job = _map_job(postings[3], "t")
        assert job.job_type == "contract"

    def test_parse_commitment_none(self):
        assert _parse_commitment("") is None
        assert _parse_commitment(None) is None


# ---------------------------------------------------------------------------
# Job function (team / department)
# ---------------------------------------------------------------------------

class TestJobFunction:
    def test_team_preferred_over_department(self, postings):
        job = _map_job(postings[0], "t")
        # Has both team="Platform" and department="Engineering"; team wins
        assert job.job_function == "Platform"

    def test_department_fallback(self, postings):
        job = _map_job(postings[1], "t")
        assert job.job_function == "Design"

    def test_no_function(self):
        raw = {"id": "x", "text": "Eng", "hostedUrl": "https://x.com", "categories": {}}
        job = _map_job(raw, "t")
        assert job.job_function is None


# ---------------------------------------------------------------------------
# Description
# ---------------------------------------------------------------------------

class TestDescription:
    def test_prefers_description_body(self, postings):
        job = _map_job(postings[0], "t")
        # descriptionBody is preferred over description
        assert "senior engineer" in job.description.lower()
        assert "Fallback" not in job.description

    def test_lists_appended(self, postings):
        job = _map_job(postings[0], "t")
        assert "Requirements" in job.description
        assert "5+ years" in job.description


# ---------------------------------------------------------------------------
# Company name
# ---------------------------------------------------------------------------

class TestCompanyName:
    def test_company_from_token(self, postings):
        job = _map_job(postings[0], "acme")
        assert job.company == "Acme"

    def test_hyphenated_token(self, postings):
        job = _map_job(postings[0], "my-startup")
        assert job.company == "My Startup"


# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------

class TestSource:
    def test_source_is_lever(self, postings):
        job = _map_job(postings[0], "acme")
        assert job.source == "lever"


# ---------------------------------------------------------------------------
# Meta / registration
# ---------------------------------------------------------------------------

class TestMeta:
    def test_meta_name(self):
        assert LeverScraper.meta.name == "lever"

    def test_meta_id_prefix(self):
        assert LeverScraper.meta.id_prefix == "lever"

    def test_meta_requires_tokens(self):
        assert LeverScraper.meta.requires_tokens is True

    def test_registered(self):
        from jbs.scrapers import available_scrapers
        assert "lever" in available_scrapers()

    def test_rate_limit_settings(self):
        assert LeverScraper.max_workers == 2
        assert LeverScraper.min_interval == 0.5
