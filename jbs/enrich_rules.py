"""Stage 1: Rule-based extraction. Pure functions, no DB or LLM dependency."""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Seniority extraction (title only)
# ---------------------------------------------------------------------------

_SENIORITY_PATTERNS = [
    (re.compile(r'\bintern\b', re.IGNORECASE), 'intern'),
    (re.compile(r'\b(?:junior|jr\.?)\b', re.IGNORECASE), 'junior'),
    (re.compile(r'\b(?:senior|sr\.?)\b', re.IGNORECASE), 'senior'),
    (re.compile(r'\bstaff\b', re.IGNORECASE), 'staff'),
    (re.compile(r'\b(?:principal|distinguished)\b', re.IGNORECASE), 'principal'),
]


def extract_seniority(title: str) -> str | None:
    """Extract seniority from job title. Returns None if ambiguous or no match."""
    matches = []
    for pattern, level in _SENIORITY_PATTERNS:
        if pattern.search(title):
            matches.append(level)
    return matches[0] if len(matches) == 1 else None


# ---------------------------------------------------------------------------
# Management detection
# ---------------------------------------------------------------------------

_MANAGEMENT_PATTERN = re.compile(
    r'\b(?:manager|director|vp|vice\s+president|head\s+of|chief)\b',
    re.IGNORECASE,
)


def extract_is_management(title: str) -> bool:
    """Detect if title indicates a management role."""
    return bool(_MANAGEMENT_PATTERN.search(title))


# ---------------------------------------------------------------------------
# Salary normalization
# ---------------------------------------------------------------------------

_FX_TO_USD = {
    'EUR': 1.08,
    'GBP': 1.27,
    'CAD': 0.74,
    'AUD': 0.66,
    'CHF': 1.13,
}


def normalize_salary_to_usd(
    min_amt: float | None,
    max_amt: float | None,
    currency: str | None,
    interval: str | None,
) -> tuple[float | None, float | None]:
    """Convert salary to annualized USD. Returns (usd_min, usd_max)."""
    if min_amt is None and max_amt is None:
        return None, None

    rate = _FX_TO_USD.get(currency, 1.0) if currency and currency != 'USD' else 1.0
    multiplier = {'yearly': 1, 'monthly': 12, 'hourly': 2080}.get(interval, 1) if interval else 1

    usd_min = round(min_amt * rate * multiplier) if min_amt else None
    usd_max = round(max_amt * rate * multiplier) if max_amt else None
    return usd_min, usd_max


# ---------------------------------------------------------------------------
# Visa sponsorship detection
# ---------------------------------------------------------------------------

_VISA_SPONSORS = re.compile(
    r'visa sponsorship available|will sponsor|we sponsor|h-1b sponsor',
    re.IGNORECASE,
)
_VISA_NO_SPONSOR = re.compile(
    r'no sponsorship|cannot sponsor|must be authorized to work|'
    r'us citizens only|permanent resident|no visa|without sponsorship',
    re.IGNORECASE,
)


def extract_visa(description: str) -> str:
    """Returns 'sponsors', 'no_sponsorship', or 'unknown'."""
    if _VISA_SPONSORS.search(description):
        return 'sponsors'
    if _VISA_NO_SPONSOR.search(description):
        return 'no_sponsorship'
    return 'unknown'


# ---------------------------------------------------------------------------
# Years of experience
# ---------------------------------------------------------------------------

_YEARS_EXP = re.compile(r'(\d+)\+?\s*(?:years?|yrs?)', re.IGNORECASE)


def extract_years_experience(description: str) -> int | None:
    """Extract minimum years of experience from description."""
    matches = _YEARS_EXP.findall(description)
    if matches:
        return min(int(m) for m in matches)
    return None


# ---------------------------------------------------------------------------
# LLM pre-filter classification
# ---------------------------------------------------------------------------

# Titles containing these are kept even if they match an exclude pattern.
_TITLE_KEEP = re.compile(
    r'\b(?:ai engineer|ml engineer|machine learning engineer)\b',
    re.IGNORECASE,
)

# Titles containing any of these → skip_title (non-engineering or adjacent).
_TITLE_EXCLUDE = re.compile(
    r'(?:'
    r'sales|marketing|recruiter|talent acq|human resource|'
    r'accountant|finance manager|financial analyst|'
    r'legal counsel|general counsel|paralegal|'
    r'customer success|account executive|business develop|'
    r'copywriter|content writer|'
    r'nurse|physician|therapist|pharmacist|receptionist|'
    r'warehouse|maintenance tech|'
    r'data scientist|data analyst|'
    r'product manager|program manager|project manager|'
    r'\bdesigner\b|'
    r'solutions engineer|support engineer|field engineer|'
    r'implementation|customer engineer'
    r')',
    re.IGNORECASE,
)

_SALARY_FLOOR = 190_000


def classify_llm_filter(
    title: str,
    is_management: bool,
    seniority: str | None,
    salary_usd_max: float | None,
    max_amount: float | None,
) -> str:
    """Classify whether a job should be sent to LLM enrichment.

    Returns one of: 'send', 'skip_mgmt', 'skip_title', 'skip_salary', 'skip_seniority'.
    Filters applied in priority order (first match wins).
    Always recomputed — not gated on prior value.
    """
    # 1. Management
    if is_management:
        return 'skip_mgmt'

    # 2. Non-engineering title (unless keep-override matches)
    if not _TITLE_KEEP.search(title) and _TITLE_EXCLUDE.search(title):
        return 'skip_title'

    # 3. Low salary (only when salary is known)
    effective_max = salary_usd_max or max_amount
    if effective_max is not None and effective_max < _SALARY_FLOOR:
        return 'skip_salary'

    # 4. Junior/intern seniority
    if seniority in ('intern', 'junior'):
        return 'skip_seniority'

    return 'send'


# ---------------------------------------------------------------------------
# Tech stack normalization (post-LLM)
# ---------------------------------------------------------------------------

_TECH_ALIASES = {
    "postgres": "PostgreSQL", "pg": "PostgreSQL",
    "k8s": "Kubernetes", "kube": "Kubernetes",
    "node": "Node.js", "nodejs": "Node.js",
    "reactjs": "React", "react.js": "React",
    "gcp": "Google Cloud", "aws": "AWS",
    "ts": "TypeScript", "js": "JavaScript",
    "py": "Python", "python3": "Python",
    "go": "Go", "golang": "Go",
}


def normalize_tech_stack(items: list[str]) -> list[str]:
    """Normalize LLM-produced tech stack names via alias map. Deduplicates."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        canonical = _TECH_ALIASES.get(item.lower(), item)
        if canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result
