# Spec 05: Enrichment & Classification Pipeline

## Problem

Jobs arrive from scrapers with raw data: title, description, company name, location string, maybe salary. To filter usefully ("senior backend roles at AI-native companies paying >$200k"), every job needs classification. No system currently tracks what has been enriched or controls costs.

## Goal

`jbs enrich` processes unclassified jobs and companies through a five-stage pipeline: data cleanup, rule-based extraction, LLM job classification, LLM company enrichment, and local embedding generation. Idempotent, incremental, cost-tracked.

## Core Design Decision: Dual LLM Backend

Two backends for LLM classification, selected automatically:

1. **Primary: Claude CLI** (`claude` subprocess). Uses the user's existing Claude subscription (Pro/Max) via the `claude` CLI tool. No API key needed. Jobs are batched 10 per call with descriptions truncated to 1500 chars to keep runtime reasonable. This is the default path.

2. **Optional fast path: Anthropic Batch API** (`pip install anthropic`). If `ANTHROPIC_API_KEY` is set, uses the Message Batches API instead. Each job gets its own call with the full description -- no truncation. Submit all at once, results in ~5 minutes. 50% cheaper per-token than standard API, with prompt caching.

**Selection logic:**
```python
def get_llm_backend():
    if os.environ.get("ANTHROPIC_API_KEY") and HAS_ANTHROPIC:
        return BatchAPIBackend()   # fast path: individual calls, full descriptions
    if shutil.which("claude"):
        return ClaudeCLIBackend()  # default: batched calls via subscription
    return None
```

**Why Claude CLI as default?** Most users already have a Claude subscription and the `claude` CLI installed. Requiring a separate API key and billing account is friction. The CLI uses subscription auth, so it "just works" for anyone who has Claude Code installed.

**Why offer the Batch API?** It's faster, more accurate (full descriptions, no truncation), and cheaper per-token. Power users who do frequent enrichment runs will appreciate it.

**Dependencies:**
- Default: `claude` CLI in PATH (bundled with Claude Code, no pip dependency)
- Optional: `anthropic>=0.40` (only if user wants Batch API fast path): `pip install -e '.[enrich]'`
- Everything except LLM stages works without either

## Pipeline Architecture

```
+---------------------------------------------------+
|  Stage 0: Description Cleanup (free, instant)     |
|  HTML->markdown, encoding fixes, boilerplate      |
+---------------------------------------------------+
|  Stage 1: Rule-Based (free, instant, ~2s)         |
|  seniority, is_management, salary, visa, years    |
+---------------------------------------------------+
|  Stage 2: LLM Jobs (Haiku Batch, ~$1 for 3000)   |
|  engineering_role, seniority, domain, tech_stack,  |
|  summary                                          |
+---------------------------------------------------+
|  Stage 3: LLM Companies (Haiku Batch, ~$0.20)    |
|  description, industry, ai_native, funding,       |
|  size_estimate                                    |
+---------------------------------------------------+
|  Stage 4: Embeddings (free, local, ~30s)          |
|  summary vectors (384d), description vectors      |
|  (768d), stored in sqlite-vec                     |
+---------------------------------------------------+
```

Each stage processes rows where `enriched_at IS NULL` (or the relevant classification field is NULL). Jobs don't change after posting, so no content-change detection is needed.

## New DB Columns

Add to the `jobs` table (beyond what spec 02 already defines):

```sql
ALTER TABLE jobs ADD COLUMN job_summary       TEXT;
ALTER TABLE jobs ADD COLUMN visa_sponsorship  TEXT CHECK(
    visa_sponsorship IS NULL OR
    visa_sponsorship IN ('sponsors', 'no_sponsorship', 'unknown')
);
ALTER TABLE jobs ADD COLUMN years_experience  INTEGER;
ALTER TABLE jobs ADD COLUMN is_management     BOOLEAN;
```

The following columns are already defined in spec 02 and need no additional migration:
- `jobs`: `tech_stack`, `salary_usd_min`, `salary_usd_max`, `enriched_at`, `engineering_role`, `seniority`, `domain`
- `companies`: `description`, `industry`, `ai_native`, `funding_stage`, `size_estimate`, `tech_stack`, `enriched_at`
- `enrichment_runs` table (full schema in spec 02)

---

## Stage 0: Description Cleanup (free, instant)

