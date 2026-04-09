# Spec: Pre-Classification Filter for LLM Enrichment

## Problem

LLM enrichment costs scale with job count. 73% of scraped jobs are irrelevant to the user (management, non-engineering, low comp, junior). We need a free pre-filter in Stage 1 that marks which jobs should be sent to LLM Stages 2-3.

## Data Model Change

### New column: `jobs.llm_filter`

```sql
ALTER TABLE jobs ADD COLUMN llm_filter TEXT
    CHECK(llm_filter IS NULL OR llm_filter IN ('send', 'skip_mgmt', 'skip_title', 'skip_salary', 'skip_seniority'));
```

- `send` — passes filter, will be sent to LLM
- `skip_mgmt` — excluded: management role
- `skip_title` — excluded: non-engineering title
- `skip_salary` — excluded: max salary < $190k (when known)
- `skip_seniority` — excluded: intern or junior level
- `NULL` — not yet processed by filter

The specific skip reason is stored for debuggability. Any `skip_*` value means the job won't be sent to LLM.

### Migration

Add to `_ensure_schema()` migrations list:
```python
("jobs", "llm_filter", "TEXT"),
```

## Stage 1 Rule: `classify_llm_filter`

Added to `jbs/enrich_rules.py`. Called during Stage 1 for every job.

```python
def classify_llm_filter(title: str, is_management: bool, seniority: str | None,
                         salary_usd_max: float | None, max_amount: float | None) -> str:
    """Classify whether a job should be sent to LLM enrichment.
    
    Returns: 'send', 'skip_mgmt', 'skip_title', 'skip_salary', or 'skip_seniority'.
    Filters are applied in priority order (first match wins).
    """
```

### Filter cascade (order matters):

1. **Management** → `skip_mgmt`
   - `is_management = True`

2. **Non-engineering title** → `skip_title`
   - Title matches any of: sales, marketing, recruiter, talent acquisition, human resource, accountant, finance manager, legal, counsel, customer success, account executive, business development, copywriter, nurse, physician, therapist, receptionist, warehouse, data scientist, data analyst, product manager, program manager, project manager, designer, solutions engineer, support engineer, field engineer, implementation
   - Note: "Solutions Engineer", "Support Engineer", "Field Engineer" are excluded — these are customer-facing, not IC engineering

3. **Low salary** → `skip_salary`
   - `COALESCE(salary_usd_max, max_amount) < 190000` AND salary is not NULL
   - Jobs with no salary data pass through (benefit of the doubt)

4. **Junior seniority** → `skip_seniority`
   - `seniority IN ('intern', 'junior')`

5. **Everything else** → `send`

### Title keyword lists

**Exclude titles containing** (case-insensitive):
```python
_TITLE_EXCLUDE = [
    'sales', 'marketing', 'recruiter', 'talent acq', 'human resource',
    'accountant', 'finance manager', 'financial analyst', 'legal', 'counsel',
    'customer success', 'account executive', 'business develop',
    'copywriter', 'content writer', 'nurse', 'physician', 'therapist',
    'pharmacist', 'receptionist', 'warehouse', 'maintenance tech',
    'data scientist', 'data analyst', 'product manager', 'program manager',
    'project manager', 'designer', 'solutions engineer', 'support engineer',
    'field engineer', 'implementation', 'customer engineer',
]
```

**Keep titles containing** (overrides exclude — checked first):
```python
_TITLE_KEEP = [
    'ai engineer', 'ml engineer', 'machine learning engineer',
]
```

If title matches both keep and exclude, keep wins.

## Changes to Stage 2 (LLM Jobs)

### Current input query (from `jbs/enrich.py`):
```sql
WHERE engineering_role IS NULL AND description IS NOT NULL AND length(description) > 50
```

### New input query:
```sql
WHERE engineering_role IS NULL
  AND description IS NOT NULL AND length(description) > 50
  AND (llm_filter = 'send' OR llm_filter IS NULL)
```

When `--force` is used, ignore `llm_filter` (send everything).

## Changes to Stage 3 (LLM Companies)

No change to the query — it already filters to companies with `engineering_role = 1` jobs. Since fewer jobs get LLM-classified, fewer companies will have `engineering_role = 1`, so the company enrichment scope naturally shrinks.

## Changes to `jbs enrich --dry-run`

Show the filter breakdown:
```
Pending enrichment:
  Stage 1: 1,200 jobs for rule-based extraction (free)
    Pre-filter: 4,292 active → 1,147 pass (skip: 1,191 mgmt, 836 title, 291 salary, 827 junior)
  Stage 2: 1,147 jobs for LLM classification (~$0.40, Haiku)
  Stage 3: ~200 companies for LLM classification (~$0.05, Haiku)
```

## Changes to Store

### New method: `update_llm_filter(job_id, value)`
Simple UPDATE wrapper.

### Modified `_ensure_schema()`
Add `llm_filter` to the migrations list.

## Files Changed

| File | Change |
|------|--------|
| `jbs/store.py` | Add `llm_filter` column migration, `update_llm_filter()` |
| `jbs/enrich_rules.py` | Add `classify_llm_filter()` function with keyword lists |
| `jbs/enrich.py` | Call `classify_llm_filter` in Stage 1, filter Stage 2 input query |
| `tests/test_enrich_rules.py` | Tests for `classify_llm_filter` |
| `tests/test_enrich.py` | Test that Stage 2 respects `llm_filter`, test `--force` bypass |

## Acceptance Criteria

- [ ] `jbs enrich --stage rules` populates `llm_filter` on all active jobs
- [ ] `jbs enrich --dry-run` shows filter breakdown
- [ ] `jbs enrich --stage jobs` only sends `llm_filter = 'send'` jobs to LLM
- [ ] `jbs enrich --stage jobs --force` sends all jobs regardless of filter
- [ ] Management, non-eng titles, low salary, and junior jobs are correctly classified
- [ ] "AI Engineer" survives even though title exclusion list has adjacent terms
- [ ] All existing tests still pass
