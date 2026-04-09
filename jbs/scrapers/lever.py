"""Lever ATS scraper — fetches jobs from Lever job boards."""

from __future__ import annotations

import logging
from datetime import datetime

from jbs.models import Compensation, Job, Location, WorkArrangement
from jbs.scrapers import register
from jbs.scrapers.ats_base import ATSBoardScraper, BoardNotFoundError
from jbs.scrapers.base import PluginMeta, ScrapeContext
from jbs.util import create_session, extract_salary_from_text, html_to_markdown, parse_location

logger = logging.getLogger(__name__)

API_URL = "https://api.lever.co/v0/postings"

_COMMITMENT_MAP = {
    "permanent": "full-time",
    "full-time": "full-time",
    "fulltime": "full-time",
    "part-time": "part-time",
    "parttime": "part-time",
    "intern": "intern",
    "internship": "intern",
    "contract": "contract",
    "contractor": "contract",
    "temporary": "contract",
}


def _parse_commitment(commitment: str) -> str | None:
    if not commitment:
        return None
    return _COMMITMENT_MAP.get(commitment.lower().strip())


def _map_job(raw: dict, token: str) -> Job | None:
    """Map a single Lever posting dict to a Job model."""
    title = raw.get("text")
    if not title:
        return None

    posting_id = raw.get("id", "")
    id_str = f"lever-{posting_id}"

    job_url = raw.get("hostedUrl") or ""
    url_direct = raw.get("applyUrl") or None

    # Date from epoch milliseconds
    created_at = raw.get("createdAt")
    date_posted = None
    if created_at:
        date_posted = datetime.fromtimestamp(created_at / 1000).date()

    # Location from categories
    categories = raw.get("categories", {})
    location_str = categories.get("location", "")
    loc_data = parse_location(location_str)
    is_remote = loc_data["work_arrangement"] == "remote"

    # Check workplaceType
    workplace = raw.get("workplaceType", "")
    if workplace and workplace.lower() == "remote":
        is_remote = True

    # Prefer country field from response over parsed
    country = raw.get("country") or loc_data["country"]

    work_arrangement = WorkArrangement.REMOTE if is_remote else WorkArrangement.UNKNOWN
    location = Location(
        city=loc_data["city"],
        state=loc_data["state"],
        country=country,
        raw=location_str or None,
        work_arrangement=work_arrangement,
    )

    # Description: prefer descriptionBody, fall back to description (HTML)
    desc_body = raw.get("descriptionBody")
    desc_html = raw.get("description", "")
    description = ""
    if desc_body:
        description = html_to_markdown(desc_body)
    elif desc_html:
        description = html_to_markdown(desc_html)

    # Append structured list sections
    for lst in raw.get("lists", []):
        section_text = lst.get("text", "")
        section_content = lst.get("content", "")
        if section_text:
            description += f"\n\n## {section_text}\n"
        if section_content:
            description += html_to_markdown(section_content)

    # Compensation: try additional text first, then description
    additional = raw.get("additionalPlain") or raw.get("additional", "")
    compensation = None
    if additional:
        min_val, max_val, currency = extract_salary_from_text(additional)
        if min_val is not None or max_val is not None:
            compensation = Compensation(min_amount=min_val, max_amount=max_val, currency=currency)
    if compensation is None and description:
        min_val, max_val, currency = extract_salary_from_text(description)
        if min_val is not None or max_val is not None:
            compensation = Compensation(min_amount=min_val, max_amount=max_val, currency=currency)

    # salaryRange structured field
    if compensation is None:
        salary_range = raw.get("salaryRange")
        if salary_range and isinstance(salary_range, dict):
            sr_min = salary_range.get("min")
            sr_max = salary_range.get("max")
            if sr_min is not None or sr_max is not None:
                sr_currency = salary_range.get("currency", "USD")
                sr_interval = salary_range.get("interval", "yearly")
                compensation = Compensation(
                    min_amount=float(sr_min) if sr_min is not None else None,
                    max_amount=float(sr_max) if sr_max is not None else None,
                    currency=sr_currency,
                    interval=sr_interval,
                )

    # Job type from commitment
    commitment = categories.get("commitment", "")
    job_type = _parse_commitment(commitment)

    # Job function from team or department
    job_function = categories.get("team") or categories.get("department") or None

    # Company name from token slug
    company_name = token.replace("-", " ").title()

    return Job(
        id=id_str,
        source="lever",
        title=title,
        company=company_name,
        url=job_url,
        url_direct=url_direct,
        location=location,
        description=description or None,
        date_posted=date_posted,
        job_type=job_type,
        job_function=job_function,
        compensation=compensation,
        is_remote=is_remote,
        board_token=token,
    )


@register
class LeverScraper(ATSBoardScraper):
    meta = PluginMeta(name="lever", id_prefix="lever", requires_tokens=True)
    max_workers = 2
    min_interval = 0.5  # 500ms rate limit

    def __init__(self):
        self.session = create_session()

    def fetch_and_map(self, token: str, ctx: ScrapeContext) -> list[Job]:
        """GET https://api.lever.co/v0/postings/{token} — returns list of Job."""
        try:
            resp = self.session.get(
                f"{API_URL}/{token}",
                params={"mode": "json"},
                timeout=30,
            )
        except Exception as e:
            logger.warning("Lever board '%s': request failed: %s", token, e)
            return []

        if resp.status_code == 404:
            raise BoardNotFoundError(token)
        if resp.status_code in (429, 403):
            logger.warning("Lever board '%s': received %d, skipping", token, resp.status_code)
            return []

        try:
            resp.raise_for_status()
        except Exception as e:
            logger.warning("Lever board '%s': HTTP error: %s", token, e)
            return []

        try:
            data = resp.json()
        except Exception as e:
            logger.warning("Lever board '%s': JSON parse error: %s", token, e)
            return []

        if not isinstance(data, list):
            return []

        results = []
        for raw in data:
            job = _map_job(raw, token)
            if job is not None:
                results.append(job)
        return results