Before any enrichment, fix known data quality issues. These are applied to the stored `description` column (or in memory, as noted).

### 0a. Greenhouse HTML to Markdown

Greenhouse descriptions are stored as raw HTML in the DB. The Greenhouse boards API returns HTML content in two forms: raw HTML (`<div>...`) and entity-encoded HTML (`&lt;div&gt;...`). Stage 0a handles both by matching `description LIKE '<%' OR description LIKE '&lt;%'`.

The `html_to_markdown()` function in `jbs/util.py` handles the full cleanup:
1. `html.unescape()` decodes entity-encoded HTML (`&lt;` -> `<`, `&quot;` -> `"`, etc.)
2. Strips `<img src="data:...">` tags (inline base64 images that inflate descriptions to MBs)
3. `markdownify` converts the clean HTML to markdown
4. Strips any remaining markdown-format data URIs (`![](data:...)`) from the output

```python
# In jbs/util.py
_DATA_IMG_RE = re.compile(
    r'<img[^>]*\ssrc=["\']data:[^"\']*["\'][^>]*/?>',
    re.IGNORECASE,
)
_MD_DATA_IMG_RE = re.compile(
    r'!\[[^\]]*\]\(data:[^)]+\)',
)

def html_to_markdown(raw_html: str) -> str:
    if not raw_html:
        return ""
    decoded = html_mod.unescape(raw_html)           # entity decode
    decoded = _DATA_IMG_RE.sub('', decoded)          # strip base64 img tags
    result = md(decoded).strip()                     # convert to markdown
    result = _MD_DATA_IMG_RE.sub('', result)         # strip markdown data URIs
    return result
```

```python
# In jbs/enrich.py — Stage 0a
rows = conn.execute("""
    SELECT id, description FROM jobs
    WHERE site = 'greenhouse'
      AND (description LIKE '<%' OR description LIKE '&lt;%')
""").fetchall()
for row in rows:
    md = html_to_markdown(row["description"])
    conn.execute(
        "UPDATE jobs SET description = ? WHERE id = ?",
        (md, row["id"]),
    )
```

This is a one-time fix for existing data; new scrapes should store markdown from the start.

### 0b. Base64 Data URI Stripping

Some descriptions (particularly from KnowBe4 Greenhouse boards) contain inline base64 `data:` images that inflate them to 1.8M characters, causing OOM during embedding generation. Stage 0b runs on **all** jobs (not just Greenhouse) and catches data URIs that survived prior conversion -- for example, descriptions that were already converted to markdown in an earlier run but still contain `![](data:image/...;base64,...)` patterns.

```python
# In jbs/enrich.py — Stage 0b
rows = conn.execute("""
    SELECT id, description FROM jobs
    WHERE description LIKE '%data:image/%'
      OR description LIKE '%data:application/%'
""").fetchall()
for row in rows:
    cleaned = strip_data_uris(row["description"])
    if cleaned != row["description"]:
        conn.execute(
            "UPDATE jobs SET description = ? WHERE id = ?",
            (cleaned, row["id"]),
        )
```

The `strip_data_uris()` helper in `jbs/util.py` strips both HTML `<img src="data:...">` tags and markdown `![](data:...)` patterns.

As defense-in-depth, `embeddings.py` also truncates descriptions to `MAX_DESC_CHARS = 30_000` before embedding, preventing OOM even if a large description slips through cleanup.

### 0c. RemoteOK Encoding Fix

~78% of RemoteOK descriptions have broken Unicode (smart quotes appearing as `a`). Run through encoding normalization to detect and fix UTF-8 mojibake.

```python
def fix_remoteok_encoding(store):
    """Fix UTF-8 mojibake in RemoteOK descriptions."""
    rows = store.conn.execute("""
        SELECT id, description FROM jobs
        WHERE site = 'remoteok'
          AND description LIKE '%â%'
    """).fetchall()
    for job_id, desc in rows:
        fixed = fix_mojibake(desc)  # detect latin-1 decoded as utf-8, re-encode
        store.conn.execute(
            "UPDATE jobs SET description = ? WHERE id = ?",
            (fixed, job_id),
        )
    store.conn.commit()
    return len(rows)
```

### 0d. Boilerplate Stripping (in memory only)

