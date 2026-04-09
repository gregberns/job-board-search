"""Tests for jbs/enrich_rules.py — Stage 1 rule-based extraction."""

import pytest

from jbs.enrich_rules import (
    extract_is_management,
    extract_seniority,
    extract_visa,
    extract_years_experience,
    normalize_salary_to_usd,
    normalize_tech_stack,
)


# ---------------------------------------------------------------------------
# Seniority extraction
# ---------------------------------------------------------------------------

class TestExtractSeniority:
    def test_intern(self):
        assert extract_seniority("Software Engineering Intern") == "intern"

    def test_junior(self):
        assert extract_seniority("Junior Backend Developer") == "junior"

    def test_jr_abbreviation(self):
        assert extract_seniority("Jr. Software Engineer") == "junior"

    def test_senior(self):
        assert extract_seniority("Senior Software Engineer") == "senior"

    def test_sr_abbreviation(self):
        assert extract_seniority("Sr. Frontend Developer") == "senior"

    def test_staff(self):
        assert extract_seniority("Staff Engineer") == "staff"

    def test_principal(self):
        assert extract_seniority("Principal Engineer") == "principal"

    def test_distinguished(self):
        assert extract_seniority("Distinguished Engineer") == "principal"

    def test_no_match(self):
        assert extract_seniority("Software Engineer") is None

    def test_ambiguous_returns_none(self):
        # "Senior Staff" matches both senior and staff -> None
        assert extract_seniority("Senior Staff Engineer") is None

    def test_case_insensitive(self):
        assert extract_seniority("SENIOR BACKEND ENGINEER") == "senior"

    def test_mid_level_no_match(self):
        # "Mid-level" has no keyword pattern -> None (deferred to LLM)
        assert extract_seniority("Mid-Level Software Engineer") is None


# ---------------------------------------------------------------------------
# Management detection
# ---------------------------------------------------------------------------

class TestExtractIsManagement:
    def test_manager(self):
        assert extract_is_management("Engineering Manager") is True

    def test_director(self):
        assert extract_is_management("Director of Engineering") is True

    def test_vp(self):
        assert extract_is_management("VP of Engineering") is True

    def test_vice_president(self):
        assert extract_is_management("Vice President, Platform") is True

    def test_head_of(self):
        assert extract_is_management("Head of Infrastructure") is True

    def test_chief(self):
        assert extract_is_management("Chief Technology Officer") is True

    def test_ic_engineer(self):
        assert extract_is_management("Senior Software Engineer") is False

    def test_tech_lead(self):
        assert extract_is_management("Tech Lead") is False

    def test_case_insensitive(self):
        assert extract_is_management("engineering manager") is True


# ---------------------------------------------------------------------------
# Salary normalization
# ---------------------------------------------------------------------------

class TestNormalizeSalary:
    def test_usd_yearly(self):
        assert normalize_salary_to_usd(150000, 200000, "USD", "yearly") == (150000, 200000)

    def test_eur_yearly(self):
        usd_min, usd_max = normalize_salary_to_usd(100000, 150000, "EUR", "yearly")
        assert usd_min == 108000  # 100000 * 1.08
        assert usd_max == 162000  # 150000 * 1.08

    def test_gbp_yearly(self):
        usd_min, usd_max = normalize_salary_to_usd(80000, 120000, "GBP", "yearly")
        assert usd_min == 101600  # 80000 * 1.27
        assert usd_max == 152400  # 120000 * 1.27

    def test_hourly_to_annual(self):
        usd_min, usd_max = normalize_salary_to_usd(50, 75, "USD", "hourly")
        assert usd_min == 104000  # 50 * 2080
        assert usd_max == 156000  # 75 * 2080

    def test_monthly_to_annual(self):
        usd_min, usd_max = normalize_salary_to_usd(10000, 15000, "USD", "monthly")
        assert usd_min == 120000  # 10000 * 12
        assert usd_max == 180000  # 15000 * 12

    def test_cad_hourly(self):
        usd_min, usd_max = normalize_salary_to_usd(40, 60, "CAD", "hourly")
        assert usd_min == round(40 * 0.74 * 2080)
        assert usd_max == round(60 * 0.74 * 2080)

    def test_none_amounts(self):
        assert normalize_salary_to_usd(None, None, "USD", "yearly") == (None, None)

    def test_partial_min_only(self):
        usd_min, usd_max = normalize_salary_to_usd(100000, None, "USD", "yearly")
        assert usd_min == 100000
        assert usd_max is None

    def test_partial_max_only(self):
        usd_min, usd_max = normalize_salary_to_usd(None, 200000, "USD", "yearly")
        assert usd_min is None
        assert usd_max == 200000

    def test_unknown_currency_defaults_to_1(self):
        usd_min, usd_max = normalize_salary_to_usd(100000, 200000, "JPY", "yearly")
        assert usd_min == 100000
        assert usd_max == 200000

    def test_none_currency(self):
        assert normalize_salary_to_usd(100000, 200000, None, "yearly") == (100000, 200000)

    def test_none_interval(self):
        assert normalize_salary_to_usd(100000, 200000, "USD", None) == (100000, 200000)


