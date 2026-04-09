from dataclasses import dataclass, field
from pathlib import Path
import tomllib


@dataclass
class Config:
    db_path: Path = Path("data/jobs.db")
    default_sources: list[str] = field(default_factory=lambda:
        ["greenhouse", "lever", "ashby", "remoteok", "hn"])
    hours_old: int = 168


def load_config(path: Path = Path("config.toml")) -> Config:
    """Load from TOML. Missing file = all defaults."""
    cfg = Config()
    if path.exists():
        with open(path, "rb") as f:
            data = tomllib.load(f)
        general = data.get("general", {})
        if "db_path" in general:
            cfg.db_path = Path(general["db_path"])
        if "default_sources" in general:
            cfg.default_sources = general["default_sources"]
        if "hours_old" in general:
            cfg.hours_old = general["hours_old"]
    return cfg
