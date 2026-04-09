"""Tests for HN Who's Hiring scraper."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jbs.models import WorkArrangement
from jbs.scrapers.base import ScrapeContext
from jbs.scrapers.hn import HNScraper, _parse_comment

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def algolia_response():
    return json.loads((FIXTURES / "hn_algolia_response.json").read_text())


@pytest.fixture
def comments_response():
    return json.loads((FIXTURES / "hn_comments.json").read_text())


@pytest.fixture
def comments(comments_response):
    return comments_response["children"]


# ---------------------------------------------------------------------------
# _parse_comment unit tests
# ---------------------------------------------------------------------------

class TestParseComment:
    def test_pipe_delimited_basic(self, comments):
        """Acme Corp | Senior Backend Engineer | San Francisco, CA | $180k-$250k | ONSITE | URL"""
        job = _parse_comment(comments[0])
        assert job is not None
        assert job.id == "hn-99101"
        assert job.source == "hn"
        assert job.company == "Acme Corp"
        assert job.title == "Senior Backend Engineer"
        assert job.url == "https://acme.example.com/jobs"
        assert job.location.city == "San Francisco"
        assert job.location.state == "CA"

    def test_id_prefix(self, comments):
        job = _parse_comment(comments[0])
        assert job.id.startswith("hn-")

    def test_company_extraction(self, comments):
        """First pipe segment is always the company."""
        job = _parse_comment(comments[0])
        assert job.company == "Acme Corp"
        job2 = _parse_comment(comments[1])
        assert job2.company == "WidgetLabs"

    def test_url_extraction(self, comments):
        """URL extracted from pipe segment."""
        job = _parse_comment(comments[0])
        assert job.url == "https://acme.example.com/jobs"

    def test_url_from_body(self, comments):
        """URL extracted from comment body when not in header."""
        job = _parse_comment(comments[1])
        # WidgetLabs has URL in body paragraph, not in pipe segments
        # The salary segment doesn't have a URL, so it falls back to body
        assert "widgetlabs.example.com" in job.url

    def test_salary_extraction(self, comments):
        """Salary parsed from $xxxk-$xxxk pattern."""
        job = _parse_comment(comments[0])
        assert job.compensation is not None
        assert job.compensation.min_amount == 180000
        assert job.compensation.max_amount == 250000
        assert job.compensation.currency == "USD"

    def test_remote_detection(self, comments):
        """WidgetLabs is fully remote."""
        job = _parse_comment(comments[1])
        assert job.is_remote is True

    def test_location_with_remote(self, comments):
        """DataFlow: 'NYC or Remote' — should detect remote and extract city."""
        job = _parse_comment(comments[2])
        assert job.is_remote is True

    def test_no_pipe_fallback(self, comments):
        """Comment without pipes uses first 80 chars as company."""
        job = _parse_comment(comments[3])
        assert job is not None
        assert job.company is not None
        assert len(job.company) <= 80

    def test_empty_comment_returns_none(self, comments):
        """Empty/deleted comment returns None."""
        job = _parse_comment(comments[4])
        assert job is None

    def test_date_posted(self, comments):
        """Date parsed from created_at_i unix timestamp."""
        job = _parse_comment(comments[0])
        assert job.date_posted is not None
        assert job.date_posted.year == 2026
        assert job.date_posted.month == 4

    def test_description_is_markdown(self, comments):
        """Description is converted from HTML to markdown."""
        job = _parse_comment(comments[0])
        assert job.description is not None
        assert "<p>" not in job.description

    def test_hn_permalink_fallback(self):
        """When no URL in comment, falls back to HN item permalink."""
        comment = {
            "id": 12345,
            "text": "SomeCo | Engineer | Remote",
            "created_at_i": 1775063000,
        }
        job = _parse_comment(comment)
        assert job.url == "https://news.ycombinator.com/item?id=12345"

    def test_malformed_pipes_graceful(self):
        """Empty pipe segments don't crash."""
        comment = {
            "id": 55555,
            "text": " | | | ",
            "created_at_i": 1775063000,
        }
        job = _parse_comment(comment)
        # May return None (all segments empty) or a job with fallback title
        # Either way, should not raise
        if job is not None:
            assert job.id == "hn-55555"

    def test_location_non_remote(self, comments):
        """NeuralPay is hybrid in London, not remote."""
        job = _parse_comment(comments[5])
        assert job is not None
        assert job.company == "NeuralPay"
        assert job.is_remote is False


