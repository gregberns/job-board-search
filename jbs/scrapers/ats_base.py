"""Shared base for ATS board scrapers (Greenhouse, Lever, Ashby)."""

import threading
import time
from abc import abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed

from jbs.models import Job, ScrapeResult
from jbs.scrapers.base import ScraperPlugin, ScrapeContext
from jbs.util import filter_jobs


class BoardNotFoundError(Exception):
    """Raised when an ATS board returns 404."""


class ATSBoardScraper(ScraperPlugin):
    max_workers: int = 10
    min_interval: float = 0.0  # seconds between requests

    def scrape(self, ctx: ScrapeContext) -> ScrapeResult:
        tokens = ctx.tokens or []
        if not tokens:
            return ScrapeResult(source=self.meta.name, jobs=[])

        all_jobs: list[Job] = []
        failed_tokens: list[str] = []
        errors: list[str] = []
        lock = threading.Lock()
        last_request_time = [0.0]  # mutable for closure

        def _rate_limited_fetch(token: str) -> list[Job]:
            if self.min_interval > 0:
                with lock:
                    elapsed = time.time() - last_request_time[0]
                    if elapsed < self.min_interval:
                        time.sleep(self.min_interval - elapsed)
                    last_request_time[0] = time.time()
            return self.fetch_and_map(token, ctx)

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {pool.submit(_rate_limited_fetch, t): t for t in tokens}
            for future in as_completed(futures):
                token = futures[future]
                try:
                    jobs = future.result()
                    all_jobs.extend(jobs)
                except BoardNotFoundError:
                    failed_tokens.append(token)
                except Exception as e:
                    errors.append(f"{token}: {type(e).__name__}: {e}")

        filtered = filter_jobs(all_jobs, ctx.search_term, ctx.hours_old, ctx.is_remote)
        return ScrapeResult(
            source=self.meta.name,
            jobs=filtered,
            failed_tokens=failed_tokens,
            errors=errors,
        )

    @abstractmethod
    def fetch_and_map(self, token: str, ctx: ScrapeContext) -> list[Job]:
        """Fetch all jobs from one board. Raise BoardNotFoundError on 404."""