# ---------------------------------------------------------------------------
# Visa sponsorship detection
# ---------------------------------------------------------------------------

class TestExtractVisa:
    def test_sponsors(self):
        assert extract_visa("We offer visa sponsorship available for qualified candidates.") == "sponsors"

    def test_will_sponsor(self):
        assert extract_visa("We will sponsor H-1B visas.") == "sponsors"

    def test_h1b_sponsor(self):
        assert extract_visa("H-1B sponsor for international hires.") == "sponsors"

    def test_no_sponsorship(self):
        assert extract_visa("No sponsorship available for this role.") == "no_sponsorship"

    def test_cannot_sponsor(self):
        assert extract_visa("We cannot sponsor visas at this time.") == "no_sponsorship"

    def test_must_be_authorized(self):
        assert extract_visa("Must be authorized to work in the US.") == "no_sponsorship"

    def test_us_citizens_only(self):
        assert extract_visa("US citizens only.") == "no_sponsorship"

    def test_without_sponsorship(self):
        assert extract_visa("Able to work without sponsorship.") == "no_sponsorship"

    def test_unknown(self):
        assert extract_visa("Great opportunity for engineers.") == "unknown"

    def test_empty(self):
        assert extract_visa("") == "unknown"

    def test_sponsors_takes_priority(self):
        # If both patterns match, sponsors wins (checked first)
        assert extract_visa("Visa sponsorship available. Must be authorized to work.") == "sponsors"


# ---------------------------------------------------------------------------
# Years of experience extraction
# ---------------------------------------------------------------------------

class TestExtractYearsExperience:
    def test_simple(self):
        assert extract_years_experience("5 years of experience required") == 5

    def test_plus(self):
        assert extract_years_experience("3+ years of Python experience") == 3

    def test_multiple_takes_minimum(self):
        assert extract_years_experience("5+ years backend, 2 years ML experience") == 2

    def test_yrs_abbreviation(self):
        assert extract_years_experience("7 yrs experience with distributed systems") == 7

    def test_yr_abbreviation(self):
        assert extract_years_experience("1 yr minimum") == 1

    def test_no_match(self):
        assert extract_years_experience("Experience with Python and Go") is None

    def test_empty(self):
        assert extract_years_experience("") is None


# ---------------------------------------------------------------------------
# Tech stack normalization
# ---------------------------------------------------------------------------

class TestNormalizeTechStack:
    def test_basic_aliases(self):
        result = normalize_tech_stack(["postgres", "k8s", "Python"])
        assert result == ["PostgreSQL", "Kubernetes", "Python"]

    def test_deduplication(self):
        result = normalize_tech_stack(["PostgreSQL", "postgres", "pg"])
        assert result == ["PostgreSQL"]

    def test_preserves_unknown(self):
        result = normalize_tech_stack(["FastAPI", "Redis"])
        assert result == ["FastAPI", "Redis"]

    def test_golang_alias(self):
        result = normalize_tech_stack(["golang", "Python"])
        assert result == ["Go", "Python"]

    def test_node_aliases(self):
        result = normalize_tech_stack(["nodejs", "Node.js"])
        assert result == ["Node.js"]

    def test_react_aliases(self):
        result = normalize_tech_stack(["reactjs", "React"])
        assert result == ["React"]

    def test_case_insensitive_lookup(self):
        result = normalize_tech_stack(["POSTGRES", "K8S"])
        assert result == ["PostgreSQL", "Kubernetes"]

    def test_empty_list(self):
        assert normalize_tech_stack([]) == []

    def test_preserves_order(self):
        result = normalize_tech_stack(["Python", "Go", "Rust"])
        assert result == ["Python", "Go", "Rust"]
