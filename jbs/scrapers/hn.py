"""HN Who's Hiring scraper — Algolia API, pipe-delimited comment parsing."""

from __future__ import annotations

import html
import logging
import re
import time
from datetime import datetime, timezone

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

logger = logging.getLogger("jbs.hn")

ALGOLIA_BASE = "https://hn.algolia.com/api/v1"
HN_ITEM_URL = "https://news.ycombinator.com/item?id={}"


@register
class HNScraper(ScraperPlugin):
    meta = PluginMeta(name="hn", id_prefix="hn", requires_tokens=False)

    def scrape(self, ctx: ScrapeContext) -> ScrapeResult:
        """Search Algolia for latest 'Ask HN: Who is hiring' thread, parse comments."""
        t0 = time.monotonic()
        session = create_session()

        # 1. Find the latest thread
        thread_id = self._find_latest_thread(session)
        if not thread_id:
            return ScrapeResult(
                source="hn", jobs=[], errors=["Could not find latest Who is Hiring thread"],
                elapsed_seconds=time.monotonic() - t0,
            )

        # 2. Fetch thread comments
        try:
            resp = session.get(f"{ALGOLIA_BASE}/items/{thread_id}", timeout=60)
        except Exception as exc:
            return ScrapeResult(
                source="hn", jobs=[], errors=[f"Network error fetching thread {thread_id}: {exc}"],
                elapsed_seconds=time.monotonic() - t0,
            )

        if not resp.ok:
            return ScrapeResult(
                source="hn", jobs=[], errors=[f"HTTP {resp.status_code} fetching thread {thread_id}"],
                elapsed_seconds=time.monotonic() - t0,
            )

        try:
            data = resp.json()
        except Exception as exc:
            return ScrapeResult(
                source="hn", jobs=[], errors=[f"JSON parse error: {exc}"],
                elapsed_seconds=time.monotonic() - t0,
            )

        children = data.get("children", [])
        if not children:
            return ScrapeResult(
                source="hn", jobs=[],
                elapsed_seconds=time.monotonic() - t0,
            )

        # 3. Parse each top-level comment
        jobs: list[Job] = []
        for comment in children:
            job = _parse_comment(comment)
            if job is not None:
                jobs.append(job)

        # 4. Client-side filtering
        jobs = filter_jobs(jobs, search_term=ctx.search_term, hours_old=ctx.hours_old, is_remote=ctx.is_remote)

        # 5. Limit results
        jobs = jobs[: ctx.results_wanted]

        logger.info("HN: parsed %d jobs from thread %s", len(jobs), thread_id)
        return ScrapeResult(
            source="hn", jobs=jobs,
            elapsed_seconds=time.monotonic() - t0,
        )

    @staticmethod
    def _find_latest_thread(session) -> str | None:
        """Use Algolia search_by_date to find the most recent 'Who is Hiring' thread."""
        url = f"{ALGOLIA_BASE}/search_by_date"
        params = {
            "query": '"who is hiring"',
            "tags": "story,author_whoishiring",
            "hitsPerPage": 1,
        }
        try:
            resp = session.get(url, params=params, timeout=60)
        except Exception as exc:
            logger.error("Network error searching for HN thread: %s", exc)
            return None

        if not resp.ok:
            logger.error("Algolia search failed: HTTP %d", resp.status_code)
            return None

        try:
            hits = resp.json().get("hits", [])
        except Exception:
            return None

        if hits:
            return str(hits[0].get("objectID", ""))
        return None


# ---------------------------------------------------------------------------
# Comment parsing (module-level for testability)
# ---------------------------------------------------------------------------

