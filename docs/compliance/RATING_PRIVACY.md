# Rating & grading privacy

**Status:** Binding for this repository  
**Updated:** 2026-08-06

## Rule

All **competitive maturity ratings**, **capability grades** (0–5, letter grades, Done well / Could-be-better / Missed the mark buckets), **regrade overalls**, and **competitor benchmark score tables** are **PRIVATE / INTERNAL ONLY**.

They are maintainer honesty tools. They are **not**:

- Public product claims
- Marketing or sales copy
- Customer-facing diligence scorecards
- Material for external blogs, decks, or press without an explicit written exception from maintainers

## What this covers

| In scope (private) | Out of scope (ordinary docs) |
| --- | --- |
| Competitive score matrix / module rescores / critical reviews | API `score` fields and decision outcomes |
| CLAIM_LOCK snapshots and “OK claim language” | Weekly ops scorecards (latency/RPS/benchmark JSON) unless they embed competitive grades |
| Maturity regrade canvas and Tier-1 honesty grade checklists | Architecture ADRs without numeric competitive grades |
| Superpowers plans/specs that target numbered maturity bars (e.g. “4.2”, “4.5”, “A++”) | |

## Required document marking

Every in-scope document must open with a **PRIVATE / INTERNAL ONLY** banner that links here.

## Publication controls

1. **Do not** list in-scope guides in the public MkDocs nav as product positioning.
2. **Exclude** in-scope Markdown from the public docs build (`docs/mkdocs.yml` `exclude_docs`).
3. **Do not** rebuild `docs/site/` pages for excluded rating docs; remove stale published HTML if present.
4. Pull requests must not introduce public marketing of maturity numbers; see `.github/pull_request_template.md`.

## Allowed internal use

- Engineering regrades, claim hygiene, and gap planning inside the repo
- Private maintainer discussion that does not republish tables externally
- Citing [CLAIM_LOCK.md](./CLAIM_LOCK.md) for what must **not** be advertised — itself still private

## Forbidden

- Quoting matrix cells, overall means, or letter grades in README, release notes, public site, or customer packs
- “We are a 4.x platform” (or A++ / primary-five overall) in any public channel
- Re-adding excluded rating pages to the public site without lifting this policy
