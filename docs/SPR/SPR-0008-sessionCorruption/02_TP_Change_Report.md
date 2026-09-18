---
# jcode-local frontmatter (SPR folder conversion, 2026-09-17).
# jcode is NOT governed by Overwatch's UDRS: no UDRS/ci_impacted/parent numeric
# ids are fabricated here. Only real, repo-verifiable values are used.
id: SPR-0008
title: sessionCorruption - client-local session state overrides server session identity and working directory
status: DRAFT
author: operator
created: 2026-09-17
domain: ENGINEERING
severity: Major
type: SPR.TP_CHANGE
version: "2026-09-17"
---

# SPR-0008: sessionCorruption — client-local session state overrides server session identity and working directory — TP Change Report

> [!WARNING]
> **AGENT INSTRUCTION: This document is NOT a Test Procedure (TP).**
> It is a *Change Report* documenting how a separate regression TP was modified.
> Every code fix requires coverage in an executable TP. Do not attempt to write
> executable bash commands directly into this report.

## Affected TP

- **TP Reference**: none (no dedicated TP currently governs the jcode
  session-resume, `/info`, or client-local session-read code paths)
- **Parent Artifact**: none. jcode is NOT governed by Overwatch's PRACA/TP labor
  model, and no parent TP exists for these code paths.

The affected code paths are:

- `crates/jcode-app-core/src/server/client_lifecycle.rs`
  (`handle_resume_session` cwd override)
- `crates/jcode-app-core/src/agent/turn_execution.rs`
  (`restore_session_with_working_dir`)
- `crates/jcode-tui/src/tui/app/state_ui.rs` (`/info` in remote mode)

None of these paths has an associated standalone TP (the jcode repo has no
`docs/praca/TP/TP-NNN.md`-equivalent), and there is **no parent TP** that could
have governed them. The correct regression mechanism for these fixes is the
jcode Rust test suite (e.g. a sibling-clone resume test and a `/info`
remote-mode identity test), not an Overwatch-style TP.

## Gap Classification (V-1 through V-6)

| Violation | Applies | Evidence |
|:----------|:--------|:---------|
| V-1: Uncovered AC | No | No parent TP exists to leave an AC uncovered |
| V-2: Suppression | No | No RADAR/exception clause involved |
| V-3: Prerequisite not enforced | No | No runtime prerequisite involved |
| V-4: Temporal ordering | No | No TP execution occurred before implementation |
| V-5: Degenerate pass criterion | No | No pass criterion at issue |
| V-6: AC count mismatch | No | No parent TP step count to mismatch |

## tp_gap

- **Category**: `no_tp`
- **Reference**: none — jcode is not governed by Overwatch's UDRS/TP model; no
  dedicated TP or parent TP governs these code paths, so the V-1..V-6 violations
  do not apply.

## Intended Verification (V-1..V-4 coverage)

The fix is verified by jcode's Rust test suite plus manual remote-mode checks, so
no Overwatch-style executable TP is required and none is created. The regression
coverage below maps to the anchor's Verification Completion V-1..V-4 and is
expressed as honest jcode checks, not a fabricated TP document.

## Steps Added / Modified

| # | Step | Expected Result | New/Modified | Maps to V# |
|:--|:-----|:----------------|:-------------|:-----------|
| 1 | Assert `/info` in remote mode renders the server-bound session id/name (resolve through the same accessor `/context` and `update_terminal_title` use) and no longer derives duration from a local stub's `created_at`. | `/info` shows the server session, not a local stub (e.g. not `Session: snail (session_)`). | New | V-1 |
| 2 | Assert resuming a session prefers the target session's stored `working_dir`; a client-reported cwd is advisory only and is refused when it differs from an existing (non-home) path. | Stored `working_dir` unchanged on resume from a sibling clone. | New | V-2 |
| 3 | Add/run the sibling-clone regression test (start in clone A, resume a session bound to clone B). | `working_dir` remains the clone-B path after resume. | New | V-3 |
| 4 | Run jcode's test suite over the touched crates (`cargo test -p jcode-app-core` / `-p jcode-tui`) and complete the audit of remaining `app.session.id`-keyed client-local reads (the `local.rs` filters and `server_events.rs`/`session_persistence.rs`/`state_ui_messages.rs`/`commands.rs`/`session_picker.rs`/`workspace_client.rs`/`catchup.rs` reads). | Tests green; audit shows all listed reads converge on server state in remote mode. | New | V-4 |

## Verification

Against the **pre-fix** state, step 1 fails (`/info` reports the local stub,
e.g. `Session: snail (session_)`), step 2 fails (the persisted `working_dir`
rewrites on resume, as observed for `t-rex` and captured in the server log at
20:43:46), and steps 3-4 fail. Against the **post-fix** state all four steps
PASS. This makes the checks honest regression guards that distinguish the fixed
state from the defect state. These checks are carried as jcode Rust
unit/regression tests and manual remote-mode assertions; no Overwatch-style TP
document is created or claimed.
