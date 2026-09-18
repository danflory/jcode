---
# jcode-local frontmatter (SPR folder conversion, 2026-09-17).
# jcode is NOT governed by Overwatch's UDRS: no UDRS/ci_impacted/parent numeric
# ids are fabricated here. Only real, repo-verifiable values are used.
id: SPR-0009
title: workflows-not-invocable-as-slash-commands - Options and Decisions
status: DRAFT
author: operator
created: 2026-09-17
domain: ENGINEERING
severity: Major
type: SPR.OPTIONS
version: "2026-09-17"
---

# SPR-0009 Options and Decisions

Four candidate approaches. Each satisfies a different mix of two goals:

- **Goal 1 — user-typed invocation:** the user types `/name args` and jcode
  resolves and runs it. This is the literal "slash command" experience.
- **Goal 2 — model-invoked execution:** the agent (model) calls a parameterized,
  durable, actually-executed primitive. This is what MCP tools already give.

## Option A — Custom command surface

Load command files from `.jcode/commands/`, `.agents/commands/`,
`.claude/commands/`, `.gemini/commands/`, with argument substitution.

- **Goal 1:** yes (a `/name args` parser + registry is added).
- **Goal 2:** yes, indirectly (the command shells out or yields a tool call).
- **Code change:** new client-side command registry + resolver + argument
  substitution (`crates/`/client). Largest surface of the four.
- **Tradeoffs:** most faithful to the requested experience; preserves governing
  source-of-truth via generated hash-pinned pointers (`04`, `05`). Highest
  implementation and maintenance cost; new parsing and precedence rules to
  govern and test.

## Option B — Extend skills into real commands

Plumb `args` through and add a workflow loader reusing existing skill discovery
(`skills/<name>/SKILL.md`).

- **Goal 1:** partial (a skill could back a slash command only if the client
  learns to invoke skills by name, which is still a client change).
- **Goal 2:** partial (execution still needs a run mechanism; skills today are
  prompt-only).
- **Code change:** medium (skill tool `args` plumbing at
  `crates/jcode-app-core/src/tool/skill.rs:31-45`; a workflow loader that maps
  `.agents/workflows/*.md` onto the rigid skill discovery at
  `crates/jcode-base/src/skill.rs:468-479`).
- **Tradeoffs:** reuses existing discovery and the required-name-description
  frontmatter, so it integrates cleanly with the current model. But it inherits
  the skill system's rigid `skills/<name>/SKILL.md` shape and prompt-only
  semantics; the crux (`args` ignored) must be changed anyway, and the
  "reference text" mindset is baked in.

## Option C — No new surface: generated SKILL.md wrappers + delegated CLI

Generate hash-pinned `SKILL.md` wrappers; a command the user types is a CLI the
wrapper delegates to, gated by `pre_tool`.

- **Goal 1:** weak (the `/name args` syntax itself still does not exist; a
  skill is prompt text, not a typed command).
- **Goal 2:** yes, via the CLI + `pre_tool` gate
  (`crates/jcode-base/src/config/default_file.rs:596-600`).
- **Code change:** low (wrapper generator + CLI, no new registry).
- **Tradeoffs:** politically cheapest (no command surface), easiest to govern
  (generated, hash-pinned pointer is natural here). But it does not actually
  deliver `/name args`; it is a runner masquerading as one and keeps
  workflows as model-readable/external-CLI artifacts.

## Option D — MCP tool surface

Expose each workflow as an MCP **tool** (real parameters, real execution, real
result), registered per project via `.jcode/mcp.json`.

- **Goal 1:** no (MCP has **no** prompts support, so there is no typed
  `/name` slash command surface; workflows would be *model-invoked*
  `workflow_check_spr(id="SPR-123")`, not user-typed `/checkSPR2 SPR-123`).
  MCP implements only the `tools` primitive:
  `crates/jcode-base/src/mcp/protocol.rs:142, :148, :155`; `prompts/list`,
  `McpPrompt`, and `resources/list` searches return nothing under `crates/`.
- **Goal 2:** yes, fully and **today** — MCP is durable, parameterized, and
  distinctly executed, and it is the *only* jcode mechanism with all three.
  Per-project registration already resolves `.jcode/mcp.json` → `.mcp.json` →
  `.claude/mcp.json`:
  `crates/jcode-base/src/mcp/protocol.rs:577-582`.
- **Code change:** none in jcode (a generator emits the MCP tool + server
  config); usable with zero jcode modifications.
- **Tradeoffs:** the only option usable today with no code change, and fully
  exercises controlled parameters/results. But it targets **model-invoked**
  execution, not **user-typed** slash commands; the literal requested
  experience (`/name args`) is impossible without an A or B client change.

## Recommendation: **Option A**

**Recommended — Option A (custom command surface).** It is the only option that
delivers the *requested* experience — a literal `/name args` slash command with
argument substitution — because B also requires a client addition to turn a
skill into a typed command, C explicitly declines a new surface, and D is
unambiguously a model-invoked tool surface given MCP has no prompts primitive.
A is chosen over B because B inherits the skill system's rigid, prompt-only,
`args`-dropping shape (`crates/jcode-app-core/src/tool/skill.rs:31-45`) that is
the very root of the problem; A starts a clean command registry. A is chosen
over D by explicitly answering the "which goal" question: if the requirement is
model-invoked execution only, D is strictly cheaper and available today, but the
reported problem is a *user-facing* slash-command gap, so Goal 1 dominates and
only A (or B with extra work) satisfies it. A's extra cost over B is bounded and
pays for a surface that is honest about being a command rather than stretching
the skill abstraction.

### Cross-cutting analysis

- **Argument substitution.** A defines `$1..$n` (and `$@`) substitution in the
  resolved command file body (`04_Command_Surface_Contract.md`). D passes
  arguments through the MCP `arguments` value
  (`crates/jcode-base/src/mcp/protocol.rs:148`) natively; B must first fix the
  dropped `args` (`skill.rs:31-45`).
- **Advisory vs enforceable.** The model *following the steps* inside a
  workflow stays advisory (prompt-level, like `AGENTS.md` today,
  `crates/jcode-base/src/prompt.rs:458, 595`). What is enforceable is
  preconditions/ordering, enforced by `pre_tool`
  (`crates/jcode-base/src/config/default_file.rs:596-600`): a step's tool call
  is blocked on exit 2 with stderr shown to the model. Full split:
  `05_Enforcement_and_Governance.md`.
- **No per-project hooks.** Hooks are global-only
  (`crates/jcode-config-types/src/lib.rs:798-801`), so per-project governance
  cannot live in a project hook. A (and D) route it through a **global
  dispatcher keyed on `JCODE_HOOK_CWD`** that resolves the active project and
  applies that project's workflow gates (`05`).
- **Governed-CI preservation (all options).** The governed source of truth
  stays `.agents/workflows/<name>.md`. Any jcode-facing artifact (A: command
  file; C: SKILL.md wrapper; D: MCP tool) is a **generated, hash-pinned
  pointer** verified by a regeneration drift check — never a second source of
  truth, never hand-edited logic (`05`).
