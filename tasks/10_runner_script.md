# Task 10: Runner Script with JSONL Output

## Objective
Create the main runner script that ties all scrapers together with incremental JSONL writes and resume-from-failure support.

## Files to Create
- `run_search.py` (project root: `/Users/gb/github/job-board-search/run_search.py`)

## Working Directory
This script must be run from the project root (`/Users/gb/github/job-board-search/`) since it uses relative paths for `tokens/` and `data/` directories.

## Design

### Token Loading
```python
def load_tokens(filepath: str) -> list[str]:
    """Load board tokens from a text file, one per line, skip comments/blanks."""
```
Reads from `tokens/*.txt` files.

### Source Configuration
Run each source separately for incremental saves:
- `remoteok` — no tokens needed
- `greenhouse` — loads `tokens/greenhouse.txt`
- `lever` — loads `tokens/lever.txt`
- `ashby` — loads `tokens/ashby.txt`
- `hn` — no tokens needed

### Incremental JSONL Writes
- After each source completes, append results to `data/jobs_{today}.jsonl`
- If the process crashes at Lever, Greenhouse results are already on disk
- Use pandas `to_json(orient="records", lines=True, mode="a")` for append

### Output
- Creates `data/` directory if needed
- Output file: `data/jobs_YYYY-MM-DD.jsonl`
- Prints per-source counts and total
- Per-source try/except: log failures, continue to next source

### CLI Arguments (optional but helpful)
- `--search-term` (default: "software engineer")
- `--results-wanted` (default: 1000)
- `--hours-old` (default: 168 = 1 week)
- `--sources` (default: all)

## Acceptance Criteria
- `python run_search.py` runs all five sources and produces a JSONL file
- Each source's results are written incrementally (verify by checking file between sources)
- A crash in one source doesn't lose results from previously completed sources
- Output file is valid JSONL (one JSON object per line)
- Token files are loaded correctly (comments/blanks skipped)
- Missing token files are handled gracefully (source skipped with message)
- `data/` directory is created automatically

## Dependencies
- Tasks 01-09 (all scrapers must be implemented)

## Blocked By
- Tasks 05, 06, 07, 08, 09 (all scrapers)
