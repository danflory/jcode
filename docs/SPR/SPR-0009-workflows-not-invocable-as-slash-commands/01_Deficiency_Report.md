---
# jcode-local frontmatter (SPR folder conversion, 2026-09-17).
# jcode is NOT governed by Overwatch's UDRS: no UDRS/ci_impacted/parent numeric
# ids are fabricated here. Only real, repo-verifiable values are used.
id: SPR-0009
title: workflows-not-invocable-as-slash-commands - Deficiency Report
status: DRAFT
author: operator
created: 2026-09-17
domain: ENGINEERING
severity: Major
type: SPR.DEFICIENCY
version: "2026-09-17"
---

# SPR-0009 Deficiency Report: workflows are not invocable as slash commands

## Summary

jcode has **no extensible command concept and no custom-command registry**. Its
only comparable extensibility mechanism, the skill system, can neither take
parameters nor execute. The MCP client can execute parameterized tools but
implements only the `tools` primitive, so it cannot present a typed `/name`
command. Together these mean a Gemini workflow (or an Overwatch
`.agents/workflows/<name>.md`) is, at best, loaded as inert reference text and
at worst identical to jcode. The user's mental model from other clients
(`/name args` runs a procedure) has no carrier in jcode.

## Root Design Failure (class: no invocable-procedure abstraction)

The root failure is a **missing abstraction**, not a buggy one. jcode models
three things a workflow needs — durable discovery, parameters, and execution —
in three mutually incompatible subsystems:

| Need | jcode mechanism | Status |
|:-----|:----------------|:-------|
| Durable discovery | Skills (`skills/<name>/SKILL.md`) | Discovered, but prompt-only |
| Parameters | Skill tool `args` | **Accepted and ignored** |
| Execution | MCP `tools/call` | Executes, but no typed slash command |

### F1: the skill tool is the only prompt-like extensibility, and it cannot carry a parameter

`SkillInput` exposes `action` in {load, list, reload, reload_all, read} and an
`args: Option<String>` that the loader "currently [takes] as accepted and
ignored":

```
crates/jcode-app-core/src/tool/skill.rs:31-45
```

So even a skill that *is* the text of a workflow cannot receive `/name args`.
This is the crux of the reported problem: a parameterized procedure cannot
receive its parameter anywhere in the skill path.

### F2: skill discovery is rigid and parse-gated

Skills are discovered ONLY as `<dir>/skills/<name>/SKILL.md`. Discovery walks a
source dir and registers each subdirectory that contains a `SKILL.md` whose
frontmatter parses with the required `name` and `description`; failures are
warned and skipped:

```
crates/jcode-base/src/skill.rs:26-34   (SkillFrontmatter requires name + description)
crates/jcode-base/src/skill.rs:468-479 (load_from_dir: only skills/<name>/SKILL.md)
crates/jcode-base/src/skill.rs:486-492 (parse_skill: warns and skips on failure)
```

A workflow file placed anywhere except `skills/<name>/SKILL.md` with both
frontmatter fields is invisible to the skill system.

### F3: no workflow concept and no command registry

A grep for `.agents/workflows` under `crates/` and `src/` returns zero matches.
Slash commands are built into the client; there is no user-extensible command
table a workflow could register in.

### F4: execution exists only as MCP tools, which have no user-typed slash surface

The MCP client implements **only** the `tools` primitive:

```
crates/jcode-base/src/mcp/protocol.rs:142  (tools/list result)
crates/jcode-base/src/mcp/protocol.rs:148  (tools/call params)
crates/jcode-base/src/mcp/protocol.rs:155  (tools/call result)
```

A regex search for `prompts/list | prompts/get | list_prompts | McpPrompt |
resources/list` under `crates/` returns zero matches. So MCP can run a tool with
real parameters and a real result, but cannot register a typed `/name` slash
command (that would require the unimplemented `prompts` primitive). MCP tools
are invoked by the model, not typed by the user.

### F5: AGENTS.md is reference text, never a procedure

`AGENTS.md` is loaded and appended to the prompt; nothing executes it:

```
crates/jcode-base/src/prompt.rs:458  (AGENTS.md pushed as a prompt part)
crates/jcode-base/src/prompt.rs:595  (AGENTS.md static instructions per project)
```

This is why a workflow mapped into jcode reads as "reference text" — that is the
only way jcode can currently surface a markdown procedure.

## Deficiency Manifestations

- **M1** `/.agents/workflows/<name>` and `/name args` are not recognized as
  commands by the client's built-in slash-command table.
- **M2** When the workflow body is surfaced at all (via skills or AGENTS.md), it
  is inert prompt text; steps are not executed and arguments are dropped.
- **M3** There is no single canonical, discoverable, parameterizable,
  executable representation of a procedure; every existing surface fails at
  least one of those four properties.

## Evidence Block

All failure-mode claims above trace to the code citations in F1–F5, each of
which was read directly. UNVERIFIED items are listed in the anchor
(`SPR-0009.md`) — notably no interactive Gemini repro and the exact Overwatch
workflow front matter convention, which is asserted from the brief not from a
jcode source file.
