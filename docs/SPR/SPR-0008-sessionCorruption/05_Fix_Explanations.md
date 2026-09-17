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
type: SPR.FIX_REPORT
version: "2026-09-17"
---

# SPR-0008: sessionCorruption — Fix Explanations

Date: 2026-09-17
Branch: `sessionCorruption`

This report explains the two fix commits made for SPR-0008, and argues why they
(plausibly) resolve the reported symptoms. It is a companion to the anchor
(`SPR-0008.md`), the Deficiency Report (`01_Deficiency_Report.md`), and the TP
Change Report (`02_TP_Change_Report.md`).

The two commits are:

- **Fix B (identity)** — `94b211c60`
  "fix(tui): report server-bound session identity in /info remote mode"
  (`crates/jcode-tui/src/tui/app/state_ui.rs`,
   `crates/jcode-tui/src/tui/app/tests.rs`)
- **Fix A (cwd)** — `b1f65c323`
  "fix(app-core): resume cwd is advisory and never clobbers stored working_dir"
  (`crates/jcode-app-core/src/agent/turn_execution.rs`,
   `crates/jcode-app-core/src/agent_tests.rs`)

Both target the anchor's root cause: client-local session state treated as
authoritative over server truth.

---

## Fix B — `/info` reports the server-bound session in remote mode

### a. Symptom it addresses (Symptom B)

In remote mode, `/info` printed a client-local stub session identity instead of
the server-bound session. Observed concrete evidence from the anchor
(`SPR-0008.md:70-89`):

```
Session: snail (session_)
CWD: /home/d/dev_env/jcode
Remote Mode: connected
```

`snail` is a *local client-side stub*; the parenthesised `session_` is a
truncated id prefix sliced from a local placeholder. An agent asked
"what session are you?" answered `eagle` (the on-disk session matching its
context) while the footer reported `snail`; neither declared identity was
authoritative.

### b. What changed, precisely

**File:** `crates/jcode-tui/src/tui/app/state_ui.rs`, function
`handle_info_command` (the `/info` handler), hunks at lines
`crates/jcode-tui/src/tui/app/state_ui.rs:1911-1940` (current file).

**Before** (`git show 94b211c60` removed hunk):

```rust
info.push_str(&format!(
    "Session: {} ({})\n",
    app.session.short_name.as_deref().unwrap_or("unnamed"),
    &app.session.id[..8]
));
```

`/info` read `app.session.short_name` and `app.session.id[..8]` directly — the
client-local cache/startup stub.

**After** (current file):

```rust
let session_id = app
    .active_client_session_id()
    .unwrap_or(app.session.id.as_str());              // state_ui.rs:1918-1920
let session_name = if app.is_remote {
    crate::id::extract_session_name(session_id)
        .map(str::to_string)
        .unwrap_or_else(|| session_id.to_string())    // state_ui.rs:1921-1924
} else {
    app.session.short_name.as_deref().unwrap_or("unnamed").to_string()
};
let session_prefix = if session_id.len() >= 8 && session_id.starts_with("session_") {
    &session_id[..8]                                  // state_ui.rs:1935-1939
} else {
    session_id
};
info.push_str(&format!("Session: {} ({})\n", session_name, session_prefix));
```

The id is now resolved through `active_client_session_id()`, the same
server-bound accessor `/context` and `update_terminal_title` use; the display
name comes from `extract_session_name` in remote mode; and the id is only sliced
to 8 chars when it is long enough and carries the real `session_` prefix.
Non-remote behavior is unchanged (it keeps `app.session.short_name`).

### c. The mechanism

**Old causal chain:** `app.session` is a client-local startup stub
(`SPR-0008.md:146-154`, `tui_lifecycle.rs:1335-1339`). `/info` read that stub
directly, so whatever the client put in the placeholder became the reported
session identity, even though the server is the only authority for the session
id and name. This produced `Session: snail (session_)` and left the actual
serving session hidden. The degenerate `(session_)` came from slicing a stub id
with no usable content: `&app.session.id[..8]` on a placeholder shorter than 8
chars or without a real `session_` prefix renders `session_` and nothing else.

