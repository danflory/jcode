# SPR-0002: Unresolved-model pricing fallback bills every unknown model at $15/$60

**File:** `crates/jcode-tui/src/tui/app/misc_ui.rs`
**Commit:** `e390d8d45` (2026-09-12) — `fix(cost): make unresolved-model pricing fallback model-aware`
**Status:** Fixed, unpushed

## What

The session cost widget billed any model the unified resolver could not
price at a hardcoded **$15/1M input and $60/1M output** via
`get_or_insert(15.0)` / `get_or_insert(60.0)`. The resolver misses in normal,
harmless situations: empty or stale models.dev cache, an unknown
openai-compatible model label (e.g. a private profile id), or the first run
before the background price refresh completes.

Worse, `get_or_insert` **latches** the default into the cache. One early miss
shadowed the correct per-model price for the rest of the session, even after
the catalog resolved properly. Observed effect: DeepSeek Flash
(~$0.06/$0.18 real rates) displayed roughly **$14**.

The fix replaces the fixed defaults with a model-aware fallback that keys off
the model family (DeepSeek/GPT/Claude/Qwen/GLM/Gemini/Llama/Mistral), and
stops writing the fallback into the cache, so a later successful catalog
resolution can still take effect. Both billing paths — local
(`update_cost_impl`) and remote (`resolve_remote_cost_pricing`) — now go
through `effective_resolved_pricing`, which reuses cached prices when present
and otherwise estimates from the model id.

## Why

Two defects compounded into one misleading number:

1. **Wrong default semantics.** A hardcoded $15/$60 is a *frontier-tier*
   placeholder. Applying it to a cheap model skews the estimate by ~250x, and
   the operator's spend display is exactly the surface they use to decide
   whether to keep going on a model.
2. **Cache poisoning.** Latching the guessed price means a transient miss
   (startup race, stale cache) became permanent for the session. A fallback
   should be a fallback — recomputed every time until a real price arrives,
   never promoted into the authoritative cache.
