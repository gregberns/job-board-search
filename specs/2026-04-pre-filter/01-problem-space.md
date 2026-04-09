# Pre-Classification Filter — Problem Space

## Goal

Reduce LLM enrichment cost by 60-75% by filtering out jobs the user will never look at before sending them to expensive Haiku classification. The user wants senior/staff/principal IC engineering roles at well-paying companies. Everything else is noise.

## User Profile

- Looking for: senior, staff, principal **IC** engineering roles
- Excludes: management, non-engineering, junior/intern, low-comp roles
- Salary floor: max salary must be >= $190k (when known)
- Adjacent roles to skip: Data Scientist, Data Analyst, TPM, Security Analyst, DevOps/SRE (unless titled "engineer")
- Include: Software Engineer, AI Engineer, Software Developer, ML Engineer, Platform Engineer, etc.
- False negative tolerance: moderate — OK to miss edge cases with weird titles

## Constraints

- Pre-filter must be free (no LLM calls) — pure title keywords + salary + seniority rules
- Must run as part of existing `jbs enrich --stage rules` (Stage 1)
- LLM stages (2, 3) must respect the filter — only process filtered-in jobs
- `--force` flag should bypass the filter and send everything

## What Success Looks Like

- `jbs enrich --dry-run` shows: "1,200 of 4,300 jobs pass pre-filter for LLM classification"
- LLM enrichment runs in ~2 min instead of ~7 min
- No senior IC engineering roles with good comp are accidentally filtered out
- Filter results are inspectable (column on jobs table)

## Out of Scope

- Changing LLM prompts or classification fields
- User-configurable keyword lists (hardcoded is fine)
- Changes to search/ranking behavior
- Retroactive re-classification of already-enriched jobs
