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
> **Implementation status.** At the time of writing, the SPR folder and this
> report are committed, and the code fix is **not yet applied**.
> `build_session_context` in `crates/jcode-base/src/prompt.rs` still emits
> `session_datetime_lines()` third. This document specifies the fix precisely so
> it can be implemented and reviewed against a written contract.

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
