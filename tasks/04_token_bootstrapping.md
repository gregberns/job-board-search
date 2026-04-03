# Task 04: Token Bootstrapping and Validation

## Objective
Create scripts to extract ATS board tokens from the awesome-easy-apply repository and validate them against live APIs. The validated token files are required input for Greenhouse, Lever, and Ashby scrapers.

## Files to Create
- `scripts/bootstrap_tokens.py`
- `scripts/validate_tokens.py`
- `tokens/greenhouse_raw.txt` (generated output)
- `tokens/greenhouse.txt` (generated output)
- `tokens/lever_raw.txt` (generated output)
- `tokens/lever.txt` (generated output)
- `tokens/ashby.txt` (manually curated)

## Changes

### 1. `scripts/bootstrap_tokens.py`
Fetches raw README.md from the awesome-easy-apply GitHub repo and extracts tokens:
- Greenhouse: extract `{token}` from `boards.greenhouse.io/{token}` URLs (expect ~540)
- Lever: extract `{slug}` from `jobs.lever.co/{slug}` URLs (expect ~251)
- Write raw tokens to `tokens/greenhouse_raw.txt` and `tokens/lever_raw.txt` (one per line)
- Print stats: how many tokens extracted per source

### 2. `scripts/validate_tokens.py`
Validates each raw token against the live API:
- **Greenhouse:** `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs` (no `content=true`)
  - 200 = valid, 404 = dead, 429 = rate-limited (retry with backoff)
  - Expect 50-70% validity (~270-380 valid tokens)
- **Lever:** `GET https://api.lever.co/v0/postings/{slug}?mode=json`
  - Expect ~20% validity (~50 valid tokens)
- Concurrent validation with bounded concurrency (e.g., 20 workers for Greenhouse, 2 for Lever)
- Write valid tokens to `tokens/greenhouse.txt` and `tokens/lever.txt`
- Log summary: "Greenhouse: 340/540 valid (63%)"

### 3. `tokens/ashby.txt` (manual curation)
Create a starter list of ~20-30 known Ashby company board names:
- linear, ramp, notion, etc.
- Source from known Ashby users and Common Crawl results

## Token file format
One token per line, blank lines and `#` comment lines ignored:
```
# Greenhouse board tokens (validated 2026-04-01)
stripe
discord
cloudflare
...
```

## Acceptance Criteria
- `bootstrap_tokens.py` successfully extracts tokens from the GitHub repo
- `validate_tokens.py` produces valid token files with reasonable counts
- Token files exist at `tokens/greenhouse.txt`, `tokens/lever.txt`, `tokens/ashby.txt`
- Token files follow the one-per-line format with comment support
- Scripts handle network errors gracefully (retry, skip, log)

## Dependencies
- None (scripts are standalone, don't depend on JobSpy code)

## Blocked By
- Nothing (can run in parallel with Tasks 01-03)
