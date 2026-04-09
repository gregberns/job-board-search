"""Tests for jbs CLI commands."""

import json

import pytest
from click.testing import CliRunner

from jbs.cli import cli
from jbs.store import Store


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def store(db_path):
    s = Store(db_path)
    yield s
    s.close()


def _seed_job(store, job_id="gh-100", title="Engineer", company="Acme", site="greenhouse"):
    """Insert a minimal job for testing."""
    conn = store._conn()
    # Run must exist before jobs (FK constraint)
    conn.execute(
        "INSERT OR IGNORE INTO runs (run_id, started_at, status) VALUES ('run1', '2026-04-01', 'completed')"
    )
    conn.execute(
        """INSERT OR IGNORE INTO companies (name, name_normalized)
           VALUES (?, ?)""",
        (company, company.lower()),
    )
    company_id = conn.execute(
        "SELECT id FROM companies WHERE name_normalized = ?", (company.lower(),)
    ).fetchone()["id"]
    conn.execute(
        """INSERT OR IGNORE INTO jobs (id, run_id, site, company_id, company_raw, title,
           date_posted, job_url, is_active, first_seen_run, last_seen_run)
           VALUES (?, 'run1', ?, ?, ?, ?, '2026-04-01', 'https://example.com/job', 1, 'run1', 'run1')""",
        (job_id, site, company_id, company, title),
    )
    conn.commit()
    return company_id


class TestInit:
    def test_init_creates_db(self, runner, tmp_path):
        db = str(tmp_path / "new.db")
        result = runner.invoke(cli, ["--db", db, "init"])
        assert result.exit_code == 0
        assert "Creating" in result.output or "Database already exists" in result.output

    def test_init_idempotent(self, runner, db_path, store):
        # DB already exists from fixture
        result = runner.invoke(cli, ["--db", db_path, "init"])
        assert result.exit_code == 0
        assert "already exists" in result.output or "Importing" in result.output


class TestScrape:
    def test_scrape_no_db(self, runner, tmp_path):
        db = str(tmp_path / "missing.db")
        result = runner.invoke(cli, ["--db", db, "scrape"])
        assert result.exit_code != 0 or "No database found" in result.output

    def test_scrape_dry_run(self, runner, db_path, store):
        result = runner.invoke(cli, ["--db", db_path, "scrape", "--dry-run"])
        assert result.exit_code == 0


