"""HN token discovery pipeline. Extracts ATS tokens from HN job URLs,
discovers careers pages, and detects ATS embeds."""

from __future__ import annotations

import re
import time
import logging
from urllib.parse import urlparse

from jbs.store import Store
from jbs.util import create_session, normalize_company_name

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ATS URL patterns
# ---------------------------------------------------------------------------

_ATS_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'jobs\.ashbyhq\.com/([^/?#]+)'), 'ashby'),
    (re.compile(r'boards\.greenhouse\.io/([^/?#]+)'), 'greenhouse'),
    (re.compile(r'job-boards\.greenhouse\.io/([^/?#]+)'), 'greenhouse'),
    (re.compile(r'jobs\.lever\.co/([^/?#]+)'), 'lever'),
]

_GRNH_SHORT_RE = re.compile(r'grnh\.se/')

# ---------------------------------------------------------------------------
# Dead-end URL patterns (not worth probing)
# ---------------------------------------------------------------------------

_DEAD_END_DOMAINS = frozenset({
    'linkedin.com', 'www.linkedin.com',
    'youtube.com', 'www.youtube.com', 'youtu.be',
    'twitter.com', 'x.com',
    'github.com',
    'docs.google.com', 'drive.google.com',
    'medium.com',
    'notion.so', 'notion.site',
    'substack.com',
})

_DEAD_END_EXTENSIONS = frozenset({'.pdf', '.png', '.jpg', '.jpeg', '.gif'})

# ---------------------------------------------------------------------------
# Careers page indicators
# ---------------------------------------------------------------------------

_CAREERS_PATH_KEYWORDS = frozenset({
    'careers', 'jobs', 'hiring', 'join', 'open-positions',
    'join-us', 'work-with-us', 'openings',
})

_CAREERS_PROBE_PATHS = [
    '/careers', '/jobs', '/join', '/about/careers', '/company/careers',
    '/work-with-us', '/hiring', '/open-positions', '/join-us',
]

# ---------------------------------------------------------------------------
# ATS embed patterns (Phase 3)
# ---------------------------------------------------------------------------

_ATS_EMBED_PATTERNS: list[tuple[re.Pattern, str]] = [
    # iframes
    (re.compile(r'<iframe[^>]+src=["\']https?://boards\.greenhouse\.io/([^/?#"\']+)', re.I), 'greenhouse'),
    (re.compile(r'<iframe[^>]+src=["\']https?://job-boards\.greenhouse\.io/([^/?#"\']+)', re.I), 'greenhouse'),
    (re.compile(r'<iframe[^>]+src=["\']https?://jobs\.lever\.co/([^/?#"\']+)', re.I), 'lever'),
    (re.compile(r'<iframe[^>]+src=["\']https?://jobs\.ashbyhq\.com/([^/?#"\']+)', re.I), 'ashby'),
    # Greenhouse embed div + script
    (re.compile(r'id=["\']grnhse_app["\'][^>]*data-url=["\']https?://boards\.greenhouse\.io/([^/?#"\']+)', re.I), 'greenhouse'),
    (re.compile(r'<script[^>]+src=["\']https?://boards\.greenhouse\.io/embed/job_board/js\?for=([^&"\']+)', re.I), 'greenhouse'),
    # Lever widget script
    (re.compile(r'<script[^>]+src=["\']https?://jobs\.lever\.co/([^/?#"\']+)/embed', re.I), 'lever'),
    # Links to ATS job boards
    (re.compile(r'href=["\']https?://boards\.greenhouse\.io/([^/?#"\']+)', re.I), 'greenhouse'),
    (re.compile(r'href=["\']https?://job-boards\.greenhouse\.io/([^/?#"\']+)', re.I), 'greenhouse'),
    (re.compile(r'href=["\']https?://jobs\.lever\.co/([^/?#"\']+)', re.I), 'lever'),
    (re.compile(r'href=["\']https?://jobs\.ashbyhq\.com/([^/?#"\']+)', re.I), 'ashby'),
]


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def match_ats_url(url: str) -> tuple[str, str] | None:
    """Match a URL against known ATS patterns.

    Returns (platform, token) or None.
    """
    for pattern, platform in _ATS_PATTERNS:
        m = pattern.search(url)
        if m:
            return platform, m.group(1)
    return None


def is_dead_end(url: str) -> bool:
    """Check if a URL is a dead-end (LinkedIn, YouTube, etc.)."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    domain = parsed.hostname or ''
    # Strip 'www.' for matching
    bare = domain.removeprefix('www.')
    if domain in _DEAD_END_DOMAINS or bare in _DEAD_END_DOMAINS:
        return True
    path = parsed.path.lower()
    return any(path.endswith(ext) for ext in _DEAD_END_EXTENSIONS)


def url_has_careers_path(url: str) -> bool:
    """Check if URL path contains careers-related keywords."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    parts = parsed.path.lower().strip('/').split('/')
    return any(p in _CAREERS_PATH_KEYWORDS for p in parts)


