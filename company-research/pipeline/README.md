# Company Research Pipeline

Tracks companies through the job search funnel. Each stage is a markdown log file
(append-only). Companies move forward through stages; entries are never deleted or
overwritten.

## Funnel Stages

1. **discovered** -- Company identified as potentially interesting. Source could be
   batch research, jbs search results, referral, or manual discovery.
2. **investigating** -- Actively researching the company. Reading about product,
   team, tech stack, open roles.
3. **reaching-out** -- Preparing to make contact. Drafting messages, finding the
   right person, tailoring resume.
4. **contacted** -- Outreach sent (application submitted, email sent, referral
   requested). Waiting for response.
5. **interviewing** -- Active interview process. Track stages, prep notes, dates.
6. **passed** -- Decided not to pursue, or they declined. Record the reason.

## File Conventions

Each stage file (e.g. `discovered.md`) is an **append-only log**. Format:

```markdown
## Company Name
**Date:** 2026-04-10
**Source:** batch-01 / jbs search / referral / etc.
**Notes:** Why this company, what caught your eye.
**ATS token:** greenhouse:companyname (if known)
```

When a company moves to the next stage, add a new entry in the destination file
with the date. The old entry stays in the source file as history.

## Batch Files

The `batch-*.md` files in the parent directory contain agent-generated research
with **user feedback annotations** (the "Your take:" sections). These are reference
material -- do not overwrite or regenerate them. They feed the `discovered` stage.

## Raw Agent Output

The `raw-agent-*.txt` files are unprocessed agent research output. Kept for
provenance. Not meant to be read directly.