**How the new code breaks it:** the id is resolved through
`active_client_session_id()`, which (like the three sibling identity surfaces
already in the anchor's root-cause chain: `tui_state.rs:885-903`,
`commands.rs:2650-2657`, `tui_lifecycle_runtime.rs:76-82`) prefers the
server-bound `remote_session_id` when the app is in remote mode. The display
name and the parenthesised prefix are both derived from that server-bound id, and
the prefix guard prevents the misleading `(session_)` placeholder. The
client-local stub is no longer substituted as the identity.

### d. Why this plausibly resolves it

The anchor's root cause is that client-local state is treated as authoritative
where a code path reads `app.session` directly. Fix B routes the one outlier
identity surface (the `/info` session line) through the server-bound accessor,
restoring server state as the authority for what `/info` reports. Unlike its
three sibling paths, `/info` is the *only* user-facing surface a user/agent can
query directly to ask "what am I?" — so this closes the concrete observable
mismatch documented in Symptom B.

This is marked **plausibly resolves**, not "resolves", because the fix is
demonstrated only at the unit level (see the Verification table): the regression
test proves `/info` renders the server-bound id, but no manual end-to-end
remote-mode check against the live shared-server topology was run for this
document, and the fix is presentation/identity only — it does not by itself
prevent any state corruption (see Fix A and Residual Risk).

### e. Tests added

File: `crates/jcode-tui/src/tui/app/tests.rs` (current lines).

1. **`info_command_reports_server_session_identity_in_remote_mode`**
   (`tests.rs:857-881`). Sets `app.session` to the `snail` stub and
   `remote_session_id` to `session_eagle_...`, runs `/info`, and asserts the
   output contains `Session: eagle (session_)`, does **not** contain `snail`,
   and contains `Remote Mode: connected`. Proves the server-bound id, not the
   local stub, is reported in remote mode.
2. **`info_command_keeps_local_session_identity_outside_remote_mode`**
   (`tests.rs:883-895`). With only `app.session` set to `snail` and no
   `remote_session_id`, runs `/info` and asserts `Session: snail (session_)` is
   kept. Proves non-remote behavior is unchanged.

### f. Verification status (Fix B)

| Check | Result |
|:------|:-------|
| Regression tests `info_command_reports_server_session_identity_in_remote_mode` and `info_command_keeps_local_session_identity_outside_remote_mode` | **UNVERIFIED-BY-THIS-DOC** — test bodies written in commit `94b211c60` and present at `tests.rs:857-895`, but not executed for this document |
| `cargo test -p jcode-tui` | **UNVERIFIED-BY-THIS-DOC** — not run here |
| Manual remote-mode `/info` against the live shared server | **UNVERIFIED-BY-THIS-DOC** — no live topology check performed for this document |

---

## Fix A — resume cwd is advisory and never clobbers the stored `working_dir`

### a. Symptom it addresses (Symptom A)

Resuming a session silently rewrote that session's persisted `working_dir`,
moving resumed work to a sibling clone. Observed concrete evidence from the
anchor (`SPR-0008.md:35-68`):

- Session `session_t-rex_1789662214733_691326d2e2194bf2` was created with
  `working_dir = /home/d/dev_env/clones/Overwatch_2`; late in the session, `pwd?`
  reported `/home/d/dev_env/clones/Overwatch` — a *different clone* — and the
  agent flagged the mismatch.
- On-disk: the `.bak` file held `Overwatch_2`, the live file held `Overwatch`
  (`SPR-0008.md:48-53`).
- Server log: create `chick` with `working_dir=.../Overwatch` at
  `20:43:46.259`, resume_start `t-rex` at `20:43:46.336`, resume ENV_SNAPSHOT
  rewriting `t-rex` at `20:43:46.560` (`SPR-0008.md:55-68`).

### b. What changed, precisely

**File:** `crates/jcode-app-core/src/agent/turn_execution.rs`, function
`restore_session_with_working_dir`, hunk at
`crates/jcode-app-core/src/agent/turn_execution.rs:688-708` (current file).

**Before** (`git show b1f65c323` removed hunk):

