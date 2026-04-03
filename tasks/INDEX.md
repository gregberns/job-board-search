# Task Index

## Overview
Implementation plan for extending JobSpy with 5 new scrapers (Greenhouse, Lever, Ashby, RemoteOK, HN Who's Hiring) targeting SMB job sources, with JSONL output.

## Tasks

| # | Task | File | Status | Blocked By |
|---|------|------|--------|------------|
| 01 | [Model Changes](01_model_changes.md) | `01_model_changes.md` | [ ] | — |
| 02 | [Shared Utilities](02_shared_utilities.md) | `02_shared_utilities.md` | [ ] | 01 |
| 03 | [Registration & Wiring](03_registration_and_wiring.md) | `03_registration_and_wiring.md` | [ ] | 01 |
| 04 | [Token Bootstrapping](04_token_bootstrapping.md) | `04_token_bootstrapping.md` | [ ] | — |
| 05 | [RemoteOK Scraper](05_remoteok_scraper.md) | `05_remoteok_scraper.md` | [ ] | 01, 02, 03 |
| 06 | [Greenhouse Scraper](06_greenhouse_scraper.md) | `06_greenhouse_scraper.md` | [ ] | 01, 02, 03, 04* |
| 07 | [Lever Scraper](07_lever_scraper.md) | `07_lever_scraper.md` | [ ] | 01, 02, 03, 04* |
| 08 | [Ashby Scraper](08_ashby_scraper.md) | `08_ashby_scraper.md` | [ ] | 01, 02, 03, 04* |
| 09 | [HN Scraper](09_hn_scraper.md) | `09_hn_scraper.md` | [ ] | 01, 02, 03 |
| 10 | [Runner Script](10_runner_script.md) | `10_runner_script.md` | [ ] | 05, 06, 07, 08, 09 |
| 11 | [Dedup Utility](11_dedup_utility.md) | `11_dedup_utility.md` | [ ] | 10 |
| 12 | [End-to-End Test](12_end_to_end_test.md) | `12_end_to_end_test.md` | [ ] | 10, 11 |

## Execution Order

```
Phase 1 (Foundation):     01 ──┬──> 02 ──┐
                               └──> 03 ──┤
                          04 (parallel)   │
                                          v
Phase 2 (Scrapers):       05, 06, 07, 08, 09 (parallel after 01+02+03)
                                          │
Phase 3 (Integration):    10 ────> 11 ──> 12
```

### Parallelism Notes
- **Task 04** (token bootstrapping) has no code dependencies and can run in parallel with Tasks 01-03
- **Tasks 02 and 03** can run in parallel after Task 01 completes
- **Tasks 05-09** (all scrapers) can run in parallel after Tasks 01, 02, 03 complete
- **Task 04** must complete before Tasks 06, 07, 08 can be fully tested (they need token files)
- **Tasks 10-12** are sequential

\* Task 04 is a soft dependency for Tasks 06-08: code can be written without it, but full testing requires token files
