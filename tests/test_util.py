"""Tests for jbs/util.py — leaf utility module."""

from types import SimpleNamespace
from datetime import date, timedelta

import pytest

from jbs.util import (
    create_session,
    extract_salary_from_text,
    filter_jobs,
    fix_mojibake,
    html_to_markdown,
    normalize_company_name,
    parse_location,
    strip_boilerplate,
    strip_data_uris,
)


# ---------------------------------------------------------------------------
# normalize_company_name — spec 02 examples + edge cases
# ---------------------------------------------------------------------------

class TestNormalizeCompanyName:
    """All examples from spec 02 plus edge cases."""

    def test_anthropic_inc(self):
        assert normalize_company_name('Anthropic, Inc.') == 'anthropic'

    def test_ramp_technologies(self):
        assert normalize_company_name('Ramp Technologies') == 'ramptechnologies'

    def test_scale_ai(self):
        assert normalize_company_name('Scale AI') == 'scaleai'

    def test_acme_corp(self):
        assert normalize_company_name('Acme Corp.') == 'acme'

    def test_acme_upper(self):
        assert normalize_company_name('ACME') == 'acme'

    def test_oreilly_media(self):
        assert normalize_company_name("O'Reilly Media") == 'oreillymedia'

    def test_llc(self):
        assert normalize_company_name('FooBar LLC') == 'foobar'

    def test_ltd(self):
        assert normalize_company_name('Widget Ltd.') == 'widget'

    def test_gmbh(self):
        assert normalize_company_name('Siemens GmbH') == 'siemens'

    def test_pbc(self):
        assert normalize_company_name('Benefit PBC') == 'benefit'

    def test_plc(self):
        assert normalize_company_name('Barclays PLC') == 'barclays'

    def test_incorporated(self):
        assert normalize_company_name('Acme Incorporated') == 'acme'

    def test_corporation(self):
        assert normalize_company_name('Acme Corporation') == 'acme'

    def test_whitespace(self):
        assert normalize_company_name('  Stripe  ') == 'stripe'

    def test_empty_string(self):
        assert normalize_company_name('') == ''

    def test_only_suffix(self):
        assert normalize_company_name('Inc.') == ''

    def test_hyphenated(self):
        assert normalize_company_name('Palo-Alto Networks') == 'paloaltonetworks'

    def test_numbers(self):
        assert normalize_company_name('1Password') == '1password'


# ---------------------------------------------------------------------------
# create_session
# ---------------------------------------------------------------------------

class TestCreateSession:
    def test_returns_session(self):
        session = create_session()
        assert hasattr(session, 'get')
        assert hasattr(session, 'post')

    def test_retry_adapter_mounted(self):
        session = create_session()
        adapter = session.get_adapter('https://example.com')
        assert adapter.max_retries.total == 3

    def test_user_agent(self):
        session = create_session()
        assert session.headers['User-Agent'] == 'jbs/0.1 (job-board-search)'


# ---------------------------------------------------------------------------
# extract_salary_from_text
# ---------------------------------------------------------------------------

class TestExtractSalaryFromText:
    def test_dollar_range(self):
        mn, mx, cur = extract_salary_from_text('Salary: $150,000 - $200,000 per year')
        assert mn == 150_000
        assert mx == 200_000
        assert cur == 'USD'

    def test_k_suffix(self):
        mn, mx, cur = extract_salary_from_text('$150k-$200k')
        assert mn == 150_000
        assert mx == 200_000
        assert cur == 'USD'

    def test_pound_sign(self):
        mn, mx, cur = extract_salary_from_text('Salary: \u00a380,000 - \u00a3100,000')
        assert mn == 80_000
        assert mx == 100_000
        assert cur == 'GBP'

    def test_euro_sign(self):
        mn, mx, cur = extract_salary_from_text('\u20ac60,000 - \u20ac90,000')
        assert mn == 60_000
        assert mx == 90_000
        assert cur == 'EUR'

    def test_no_salary(self):
        mn, mx, cur = extract_salary_from_text('No salary information available')
        assert mn is None
        assert mx is None

    def test_empty_string(self):
        mn, mx, cur = extract_salary_from_text('')
        assert mn is None
        assert mx is None

    def test_en_dash(self):
        mn, mx, cur = extract_salary_from_text('$120,000\u2013$180,000')
        assert mn == 120_000
        assert mx == 180_000