def detect_ats_in_html(html: str) -> tuple[str, str] | None:
    """Scan HTML for ATS embeds (iframes, scripts, links).

    Returns (platform, token) or None.
    """
    for pattern, platform in _ATS_EMBED_PATTERNS:
        m = pattern.search(html)
        if m:
            return platform, m.group(1)
    return None


# ---------------------------------------------------------------------------
# Phase 1: Harvest ATS tokens from HN URLs
# ---------------------------------------------------------------------------

def harvest_ats_tokens(store: Store, verbose: bool = False) -> dict:
    """Extract ATS tokens from HN job URLs via regex matching."""
    rows = store.get_unprocessed_hn_urls()
    if not rows:
        log.info("Phase 1: No unprocessed HN URLs")
        return {"total": 0, "ats_found": 0, "by_platform": {}}

    session = create_session()
    ats_found = 0
    by_platform: dict[str, int] = {}

    for row in rows:
        url = row["job_url"]
        company_raw = row.get("company_raw")
        hn_job_id = row["id"]

        # Check for grnh.se short URLs — resolve redirect
        if _GRNH_SHORT_RE.search(url):
            try:
                resp = session.head(url, allow_redirects=True, timeout=10)
                url = resp.url
            except Exception as e:
                log.debug("Failed to resolve %s: %s", url, e)

        result = match_ats_url(url)
        if result:
            platform, token = result
            company_name = normalize_company_name(company_raw) if company_raw else None
            store.add_token(platform, token, company_name=company_raw)
            store.upsert_hn_career_page(
                hn_job_id,
                company_name=company_raw,
                company_url=url,
                ats_platform=platform,
                ats_token=token,
                page_type='ats',
                status='scraped',
            )
            ats_found += 1
            by_platform[platform] = by_platform.get(platform, 0) + 1
            if verbose:
                log.info("  ATS: %s/%s (%s)", platform, token, company_raw)
        else:
            store.upsert_hn_career_page(
                hn_job_id,
                company_name=company_raw,
                company_url=url,
                status='pending',
            )

    log.info("Phase 1: Found %d ATS tokens in %d URLs", ats_found, len(rows))
    for p, c in sorted(by_platform.items()):
        log.info("  %s: %d new", p, c)

    return {"total": len(rows), "ats_found": ats_found, "by_platform": by_platform}


# ---------------------------------------------------------------------------
# Phase 2: Careers page discovery
# ---------------------------------------------------------------------------

def discover_careers_pages(store: Store, verbose: bool = False) -> dict:
    """Discover careers pages from pending HN URLs."""
    pending = store.get_hn_pages_by_status('pending')
    if not pending:
        log.info("Phase 2: No pending URLs to process")
        return {"total": 0, "discovered": 0, "dead_ends": 0}

    session = create_session()
    discovered = 0
    dead_ends = 0

    for page in pending:
        url = page.get("company_url")
        hn_job_id = page["hn_job_id"]

        if not url:
            store.update_hn_career_page(hn_job_id, status='skipped')
            continue

        # Dead-end classification
        if is_dead_end(url):
            store.update_hn_career_page(
                hn_job_id, page_type='dead_end', status='skipped',
            )
            dead_ends += 1
            continue

        # URL already points to a careers page
        if url_has_careers_path(url):
            store.update_hn_career_page(
                hn_job_id, careers_url=url, status='discovered',
            )
            discovered += 1
            continue

        # Probe common careers paths
        careers_url = _probe_careers_paths(session, url)
        if careers_url:
            store.update_hn_career_page(
                hn_job_id, careers_url=careers_url, status='discovered',
            )
            discovered += 1
            if verbose:
                log.info("  Probed: %s -> %s", url, careers_url)
            continue

        # Scan homepage for careers links
        careers_url = _scan_homepage_links(session, url)
        if careers_url:
            store.update_hn_career_page(
                hn_job_id, careers_url=careers_url, status='discovered',
            )
            discovered += 1
            if verbose:
                log.info("  Link scan: %s -> %s", url, careers_url)
            continue

        # No careers page found — leave as pending
        store.update_hn_career_page(hn_job_id, last_checked=_now_iso())

    log.info(
        "Phase 2: Processed %d URLs — %d careers pages found, %d dead ends",
        len(pending), discovered, dead_ends,
    )
    return {"total": len(pending), "discovered": discovered, "dead_ends": dead_ends}


