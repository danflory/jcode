---
# jcode-local frontmatter (SPR folder conversion, 2026-09-17).
# jcode is NOT governed by Overwatch's UDRS: no UDRS/ci_impacted/parent numeric
# ids are fabricated here. Only real, repo-verifiable values are used.
id: SPR-0009
title: workflows-not-invocable-as-slash-commands - Enforcement and Governance
status: DRAFT
author: operator
created: 2026-09-17
domain: ENGINEERING
severity: Major
type: SPR.GOVERNANCE
version: "2026-09-17"
---

# SPR-0009 Enforcement and Governance

## 1. Governed-CI preservation

The governed **source of truth stays `.agents/workflows/<name>.md`**: id'd,
versioned, protected, changed only through the project's own governance. jcode
does not govern workflows; it consumes them.

Every jcode-facing artifact — Option A command file, Option C `SKILL.md`
wrapper, or Option D MCP tool registration — is a **generated, hash-pinned
pointer**:

- generated from the governed source by a build/generator step;
- pinned with `source` + `source_sha256` (contract `04`, §1);
- **regeneration drift check:** on load/invoke, recompute the governed source
  hash and compare. Mismatch ⇒ refuse (or warn loudly), forcing a regenerate.
- Never a second source of truth; never hand-edited logic.

This constraint is intentionally independent of which option is chosen. Option
D's per-project `.jcode/mcp.json` (`crates/jcode-base/src/mcp/protocol.rs:577-582`)
is itself generated and drift-checked, never edited by hand.

## 2. Enforceable vs advisory

Two distinct layers:

- **Advisory — the model following steps.** The step *instructions* inside a
  workflow are prompt-level guidance. Like `AGENTS.md`, they are loaded as
  reference text and are not executed:
  `crates/jcode-base/src/prompt.rs:458, 595`. The model "following" them is a
  soft property and cannot be hard-guaranteed; this is inherently advisory.

- **Enforceable — preconditions and ordering.** The structural properties of a
  workflow can and should be enforced by the `pre_tool` hook:
  `crates/jcode-base/src/config/default_file.rs:596-600`. `pre_tool` receives
  `JCODE_HOOK_TOOL_NAME` and the tool input JSON on stdin; exit 0 allows, exit 2
  blocks the call and stderr is shown to the model as the error; anything else
  fails open.
  Enforceable examples: "step 3's tool must not run before step 2's result",
  "precondition X not satisfied ⇒ blocked with reason".

## 3. No per-project hooks ⇒ global dispatcher keyed on `JCODE_HOOK_CWD`

jcode has **no per-project hooks**; hooks are global-only
(`crates/jcode-config-types/src/lib.rs:798-801`: all hooks except `pre_tool`
are observers; `pre_tool` is the sole gate, configured globally). Therefore
per-project governance cannot live in a project-local hook file.

Design: a **single global `pre_tool` dispatcher** that:

1. reads `JCODE_HOOK_CWD` (documented as a hook env var,
   `crates/jcode-config-types/src/lib.rs:793-796`) to identify the active
   project;
2. loads that project's generated workflow-gate manifest (itself a
   hash-pinned pointer per §1);
3. applies the project's precondition/ordering checks for the tool about to be
   called;
4. returns exit 2 (block + stderr) or exit 0 (allow), exactly per the
   `pre_tool` contract (`default_file.rs:596-600`).

This keeps per-project enforcement without per-project hooks, and matches the
same per-session/per-working-dir scoping principle already used for skills
(`crates/jcode-base/src/skill.rs:233-239`) and MCP config
(`protocol.rs:577-582`).

## 4. What is justifiable as advisory vs enforceable (summary)

| Property | Layer | Mechanism |
|:---------|:------|:----------|
| Workflow step text | Advisory | prompt part (`prompt.rs:458, 595`) |
| Discovery of commands/tools | Enforced | client registry / MCP `tools/list` |
| Argument substitution | Enforced | client-substituted body / MCP `arguments` (`protocol.rs:148`) |
| Preconditions / ordering | Enforced | global `pre_tool` dispatcher keyed on `JCODE_HOOK_CWD` (`default_file.rs:596-600`; `lib.rs:798-801`) |
| Governed source truth | Proposed, not in force | generated hash-pinned pointer + drift check (never a second source of truth); see §5 item 2 |

## 5. Relationship to the security model (`09_Security_Model.md`)

Enforcement and security are different axes here and should not be conflated:

- **Enforcement** (this document) is about *ordering and preconditions*: did the
  workflow's steps run in the right order, with the right gates answered. Its
  mechanism is the global `pre_tool` dispatcher, which is the only blocking point in
  the agent loop.
- **Security** (`09_Security_Model.md`) is about *capability and read scope*. Because
  the network posture is internal-only — MCP is a stdio child of the daemon in the
  same guest as the clones, the loopback governed DB, and the k3s cluster — there is
  no exposure boundary to enforce. The live questions are what the agent may read
  (the model API is the only egress) and what it may do (governed DB writes, the
  clone's code, cluster reach).

Two consequences for this document:

1. The `pre_tool` dispatcher is the **only** available gate for both purposes. If a
   read-scope policy is ever defined (§9 item 3 of the security model), it must be
   implemented here, because jcode has no per-project hooks and no other blocking
   point.
2. The "governed source truth" row in §4 is currently a **proposal, not an
   enforcement**: the hash-pinned pointer is unimplemented
   (`grep -c SHA256 temp/mcp/ow_createspr/server.py` → 0). Until it exists, nothing
   enforces that the executed `OW_tools` matches the reviewed one.

## 6. UNVERIFIED items

The exact env-var spelling and delivery of `JCODE_HOOK_CWD` to a spawned
`pre_tool` process is asserted from the hook env-var documentation
(`crates/jcode-config-types/src/lib.rs:793-796`) rather than from a run of the
hook; the executable dispatcher behavior is not exercised by this documentation
SPR (no code changes made).
