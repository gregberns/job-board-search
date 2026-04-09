"""Tests for jbs/discover.py — HN token discovery pipeline."""

import pytest
from unittest.mock import MagicMock, patch

from jbs.discover import (
    match_ats_url,
    is_dead_end,
    url_has_careers_path,
    detect_ats_in_html,
    harvest_ats_tokens,
    discover_careers_pages,
    detect_ats_on_careers,
    _classify_page,
)
from jbs.store import Store


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    db = tmp_path / "test.db"
    s = Store(db)
    # Insert a run so FK constraints are satisfied
    s._conn().execute(
        "INSERT INTO runs (run_id, started_at, sources) VALUES ('r1', '2026-01-01', 'hn')"
    )
    s._conn().commit()
    return s


def _insert_hn_job(store, job_id, url, company_raw=None):
    """Helper to insert an HN job row."""
    store._conn().execute(
        """INSERT INTO jobs (id, run_id, site, job_url, company_raw, title)
           VALUES (?, 'r1', 'hn', ?, ?, 'Engineer')""",
        (job_id, url, company_raw),
    )
    store._conn().commit()


# ---------------------------------------------------------------------------
# URL pattern matching
# ---------------------------------------------------------------------------

class TestMatchAtsUrl:
    def test_ashby(self):
        assert match_ats_url("https://jobs.ashbyhq.com/acme-ai") == ("ashby", "acme-ai")

    def test_ashby_with_path(self):
        assert match_ats_url("https://jobs.ashbyhq.com/acme-ai/some-job-id") == ("ashby", "acme-ai")

    def test_greenhouse_boards(self):
        assert match_ats_url("https://boards.greenhouse.io/livekitinc") == ("greenhouse", "livekitinc")

    def test_greenhouse_job_boards(self):
        assert match_ats_url("https://job-boards.greenhouse.io/ramp") == ("greenhouse", "ramp")

    def test_greenhouse_with_query(self):
        assert match_ats_url("https://boards.greenhouse.io/acme?gh_jid=123") == ("greenhouse", "acme")

    def test_lever(self):
        assert match_ats_url("https://jobs.lever.co/openai") == ("lever", "openai")

    def test_lever_with_path(self):
        assert match_ats_url("https://jobs.lever.co/openai/abc-123") == ("lever", "openai")

    def test_no_match(self):
        assert match_ats_url("https://example.com/careers") is None

    def test_no_match_homepage(self):
        assert match_ats_url("https://acme.com") is None


# ---------------------------------------------------------------------------
# Dead-end detection
# ---------------------------------------------------------------------------

class TestIsDeadEnd:
    def test_linkedin(self):
        assert is_dead_end("https://www.linkedin.com/company/acme") is True

    def test_linkedin_no_www(self):
        assert is_dead_end("https://linkedin.com/jobs/view/123") is True

    def test_youtube(self):
        assert is_dead_end("https://www.youtube.com/watch?v=abc") is True

    def test_youtu_be(self):
        assert is_dead_end("https://youtu.be/abc") is True

    def test_twitter(self):
        assert is_dead_end("https://twitter.com/acme") is True

    def test_x_dot_com(self):
        assert is_dead_end("https://x.com/acme") is True

    def test_github(self):
        assert is_dead_end("https://github.com/acme/repo") is True

    def test_pdf(self):
        assert is_dead_end("https://example.com/jobs.pdf") is True

    def test_google_docs(self):
        assert is_dead_end("https://docs.google.com/document/d/abc") is True

    def test_normal_url(self):
        assert is_dead_end("https://acme.com") is False

    def test_careers_url(self):
        assert is_dead_end("https://acme.com/careers") is False


# ---------------------------------------------------------------------------
# Careers path detection
# ---------------------------------------------------------------------------