```rust
if let Some(working_dir) = working_dir {
    session.working_dir = Some(working_dir.to_string());
    session.refresh_initial_session_context_message();
}
```

The supplied `working_dir` was written unconditionally, overwriting any stored
value.

**After** (current file):

```rust
if let Some(working_dir) = working_dir {
    let has_stored_dir = session
        .working_dir
        .as_deref()
        .map(str::trim)
        .is_some_and(|dir| !dir.is_empty());   // turn_execution.rs:699-703
    if !has_stored_dir {
        session.working_dir = Some(working_dir.to_string());
        session.refresh_initial_session_context_message();  // lines 704-707
    }
}
```

The caller-supplied cwd is applied **only** when the target session has no
usable stored directory (None or empty). When the session already has a stored,
differing cwd, that stored value wins and the supplied one is ignored.

### c. The mechanism

**Old causal chain:** on resume, `client_lifecycle.rs` computed
`resume_working_dir` from the *current* agent — the client's freshly created
session bound to the client's launch cwd — and passed it as
`working_dir_override` to `handle_resume_session`
(`SPR-0008.md:133-144`, `client_lifecycle.rs:1848-1851,1864` →
`client_session.rs:1568-1571`). `restore_session_with_working_dir` applied it
unconditionally (`turn_execution.rs:689-692`). The only guard,
`subscribe_working_dir_replacement` (`client_session.rs:489-509`), rejects only
the home directory when the session already has a different non-home cwd; a
sibling clone (`Overwatch` vs `Overwatch_2`) passes through. So a client
launched in a sibling clone silently rewrote the resume target's stored cwd:
`chick` (bound to `Overwatch`) resumed `t-rex` (stored `Overwatch_2`) and moved
it to `Overwatch`.

**How the new code breaks it:** the stored `working_dir` is now read first and
treated as authoritative. The override is applied only when the stored value is
absent. A differing existing stored cwd is never rewritten, so resuming from a
sibling clone cannot clobber the target's real working directory. The
`refresh_initial_session_context_message()` call (and thus any context re-derive
from the rewritten cwd) only runs in the genuinely-no-cwd case.

### d. Why this plausibly resolves it

The anchor's root cause is that client-local state (here, the resuming client's
cwd) is treated as authoritative over server truth (the target session's stored
`working_dir`). Fix A makes the target session's stored directory the authority
and demotes the client-reported cwd to advisory, applied only for sessions that
genuinely lack a cwd. This directly reverses the recorded corruption: the
`t-rex` live file would no longer be rewritten from `Overwatch_2` to
`Overwatch` on a sibling-clone resume.

This is marked **resolves** for the specific stored-cwd-preservation behavior,
because the regression test `resume_supplied_cwd_does_not_clobber_stored_working_dir`
demonstrates the exact defect state (a session stored at `/workspace/Overwatch`,
resumed with a reported `/workspace/Overwatch_2`, ends with its stored
`/workspace/Overwatch` intact) and the companion test pins the only remaining
override path. However, it is **not** a complete resolution of the whole SPR:
it guards only the resume override path, not every route that can set a session
cwd (see Residual Risk).

### e. Tests added

File: `crates/jcode-app-core/src/agent_tests.rs` (current lines).

1. **`resume_supplied_cwd_does_not_clobber_stored_working_dir`**
   (`agent_tests.rs:1192-1221`). Builds an `Agent`, creates a session whose
   stored `working_dir` is `/workspace/Overwatch`, then calls
   `restore_session_with_working_dir` with a reported `/workspace/Overwatch_2`
   (a sibling clone). Asserts `agent.working_dir()` is still `Some(stored_dir)`.
   Proves the stored cwd wins over a differing reported cwd.
2. **`resume_supplied_cwd_applies_when_session_has_no_stored_dir`**
   (`agent_tests.rs:1223-1245`). Creates a session with `working_dir = None`
   and calls `restore_session_with_working_dir` with `/workspace/Overwatch_2`.
   Asserts `agent.working_dir()` is `Some(reported_dir)`. Proves the override is
   still honored when the session truly has no cwd yet.

### f. Verification status (Fix A)

