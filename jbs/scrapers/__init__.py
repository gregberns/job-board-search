"""Scraper plugin registry."""

from jbs.scrapers.base import ScraperPlugin

_REGISTRY: dict[str, type[ScraperPlugin]] = {}


def register(cls):
    """Decorator. Registers a scraper plugin class by its meta.name."""
    _REGISTRY[cls.meta.name] = cls
    return cls


def get_scraper(name: str) -> ScraperPlugin:
    """Instantiate and return a scraper by name."""
    if name not in _REGISTRY:
        raise KeyError(f"Unknown scraper: {name}. Available: {list(_REGISTRY)}")
    return _REGISTRY[name]()


def available_scrapers() -> list[str]:
    """Return names of all registered scrapers."""
    return list(_REGISTRY)


# Explicit imports trigger @register on class definition.
# Scraper modules are placeholders until Beads 2a-2e create implementations.
try:
    from jbs.scrapers import greenhouse, lever, ashby, remoteok, hn  # noqa: E402, F401
except ImportError:
    pass  # Scraper modules not yet created (dev/testing)