class TestUrlHasCareersPath:
    def test_careers(self):
        assert url_has_careers_path("https://acme.com/careers") is True

    def test_jobs(self):
        assert url_has_careers_path("https://acme.com/jobs") is True

    def test_hiring(self):
        assert url_has_careers_path("https://acme.com/hiring") is True

    def test_nested(self):
        assert url_has_careers_path("https://acme.com/about/careers") is True

    def test_join(self):
        assert url_has_careers_path("https://acme.com/join") is True

    def test_homepage(self):
        assert url_has_careers_path("https://acme.com") is False

    def test_random_path(self):
        assert url_has_careers_path("https://acme.com/about") is False


# ---------------------------------------------------------------------------
# ATS embed detection
# ---------------------------------------------------------------------------

class TestDetectAtsInHtml:
    def test_greenhouse_iframe(self):
        html = '<iframe src="https://boards.greenhouse.io/acme/jobs/123"></iframe>'
        assert detect_ats_in_html(html) == ("greenhouse", "acme")

    def test_greenhouse_job_boards_iframe(self):
        html = '<iframe src="https://job-boards.greenhouse.io/ramp"></iframe>'
        assert detect_ats_in_html(html) == ("greenhouse", "ramp")

    def test_lever_iframe(self):
        html = '<iframe src="https://jobs.lever.co/openai"></iframe>'
        assert detect_ats_in_html(html) == ("lever", "openai")

    def test_ashby_iframe(self):
        html = '<iframe src="https://jobs.ashbyhq.com/acme-ai"></iframe>'
        assert detect_ats_in_html(html) == ("ashby", "acme-ai")

    def test_greenhouse_embed_script(self):
        html = '<script src="https://boards.greenhouse.io/embed/job_board/js?for=acme"></script>'
        assert detect_ats_in_html(html) == ("greenhouse", "acme")

    def test_lever_embed_script(self):
        html = '<script src="https://jobs.lever.co/openai/embed"></script>'
        assert detect_ats_in_html(html) == ("lever", "openai")

    def test_greenhouse_link(self):
        html = '<a href="https://boards.greenhouse.io/acme">View Jobs</a>'
        assert detect_ats_in_html(html) == ("greenhouse", "acme")

    def test_ashby_link(self):
        html = '<a href="https://jobs.ashbyhq.com/acme-ai">View Jobs</a>'
        assert detect_ats_in_html(html) == ("ashby", "acme-ai")

    def test_no_ats(self):
        html = '<html><body><h1>Our Jobs</h1><p>Apply by email</p></body></html>'
        assert detect_ats_in_html(html) is None

    def test_greenhouse_div_data_url(self):
        html = '<div id="grnhse_app" data-url="https://boards.greenhouse.io/acme"></div>'
        assert detect_ats_in_html(html) == ("greenhouse", "acme")


# ---------------------------------------------------------------------------
# Page classification
# ---------------------------------------------------------------------------

class TestClassifyPage:
    def test_spa_root(self):
        html = '<html><body><div id="root"></div><script src="app.js"></script></body></html>'
        assert _classify_page(html) == 'spa'

    def test_spa_app(self):
        html = '<html><body><div id="app"></div></body></html>'
        assert _classify_page(html) == 'spa'

    def test_spa_next(self):
        html = '<html><body><div id="__next"></div></body></html>'
        assert _classify_page(html) == 'spa'

    def test_static_html(self):
        html = '<html><body>' + '<p>Some job content here.</p>' * 30 + '</body></html>'
        assert _classify_page(html) == 'static_html'

    def test_unknown_minimal(self):
        html = '<html><body><p>Hi</p></body></html>'
        assert _classify_page(html) == 'unknown'


# ---------------------------------------------------------------------------
# Phase 1: harvest_ats_tokens integration
# ---------------------------------------------------------------------------

