# SPR-0005: Visible swarm spawn sessions were never persisted, so the spawned terminal's `jcode --resume <id>` died with "No session found matching ..."

**Files:**
- `crates/jcode-base/src/session/persistence.rs` — `Session::save()` refactored to
  `save_inner(force)`; new public `Session::save_forced()`; unit test
  `plain_save_skips_empty_session_but_save_forced_writes_snapshot`
- `crates/jcode-app-core/src/server/comm_session.rs` — `create_visible_spawn_session()`
  now calls `session.save_forced()` instead of `session.save()`
- `crates/jcode-app-core/src/server/comm_session_tests.rs` — regression test
  `prepare_visible_spawn_session_persists_session_snapshot_for_resume`

**Commit:** `a7b6411bddb882f919c02ae8af6a0448c30da618`
`fix(swarm): persist visible spawn sessions so --resume can attach` (2026-09-16 08:00:17 -0400)

**Status:** Committed locally on the personal no-push clone. Not yet installed:
the running server (v0.85.3-dev `3078606c0`, dirty) predates the fix. Activation
requires a rebuild published to `~/.jcode/builds/current`, which triggers the
server reload path (`server_has_newer_binary` / `reload_exec_target`).

**Author:** Dan Flory (operator) + jcode agent (coordinator session `session_bear`).

---

## Who

| Party | Role |
|---|---|
| Operator (d) | Spawned a "chat session" via `swarm spawn` (visible mode); tried `jcode --resume crab` and `jcode --resume`; reported both fail |
| Coordinator agent (this swarm, `session_bear`) | Spawned the worker, investigated the failure, root-caused it, implemented + tested the fix, committed it. **Current mode:** running at `swarm` effort (light fan-out sentinel) — maximum model reasoning plus swarm orchestration enabled; investigation and fix were performed in this mode. **Model:** DeepSeek V4.1 FLASH |
| Affected users | Anyone who spawns a swarm worker with `spawn_mode: "visible"` (or `"auto"` that resolves to visible) on a headed server |

The failing worker was `session_crab_1789558012763_5ea7c144dffdb54e` (label
"chat session", working dir `/home/d/dev_env`, child of the coordinator).

## What

A visible swarm spawn does two things in the server process
(`spawn_swarm_agent`, `comm_session.rs`):

1. Creates the session record and opens a **separate terminal** running
   `~/.jcode/builds/current/jcode --resume <new-session-id>`.
2. Registers the session as a swarm member ("startup queued") and waits for the
   new client to attach.

The spawned terminal's client resolves `<new-session-id>` **against the on-disk
session store first** (`find_session_by_name_or_id`, `crash.rs:561`), and only
then connects to the shared server. In this failure, the session record was
never written to `~/.jcode/sessions/`, so:

- the spawned terminal hard-exited with `Error: No session found matching
  'session_crab_...'` and the `Use jcode --resume to list available sessions.`
  hint, before ever reaching the server;
- `jcode --resume crab` (short-name match) returned the same error;
- `jcode --resume` (picker) did not list the session at all.

The swarm member existed only in server memory, so the worker sat in
"startup queued" forever, un-resumable.

## When (local EDT, 2026-09-16)

| Time (EDT) | Event |
|---|---|
| 07:26:52 | Coordinator spawns "crab" (visible). Server writes the `client-input-session_crab_*` handoff file; `Session::save()` **no-ops** (see Why) |
| 07:27–07:35 | Spawned terminal opens at `~/.jcode/builds/current/jcode`, runs `--resume session_crab_...`, exits "No session found matching ..." |
| 07:35 | Operator: `jcode --resume crab` and bare `jcode --resume` both fail |
| 07:38–07:44 | Investigation: no `session_crab_*.json` anywhere under `~/.jcode/`; only the client-input handoff; three pre-existing tests already failing on the same defect |
| 07:52 | Fix implemented (`save_forced` + call-site + regression tests) |
| 07:57–07:58 | Tests verified: 7/7 visible-spawn tests, 77/77 `jcode-base` session tests, new unit test |
| 08:00:17 | Commit `a7b6411bd` |
| 08:00 | Broken `crab` session stopped (could never attach; no agent ever created) |

## Why (root cause)

`Session::save()` (`persistence.rs:374`) contains a deliberate guard
(`persistence.rs:390–418`):

```rust
if !force
    && !self.persist_state.snapshot_exists
    && !self.messages.iter().any(is_visible_conversation_message)
    && !self.saved
    && self.custom_title.is_none()
    && self.title.is_none()
    && self.parent_id.is_none()
{
    return Ok(());   // nothing written
}
```