42-71% of Greenhouse/Ashby descriptions have legal boilerplate (EEO statements, ADA disclosures, privacy notices). Strip these with regex patterns matching common boilerplate sections.

**Important:** Boilerplate is stripped in memory at enrichment time as a preprocessing step, not persisted. The raw description stays in the DB for `jbs show`. FTS5 indexes the raw description -- boilerplate won't match engineering search terms anyway.

```python
_BOILERPLATE_PATTERNS = [
    re.compile(r'(?:^|\n)#{1,3}\s*(?:Equal Opportunity|EEO|Diversity).*', re.DOTALL | re.IGNORECASE),
    re.compile(r'(?:^|\n)#{1,3}\s*(?:Privacy|Data Protection|GDPR).*', re.DOTALL | re.IGNORECASE),
    re.compile(r'(?:^|\n)(?:We are an equal opportunity|This company is committed to).*', re.DOTALL | re.IGNORECASE),
    re.compile(r'(?:^|\n)#{1,3}\s*(?:Accommodation|ADA|Disability).*', re.DOTALL | re.IGNORECASE),
]

def strip_boilerplate(text: str) -> str:
    """Remove legal boilerplate from job descriptions (in memory, not persisted)."""
    for pattern in _BOILERPLATE_PATTERNS:
        text = pattern.sub('', text)
    return text.strip()
```

### 0e. Ashby Structured Salary Capture

The Ashby API returns `compensationTiers` but the scraper isn't extracting them properly. Fix the scraper to populate `min_amount`/`max_amount`/`currency` from structured data. This is a scraper fix, not an enrichment fix, but it belongs in the data quality scope of this spec.

---

## Stage 1: Rule-Based Extraction (free, instant, ~2s for 3000 jobs)

Pure regex/keyword extraction. No LLM. Run on ALL jobs, not just engineering roles.

### Fields Extracted

| Field | Approach | Estimated Accuracy |
|---|---|---|
| `seniority` (partial) | Title keyword matching (see patterns below) | ~70% of cases resolved |
| `is_management` (partial) | Title contains Manager, Director, VP, Head of, Chief | ~95% |
| `salary_usd_min` / `salary_usd_max` | Existing `extract_salary_from_text()` + static FX + structured source data | ~95% structured, ~25% text |
| `visa_sponsorship` | Regex patterns on description (~10 patterns, three values) | ~80% when mentioned |
| `years_experience` | Regex on description, extract minimum number | ~90% when mentioned |

### Seniority Patterns (title only)

```python
_SENIORITY_PATTERNS = [
    (r'\bintern\b', 'intern'),
    (r'\b(?:junior|jr\.?)\b', 'junior'),
    (r'\b(?:senior|sr\.?)\b', 'senior'),
    (r'\bstaff\b', 'staff'),
    (r'\b(?:principal|distinguished)\b', 'principal'),
]

def extract_seniority(title: str) -> str | None:
    """Extract seniority from job title. Returns None if ambiguous or no match."""
    matches = []
    for pattern, level in _SENIORITY_PATTERNS:
        if re.search(pattern, title, re.IGNORECASE):
            matches.append(level)
    return matches[0] if len(matches) == 1 else None  # ambiguous -> defer to LLM
```

### Management Detection

```python
_MANAGEMENT_PATTERNS = re.compile(
    r'\b(?:manager|director|vp|vice\s+president|head\s+of|chief)\b',
    re.IGNORECASE,
)

def extract_is_management(title: str) -> bool:
    return bool(_MANAGEMENT_PATTERNS.search(title))
```

### Salary Normalization

Use existing `extract_salary_from_text()` from `jbs/util.py`. Add static FX conversion for non-USD currencies. Also use structured salary data from sources that provide it (RemoteOK, fixed Ashby).

```python
_FX_TO_USD = {
    'EUR': 1.08,
    'GBP': 1.27,
    'CAD': 0.74,
    'AUD': 0.66,
    'CHF': 1.13,
}

def normalize_salary_to_usd(min_amt, max_amt, currency, interval):
    """Convert salary to annualized USD. Returns (usd_min, usd_max) or (None, None)."""
    if min_amt is None and max_amt is None:
        return None, None

    rate = _FX_TO_USD.get(currency, 1.0) if currency != 'USD' else 1.0

    # Annualize
    multiplier = {'yearly': 1, 'monthly': 12, 'hourly': 2080}.get(interval, 1)

    usd_min = round(min_amt * rate * multiplier) if min_amt else None
    usd_max = round(max_amt * rate * multiplier) if max_amt else None
    return usd_min, usd_max
```

