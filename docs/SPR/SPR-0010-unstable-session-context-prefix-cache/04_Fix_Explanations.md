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
type: SPR.FIX_REPORT
version: "2026-09-18"
---

# SPR-0010: Fix Explanations

Date: 2026-09-18
Branch: `dev`

This report explains the fix for SPR-0010, the mechanism by which it resolves the
reported defect, its test coverage, and its residual risk. It is a companion to
the anchor (`SPR-0010.md`), the Deficiency Report
(`01_Deficiency_Report.md`), the TP Change Report (`02_TP_Change_Report.md`), and
the Cost Evidence (`03_Cost_Evidence.md`).

> [!NOTE]
> **Implementation status.** The **observability** half of this SPR is
> implemented and verified (commit `b89aeaf6d`): `JCODE_TRACE=1` now dumps the
> exact rendered request payload, confirming the defect directly. The **fix**
> half is still **not applied** — `build_session_context` in
> `crates/jcode-base/src/prompt.rs:699` still emits `session_datetime_lines()`
> third. This document specifies the fix precisely so it can be implemented and
> reviewed against a written contract.

## The Change

**One function, one reordering.** In
`crates/jcode-base/src/prompt.rs::build_session_context`, move the datetime
lines from third position to last position:

```rust
pub fn build_session_context(working_dir: Option<&Path>) -> String {
    let mut lines = vec!["# Session Context".to_string()];

    // STABLE BLOCK — must be byte-identical across sessions on the same
    // machine, build, and working directory. No volatile field may precede
    // any line below.
    lines.push(format!("OS: {}", std::env::consts::OS));
    lines.push(format!("Architecture: {}", std::env::consts::ARCH));
    lines.push(format!(
        "Jcode version: {} ({})",
        jcode_build_meta::version(),
        jcode_build_meta::git_hash()
    ));

    if let Some(hardware) = hardware_context() {
        lines.push(hardware);
    }

    let cwd = working_dir.map(Path::to_path_buf);
    if let Some(cwd) = cwd.as_deref() {
        lines.push(format!("Working directory: {}", cwd.display()));
        if let Some(git_info) = get_git_info(Some(cwd)) {
            lines.push(git_info);
        }
    }

    // VOLATILE BLOCK — last, so it cannot truncate the stable prefix.
    lines.extend(session_datetime_lines());

    lines.join("\n")
}
```

No signature change, no new dependency, no caller change. The function remains
pure apart from `chrono::Local::now()`.

## Mechanism

Provider prefix caching matches on a **byte-identical request prefix**. Before
the fix the first provider-visible message reads:

```
# Session Context
Date: 2026-09-18      <- differs daily
Time: 14:33:34        <- differs every second  <-- divergence point
Timezone: -04:00
OS: linux
Architecture: x86_64
Jcode version: ...
```

so the longest prefix any two sessions share ends mid-`Time:`. Measured: **60
characters**, across all three models tested (`03_Cost_Evidence.md` §2).

After the fix the same block reads:

```
# Session Context
OS: linux
Architecture: x86_64
Jcode version: ...
Hardware: ...
Working directory: ...
git info
Date: 2026-09-18
Time: 14:33:34
Timezone: -04:00
```

Every shared field now precedes every volatile field, so the common prefix
extends to the start of the `Date:` line. Sessions started the same day on the
same machine, build, and working directory share the entire block.

**Why this is the whole fix.** The defect is ordering, not content. The block was
already correctly positioned as the first provider-visible item; it was
correctly per-session immutable; it was correctly wrapped and identifiable. Only
the intra-block field order was wrong, and field order is exactly what
determines how far a prefix match extends.

## Observability: seeing the real payload (implemented)

Before implementing the fix, an observability lever was added so the diagnosis
can be *seen* rather than inferred. Commit `b89aeaf6d`.

`Agent::dump_request_prefix` (`crates/jcode-app-core/src/agent/prompting.rs`) is
called at both send points — `turn_loops.rs` (blocking) and
`turn_streaming_mpsc.rs` (streaming) — immediately after request assembly, with
the final `send_messages`, `tools`, and `split_prompt` in hand. It emits, in wire
order:

- the static system prompt, then the dynamic system prompt
- the tool schemas, plus a `fingerprint(name:desc_len)` for the whole tool set
- each leading provider-visible message with `role` and rendered `len`

Gated on the **existing** `JCODE_TRACE` switch via `logging::debug`, so no new
config surface was added (a `features.dump_request_prefix` field was prototyped
and reverted once `JCODE_TRACE` was found to already provide the knob). Off by
default because the payload contains repo context.

```
JCODE_TRACE=1 jcode run "anything"
grep -A2 'REQUEST PAYLOAD DUMP' ~/.jcode/logs/jcode-$(date +%F).log
```

**Verified live.** A real request produced a readable dump. The session-context
message rendered as:

```
<system-reminder>
# Session Context
Date: 2026-09-18
Time: 15:58:45          <-- volatile, third line
Timezone: -04:00
OS: linux
Architecture: x86_64
Jcode version: v0.85.0-dev (36e00ba20, dirty) (36e00ba20)
Hardware: ...
Working directory: /home/d/dev_env/jcode
Git:
  Branch: dev
  Modified: 3 files
     M crates/jcode-app-core/src/agent/prompting.rs
     ...
</system-reminder>
```

This confirms the reported defect directly: `Time:` is at position 3, ahead of
every stable field, so any two sessions diverge there.

### Finding: two additional volatile fields in the block

The live dump surfaced volatility the static source read had not:

1. **`Git:` is in the context block**, and it includes a `Modified: N files`
   count and the file list. That changes whenever the working tree changes, so
   two workers spawned at different tree states diverge at that line. It sits
   **after** the stable fields, so it is a second-order divergence rather than a
   prefix-killer, but it is more volatile than `Working directory:` alone.
2. **`Jcode version:` includes build dirtiness** (`dirty`), so a rebuilt binary
   changes that line. Relevant to this fix's assumption that the block is stable
   across sessions on one machine: it is stable only for a fixed binary.

Both should be considered when deciding the final field order. `Git:` in
particular is worth an explicit decision — it is useful context for a worker, but
it is per-invocation volatile.

## Test Coverage (per `02_TP_Change_Report.md`)

**V-2 (primary, deterministic).** Assert structural ordering: no datetime line
precedes a stable field. Cheap, no clock injection needed:

```rust
#[test]
fn session_context_puts_volatile_fields_last() {
    let ctx = build_session_context(None);
    let time_pos = ctx.find("Time: ").expect("Time line present");
    for stable in ["OS: ", "Architecture: ", "Jcode version: "] {
        let pos = ctx.find(stable).expect("stable field present");
        assert!(
            pos < time_pos,
            "volatile 'Time:' must not precede stable '{stable}'"
        );
    }
}
```

**V-1 (property, preferred).** Assert cross-session stability directly. Requires
either an injectable clock or two calls with a manipulated time; if
`build_session_context` is not made time-injectable, V-2 is the required proxy
and V-1 stays a manual check via the anchor's repro script.

**V-3 (regression, no new tests).** Existing tests must pass **unmodified**:
`prompt_tests.rs:291` (context contains `# Session Context`),
`prompt_tests.rs:333` (`dynamic_part` excludes it),
`session_tests/cases.rs:263,450` (context is the first message),
`memory_tests.rs:877`. Modifying any of these to accommodate the change is itself
a regression signal.

**V-4 (measurement).** Re-run `03_Cost_Evidence.md` §2 and §3 and record results.

## Residual Risk

**Low, and bounded.** The change alters the rendered order of fields in a
diagnostic block. It does not alter: the message's position, its
`display_role: System`, its `<system-reminder>` wrapper, its identificability via
`SESSION_CONTEXT_PREFIX`, its per-session immutability, or the refresh path.

Specific residual concerns:

1. **Any consumer parsing the block positionally.** `SESSION_CONTEXT_PREFIX`
   matches on a prefix string, and `has_session_context_message` /
   `refresh_initial_session_context_message` use `starts_with`, so they are
   unaffected. A positional parser of the datetime fields would break; none was
   found in the survey, but the survey was of tests and call sites, not of every
   possible consumer.
2. **`Working directory:` remains a differentiator.** Workers in sibling clones
   or worktrees still diverge at that line. This fix moves the divergence point
   *later* but does not eliminate it for those cases. Recorded as a follow-up in
   the anchor.
3. **`Date:` still diverges daily.** Sessions started on different days share the
   block only up to `Date:`. Acceptable; cross-day swarms are rare, and this is
   strictly better than the current second-resolution divergence.
4. **Human-facing output order changes.** `Date`/`Time`/`Timezone` move from
   near the top of the context block to the bottom. Cosmetic; no test asserts the
   reverse.

## Expected Effect

The measured claim to be tested after implementation:

- Common prefix across sibling workers rises from **60 characters** to the full
  stable block (the `# Session Context` heading through `Working directory:` /
  git info), which is the great majority of the block.
- Worker cache hit rate on `V4-Flash-0731` (currently **90.9%**) rises. How far
  determines whether the worker tier approaches the **97.58%** break-even
  computed in `03_Cost_Evidence.md` §4.
- The coordinator's rate (95.7%) should improve little, since it was already
  near saturation; the gain is concentrated in the worker column, which is where
  the defect's cost lives.

## Not In Scope

- The `model_cost_replay` `mix` accounting defect (`03_Cost_Evidence.md` §5) —
  separate follow-up, separate repository.
- Any change to `swarm_model` / `default_model` configuration. This SPR fixes the
  measurement precondition; the tier decision should be revisited only after
  re-measuring.
- Reducing the hardware block or trimming the snapshot's content. Out of scope;
  the fix is ordering only.
