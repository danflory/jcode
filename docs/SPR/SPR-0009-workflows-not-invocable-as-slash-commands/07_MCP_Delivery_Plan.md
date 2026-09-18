---
# jcode-local frontmatter (SPR folder conversion, 2026-09-17).
# jcode is NOT governed by Overwatch's UDRS: no UDRS/ci_impacted/parent numeric
# ids are fabricated here. Only real, repo-verifiable values are used.
id: SPR-0009-P07
title: MCP delivery plan - a hybrid workflow-execution pipeline grounded in the SPR-0009 analysis
status: DRAFT
author: operator
created: 2026-09-18
domain: ENGINEERING
severity: Major
type: PLAN
version: "2026-09-18"
---

# SPR-0009-P07: MCP Delivery Plan

## 1. Purpose

This document is a **delivery plan** (not a survey) for bringing MCP-based workflow
execution to jcode, scoped to the SPR-0009 problem: Overwatch/Gemini workflows such
as the `.agents/workflows/*.md` 2-series cannot be invoked as typed slash commands.
It records the design decisions reached in the accompanying working session, the
deterministic-vs-judgment boundary, the target tool surface, and a left-shifted
delivery pipeline. It is grounded in the conversation that produced it; code references
were read from the real repo during analysis.

## 2. Context: why this exists

The driving problem is **speed and determinism**. The current mechanism is markdown
instruction files that embed command strings (`python3 OW_tools/...`) and are
re-parsed by the model on every run. Two distinct costs are conflated when the user
reports that the workflows are slow:

1. **Re-parsing prose** — the model re-reads the whole workflow, extracts fields, and
   reconstructs the exact shell invocation each time. Token-expensive and error-prone.
2. **Deciding under uncertainty** — `change_class`, `severity`, `domain`, TP-gap
   classification are *judgment* tasks, irreducible to a lookup.

A typed schema eliminates cost (1) almost completely. It does **not** eliminate cost
(2); it relocates it. Therefore the plan explicitly keeps the judgment on the session
model (traceable in the transcript) and moves the deterministic 80% into typed tools.

## 3. Scope of MCP in jcode (verified from code)

Analysis findings that constrain the design:

- **MCP is an external child process**, not an in-process subsystem. jcode is the MCP
  *client*; servers are separately spawned executables speaking the protocol over stdio.
