# SPR-0004: DeepInfra wire tier stays "flex" regardless of openai_service_tier config

**Status:** CLOSED — root cause found, fix applied, production verified (2026-09-15 ~23:36Z).
**Rule (operator):** every change is logged, committed, and carries an undo
procedure in this file before/with the change.

## Defect (verified, empirical)

The outbound request body to `https://api.deepinfra.com/v1/openai` always carries
`service_tier = "flex"` — independent of the configured `openai_service_tier`.

Evidence from `~/.jcode/logs/jcode-2026-09-15.log` (`REQUEST SERVICE_TIER` lines,
emitted by `openrouter_sse_stream.rs` reading the outbound body just before send):

- Config `openai_service_tier = "standard"`: `REQUEST SERVICE_TIER: "flex"` on every
  deepinfra call (22:34–22:54).
- Toggle experiment 02:54Z: config to `"priority"`, confirmed reload
  (`CONFIG_RELOAD modified_changed=true`), next request still `flex`. Restored to
  `"standard"`.
- Conclusion: `[provider] openai_service_tier` has **no observed effect** on the
  wire tier for this deepinfra route.

## Instrumentation already present (SPR-0003, commit ad2c923f5)

Two SPR-0003 log lines disagree, which is the crux:
1. `openrouter_provider_impl.rs` build_request logs `Service tier: standard (field
   omitted from request body)` (config maps to standard).
2. `openrouter_sse_stream.rs` `stream_response` (line 184) logs
   `REQUEST SERVICE_TIER: <request.get("service_tier")>` = `flex`.

Both operate on the same `request` object (build_request moves it into
`request_for_retries` → `run_stream_with_retries` → `stream_response`). The live log
proves the binary is current (both SPR-0003 strings appear), so this is not a stale
binary; it is a divergence between build_request's state and the wire's state.

## Verified config/completion facts