def _probe_careers_paths(session, base_url: str) -> str | None:
    """HEAD-probe common careers paths on a domain. Returns first 200 OK URL."""
    try:
        parsed = urlparse(base_url)
        origin = f"{parsed.scheme}://{parsed.hostname}"
        if parsed.port and parsed.port not in (80, 443):
            origin += f":{parsed.port}"
    except Exception:
        return None

    for path in _CAREERS_PROBE_PATHS:
        probe_url = origin + path
        try:
            resp = session.head(probe_url, allow_redirects=True, timeout=10)
            if resp.status_code == 200:
                return probe_url
        except Exception:
            continue
        time.sleep(0.5)

    return None


def _scan_homepage_links(session, url: str) -> str | None:
    """GET a homepage and scan <a> tags for careers-related links."""
    try:
        resp = session.get(url, timeout=10)
        if resp.status_code != 200:
            return None
    except Exception:
        return None

    # Simple regex scan for <a href="..."> with careers keywords
    link_re = re.compile(r'<a\s[^>]*href=["\']([^"\']+)["\']', re.I)
    for m in link_re.finditer(resp.text):
        href = m.group(1)
        if url_has_careers_path(href):
            # Resolve relative URLs
            if href.startswith('/'):
                parsed = urlparse(url)
                origin = f"{parsed.scheme}://{parsed.hostname}"
                if parsed.port and parsed.port not in (80, 443):
                    origin += f":{parsed.port}"
                return origin + href
            if href.startswith('http'):
                return href
    return None


# ---------------------------------------------------------------------------
# Phase 3: ATS detection on careers pages
# ---------------------------------------------------------------------------

def detect_ats_on_careers(store: Store, verbose: bool = False) -> dict:
    """Scan discovered careers pages for ATS embeds."""
    pages = store.get_hn_pages_by_status('discovered')
    if not pages:
        log.info("Phase 3: No discovered careers pages to scan")
        return {"total": 0, "ats_found": 0, "by_platform": {}}

    session = create_session()
    ats_found = 0
    by_platform: dict[str, int] = {}
    static_html = 0
    spa = 0

    for page in pages:
        careers_url = page.get("careers_url") or page.get("company_url")
        hn_job_id = page["hn_job_id"]
        company_name = page.get("company_name")

        if not careers_url:
            continue

        try:
            resp = session.get(careers_url, timeout=15)
            if resp.status_code != 200:
                store.update_hn_career_page(
                    hn_job_id, status='failed',
                    error=f"HTTP {resp.status_code}",
                    last_checked=_now_iso(),
                )
                continue
        except Exception as e:
            store.update_hn_career_page(
                hn_job_id, status='failed',
                error=str(e)[:200],
                last_checked=_now_iso(),
            )
            continue

        html = resp.text
        result = detect_ats_in_html(html)

        if result:
            platform, token = result
            store.add_token(platform, token, company_name=company_name)
            store.update_hn_career_page(
                hn_job_id,
                ats_platform=platform,
                ats_token=token,
                page_type='ats',
                status='scraped',
                last_checked=_now_iso(),
            )
            ats_found += 1
            by_platform[platform] = by_platform.get(platform, 0) + 1
            if verbose:
                log.info("  ATS embed: %s/%s on %s", platform, token, careers_url)
        else:
            page_type = _classify_page(html)
            store.update_hn_career_page(
                hn_job_id,
                page_type=page_type,
                last_checked=_now_iso(),
            )
            if page_type == 'static_html':
                static_html += 1
            elif page_type == 'spa':
                spa += 1

        time.sleep(0.5)

    log.info(
        "Phase 3: Scanned %d pages — %d ATS tokens, %d static_html, %d spa",
        len(pages), ats_found, static_html, spa,
    )
    for p, c in sorted(by_platform.items()):
        log.info("  %s: %d", p, c)

    return {"total": len(pages), "ats_found": ats_found, "by_platform": by_platform}


def _classify_page(html: str) -> str:
    """Classify a non-ATS careers page as static_html or spa."""
    # SPA indicators: minimal body with JS app mount points
    if re.search(r'<div\s+id=["\'](?:root|app|__next)["\']>\s*</div>', html, re.I):
        return 'spa'
    # If body has substantial text content, it's static
    body_match = re.search(r'<body[^>]*>(.*)</body>', html, re.I | re.DOTALL)
    if body_match:
        text = re.sub(r'<[^>]+>', '', body_match.group(1))
        if len(text.strip()) > 200:
            return 'static_html'
    return 'unknown'


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_discovery(store: Store, phase: str | None = None, verbose: bool = False) -> None:
    """Run HN token discovery pipeline."""
    if phase is None or phase == 'harvest':
        harvest_ats_tokens(store, verbose)
    if phase is None or phase == 'find-careers':
        discover_careers_pages(store, verbose)
    if phase is None or phase == 'detect-ats':
        detect_ats_on_careers(store, verbose)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
