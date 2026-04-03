# Task 12: End-to-End Test

## Objective
Run a full end-to-end test across all five sources to validate the complete pipeline works together.

## What to Test

### 1. Full Pipeline Run
Run `python run_search.py` with all sources enabled and verify:
- All five sources produce results (or gracefully report 0/failure)
- JSONL output file is created and valid
- Dedup runs successfully
- No unhandled exceptions

### 2. Per-Source Validation
For each source, verify:
- **RemoteOK:** Returns jobs, all have `is_remote=True`, valid URLs
- **Greenhouse:** Returns jobs from multiple boards, `board_token` populated, `first_published` used for dates
- **Lever:** Returns jobs (expect fewer due to high 404 rate), rate limiting respected
- **Ashby:** Returns jobs, compensation parsed when available, JSON control chars handled
- **HN:** Returns jobs from latest thread, pipe-delimited headers parsed, malformed comments don't crash

### 3. Data Quality Checks
- No jobs with `id=None`
- All job URLs are valid HTTP(S) URLs
- `date_posted` values are reasonable (within last year)
- No duplicate IDs within a single source
- Compensation values are positive when present (no negative or zero salaries)
- Description fields are populated (not all null)

### 4. Error Recovery
- Verify that if one source fails, others still produce results
- Verify incremental writes: kill the process mid-run and check partial JSONL output

### 5. Performance Sanity
- Greenhouse two-pass strategy reduces data transfer vs single-pass
- Lever doesn't hit rate limits with current concurrency settings
- Full run completes in a reasonable time (target: under 30 minutes for all sources)

## Acceptance Criteria
- Full pipeline run completes without unhandled exceptions
- Each source produces at least some results (or a clear explanation of why not)
- Output JSONL is valid and parseable
- Data quality checks pass
- Error recovery works (partial results preserved on crash)

## Dependencies
- All previous tasks (01-11)

## Blocked By
- Tasks 10, 11