# ---------------------------------------------------------------------------
# HNScraper.scrape integration tests (mocked HTTP)
# ---------------------------------------------------------------------------

class TestHNScraper:
    @patch("jbs.scrapers.hn.create_session")
    def test_scrape_success(self, mock_create_session, algolia_response, comments_response):
        mock_session = MagicMock()
        mock_create_session.return_value = mock_session

        # First call: search_by_date (find thread)
        search_resp = MagicMock()
        search_resp.ok = True
        search_resp.json.return_value = algolia_response

        # Second call: items/{id} (fetch comments)
        items_resp = MagicMock()
        items_resp.ok = True
        items_resp.json.return_value = comments_response

        mock_session.get.side_effect = [search_resp, items_resp]

        scraper = HNScraper()
        result = scraper.scrape(ScrapeContext())

        assert result.source == "hn"
        assert len(result.jobs) > 0
        assert result.errors == []
        assert all(j.id.startswith("hn-") for j in result.jobs)

    @patch("jbs.scrapers.hn.create_session")
    def test_scrape_no_thread_found(self, mock_create_session):
        mock_session = MagicMock()
        mock_create_session.return_value = mock_session

        search_resp = MagicMock()
        search_resp.ok = True
        search_resp.json.return_value = {"hits": []}
        mock_session.get.return_value = search_resp

        result = HNScraper().scrape(ScrapeContext())
        assert result.jobs == []
        assert any("Could not find" in e for e in result.errors)

    @patch("jbs.scrapers.hn.create_session")
    def test_scrape_network_error(self, mock_create_session):
        mock_session = MagicMock()
        mock_create_session.return_value = mock_session

        search_resp = MagicMock()
        search_resp.ok = True
        search_resp.json.return_value = {"hits": [{"objectID": "123"}]}

        mock_session.get.side_effect = [search_resp, ConnectionError("timeout")]

        result = HNScraper().scrape(ScrapeContext())
        assert result.jobs == []
        assert len(result.errors) == 1

    @patch("jbs.scrapers.hn.create_session")
    def test_scrape_with_search_term_filter(self, mock_create_session, algolia_response, comments_response):
        mock_session = MagicMock()
        mock_create_session.return_value = mock_session

        search_resp = MagicMock()
        search_resp.ok = True
        search_resp.json.return_value = algolia_response

        items_resp = MagicMock()
        items_resp.ok = True
        items_resp.json.return_value = comments_response

        mock_session.get.side_effect = [search_resp, items_resp]

        result = HNScraper().scrape(ScrapeContext(search_term="ML"))
        # Only DataFlow mentions ML
        assert all("ML" in (j.description or "") or "ML" in j.title for j in result.jobs)

    @patch("jbs.scrapers.hn.create_session")
    def test_scrape_results_wanted(self, mock_create_session, algolia_response, comments_response):
        mock_session = MagicMock()
        mock_create_session.return_value = mock_session

        search_resp = MagicMock()
        search_resp.ok = True
        search_resp.json.return_value = algolia_response

        items_resp = MagicMock()
        items_resp.ok = True
        items_resp.json.return_value = comments_response

        mock_session.get.side_effect = [search_resp, items_resp]

        result = HNScraper().scrape(ScrapeContext(results_wanted=2))
        assert len(result.jobs) <= 2