The guard's stated purpose: "A newly opened panel contains only its hidden
session-context message. Do not turn that implementation detail into a
transcript on disk." In other words, an in-memory session that has not produced
a real conversation should not litter `sessions/` with an empty file.

`create_visible_spawn_session` (`comm_session.rs:67`) created
`Session::create(None, None)` — no messages, `saved=false`, no
`custom_title`/`title`/`parent_id` — then called plain `save()`. Every guard
condition held, so **no file was written**. The guard's own comment (added for
issue #1144) names this exact class of failure: "Otherwise later lookups by id
find no file and silently treat the session as missing."

The visible-spawn contract is the inverse of the guard's assumption. The
session is created in one process (the server) and handed to a *different*
process (the spawned terminal) whose first act is an on-disk id lookup. Without
a snapshot file, that lookup fails, and — because the resume is not a reload
handoff (`JCODE_RESUMING` unset) — the CLI hard-exits (`dispatch.rs:682–688`)
rather than deferring to the server. The session is therefore unreachable even
though the server knows about it.

Evidence:
- `~/.jcode/logs/jcode-2026-09-16.log` shows only
  `Headed spawn: persisting startup submission for session_crab_...` — no
  session snapshot write.
- `find ~/.jcode -name '*crab*'` returns only the `client-input-*` handoff and
  unrelated scratch/test artifacts; `~/.jcode/sessions/` has no crab file.
- The session-picker cache (`session-picker-list-v2.json`) lists crab only
  inside the coordinator's transcript text, never as a session.
- Three existing tests already asserted the intended behavior and were **red**:
  `prepare_visible_spawn_session_persists_and_launches_provider_key_for_openrouter_model`,
  `..._persists_requested_effort`, `..._prefers_parent_provider_key_over_model_guess`
  — all failed with `prepared session should save: No such file or directory`.

## How (fix)

