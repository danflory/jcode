# SPR-0004: DeepInfra wire tier stays "flex" regardless of openai_service_tier config

**Status:** OPEN — instrumented; probe server running; awaiting request capture.
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

## REVERT GUARD (current state)

- Config: `~/.jcode/config.toml` line 121 = `"standard"` (restored; backup
  `~/.jcode/config.toml.bak-priority-test` exists but is a pre-test backup and can
  be removed after this SPR closes).
- Production server PID 2584151: unchanged, still the old locked binary.
- Debug server PID 2632298: running; kill + remove temp dirs per C4 undo.
