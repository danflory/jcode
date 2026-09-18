---
# jcode-local frontmatter (SPR folder conversion, 2026-09-17).
# jcode is NOT governed by Overwatch's UDRS: no UDRS/ci_impacted/parent numeric
# ids are fabricated here. Only real, repo-verifiable values are used.
id: SPR-0009-P08
title: Comparison of 06 (MCP Server Build Steps) and 07 (MCP Delivery Plan)
status: DRAFT
author: operator
created: 2026-09-18
domain: ENGINEERING
severity: Major
type: PLAN.COMPARE
version: "2026-09-18"
---

# SPR-0009-P08: Comparison — 06 vs 07

This document compares the two parallel deliverables in this folder:

- **`06_MCP_Server_OW_tools_Steps.md`** — the empirical build/verification document
  (produced in a separate working session, "snail").
- **`07_MCP_Delivery_Plan.md`** — the strategic delivery plan (produced in the
  main working session, "blowfish").

They were produced independently and are complementary. This document records the
convergences, the divergences, the strengths of each, and what each resolves in the
other.

## 1. Nature of each document

| | 06 (snail) | 07 (blowfish) |
|:--|:-----------|:--------------|
| Kind | Build steps + verification record | Delivery plan / governance |
| Method | Read OW_tools source, ran commands, built a working server, measured numbers | Read the 2-series workflows, reasoned about costs, boundary, lifecycle |
| Proof | **Working implementation** verified end-to-end via jcode's client | No implementation; proposals and milestones |
| Scope | OW_tools entry-point → MCP tool surface (Option D instantiation) | Full hybrid (Option A surface + Option D execution) for the 2-series |

## 2. Where the two documents agree (independent convergence)

Neither read the other, yet both reached these conclusions:

1. **Option D (MCP) is the deterministic execution layer; Option A is required for
   the literal slash-command problem.** 06 states this explicitly in its ambiguity
   flag (§7); 07 makes it the core of the hybrid design (§4).
2. **Fine-grained, per-step tools.** 06's working implementation maps createSPR2
   steps 1:1 to 11 tools (`ow_resolve_parent`, `ow_scaffold_spr`,
   `ow_backpatch_parent`, ...); 07's default was "fine per command, grouped by phase"
   (§9).
3. **Hash-pinned generated pointers keep a single source of truth.** 06 builds
   `OW_TOOLS_SHA256` into the server and refuses on mismatch (§3 Step 7); 07
   specifies the same guard for the generated config (§4).
4. **Eager-vs-deferred exposure is a token-economics decision.** 07's
   "index-then-load" (§4.2) is confirmed empirically by 06's measured threshold
   swap (eager < 8,000 tokens; deferred surface via `mcp_search`/`mcp_call`).

## 3. What 06 resolves that 07 left open

07's "Open questions" (§9) and risks are answered by 06 with evidence:

- **Tool granularity (open in 07)** → 06 built and proved 11 per-step tools for
  createSPR2. Fine-grained per-step works.
- **Eager-exposure economics (open in 07)** → 06 measured ~168 tokens/tool,
  11 tools = 1,844 tokens total, comfortably under the 8,000 threshold;
  recommends 5-7 eager + ~50 deferred for the full fan-out.
- **Schema fidelity (risk in 07)** → 06 resolved the exact concern 07 raised:
  the model *can* read OW_tools source and verify signatures (it did), and a
  working stdlib server was consumed by jcode's client with no SDK issue.
- **M4 smoke test (future work in 07)** → 06 already ran it: `jcode run` with a
  socket fired `[mcp__ow_createspr__ow_db_probe]` with exit 0, plus raw JSON-RPC
  probes and behavioral confirmation of the threshold swap.

## 4. What 07 contributes that 06 lacks

1. **The deterministic-vs-judgment boundary.** 06 maps the *tool surface* but does
   not classify which steps must remain on the session model. 07 identifies the
   irreducible inference cluster (TP-gap V-1..V-6, change_class/severity/domain,
   check-6 semantic reconciliation, the fix itself, deferral/D31/lesson judgment)
   and the ~25-28 deterministic commands that convert.
