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
  (written by worker `buffalo` under coordinator `ram`, then corrected by the
  coordinator over five follow-up commits: citation qualification, an exit-code
  mis-citation, executable §5, measured token numbers, and the registration-contract
  proof).
- **`07_MCP_Delivery_Plan.md`** — the strategic delivery plan (produced in a separate
  working session, `blowfish`, and committed separately).

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
3. **Gates are returned as data, not blocked on.** Neither document relies on an
   interactive prompt: 06's server returns `gate` objects because jcode has no
   elicitation channel, and 07 keeps STOP points as explicit steps the session model
   reports before continuing (§4).

## 2a. Where the two documents actually diverge

Two claims that look like convergence are not, and should not be reconciled by
weakening either document:

1. **Hash-pinned pointers.** 06 §3 Step 7 *proposes* an `OW_TOOLS_SHA256` guard that
   makes the server refuse on drift, and doc 05 carries the same governance idea. It is
   **not implemented**: the working server contains no hashing
   (`grep -c SHA256 temp/mcp/ow_createspr/server.py` → 0). 07 does not specify hash
   pinning at all; its drift mitigation is "generated index + single-source contract,
   tool layer canonical for args" (§8). So this is a proposal in 06 and a different
   (weaker) mitigation in 07, not a shared design. Whoever builds the generated server
   must decide which one wins.
2. **Exposure strategy.** 07 §4.2 designs index-then-load (Tier 1 index + Tier 2 lookup
   tool). 06's measurements point the other way for this catalog: ~168 tokens per tool,
   so ~24 tools for the whole 2-series is ~4,000 tokens, under the 8,000-token
   threshold where jcode defers to `mcp_search`/`mcp_call`. Eager exposure is therefore
   viable and cheaper in round-trips, and index-then-load is an optimization to hold in
   reserve above roughly 45 tools rather than a default. 06's threshold swap confirms
   the deferral *mechanism* exists; it does not confirm that indexing is the right
   choice at this size.

## 3. What 06 resolves that 07 left open

07's "Open questions" (§9) and risks are answered by 06 with evidence:

- **Tool granularity (open in 07)** → 06 built and proved 11 per-step tools for
  createSPR2. Fine-grained per-step works.
- **Eager-exposure economics (open in 07)** → 06 measured ~168 tokens/tool,
  11 tools = 1,844 tokens total, comfortably under the 8,000 threshold. The measured
  conclusion for this catalog is stronger than 06's original suggestion: ~24 tools for
  the whole 2-series is ~4,000 tokens, so the entire surface can be eager and
  index-then-load is not needed below roughly 45 tools.
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
   and the ~19-24 deterministic commands that convert (measured counts: 12 `python3`
   lines in create, 4 in do, 0 in check, 8 in close).
2. **The traceability contract.** Judgment stays on the session model (visible in
   the transcript); tools return structured, reasoned JSON. 06's server design
   does not address where inference must live.
3. **The delivery lifecycle.** 07 gives the build a left-shifted structure
   (DAR → RFC → do → check/close) and milestones M1-M4. 06 is numbered steps with
   no review gate structure.
4. **The full 2-series scope.** 06 implements createSPR2 only (11 tools) and flags
   the rest as future. 07 governs conversion of create/do/check/close.

## 5. Where the 06 artifact lives (scope of the artifact)

The 06 work is **not** confined to the jcode directory. It spans three locations:

1. **jcode repo (committed).** 06 was touched by 8 commits
   (`55b937013` → `4ae34b32b`), and the server itself by 4 more
   (`3ef35ae62` → `a6bd18831`):
   - `docs/SPR/SPR-0009-workflows-not-invocable-as-slash-commands/06_MCP_Server_OW_tools_Steps.md`
   - `temp/mcp/ow_createspr/` — `server.py`, `smoke_test.py`, `README.md`, `mcp.snippet.json`
