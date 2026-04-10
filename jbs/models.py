from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class WorkArrangement(Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


@dataclass
class Location:
    city: str | None = None
    state: str | None = None
    country: str | None = None
    raw: str | None = None
    work_arrangement: WorkArrangement = WorkArrangement.UNKNOWN


@dataclass
class Compensation:
    min_amount: float | None = None
    max_amount: float | None = None
    currency: str = "USD"
    interval: str = "yearly"  # yearly, monthly, hourly


@dataclass
class Job:
    id: str                         # Prefixed: gh-123, lever-abc, rok-456
    source: str                     # greenhouse, lever, ashby, remoteok, hn
    title: str
    company: str | None             # Raw company name (stored as company_raw in DB)
    url: str
    location: Location
    url_direct: str | None = None
    compensation: Compensation | None = None
    description: str | None = None
    date_posted: date | None = None
    job_type: str | None = None     # full-time, part-time, contract, intern
    job_function: str | None = None
    board_token: str | None = None  # ATS board slug
    is_remote: bool = False
    scraped_at: datetime | None = None


@dataclass
class ScrapeResult:
    source: str
    jobs: list[Job]
    failed_tokens: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0


@dataclass
class SearchQuery:
    text: str | None = None
    sites: list[str] | None = None
    companies: list[str] | None = None
    seniority: list[str] | None = None
    domains: list[str] | None = None
    industries: list[str] | None = None
    work_arrangement: list[str] | None = None
    country: str | None = None
    state: str | None = None
    city: str | None = None
    min_salary: float | None = None
    max_salary: float | None = None
    engineering_only: bool = False
    ai_native_min: float | None = None
    hours_old: int | None = None
    new_only: bool = False
    include_inactive: bool = False
    tags: list[str] | None = None
    rating: int | None = None
    vec_query: str | None = None
    limit: int = 50
    offset: int = 0