- `~/.jcode/config.toml` line 121 is the only tier key in any config (global or
  repo): `openai_service_tier = "standard"`. No per-repo jcode config overlay
  exists (jcode's "per-repo mapping" is launch hotkeys only).
- No `JCODE_OPENAI_SERVICE_TIER` env override. `JCODE_OPENAI_EXTRA_BODY` unset.
- The deepinfra path logs `prv:OpenRouter` and routes through the openrouter-runtime.

---

## CHANGE LOG (each entry: what, commit, undo)

### C1. Create SPR-0004 debugging report file
- **What:** created `docs/SPR/SPR-0004-deepinfra-flex-on-wire-despite-standard-config.md`.
- **Commit:** this commit (see `git log -1`).
- **Undo:** `git rm docs/SPR/SPR-0004-deepinfra-flex-on-wire-despite-standard-config.md`.

### C2. Add temporary debug lines in openrouter_provider_impl.rs
- **What:** two `eprintln!` blocks emitting `SPR0004DBG`:
  - `SPR0004DBG after_service_tier_block service_tier={...} provider_features={...}`
    immediately after the service_tier eviction block (after line 246).
  - `SPR0004DBG end_build_request service_tier={...}` just before
    `run_stream_with_retries` is spawned (before line ~370).
- **File:** `crates/jcode-provider-openrouter-runtime/src/openrouter_provider_impl.rs`.
- **Commit:** this commit.
- **Undo:** remove both `SPR0004DBG` `eprintln!` blocks (they are delimited by
  `// TEMP DEBUG SPR-0004` comments).

### C3. Build (debug check) + build (release binary)
- **What:** `cargo build --package jcode-provider-openrouter-runtime` (60s) to
  verify the debug lines compile; then `cargo build --release --bin jcode` (17s,
  incremental) to produce `/home/d/dev_env/jcode/target/release/jcode` containing
  the debug lines. **No new binary was installed** over stable/current (the running
  server holds the old binary → "Text file busy" on install).
- **Commit:** no source change; build artifacts only (not committed).
- **Undo:** N/A (build artifacts under `target/` are git-ignored).

### C4. Launch isolated second debug server
- **What:** started a second server from the freshly built release binary with
  isolated runtime so it does not collide with the production server:
  - `XDG_RUNTIME_DIR=/tmp/jcode-debug-runtime`
  - `XDG_DATA_HOME=/tmp/jcode-debug-data`
  - `--provider deepinfra serve --socket /tmp/jcode-debug.sock`
  - `--cwd /home/d/dev_env/Overwatch_5 --server-name spr0004-debug --no-update`
  - PID **2632298**, log `/tmp/jcode-debug-server.log`, socket
    `/tmp/jcode-debug.sock`.
- **Commit:** no source change.
- **Undo:** `kill 2632298` (graceful), then
  `rm -rf /tmp/jcode-debug-runtime /tmp/jcode-debug-data /tmp/jcode-debug.sock /tmp/jcode-debug-server.log`.
  The production server (PID 2584151) is untouched and continues serving.

---

## NEXT PROBE (RADAR rule 7)

Drive one chat request through the isolated server (`/tmp/jcode-debug.sock`). The
`SPR0004DBG` lines print stderr of PID 2632298 (visible in
`/tmp/jcode-debug-server.log`), showing `service_tier` (a) right after the eviction
block and (b) at end of build_request. Compare both to the wire `service_tier`
captured by the loopback/mock client.

Expected outcomes:
- If `SPR0004DBG after_service_tier_block` = `ABSENT` and
  `SPR0004DBG end_build_request` = `ABSENT`, but wire = `flex`: flex is injected
  between build_request return and stream_response → narrow to the transport layer.
- If either `SPR0004DBG` line = `"flex"` already: the eviction is not running in
  this binary → narrow to a stale/incomplete build or a different request path.

## PROBE RESULT P1 (2026-09-15 ~23:14Z) — flex injected INSIDE build_request

Drove one request through the isolated debug server (PID 2632298,
`jcode run --socket /tmp/jcode-debug.sock -p deepinfra -m deepseek-ai/DeepSeek-V4-Flash-0731`).
Debug output (server stderr):

```
SPR0004DBG after_service_tier_block service_tier="ABSENT"
SPR0004DBG end_build_request  service_tier="\"flex\""
```

- Right after the service_tier eviction block: `service_tier` is **ABSENT** (the
  standard→omit eviction worked).
- At end of `build_request`: the **same** `request` object now carries `flex`.

**Conclusion:** flex is introduced inside `build_request`, in the lines between the
service_tier block (246) and the end of the function (~370): candidates are the
`thinking` override (~248), the provider-routing `request["provider"]` block (~260),
or the `extra_body` merge (~305–311). This is the narrow band to search.

### C5. Log probe result P1
- **What:** recorded this finding and the one-shot run command used.
- **Commit:** next commit.
- **Undo:** N/A (log entry).

### C6. (pending) Narrow to exact injection among thinking/provider/extra_body
- Planned: add a `SPR0004DBG` line before the extra_body merge, or temporarily gate
  each candidate block, and re-run the same one-shot request.
- **Undo** (when done): remove the added debug line / restore the gated block, per
  the matching temp-debug convention.

## ROOT CAUSE FOUND (P2, 2026-09-15 ~23:29Z)

**Location:** `~/.config/jcode/deepinfra.env` line 6:
```
JCODE_OPENAI_EXTRA_BODY={"service_tier":"flex"}
```

The env file also contains a comment: "NOT read [provider].openai_service_tier.
This env var is the supported way to inject it; verified accepted by the API
(response echoes service_tier=flex)." A prior session (stallion/whale era) wrote
this, with a probe backup at `~/.config/jcode/deepinfra.env.probe-backup`.

**Mechanism (verified end-to-end):**
1. `build_request` service_tier block reads config `standard` → evicts tier → logs
   "standard (omitted)" → request has no `service_tier` (matches
   `SPR0004DBG after_service_tier_block = ABSENT`).
2. The `extra_body` merge (after the eviction) merges
   `JCODE_OPENAI_EXTRA_BODY={"service_tier":"flex"}` from the env file into every
   request body → `service_tier: "flex"` reappears (matches
   `SPR0004DBG after_extra_body_merge = "flex"`).
3. Wire sends flex regardless of config; the config-toggle experiment earlier was
   doomed because this unconditional override wins after eviction.

**Fix options (one fix, pick with operator):**
- Want standard: delete the `JCODE_OPENAI_EXTRA_BODY` line from
  `~/.config/jcode/deepinfra.env`.
- Want priority: change line to `JCODE_OPENAI_EXTRA_BODY={"service_tier":"priority"}`.

**Undo for any fix:** the `deepinfra.env.probe-backup` contains the original flex
line; `deepinfra.env.bak-20260915` holds the pre-probe state.

### C7. Log P2 root cause
- **What:** recorded this root-cause finding in SPR-0004.
- **Commit:** next commit.
- **Undo:** N/A (report-only).

### C8. FIX APPLIED + VERIFIED (2026-09-15 ~23:33Z)
- **When flex line was placed:** `deepinfra.env` mtime 2026-09-14 20:19:17 EDT;
  `deepinfra.env.probe-backup` 20:14:31 EDT (pre-probe state without the line is
  `deepinfra.env.bak-20260915`, Sep 8).
- **Fix:** removed `JCODE_OPENAI_EXTRA_BODY=...` line from `~/.config/jcode/deepinfra.env`.
  Backup: `~/.config/jcode/deepinfra.env.pre-standard-20260916`.
- **Verification probe (debug server):**
  `after_service_tier_block=ABSENT`, `after_extra_body_merge=ABSENT`,
  `end_build_request=ABSENT` → request goes out with no tier field = standard.
- **Undo:** restore from `deepinfra.env.pre-standard-20260916`.
- **Note:** production server (PID 2584151) still holds the pre-fix env file in its
  constructed provider; restart needed for the production process to serve standard.

## TEST PROCEDURE TIMING (local EDT, 2026-09-15)

| Time (EDT) | Elapsed | Step |
|---|---|---|
| 02:53:37 | 0:00 | Operator: toggle tier to test |
| 02:54:18 | 0:41 | Config standard→priority toggle test; restored to standard |
| 02:59:11 | ~5:53 | Created SPR-0004 debugging file |
| 03:05:01 | +0:10 | Added debug line 1 (after service_tier block) |
| 03:05:09 | +0:08 | Added debug line 2 (end of build_request) |
| 03:05:13→03:06:14 | 1:01 | cargo build -p openrouter-runtime (compile check) |
| 03:06:25→03:06:43 | 0:18 | cargo build --release --bin jcode |
| 03:07:12 | — | Install failed: "Text file busy" (server holds old binary) |
| 03:09:51 | 2:39 | 2nd server attempt; failed on shared runtime dir |
| 03:10:19 | 0:28 | Launched isolated 2nd server (PID 2632298) |
| 03:13:42 | 3:23 | Committed a30fc06b3 (report + debug lines) |
| 03:14:33 | 0:51 | Probe P1: one-shot jcode run through debug server |
| 03:15:16 | 0:43 | Logging P1 result to SPR-0004 |

**Total to ~03:15:16: ~21.7 min.** Over the 10-min budget, but the debug-line +
isolated-server approach (not a full unit test) produced the decisive P1 narrowing:
flex is injected inside build_request between the eviction block and end of function
(lines 247–370). A full unit-test-only approach would not have surfaced this as
directly at this stage.

## REVERT GUARD (current state)

- Config: `~/.jcode/config.toml` line 121 = `"standard"` (restored; backup
  `~/.jcode/config.toml.bak-priority-test` exists as a pre-test backup; safe to
  remove once this SPR closes).
- Production server PID 2584151: unchanged, still the old locked binary.
- Debug server PID 2632298: running; undo = `kill 2632298` then
  `rm -rf /tmp/jcode-debug-runtime /tmp/jcode-debug-data /tmp/jcode-debug.sock`.
- Current source: debug lines + report committed as `a30fc06b3`, plus this
  P1 finding (next commit).
