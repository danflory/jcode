---
# jcode-local frontmatter (SPR folder conversion, 2026-09-17).
# jcode is NOT governed by Overwatch's UDRS: no UDRS/ci_impacted/parent numeric
# ids are fabricated here. Only real, repo-verifiable values are used.
id: SPR-0009
title: workflows-not-invocable-as-slash-commands - TP Change Report
status: DRAFT
author: operator
created: 2026-09-17
domain: ENGINEERING
severity: Major
type: SPR.TP
version: "2026-09-17"
---

# SPR-0009 TP Change Report

## Classification

This is a **capability-gap SPR**, not a regression. There is no existing test
(false negative) that should have caught a behavior change, because the
invocable-procedure capability **does not exist** in jcode. Consistent with the
jcode-local convention used by SPR-0008 (no fabricated TP or parent TP ids), no
`TP` id is manufactured here.

- **Test gap type:** missing-capability (no TP, no parent TP).
- **What is missing:** a test that a workflow can be invoked as `/name args`
  with argument substitution and (for the enforceable subset) precondition /
  ordering gating. No such test can exist until one of options A/B carries a
  code change (see `03_Options_and_Decisions.md`). Option D needs only an MCP
  tool registration test.

## Gap table (VCL ↔ verification)

| Verification | Kind | Covers |
|:-------------|:-----|:-------|
| V-1 | Manual repro | `/name args` not recognized (client built-in table) |
| V-2 | Code check | Skill tool `args` accepted-and-ignored (`skill.rs:31-45`) |
| V-3 | Code check | Skill discovery + required frontmatter (`skill.rs:26-34, 468-479, 486-492`) |
| V-4 | Code check | No `.agents/workflows` registry in `crates/`/`src/` |
| V-5 | Code check | `pre_tool` gate semantics (`default_file.rs:596-600`); hooks global-only (`lib.rs:798-801`) |
| V-6 | Code check | `AGENTS.md` prompt-only (`prompt.rs:458, 595`) |
| V-7 | Contract review | `04`: load paths, discovery, substitution, hash-pinned pointer + drift check |
| V-8 | Architecture review | `05`: global dispatcher keyed on `JCODE_HOOK_CWD`; enforceable vs advisory |
| V-9 | Code check | MCP tools-only primitive (`protocol.rs:142, 148, 155`) |
| V-10 | Code check | No MCP prompts/resources (`prompts/list`, `McpPrompt`, `resources/list` → 0 matches) |
| V-11 | Code check | Per-project MCP override order (`protocol.rs:577-582`) |
| V-12 | Decision review | `03` is a four-way decision (A/B/C/D) with explicit goal mapping + recommendation |

## Proposed future test coverage (once a fix lands)

- **T-A (option A):** command file discovery across the four load roots;
  argument substitution of `$1..$n`; precedence when the same name exists in
  multiple roots; a generated hash-pinned pointer failing its drift check is
  refused/warned.
- **T-D (option D):** a workflow registered as an MCP tool is listed by
  `tools/list`, accepts typed arguments, executes, and returns a result;
  override order `.jcode/mcp.json` → `.mcp.json` → `.claude/mcp.json`.
- **T-enforce:** a `pre_tool`-keyed gateway blocks (exit 2) an out-of-order or
  unsatisfied-precondition step and surfaces stderr to the model
  (`default_file.rs:596-600`).

## UNVERIFIED

No runnable test is executed by this documentation SPR (no code changes were
made). V-1 remains a manual counter-check because no live Gemini client was run.