def _parse_comment(comment: dict) -> Job | None:
    """Parse a single top-level HN comment into a Job."""
    comment_id = comment.get("id")
    text_html = comment.get("text") or ""

    if not text_html.strip():
        return None

    text_decoded = html.unescape(text_html)

    # Extract URLs before stripping tags
    urls_in_text = re.findall(r'https?://[^\s<>"\']+', text_decoded)

    # Plain text: replace tags with newlines
    text_plain = re.sub(r"<[^>]+>", "\n", text_decoded).strip()
    lines = [line.strip() for line in text_plain.split("\n") if line.strip()]
    if not lines:
        return None

    first_line = lines[0]

    # ---- Parse pipe-delimited header ----
    company_name: str | None = None
    title: str | None = None
    location: Location | None = None
    is_remote: bool = False
    compensation: Compensation | None = None
    job_url: str | None = None

    if "|" in first_line:
        segments = [seg.strip() for seg in first_line.split("|")]

        company_name = segments[0] if segments[0] else None

        for seg in segments[1:]:
            if not seg:
                continue

            seg_lower = seg.lower()

            # URL
            url_match = re.search(r"https?://\S+", seg)
            if url_match:
                if not job_url:
                    job_url = url_match.group(0)
                continue

            # Salary ($xxx,xxx or $xxxk)
            if re.search(r"\$[\d,]+", seg):
                min_amt, max_amt, currency = extract_salary_from_text(seg)
                if min_amt is not None or max_amt is not None:
                    compensation = Compensation(min_amount=min_amt, max_amount=max_amt, currency=currency)
                continue

            # Remote / onsite / hybrid keywords
            has_remote_kw = bool(re.search(r"\b(remote|onsite|on-site|hybrid)\b", seg, re.IGNORECASE))
            if has_remote_kw:
                if re.search(r"\bremote\b", seg_lower):
                    is_remote = True
                # Try location from remaining text
                loc_text = re.sub(r"\b(remote|onsite|on-site|hybrid)\b", "", seg, flags=re.IGNORECASE).strip()
                loc_text = re.sub(r"^\s*[/|,\-or]+\s*", "", loc_text).strip()
                loc_text = re.sub(r"\s*[/|,\-or]+\s*$", "", loc_text).strip()
                if loc_text and location is None:
                    loc = parse_location(loc_text)
                    if loc["city"] or loc["state"]:
                        location = Location(
                            city=loc["city"], state=loc["state"], country=loc["country"],
                            work_arrangement=WorkArrangement(loc["work_arrangement"]),
                        )
                continue

            # Location or title — require comma or state for location confidence
            if "," in seg or re.search(r"\b[A-Z]{2}\b", seg):
                loc = parse_location(seg)
                if loc["work_arrangement"] == "remote":
                    is_remote = True
                if loc["city"] or loc["state"]:
                    if location is None:
                        location = Location(
                            city=loc["city"], state=loc["state"], country=loc["country"],
                            work_arrangement=WorkArrangement(loc["work_arrangement"]),
                        )
                    continue
            if not title and seg:
                title = seg
    else:
        company_name = first_line[:80]

    # Fallback URL
    if not job_url and urls_in_text:
        job_url = urls_in_text[0]
    if not job_url:
        job_url = HN_ITEM_URL.format(comment_id)

    # Description
    description = html_to_markdown(text_html)

    # Date
    date_posted = None
    created_at = comment.get("created_at_i")
    if isinstance(created_at, (int, float)):
        try:
            date_posted = datetime.fromtimestamp(created_at, tz=timezone.utc).date()
        except (OSError, ValueError, OverflowError):
            pass

    if date_posted is None:
        created_at_str = comment.get("created_at")
        if isinstance(created_at_str, str):
            try:
                date_posted = datetime.fromisoformat(
                    created_at_str.replace("Z", "+00:00")
                ).date()
            except (ValueError, TypeError):
                pass

    # Fallback salary from first line
    if compensation is None:
        min_amt, max_amt, currency = extract_salary_from_text(first_line)
        if min_amt is not None or max_amt is not None:
            compensation = Compensation(min_amount=min_amt, max_amount=max_amt, currency=currency)

    # Fallback title
    if not title:
        title = f"{company_name} (HN Hiring)" if company_name else "HN Who is Hiring"

    # Default location
    if location is None:
        location = Location(
            work_arrangement=WorkArrangement.REMOTE if is_remote else WorkArrangement.UNKNOWN,
        )

    return Job(
        id=f"hn-{comment_id}",
        source="hn",
        title=title,
        company=company_name,
        url=job_url,
        location=location,
        compensation=compensation,
        description=description,
        date_posted=date_posted,
        is_remote=is_remote,
    )