# ---------------------------------------------------------------------------
# strip_boilerplate
# ---------------------------------------------------------------------------

class TestStripBoilerplate:
    def test_eeo_statement(self):
        text = 'Great job description.\n## Equal Opportunity Employer\nWe are committed...'
        result = strip_boilerplate(text)
        assert 'Great job description' in result
        assert 'Equal Opportunity' not in result

    def test_privacy_section(self):
        text = 'Role details here.\n### Privacy Policy\nWe collect your data...'
        result = strip_boilerplate(text)
        assert 'Role details' in result
        assert 'Privacy' not in result

    def test_we_are_equal(self):
        text = 'Build cool stuff.\nWe are an equal opportunity employer and value diversity.'
        result = strip_boilerplate(text)
        assert 'Build cool stuff' in result
        assert 'equal opportunity' not in result

    def test_no_boilerplate(self):
        text = 'This is a clean job description with technical requirements.'
        result = strip_boilerplate(text)
        assert result == text

    def test_accommodation_section(self):
        text = 'Requirements listed.\n## Accommodation\nWe provide reasonable...'
        result = strip_boilerplate(text)
        assert 'Requirements' in result
        assert 'Accommodation' not in result


# ---------------------------------------------------------------------------
# fix_mojibake
# ---------------------------------------------------------------------------

class TestFixMojibake:
    def test_smart_quote(self):
        # "you\u2019re" encoded as UTF-8 then decoded as latin-1 gives mojibake
        original = 'you\u2019re'
        broken = original.encode('utf-8').decode('latin-1')
        assert fix_mojibake(broken) == original

    def test_clean_ascii(self):
        text = 'Normal ASCII text'
        assert fix_mojibake(text) == text

    def test_empty(self):
        assert fix_mojibake('') == ''

    def test_none(self):
        assert fix_mojibake(None) is None

    def test_unfixable(self):
        # Already valid UTF-8 with non-latin chars should pass through
        text = 'Hello \u4e16\u754c'
        assert fix_mojibake(text) == text


# ---------------------------------------------------------------------------
# filter_jobs
# ---------------------------------------------------------------------------

def _make_job(title='Eng', description='Build things', date_posted=None, is_remote=False):
    return SimpleNamespace(
        title=title, description=description, date_posted=date_posted, is_remote=is_remote,
    )


class TestFilterJobs:
    def test_no_filters(self):
        jobs = [_make_job(), _make_job()]
        assert len(filter_jobs(jobs)) == 2

    def test_search_term_title(self):
        jobs = [_make_job(title='Backend Engineer'), _make_job(title='Designer')]
        result = filter_jobs(jobs, search_term='backend')
        assert len(result) == 1
        assert result[0].title == 'Backend Engineer'

    def test_search_term_description(self):
        jobs = [_make_job(description='Python and Django'), _make_job(description='Photoshop')]
        result = filter_jobs(jobs, search_term='python')
        assert len(result) == 1

    def test_hours_old(self):
        recent = _make_job(date_posted=date.today())
        old = _make_job(date_posted=date.today() - timedelta(days=30))
        no_date = _make_job(date_posted=None)
        result = filter_jobs([recent, old, no_date], hours_old=48)
        # recent and no_date should pass; old should not
        assert len(result) == 2

    def test_is_remote(self):
        remote = _make_job(is_remote=True)
        onsite = _make_job(is_remote=False)
        result = filter_jobs([remote, onsite], is_remote=True)
        assert len(result) == 1
        assert result[0].is_remote is True


# ---------------------------------------------------------------------------
# parse_location
# ---------------------------------------------------------------------------

