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
type: SPR.DEFICIENCY
version: "2026-09-17"
---

# SPR-0008: sessionCorruption — client-local session state overrides server session identity and working directory — Deficiency Report

## Root Design Failure

The shared-server / remote-mode design in jcode exposes session identity and
working directory through client-local state (`app.session`) while the
authoritative copies live on the server daemon. The design lets a client
substitute its local view wherever a code path happens to read `app.session`
directly, instead of routing every user-facing identity surface through the
server-bound `remote_session_id` accessor that three sibling paths already use.
This is the **"client-local state treated as authority"** class of defect: the
client is a cache, but nothing in the design enforces that it stays a cache.
Deficiency break count: **2** — the two agreed, Confirmed symptoms (A: resume
cwd rewrite, B: `/info` local stub identity) in the anchor.

## What the Original Design Got Wrong (2 deficiencies)

1. **Resume cwd override is read from the wrong session and applied
   unconditionally.** `client_lifecycle.rs` computes `resume_working_dir` from
   the *current* agent (the client's freshly created session bound to the
   client's launch cwd), not from the resume *target*, and passes it as
   `working_dir_override` to `handle_resume_session`
   (`client_lifecycle.rs:1848-1851,1864`). `restore_session_with_working_dir`
   then applies it unconditionally (`client_session.rs:1568-1571`,
   `turn_execution.rs:689-692`). The only guard,
   `subscribe_working_dir_replacement` (`client_session.rs:489-509`), rejects
   only the home directory; a sibling clone passes through, so resuming silently
   rewrites the persisted `working_dir`.

2. **`/info` renders client-local state instead of server truth.** `/info`
   reads `app.session.short_name` and `app.session.id[..8]`
   (`state_ui.rs:1913-1917`) and `std::env::current_dir()`
   (`state_ui.rs:1888-1890`) — all client-local — even though three sibling
   identity surfaces (`tui_state.rs:885-903`, the server-bound
   `session_display_name()`; `commands.rs:2650-2657`, `active_session_id()`;
   `tui_lifecycle_runtime.rs:76-82`, `update_terminal_title()`) already prefer
   `remote_session_id`. `/info` is the outlier. The parenthesised `session_` in
   the output is a truncated id prefix from a local placeholder.

## Impact Assessment

**Live evidence (2026-09-17, Confirmed in the anchor).**

- **Session `t-rex` cwd rewrite.** Resumed from a client whose cwd was a sibling
  clone; on-disk `working_dir` rewrote from `/home/d/dev_env/clones/Overwatch_2`
  to `/home/d/dev_env/clones/Overwatch`. Evidence: the pre-wipe backup
  `session_t-rex_....json.pre-wipe-1789671862548.bak` (19:04) holds
  `Overwatch_2` while the live file holds `Overwatch`; the server log timestamps
  the rewrite at `20:43:46.259` (create `chick`), `20:43:46.336` (resume_start
  `t-rex`), `20:43:46.560` (resume ENV_SNAPSHOT with the new cwd).
- **`/info` local-stub identity.** A remote client printed
  `Session: snail (session_)` — a client-local stub, not the serving session.
  An agent asked "what session are you?" answered `eagle` (the on-disk session
  matching its context) while the footer reported `snail`; neither was
  authoritative because the runtime exposes no client-visible ground truth.

**Impact of the class of defect.**

- **Wrong working directory for tools.** `bash` runs with
  `command.current_dir(dir)` (`bash.rs:933`); a rewrite points every subsequent
  command at the wrong repository. In a swarm sharing one server, workers can be
  misdirected at a sibling clone.
- **Cross-session bleed / wrong answers.** Local reads and filters keyed on the
  client's `app.session.id` can match or miss the wrong session when the local
  placeholder differs from the server id.
- **Misleading identity and diagnostics.** `/info`, terminal titles, transcripts,
  todo/goal titles, prompt history, and side panels can all describe a
  different session than the one actually serving the turn.

## Corrective Design

Converge every user-facing identity surface on server state:

1. **`/info` identity in remote mode** — resolve session id/name through the
   server-bound accessor (as `/context`, `update_terminal_title`, and
   `active_session_id()` already do) and stop deriving duration from a local
   stub's `created_at`.
2. **Resume cwd precedence** — prefer the target session's stored
   `working_dir`; treat a client-reported cwd as advisory and refuse to
   overwrite a differing existing (non-home) path; add a sibling-clone
   regression test.
3. **Audit and converge the wider class** — local session-file reads and BUS
   filters that use `app.session.id` (`local.rs:230,289,297,349,439,491,551,589`;
   `server_events.rs:2815`, `remote/session_persistence.rs:58`,
   `state_ui_messages.rs:377`, `commands.rs:436`, `session_picker.rs:932`,
   `workspace_client.rs:225`, `catchup.rs:55`) converge on server state in
   remote mode.

Guiding rule: **in remote mode `app.session` is a cache, never an authority.**

## Convergence Pattern Check

Not applicable: neither requirement involves iteration, retry, or batch logic
(this SPR does not reference any convergence pattern). The fixes are a targeted
server-bound accessor substitution and a resume-cwd precedence change, each with
a direct regression check.