### Visa Sponsorship Detection

```python
_VISA_SPONSORS = re.compile(
    r'visa sponsorship available|will sponsor|we sponsor|h-1b sponsor',
    re.IGNORECASE,
)
_VISA_NO_SPONSOR = re.compile(
    r'no sponsorship|cannot sponsor|must be authorized to work|'
    r'us citizens only|permanent resident|no visa|without sponsorship',
    re.IGNORECASE,
)

def extract_visa(description: str) -> str | None:
    """Returns 'sponsors', 'no_sponsorship', or 'unknown'."""
    if _VISA_SPONSORS.search(description):
        return 'sponsors'
    if _VISA_NO_SPONSOR.search(description):
        return 'no_sponsorship'
    return 'unknown'
```

### Years of Experience

```python
_YEARS_EXP = re.compile(r'(\d+)\+?\s*(?:years?|yrs?)', re.IGNORECASE)

def extract_years_experience(description: str) -> int | None:
    """Extract minimum years of experience from description."""
    matches = _YEARS_EXP.findall(description)
    if matches:
        return min(int(m) for m in matches)  # take the minimum mentioned
    return None
```

### LLM Pre-Filter (`classify_llm_filter`)

Stage 1 classifies each job as `send` or `skip_*` to control which jobs reach the LLM in Stage 2. This saves LLM cost by filtering out jobs that are clearly not relevant before sending them for classification.

```python
_SALARY_FLOOR = 190_000

def classify_llm_filter(title, is_management, seniority, salary_usd_max, max_amount) -> str:
    """Returns: 'send', 'skip_mgmt', 'skip_title', 'skip_salary', 'skip_seniority'.
    Applied in priority order (first match wins). Always recomputed."""
    if is_management:
        return 'skip_mgmt'
    if not _TITLE_KEEP.search(title) and _TITLE_EXCLUDE.search(title):
        return 'skip_title'
    effective_max = salary_usd_max or max_amount
    if effective_max is not None and effective_max < _SALARY_FLOOR:
        return 'skip_salary'
    if seniority in ('intern', 'junior'):
        return 'skip_seniority'
    return 'send'
```

The `llm_filter` column is stored on each job row. Stage 2's WHERE clause respects it: `(llm_filter = 'send' OR llm_filter IS NULL)`.

### What Stage 1 Does NOT Do

- **`tech_stack`** -- delegated to LLM. While regex can match obvious keywords, it misses semantic references ("Google's cloud platform" = GCP, "Meta's ML framework" = PyTorch). Since we're sending full descriptions to the LLM anyway, let it handle this for better accuracy.
- **`engineering_role`** -- needs semantic understanding ("Sales Engineer" = false, "ML Engineer" = true).
- **`domain`** -- needs full description context.
- **`job_summary`** -- fundamentally generative.

### Enrichment Watermark

Stage 1 sets `enriched_at` on ALL jobs it processes. `enriched_at` means "has been through rule-based extraction at minimum." Stage 2 uses its own watermark (`WHERE engineering_role IS NULL AND description IS NOT NULL AND length(description) > 50`) to find jobs needing LLM classification -- it does not rely on `enriched_at`. This means `jbs enrich --stage rules` is useful on its own: jobs get seniority, salary, visa, years_experience even without an API key.

---

## Stage 2: LLM Job Classification (Haiku, ~$1 for 3000 jobs)

Individual classification per job via the Message Batches API. Full description sent (after Stage 0 cleanup applied in memory).

### Input Query

```sql
SELECT id, title, company_raw, description, location_raw, work_arrangement,
       seniority, is_management, salary_usd_min, salary_usd_max
FROM jobs
WHERE engineering_role IS NULL
  AND description IS NOT NULL
  AND length(description) > 50
  AND (llm_filter = 'send' OR llm_filter IS NULL)
ORDER BY date_posted DESC
```

Note: `seniority` and `is_management` from Stage 1 are passed as context so the LLM can confirm or override.

### System Prompt (cached across all requests)

