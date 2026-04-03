# Job Board API & Programmatic Access Research

**Research Date:** April 2026
**Focus:** Software Engineering jobs, United States, small-to-medium businesses (under 500 employees)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Tier 1 — Best Free/Low-Cost APIs (Recommended Starting Points)](#tier-1--best-freelow-cost-apis)
3. [Tier 2 — Useful APIs with Some Limitations](#tier-2--useful-apis-with-some-limitations)
4. [Tier 3 — Paid APIs and Aggregators](#tier-3--paid-apis-and-aggregators)
5. [Tier 4 — Restricted/Deprecated/No Public API](#tier-4--restricteddeprecatedno-public-api)
6. [ATS Platform Public APIs](#ats-platform-public-apis)
7. [Open Source Tools](#open-source-tools)
8. [RSS Feeds](#rss-feeds)
9. [Government & Public Data](#government--public-data)
10. [Company Size Filtering Strategy](#company-size-filtering-strategy)
11. [Legal Considerations](#legal-considerations)
12. [Recommended Architecture](#recommended-architecture)

---

## Executive Summary

There is **no single API** that perfectly covers "Software Engineering jobs at US companies with <500 employees." The best approach is a **multi-source strategy** combining several free/cheap APIs with an open-source scraping library as a fallback. Here are the top recommendations:

| Priority | Source | Why |
|----------|--------|-----|
| 1 | **The Muse API** | Free, no auth needed for 500 req/hr, has company size filter (small/medium/large) |
| 2 | **Adzuna API** | Free tier, large aggregator, US coverage, salary data |
| 3 | **RemoteOK API** | Completely free, no auth, JSON endpoint, tech-focused |
| 4 | **Jobicy API** | Free, no auth, remote tech jobs, US filtering |
| 5 | **HN Who's Hiring** | Free via HN API, startup-focused, small companies |
| 6 | **JobSpy (OSS)** | Scrapes Indeed/LinkedIn/Glassdoor/Google/ZipRecruiter |
| 7 | **ATS APIs** | Free, no auth: Greenhouse, Lever, Ashby, Workable, Recruitee |
| 8 | **USAJobs API** | Free, government tech jobs |

---

## Tier 1 — Best Free/Low-Cost APIs

### 1. The Muse API ★★★★★

The best starting point for this project due to its company size filtering capability.

- **URL:** `https://www.themuse.com/api/public/jobs`
- **Auth:** Optional API key (query param `api_key`)
- **Rate Limits:**
  - Without API key: 500 requests/hour
  - With API key (free registration): 3,600 requests/hour
- **Cost:** Free
- **Data Format:** JSON
- **Company Size Filter:** YES — `size` field with values: `small`, `medium`, `large`
- **Other Filters:** category (50+ including "Software Engineer"), level (Entry/Mid/Senior), location, company name
- **Response Fields:** Job title, company name, company size, locations, categories, levels, publication date, landing page URL, company description
- **Companies Endpoint:** `GET /api/public/companies?page=0` returns company profiles with size data
- **Pagination:** 20 results per page, 0-indexed
- **Limitations:** ~966 total companies in their database (curated, not exhaustive); company size categories are broad (small/medium/large, not exact headcount)
- **Legal:** Public API, intended for developer use
- **Contact:** api@themuse.com

**Example:**
```
GET https://www.themuse.com/api/public/jobs?page=0&category=Software%20Engineer&location=United%20States
```

### 2. Adzuna API ★★★★☆

Large job aggregator with good US coverage and salary analytics.

- **URL:** `https://api.adzuna.com/v1/api/jobs/us/search/{page}`
- **Auth:** `app_id` + `app_key` (free registration)
- **Rate Limits:** Generous free tier (exact limits not publicly documented; can request increases)
- **Cost:** Free tier available
- **Data Format:** JSON, JSONP, HTML, XLSX
- **Company Size Filter:** No direct filter, but company name is returned
- **Search Filters:** Keywords, location, category, salary range, full-time/part-time/contract, distance
- **Endpoints:**
  - Job search (9 endpoints total)
  - Salary histogram
  - Top companies
  - Category list
  - Historical salary data
- **Coverage:** 12 countries including US
- **Limitations:** No company size filtering; would need to cross-reference company sizes externally
- **Legal:** Requires attribution; terms of service at developer.adzuna.com

**Example:**
```
GET https://api.adzuna.com/v1/api/jobs/us/search/1?app_id=XXX&app_key=XXX&what=software+engineer&where=united+states
```

### 3. RemoteOK API ★★★★☆

Simple, free, tech-focused remote job API.

- **URL:** `https://remoteok.com/api`
- **Auth:** None required
- **Rate Limits:** Not explicitly documented; be reasonable
- **Cost:** Free
- **Data Format:** JSON array
- **Company Size Filter:** No
- **Response Fields:** slug, id, date, company, position, tags (technologies), description (HTML), location, salary_min, salary_max, apply_url
- **Limitations:** Remote jobs only; no company size data; must link back to RemoteOK URLs (required by ToS); no search/filter params — returns all recent jobs as one dump
- **Legal:** Must link back to RemoteOK with a follow link and credit them as source. Cannot use their logo without permission.
- **Note:** ~30,000+ listings; response can be large; data includes salary ranges when available

**Example:**
```
GET https://remoteok.com/api
```

### 4. Jobicy API ★★★★☆

Clean free API for remote jobs with geographic and category filtering.

- **URL:** `https://jobicy.com/api/v2/remote-jobs`
- **Auth:** None required
- **Rate Limits:** A few times per day is sufficient; excessive polling blocked
- **Cost:** Free
- **Data Format:** JSON
- **Company Size Filter:** No
- **Filters:** `count` (1-100), `geo` (e.g., "usa"), `industry` (category), `tag` (keyword search in title/description)
- **Response Fields:** Job title, company, location, job type, URL, description, publication date
- **Limitations:** Remote jobs only; 100 jobs max per request; no company size data
- **Legal:** Must attribute links back to Jobicy.com; do not redistribute to third-party job platforms

**Example:**
```
GET https://jobicy.com/api/v2/remote-jobs?count=50&geo=usa&industry=engineering&tag=software
```

### 5. Himalayas API ★★★★☆

Free, no-auth API for remote jobs with excellent filtering.

- **URL:** `https://himalayas.app/jobs/api` (browse) or `https://himalayas.app/jobs/api/search` (search)
- **Auth:** None required
- **Rate Limits:** 20 jobs per request (reduced from higher limits in March 2025)
- **Cost:** Free
- **Data Format:** JSON
- **Company Size Filter:** No direct filter
- **Search Filters:** keyword, country, worldwide availability, seniority, employment type, company slug, timezone, sort order
- **Limitations:** Remote-focused; 20 items per request; must credit Himalayas as source
- **Legal:** Attribution required

### 6. Hacker News "Who's Hiring" ★★★★☆

Monthly threads with jobs from startups (overwhelmingly small companies <500 employees).

- **Access Method:** HN Firebase API
- **URL:** `https://hacker-news.firebaseio.com/v0/item/{thread_id}.json`
- **Auth:** None
- **Rate Limits:** None documented for read access
- **Cost:** Free
- **Data Format:** JSON (but job posts are unstructured text in comments)
- **Company Size Filter:** Not structured, but virtually all HN posting companies are small/medium
- **How It Works:**
  1. Find the monthly "Who is Hiring?" thread (posted by user `whoishiring` on 1st of each month)
  2. Fetch the thread to get `kids` array (comment IDs)
  3. Fetch each comment for job details
- **Parsing Challenge:** Comments are freeform text; need NLP or regex to extract company, role, location, salary, tech stack
- **Pre-Built Solutions:**
  - [hnhiring.com](https://hnhiring.com/) — Indexed archive of 58,533+ job ads since Jan 2018
  - [gabfl/hn-whoishiring](https://github.com/gabfl/hn-whoishiring) — FastAPI app to manage HN Who's Hiring posts
  - Apify HN Jobs Scraper — deterministic parser, no AI required, structured output
- **Legal:** HN API is public and free to use

---

## Tier 2 — Useful APIs with Some Limitations

### 7. Jooble API ★★★☆☆

Job aggregator with wide coverage.

- **URL:** `https://jooble.org/api/`
- **Auth:** API key (free registration via form)
- **Rate Limits:** Not publicly documented
- **Cost:** Free (after approval)
- **Data Format:** JSON
- **Company Size Filter:** No
- **Search Params:** Keywords, location
- **Limitations:** Requires form submission for API access; documentation sparse

### 8. Findwork API ★★★☆☆

Dev/design job aggregator pulling from HN, RemoteOK, WWR, Dribbble.

- **URL:** `https://findwork.dev/api/jobs/`
- **Auth:** API key required
- **Rate Limits:** Not documented
- **Cost:** Free tier available
- **Data Format:** JSON
- **Company Size Filter:** No
- **Filters:** Geography, employment type, full-text search
- **Limitations:** Unclear current status and tier limits

### 9. Arbeitnow API ★★★☆☆

European-focused job board with some remote/US listings.

- **URL:** `https://www.arbeitnow.com/api/job-board-api`
- **Auth:** None required
- **Rate Limits:** Use proxies for heavy usage
- **Cost:** Free
- **Data Format:** JSON
- **Company Size Filter:** No
- **Limitations:** Primarily European; limited US coverage

### 10. Remotive API ★★★☆☆

Curated remote jobs with category filtering.

- **URL:** `https://remotive.com/api/remote-jobs`
- **Auth:** None required
- **Rate Limits:** Max 4 requests/day recommended; >2/min will be blocked
- **Cost:** Free
- **Data Format:** JSON
- **Company Size Filter:** No
- **Filters:** Category, company name (partial match)
- **Response Fields:** ID, URL, title, company name, logo, category, job type, publication date, salary, location
- **Limitations:** Very restrictive rate limits; not allowed to submit to Google Jobs, LinkedIn, Jooble; remote only
- **Legal:** Attribution required; strict redistribution rules

### 11. Careerjet API ★★★☆☆

International job search engine.

- **URL:** `https://www.careerjet.com/partners/api/`
- **Auth:** API key (free registration)
- **Rate Limits:** 1,000 requests/hour
- **Cost:** Free
- **Data Format:** JSON
- **Company Size Filter:** No
- **Limitations:** Older API; limited documentation; no HTTPS on some endpoints

### 12. Reed API ★★★☆☆

UK-focused but has some international coverage.

- **URL:** `https://www.reed.co.uk/api/1.0/search`
- **Auth:** API key (free registration)
- **Rate Limits:** Not documented
- **Cost:** Free
- **Data Format:** JSON
- **Company Size Filter:** No
- **Limitations:** Primarily UK-focused; less useful for US-only searches

### 13. USAJobs API ★★★☆☆

See [Government & Public Data](#government--public-data) section below.

---

## Tier 3 — Paid APIs and Aggregators

### 14. TheirStack ★★★★☆ (paid)

The most comprehensive aggregator, with company size filtering.

- **URL:** `https://api.theirstack.com/v1/jobs/search`
- **Auth:** API key
- **Rate Limits:** Based on plan credits
- **Cost:** Free tier: 200 API credits/month; Paid: from $59/month
- **Data Format:** JSON
- **Company Size Filter:** YES — `min_employees`, `max_employees` parameters
- **Coverage:** 324k+ sources (LinkedIn, Indeed, Glassdoor, 16+ job boards, ATS platforms)
- **Other Filters:** Title, location, seniority, salary, technology, company, industry, funding
- **Enriched Data:** Company size, industry, funding, tech stack, location
- **Limitations:** Free tier is very limited (200 credits); expensive at scale
- **Best For:** If budget allows, this is the single best API for the specific use case (SWE + US + <500 employees)

### 15. SerpApi (Google Jobs) ★★★☆☆ (paid)

Programmatic access to Google Jobs search results.

- **URL:** `https://serpapi.com/google-jobs-api`
- **Auth:** API key
- **Rate Limits:** Based on plan
- **Cost:** Free: 250 searches/month; Paid: from $75/month (5,000 searches)
- **Data Format:** JSON
- **Company Size Filter:** No (but Google aggregates from many sources)
- **Capabilities:** Full Google Jobs search with all filters; returns job titles, companies, locations, descriptions, apply links, salary estimates
- **Limitations:** Expensive per-query; no company size data; each search = 1 credit

### 16. Fantastic.jobs API ★★★☆☆

Access to 8M+ jobs/month from ATS platforms.

- **URL:** Via RapidAPI or direct
- **Auth:** API key
- **Cost:** Paid tiers
- **Company Size Filter:** Available on some endpoints

### 17. Apify Scrapers ★★★☆☆ (paid per-use)

Pre-built scrapers for specific platforms (LinkedIn, Indeed, Dice, Wellfound, HN, YC).

- **Pricing:** Pay-per-use compute; free tier for small volumes
- **Platforms Available:** LinkedIn Jobs, Indeed, Dice, Wellfound, YC Jobs, HN Who's Hiring, Glassdoor, ZipRecruiter
- **Company Size Filter:** LinkedIn scraper supports employee count filter
- **Limitations:** Third-party service; scraping ToS risks; costs add up

---

## Tier 4 — Restricted/Deprecated/No Public API

### Indeed ★☆☆☆☆

- **Status:** The Publisher API (Job Search) is **deprecated and closed to new integrations**
- **Current APIs:** Job Sync API and Sponsored Jobs API exist but are for ATS partners/employers only (not job seekers)
- **Requirements:** Partner application, OAuth 2.0, six-week integration process
- **Cost:** Sponsored Jobs API charges based on sponsorship spend (policy effective Dec 2024)
- **RSS Feeds:** Indeed RSS feeds (`rss.indeed.com/rss?q=...`) may still work but Indeed is moving away from XML/RSS entirely in 2025
- **Bottom Line:** No viable programmatic access for personal job search projects

### LinkedIn ★☆☆☆☆

- **Status:** No public job search API available
- **Official API:** Job Posting API exists but requires LinkedIn partnership (for ATS/recruiting platforms only)
- **Company Size Filter:** LinkedIn's UI supports 1-10, 11-50, 51-200, 201-500, 501-1000, etc. but this is not available via any public API
- **Rate Limits:** 100-500 requests/day for authorized apps
- **Workarounds:** Third-party scrapers (Apify, Piloterr) and SerpApi can access LinkedIn job data
- **Legal Risk:** LinkedIn actively litigates against scrapers; ToS prohibit scraping
- **Bottom Line:** Scraping LinkedIn carries the highest legal risk of any job board

### Glassdoor ★☆☆☆☆

- **Status:** Legacy Partner API is **closed to new applicants** as of 2025
- **Current API:** No modern public API; no SCIM/REST user management API
- **Workarounds:** Third-party scrapers (Bright Data, OpenWeb Ninja) or JobSpy library
- **Bottom Line:** No direct programmatic access available for new developers

### ZipRecruiter ★★☆☆☆

- **Status:** Partner API exists but requires ATS integration partnership
- **Access:** Contact atsintegrations@ziprecruiter.com
- **APIs:** Jobs API, Questions API, Features API, XML Feed Import, Apply Webhook
- **Requirements:** Partner registration, API key, integration review process
- **Bottom Line:** Not available for personal use; designed for ATS/recruiting platforms

### Monster ★☆☆☆☆

- **Status:** No documented public API found
- **Bottom Line:** No viable programmatic access

### Dice ★☆☆☆☆

- **Status:** Official Dice API was **shut down in October 2017**
- **Workarounds:** Apify scrapers available
- **Bottom Line:** No official API; scraping only

### Wellfound (formerly AngelList) ★★☆☆☆

- **Status:** No documented public API for job listings
- **Architecture:** Uses GraphQL internally (data embedded in `__NEXT_DATA__` script tags)
- **Workarounds:** Reverse-engineer GraphQL endpoints or use Apify scrapers
- **Coverage:** 130,000+ active listings from 35,000+ companies (mostly startups — great for <500 employee filter)
- **Bottom Line:** Excellent data source for startups but requires scraping

### Stack Overflow Jobs ★☆☆☆☆

- **Status:** Stack Overflow Jobs was **discontinued** (shut down in March 2022)
- **Bottom Line:** Dead. Not available.

### GitHub Jobs ★☆☆☆☆

- **Status:** GitHub Jobs was **discontinued** in May 2021
- **Bottom Line:** Dead. Not available.

### Built In ★★☆☆☆

- **Status:** No public API found
- **Coverage:** Excellent for US tech jobs across major cities (SF, NYC, Seattle, Denver, Boston, etc.)
- **Workaround:** Scraping only
- **Bottom Line:** Good data source but no API

---

## ATS Platform Public APIs

These are **free, no-auth, public APIs** from Applicant Tracking Systems. Each company using these ATS platforms exposes their job board through a standardized endpoint. You need to know the company's board token.

### Greenhouse ★★★★★

- **Endpoint:** `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true`
- **Auth:** None required for GET endpoints
- **Rate Limits:** Not rate limited (cached)
- **Data:** JSON — offices, departments, job listings with full descriptions
- **Limitations:** No search/filter; returns all jobs for one company; need to know board tokens
- **Note:** Thousands of tech companies use Greenhouse

### Lever ★★★★★

- **Endpoint:** `GET https://api.lever.co/v0/postings/{company_slug}`
- **Auth:** None required
- **Rate Limits:** Not documented
- **Data:** JSON or HTML
- **Limitations:** Returns all postings for one company; limited filtering

### Ashby ★★★★☆

- **Endpoint:** `GET https://api.ashbyhq.com/posting-api/job-board/{company_slug}?includeCompensation=true`
- **Auth:** None required
- **Data:** JSON with compensation data

### Workable ★★★☆☆

- **Endpoint:** `GET https://apply.workable.com/api/v1/widget/accounts/{company_slug}`
- **Auth:** None required
- **Data:** JSON

### Recruitee ★★★☆☆

- **Endpoint:** `GET https://{company_slug}.recruitee.com/api/offers`
- **Auth:** None required
- **Data:** JSON

### Strategy for ATS APIs

The challenge is **discovering board tokens**. Approaches:
- Use [github.com/plibither8/jobber](https://github.com/plibither8/jobber) — unified API for Ashby, Greenhouse, Lever
- Use [github.com/adgramigna/job-board-scraper](https://github.com/adgramigna/job-board-scraper) — scrapes Greenhouse, Lever, Ashby, Rippling
- Maintain a curated list of known startup board tokens
- Use [unified.to](https://unified.to/) — commercial unified ATS API (60+ platforms)

---

## Open Source Tools

### JobSpy ★★★★★ (Best Overall)

The most popular open-source job scraping library.

- **GitHub:** [speedyapply/JobSpy](https://github.com/speedyapply/JobSpy)
- **Stars:** 3,100+
- **License:** MIT
- **Language:** Python (pip install python-jobspy)
- **Requires:** Python 3.10+
- **Supported Sites:** LinkedIn, Indeed, Glassdoor, Google, ZipRecruiter, Bayt, Naukri, BDJobs
- **Key Features:**
  - Concurrent scraping across all supported boards
  - Standardized pandas DataFrame output
  - Filters: location, distance, job_type, is_remote, hours_old, easy_apply
  - Proxy support for rate limit mitigation
  - Salary normalization
- **Company Size Filter:** Not built-in (post-process DataFrames)
- **Rate Limit Notes:**
  - Indeed: No rate limiting (best scraper)
  - LinkedIn: Rate limits around page 10 with single IP; proxies recommended
  - All platforms cap at ~1,000 jobs per search
- **Legal Note:** Scraping may violate site ToS; personal use is generally low-risk

### JobFunnel

- **GitHub:** [PaulMcInnis/JobFunnel](https://github.com/PaulMcInnis/JobFunnel)
- **Purpose:** Scrape job websites into a single spreadsheet with deduplication

### job-board-scraper

- **GitHub:** [adgramigna/job-board-scraper](https://github.com/adgramigna/job-board-scraper)
- **Purpose:** Scrapes Greenhouse, Lever, Ashby, and Rippling job boards

### Jobber

- **GitHub:** [plibither8/jobber](https://github.com/plibither8/jobber)
- **Purpose:** Unified API to fetch listings from Ashby, Greenhouse, Lever, etc.

### hn-whoishiring

- **GitHub:** [gabfl/hn-whoishiring](https://github.com/gabfl/hn-whoishiring)
- **Purpose:** FastAPI/FastUI app for HN Who's Hiring posts; SQLite storage

### YC OSS API

- **GitHub:** [yc-oss/api](https://github.com/yc-oss/api)
- **Endpoint:** `https://yc-oss.github.io/api/meta.json`
- **Purpose:** Public API for Y Combinator-funded companies (team size, industry, etc.)

### JobApis (PHP)

- **GitHub:** [jobapis.github.io/open-source](https://jobapis.github.io/open-source/)
- **Purpose:** PHP clients for multiple job board APIs (The Muse, Careerjet, etc.)

---

## RSS Feeds

| Source | RSS URL | Update Frequency | Auth | Notes |
|--------|---------|------------------|------|-------|
| We Work Remotely | `https://weworkremotely.com/remote-jobs.rss` | Real-time | None | Category feeds also available (programming, etc.) |
| We Work Remotely (Programming) | `https://weworkremotely.com/categories/remote-programming-jobs.rss` | Real-time | None | Software-specific |
| Jobicy | `https://jobicy.com/feed/newjobs` | Daily | None | Remote jobs |
| Remotive | `https://remotive.com/remote-jobs/feed/` | Daily | None | Remote tech jobs |
| Himalayas | `https://himalayas.app/rss` | Ongoing | None | Remote jobs |
| JobsCollider | Via GitHub repo | Hourly | None | Category-based feeds |
| Indeed (legacy) | `https://rss.indeed.com/rss?q=software+engineer&l=united+states` | Unknown | None | May be deprecated; Indeed moving away from RSS |
| USAJobs | Via API | Real-time | API key | Government jobs |

**Note:** We Work Remotely requires attribution when using their RSS feeds.

---

## Government & Public Data

### USAJobs API ★★★☆☆

- **URL:** `https://data.usajobs.gov/api/search`
- **Auth:** API key + user agent header (email address); free registration at developer.usajobs.gov
- **Rate Limits:** Not publicly specified
- **Cost:** Free
- **Data Format:** JSON
- **Search Params:** keyword, location, job category, agency, salary range, hiring path, travel, security clearance
- **Company Size Filter:** N/A (government agencies)
- **Limitations:** Government jobs only; most agencies are large, but there are small agencies and government-adjacent orgs
- **Best For:** Government software engineering roles

### Bureau of Labor Statistics (BLS) API

- **URL:** `https://api.bls.gov/publicAPI/v2/timeseries/data/`
- **Auth:** Optional (registration increases rate limits)
- **Rate Limits:** 25 queries/day without key; 500/day with key
- **Cost:** Free
- **Data Format:** JSON, Excel
- **Relevance:** JOLTS (Job Openings and Labor Turnover Survey) provides aggregate labor market data — not individual job listings but useful for market analysis (trends, openings by industry)
- **Limitations:** Statistical/aggregate data only, not individual job postings

### Data.gov

- **URL:** catalog.data.gov
- **Relevance:** Federal datasets including employment statistics
- **Limitation:** Macro-level data, not individual job listings

---

## Company Size Filtering Strategy

Since most job APIs do NOT provide company size filtering, here is a practical strategy:

### APIs with Built-In Company Size Filtering

| API | Filter Type | Values |
|-----|-------------|--------|
| **The Muse** | Company size category | `small`, `medium`, `large` (on companies endpoint) |
| **TheirStack** (paid) | Employee count range | `min_employees`, `max_employees` (exact numbers) |
| **LinkedIn UI** | Employee count ranges | 1-10, 11-50, 51-200, 201-500 (not available via API) |
| **Apify LinkedIn Scraper** | Employee count | Advanced filter on number of employees |

### Cross-Reference Strategy for Other APIs

For APIs without company size data, use a two-step process:

1. **Collect jobs** from APIs (Adzuna, RemoteOK, Jobicy, etc.)
2. **Look up company size** via:
   - **The Muse Companies API:** `GET /api/public/companies?page=0` — returns size field
   - **YC OSS API:** For Y Combinator companies, team size is available
   - **LinkedIn Company Search:** Manual or via third-party scraper
   - **Crunchbase API:** Company data including employee count (paid)
   - **Coresignal API:** Employee count API (paid)
   - **Clearbit/Apollo:** Company enrichment APIs (freemium)
   - **Manual heuristic:** Companies posting on HN "Who's Hiring", RemoteOK, Wellfound, and YC are overwhelmingly <500 employees

### Platforms That Naturally Skew Small (<500 Employees)

These sources overwhelmingly feature small-to-medium companies:
- Hacker News "Who's Hiring" threads
- Wellfound (formerly AngelList)
- Y Combinator job listings
- RemoteOK
- We Work Remotely
- Himalayas
- Jobicy

---

## Legal Considerations

### Safe (Official APIs with ToS allowing data access)
- The Muse API — designed for developers
- Adzuna API — public developer program
- USAJobs API — government public data
- RemoteOK API — explicitly offered, requires attribution
- Jobicy API — explicitly offered, requires attribution
- Himalayas API — explicitly offered, requires attribution
- Jooble API — developer program
- BLS API — government public data
- ATS APIs (Greenhouse, Lever, Ashby) — publicly accessible by design

### Moderate Risk (Scraping publicly visible data)
- JobSpy scraping Indeed — Indeed data is public; CFAA case law (hiQ v. LinkedIn) supports scraping public data; but violates Indeed ToS
- JobSpy scraping Google Jobs — low risk (public search results)
- Scraping Wellfound — uses anti-scraping measures; GraphQL is public but not documented as an API
- Scraping Built In — no API; ToS may prohibit

### Higher Risk (Do not recommend)
- LinkedIn scraping — LinkedIn actively litigates; most restrictive ToS; rate limits aggressively
- Bypassing login walls, CAPTCHAs, or other technical barriers — may violate CFAA
- Redistributing scraped data commercially

### Key Legal Precedents
- **hiQ Labs v. LinkedIn (9th Circuit):** Scraping publicly accessible data does not violate CFAA. However, contract law (ToS) may still apply.
- **Van Buren v. United States (Supreme Court, 2021):** Narrowed CFAA — accessing data you're authorized to see, even for unauthorized purposes, is not a CFAA violation.
- **General principle:** Scraping public data for personal use is lowest-risk; redistributing or commercializing scraped data increases risk.

---

## Recommended Architecture

### Phase 1: API-First Approach (Free)

```
┌──────────────────────────────────────────────────┐
│                   Job Aggregator                  │
├──────────────────────────────────────────────────┤
│                                                  │
│  Data Sources (APIs):                            │
│  ├── The Muse API (size filter!)                 │
│  ├── Adzuna API (US coverage)                    │
│  ├── RemoteOK API (tech/remote)                  │
│  ├── Jobicy API (remote, US filter)              │
│  ├── Himalayas API (remote, search)              │
│  ├── Jooble API (aggregator)                     │
│  ├── HN Who's Hiring (startup-focused)           │
│  └── USAJobs API (government)                    │
│                                                  │
│  Data Enrichment:                                │
│  ├── The Muse Companies API → company size       │
│  ├── YC OSS API → startup team sizes             │
│  └── Heuristic: source = HN/RemoteOK → small co │
│                                                  │
│  Storage: SQLite/PostgreSQL                      │
│  Deduplication: by job URL + company + title      │
│  Schedule: Daily cron job                        │
│                                                  │
└──────────────────────────────────────────────────┘
```

### Phase 2: Add ATS Direct Access (Free)

Maintain a curated list of interesting small/medium companies and their Greenhouse/Lever/Ashby board tokens. Query their public job board APIs directly.

### Phase 3: Add Scraping (Optional)

Use JobSpy to fill gaps from Indeed, Google Jobs, and ZipRecruiter. Use proxies and rate limiting to avoid blocks.

### Phase 4: Add Paid Sources (If Budget Allows)

- TheirStack ($59/mo) for the most comprehensive coverage with company size filtering
- SerpApi ($75/mo) for Google Jobs structured data

---

## Quick Reference: All Sources Summary

| Source | Type | Auth | Cost | Size Filter | US SWE Jobs | Viability |
|--------|------|------|------|-------------|-------------|-----------|
| The Muse | API | Optional key | Free | YES (S/M/L) | Good | ★★★★★ |
| Adzuna | API | API key | Free tier | No | Excellent | ★★★★☆ |
| RemoteOK | API | None | Free | No | Good (remote) | ★★★★☆ |
| Jobicy | API | None | Free | No | Good (remote) | ★★★★☆ |
| Himalayas | API | None | Free | No | Good (remote) | ★★★★☆ |
| HN Who's Hiring | API | None | Free | Inherent (small) | Good | ★★★★☆ |
| Greenhouse ATS | API | None | Free | No | Per-company | ★★★★★ |
| Lever ATS | API | None | Free | No | Per-company | ★★★★★ |
| Ashby ATS | API | None | Free | No | Per-company | ★★★★☆ |
| Jooble | API | API key | Free | No | Good | ★★★☆☆ |
| Findwork | API | API key | Free tier | No | Good | ★★★☆☆ |
| Careerjet | API | API key | Free | No | Fair | ★★★☆☆ |
| USAJobs | API | API key | Free | N/A (govt) | Fair | ★★★☆☆ |
| Remotive | API | None | Free | No | Fair (remote) | ★★★☆☆ |
| Arbeitnow | API | None | Free | No | Limited (EU) | ★★☆☆☆ |
| Reed | API | API key | Free | No | Limited (UK) | ★★☆☆☆ |
| WWR | RSS | None | Free | No | Good (remote) | ★★★★☆ |
| JobSpy | OSS scraper | N/A | Free | No (post-process) | Excellent | ★★★★★ |
| TheirStack | API | API key | $59/mo+ | YES (exact) | Excellent | ★★★★☆ |
| SerpApi | API | API key | $75/mo+ | No | Excellent | ★★★☆☆ |
| Indeed | Deprecated | N/A | N/A | No | N/A | ★☆☆☆☆ |
| LinkedIn | No public API | N/A | N/A | UI only | N/A | ★☆☆☆☆ |
| Glassdoor | Closed | N/A | N/A | No | N/A | ★☆☆☆☆ |
| ZipRecruiter | Partner only | N/A | N/A | No | N/A | ★☆☆☆☆ |
| Dice | Shut down 2017 | N/A | N/A | No | N/A | ★☆☆☆☆ |
| Wellfound | No public API | N/A | N/A | No | N/A | ★★☆☆☆ |
| Stack Overflow | Dead | N/A | N/A | N/A | N/A | ☆☆☆☆☆ |
| GitHub Jobs | Dead | N/A | N/A | N/A | N/A | ☆☆☆☆☆ |

---

*Research compiled April 2026. API availability and terms may change. Always verify current status before building integrations.*
