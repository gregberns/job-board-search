"""Greenhouse ATS scraper — two-pass fetch (metadata then detail)."""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta

from jbs.models import Compensation, Job, Location, WorkArrangement
from jbs.scrapers import register
from jbs.scrapers.ats_base import ATSBoardScraper, BoardNotFoundError
from jbs.scrapers.base import PluginMeta, ScrapeContext
from jbs.util import create_session, extract_salary_from_text, parse_location

logger = logging.getLogger(__name__)

BASE_URL = "https://boards-api.greenhouse.io/v1/boards"


def _parse_date(date_str: str | None) -> date | None:
    """Parse ISO 8601 date string to date object."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str).date()
    except (ValueError, TypeError):
        pass
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _map_job(raw: dict, token: str) -> Job | None:
    """Map a Greenhouse job dict to a Job model."""
    title = raw.get("title")
    if not title:
        return None

    job_id = raw.get("id")
    id_str = f"gh-{job_id}" if job_id else f"gh-{token}-unknown"

    job_url = raw.get("absolute_url") or ""
    company_name = raw.get("company_name")

    # Location
    location_data = raw.get("location")
    if isinstance(location_data, dict):
        location_str = location_data.get("name") or ""
    elif isinstance(location_data, str):
        location_str = location_data
    else:
        location_str = ""

    loc_data = parse_location(location_str)
    is_remote = loc_data["work_arrangement"] == "remote"
    work_arrangement = WorkArrangement.REMOTE if is_remote else WorkArrangement.UNKNOWN
    location = Location(
        city=loc_data["city"],
        state=loc_data["state"],
        country=loc_data["country"],
        raw=location_str or None,
        work_arrangement=work_arrangement,
    )

    # Description: stored as HTML (cleanup happens in enrichment stage 0)
    description = raw.get("content") or None

    # Date posted: prefer first_published
    date_posted = _parse_date(raw.get("first_published")) or _parse_date(raw.get("updated_at"))

    # Departments -> job_function
    departments = raw.get("departments")
    job_function = None
    if departments and isinstance(departments, list):
        dept_names = [
            d.get("name") for d in departments if isinstance(d, dict) and d.get("name")
        ]
        if dept_names:
            job_function = ", ".join(dept_names)

    # Compensation: extract from description text (no structured comp in public API)
    compensation = None
    if description:
        min_amt, max_amt, cur = extract_salary_from_text(description)
        if min_amt is not None or max_amt is not None:
            compensation = Compensation(min_amount=min_amt, max_amount=max_amt, currency=cur)

    return Job(
        id=id_str,
        source="greenhouse",
        title=title,
        company=company_name,
        url=job_url,
        location=location,
        description=description,
        date_posted=date_posted,
        job_function=job_function,
        compensation=compensation,
        is_remote=is_remote,
        board_token=token,
    )


@register
class GreenhouseScraper(ATSBoardScraper):
    meta = PluginMeta(name="greenhouse", id_prefix="gh", requires_tokens=True)
    max_workers = 10
    min_interval = 0.05  # 50ms between detail fetches

    def __init__(self):
        self.session = create_session()

    def fetch_and_map(self, token: str, ctx: ScrapeContext) -> list[Job]:
        """Two-pass: lightweight metadata first, full content only for matches."""
        # --- Pass 1: lightweight listing ---
        try:
            resp = self.session.get(f"{BASE_URL}/{token}/jobs", timeout=30)
        except Exception as e:
            logger.warning("Greenhouse board '%s': request failed: %s", token, e)
            return []

        if resp.status_code == 404:
            raise BoardNotFoundError(token)
        if resp.status_code in (429, 403):
            logger.warning("Greenhouse board '%s': received %d, skipping", token, resp.status_code)
            return []

        try:
            resp.raise_for_status()
        except Exception as e:
            logger.warning("Greenhouse board '%s': HTTP error: %s", token, e)
            return []

        data = resp.json()
        jobs = data.get("jobs", [])
        if not jobs:
            return []

        # --- Pre-filter on lightweight data ---
        search_term = ctx.search_term.lower() if ctx.search_term else None
        cutoff_date = None
        if ctx.hours_old:
            cutoff_date = date.today() - timedelta(hours=ctx.hours_old)

        candidates = []
        for job in jobs:
            if search_term:
                title = (job.get("title") or "").lower()
                if search_term not in title:
                    continue
            if cutoff_date:
                first_published = job.get("first_published")
                if first_published:
                    posted = _parse_date(first_published)
                    if posted and posted < cutoff_date:
                        continue
            candidates.append(job)

        if not candidates:
            return []

        # --- Pass 2: fetch full details for matching jobs ---
        results = []
        for job in candidates:
            job_id = job.get("id")
            if not job_id:
                mapped = _map_job(job, token)
                if mapped:
                    results.append(mapped)
                continue

            time.sleep(self.min_interval)
            try:
                detail_resp = self.session.get(
                    f"{BASE_URL}/{token}/jobs/{job_id}",
                    params={"questions": "true"},
                    timeout=30,
                )
                if detail_resp.ok:
                    detail = detail_resp.json()
                    mapped = _map_job(detail, token)
                else:
                    logger.debug(
                        "Greenhouse job %s from '%s': detail returned %d",
                        job_id, token, detail_resp.status_code,
                    )
                    mapped = _map_job(job, token)
            except Exception as e:
                logger.debug(
                    "Greenhouse job %s from '%s': detail failed: %s",
                    job_id, token, e,
                )
                mapped = _map_job(job, token)

            if mapped:
                results.append(mapped)

        return results
