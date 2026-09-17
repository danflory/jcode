---
# jcode-local frontmatter. These are operating-pattern documents, not SPRs:
# no UDRS/ci_impacted/parent numeric ids are used.
id: workPatterns
title: Work Patterns - repeatable coordinator/worker execution flows
status: ACTIVE
author: operator
created: 2026-09-17
domain: ENGINEERING
type: WORKPATTERNS.README
version: "2026-09-17"
---

# Work Patterns

Repeatable operating patterns for coordinator/worker execution on this repo.
Each pattern is a self-contained flow that a coordinator agent can follow, and
an operator can audit.

## Document Index

| Document | Type | Purpose |
|:---------|:-----|:--------|
| `01_Approval_Gated_Assignment_Flow.md` | Pattern | Show the assignment plan, get explicit approval, then assign to a worker |

## Why these exist

Ad-hoc delegation is hard to audit and easy to get wrong: overlapping edits,
unauthorized commits, unverifiable "done" reports, and workers drifting outside
their scope. These patterns make delegation explicit, bounded, and verifiable,
so an operator can approve work in one short exchange and then verify it against
evidence rather than trusting a summary.

## Pattern status

| Pattern | Status | Origin |
|:--------|:-------|:-------|
| `01_Approval_Gated_Assignment_Flow.md` | ACTIVE | Developed during the SPR-0008 `sessionCorruption` work (swarm: eagle coordinator; lobster, mosquito, owl workers) |
