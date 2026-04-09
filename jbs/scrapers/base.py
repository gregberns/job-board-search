"""Scraper plugin interface: PluginMeta, ScrapeContext, ScraperPlugin ABC."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from jbs.models import ScrapeResult


@dataclass(frozen=True)
class PluginMeta:
    name: str              # e.g. "greenhouse"
    id_prefix: str         # e.g. "gh"
    requires_tokens: bool = False


@dataclass
class ScrapeContext:
    search_term: str | None = None
    hours_old: int | None = None
    is_remote: bool = False
    results_wanted: int = 99999
    tokens: list[str] | None = None


class ScraperPlugin(ABC):
    meta: PluginMeta  # subclasses set as class variable

    @abstractmethod
    def scrape(self, ctx: ScrapeContext) -> ScrapeResult:
        """Must not raise. All errors go in ScrapeResult.errors."""
