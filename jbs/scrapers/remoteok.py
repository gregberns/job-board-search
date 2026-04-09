"""RemoteOK scraper — single API call, all jobs remote."""

from __future__ import annotations

import logging
from datetime import datetime

from jbs.models import Compensation, Job, Location, ScrapeResult, WorkArrangement
from jbs.scrapers import register
from jbs.scrapers.base import PluginMeta, ScraperPlugin, ScrapeContext
from jbs.util import (
    create_session,
    extract_salary_from_text,
    filter_jobs,
    html_to_markdown,
    parse_location,
)

log = logging.getLogger(__name__)

API_URL = "https://remoteok.com/api"


def _parse_compensation(item: dict) -> Compensation | None:
    """Extract compensation from salary_min / salary_max fields."""
    salary_min = item.get("salary_min")
    salary_max = item.get("salary_max")

    min_val = float(salary_min) if salary_min and int(salary_min) != 0 else None
    max_val = float(salary_max) if salary_max and int(salary_max) != 0 else None

    if min_val is None and max_val is None:
        return None

    return Compensation(min_amount=min_val, max_amount=max_val, currency="USD", interval="yearly")


def _parse_date(date_str: str | None):
    """Parse an ISO-format date string into a date object."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
    except (ValueError, AttributeError):
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


@register
class RemoteOKScraper(ScraperPlugin):
    meta = PluginMeta(name="remoteok", id_prefix="rok", requires_tokens=False)

    def scrape(self, ctx: ScrapeContext) -> ScrapeResult:
        """Single GET to remoteok.com/api. All jobs are remote. Never raises."""
        session = create_session()
        session.headers["Accept"] = "application/json"

        try:
            response = session.get(API_URL, timeout=30)
        except Exception as e:
            log.error("Network error fetching RemoteOK API: %s", e)
            return ScrapeResult(source="remoteok", jobs=[], errors=[f"Network error: {e}"])

        if response.status_code == 429:
            log.warning("RemoteOK rate limited (429)")
            return ScrapeResult(source="remoteok", jobs=[], errors=["Rate limited (429)"])

        if response.status_code != 200:
            log.error("RemoteOK returned status %d", response.status_code)
            return ScrapeResult(source="remoteok", jobs=[], errors=[f"HTTP {response.status_code}"])

        try:
            data = response.json()
        except Exception as e:
            log.error("Failed to parse RemoteOK JSON: %s", e)
            return ScrapeResult(source="remoteok", jobs=[], errors=[f"JSON parse error: {e}"])

        if not isinstance(data, list) or len(data) < 2:
            return ScrapeResult(source="remoteok", jobs=[])

        # First element is metadata — skip it
        raw_jobs = data[1:]

        jobs: list[Job] = []
        for item in raw_jobs:
            try:
                job = self._map_job(item)
                if job:
                    jobs.append(job)
            except Exception as e:
                log.debug("Skipping job: %s", e)
                continue

        jobs = filter_jobs(jobs, search_term=ctx.search_term, hours_old=ctx.hours_old, is_remote=ctx.is_remote)

        log.info("RemoteOK: returning %d jobs", len(jobs))
        return ScrapeResult(source="remoteok", jobs=jobs)

    def _map_job(self, item: dict) -> Job | None:
        """Map a single RemoteOK API entry to a Job."""
        job_id = item.get("id")
        title = item.get("position")
        if not job_id or not title:
            return None

        company = item.get("company")
        rok_id = f"rok-{job_id}"
        job_url = f"https://remoteok.com/remote-jobs/{job_id}"
        apply_url = item.get("apply_url") or item.get("url") or None

        # Location — parse raw string, override arrangement to REMOTE
        raw_location = item.get("location") or ""
        loc_parts = parse_location(raw_location)
        location = Location(
            city=loc_parts["city"],
            state=loc_parts["state"],
            country=loc_parts["country"],
            raw=raw_location or None,
            work_arrangement=WorkArrangement.REMOTE,
        )

        # Description
        description_html = item.get("description") or ""
        description = html_to_markdown(description_html) if description_html else ""

        # Date
        date_posted = _parse_date(item.get("date"))

        # Compensation — structured fields first, fallback to text extraction
        compensation = _parse_compensation(item)
        if compensation is None and description:
            min_val, max_val, currency = extract_salary_from_text(description)
            if min_val is not None or max_val is not None:
                compensation = Compensation(min_amount=min_val, max_amount=max_val, currency=currency)

        return Job(
            id=rok_id,
            source="remoteok",
            title=title,
            company=company,
            url=job_url,
            url_direct=apply_url,
            location=location,
            description=description,
            compensation=compensation,
            date_posted=date_posted,
            is_remote=True,
        )