2. **The traceability contract.** Judgment stays on the session model (visible in
   the transcript); tools return structured, reasoned JSON. 06's server design
   does not address where inference must live.
3. **The delivery lifecycle.** 07 gives the build a left-shifted structure
   (DAR → RFC → do → check/close) and milestones M1-M4. 06 is numbered steps with
   no review gate structure.
4. **The full 2-series scope.** 06 implements createSPR2 only (11 tools) and flags
   the rest as future. 07 governs conversion of create/do/check/close.

## 5. Where snail's work lives (scope of the artifact)

Snail's work is **not** confined to the jcode directory. It spans three locations:

1. **jcode repo (committed, 5 commits: `a9f735d5d` → `4ae34b32b`):**
   - `docs/SPR/SPR-0009-workflows-not-invocable-as-slash-commands/06_MCP_Server_OW_tools_Steps.md`
   - `temp/mcp/ow_createspr/` — `server.py`, `smoke_test.py`, `README.md`, `mcp.snippet.json`
2. **Outside the repo — `~/.jcode/mcp.json` (global registration):**
   - Registers `ow_createspr` with `shared: true`, `timeout_secs: 120`,
     `OW_REPO_ROOT=/home/d/dev_env/clones/Overwatch`.
3. **The Overwatch world:**
   - `OW_REPO_ROOT` points at `/home/d/dev_env/clones/Overwatch`.
   - The acceptance probe reported `"governed_db_reachable": true`, i.e. the
     server reached the Overwatch governed firecontrol DB.

Note an inconsistency between 06's proposal and its live config:
- 06 §4 proposes project-local `.jcode/mcp.json` with `shared: false`
  (stateful, per-session).
- 06 §8's working registration is **global** (`~/.jcode/mcp.json`) with
  `shared: true`.

## 6. Summary of relative strengths

| Dimension | 06 (snail) | 07 (blowfish) |
|:----------|:-----------|:--------------|
| Empirical proof | ✅ built + verified | ❌ proposal only |
| Measured numbers | ✅ tokens, threshold, names | ❌ none |
| Deterministic-vs-judgment | ❌ not classified | ✅ full boundary |
| Traceability contract | ❌ not addressed | ✅ explicit |
| Delivery lifecycle / governance | ❌ numbered steps | ✅ DAR/RFC/do/check + milestones |
| Coverage | ✅ createSPR2 only | ✅ full 2-series |
| Registration/scope analysis | ⚠️ inconsistent (global vs proposal) | ✅ global-vs-project scoping documented |

## 7. Reconciliation: what to do next

1. **07 should adopt 06's evidence**: mark M4 (smoke test) done for createSPR2,
   cite the 1,844-token / ~168-per-tool measurements, and record 06's UNVERIFIED
   items (1-5) as the real build risks for the remaining workflows.
2. **06 should adopt 07's boundary**: before generating the remaining tools, apply
   the deterministic-vs-judgment table so judgment steps stay on the session model.
3. **Resolve the registration inconsistency**: decide global+shared vs
   project-local+non-shared before generalizing beyond createSPR2; 07's scope
   analysis (§3) is the reference for that decision.
4. **Sequence the rest**: 07's lifecycle (DAR catalog → RFC contract → do → check)
   is the governance wrapper around 06's proven per-step tool pattern.

## 8. Verification list

- **C-1** — The two documents' convergences are recorded with section references.
- **C-2** — Every 07 open question resolved by 06 is marked with its 06 evidence.
- **C-3** — The deterministic-vs-judgment boundary in 07 is identified as the
  missing piece in 06.
- **C-4** — The registration inconsistency (global+shared vs project-local+non-shared)
  is recorded with both sides cited.
- **C-5** — The artifact locations (jcode repo, `~/.jcode/mcp.json`, Overwatch)
  are documented accurately.

**END.** This document is a comparison only; it changes no code.
