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
  the **session working directory**, not the jcode daemon cwd (issue #420).
- **Two process scopes**: `shared` servers pool jcode-daemon-global; non-shared servers are
  spawned **per-session with the session cwd** as the child process cwd
  (`connect_in_dir`, `crates/jcode-base/src/mcp/client.rs:155-181`).
- **Tools-only primitive**: MCP in jcode supports only `tools/list` and `tools/call`
  (`crates/jcode-base/src/mcp/protocol.rs:142, :148, :155`). No `prompts` or `resources`
  support (verified: 0 matches).
- **Credentials are scrubbed by denylist, not allowlist**: the child **inherits the
  jcode daemon's environment** with a narrow set of sensitive keys removed, then has the
  per-server declared `env` added on top (`mcp_child_env`,
  `crates/jcode-base/src/mcp/client.rs:411-418`; `Command::envs` at `:176`, with no
  `env_clear` on this path). The denylist is
  `*_API_KEY`, `*_ACCESS_TOKEN`, `*_AUTH_TOKEN`, plus exactly `AWS_ACCESS_KEY_ID`,
  `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `AZURE_CLIENT_SECRET`, and
  `GOOGLE_APPLICATION_CREDENTIALS` (`:396-409`). Anything else passes through:
  `GITHUB_TOKEN`, `HF_TOKEN`, `SLACK_BOT_TOKEN`, `CLIENT_SECRET`, `PGPASSWORD`, and
  `DATABASE_URL` are **not** scrubbed. This matters directly here, because the server
  under design will hold governed-DB write access; treat the inherited environment as
  untrusted input and have the server read only the config it needs.
- **No credentials leak by design**: providers are opted in per-server via declared
  `env`, so a server that needs a provider credential must be given it explicitly.
  That is a convenience property, not the isolation property the denylist implies.
- **The network posture is internal-only, so exposure is not the security question.**
  The MCP server is a stdio child of the jcode daemon, in the same guest as that daemon, the
  clones, the governed DB (loopback `127.0.0.1:51728`) and the k3s cluster, with no
  listener of its own. Transport security, inbound exposure, and config scope used as
  a protection are therefore moot; the live questions are capability, read scope, and
  provenance. Full treatment, including the measured containment state (effective
  root via passwordless sudo, uncontained guest) and the credentials stub, is in
  `09_Security_Model.md`. Nothing in this plan should be read as a network control.
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

**Measured against this catalog, Tier 1/Tier 2 is optional, not required.** The
cost of a tool definition was measured at ~168 tokens (`06_MCP_Server_OW_tools_Steps.md`
§6: 11 live tools = 1,844 tokens, computed with jcode's own
`len(json({name, description, input_schema}))/4` formula). At ~24 tools for the
whole 2-series that is ~4,000 tokens, and even 45 tools stays under the 8,000-token
threshold at which jcode swaps to the deferred `mcp_search`/`mcp_call` surface.
Below that threshold, exposing every tool eagerly is cheaper in round-trips than an
index plus a lookup call, and the lookup result itself enters context anyway. Adopt
index-then-load only if the catalog grows past roughly 45 tools, or if a workflow
family outside the 2-series is folded in.

The deferral mechanism itself is real and was confirmed behaviorally: setting
`mcp_tools_token_threshold = 1` on a running jcode daemon made the next session call
`mcp_search` then `mcp_call` instead of the direct tool, and restoring 8000 returned
it to the direct call — same daemon, no restart (terminology: `09_Security_Model.md` §2.1).

## 5. Deterministic-vs-judgment boundary

The 2-series (`createSPR2`, `doSPR2`, `checkSPR2`, `closeSPR2`) contains roughly
**19-24 distinct deterministic executable operations**, concentrated in `create`
and `close`; `check` has none.

Counts are measured from the workflow files, not estimated. `python3` invocation
lines: create=12, do=4, check=0, close=8. Distinct `db_write.py` subcommands:
create={`ow_write_ci`, `query_ci_by_path`, `query_test_execs`, `upsert_praca`,
`upsert_sc`}, do={`lookup_ci`, `query_ci_by_path`, `upsert_sc`},
check={}, close={`lookup_ci`, `query_ci_by_path`, `query_closure_readiness`,
`query_drg_dashboard`, `query_mikado_status`, `tag_ci`}. Add the non-`db_write`
operations per workflow: create adds `praca_scaffold scaffold-folder`,
`praca_scaffold backpatch-parent`, `update_author.py`, `check_folder_frontmatter.py`;
close adds `ow_close_ci` and `deferral_scanner`. Reproduce with
`grep -o "db_write.py [a-z_]*" .agents/workflows/<wf>.md | awk '{print $2}' | sort -u`
and `grep -c "python3 " .agents/workflows/<wf>.md`.

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

Schemas are **derived from source, not inferred from model capability**: every
deterministic operation is an existing CLI or function, so its types are already
written down. `python3 -m OW_tools.<tool> --help` yields the argparse surface, and the
`ow_actions_*` modules carry real signatures — e.g. `ow_resolve_ci(*, path, title,
ci_id) -> int | None` (`OW_tools/ow_actions_governance.py:157-170`),
`ow_register_ci(path) -> OW_TransitionResult`
(`OW_tools/ow_actions_efsm_compound.py:380`), `ow_callers(tool) -> dict[str, int]`
(`:197`). Doc 06 §2 does exactly this for seven entry points and records the result.
A schema that is guessed and only checked at run time is the failure mode the risk
table is trying to avoid; deriving costs minutes and removes the guess. The review
gate for this phase is therefore "every field traces to a real signature or `--help`
line", not "the model believes it can do this".

### Phase do — implementation (~10% of effort)
Generate the MCP server from the design; rewrite the markdown into thin procedure
orchestration that references tools by name. Heavily mechanical once DAR/RFC are locked.

There is already a working precedent for the shape of this output:
`temp/mcp/ow_createspr/` (doc 06 §8) implements createSPR2 as 11 stdlib-only tools over
stdio JSON-RPC 2.0, dry-run by default, verified end to end through jcode's own client
(`Connected: 1/1`) and by a real session calling `mcp__ow_createspr__ow_db_probe`. Reuse
its conventions — newline-delimited JSON framing (jcode does not use Content-Length,
`crates/jcode-base/src/mcp/client.rs:54,198`), structured per-step JSON returns, and
`dry_run` defaulting true on every mutating tool.

### Phase check/close — verification
Verification is two-staged, because a schema error in this surface does not fail
loudly — it writes a wrong `parent`, `domain`, or `severity` into the governed DB and
looks like success.

1. **Dry-run verification (required before any real run).** Execute every mutating tool
   with `dry_run: true` against a sandbox target: a `target_dir` outside the Overwatch
   repo and an explicit `artifact_id` so no governed number is allocated. Confirm
   created files, planned commands, and that
   `git -C /home/d/dev_env/clones/Overwatch status --porcelain` is unchanged before and
   after. Doc 06 §5 does this and it is reproducible in minutes.
2. **One live `createSPR` run** as the smoke test, with the operator gates answered
   (`tp_gap_category`, `tp_gap_reference`, `change_class`, `lesson_key`). This is the
   point at which a latent schema error is allowed to surface, because by then the
   dry-run pass has already excluded the corrupting cases.

Skipping stage 1 and treating the first real invocation as the test is not acceptable
for a workflow that writes governed state.

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
| Latent wrong schema (correct-looking but wrong at run) | Derive every field from `--help`/signatures at RFC; thin-required/fat-default reduces surface; mandatory dry-run pass before the live run |
| Losing the slash UX | Option A retained as the surface layer on top of MCP |
| Opaque tool judgments (traceability loss) | Judgment stays on session model; tools return `evidence` notes |
| Markdown↔tool drift after text improvements | Generated index + single-source contract; tool layer is canonical for args |
| Schema done by guessing OW_tools real types | Derive from source: `--help` output and `ow_actions_*` signatures, as doc 06 §2 does for seven entry points; verify with the dry-run pass before M4 |
| Credential leak into the MCP child | jcode scrubs only a narrow denylist (`*_API_KEY`, `*_ACCESS_TOKEN`, `*_AUTH_TOKEN`, five AWS/Azure/GCP names); the child inherits everything else, so the server must not assume its environment is clean. See `09_Security_Model.md` §6 (stub, to be developed) |
| No containment inside the sandbox | The agent is effective root (passwordless sudo, `lxd` group) in an uncontained KVM guest, so it can read cluster secrets and any credential file. "Internal-only" is a network property, not a privilege property: `09_Security_Model.md` §5 |
| Unverified code provenance | The server executes the clone's own `OW_tools` with DB reach and no hash check; decide one drift mechanism before generating (`08_Comparison_06_vs_07.md` §2a) |

## 9. Open questions

- Tool granularity: one tool per phase vs one per command (coarse vs fine). Default:
  fine per command, grouped by phase prefix. Doc 06 already ran this experiment for
  createSPR2 and fine per step worked, including the gate-return shape.
- Placement of the MCP server code (new crate/module vs wrapper around `OW_tools`).
  The question is narrower than it looks: the working precedent is a standalone stdlib
  Python server under `temp/mcp/ow_createspr/` (doc 06 §8) that shells out to
  `OW_tools`. No jcode crate changes were needed, which is the strongest argument for
  keeping the generated server out of the jcode crates.
- Whether `check` (the least-scripted stage) should prioritize scripting its semantic
  reconciliation before create/close, given it is the highest-judgment gate today.

## 10. Verification list (P-series)

- **P-1** — Catalog is exhaustive: every deterministic executable in the 4 v2 workflows
  appears in the boundary table (measured: 12 `python3` lines in create, 4 in do, 0 in
  check, 8 in close; 5/3/0/6 distinct `db_write` subcommands respectively).
- **P-2** — Boundary correctness: each entry is classified deterministic or judgment
  with a code/evidence reference.
- **P-3** — Schema principle applied: required fields are only the few genuinely-decided
  inputs; derivable values are server-computed defaults.
- **P-4** — Traceability: judgment steps remain on the session model; no self-inferring
  tool is introduced for judgment.
- **P-5** — Index-then-load: Tier-1 index is small; full detail loads only on demand.
  Not required below ~45 tools; if skipped, record that the eager surface was measured
  under the 8,000-token threshold.
- **P-6** — M4 smoke-test passes: every mutating tool is first exercised with
  `dry_run: true` against a sandbox target with the Overwatch tree unchanged, then a
  `createSPR` runs end-to-end through the generated surface with correct results.

**END.** This is a plan, not the implementation; it changes no code in `crates/`, `src/`,
`temp/`, `~/.jcode`, or the Overwatch workflow files.