class TestParseLocation:
    def test_city_state(self):
        loc = parse_location('San Francisco, CA')
        assert loc['city'] == 'San Francisco'
        assert loc['state'] == 'CA'
        assert loc['country'] == 'USA'

    def test_remote(self):
        loc = parse_location('Remote')
        assert loc['work_arrangement'] == 'remote'

    def test_city_state_country(self):
        loc = parse_location('New York, NY, USA')
        assert loc['city'] == 'New York'
        assert loc['state'] == 'NY'
        assert loc['country'] == 'USA'

    def test_empty(self):
        loc = parse_location('')
        assert loc['work_arrangement'] == 'unknown'

    def test_none(self):
        loc = parse_location(None)
        assert loc['city'] is None

    def test_remote_with_city(self):
        loc = parse_location('Remote - San Francisco, CA')
        assert loc['work_arrangement'] == 'remote'
        assert loc['city'] == 'San Francisco'

    def test_hybrid_not_detected(self):
        loc = parse_location('Austin, TX')
        assert loc['work_arrangement'] == 'unknown'


# ---------------------------------------------------------------------------
# html_to_markdown
# ---------------------------------------------------------------------------

class TestHtmlToMarkdown:
    def test_basic_html(self):
        result = html_to_markdown('<p>Hello <strong>world</strong></p>')
        assert 'Hello' in result
        assert 'world' in result

    def test_empty(self):
        assert html_to_markdown('') == ''

    def test_none(self):
        assert html_to_markdown(None) == ''

    def test_list(self):
        result = html_to_markdown('<ul><li>Item 1</li><li>Item 2</li></ul>')
        assert 'Item 1' in result
        assert 'Item 2' in result

    def test_entity_encoded_html(self):
        """Entity-encoded HTML (from Greenhouse API) is decoded before conversion."""
        result = html_to_markdown('&lt;p&gt;Hello &lt;strong&gt;world&lt;/strong&gt;&lt;/p&gt;')
        assert 'Hello' in result
        assert 'world' in result
        assert '&lt;' not in result

    def test_strips_base64_images(self):
        """Inline base64 images are stripped (they inflate descriptions to MBs)."""
        html = '<p>Job description</p><img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"/><p>More details</p>'
        result = html_to_markdown(html)
        assert 'Job description' in result
        assert 'More details' in result
        assert 'data:image' not in result
        assert 'iVBOR' not in result

    def test_preserves_regular_images(self):
        """Regular URL images are preserved (converted to markdown)."""
        html = '<p>Text</p><img src="https://example.com/logo.png" alt="Logo"/>'
        result = html_to_markdown(html)
        assert 'example.com/logo.png' in result

    def test_entity_encoded_with_base64(self):
        """Entity-encoded HTML with base64 images: decode then strip."""
        html = '&lt;p&gt;Description&lt;/p&gt;&lt;img src=&quot;data:image/png;base64,abc123&quot;/&gt;&lt;p&gt;End&lt;/p&gt;'
        result = html_to_markdown(html)
        assert 'Description' in result
        assert 'End' in result
        assert 'data:image' not in result

    def test_idempotent_on_markdown(self):
        """Already-converted markdown passes through without damage."""
        md_text = '**Bold** text with [links](https://example.com)\n\n- Item 1\n- Item 2'
        result = html_to_markdown(md_text)
        assert 'Bold' in result
        assert 'links' in result


# ---------------------------------------------------------------------------
# strip_data_uris
# ---------------------------------------------------------------------------

class TestStripDataUris:
    def test_strips_html_data_img(self):
        text = 'Hello <img src="data:image/png;base64,abc123"/> world'
        result = strip_data_uris(text)
        assert 'Hello' in result
        assert 'world' in result
        assert 'data:image' not in result

    def test_strips_markdown_data_img(self):
        text = 'Hello ![logo](data:image/jpeg;base64,/9j/4AAQSkZJ) world'
        result = strip_data_uris(text)
        assert 'Hello' in result
        assert 'world' in result
        assert 'data:image' not in result

    def test_preserves_normal_text(self):
        text = 'No images here, just text about data processing.'
        assert strip_data_uris(text) == text

    def test_preserves_regular_urls(self):
        text = '![logo](https://example.com/img.png)'
        assert strip_data_uris(text) == text
