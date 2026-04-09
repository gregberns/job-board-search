from pathlib import Path
from jbs.config import load_config, Config


def test_load_config_missing_file(tmp_path):
    """Missing config file returns correct defaults."""
    cfg = load_config(tmp_path / "nonexistent.toml")
    assert cfg.db_path == Path("data/jobs.db")
    assert cfg.default_sources == ["greenhouse", "lever", "ashby", "remoteok", "hn"]
    assert cfg.hours_old == 168


def test_load_config_custom_values(tmp_path):
    """Custom values override defaults."""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '[general]\ndb_path = "custom/path.db"\n'
        'default_sources = ["remoteok"]\nhours_old = 48\n'
    )
    cfg = load_config(config_file)
    assert cfg.db_path == Path("custom/path.db")
    assert cfg.default_sources == ["remoteok"]
    assert cfg.hours_old == 48


def test_config_db_path_is_path():
    """Config.db_path is a Path object."""
    cfg = Config()
    assert isinstance(cfg.db_path, Path)