```
You are a job posting classifier for a software engineer's job search tool. Classify the job posting and return ONLY valid JSON (no markdown, no explanation).

Fields to return:
{
  "engineering_role": bool,    // true for software/data/ML/infra/DevOps/SRE/security engineering, QA/SDET.
                               // false for sales, marketing, HR, design, product management, support, recruiting.
                               // Edge cases: "Sales Engineer" = false, "Engineering Manager" = true,
                               // "Technical Program Manager" = false, "Data Analyst" = true only if SQL/Python heavy.
  "seniority": string,         // intern/junior/mid/senior/staff/principal. Use title primarily.
                               // Default "mid" if genuinely unclear. Don't default to "mid" if there are signals.
  "is_management": bool,       // true if the role manages people (Manager/Director/VP/Head of).
                               // "Tech Lead" = false (IC). "Engineering Manager" = true.
  "domain": string | null,     // Only if engineering_role=true. One of:
                               // backend, frontend, fullstack, mobile, devops_infra, data, ml_ai, security, embedded, other
  "tech_stack": string[],      // Technologies mentioned. Use canonical names: "Python" not "python3",
                               // "React" not "ReactJS", "PostgreSQL" not "postgres", "Kubernetes" not "k8s",
                               // "Node.js" not "Node", "TypeScript" not "TS", "Google Cloud" not "GCP",
                               // "Amazon Web Services" not "AWS" (use the full marketing name when ambiguous).
                               // Include languages, frameworks, databases, cloud providers, tools.
                               // Empty array if none mentioned.
  "job_summary": string         // 1-2 sentences. What the role actually does and what makes it notable.
                               // Be specific: "Building real-time fraud detection using Flink and PyTorch at a Series B fintech."
                               // NOT generic: "Software engineer at a tech company."
                               // If engineering_role=false, still summarize what the role is.
}
```

### User Message Per Job

```
Title: {{title}}
Company: {{company}}
Location: {{location}}
Pre-classified seniority: {{seniority or "unknown"}}
Pre-classified management: {{is_management or "unknown"}}
Salary: {{salary range if known, else "not specified"}}

Description:
{{full description, cleaned in memory}}
```

### Post-Processing: `tech_stack` Normalization

Despite canonical name instructions, the LLM will produce variations across 3,000 classifications. Apply a deterministic alias map after parsing:

```python
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
    seen = set()
    result = []
    for item in items:
        canonical = _TECH_ALIASES.get(item.lower(), item)
        if canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result
```

### Implementation: LLM Backend Abstraction

Both backends implement the same interface:

```python
class LLMBackend(ABC):
    @abstractmethod
    def classify_jobs(self, jobs: list[dict], system_prompt: str) -> dict[str, dict]:
        """Classify jobs. Returns {job_id: classification_dict}."""

    @abstractmethod
    def classify_companies(self, companies: list[dict], system_prompt: str) -> dict[str, dict]:
        """Classify companies. Returns {name_normalized: classification_dict}."""
```

#### Claude CLI Backend (default)

Calls the `claude` CLI via `subprocess.run()` with `--output-format json`. Uses subscription auth, no API key needed. Jobs are batched 10 per call with descriptions truncated to 1500 chars.

```python
class ClaudeCLIBackend(LLMBackend):
    BATCH_SIZE = 10
    DESC_LIMIT = 1500

    def classify_jobs(self, jobs, system_prompt):
        batches = [jobs[i:i+self.BATCH_SIZE] for i in range(0, len(jobs), self.BATCH_SIZE)]
        results = {}

        for batch in batches:
            jobs_json = json.dumps([{
                "id": j["id"],
                "title": j["title"],
                "company": j["company_raw"],
                "description": strip_boilerplate(j["description"])[:self.DESC_LIMIT],
                "location": j["location_raw"],
                "seniority": j.get("seniority") or "unknown",
            } for j in batch], indent=2)

            prompt = f"{system_prompt}\n\nClassify each job...\n\nJobs:\n{jobs_json}"
            response_text = self._call_claude(prompt)
            parsed = json.loads(response_text)

            for item in parsed:
                results[item["id"]] = item

        return results

    def _call_claude(self, prompt: str) -> str:
        result = subprocess.run(
            ["claude", "-p", prompt,
             "--model", "claude-haiku-4-5-20251001",
             "--output-format", "json",
             "--max-turns", "1"],
            capture_output=True, text=True, timeout=300,
        )
        wrapper = json.loads(result.stdout)
        return wrapper.get("result", "")
```