2. **Outside the repo — `~/.jcode/mcp.json` (global registration):**
   - Registers `ow_createspr` with `shared: true`, `timeout_secs: 120`,
     `OW_REPO_ROOT=/home/d/dev_env/clones/Overwatch`.
3. **The Overwatch world:**
   - `OW_REPO_ROOT` points at `/home/d/dev_env/clones/Overwatch`.
   - The acceptance probe reported `"governed_db_reachable": true`, i.e. the
     server reached the Overwatch governed firecontrol DB
     (`DB_NAME = "firecontrol"`, `OW_tools/db_write_commands/_connections/_dsn.py:38`).

**Registration scope is a resolved question, not an inconsistency.** 06 §4's
`shared: false` is conditional: it applies to a server that holds per-session state.
The server actually built is stateless — every call shells out with an explicit
`OW_REPO_ROOT` and cwd — so a global registration with `shared: true` is the correct
reading, and the README records that reasoning. 07 §3's global-vs-project analysis is
what makes the distinction explicit; the two documents do not conflict here.

## 6. Summary of relative strengths

| Dimension | 06 (buffalo + coordinator review) | 07 (blowfish) |
|:----------|:-----------|:--------------|
| Empirical proof | ✅ built + verified | ❌ proposal only |
| Measured numbers | ✅ tokens, threshold, names | ❌ none |
| Deterministic-vs-judgment | ❌ not classified | ✅ full boundary |
| Traceability contract | ❌ not addressed | ✅ explicit |
| Delivery lifecycle / governance | ❌ numbered steps | ✅ DAR/RFC/do/check + milestones |
| Coverage | ✅ createSPR2 only | ✅ full 2-series |
| Registration/scope analysis | ✅ resolved (stateless server → global + `shared: true`) | ✅ global-vs-project scoping documented |
| Drift protection | ⚠️ proposed only (`OW_TOOLS_SHA256`, not implemented) | ⚠️ specified but weaker (generated index, no hash) |

## 7. Reconciliation: what to do next

1. **07 should adopt 06's evidence**: mark M4 (smoke test) done for createSPR2,
   cite the 1,844-token / ~168-per-tool measurements, and record 06's UNVERIFIED
   items (1-5) as the real build risks for the remaining workflows.
2. **06 should adopt 07's boundary**: before generating the remaining tools, apply
   the deterministic-vs-judgment table so judgment steps stay on the session model.
3. **Pick one drift mechanism.** 06 proposes hash pinning and never built it; 07
   proposes a generated index with no hash. Decide before generating, because a
   generated server that silently tracks a changed `OW_tools` is the governance risk
   both documents were trying to close.
4. **Sequence the rest**: 07's lifecycle (DAR catalog → RFC contract → do → check)
   is the governance wrapper around 06's proven per-step tool pattern.
5. **Derive schemas, don't guess them** (07 §6 RFC, corrected): every field should
   trace to a `--help` line or a real signature before generation, and every mutating
   tool should pass a dry-run sandbox pass before the live `createSPR` run.

## 8. Verification list

- **C-1** — The two documents' convergences are recorded with section references.
- **C-2** — Every 07 open question resolved by 06 is marked with its 06 evidence.
- **C-3** — The deterministic-vs-judgment boundary in 07 is identified as the
  missing piece in 06.
- **C-4** — The real divergences (hash pinning, exposure strategy) are recorded as
  divergences, and the registration scope is recorded as resolved with its reasoning.
- **C-5** — The artifact locations (jcode repo, `~/.jcode/mcp.json`, Overwatch)
  are documented accurately.
- **C-6** — Attribution and commit counts are verified against git history and the
  session records (06: worker `buffalo` + coordinator corrections, 8 commits; server:
  4 commits).
- **C-7** — Every measured number in this comparison (command counts, token costs,
  tool counts) is reproducible by the command quoted beside it.

**END.** This document is a comparison only; it changes no code.