1. **`persistence.rs`** — separate the *policy* ("should this empty session be
   skipped?") from the *mechanism* ("write the snapshot"). `save()` becomes a
   thin delegate to `save_inner(false)`, preserving today's skip exactly. A new
   `pub fn save_forced(&mut self)` delegates to `save_inner(true)`, which runs
   the identical persistence pipeline (metadata/vector snapshot or journal
   append, `recent_session_index::upsert_session`, telemetry) with the skip
   guard bypassed.
2. **`comm_session.rs`** — `create_visible_spawn_session` now calls
   `session.save_forced()?`, so the snapshot (with working dir, model,
   provider key, route, and effort overrides) exists on disk before the
   terminal's `--resume` runs.
3. **Tests**
   - `persistence.rs::plain_save_skips_empty_session_but_save_forced_writes_snapshot`:
     asserts the skip still holds for plain `save()` on an empty session, that
     `save_forced()` lands a file, and that `Session::load` round-trips it.
   - `comm_session_tests.rs::prepare_visible_spawn_session_persists_session_snapshot_for_resume`:
     the exact bare-spawn case (all overrides `None`, no startup message) must
     produce a loadable session carrying the requested working dir.

Verification (all green):
- `cargo test -p jcode-base --lib session::persistence::tests::plain_save_skips_empty_session_but_save_forced_writes_snapshot` — 1 passed.
- `cargo test -p jcode-app-core --lib prepare_visible_spawn_session` — 7 passed
  (the 3 previously-red tests now green, plus the new regression test).
- `cargo test -p jcode-base --lib session::` — 77 passed (skip semantics and
  every other persistence path unchanged).

## Design rationale (alternatives considered and rejected)

| Approach | Why rejected |
|---|---|
| Fabricate a `title` on the spawn (title is explicit state the guard honors) | A title surfaces as the session's display name in UIs; an unnamed worker deserves no invented title. Fixes persistence via a visible, semantically-wrong side effect |
| Set `parent_id = <coordinator>` (parent linkage is also honored) | `session.rs:1076` treats any session with a parent as internal (`internal = self.is_debug \|\| self.parent_id.is_some()`), which would hide the user's chat session from the picker. Wrong outcome |
| `mark_saved(None)` (sets the `saved` flag the guard honors) | `saved` renders a 📌 pin in the picker (`render.rs:205`), implying the user bookmarked the session. Misleading |
| Add a `force: bool` parameter to `save()` | Widens the interface for all ~20 existing callers who never opt in; pushes policy decisions onto the whole codebase |
| **`save_forced()` (chosen)** | A single, narrow method that expresses exactly one intent — "this session must exist on disk" — with zero behavior change for every existing caller |

## SOLID analysis (defended)

**S — Single Responsibility.**
`Session::save()` previously carried two responsibilities fused together:
(1) the *policy* of whether a brand-new empty session deserves a transcript on
disk, and (2) the *mechanism* of persisting state. The refactor splits them
explicitly: `save_inner(force)` owns the mechanism and takes the policy as one
boolean; `save()` and `save_forced()` are the two policy faces. The skip policy
still lives in exactly one place (the guard in `save_inner`) rather than being
re-implemented or worked around by each caller. `create_visible_spawn_session`
keeps its single responsibility — prepare a resumable session — and now does so
honestly instead of calling a method whose contract silently declined to write.

**O — Open/Closed.**
The change is strictly additive: a new public capability (`save_forced`) and a
new caller, with `save()`'s observable behavior byte-for-byte identical for
every existing caller. The module is open for extension (new persistence
intents can be expressed without touching the guard) and closed for
modification (no existing caller was edited to accommodate the fix, and the
skip policy for ordinary empty sessions is untouched). Contrast the rejected
alternatives, which would have modified shared visible state (title, pin,
internal flag) to achieve persistence — a modification, not an extension.

**L — Liskov Substitution.**
`save_forced()` is a sibling method on the same concrete `Session` type, not an
override or a subtype, so there is no substitution relationship to violate.
The relevant contract preservation is: code that calls `save()` must still be
able to rely on its documented guarantee ("an untouched empty session is not
persisted"). That guarantee is verified by
`plain_save_skips_empty_session_but_save_forced_writes_snapshot` and by the
pre-existing `untouched_session_is_not_persisted_until_real_conversation_starts`.
Had the fix changed `save()` globally to always write (the naive fix), it would
have silently broken that implicit contract for every existing caller — a
LSP-style behavioral substitution failure. The chosen design substitutes
behavior only where a new, explicit intent is expressed.

**I — Interface Segregation.**
The alternative `save(force: bool)` would have forced every caller to at least
acknowledge a parameter it does not care about, widening the shared interface
and coupling unrelated callers to the "force" concern. `save_forced()` is a
separate, minimal method exposing exactly one additional capability; callers
that only need the default policy never see it. The intent is also more
legible at the call site: `session.save_forced()` reads as "this session must
exist on disk," whereas `session.save(true)` is an opaque boolean trap.

**D — Dependency Inversion.**
The high-level flow (visible spawn: create → persist → launch a resuming
client) depends on an abstraction of persistence — `Session::save()` /
`Session::save_forced()` — and never on the low-level details of snapshot
checkpoints, journal files, or the on-disk store path. The fix preserves that
inversion: `create_visible_spawn_session` expresses *intent* ("must be
resumable by id") through the session API, and the *how* (checkpoint vs
journal, `recent_session_index::upsert_session`, telemetry) stays encapsulated
in `save_inner`. Any future persistence backend satisfies the contract without
the caller changing. This is also why the fix is one line at the call site: the
dependency was already correctly inverted; only the policy default was wrong.

## Side effects (intended)

- `save_forced()` runs the full success path including
  `recent_session_index::upsert_session`, so a freshly spawned visible session
  now also appears in recent/picker listings. This is the desired behavior —
  the session is real, live, and resumable — and is exactly what the operator
  expected from `jcode --resume`.
- The cleanup path (`cleanup_prepared_visible_spawn_session`) already deletes
  the snapshot on a failed/declined launch; it now has something real to clean
  up, which it already did correctly.

## Reproduction

1. From any session, call `swarm spawn` with `spawn_mode: "visible"` (or
   `"auto"` resolving to visible) and a `working_dir`.
2. The server opens a new terminal running `jcode --resume session_<name>_...`.
3. Observe the terminal exit with `Error: No session found matching ...`
   (pre-fix).
4. `jcode --resume <name>` and bare `jcode --resume` also fail to find it.

## Caveats / activation

- The fix lives in the server-side spawn path, so the **running server** must
  be rebuilt and reloaded for new spawns to persist. Until then the old
  behavior (broken visible spawns) persists.
- The already-spawned `crab` session was never persisted and no agent ever
  attached; it cannot be recovered. It has been stopped.
- `save_forced()` is a deliberate opt-out of a product policy (no empty
  transcripts). It should be used only by callers that genuinely hand a session
  to another process that must resolve it by id — not as a general
  "persist empty sessions" switch.

## Revert guard

Reverting `a7b6411bd` restores the pre-fix state exactly: `save()` is the only
entry point, `create_visible_spawn_session` calls plain `save()`, and the three
tests revert to red (they are the canaries that caught this defect). The
regression test added here is the first to exercise the bare-spawn path, which
the original suite did not cover.
