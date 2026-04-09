"""Shared utility functions for jbs. LEAF module — no imports from other jbs modules."""

from __future__ import annotations

import re
from datetime import date, timedelta

from markdownify import markdownify as md
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------

def create_session() -> Session:
    """Create a requests Session with retry, timeout defaults, and User-Agent."""
    session = Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers["User-Agent"] = "jbs/0.1 (job-board-search)"
    return session


# ---------------------------------------------------------------------------
# HTML / text cleanup
# ---------------------------------------------------------------------------

def html_to_markdown(html: str) -> str:
    """Convert HTML to clean markdown using markdownify."""
    if not html:
        return ""
    return md(html).strip()


_BOILERPLATE_PATTERNS = [
    re.compile(
        r'(?:^|\n)#{1,3}\s*(?:Equal Opportunity|EEO|Diversity).*',
        re.DOTALL | re.IGNORECASE,
    ),
    re.compile(
        r'(?:^|\n)#{1,3}\s*(?:Privacy|Data Protection|GDPR).*',
        re.DOTALL | re.IGNORECASE,
    ),
    re.compile(
        r'(?:^|\n)(?:We are an equal opportunity|This company is committed to).*',
        re.DOTALL | re.IGNORECASE,
    ),
    re.compile(
        r'(?:^|\n)#{1,3}\s*(?:Accommodation|ADA|Disability).*',
        re.DOTALL | re.IGNORECASE,
    ),
]


def strip_boilerplate(text: str) -> str:
    """Remove legal boilerplate from job descriptions (in memory, not persisted)."""
    for pattern in _BOILERPLATE_PATTERNS:
        text = pattern.sub('', text)
    return text.strip()


def fix_mojibake(text: str) -> str:
    """Fix UTF-8 mojibake (latin-1 decoded as UTF-8).

    Common pattern: smart quotes appearing as ``\u00e2\u0080\u0099`` etc.
    """
    if not text:
        return text
    try:
        return text.encode('latin-1').decode('utf-8')
    except (UnicodeDecodeError, UnicodeEncodeError):
        return text


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def filter_jobs(
    jobs: list,
    search_term: str | None = None,
    hours_old: int | None = None,
    is_remote: bool = False,
) -> list:
    """Client-side filtering of scraped results.

    Each job is expected to have attributes: title, description, date_posted, is_remote.
    """
    filtered = jobs

    if search_term:
        term = search_term.lower()
        filtered = [
            j for j in filtered
            if (getattr(j, 'title', None) and term in j.title.lower())
            or (getattr(j, 'description', None) and term in j.description.lower())
        ]

    if hours_old:
        cutoff = date.today() - timedelta(hours=hours_old)
        filtered = [
            j for j in filtered
            if getattr(j, 'date_posted', None) is None or j.date_posted >= cutoff
        ]

    if is_remote:
        filtered = [j for j in filtered if getattr(j, 'is_remote', False)]

    return filtered


# ---------------------------------------------------------------------------
# Salary extraction
# ---------------------------------------------------------------------------

_SALARY_RANGE_RE = re.compile(
    r'[\$\£\€](\d+(?:,\d+)?(?:\.\d+)?)([kK]?)\s*[-\u2013\u2014]\s*'
    r'(?:[\$\£\€])?(\d+(?:,\d+)?(?:\.\d+)?)([kK]?)'
)

_CURRENCY_SYMBOLS = {'$': 'USD', '\u00a3': 'GBP', '\u20ac': 'EUR'}
_CURRENCY_RE = re.compile(r'([\$\£\€])')


def extract_salary_from_text(text: str) -> tuple[float | None, float | None, str]:
    """Extract salary range from free text.

    Returns (min_amount, max_amount, currency).
    """
    if not text:
        return None, None, 'USD'

    match = _SALARY_RANGE_RE.search(text)
    if not match:
        return None, None, 'USD'

    def _parse(raw: str, k_suffix: str) -> float:
        val = float(raw.replace(',', ''))
        if k_suffix.lower() == 'k':
            val *= 1000
        return val

    min_val = _parse(match.group(1), match.group(2))
    max_val = _parse(match.group(3), match.group(4))

    # Detect currency from the text preceding the match
    currency = 'USD'
    cur_match = _CURRENCY_RE.search(text[:match.start() + 1] if match.start() > 0 else text[:10])
    if cur_match:
        currency = _CURRENCY_SYMBOLS.get(cur_match.group(1), 'USD')
    else:
        # Check the match itself
        prefix_char = text[match.start()] if match.start() < len(text) else ''
        currency = _CURRENCY_SYMBOLS.get(prefix_char, 'USD')

    return min_val, max_val, currency


# ---------------------------------------------------------------------------
# Company name normalization
# ---------------------------------------------------------------------------

_SUFFIXES = re.compile(
    r',?\s*\b(inc|llc|ltd|corp|co|pbc|gmbh|ag|sa|plc|pty|limited|incorporated|corporation)\.?\s*$',
    re.IGNORECASE,
)


def normalize_company_name(name: str) -> str:
    """Normalize a company name for deduplication.

    Steps:
    1. Strip whitespace
    2. Remove common corporate suffixes (Inc, LLC, Ltd, Corp, PBC, GmbH, etc.)
    3. Lowercase
    4. Remove all non-alphanumeric characters

    Examples:
        'Anthropic, Inc.'  -> 'anthropic'
        'Ramp Technologies' -> 'ramptechnologies'  (not a suffix)
        'Scale AI'          -> 'scaleai'
        'Acme Corp.'        -> 'acme'
        'ACME'              -> 'acme'
        "O'Reilly Media"    -> 'oreillymedia'
    """
    s = name.strip()
    s = _SUFFIXES.sub('', s)
    s = s.lower()
    s = re.sub(r'[^a-z0-9]', '', s)
    return s


# ---------------------------------------------------------------------------
# Location parsing
# ---------------------------------------------------------------------------

_REMOTE_KEYWORDS = frozenset({
    'remote', 'anywhere', 'worldwide', 'distributed', 'work from home', 'wfh',
})

_US_STATES = frozenset({
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
    'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
    'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
    'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
    'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY', 'DC',
})


def parse_location(raw: str) -> dict:
    """Parse location string into components.

    Returns dict with keys: city, state, country, work_arrangement.
    """
    if not raw:
        return {'city': None, 'state': None, 'country': None, 'work_arrangement': 'unknown'}

    is_remote = any(kw in raw.lower() for kw in _REMOTE_KEYWORDS)

    # Strip remote-related text for location parsing
    clean = raw
    for kw in _REMOTE_KEYWORDS:
        clean = re.sub(rf'\b{re.escape(kw)}\b', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'[/|,\-]+\s*$', '', clean).strip()
    clean = re.sub(r'^\s*[/|,\-]+', '', clean).strip()

    city, state, country = None, None, None

    if is_remote and not clean:
        return {'city': None, 'state': None, 'country': None, 'work_arrangement': 'remote'}

    # Try "City, ST" or "City, ST, Country" pattern
    parts = [p.strip() for p in clean.split(',') if p.strip()]

    if len(parts) >= 3:
        city = parts[0]
        state = parts[1]
        country = parts[2]
    elif len(parts) == 2:
        city = parts[0]
        if parts[1].upper() in _US_STATES:
            state = parts[1].upper()
            country = 'USA'
        else:
            # Could be "City, Country" or "City, State"
            state = parts[1]
    elif len(parts) == 1 and parts[0]:
        city = parts[0]

    work_arrangement = 'remote' if is_remote else 'unknown'

    return {
        'city': city,
        'state': state,
        'country': country,
        'work_arrangement': work_arrangement,
    }