class TestHarvestAtsTokens:
    def test_extracts_ashby_token(self, store):
        _insert_hn_job(store, "hn-1", "https://jobs.ashbyhq.com/acme-ai", "Acme AI")
        result = harvest_ats_tokens(store)

        assert result["ats_found"] == 1
        assert result["by_platform"]["ashby"] == 1

        # Token added to companies
        tokens = store.get_tokens("ashby")
        assert "acme-ai" in tokens

        # hn_career_pages updated
        pages = store.get_hn_pages_by_status("scraped")
        assert len(pages) == 1
        assert pages[0]["ats_platform"] == "ashby"
        assert pages[0]["ats_token"] == "acme-ai"

    def test_extracts_greenhouse_token(self, store):
        _insert_hn_job(store, "hn-2", "https://boards.greenhouse.io/livekitinc", "LiveKit")
        result = harvest_ats_tokens(store)

        assert result["ats_found"] == 1
        assert result["by_platform"]["greenhouse"] == 1
        assert "livekitinc" in store.get_tokens("greenhouse")

    def test_extracts_lever_token(self, store):
        _insert_hn_job(store, "hn-3", "https://jobs.lever.co/openai", "OpenAI")
        result = harvest_ats_tokens(store)

        assert result["ats_found"] == 1
        assert result["by_platform"]["lever"] == 1
        assert "openai" in store.get_tokens("lever")

    def test_non_ats_url_becomes_pending(self, store):
        _insert_hn_job(store, "hn-4", "https://acme.com", "Acme")
        result = harvest_ats_tokens(store)

        assert result["ats_found"] == 0
        pages = store.get_hn_pages_by_status("pending")
        assert len(pages) == 1

    def test_mixed_urls(self, store):
        _insert_hn_job(store, "hn-5", "https://jobs.ashbyhq.com/foo", "Foo")
        _insert_hn_job(store, "hn-6", "https://bar.com", "Bar")
        _insert_hn_job(store, "hn-7", "https://jobs.lever.co/baz", "Baz")
        result = harvest_ats_tokens(store)

        assert result["total"] == 3
        assert result["ats_found"] == 2

    def test_skips_already_processed(self, store):
        _insert_hn_job(store, "hn-8", "https://jobs.ashbyhq.com/acme-ai", "Acme AI")
        harvest_ats_tokens(store)

        # Run again — should find nothing new
        result = harvest_ats_tokens(store)
        assert result["total"] == 0


# ---------------------------------------------------------------------------
# Phase 2: discover_careers_pages integration
# ---------------------------------------------------------------------------