| Check | Result |
|:------|:-------|
| Regression tests `resume_supplied_cwd_does_not_clobber_stored_working_dir` and `resume_supplied_cwd_applies_when_session_has_no_stored_dir` | **UNVERIFIED-BY-THIS-DOC** — test bodies written in commit `b1f65c323` and present at `agent_tests.rs:1192-1245`, but not executed for this document |
| `cargo test -p jcode-app-core` | **UNVERIFIED-BY-THIS-DOC** — not run here |
| Manual sibling-clone resume against the live shared server | **UNVERIFIED-BY-THIS-DOC** — no live topology check performed for this document |

---

## Residual Risk / NOT COVERED

These two fixes are narrow-first and do **not** fully resolve the SPR's wider
"client-local state as authority" class:

1. **Fix B may be necessary but NOT sufficient: the target-aware subscribe path
   re-applies the client-reported cwd after resume, so symptom A may still
   reproduce on a sibling-clone attach.** This is stronger than a generic
   "different code path" caveat; it is the *same* path the original incident
   used. The chain, verified against the current files:
   - `crates/jcode-app-core/src/server/client_lifecycle.rs:1597-1690` — the
     target-aware `Request::Subscribe { target_session_id: Some(target),
     working_dir }` path first calls `handle_resume_session` (line `1611`),
     passing `subscribe_working_dir.as_deref()` as the resume override, and only
     afterwards (when `client_session_id == target_session_id`) calls
     `handle_subscribe` (line `1656`).
   - `crates/jcode-app-core/src/server/client_session.rs:648-649` —
     `handle_subscribe` does
     `if let Some(ref dir) = subscribe_working_dir { apply_or_defer_subscribe_working_dir(agent, dir, client_session_id); ... }`
     with **no** guard for a resume target.
   - `crates/jcode-app-core/src/server/client_session.rs:489-509` —
     `subscribe_working_dir_replacement` rejects only the home directory when the
     session already has a different non-home cwd; a sibling clone path is
     therefore **accepted**.
   - `crates/jcode-app-core/src/agent/provider.rs:307-315` — `set_working_dir`
     then assigns `self.session.working_dir = Some(dir)`, overwriting the stored
     dir.
   - The client always sends its cwd on a resume attach:
     `crates/jcode-tui/src/tui/backend.rs:351` builds
     `(working_dir, selfdev) = super::subscribe_metadata(remote_working_dir)` and
     includes it in the `Subscribe` at `backend.rs:357-372`.
   - **Chain:** Fix A (commit `b1f65c323`) makes step 1 (resume) preserve the
     stored cwd, but step 2 (subscribe) immediately re-applies the client's
     reported cwd, reverting the preserved value and re-introducing the
     sibling-clone rewrite.
   - **Original incident used this exact path:** the server log at
     `2026-09-17T20:43:46` showed
     `phase=resume_start request_id=1 source_session_id=session_chick target_session_id=session_t-rex`,
     i.e. the target-aware `Subscribe` path where step 2 still applies the
     reported cwd.
   - **Status: UNVERIFIED.** This is a code-level analysis of the current
     sources, not a reproduction. I did not re-run the live sibling-clone attach
     to confirm symptom A reproduces after fix B, so do not treat the
     "may still reproduce" claim as proven.
2. **Fix A only covers the resume override.** It does not cover every route that
   can set a session `working_dir` (e.g. the subscribe path above, session
   creation-time cwd binding, or any other writer of `session.working_dir`).
3. **The anchor's item 3 (the wider client-local-state audit) is still
   unimplemented.** The audit of BUS filters and local session-file reads listed
   in `SPR-0008.md:185-192` (the `local.rs` filters and
   `server_events.rs`/`remote/session_persistence.rs`/`state_ui_messages.rs`/
   `commands.rs`/`session_picker.rs`/`workspace_client.rs`/`catchup.rs` reads)
   remains open, so other surfaces may still substitute client-local state for
   server truth.
4. **Fix A is presentation/identity only and does not by itself prevent any
   state corruption.** It makes `/info` report the server-bound session, but it
   does not stop the resume-override (that is Fix A's job) or any other write
   from rewriting a session's `working_dir`.
