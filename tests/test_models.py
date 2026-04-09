from datetime import date, datetime

from jbs.models import (
    Compensation,
    Job,
    Location,
    ScrapeResult,
    SearchQuery,
    WorkArrangement,
)


class TestWorkArrangement:
    def test_enum_values(self):
        assert WorkArrangement.REMOTE.value == "remote"
        assert WorkArrangement.HYBRID.value == "hybrid"
        assert WorkArrangement.ONSITE.value == "onsite"
        assert WorkArrangement.UNKNOWN.value == "unknown"


class TestLocation:
    def test_defaults(self):
        loc = Location()
        assert loc.city is None
        assert loc.state is None
        assert loc.country is None
        assert loc.raw is None
        assert loc.work_arrangement is WorkArrangement.UNKNOWN

    def test_with_values(self):
        loc = Location(city="SF", state="CA", country="US", raw="SF, CA")
        assert loc.city == "SF"
        assert loc.state == "CA"


class TestCompensation:
    def test_defaults(self):
        comp = Compensation()
        assert comp.min_amount is None
        assert comp.max_amount is None
        assert comp.currency == "USD"
        assert comp.interval == "yearly"


class TestJob:
    def test_required_fields_only(self):
        job = Job(
            id="gh-123",
            source="greenhouse",
            title="Software Engineer",
            company="Acme",
            url="https://example.com/job/123",
            location=Location(),
        )
        assert job.id == "gh-123"
        assert job.source == "greenhouse"
        assert job.title == "Software Engineer"
        assert job.company == "Acme"
        assert job.url == "https://example.com/job/123"
        assert job.location.work_arrangement is WorkArrangement.UNKNOWN
        # Defaults
        assert job.url_direct is None
        assert job.compensation is None
        assert job.description is None
        assert job.date_posted is None
        assert job.job_type is None
        assert job.job_function is None
        assert job.board_token is None
        assert job.is_remote is False
        assert job.scraped_at is None

    def test_all_optional_fields(self):
        now = datetime(2026, 4, 9, 12, 0, 0)
        job = Job(
            id="lever-abc",
            source="lever",
            title="ML Engineer",
            company="AI Corp",
            url="https://lever.co/jobs/abc",
            location=Location(
                city="Remote", work_arrangement=WorkArrangement.REMOTE
            ),
            url_direct="https://aicorp.com/careers/ml",
            compensation=Compensation(min_amount=150000, max_amount=200000),
            description="Build ML systems",
            date_posted=date(2026, 4, 1),
            job_type="full-time",
            job_function="engineering",
            board_token="aicorp",
            is_remote=True,
            scraped_at=now,
        )
        assert job.url_direct == "https://aicorp.com/careers/ml"
        assert job.compensation.min_amount == 150000
        assert job.compensation.max_amount == 200000
        assert job.date_posted == date(2026, 4, 1)
        assert job.job_type == "full-time"
        assert job.board_token == "aicorp"
        assert job.is_remote is True
        assert job.scraped_at == now

    def test_company_can_be_none(self):
        job = Job(
            id="hn-999",
            source="hn",
            title="Hiring",
            company=None,
            url="https://hn.com/999",
            location=Location(),
        )
        assert job.company is None


class TestScrapeResult:
    def test_defaults(self):
        result = ScrapeResult(source="greenhouse", jobs=[])
        assert result.source == "greenhouse"
        assert result.jobs == []
        assert result.failed_tokens == []
        assert result.errors == []
        assert result.elapsed_seconds == 0.0

    def test_mutable_defaults_are_independent(self):
        r1 = ScrapeResult(source="a", jobs=[])
        r2 = ScrapeResult(source="b", jobs=[])
        r1.failed_tokens.append("tok1")
        r1.errors.append("err1")
        assert r2.failed_tokens == []
        assert r2.errors == []


class TestSearchQuery:
    def test_defaults(self):
        q = SearchQuery()
        assert q.text is None
        assert q.sites is None
        assert q.companies is None
        assert q.seniority is None
        assert q.domains is None
        assert q.industries is None
        assert q.work_arrangement is None
        assert q.country is None
        assert q.state is None
        assert q.city is None
        assert q.min_salary is None
        assert q.max_salary is None
        assert q.engineering_only is False
        assert q.ai_native_min is None
        assert q.hours_old is None
        assert q.new_only is False
        assert q.include_inactive is False
        assert q.tags is None
        assert q.rating is None
        assert q.limit == 50
        assert q.offset == 0

    def test_with_filters(self):
        q = SearchQuery(
            text="ML",
            sites=["greenhouse"],
            engineering_only=True,
            ai_native_min=0.7,
            limit=20,
        )
        assert q.text == "ML"
        assert q.sites == ["greenhouse"]
        assert q.engineering_only is True
        assert q.ai_native_min == 0.7
        assert q.limit == 20
