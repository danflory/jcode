---
# jcode-local frontmatter (SPR folder conversion, 2026-09-17).
# jcode is NOT governed by Overwatch's UDRS: no UDRS/ci_impacted/parent numeric
# ids are fabricated here. Only real, repo-verifiable values are used.
id: SPR-0009
title: workflows-not-invocable-as-slash-commands - Command Surface Contract
status: DRAFT
author: operator
created: 2026-09-17
domain: ENGINEERING
severity: Major
type: SPR.CONTRACT
version: "2026-09-17"
---

# SPR-0009 Command Surface Contract (Option A)

This is the proposed interface contract for the recommended **custom command
surface**. It specifies what a command is, where it is discovered, how it is
invoked, how arguments substitute, and how it stays a governed pointer to
`.agents/workflows/<name>.md`.

## 1. Command files

A command file is a Markdown file with frontmatter and a body:

```markdown
---
name: <command-name>
description: <one-line description>
# optional:
source: .agents/workflows/<name>.md   # governed source path
source_sha256: <hash of governed source, generated>
---
<body with steps; `$1..$n`/`$@` are substituted>
```

- `name` + `description` are **required**, mirroring the skill frontmatter
  requirement (`crates/jcode-base/src/skill.rs:26-34`). A file missing either is
  warned and skipped, mirroring `parse_skill`
  (`crates/jcode-base/src/skill.rs:486-492`).
- `source` + `source_sha256` are **generated** fields: the command file never
  holds workflow logic, only a hash-pinned pointer to the governed source. If a
  regeneration drift check finds `source_sha256` no longer matches the governed
  file, invocation is refused with a clear "regenerate command from governed
  source" message. Never a second source of truth, never hand-edited logic.

## 2. Discovery and load roots

Command files are discovered from four roots, in override order (later wins for
same-named commands):

1. `.jcode/commands/`
2. `.agents/commands/`
3. `.claude/commands/`
4. `.gemini/commands/`

Each root contributes `<root>/<name>.md` files (flat, name = filename stem,
analogous to namespacing existing clients use). Discovery follows the
`load_from_dir` shape established by the skill registry
(`crates/jcode-base/src/skill.rs:468-479`): iterate the dir, accept only files
whose frontmatter parses, skip the rest.

## 3. Invocation

`/name args...` resolves `name` against the merged registry, then:

1. Validates the `source_sha256` pointer against the governed source (fail on
   drift).
2. Substitutes arguments into the body:
   - `$1..$n` → positional arguments (quoted to preserve spaces);
   - `$@` → all arguments;
   - `$$` → a literal `$`.
3. Any shelling out is non-interactive and scoped to the active working
   directory (never the daemon cwd; see the per-session overlay note in
   `crates/jcode-base/src/skill.rs:233-239` for the same principle).

## 4. Relationship to skills and MCP

- **Skills** remain prompt-only discovery (`skill.rs:26-34, 468-486`) and are
  NOT the command surface. A command is not a skill; they are separate
  registries. The skills `args` field remains accepted-and-ignored
  (`crates/jcode-app-core/src/tool/skill.rs:31-45`); the command registry has
  its own argument handling.
- **MCP** (`crates/jcode-base/src/mcp/protocol.rs:142-161`) is
  forwarded-to where a workflow step needs controlled execution; the contract
  does not change MCP's tools-only primitive, and it does not pretend MCP can
  register a typed `/name` command (no prompts support).

## 5. Error contract

- Unknown `/name` → "unknown command" (no partial execution).
- Stale `source_sha256` → block with "command out of date; regenerate from
  governed source".
- Missing required frontmatter → warned and skipped at discovery
  (`skill.rs:486-492` parallel).
- Step gating failures surface exactly like `pre_tool`: blocked with stderr
  shown to the model (`crates/jcode-base/src/config/default_file.rs:596-600`).

## 6. Topology note

The client owns the `/name` parser and the merged registry (a client-side
change per Option A). Enforcement is delegated to the `05` documentary model:
the global `pre_tool` dispatcher keyed on `JCODE_HOOK_CWD`
(`crates/jcode-config-types/src/lib.rs:798-801`) applies per-project gates
because jcode has no per-project hooks.