class TestDiscoverCareersPages:
    def test_dead_end_classified(self, store):
        _insert_hn_job(store, "hn-10", "https://linkedin.com/company/acme", "Acme")
        store.upsert_hn_career_page("hn-10", company_url="https://linkedin.com/company/acme", status="pending")

        result = discover_careers_pages(store)
        assert result["dead_ends"] == 1

        pages = store.get_hn_pages_by_status("skipped")
        assert len(pages) == 1
        assert pages[0]["page_type"] == "dead_end"

    def test_careers_url_detected(self, store):
        _insert_hn_job(store, "hn-11", "https://acme.com/careers", "Acme")
        store.upsert_hn_career_page("hn-11", company_url="https://acme.com/careers", status="pending")

        result = discover_careers_pages(store)
        assert result["discovered"] == 1

        pages = store.get_hn_pages_by_status("discovered")
        assert len(pages) == 1
        assert pages[0]["careers_url"] == "https://acme.com/careers"

    @patch("jbs.discover.create_session")
    def test_probes_careers_paths(self, mock_create, store):
        _insert_hn_job(store, "hn-12", "https://acme.com", "Acme")
        store.upsert_hn_career_page("hn-12", company_url="https://acme.com", status="pending")

        mock_session = MagicMock()
        mock_create.return_value = mock_session

        # HEAD /careers returns 200
        def head_side_effect(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200 if url == "https://acme.com/careers" else 404
            return resp

        mock_session.head.side_effect = head_side_effect

        result = discover_careers_pages(store)
        assert result["discovered"] == 1

        pages = store.get_hn_pages_by_status("discovered")
        assert pages[0]["careers_url"] == "https://acme.com/careers"

    @patch("jbs.discover.create_session")
    def test_scans_homepage_links(self, mock_create, store):
        _insert_hn_job(store, "hn-13", "https://acme.com", "Acme")
        store.upsert_hn_career_page("hn-13", company_url="https://acme.com", status="pending")

        mock_session = MagicMock()
        mock_create.return_value = mock_session

        # HEAD all paths return 404
        head_resp = MagicMock()
        head_resp.status_code = 404
        mock_session.head.return_value = head_resp

        # GET homepage returns HTML with careers link
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.text = '<html><body><a href="/careers">Join Us</a></body></html>'
        mock_session.get.return_value = get_resp

        result = discover_careers_pages(store)
        assert result["discovered"] == 1

        pages = store.get_hn_pages_by_status("discovered")
        assert pages[0]["careers_url"] == "https://acme.com/careers"


# ---------------------------------------------------------------------------
# Phase 3: detect_ats_on_careers integration
# ---------------------------------------------------------------------------

class TestDetectAtsOnCareers:
    @patch("jbs.discover.create_session")
    def test_detects_greenhouse_iframe(self, mock_create, store):
        _insert_hn_job(store, "hn-20", "https://acme.com/careers", "Acme")
        store.upsert_hn_career_page(
            "hn-20", company_name="Acme", company_url="https://acme.com",
            careers_url="https://acme.com/careers", status="discovered",
        )

        mock_session = MagicMock()
        mock_create.return_value = mock_session

        resp = MagicMock()
        resp.status_code = 200
        resp.text = '<html><body><iframe src="https://boards.greenhouse.io/acme/jobs"></iframe></body></html>'
        mock_session.get.return_value = resp

        result = detect_ats_on_careers(store)
        assert result["ats_found"] == 1
        assert result["by_platform"]["greenhouse"] == 1

        # Token added
        assert "acme" in store.get_tokens("greenhouse")

        # Status updated
        pages = store.get_hn_pages_by_status("scraped")
        assert len(pages) == 1
        assert pages[0]["ats_platform"] == "greenhouse"

    @patch("jbs.discover.create_session")
    def test_classifies_static_html(self, mock_create, store):
        _insert_hn_job(store, "hn-21", "https://bar.com/careers", "Bar")
        store.upsert_hn_career_page(
            "hn-21", company_name="Bar", careers_url="https://bar.com/careers",
            status="discovered",
        )

        mock_session = MagicMock()
        mock_create.return_value = mock_session

        resp = MagicMock()
        resp.status_code = 200
        resp.text = '<html><body>' + '<p>Job listing content here.</p>' * 30 + '</body></html>'
        mock_session.get.return_value = resp

        result = detect_ats_on_careers(store)
        assert result["ats_found"] == 0

        pages = store.get_hn_pages_by_status("discovered")
        assert len(pages) == 1
        assert pages[0]["page_type"] == "static_html"

    @patch("jbs.discover.create_session")
    def test_classifies_spa(self, mock_create, store):
        _insert_hn_job(store, "hn-22", "https://baz.com/careers", "Baz")
        store.upsert_hn_career_page(
            "hn-22", company_name="Baz", careers_url="https://baz.com/careers",
            status="discovered",
        )

        mock_session = MagicMock()
        mock_create.return_value = mock_session

        resp = MagicMock()
        resp.status_code = 200
        resp.text = '<html><body><div id="root"></div><script src="app.js"></script></body></html>'
        mock_session.get.return_value = resp

        result = detect_ats_on_careers(store)
        assert result["ats_found"] == 0

        pages = store.get_hn_pages_by_status("discovered")
        assert len(pages) == 1
        assert pages[0]["page_type"] == "spa"

    @patch("jbs.discover.create_session")
    def test_handles_http_error(self, mock_create, store):
        _insert_hn_job(store, "hn-23", "https://down.com/careers", "Down")
        store.upsert_hn_career_page(
            "hn-23", company_name="Down", careers_url="https://down.com/careers",
            status="discovered",
        )

        mock_session = MagicMock()
        mock_create.return_value = mock_session

        resp = MagicMock()
        resp.status_code = 500
        mock_session.get.return_value = resp

        result = detect_ats_on_careers(store)
        assert result["ats_found"] == 0

        pages = store.get_hn_pages_by_status("failed")
        assert len(pages) == 1
