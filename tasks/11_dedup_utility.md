# Task 11: Deduplication Utility

## Objective
Create a post-processing deduplication step that removes duplicate job listings across sources.

## Files to Create or Modify
- Add dedup function to `run_search.py` or create `scripts/dedup.py`

## Design

### Dedup Key
`(company_name_normalized, title_normalized)`

### Normalization
- Company name: lowercase, strip common suffixes (Inc, LLC, Ltd, Corp, Co., etc.), strip whitespace
- Title: lowercase, strip whitespace, normalize common variations

### Conflict Resolution
When duplicates are found, keep the record with the richest data:
- Count non-null fields
- Keep the record with the highest count
- Tie-breaker: prefer the record with a longer description

### Integration
This runs as a post-processing step after all sources have written to the JSONL file:
1. Read the JSONL file
2. Group by dedup key
3. For each group, keep the richest record
4. Write deduplicated results back (or to a new file like `jobs_{date}_deduped.jsonl`)
5. Log stats: "Deduped: 1500 -> 1350 jobs (150 duplicates removed)"

## Acceptance Criteria
- Duplicates with different company name casing are caught ("Stripe" vs "stripe")
- Duplicates with suffixes are caught ("Stripe Inc" vs "Stripe")
- The richest record is kept (most non-null fields)
- Original JSONL is preserved; deduped version is written separately (or clearly replaces)
- Stats are printed showing how many dupes were removed
- Handles edge cases: null company_name, null title

## Dependencies
- Task 10 (runner script that produces the JSONL file)

## Blocked By
- Task 10