**Batching rationale:** 10 jobs x 1500 char descriptions = ~15KB per call. Smaller batches improve reliability — a single timeout loses fewer jobs. ~300 calls for 3000 jobs.

#### Batch API Backend (fast path, requires API key)

Uses the Anthropic Python SDK with the Message Batches API. Individual calls per job with full descriptions.

```python
import anthropic

class BatchAPIBackend(LLMBackend):
    def classify_jobs(self, jobs, system_prompt):
        client = anthropic.Anthropic()

        requests = []
        for job in jobs:
            clean_desc = strip_boilerplate(job["description"])
            requests.append({
                "custom_id": job["id"],
                "params": {
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 300,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": format_job_prompt(job, clean_desc)}],
                },
            })

        # Submit batch
        batch = client.messages.batches.create(requests=requests)

        # Poll until complete (timeout after 1 hour)
        deadline = time.time() + 3600
        while batch.processing_status != "ended":
            if time.time() > deadline:
                raise TimeoutError(f"Batch {batch.id} not completed after 1h")
            time.sleep(30)
            batch = client.messages.batches.retrieve(batch.id)

        # Collect results
        results = {}
        for entry in client.messages.batches.results(batch.id):
            if entry.result.type == "succeeded":
                data = json.loads(entry.result.message.content[0].text)
                results[entry.custom_id] = data
        return results
```

**Key differences:**

| | Claude CLI (default) | Batch API (fast path) |
|---|---|---|
| Auth | Claude subscription | API key |
| Description length | 1500 chars (truncated) | Full (no truncation) |
| Jobs per call | 10 (batched prompt) | 1 (individual) |
| Total time (3000 jobs) | ~10 min | ~5 min |
| Cost | Included in subscription | ~$1.20 (Haiku Batch) |
| Accuracy | Good (~85%) | Best (~95%, full context) |

### Error Handling

- **Per-job failure:** If a single job's classification fails (malformed JSON, API error), log it and continue. The job stays with `engineering_role IS NULL` and will be retried on next `jbs enrich` run. Wrap `json.loads()` in try/except; on parse failure, log the raw response text for debugging.
- **Agent SDK failures:** If a batched call fails, retry the batch once. If it fails again, log the error and continue to the next batch. Individual jobs in failed batches remain unclassified for retry.
- **Batch API failures:** If batch submission fails (network/auth error), fall back to Agent SDK backend if available. If the batch times out after 1 hour, report the batch ID for manual follow-up.
- **Partial failure:** Process all successful entries; skip failures. Failed items remain with `engineering_role IS NULL` for next run.
- Track results in the `enrichment_runs` table.

---

## Stage 3: LLM Company Enrichment (Haiku, ~$0.20 for 600 companies)

Same approach: individual requests via the Message Batches API.

**Dependency:** Stage 3 uses `engineering_role` and `tech_stack` from Stage 2 results to build its prompts. Running `jbs enrich --stage companies` without Stage 2 having completed will produce lower-quality company classifications (no tech stack context, no engineering role filter on sample titles). The full `jbs enrich` pipeline runs stages in order; `--stage companies` alone is for re-runs after prompt changes.

### Input Query

```sql
SELECT c.name, c.name_normalized, c.ats_platform, c.ats_token, c.website,
       GROUP_CONCAT(DISTINCT j.title) as sample_titles,
       GROUP_CONCAT(DISTINCT j.tech_stack) as tech_stacks
FROM companies c
LEFT JOIN jobs j ON j.company_id = c.id AND j.engineering_role = 1
WHERE c.enriched_at IS NULL
GROUP BY c.id
```

### System Prompt

