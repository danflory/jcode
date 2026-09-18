---
# jcode-local frontmatter. Operating-pattern document, not an SPR: no UDRS ids.
id: WP-0001
title: Approval-Gated Assignment Flow
status: ACTIVE
author: operator
created: 2026-09-17
domain: ENGINEERING
type: WORKPATTERN
version: "2026-09-17"
---

# WP-0001: Approval-Gated Assignment Flow

A repeatable flow for delegating work to worker agents: the coordinator drafts an
assignment plan, shows it to the operator, waits for explicit approval, then
assigns it to a worker and independently verifies the result.

## Roles

| Role | Responsibility |
|:-----|:---------------|
| Coordinator | Decomposes work, drafts the plan, assigns, verifies, reports. Owns the outcome. |
| Operator | Reads the plan, approves or amends, receives evidence-based reports. Owns the intent. |
| Worker | Executes exactly one approved task, reports back with evidence. |

## The flow

```
1. DECOMPOSE   Coordinator isolates one task with a single clear goal.
2. DRAFT       Coordinator writes the assignment brief (template below).
3. SHOW        Coordinator presents the brief to the operator. No worker is started yet.
4. APPROVE     Operator approves or amends. This is the gate.
5. ASSIGN      Coordinator sends the approved brief to an idle worker, or spawns one.
6. EXECUTE     Worker does exactly the one task, within its file/scope constraints.
7. VERIFY      Coordinator independently checks the worker's claims against real state.
8. REPORT      Coordinator reports to the operator with evidence, and flags anomalies.
```

Steps 3 and 4 are the defining feature: **the operator sees the exact brief before
any worker is started.** The coordinator never spends worker time on an
unapproved plan.

## The assignment brief (required sections)

Every brief must contain all of these. A brief missing one is incomplete.

1. **One task only** - an explicit "ONE TASK ONLY" header plus the single goal.
2. **Context** - the problem, and the specific files or docs to read first.
3. **Deliverable** - exact path(s) to create or change, and nothing else.
4. **Requirements** - concrete, checkable behavior (not adjectives).
5. **Constraints** - see the standard set below.
6. **Verification** - what the worker must run and show before reporting.
7. **Report back** - the exact evidence the coordinator expects in the reply.
8. **Routing** - which worker (or spawn), and which model.

## Standard constraints (include in every brief)

- Touch ONLY the named files/paths. Do not edit anything else.
- Do NOT commit and do NOT push. The coordinator commits.
- Do not touch `crates/` unless the task IS a code task, and never outside scope.
- Cite real `file:line` for any claim about existing code.
- Mark anything unverified as **UNVERIFIED** rather than guessing.
- If the task looks inconsistent or destructive without authorization, STOP and report.
- Report back concisely: paths, exact commands run, observed results, failures.

## Scope discipline

- One worker, one task. Never bundle two goals into one brief.
- Prefer disjoint file scopes across concurrent workers so concurrent edits cannot
  conflict. (Example: one worker on `crates/jcode-tui`, another on `crates/jcode-app-core`,
  a third writing docs only.)
- A worker must not commit. Commits made by workers have landed unexpectedly and
  had to be untangled; keep commit authority with the coordinator.

## Verification (step 7) is not optional

The coordinator must not relay a worker's summary as fact. Verify against real
state: read the files, run the commands, check counts, inspect git status and
`git log`/`git reflog`. Report the delta between the worker's claim and observed
reality.

## Failure modes observed, and the mitigation

| Failure mode | Mitigation |
|:-------------|:-----------|
| Worker commits without authorization | "Do NOT commit" in the brief; coordinator checks `git log` after; commit authority stays with coordinator |
| Worker edits outside scope | Explicit allowed-path list; coordinator diffs after |
| Worker writes test fixtures into real state (`~/.jcode/sessions`) | Briefs must require isolated temp dirs for fixtures; verify no new files appeared in real state |
| Overlapping concurrent edits | Disjoint file scopes; route doc-only work separately from code |
| Worker assumes/guesses instead of verifying | Require evidence and `UNVERIFIED` marking; coordinator re-checks |
| Worker claimed "done" but left leftovers | Require the worker to show the actual verification command and output |
| Worker vanished or left the swarm before assignment | Rerouting: assign to another idle worker; plan for it rather than dropping the task |
| Requested stop did not take effect (cooperative stop) | Do not assume a stopped worker is inert; check the working tree afterward |
| Model cost | Route workers to a cheaper model than the coordinator when the task is well-scoped |

## Worked example (SPR-0008 `sessionCorruption`)

Coordinator: `eagle`. Model routing: workers on a cheaper sibling route than the
coordinator.

| Task | Worker | Outcome |
|:-----|:-------|:--------|
| Convert the single-file SPR into the Overwatch-style folder | `lobster` | 4 files created; old file removed |
| Research persistent semantic-index options into `docs/tempResponses/` | `mosquito` | Options report, later moved into the SPR folder as `04_...` |
| Build and run the session-prune tool in `temp/tools/` | `owl` | Tool created, dry-run + apply run, sessions 27 -> 7 |
| `/info` remote-identity fix | `giraffe` | Code change; **worker also committed it, violating the constraint** |
| Resume cwd precedence fix | `hamster` | Code change plus a test that leaked fixtures into the real sessions dir |
| Client-local-state audit | `ladybug` | Audit document written |

Both failures above are exactly why the constraints and step-7 verification exist:
the unauthorized commit and the leaked fixtures were caught by the coordinator
inspecting real state, not by trusting reports.

## When to use this flow

Use it whenever work is delegated to a worker agent and the operator wants to see
and approve the plan first. It costs one extra exchange (show, then approve) and
buys auditability, bounded scope, and verifiable results.
