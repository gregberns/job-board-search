"""Ashby ATS scraper — fetches jobs from Ashby job boards."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from jbs.models import Compensation, Job, Location, WorkArrangement
from jbs.scrapers import register
from jbs.scrapers.ats_base import ATSBoardScraper, BoardNotFoundError
from jbs.scrapers.base import PluginMeta, ScrapeContext
from jbs.util import create_session, extract_salary_from_text, html_to_markdown, parse_location

logger = logging.getLogger(__name__)

API_URL = "https://api.ashbyhq.com/posting-api/job-board"

# Control chars to strip (keep \n \r \t)
_CTRL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_INTERVAL_MAP = {
    "YEAR": "yearly",
    "MONTH": "monthly",
    "WEEK": "weekly",
    "DAY": "daily",
    "HOUR": "hourly",
}

_EMPLOYMENT_TYPE_MAP = {
    "fulltime": "full-time",
    "parttime": "part-time",
    "contract": "contract",
    "contractor": "contract",
    "temporary": "contract",
    "temp": "contract",
    "intern": "intern",
    "internship": "intern",
}


def _normalize_employment_type(raw: str) -> str | None:
    key = raw.lower().replace(" ", "").replace("-", "")
    return _EMPLOYMENT_TYPE_MAP.get(key)


def _extract_compensation(raw: dict) -> Compensation | None:
    """Extract structured compensation from Ashby compensationTiers."""
    tiers = raw.get("compensationTiers")
    if tiers and isinstance(tiers, list):
        for tier in tiers:
            components = tier.get("components")
            if not components or not isinstance(components, list):
                continue
            for comp in components:
                min_val = comp.get("minValue")
                max_val = comp.get("maxValue")
                if min_val is not None or max_val is not None:
                    currency = comp.get("currencyCode") or "USD"
                    interval_str = (comp.get("interval") or "").upper()
                    return Compensation(
                        min_amount=float(min_val) if min_val is not None else None,
                        max_amount=float(max_val) if max_val is not None else None,
                        currency=currency,
                        interval=_INTERVAL_MAP.get(interval_str, "yearly"),
                    )

    # Top-level compensation field (alternate structure)
    compensation_field = raw.get("compensation")
    if compensation_field and isinstance(compensation_field, dict):
        min_val = compensation_field.get("minValue")
        max_val = compensation_field.get("maxValue")
        if min_val is not None or max_val is not None:
            currency = compensation_field.get("currencyCode") or "USD"
            interval_str = (compensation_field.get("interval") or "").upper()
            return Compensation(
                min_amount=float(min_val) if min_val is not None else None,
                max_amount=float(max_val) if max_val is not None else None,
                currency=currency,
                interval=_INTERVAL_MAP.get(interval_str, "yearly"),
            )

    # Fall back to salary summary text
    salary_summary = raw.get("scrapeableCompensationSalarySummary") or ""
    if salary_summary:
        min_amt, max_amt, cur = extract_salary_from_text(salary_summary)
        if min_amt is not None or max_amt is not None:
            return Compensation(min_amount=min_amt, max_amount=max_amt, currency=cur)

    return None


def _parse_date(date_str: str | None):
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


def _map_job(raw: dict, token: str, company_name: str) -> Job | None:
    """Map a single Ashby job dict to a Job model."""
    title = raw.get("title")
    if not title:
        return None

    job_id = raw.get("id")
    id_str = f"ashby-{job_id}" if job_id else f"ashby-{token}-unknown"

    job_url = raw.get("jobUrl") or ""
    url_direct = raw.get("applyUrl") or None

    # Location
    location_str = raw.get("location") or ""
    loc_data = parse_location(location_str)
    is_remote = loc_data["work_arrangement"] == "remote"

    # Check isRemote / workplaceType fields
    if raw.get("isRemote"):
        is_remote = True
    workplace_type = (raw.get("workplaceType") or "").lower()
    if workplace_type in ("remote", "fully remote"):
        is_remote = True

    work_arrangement = WorkArrangement.REMOTE if is_remote else WorkArrangement.UNKNOWN
    location = Location(
        city=loc_data["city"],
        state=loc_data["state"],
        country=loc_data["country"],
        raw=location_str or None,
        work_arrangement=work_arrangement,
    )

    # Description
    description_html = raw.get("descriptionHtml") or ""
    description_plain = raw.get("descriptionPlain") or ""
    if description_html:
        description = html_to_markdown(description_html)
    elif description_plain:
        description = description_plain.strip()
    else:
        description = None

    # Date posted
    date_posted = _parse_date(raw.get("publishedAt"))

    # Employment type
    employment_type = raw.get("employmentType") or ""
    job_type = _normalize_employment_type(employment_type) if employment_type else None

    # Department / team
    dept = raw.get("department") or ""
    team = raw.get("team") or ""
    parts = [p for p in (dept, team) if p]
    job_function = ", ".join(parts) if parts else None

    # Compensation
    compensation = _extract_compensation(raw)
    if compensation is None and description:
        min_amt, max_amt, cur = extract_salary_from_text(description)
        if min_amt is not None or max_amt is not None:
            compensation = Compensation(min_amount=min_amt, max_amount=max_amt, currency=cur)

    return Job(
        id=id_str,
        source="ashby",
        title=title,
        company=company_name,
        url=job_url,
        url_direct=url_direct,
        location=location,
        description=description,
        date_posted=date_posted,
        job_type=job_type,
        job_function=job_function,
        compensation=compensation,
        is_remote=is_remote,
        board_token=token,
    )


@register
class AshbyScraper(ATSBoardScraper):
    meta = PluginMeta(name="ashby", id_prefix="ashby", requires_tokens=True)
    max_workers = 10
    min_interval = 0.0

    def __init__(self):
        self.session = create_session()

    def fetch_and_map(self, token: str, ctx: ScrapeContext) -> list[Job]:
        """Fetch all jobs from an Ashby board and map to Job objects."""
        try:
            resp = self.session.get(
                f"{API_URL}/{token}",
                params={"includeCompensation": "true"},
                timeout=30,
            )
        except Exception as e:
            logger.warning("Ashby board '%s': request failed: %s", token, e)
            return []

        if resp.status_code == 404:
            raise BoardNotFoundError(token)
        if resp.status_code in (429, 403):
            logger.warning("Ashby board '%s': received %d, skipping", token, resp.status_code)
            return []

        try:
            resp.raise_for_status()
        except Exception as e:
            logger.warning("Ashby board '%s': HTTP error: %s", token, e)
            return []

        # Sanitize control characters that break json.loads()
        raw_text = _CTRL_CHAR_RE.sub(" ", resp.text)

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as e:
            logger.warning("Ashby board '%s': JSON parse error: %s", token, e)
            return []

        jobs_data = data.get("jobs", [])
        if not jobs_data:
            return []

        company_name = data.get("organizationName") or token.replace("-", " ").title()

        results = []
        for raw in jobs_data:
            job = _map_job(raw, token, company_name)
            if job is not None:
                results.append(job)
        return results
