# SPR-0001: /clear leaves stale cost and token accounting in the info widget

**File:** `crates/jcode-tui/src/tui/app/commands_review.rs`
**Commit:** `4620e42bc` (2026-09-14) — `fix(tui): zero cost and token accounting on /clear`
**Status:** Fixed, unpushed

## What

After `/clear`, the info widget kept showing the discarded session's spend:
`cost.total_cost`, `token_accounting.total_*`, and the history-restored
totals survived the clear, alongside the pre-clear counter snapshot
(observed: 23M tokens in / 211k out and its dollar value, from a 400k-context
session, still visible after the context was wiped).

The fix extends `clear_live_usage_state` — the shared hook both `/clear`
paths (remote `key_handling.rs` and local `reset_current_session`) already
funnel through — to also zero the accumulated cost and token accounting, so
the new session starts at $0 and 0 tokens. A regression test covers both the
shared hook and the `reset_current_session` caller.

## Why

The root cause was an asymmetry: the server side treated `/clear` as a brand
new session (new id, empty context), but the client-side full-discard hook
only reset the live **streaming** counters. Anything accumulated across
completed turns (total cost, total tokens) was treated as persistent session
state and untouched. That is inconsistent with the semantics a user expects
from `/clear` — wiping the conversation means wiping the accounting tied to
that conversation — and it makes the spend display actively misleading: the
widget reports dollars for a conversation that no longer exists in context.