class TestSearch:
    def test_search_empty(self, runner, db_path, store):
        result = runner.invoke(cli, ["--db", db_path, "search"])
        assert result.exit_code == 0

    def test_search_table_output(self, runner, db_path, store):
        _seed_job(store)
        result = runner.invoke(cli, ["--db", db_path, "--format", "table", "search"])
        assert result.exit_code == 0
        assert "gh-100" in result.output
        assert "Engineer" in result.output

    def test_search_json_output(self, runner, db_path, store):
        _seed_job(store)
        result = runner.invoke(cli, ["--db", db_path, "--format", "json", "search"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["id"] == "gh-100"

    def test_search_csv_output(self, runner, db_path, store):
        _seed_job(store)
        result = runner.invoke(cli, ["--db", db_path, "--format", "csv", "search"])
        assert result.exit_code == 0
        assert "id," in result.output
        assert "gh-100" in result.output

    def test_search_with_company_filter(self, runner, db_path, store):
        _seed_job(store, job_id="gh-1", company="Anthropic")
        _seed_job(store, job_id="gh-2", company="Ramp")
        result = runner.invoke(cli, ["--db", db_path, "--format", "json", "search", "--company", "Anthropic"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert all(r["company_name"] == "Anthropic" for r in data)

    def test_search_new_flag(self, runner, db_path, store):
        _seed_job(store)
        result = runner.invoke(cli, ["--db", db_path, "search", "--new"])
        assert result.exit_code == 0

    def test_search_engineering_flag(self, runner, db_path, store):
        _seed_job(store)
        conn = store._conn()
        conn.execute("UPDATE jobs SET engineering_role = 1 WHERE id = 'gh-100'")
        conn.commit()
        result = runner.invoke(cli, ["--db", db_path, "--format", "json", "search", "--engineering"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1


class TestShow:
    def test_show_job(self, runner, db_path, store):
        _seed_job(store)
        result = runner.invoke(cli, ["--db", db_path, "--format", "table", "show", "gh-100"])
        assert result.exit_code == 0
        assert "Engineer" in result.output
        assert "Acme" in result.output

    def test_show_partial_id(self, runner, db_path, store):
        _seed_job(store, job_id="gh-881901")
        result = runner.invoke(cli, ["--db", db_path, "--format", "table", "show", "gh-881"])
        assert result.exit_code == 0
        assert "Engineer" in result.output

    def test_show_json(self, runner, db_path, store):
        _seed_job(store)
        result = runner.invoke(cli, ["--db", db_path, "--format", "json", "show", "gh-100"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["id"] == "gh-100"

    def test_show_no_desc(self, runner, db_path, store):
        _seed_job(store)
        conn = store._conn()
        conn.execute("UPDATE jobs SET description = 'Long description here' WHERE id = 'gh-100'")
        conn.commit()
        result = runner.invoke(cli, ["--db", db_path, "--format", "table", "show", "gh-100", "--no-desc"])
        assert result.exit_code == 0
        assert "Long description here" not in result.output

    def test_show_not_found(self, runner, db_path, store):
        result = runner.invoke(cli, ["--db", db_path, "show", "nonexistent"])
        assert result.exit_code != 0


class TestEnrich:
    def test_enrich_dry_run(self, runner, db_path, store):
        _seed_job(store)
        result = runner.invoke(cli, ["--db", db_path, "enrich", "--dry-run"])
        assert result.exit_code == 0


class TestAnnotate:
    def test_annotate_tag(self, runner, db_path, store):
        _seed_job(store)
        result = runner.invoke(cli, ["--db", db_path, "annotate", "gh-100", "--tag", "interesting"])
        assert result.exit_code == 0
        assert "+ tag: interesting" in result.output

    def test_annotate_rating(self, runner, db_path, store):
        _seed_job(store)
        result = runner.invoke(cli, ["--db", db_path, "annotate", "gh-100", "--rating", "4"])
        assert result.exit_code == 0
        assert "rating: 4" in result.output
        job = store.get_job("gh-100")
        assert job["annotation_rating"] == 4

    def test_annotate_note(self, runner, db_path, store):
        _seed_job(store)
        result = runner.invoke(cli, ["--db", db_path, "annotate", "gh-100", "--note", "Great fit"])
        assert result.exit_code == 0
        assert "note: Great fit" in result.output

    def test_annotate_untag(self, runner, db_path, store):
        _seed_job(store)
        store.add_tag("gh-100", "old-tag")
        result = runner.invoke(cli, ["--db", db_path, "annotate", "gh-100", "--untag", "old-tag"])
        assert result.exit_code == 0
        assert "- tag: old-tag" in result.output
        job = store.get_job("gh-100")
        assert "old-tag" not in job["tags"]

    def test_annotate_pros_cons(self, runner, db_path, store):
        _seed_job(store)
        result = runner.invoke(cli, [
            "--db", db_path, "annotate", "gh-100",
            "--pros", "Great comp", "--cons", "Remote only",
        ])
        assert result.exit_code == 0
        job = store.get_job("gh-100")
        assert "Great comp" in job["pros"]
        assert "Remote only" in job["cons"]


class TestApply:
    def test_apply_default_stage(self, runner, db_path, store):
        _seed_job(store)
        result = runner.invoke(cli, ["--db", db_path, "apply", "gh-100"])
        assert result.exit_code == 0
        assert "interest: applied" in result.output

    def test_apply_custom_stage(self, runner, db_path, store):
        _seed_job(store)
        result = runner.invoke(cli, [
            "--db", db_path, "apply", "gh-100",
            "--stage", "phone-screen", "--note", "Apr 10",
        ])
        assert result.exit_code == 0
        assert "interest: phone-screen" in result.output

    def test_apply_list(self, runner, db_path, store):
        _seed_job(store)
        store.set_interest("gh-100", "applied")
        result = runner.invoke(cli, ["--db", db_path, "apply", "--list"])
        assert result.exit_code == 0
        assert "gh-100" in result.output

    def test_apply_list_empty(self, runner, db_path, store):
        result = runner.invoke(cli, ["--db", db_path, "apply", "--list"])
        assert result.exit_code == 0


class TestStats:
    def test_stats_empty(self, runner, db_path, store):
        result = runner.invoke(cli, ["--db", db_path, "--format", "table", "stats"])
        assert result.exit_code == 0
        assert "Jobs:" in result.output

    def test_stats_with_data(self, runner, db_path, store):
        _seed_job(store)
        result = runner.invoke(cli, ["--db", db_path, "stats"])
        assert result.exit_code == 0

    def test_stats_json(self, runner, db_path, store):
        _seed_job(store)
        result = runner.invoke(cli, ["--db", db_path, "--format", "json", "stats"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "jobs_total" in data


class TestTokensList:
    def test_tokens_list_empty(self, runner, db_path, store):
        result = runner.invoke(cli, ["--db", db_path, "tokens", "list"])
        assert result.exit_code == 0

    def test_tokens_list_with_data(self, runner, db_path, store):
        store.add_token("greenhouse", "anthropic")
        result = runner.invoke(cli, ["--db", db_path, "tokens", "list"])
        assert result.exit_code == 0
        assert "greenhouse" in result.output

    def test_tokens_list_json(self, runner, db_path, store):
        store.add_token("greenhouse", "anthropic")
        result = runner.invoke(cli, ["--db", db_path, "--format", "json", "tokens", "list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "greenhouse" in data


class TestTokensAdd:
    def test_add_new_token(self, runner, db_path, store):
        result = runner.invoke(cli, ["--db", db_path, "tokens", "add", "greenhouse", "anthropic"])
        assert result.exit_code == 0
        assert "Added greenhouse token: anthropic" in result.output

    def test_add_existing_token(self, runner, db_path, store):
        store.add_token("greenhouse", "anthropic")
        result = runner.invoke(cli, ["--db", db_path, "tokens", "add", "greenhouse", "anthropic"])
        assert result.exit_code == 0
        assert "already exists" in result.output

    def test_add_with_name(self, runner, db_path, store):
        result = runner.invoke(cli, [
            "--db", db_path, "tokens", "add", "lever", "ramp", "--name", "Ramp Technologies",
        ])
        assert result.exit_code == 0
        assert "Ramp Technologies" in result.output


class TestGlobalDbOption:
    def test_db_option(self, runner, tmp_path):
        db = str(tmp_path / "custom.db")
        result = runner.invoke(cli, ["--db", db, "init"])
        assert result.exit_code == 0
        # Verify DB was created at custom path
        assert (tmp_path / "custom.db").exists()


class TestTokensDiscover:
    def test_discover_status(self, runner, db_path, store):
        result = runner.invoke(cli, ["--db", db_path, "tokens", "discover", "--status"])
        assert result.exit_code == 0


class TestNoDbError:
    def test_search_no_db(self, runner, tmp_path):
        db = str(tmp_path / "missing.db")
        result = runner.invoke(cli, ["--db", db, "search"])
        assert "No database found" in result.output

    def test_show_no_db(self, runner, tmp_path):
        db = str(tmp_path / "missing.db")
        result = runner.invoke(cli, ["--db", db, "show", "gh-1"])
        assert "No database found" in result.output

    def test_stats_no_db(self, runner, tmp_path):
        db = str(tmp_path / "missing.db")
        result = runner.invoke(cli, ["--db", db, "stats"])
        assert "No database found" in result.output
