import pytest
from pathlib import Path
from jbs.config import Config


@pytest.fixture
def tmp_db(tmp_path):
    """Returns a Path to a temp SQLite DB file."""
    return tmp_path / "test_jobs.db"


@pytest.fixture
def sample_config(tmp_db):
    """Returns a Config with temp DB path."""
    return Config(db_path=tmp_db)
