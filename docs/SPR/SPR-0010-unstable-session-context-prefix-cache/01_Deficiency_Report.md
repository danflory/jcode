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
type: SPR.DEFICIENCY
version: "2026-09-18"
---

# SPR-0010: Unstable Session Context Prefix — Deficiency Report

## Root Design Failure

jcode builds a session-context block and deliberately places it **first among
provider-visible transcript items**, which is the correct position for prefix
caching. It then orders that block's fields so that a **second-resolution
timestamp appears third**, ahead of every stable field. The design intent
(prefix stability, expressed in the doc comment "Persist an immutable
session-context snapshot as the first provider-visible transcript item") and the
field ordering (volatile field first) are in direct opposition.

This is the **"volatile field ordered ahead of stable fields inside a
prefix-stability block"** class of defect: the container is designed for cache
reuse, but the ordering guarantees the reuse never happens. Nothing in the
design encodes the invariant that the block must be *identical across sessions*;
it only encodes that it must be *immutable within a session*. Those are
different properties, and the swarm use case depends on the first.

Deficiency break count: **1** — a single, well-localized ordering defect with
measurable cost consequences, recorded in the anchor as the 60-character common
prefix.

## What the Original Design Got Wrong (1 deficiency)

**Fields are ordered by human readability, not by cache stability.** In
`crates/jcode-base/src/prompt.rs:699`, `build_session_context` pushes
`session_datetime_lines()` third:

```rust
let mut lines = vec!["# Session Context".to_string()];
lines.extend(session_datetime_lines());   // Date, Time, Timezone
lines.push(format!("OS: {}", ...));
lines.push(format!("Architecture: {}", ...));
lines.push(format!("Jcode version: {} ({})", ...));
```

and `session_datetime_lines` (line 726) includes
`format!("Time: {}", now.format("%H:%M:%S"))`, which changes every second.

Read as a document, this ordering is natural: a context header that states when
it was captured. Read as a cacheable request prefix, it is inverted: the one
field guaranteed to differ between any two sessions is placed ahead of every
field guaranteed to be identical.

The consequence is measurable and was measured: across 13 worker sessions in the
project sandbox VM, grouped by model, the longest common prefix is **60
characters** in all three groups, terminating mid-`Time:` line.

**Why the existing immutability design did not prevent this.** The snapshot is
per-session immutable, and `refresh_initial_session_context_message`
(`crates/jcode-base/src/session.rs:944`) only rewrites it before a real
conversation starts. Both properties are correct and were preserved. Neither
addresses cross-session stability, which is the property prefix caching
actually requires. The two properties were conflated in the original design.

## Impact Assessment

**Measured evidence (2026-09-18, project sandbox VM).**

- **Common prefix across workers: 60 chars.** Computed per model group across 13
  child sessions: 3x `DeepSeek-V4.1-Flash`, 8x `DeepSeek-V4-Flash-0731`,
  2x `DeepSeek-V4-Flash`. All three groups truncate at the same place.
- **Only the reminder wrapper and heading are shared.** `<system-reminder>\n# Session
  Context\nDate: <same day>\nTime: 0` — the remainder of the block (OS,
  Architecture, Jcode version, hardware, working directory) is priced as fresh
  input on every worker's first request.
- **Rate differential at stake.** Cached vs uncached input per 1M tokens on the
  models in use: `DeepSeek-V4-Flash-0731` $0.015 vs $0.06 (4.0x);
  `DeepSeek-V4.1-Flash` $0.006 vs $0.20 (33.3x). The `V4.1-Flash` ratio is
  extreme, so the loss on that model is correspondingly larger.
- **Role-split hit rates measured** (see `03_Cost_Evidence.md` for method):
  root/coordinator on `V4.1-Flash` 95.7% (664 turns), workers on
  `V4-Flash-0731` 90.9% (151 turns). The worker figure is the one this defect
  suppresses; the theoretical ceiling under a stable prefix is materially
  higher.

**Impact of the defect class.**

- **Fan-out cost scales with the defect.** Every additional worker re-pays the
  uncached rate on identical leading context. Wide swarms, which are the
  recommended pattern for aggressive parallel work, are penalized most.
- **Model-tier decisions are distorted.** Because the cached/uncached ratio
  differs sharply by tier, a suppressed worker hit rate biases the tier choice.
  A break-even analysis performed on the corrupted assumption is recorded in
  `03_Cost_Evidence.md` as a cautionary example: the initial figure of a 94.5%
  break-even was computed against a mis-derived mix and was wrong.
- **Silent.** Nothing surfaces the lost reuse. `kv_cache_miss_notices` reports
  per-turn misses but the cause is structural, present on the very first request
  of every session, so it reads as baseline rather than as a defect.
- **Not user-visible as a bug.** No functional behavior breaks; only cost. This
  is why it survived to the current build.

## Corrective Design

Make the stable block contiguous, with any volatile field last:

1. Emit `# Session Context` first.
2. Emit all stable fields in a fixed order: `OS`, `Architecture`,
   `Jcode version`, hardware, `Working directory`, git info.
3. Emit datetime fields **last**. Optionally drop `Time:` from the
   provider-visible snapshot entirely, since the accompanying message already
   carries `display_role: System` and the display path does not require the
   provider-visible copy to contain it.

Guiding rule: **inside a prefix-stability block, no volatile field may precede a
stable field.**

### Open design question: `Working directory`

`Working directory:` is stable across workers that share a directory and
unstable across workers in sibling clones or worktrees. `docs/SWARM_TASK_GRAPH.md`
§5 establishes "the repo + git are the shared medium", and the coordinator
pattern assumes workers generally share a checkout. The field should remain, but
if sibling-clone swarms become common it becomes a second-order version of this
same defect. Recorded as a follow-up rather than folded into this fix.

## Convergence Pattern Check

Not applicable: this requirement involves no iteration, retry, or batch logic.
The fix is a pure reordering of string construction in a single function, with a
direct unit-test check on the resulting property.

## Evidence Method Note

The measurements in this report come from direct inspection of
`~/.jcode/sessions/*.json` (`messages[0].content[].text`) inside the project
sandbox VM, plus the `OW_tools/model_cost_replay` tool at
`~/dev_env/clones/Overwatch/` for the rate-card arithmetic. Token counts live
under `messages[].token_usage` (not `usage`), with fields
`cache_read_input_tokens`, `input_tokens`, `output_tokens`. Reproduce with the
scripts recorded in `03_Cost_Evidence.md`.