```
You are a company classifier for a software engineer's job search tool. Given a company name and sample job titles, classify the company. Return ONLY valid JSON.

{
  "description": string,        // 1 sentence about what the company does. Be specific.
  "industry": string,           // One of: AI/ML, Developer Tools, FinTech, HealthTech, EdTech,
                                // Cybersecurity, Cloud/Infra, E-Commerce, Media, Enterprise SaaS,
                                // Crypto/Web3, Robotics, Biotech, Automotive, Aerospace/Defense,
                                // Logistics, HR Tech, Legal Tech, Climate Tech, Other
  "ai_native": float,           // 0.0-1.0. How central is AI to the company's core product?
                                // 0.9+ = AI IS the product (OpenAI, Anthropic, Scale AI, Cohere)
                                // 0.6-0.8 = AI is a major feature (Notion AI, Figma AI, etc.)
                                // 0.3-0.5 = uses AI for some features
                                // 0.0-0.2 = no meaningful AI component
  "funding_stage": string,      // seed/series_a/series_b/series_c/growth/public/acquired/unknown
  "size_estimate": string       // 1-10/11-50/51-200/201-1000/1000+/unknown
}
```

### User Message Per Company

```
Company: {{name}}
Website: {{website or "unknown"}}
ATS: {{ats_platform or "none"}} ({{ats_token or ""}})
Sample engineering job titles: {{sample_titles}}
Technologies used: {{aggregated tech stacks from jobs}}
```

### Company Tech Stack Aggregation (SQL, no LLM)

After Stage 3, aggregate tech stacks from jobs into the company record:

```sql
UPDATE companies SET tech_stack = (
    SELECT json_group_array(DISTINCT value)
    FROM jobs, json_each(jobs.tech_stack)
    WHERE jobs.company_id = companies.id
) WHERE tech_stack IS NULL OR tech_stack = '[]';
```

---

## Stage 4: Embedding Generation (free, local, ~30s for 1000 jobs)

Generates vector embeddings for semantic search. Runs entirely locally via ONNX models — no API key, no LLM backend needed. See spec 06 for model details and text preparation.

### Input Query

```sql
SELECT j.rowid, j.id, j.title, j.company_raw, j.description,
       j.job_summary, j.domain, j.tech_stack,
       COALESCE(c.name, j.company_raw) AS company_name,
       c.description AS company_description
FROM jobs j
LEFT JOIN companies c ON c.id = j.company_id
WHERE j.is_active = 1
  AND j.rowid NOT IN (SELECT rowid FROM vec_summaries)
```

**Scope:** All active jobs with descriptions, not limited to `engineering_role = 1`. Embeddings are cheap locally; casting a wide net means vector search works even before LLM classification runs.

**Watermark:** Vec table membership (`NOT IN vec_summaries`) rather than a column, since embeddings are stored in separate vec tables.

### Processing

1. For each job, build two texts:
   - Composite text (title + company + summary + domain + tech) — for summary model
   - Description text (title + company + full description) — for description model
2. Batch-embed with both models (batches of 100 for progress reporting)
3. Store embeddings in `vec_summaries` and `vec_descriptions` via `Store.store_embeddings()`
4. Record in `enrichment_runs` table with `stage='embeddings'`

### Idempotent Behavior

- Without `--force`: skips jobs already in vec tables
- With `--force`: deletes all entries from both vec tables and re-embeds everything

### Dependencies

Requires `fastembed` and `sqlite-vec`. If either is missing, Stage 4 logs an error with install instructions and skips (does not abort the pipeline).

---

## CLI Interface

### Commands

```bash
jbs enrich                         # full pipeline (stages 0-4), unprocessed only
jbs enrich --stage rules           # Stage 0+1 only (free, no API key needed)
jbs enrich --stage jobs            # Stage 2 only
jbs enrich --stage companies       # Stage 3 only
jbs enrich --stage embeddings      # Stage 4 only (free, local)
jbs enrich --dry-run               # show pending counts and cost estimate
jbs enrich --force                 # re-enrich everything (ignore enriched_at)
jbs enrich --source greenhouse     # only enrich jobs from this source
```

### Normal Output

```
Enriching 891 unprocessed jobs...

  Stage 0: cleanup     891 descriptions fixed  (0.3s)
    html_to_md: 450   data_uri: 5   encoding: 43   boilerplate: stripped
  Stage 1: rules       891 jobs processed      (1.2s)
    seniority: 624   visa: 178   salary: 89   years_exp: 534
  Stage 2: jobs        891 jobs submitted       (waiting for batch...)
    Batch received in 4m 12s
    engineering_role: 891   seniority: 267 refined   domain: 312   summaries: 312
  Stage 3: companies    63 companies submitted  (waiting for batch...)
    Batch received in 1m 03s
    ai_native: 63   industry: 63   funding: 41
  Stage 4: embeddings   1083 jobs embedded         (28.3s)
    summaries: 1083 (384d)   descriptions: 1083 (768d)

Enrichment complete.
  Cost: $0.89 (Haiku, Batch API)
  Run ID: enrich_2026-04-06_143000
```

