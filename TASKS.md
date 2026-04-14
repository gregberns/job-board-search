# Tasks — jbs

## Active

### Broaden company search scope
- Need to find more companies matching the four-filter flywheel (see `what-im-looking-for/framework.md`)
- Focus on the **platform/data/decision layer** serving physical industries — NOT robotics/embedded/perception
- Must be Senior/Staff backend engineer roles matching user's skillset
- Remote-first is a hard requirement
- Explore additional job sources beyond current ATS boards
- Current batches 4 (AI-first) and 5 (Rust) were mostly robotics misses — need to recalibrate

### Build Workable scraper
- Spec complete at `specs/07-workable-scraper.md`
- API endpoints confirmed, data mapping done, implementation plan ready
- Token file at `tokens/workable.txt` with 29 tokens
- Needs implementation + tests

### Review batch-06 (remote-first)
- User reviewing `company-research/batch-06-remote-first.md`
- Feedback pending

### Pipeline progression
- 3 companies in ADVANCE: PermitFlow, Kallikor, Foxglove
- 10 in MAYBE — need deeper investigation
- Need to move ADVANCE companies to "investigating" stage with concrete next actions

## Backlog

### Expand token coverage
- ~100 new tokens added across Greenhouse/Lever/Ashby/Workable
- Run a fresh scrape to pick up new companies
- Consider adding Gem ATS (Nominal uses it)
- Consider adding Comeet ATS (Darrow uses it)

### Improve search targeting
- Current vec search returns too many big companies and robotics firms
- Need to filter for remote + platform-layer + senior/staff roles
- Framework search criteria doc at `company-research/framework-search-criteria.md`

### Fresh scrape with new tokens
- Last scrape was 2026-04-09
- New tokens added 2026-04-13 won't be picked up until next scrape
