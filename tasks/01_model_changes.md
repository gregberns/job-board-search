# Task 01: Model Changes

## Objective
Extend the existing data models to support the five new scrapers. This is the foundation that all other tasks depend on.

## Files to Modify
- `JobSpy/jobspy/model.py`
- `JobSpy/jobspy/exception.py`
- `JobSpy/jobspy/util.py`

## Changes

### 1. Extend `Site` enum in `model.py`
Add five new members:
```python
GREENHOUSE = "greenhouse"
LEVER = "lever"
ASHBY = "ashby"
REMOTEOK = "remoteok"
HN = "hn"
```

### 2. Extend `ScraperInput` in `model.py`
Add these fields to the `ScraperInput` BaseModel:
```python
greenhouse_board_tokens: list[str] | None = None
lever_company_slugs: list[str] | None = None
ashby_board_names: list[str] | None = None
hn_thread_id: str | None = None
```

### 3. Add `board_token` to `JobPost` in `model.py`
```python
board_token: str | None = None  # ATS board token/slug this job came from
```

### 4. Add `ScraperException` to `exception.py`
```python
class ScraperException(Exception):
    def __init__(self, site: Site, message: str, *, status_code: int | None = None, token: str | None = None):
        self.site = site
        self.status_code = status_code
        self.token = token
        super().__init__(f"[{site.value}] {message}")
```
Keep existing per-site exceptions for backward compatibility.

### 5. Update `desired_order` in `util.py`
Add `board_token` to the column ordering list.

## Acceptance Criteria
- All five new `Site` enum values exist and are importable
- `ScraperInput` accepts the four new optional fields without breaking existing callers (all default to `None`)
- `JobPost` instances can carry a `board_token`
- `ScraperException` can be instantiated with site, message, and optional status_code/token
- Existing tests/imports still work (no regressions)

## Dependencies
- None (this is the first task)

## Blocked By
- Nothing