### Dry Run Output

```
$ jbs enrich --dry-run
Pending enrichment:
  Stage 0: 450 Greenhouse HTML descriptions to convert (raw + entity-encoded)
  Stage 1: 891 jobs for rule-based extraction     (free)
  Stage 2: 891 jobs for LLM classification        (~$0.89, Haiku Batch API)
  Stage 3: 63 companies for LLM classification    (~$0.08, Haiku Batch API)
  Stage 4: 1083 jobs for embedding generation      (free, local)
  Estimated total: ~$0.97
  Estimated time: ~5 minutes (batch processing)
```

### Missing API Key

```
$ jbs enrich
Stage 0: cleanup... done (0.3s)
Stage 1: rules... done (1.2s)
Stage 2: ANTHROPIC_API_KEY not set. Skipping LLM stages.
  Set it: export ANTHROPIC_API_KEY=sk-ant-...
  Or run rules only: jbs enrich --stage rules
```

---

## Enrichment Tracking

The `enrichment_runs` table (defined in spec 02) tracks each run:

```sql
INSERT INTO enrichment_runs (run_id, started_at, stage, items, input_tokens, output_tokens, cost_usd, model)
VALUES ('enrich_2026-04-06_143000', '2026-04-06T14:30:00', 'jobs', 891, 1245000, 89100, 0.89, 'claude-haiku-4-5');
```

**Per-job tracking:** `enriched_at` on the `jobs` and `companies` tables serves as the watermark. `enriched_at IS NULL` = unprocessed.

**Re-enrichment:** `jbs enrich --force` ignores `enriched_at` and re-processes everything. Use when:
- Prompt was improved
- New fields added
- Model upgraded

---

## User Feedback Integration (v2, not v1)

v1 stores annotations (rating, pros, cons, interest) but does NOT use them to influence enrichment or ranking. This is intentional -- the user needs 50+ annotations before patterns are meaningful.

v2 direction (after sufficient annotation data):
- Compute preference profile from highly-rated jobs: preferred domains, seniority, ai_native threshold, tech_stack overlap
- Score new jobs: `preference_score = weighted_match(domain, seniority, ai_native, tech_overlap)`
- This is a SQL computed score, not an ML model
- Auto-suggest tags based on similarity to previously tagged jobs

---

## Cost Model

| Operation | Jobs | Est. Cost | Time |
|---|---|---|---|
| Initial full enrichment | 3,000 jobs + 600 companies | ~$1.20 | ~5 min |
| Daily incremental | ~200 new jobs + ~20 companies | ~$0.10 | ~2 min |
| Monthly steady-state | ~6,000 jobs + ~200 companies | ~$3.00 | -- |

The Batch API gives a 50% discount over standard API pricing. Prompt caching (1-hour TTL on system prompt) gives an additional ~50% reduction on input tokens for the cached portion.

---

## Files to Create/Modify

| File | Action | Description |
|---|---|---|
| `jbs/enrich.py` | Create | Main enrichment pipeline: stages 0-3, batch API client, result processing |
| `jbs/enrich_prompts.py` | Create | System prompts and prompt formatting functions (separated for easy iteration) |
| `jbs/enrich_rules.py` | Create | Stage 1: salary extraction, seniority keywords, visa patterns, years_experience regex |
| `jbs/store.py` | Modify | Add enrichment-related queries (`get_unenriched_jobs`, `update_enrichment`, new columns in `_ensure_schema`) |
| `jbs/util.py` | Modify | Add `strip_boilerplate`, `fix_mojibake` functions |
| `jbs/llm_backend.py` | Create | `LLMBackend` ABC, `ClaudeCLIBackend`, `BatchAPIBackend`, `get_llm_backend()` selector |
| `jbs/embeddings.py` | Create | Embedding models, text preparation, batch embedding (see spec 06) |
| `pyproject.toml` | Modify | Add `anthropic>=0.40` to optional: `[project.optional-dependencies] enrich = ["anthropic>=0.40"]`; add vector optional deps |
