"""Scrape orchestrator: ties scrapers to the store."""

from __future__ import annotations

import logging
from datetime import datetime

from jbs.config import Config
from jbs.scrapers import get_scraper
from jbs.scrapers.base import ScrapeContext
from jbs.store import Store

log = logging.getLogger(__name__)


class ScraperOrchestrator:
    def __init__(self, config: Config, store: Store):
        self.config = config
        self.store = store

    def run(
        self,
        sources: list[str],
        search_term: str | None = None,
        hours_old: int | None = None,
        dry_run: bool = False,
    ) -> dict:
        """Run scrapers sequentially. Returns {"run_id": ..., "total": ...}."""
        run_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")

        if not dry_run:
            self.store.start_run(run_id, ",".join(sources), search_term)

        total = 0

        for name in sources:
            scraper = get_scraper(name)
            ctx = self._build_context(name, search_term, hours_old)

            if scraper.meta.requires_tokens and not ctx.tokens:
                log.info("%s: skipped (no tokens in DB)", name)
                continue

            if dry_run:
                log.info("%s: dry-run (would scrape %d tokens)",
                         name, len(ctx.tokens) if ctx.tokens else 0)
                continue

            result = scraper.scrape(ctx)
            inserted = self.store.upsert_jobs(result.jobs, run_id)
            total += inserted

            if result.failed_tokens:
                self.store.mark_tokens_stale(name, result.failed_tokens)

            # Mark tokens that returned jobs as valid
            if scraper.meta.requires_tokens and ctx.tokens:
                successful = [t for t in ctx.tokens if t not in set(result.failed_tokens)]
                if successful:
                    self.store.mark_tokens_valid(name, successful)

            self.store.mark_stale_jobs(run_id, name)

            self._log_source_summary(name, result, inserted)

        if not dry_run:
            self.store.finish_run(run_id, total)

        return {"run_id": run_id, "total": total}

    def _build_context(
        self, source: str, search_term: str | None, hours_old: int | None
    ) -> ScrapeContext:
        """Build ScrapeContext. For ATS sources, load tokens from DB."""
        tokens = None
        if source in ("greenhouse", "lever", "ashby"):
            tokens = self.store.get_tokens(source)
        return ScrapeContext(
            search_term=search_term,
            hours_old=hours_old or self.config.hours_old,
            tokens=tokens,
        )

    @staticmethod
    def _log_source_summary(name: str, result, inserted: int) -> None:
        total = len(result.jobs)
        errors = len(result.errors)
        failed = len(result.failed_tokens)
        log.info(
            "%s: %d jobs (%d new), %.1fs%s%s",
            name,
            total,
            inserted,
            result.elapsed_seconds,
            f", {failed} failed tokens" if failed else "",
            f", {errors} errors" if errors else "",
        )