- **Two config scopes**: global (`~/.jcode/mcp.json`, plus Claude sources) and
  project-local (`.jcode/mcp.json`, `.mcp.json`, `.claude/mcp.json`), resolved against
  the **session working directory**, not the daemon cwd (issue #420).
- **Two process scopes**: `shared` servers pool daemon-global; non-shared servers are
  spawned **per-session with the session cwd** as the child process cwd
  (`connect_in_dir`, `client.rs:180-181`).
- **Tools-only primitive**: MCP in jcode supports only `tools/list` and `tools/call`
  (`protocol.rs:142,148,155`). No `prompts` or `resources` support (verified: 0 matches).
- **No credentials leak by default**: the child inherits only explicitly-declared
  `env` (issue #771), so providers must be opted in per-server.
- **jcode has no slash-command registry**; MCP itself provides no user-typed `/name`
  surface. Option D (MCP-as-tool) thus **removes** the slash unless a command surface
  (Option A) is built on top.

## 4. Design decision: the hybrid

The selected approach is a **hybrid** that reconciles Option A and Option D:

- **Option A (custom command surface / slash commands)** is retained as the
  user-facing layer and the home of continuously-improved instruction text.
- **Option D (MCP tools)** is used as the **deterministic execution layer**: one typed
  tool per deterministic command, with real parameters, real execution, real result.
- **Traceability contract**: judgment stays on the **session model** (visible in the
  transcript — the more traceable location). MCP tools are lazy plumbing that shuttle
  context and return structured, *reasoned* JSON. Self-inferring tools (a model hidden
  inside the server) are deliberately excluded from the judgment steps because they are
  the least traceable and collide with the "evidence-in-transcript" persona contract.

### 4.1 Schema principle: thin-on-required, fat-on-computed

To minimize what the model must "come up with" (the real slowness), tool schemas follow
the philosophy already used by `checkSPR2` (auto-derive instead of numeric entry):

- **Required fields**: only what genuinely must be decided by the caller, e.g.
  `title`, `parent_id`.
- **Server-computed defaults**: everything derivable — next SPR number, `change_class`
  from `ci_impacted`, `severity` default 3, `domain` via a sensible default/enum.
- **Judgment fields are optional overrides**, not required inputs. The tool computes a
  value with a reasoned `evidence` note and the caller may override.

Requiring too many fields up front is counterproductive: forcing the model to commit to
judgment values before it has evidence produces wrong guesses and retry round-trips.

### 4.2 Discovery: index-then-load

Tell the model about many tools efficiently without bloating the prompt:

- **Tier 1 (always-on, tiny)**: a generated one-line index —
  `name — purpose [category]` per command, matching the skill frontmatter contract
  (`name` + `description`).
- **Tier 2 (lazy)**: one cheap lookup tool (`lookup_command(name)`) returning the full
  spec/args/examples for the single command the model commits to. Mirrors jcode's
  `mcp_search`/`mcp_call` deferred mode and `/skills` one-at-a-time loading.

## 5. Deterministic-vs-judgment boundary

The 2-series (`createSPR2`, `doSPR2`, `checkSPR2`, `closeSPR2`) contains roughly
**25-28 distinct deterministic executable operations**, concentrated in `create` (~10)
and `close` (~9 new); `do` adds ~6 (much of it unavoidable fix judgment); `check`
has ~0 scripted commands (it is a read-and-verify gate).

### 5.1 Deterministic (convert to typed MCP tools)

- `update_author.py` (author provenance)
- `query_ci_by_path`, `query_test_execs`, `query_closure_readiness`, `query_drg_dashboard`,
  `query_mikado_status`, `lookup_ci` (DB queries)
- `praca_scaffold scaffold-folder`, `praca_scaffold backpatch-parent` (scaffold)
- `ow_write_ci`, `upsert_praca`, `upsert_sc`, `tag_ci` (registration/metadata)
- `check_folder_frontmatter` (validation)
- `deferral_scanner` (scan, with the *classification* of hits remaining judgment)
- `ow_close_ci` (the FIDO2-sealed close)
- grep-based self-checks collapse into **typed tool returns** (`id`, `parent`,
  `created_files`, `status`).

### 5.2 Judgment (stays on the session model)

- **TP-gap V-1..V-6 sufficiency classification** (createSPR2 Phase 0)
- **`change_class`, `severity`, `domain`** impact decisions (derive-recommend / verify)
- **Lesson elevation / distillation** (create + close)
- **Check-6 semantic reconciliation** (break→fix→VCL→TP correspondence across docs)
- **The actual code fix + its defect-coverage test step** (doSPR2 Phase 2 / 1.5)
- **Deferral legitimacy classification, D31 consistency, tag creation** (close)

## 6. Delivery pipeline (left-shifted)

The hybrid is itself built as a **transformational pipeline** whose effort is
front-loaded into design (the user's left-shift), mirroring the Overwatch lifecycle
(DAR/RFC design-checking dominates; implementation is the small, mechanical tail):

### Phase DAR — analysis
Produce the full command catalog and the boundary table above. For each deterministic
operation, capture exact invocation, args, return shape, and failure modes. Risk centers
on miscategorizing a step as deterministic when it is judgment (silent corruption).

### Phase RFC — design/checking (the expensive part)
Specify the tool surface *before* generation: per-tool `inputSchema` (types, enums,
ranges), server-computed defaults, and the return shape that replaces grep self-checks.
Decide coarse-vs-fine tooling and where each workflow's gates/STOP points survive.
Solely from the model's proven per-run capability — no external input gate is required.

### Phase do — implementation (~10% of effort)
Generate the MCP server from the design; rewrite the markdown into thin procedure
orchestration that references tools by name. Heavily mechanical once DAR/RFC are locked.

### Phase check/close — verification
One live `createSPR` run as the smoke test. The first real invocation doubles as
verification: any latent schema error surfaces here, which is acceptable because the
workflow is run repeatedly anyway.

## 7. Milestones

1. **M1 — Catalog + boundary doc** (Phase DAR deliverable): the deterministic-vs-judgment
   table. Fully automatable from the workflow text already read.
2. **M2 — Tool-surface contract** (Phase RFC deliverable): every tool's name, schema,
   defaults, return shape; the markdown-rewrite template; the index spec.
3. **M3 — Generated server + rewritten markdown** (Phase do deliverable).
4. **M4 — Smoke-test** one `createSPR` end-to-end via the generated surface.

## 8. Risks and mitigations

| Risk | Mitigation |
|:-----|:-----------|
| Miscategorized step (judgment treated as deterministic) | Boundary table is the DAR review artifact; reviewed before generation |
| Latent wrong schema (correct-looking but wrong at run) | Thin-required/fat-default reduces surface; M4 smoke test catches |
| Losing the slash UX | Option A retained as the surface layer on top of MCP |
| Opaque tool judgments (traceability loss) | Judgment stays on session model; tools return `evidence` notes |
| Markdown↔tool drift after text improvements | Generated index + single-source contract; tool layer is canonical for args |
| Schema done by guessing OW_tools real types | Derive from the model's demonstrated per-run capability; verify at M4 |

## 9. Open questions

- Tool granularity: one tool per phase vs one per command (coarse vs fine). Default:
  fine per command, grouped by phase prefix.
- Placement of the MCP server code (new crate/module vs wrapper around `OW_tools`).
- Whether `check` (the least-scripted stage) should prioritize scripting its semantic
  reconciliation before create/close, given it is the highest-judgment gate today.

## 10. Verification list (P-series)

- **P-1** — Catalog is exhaustive: every deterministic executable in the 4 v2 workflows
  appears in the boundary table (create=10, do=6 new, close=9 new, check=0).
- **P-2** — Boundary correctness: each entry is classified deterministic or judgment
  with a code/evidence reference.
- **P-3** — Schema principle applied: required fields are only the few genuinely-decided
  inputs; derivable values are server-computed defaults.
- **P-4** — Traceability: judgment steps remain on the session model; no self-inferring
  tool is introduced for judgment.
- **P-5** — Index-then-load: Tier-1 index is small; full detail loads only on demand.
- **P-6** — M4 smoke-test passes: a `createSPR` runs end-to-end through the generated
  surface with correct results.

**END.** This is a plan, not the implementation; it changes no code in `crates/`, `src/`,
`temp/`, `~/.jcode`, or the Overwatch workflow files.
