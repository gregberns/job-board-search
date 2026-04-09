"""Tests for jbs/enrich.py — enrichment pipeline with mock LLM backend."""

import json
import pytest

from jbs.enrich import EnrichmentPipeline
from jbs.llm_backend import LLMBackend
from jbs.store import Store


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    """Store backed by a temp DB with sample data."""
    db = tmp_path / "test.db"
    s = Store(db)
    conn = s._conn()

    # Create a run
    conn.execute(
        "INSERT INTO runs (run_id, started_at, sources, status) VALUES ('r1', '2026-04-01T00:00:00Z', 'greenhouse', 'completed')"
    )

    # Create a company
    conn.execute(
        "INSERT INTO companies (name, name_normalized) VALUES ('Acme Corp', 'acme')"
    )
    company_id = conn.execute("SELECT id FROM companies WHERE name_normalized = 'acme'").fetchone()["id"]

    # Sample jobs
    jobs = [
        ("gh-1", "greenhouse", company_id, "Acme Corp", "Senior Software Engineer",
         "<div><p>Build distributed systems. 5+ years experience. Will sponsor H-1B visas.</p></div>",
         "San Francisco, CA", 150000, 200000, "USD", "yearly"),
        ("gh-2", "greenhouse", company_id, "Acme Corp", "Engineering Manager",
         "<h1>About</h1><p>Lead the platform team. No sponsorship available.</p>",
         "New York, NY", None, None, None, None),
        ("rok-1", "remoteok", company_id, "Acme Corp", "Junior Backend Developer",
         "Build APIs with Python and PostgreSQL. 2 years experience. Smar\u00e2\u0080\u0099t quotes here.",
         "Remote", 40, 60, "USD", "hourly"),
        ("gh-3", "greenhouse", company_id, "Acme Corp", "Staff ML Engineer",
         "Design ML pipelines. 8+ years of experience required. We sponsor visas.",
         "Remote", 200000, 300000, "EUR", "yearly"),
        ("gh-4", "greenhouse", company_id, "Acme Corp", "Sales Representative",
         "Sell our product to enterprise customers. Manage relationships with key accounts and drive revenue growth across the region.",
         "Chicago, IL", None, None, None, None),
    ]

    for job in jobs:
        conn.execute(
            """INSERT INTO jobs (id, run_id, site, company_id, company_raw, title,
                   description, location_raw, min_amount, max_amount, currency, salary_interval)
               VALUES (?, 'r1', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            job,
        )

    conn.commit()
    yield s
    s.close()


@pytest.fixture
def pipeline(store):
    return EnrichmentPipeline(store)


class MockLLMBackend(LLMBackend):
    """Returns canned classifications for testing."""

    def classify_jobs(self, jobs, system_prompt):
        results = {}
        for job in jobs:
            is_eng = "engineer" in job.get("title", "").lower()
            results[job["id"]] = {
                "engineering_role": is_eng,
                "seniority": "senior",
                "is_management": "manager" in job.get("title", "").lower(),
                "domain": "backend" if is_eng else None,
                "tech_stack": ["Python", "postgres"],
                "job_summary": f"Mock summary for {job.get('title', '')}",
            }
        return results

    def classify_companies(self, companies, system_prompt):
        results = {}
        for company in companies:
            results[company["name_normalized"]] = {
                "description": f"Mock description for {company.get('name', '')}",
                "industry": "Developer Tools",
                "ai_native": 0.3,
                "funding_stage": "series_b",
                "size_estimate": "51-200",
            }
        return results


# ---------------------------------------------------------------------------
# Stage 0: cleanup
# ---------------------------------------------------------------------------

class TestStage0Cleanup:
    def test_greenhouse_html_converted(self, pipeline, store):
        pipeline._run_stage0_cleanup()
        conn = store._conn()
        row = conn.execute("SELECT description FROM jobs WHERE id = 'gh-1'").fetchone()
        # Should no longer start with < (HTML)
        assert not row["description"].startswith("<")

    def test_greenhouse_detects_html(self, pipeline, store):
        counts = pipeline._run_stage0_cleanup()
        # gh-1 and gh-2 start with < — gh-3 and gh-4 don't
        assert counts["html_to_md"] == 2

    def test_remoteok_encoding_fixed(self, pipeline, store):
        counts = pipeline._run_stage0_cleanup()
        assert counts["encoding"] == 1

    def test_source_filter(self, pipeline, store):
        counts = pipeline._run_stage0_cleanup(source="greenhouse")
        assert counts["html_to_md"] == 2
        assert counts["encoding"] == 0  # remoteok skipped


# ---------------------------------------------------------------------------
# Stage 1: rule-based extraction
# ---------------------------------------------------------------------------

class TestStage1Rules:
    def test_seniority_extracted(self, pipeline, store):
        pipeline._run_stage1_rules()
        conn = store._conn()

        row = conn.execute("SELECT seniority FROM jobs WHERE id = 'gh-1'").fetchone()
        assert row["seniority"] == "senior"

        row = conn.execute("SELECT seniority FROM jobs WHERE id = 'rok-1'").fetchone()
        assert row["seniority"] == "junior"

        row = conn.execute("SELECT seniority FROM jobs WHERE id = 'gh-3'").fetchone()
        assert row["seniority"] == "staff"

    def test_management_detected(self, pipeline, store):
        pipeline._run_stage1_rules()
        conn = store._conn()

        row = conn.execute("SELECT is_management FROM jobs WHERE id = 'gh-2'").fetchone()
        assert row["is_management"] == 1

        row = conn.execute("SELECT is_management FROM jobs WHERE id = 'gh-1'").fetchone()
        assert row["is_management"] == 0

    def test_salary_normalized(self, pipeline, store):
        pipeline._run_stage1_rules()
        conn = store._conn()

        row = conn.execute("SELECT salary_usd_min, salary_usd_max FROM jobs WHERE id = 'gh-1'").fetchone()
        assert row["salary_usd_min"] == 150000
        assert row["salary_usd_max"] == 200000

        # Hourly -> annual
        row = conn.execute("SELECT salary_usd_min, salary_usd_max FROM jobs WHERE id = 'rok-1'").fetchone()
        assert row["salary_usd_min"] == 40 * 2080
        assert row["salary_usd_max"] == 60 * 2080

        # EUR -> USD
        row = conn.execute("SELECT salary_usd_min, salary_usd_max FROM jobs WHERE id = 'gh-3'").fetchone()
        assert row["salary_usd_min"] == round(200000 * 1.08)
        assert row["salary_usd_max"] == round(300000 * 1.08)

    def test_visa_detection(self, pipeline, store):
        # Run stage 0 first to convert HTML so descriptions are readable
        pipeline._run_stage0_cleanup()
        pipeline._run_stage1_rules()
        conn = store._conn()

        row = conn.execute("SELECT visa_sponsorship FROM jobs WHERE id = 'gh-1'").fetchone()
        assert row["visa_sponsorship"] == "sponsors"

        row = conn.execute("SELECT visa_sponsorship FROM jobs WHERE id = 'gh-2'").fetchone()
        assert row["visa_sponsorship"] == "no_sponsorship"

    def test_years_experience(self, pipeline, store):
        pipeline._run_stage0_cleanup()
        pipeline._run_stage1_rules()
        conn = store._conn()

        row = conn.execute("SELECT years_experience FROM jobs WHERE id = 'gh-1'").fetchone()
        assert row["years_experience"] == 5

        row = conn.execute("SELECT years_experience FROM jobs WHERE id = 'rok-1'").fetchone()
        assert row["years_experience"] == 2

    def test_enriched_at_set(self, pipeline, store):
        pipeline._run_stage1_rules()
        conn = store._conn()
        row = conn.execute("SELECT enriched_at FROM jobs WHERE id = 'gh-1'").fetchone()
        assert row["enriched_at"] is not None

    def test_idempotent_skips_enriched(self, pipeline, store):
        count1, _ = pipeline._run_stage1_rules()
        count2, _ = pipeline._run_stage1_rules()
        assert count1 == 5
        assert count2 == 0  # all already enriched

    def test_force_reprocesses(self, pipeline, store):
        pipeline._run_stage1_rules()
        count, _ = pipeline._run_stage1_rules(force=True)
        assert count == 5

    def test_source_filter(self, pipeline, store):
        count, _ = pipeline._run_stage1_rules(source="remoteok")
        assert count == 1


# ---------------------------------------------------------------------------
# Stage 2: LLM job classification (mock backend)
# ---------------------------------------------------------------------------

class TestStage2Jobs:
    def test_mock_classification(self, pipeline, store):
        backend = MockLLMBackend()
        # Need descriptions to be present
        pipeline._run_stage0_cleanup()
        count, results = pipeline._run_stage2_with_backend(backend)
        assert count == 5
        assert len(results) == 5

    def test_engineering_role_persisted(self, pipeline, store):
        backend = MockLLMBackend()
        pipeline._run_stage0_cleanup()
        pipeline._run_stage2_with_backend(backend)
        conn = store._conn()

        row = conn.execute("SELECT engineering_role FROM jobs WHERE id = 'gh-1'").fetchone()
        assert row["engineering_role"] == 1

        row = conn.execute("SELECT engineering_role FROM jobs WHERE id = 'gh-4'").fetchone()
        assert row["engineering_role"] == 0

    def test_tech_stack_stored_as_json(self, pipeline, store):
        backend = MockLLMBackend()
        pipeline._run_stage0_cleanup()
        pipeline._run_stage2_with_backend(backend)
        conn = store._conn()

        row = conn.execute("SELECT tech_stack FROM jobs WHERE id = 'gh-1'").fetchone()
        stack = json.loads(row["tech_stack"])
        # MockLLMBackend returns ["Python", "postgres"] which gets normalized
        assert "Python" in stack
        assert "PostgreSQL" in stack

    def test_enrichment_run_tracked(self, pipeline, store):
        backend = MockLLMBackend()
        pipeline._run_stage0_cleanup()
        pipeline._run_stage2_with_backend(backend)
        conn = store._conn()

        runs = conn.execute("SELECT * FROM enrichment_runs WHERE stage = 'jobs'").fetchall()
        assert len(runs) == 1
        assert runs[0]["items"] == 5


# ---------------------------------------------------------------------------
# Stage 3: LLM company classification (mock backend)
# ---------------------------------------------------------------------------

class TestStage3Companies:
    def test_mock_company_classification(self, pipeline, store):
        backend = MockLLMBackend()
        count, results = pipeline._run_stage3_with_backend(backend)
        assert count == 1
        assert "acme" in results

    def test_company_fields_persisted(self, pipeline, store):
        backend = MockLLMBackend()
        pipeline._run_stage3_with_backend(backend)
        conn = store._conn()

        row = conn.execute("SELECT * FROM companies WHERE name_normalized = 'acme'").fetchone()
        assert row["industry"] == "Developer Tools"
        assert row["ai_native"] == 0.3
        assert row["funding_stage"] == "series_b"
        assert row["size_estimate"] == "51-200"
        assert row["enriched_at"] is not None


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_dry_run_returns_counts(self, pipeline, store):
        info = pipeline._dry_run()
        assert info["stage0_html"] == 2  # gh-1, gh-2 start with <
        assert info["stage1"] == 5       # all unenriched
        assert info["stage2"] == 5       # all unenriched with descriptions
        assert info["stage3"] == 1       # one company

    def test_dry_run_no_mutations(self, pipeline, store):
        pipeline._dry_run()
        conn = store._conn()
        row = conn.execute("SELECT enriched_at FROM jobs WHERE id = 'gh-1'").fetchone()
        assert row["enriched_at"] is None  # nothing changed


# ---------------------------------------------------------------------------
# Full pipeline run (mock)
# ---------------------------------------------------------------------------

class TestFullPipeline:
    def test_run_all_stages(self, pipeline, store, monkeypatch):
        """Full pipeline with mock backend."""
        monkeypatch.setattr("jbs.enrich.get_llm_backend", lambda: MockLLMBackend())
        pipeline.run()
        conn = store._conn()

        # Stage 0+1 effects
        row = conn.execute("SELECT seniority, enriched_at FROM jobs WHERE id = 'gh-1'").fetchone()
        assert row["enriched_at"] is not None

        # Stage 2 effects
        row = conn.execute("SELECT engineering_role FROM jobs WHERE id = 'gh-1'").fetchone()
        assert row["engineering_role"] is not None

        # Stage 3 effects
        row = conn.execute("SELECT industry FROM companies WHERE name_normalized = 'acme'").fetchone()
        assert row["industry"] is not None
