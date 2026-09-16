# SPR-0003: Service tier visibility for DeepInfra (and any OpenAI-compat gateway)

**Files:** `crates/jcode-provider-openrouter-runtime/src/{openrouter_provider_impl.rs,openrouter_sse_stream.rs}`, `crates/jcode-provider-openrouter/src/stream.rs`, `crates/jcode-message-types/src/lib.rs`, `crates/jcode-provider-core/src/attempt_tracker.rs`, `crates/jcode-app-core/src/agent/{agent.rs,agent/status.rs,agent/turn_loops.rs,agent/turn_streaming_mpsc.rs}`, `crates/jcode-protocol/src/wire.rs`, `crates/jcode-tui/src/tui/{app.rs,app/tui_lifecycle.rs,app/tui_state.rs,app/turn.rs,info_widget.rs,info_widget_model.rs}`
**Commit:** `ad2c923f5` (2026-09-16) — `feat(deepinfra): visible service tier - exact request logging plus response tier echo`
**Status:** Local, push-blocked (personal no-push clone, pre-push hook + poisoned push URL)
**Installed:** `jcode v0.85.1-dev (ad2c923f5, dirty)` via `scripts/install_release.sh --fast`

## Research: what DeepInfra actually documents

Read from https://docs.deepinfra.com/chat/overview (fetched 2026-09-15 ~00:30Z):

- Endpoint: `https://api.deepinfra.com/v1/openai/chat/completions`, OpenAI-compatible.
- `service_tier` selects a **non-standard** tier. Exactly two requestable values on
  **tagged** models:
  - `"priority"` — front-of-queue, ~50% surcharge (1.5x standard price).
  - `"flex"` — best-effort, ~20% discount (0.8x price); may queue up to 10 minutes
    before running or being rejected with HTTP 429 (`engine_overloaded`).
- **Omitting the field = standard** real-time scheduling at 1x price.
  "standard" is not documented as a requestable value.
- Only relevant on models tagged for tiers. On untagged models the request is
  served at standard and billed at standard, with **no error** — a silent downgrade.
- The **response** carries a `service_tier` field confirming the tier actually
  served. This echo is the ground truth for billing, not the request intent.
- Interaction: `fail_fast: true` beats `service_tier: "priority"` (explicit no-wait wins).

## Problem

Before this SPR the deepinfra path (openrouter-runtime) either sent **no** tier
field at all, or (after a first commit in this series) sent any configured value
that was not `""`/`off`/`standard`/`auto` verbatim — including values DeepInfra
would not recognize. There was zero visibility of what went into the request
body and nothing on the surface showed what tier the gateway actually served.
Billing evidence had to come from the provider console after the fact.

## What changed

### Request side (send exactly what DeepInfra documents)

- Tier filter reworked to a `match` on the configured
  `[provider] openai_service_tier`:
  - `"flex"` / `"priority"` → set `request["service_tier"]`, log exact value.
  - `""` / `"off"` / `"standard"` / `"auto"` / `"none"` → omit the field (= standard).
  - anything else → send verbatim with a **warning** log (gateway decides validity).
- Per-request log line just before send:
  `REQUEST SERVICE_TIER: "priority" (model: …, endpoint: …)` —
  `omitted (standard)` when the field is absent. Grep target:
  `grep "REQUEST SERVICE_TIER" ~/.jcode/logs/jcode-YYYY-MM-DD.log`.

### Response side (ground truth from the echo)

- SSE parser (`jcode-provider-openrouter/src/stream.rs`) reads
  `parsed["service_tier"]` on every chunk and emits a new
  `StreamEvent::ServiceTier { tier }` (deduped naturally by consumers
  overwriting state).
- New variant threaded through all exhaustive match sites:
  - `attempt_tracker.rs`: classified overwrite-style (not replay-visible), so a
    mid-stream retry does not duplicate a stale tier reading.
  - blocking turn loop (`turn_loops.rs`): stores into agent state
    `last_service_tier` + `[trace] service_tier=…` eprint in trace mode.
  - streaming loop (`turn_streaming_mpsc.rs`): stores state and forwards
    `ServerEvent::ServiceTier` over the wire (serde `service_tier`).
- TUI: new streaming field `served_service_tier` (deliberately **distinct** from
  the pre-existing `remote_service_tier`, which is the *requested/configured*
  tier) fed into `InfoWidgetData.served_service_tier`.

### UI rendering

- Model info lines get a `Tier: <tier>` row, colored: priority = warm
  (premium), anything non-standard = green (discount). Hidden entirely when the
  served tier is standard (or absent) so plain sessions stay uncluttered.

## Why requested-vs-served matters

DeepInfra silently serves standard when a model is untagged or unsupported:
the requested tier can diverge from the billed tier. Showing both separately
(the TUI already showed the configured tier via fast-mode) makes that divergence
visible in real time.

## Verification

- `cargo check --workspace` clean.
- `cargo test -p jcode-provider-openrouter-runtime --lib`: 134 passed.
- `cargo test -p jcode-provider-openrouter -p jcode-message-types`: 37 passed.
- Full workspace `cargo test` unchanged versus the pre-existing baseline
  (258 lib + 6; the 8 lib failures and 21 workspace-crate failures are identical
  on clean `origin/master` 74e7a4be5 — documented in the v0.85.0 verification).
- Live-build verification: installed and reloaded onto `ad2c923f5`.
- Not yet exercised against live deepinfra traffic (needs a tier-tagged model
  request; recommend checking `REQUEST SERVICE_TIER` grep plus one flex call).

## Configuration

`~/.jcode/config.toml`:

```toml
[provider]
openai_service_tier = "priority"   # or "flex"; omit/empty/standard/no field = standard
```

Or `/fast on` / `/fast off` in the TUI (existing path, writes the same key).

## Caveats

- OpenRouter as a routing layer does not guarantee tier passthrough to its own
  upstreams in all cases; the echo field is authoritative for whatever path
  actually served the request.
- `jcode-provider-openai-runtime` (native OpenAI path) already had its own
  service_tier plumbing and Responses-API canonical fingerprint logging
  including `service_tier=`; this SPR closes the equivalent gap on the
  OpenAI-compat/deepinfra path. Its request-side fingerprint remains
  RESPONSES-specific; a chat-completions canonical fingerprint for the compat
  path is a possible follow-up.
- "standard" is deliberately mapped to omission because DeepInfra only documents
  the two non-standard values; if DeepInfra later documents a requestable
  "standard", the filter needs the value added back.
