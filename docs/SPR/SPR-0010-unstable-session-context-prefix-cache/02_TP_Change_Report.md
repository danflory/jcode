---
# jcode-local frontmatter (SPR folder conversion, 2026-09-17).
# jcode is NOT governed by Overwatch's UDRS: no UDRS/ci_impacted/parent numeric
# ids are fabricated here. Only real, repo-verifiable values are used.
id: SPR-0010
title: unstable session context prefix - volatile timestamp in the first provider-visible message defeats prompt cache reuse across swarm workers
status: CONFIRMED
author: operator
created: 2026-09-18
domain: ENGINEERING
severity: Major
type: SPR.TP_CHANGE
version: "2026-09-18"
---

# SPR-0010: Unstable Session Context Prefix — TP Change Report

> [!WARNING]
> **AGENT INSTRUCTION: This document is NOT a Test Procedure (TP).**
> It is a *Change Report* documenting how a separate regression TP was modified.
> Every code fix requires coverage in an executable TP. Do not attempt to write
> executable bash commands directly into this report.

## Affected TP

- **TP Reference**: none (no dedicated TP currently governs jcode session-context
  construction, prompt-prefix stability, or cache-affecting prompt assembly)
- **Parent Artifact**: none. jcode is NOT governed by Overwatch's PRACA/TP labor
  model, and no parent TP exists for these code paths.

The affected code paths are:

- `crates/jcode-base/src/prompt.rs` (`build_session_context`,
  `session_datetime_lines`)
- `crates/jcode-base/src/session.rs` (`ensure_initial_session_context_message`,
  `refresh_initial_session_context_message`)

None of these paths has an associated standalone TP (the jcode repo has no
`docs/praca/TP/TP-NNN.md`-equivalent), and there is **no parent TP** that could
be modified. This report therefore classifies the *test gap* and identifies
where regression coverage must be added, per the pattern established by
SPR-0008's TP Change Report.

## Existing Test Coverage Survey

| Path | Existing tests | Gap |
|:-----|:---------------|:----|
| `prompt.rs` `build_session_context` | `prompt_tests.rs:291` asserts the context contains `# Session Context`; `prompt_tests.rs:333` asserts `split.dynamic_part` does **not** contain it | Asserts *presence*, never *ordering* or *stability*. A timestamp at line 3 passes both. |
| `session.rs` context injection | `session_tests/cases.rs:263` asserts the first message contains `# Session Context`; `cases.rs:450` similar | Asserts the context is first and identifiable. Does not assert that two independently built contexts share a prefix. |
| Prefix-splitting | `prompt.rs:201-222` (`static_part` / `dynamic_part` split), `prompt_tests.rs:29` | Covers the system-prompt split, an adjacent concern, but **not** the session-context message, which is a separate transcript item. |
| Cache-affecting assembly | none found | No test anywhere describes the invariant "leading provider-visible content must be stable across sessions". |

## Test Gap Classification

**V-1 — Cross-session prefix stability (primary gap).**

No test constructs two contexts under differing wall-clock times and asserts
their common prefix covers the block. This is the invariant the defect breaks,
and it is currently unexpressed in the test suite.

- *Coverage to add*: build a context, advance the clock, build again, assert the
  longest common prefix extends past all stable fields.
- *Determinism*: requires injectable time. If `build_session_context` cannot be
  made time-injectable without an API change, the test can instead assert
  *ordering*: that no volatile field appears before a stable field in the
  emitted string.

**V-2 — Field ordering (structural gap).**

No test asserts relative ordering of fields within the context block.

- *Coverage to add*: assert `OS:` / `Architecture:` / `Jcode version:` appear
  before any `Time:` line, or that no datetime line precedes a stable field.
- This is the cheap, deterministic proxy for V-1 and is the recommended primary
  regression test.

**V-3 — Behavioral preservation (regression gap).**

The existing contract has three parts, all currently covered but which must
remain covered after the reorder:

- the snapshot is the **first** provider-visible item
- it carries `display_role: System`
- `has_session_context_message` / `refresh_initial_session_context_message` still
  match via `SESSION_CONTEXT_PREFIX`

- *Coverage to add*: no new tests strictly required; existing tests at
  `session_tests/cases.rs:263,450` and `memory_tests.rs:877` must continue to
  pass unmodified. Modifying them to accommodate the change would itself be a
  signal of regression.

**V-4 — Post-fix measurement (evidence gap).**

No automated test can assert provider-side cache behavior; this requires
measurement.

- *Coverage to add*: none automated. Record the re-measured worker hit rate in
  `03_Cost_Evidence.md`, using the role-split method described there.

## Required Coverage Before Closure

| V-# | Kind | Where | Deterministic |
|:----|:-----|:------|:--------------|
| V-1 | Property (cross-session stability) | `crates/jcode-base/src/prompt_tests.rs` | Yes, if time is injectable; otherwise via V-2 |
| V-2 | Structural (field ordering) | `crates/jcode-base/src/prompt_tests.rs` | Yes |
| V-3 | Behavioral (existing contract) | existing tests, unmodified | Yes |
| V-4 | Measurement (provider cache) | `03_Cost_Evidence.md` | No (empirical) |

## Note on Test Suite Condition

Recording for accuracy: the last full `cargo test` run noted in
`docs/SPR/update-log.md` (2026-09-15 ~23:40Z) found 8 lib failures plus 21
workspace-crate failures, all confirmed **identical on clean upstream
`origin/master`** and therefore environment-dependent and pre-existing. A new
test added for this SPR should be evaluated against that baseline, not against a
green suite, and should be run in isolation
(`cargo test -p jcode-base --lib prompt_tests`) to avoid conflating the two.
