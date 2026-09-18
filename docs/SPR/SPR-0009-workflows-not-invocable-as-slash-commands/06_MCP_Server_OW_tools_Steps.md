---
# jcode-local frontmatter (SPR folder conversion, 2026-09-17).
# jcode is NOT governed by Overwatch's UDRS: no UDRS/ci_impacted/parent numeric
# ids are fabricated here. Only real, repo-verifiable values are used.
id: SPR-0009
title: workflows-not-invocable-as-slash-commands - MCP Server for OW_tools Build Steps
status: DRAFT
author: operator
created: 2026-09-18
domain: ENGINEERING
severity: Major
type: SPR.STEPS
version: "2026-09-18"
---

# SPR-0009 MCP Server for OW_tools — Build Steps

## Interpretation note

OW_tools holds **Python tools and CLIs** (intention-revealing action functions,
database-write dispatchers, lifecycle management scripts, scaffold generators),
not `.agents/workflows/*.md` workflow documents. The SPR-0009 problem statement
targets `.agents/workflows/*.md` as the governed source of truth, but Option D
(the MCP route) is defined as exposing **any** procedure as an MCP tool. This
document interprets the assignment as: **build an MCP server that wraps the
invocable OW_tools Python entry points so they become model-callable MCP tools
in jcode.** The same hash-pinned-pointer governance pattern from docs 04/05
applies to the generated `.jcode/mcp.json` and the server dispatch layer.

---

## 1. OW_tools entry point inventory

Representative invocable entry points, with real file paths. Each is callable
via `python3 -m` and accepts arguments through argparse.

### 1.1 CLI dispatcher (`__main__.py`)

| Entry point | Path | Invocation |
|:------------|:-----|:-----------|
| CLI dispatcher | `OW_tools/__main__.py` | `python3 -m OW_tools <module> [args]` |
| Tool lister | `OW_tools/discover_cli.py` | `python3 -m OW_tools --list` |

The dispatcher (`OW_tools/__main__.py:9-59`) loads any module under `OW_tools.`
that exports an `execute()` function and forwards remaining CLI args to it.
`discover_cli.py` (`OW_tools/discover_cli.py:14-64`) does static AST analysis to
find conformant modules with `execute()`.

### 1.2 D33 intention-revealing action functions

A facade module (`OW_tools/ow_actions.py:1-165`) that re-exports ~50 thin
wrapper functions from submodules:

| Domain | Functions (representative sample) | File |
|:-------|:----------------------------------|:-----|
| Governance | `ow_resolve_ci`, `ow_callers`, `ow_blast_radius`, `ow_list_all_themes`, `ow_list_dimensions`, `ow_all_archived`, `ow_mark_archived`, `classify_path_divergence`, `ow_git_head_subject`, `ow_query_audit_changelog`, `ow_list_cis_by_theme`, `ow_list_themes_like` | `ow_actions_governance.py` |
| EFSM compound | `ow_register_ci`, `ow_register_directory`, `ow_close_ci`, `ow_close_rfc`, `ow_get_ci_info`, `ow_release_ci`, `ow_supersede_ci`, `ow_withdraw_ci`, `ow_query_efsm_path` | `ow_actions_efsm_compound.py` |
| EFSM single | `ow_activate_ci`, `ow_promote`, `ow_demote`, `ow_deprecate`, `ow_escalate`, `ow_expire`, `ow_freeze`, `ow_unfreeze`, `ow_obsolete`, `ow_reassign`, `ow_recall`, `ow_reject`, `ow_revise`, `ow_suspend`, `ow_submit_for_promotion`, `ow_submit_for_deprecation`, `ow_submit_for_obsolescence`, `ow_submit_for_suspension` | `ow_actions_efsm_single.py` |
| Lessons | `ow_prior_art`, `ow_prior_art_broad`, `ow_log_lesson`, `ow_sr_findings`, `ow_sr_open_findings`, `ow_sr_decisions`, `ow_lessons_for_artifact`, `ow_lessons_for_node`, `ow_lessons_for_topic`, `ow_lesson_coverage`, `ow_lesson_detail`, `ow_critical_lessons`, `ow_resolve_lesson`, `ow_validate_lessons` | `ow_actions_lessons.py` |
| Mikado | `ow_register_mikado_graph`, `ow_advance_mikado_node`, `ow_close_mikado_node`, `ow_firecontrol_schema`, `ow_dump_schema`, `ow_mikado_critical_path`, `ow_mikado_status` | `ow_actions_mikado.py` |
| Scanner | `ow_retire_stale_rules`, `ow_entropy_bucket_summary`, `ow_demote_rule`, `ow_backfill_field`, `ow_query_scan_findings`, `ow_query_scan_rules` | `ow_actions_scanner.py` |
| Metadata | `ow_relocate`, `ow_rename`, `ow_reparent`, `ow_set_functional_status`, `ow_update_sha` | `ow_actions_metadata.py` |
| Commit | `ow_commit` | `ow_actions_commit.py` |

### 1.3 CLI tool packages (each with `__main__.py` + `execute()`)

| Package | Path | Typical invocation | Purpose |
|:--------|:-----|:-------------------|:--------|
| `ci_lifecycle` | `OW_tools/ci_lifecycle/__main__.py` | `python3 -m OW_tools.ci_lifecycle transition --ci-id <ID> --event <event>` | Governed CI status transitions via EFSM |
| `praca_scaffold` | (dir under `OW_tools/praca_scaffold/`) | `python3 -m OW_tools.praca_scaffold generate --type <type> --parent <id> --title <title>` | PRACA document scaffold generation |
| `next_number` | `OW_tools/next_number/__main__.py` | `python3 -m OW_tools.next_number <CATEGORY>` | Atomic DB-backed sequential ID allocation |
| `db_write` | `OW_tools/db_write.py` | `python3 OW_tools/db_write.py <command> [args]` | Universal DB write dispatcher (20+ command modules) |
| `ow_sign` | `OW_tools/cli/ow_sign.py` | `python3 OW_tools/cli/ow_sign.py register [--force]` | FIDO2 hardware authenticator (YubiKey) signing |
| `session_lifecycle` | `OW_tools/session_lifecycle/` | `python3 -m OW_tools.session_lifecycle.session_init` / `session_close` / `update_author` | Session init/close, SR file management, git author enrichment |
| `daemon_contract` | `OW_tools/daemon_contract/` | `python3 -c "from OW_tools.daemon_contract import contract_health; ..."` | Database connection health checks |
| `gemini_change_approve` | `OW_tools/gemini_change_approve/` | `sudo OW_tools/gemini_change_approve/apply.py --reason ...` | Signature-gate for out-of-repo protected files |

### 1.4 RUNBOOKs (reference workflows, not invocable entry points)

| RUNBOOK | Path |
|:--------|:-----|
| CI Lifecycle | `OW_tools/ci_lifecycle/RUNBOOK.md` |
| Daemon Contract | `OW_tools/daemon_contract/RUNBOOK.md` |
| Gemini Change Approve | `OW_tools/gemini_change_approve/RUNBOOK.md` |
| Next Number | `OW_tools/next_number/RUNBOOK.md` |
| PRACA Scaffold | `OW_tools/praca_scaffold/RUNBOOK.md` |
| Session Lifecycle | `OW_tools/session_lifecycle/RUNBOOK.md` |
| UDRS Archive Audit | `OW_tools/udrs_archive_audit/RUNBOOK.md` |
| UDRS Linker Frontmatter Schema | `OW_tools/udrs_linker/RUNBOOK_frontmatter_schema.md` |

RUNBOOKs document **how to use** the tools; they are not themselves invocable.
An MCP server would wrap the underlying entry points, not the RUNBOOK files.

---

## 2. Mapping table: OW_tools entry point → proposed MCP tool

Each row proposes an MCP tool name, its expected JSON Schema parameters, and the
shape of its result. The server implementation would import or shell out to the
Python entry point and translate the result into MCP `content[].text`.

| OW_tools entry point | Proposed MCP tool name | Parameters (JSON Schema properties) | Result | Notes |
|:---------------------|:-----------------------|:------------------------------------|:-------|:------|
| `ow_register_ci(path)` | `mcp__ow_tools__register_ci` | `path: string` | `{udrs_id: int}` | Thin Python wrapper, easy to inline-import |
| `ow_resolve_ci(path, title, ci_id)` | `mcp__ow_tools__resolve_ci` | `path?: string, title?: string, ci_id?: int` | `{udrs_id: int\|null}` | UNION key lookup |
| `ow_blast_radius(commit_sha)` | `mcp__ow_tools__blast_radius` | `commit_sha: string` | `{files: [...], cis: [...]}` | Commit cross-reference |
| `ow_callers(tool)` | `mcp__ow_tools__callers` | `tool: string` | `{workflows: int, skills: int, ...}` | Workspace-wide analysis |
| `ci_lifecycle transition` | `mcp__ow_tools__ci_transition` | `ci_id: int, event: string, intent?: string` | `{message: string}` | Shell out to `python3 -m OW_tools.ci_lifecycle` |
| `next_number <CAT>` | `mcp__ow_tools__next_number` | `category: string, peek?: bool` | `{number: int}` | Shell out to `python3 -m OW_tools.next_number` |
| `praca_scaffold generate` | `mcp__ow_tools__praca_generate` | `type: string, parent: int, title: string, dir?: string, output?: string` | `{path: string, udrs_id: int}` | Shell out to `python3 -m OW_tools.praca_scaffold` |
| `session_lifecycle.session_init` | `mcp__ow_tools__session_init` | `dry_run?: bool` | `{session_metadata: object}` | Shell out to `python3 -m OW_tools.session_lifecycle.session_init` |
| `session_lifecycle.session_close` | `mcp__ow_tools__session_close` | `dry_run?: bool` | `{close_metadata: object}` | Shell out to `python3 -m OW_tools.session_lifecycle.session_close` |
| `ow_entropy_bucket_summary()` | `mcp__ow_tools__entropy_summary` | _(none)_ | `{summary: object}` | Stateless read, no side effects |
| `ow_list_all_themes()` | `mcp__ow_tools__list_themes` | _(none)_ | `{themes: [{theme, count}]}` | Stateless read |
| `ow_prior_art(keyword)` | `mcp__ow_tools__prior_art` | `keyword: string` | `{results: [...]}` | Lessons + SR findings search |

**Not MCP-tool-shaped:**

| OW_tools thing | Reason |
|:---------------|:-------|
| `ow_sign` (FIDO2/YubiKey) | Requires interactive hardware touch + PIN; MCP has no interactive input channel. jcode's `tools/call` expects a non-interactive JSON-RPC exchange (`crates/jcode-base/src/mcp/protocol.rs:148`). |
| `gemini_change_approve/apply.py` | Requires `sudo` and operator approval; the MCP server runs as the agent, not as root. |
| `daemon_contract` health checks | These are monitoring probes, not invocable procedures. An MCP tool wrapping them would be redundant with the existing sentinel file (`cat .contract_status`). |
| `db_write.py` subcommands | This is the **universal write dispatcher** with 20+ command families. Exposing every subcommand as a separate tool creates explosion. Better: expose a single `mcp__ow_tools__db_write` with a `command` discriminator parameter, or pick the 3-5 most-used subcommands and leave the rest behind `mcp_search`/`mcp_call`. |
| RUNBOOK files | Documents, not executable code. |

---

## 3. Numbered build steps (PROPOSED, never executed)

### Step 1 — Scaffold the MCP server project

Create a new Python package (e.g. `ow_tools_mcp_server/`) next to the existing
`OW_tools/` directory, or as a subdirectory `OW_tools/mcp_server/`. The server
MUST NOT be inside `OW_tools/` if it needs its own dependencies — the governed
`OW_tools/` environment is separate.

PROPOSED structure:

```
ow_tools_mcp_server/
  __init__.py
  server.py            # FastMCP / stdio JSON-RPC 2.0 server
  tool_definitions.py  # Tool schema definitions (tools/list response)
  dispatch.py          # Maps tool name → Python callable or subprocess
```

### Step 2 — Implement stdio transport

jcode's MCP client supports only `stdio` transport
(`crates/jcode-base/src/mcp/protocol.rs:192-207`: `command` + `args` for stdio servers). The server MUST:
- Read JSON-RPC 2.0 requests from stdin, line-delimited.
- Write JSON-RPC 2.0 responses to stdout.
- Log diagnostics to stderr (which jcode captures and surfaces in error cases).
- NOT use HTTP, SSE, or WebSocket transport (jcode skips non-stdio entries at
  load time — `crates/jcode-base/src/mcp/protocol.rs:207`).

PROPOSED implementation: use the `fastmcp` or `mcp` Python SDK which handles
the stdio transport and JSON-RPC framing. The `FastMCP` dev server with stdio
transport is the recommended approach.

### Step 3 — Implement `tools/list`

Return tool definitions. Each tool has:
- `name`: prefixed with `ow_tools__` for namespacing (e.g. `ow_tools__register_ci`).
- `description`: taken from the Python function's docstring or RUNBOOK purpose.
- `inputSchema`: JSON Schema derived from the Python function's arguments
  (argparse params for CLI tools, function kwargs for ow_actions functions).

Example tool definition:

```json
{
  "name": "ow_tools__next_number",
  "description": "Allocate next sequential UDRS number for a category (atomic DB-backed)",
  "inputSchema": {
    "type": "object",
    "properties": {
      "category": {
        "type": "string",
        "description": "UDRS category (SPR, RFC-OW, DAR-OW, CAR, etc.)"
      },
      "peek": {
        "type": "boolean",
        "description": "Query without allocating"
      }
    },
    "required": ["category"]
  }
}
```

### Step 4 — Implement `tools/call` dispatch

For each tool name, the dispatch logic does one of:

**A. Inline Python import** (for `ow_actions.py` wrappers):
```python
from OW_tools.ow_actions import ow_register_ci
result = ow_register_ci(path=arguments["path"])
```
Used for functions that have no side effects beyond the DB and need no
CLI argument parsing.

**B. Subprocess** (for CLI tool packages with argparse):
```python
import subprocess, json
result = subprocess.run(
    ["python3", "-m", "OW_tools.ci_lifecycle", "transition",
     "--ci-id", str(arguments["ci_id"]),
     "--event", arguments["event"]],
    capture_output=True, text=True, cwd=project_root,
)
```
Used for tools that have complex argparse interfaces, expect specific exit
codes, or write files.

**C. Hybrid** — use the internal Python API of the tool package directly
instead of shelling out, when the package exports an importable `execute()`
function. Note: many tools in OW_tools have `execute()` per the convention
(`discover_cli.py:84-103`). Prefer this over subprocess when it avoids
argparse re-entry.

### Step 5 — Error and exit-code surfacing

OW_tools tools use exit codes (see `OW_tools/ci_lifecycle/RUNBOOK.md:31-35`):
- `0` = success
- `1` = database or unknown error
- `2` = validation error (e.g. illegal EFSM transition)

The MCP server MUST:
- Map exit code `0` → `isError: false`, stdout content as `content[].text`.
- Map exit code `1` → `isError: true`, stderr as `content[].text`.
- Map exit code `2` → `isError: true`, stderr as `content[].text`, preserving
  the exact error message. (Note: jcode's own `pre_tool` hook, which also blocks
  on exit 2 and surfaces stderr, is a separate mechanism documented at
  `crates/jcode-base/src/config/default_file.rs:596-600`; the MCP `isError`
  mapping here is this server's own choice, not jcode hook behavior.)

For inline imports, catch `OW_Error` / `Exception` and set `isError: true`
with the exception message.

### Step 6 — cwd scoping

jcode spawns MCP servers at project root
(`crates/jcode-base/src/mcp/protocol.rs:577-582`: `load_project_locals` resolves per working directory).
The OW_tools Python code auto-detects project context via `detect_project()`
(`TOOL_STANDARDS.md:22-39`), which calls `git rev-parse --show-toplevel` from
CWD. The MCP server MUST either:
- Inherit jcode's CWD (which is the project root), or
- Accept a `JCODE_HOOK_CWD`-style env var to set its working directory.

PROPOSED: set the `cwd` field in the MCP server config to the project root
(already the default when `.jcode/mcp.json` is in the project root).

### Step 7 — Hash-pinned governed source pointer (per SPR-0009 docs 04/05)

The governed source of truth is `OW_tools/` (the Python code itself). The MCP
server configuration (`.jcode/mcp.json`) and the server's dispatch table are
**generated, hash-pinned pointers** — never a second source of truth.

PROPOSED generator workflow:

1. A build script computes `sha256` of the relevant `OW_tools/` modules
   (or a manifest file `OW_tools/MANIFEST.json`).
2. The build script emits a `.jcode/mcp.json` that includes a custom env var
   `OW_TOOLS_SHA256=<hash>` passed to the MCP server.
3. At startup, the MCP server reads `OW_TOOLS_SHA256`, computes the actual
   hash of the files it loaded, and compares. Mismatch → the server refuses
   all tool calls with `isError: true` and a regeneration message.
4. A CI drift check (regen + diff) catches stale pointers before merge, per
   the governance model in doc 05 (§1).

This ensures that the MCP server always reflects the current OW_tools state
and that changes to OW_tools require a regeneration step.

---

## 4. Registration — proposed `.jcode/mcp.json` snippet

Per the resolution order (`crates/jcode-base/src/mcp/protocol.rs:577-582`: `.jcode/mcp.json` → `.mcp.json`
→ `.claude/mcp.json`), the generated config goes in `.jcode/mcp.json`:

```json
{
  "mcpServers": {
    "ow_tools": {
      "command": "python3",
      "args": [
        "-m",
        "ow_tools_mcp_server.server"
      ],
      "env": {
        "OW_TOOLS_SHA256": "<hash-of-governed-ow_tools-manifest>",
        "OW_TOOLS_PROJECT_ROOT": "${OW_TOOLS_PROJECT_ROOT:-/abs/path/to/overwatch}"
      },
      "timeout_secs": 120,
      "shared": false
    }
  }
}
```

- **Environment expansion is `${VAR}` and `${VAR:-default}` only, resolved
  against the process environment** (`crates/jcode-base/src/mcp/protocol.rs:283-296`,
  applied to `command`, `args`, `env` values, `url`, and `headers` at `:350-373`).
  There is no `${cwd}` magic: an unresolved name is left in place literally and
  jcode logs `MCP: Server '<name>' references unset environment variable '<var>'`
  (`crates/jcode-base/src/mcp/protocol.rs:389-395`). So use a real variable, a
  literal absolute path, or a `${VAR:-default}` fallback as shown above.
- `"timeout_secs"` — per-request reply budget for `tools/call`, `tools/list`, and
  `initialize`; absent means 30s
  (`crates/jcode-base/src/mcp/protocol.rs:225-230`). Governed DB calls can exceed
  30s, so raise it.
- `"shared": false` — the server maintains DB connections and cwd-dependent
  state, so it must not be shared across sessions
  (`crates/jcode-base/src/mcp/protocol.rs:199-203`: `shared` defaults to `true` for stateless API wrappers;
  stateful servers should not be shared).
- `command: "python3"` — stdio transport per `crates/jcode-base/src/mcp/protocol.rs:192-207`.
- The env var `OW_TOOLS_SHA256` is the hash-pinned pointer; `OW_TOOLS_PROJECT_ROOT`
  informs the server which project it serves.

---

## 5. Verification steps

Two sets. **A** runs today against the working implementation described in §8.
**B** is the same shape for the generated `ow_tools_mcp_server`; those names
will not resolve until it exists.

### A. Runnable now (server name `ow_createspr`)

```bash
# 1. Server starts and answers tools/list with real schemas.
#    jcode's client speaks NEWLINE-DELIMITED JSON
#    (crates/jcode-base/src/mcp/client.rs:54, :198), not Content-Length framing.
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"probe","version":"1"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  | python3 /home/d/dev_env/jcode/temp/mcp/ow_createspr/server.py

# 2. A real tool call returns a real result (read-only DB probe).
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"probe","version":"1"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"ow_db_probe","arguments":{}}}' \
  | python3 /home/d/dev_env/jcode/temp/mcp/ow_createspr/server.py

# 3. jcode registers and connects the server (from any session).
#    Registered in ~/.jcode/mcp.json; the mcp tool's reload action reports it.
```

Observed for command 1: `result.tools` lists 11 tools, each with an `inputSchema`.
Observed for command 2: `content[0].text` is a JSON object with
`"governed_db_reachable": true` and `"status": "ok"`.
Observed for command 3: `Reloaded MCP config. Connected: 1/1` plus all 11 names.

### B. Same shape for the generated server (not runnable yet)

```bash
# Verify the server responds to tools/list
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | python3 -m ow_tools_mcp_server.server \
  | head -c 500
```

Expected output: a JSON-RPC response with a `result.tools` array containing at
least one tool definition.

```bash
# Call the next_number tool in peek mode (allocates nothing).
# Tool names are `mcp__<server>__<tool>`, so the server name already namespaces
# them; do not also bake an `ow_tools__` prefix into the tool name.
echo '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"next_number","arguments":{"category":"SPR","peek":true}}}' \
  | python3 -m ow_tools_mcp_server.server \
  | python3 -m json.tool
```

Expected output: a JSON object with `content[0].text` containing an integer
(the current max SPR number — never creates a new one in peek mode).

```bash
# Tamper the pinned hash and confirm the server refuses.
OW_TOOLS_SHA256=deadbeef \
  echo '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"next_number","arguments":{"category":"SPR"}}}' \
  | python3 -m ow_tools_mcp_server.server
```

Expected: `isError: true` with a message about hash mismatch / regenerate required.

### 5.5 End-to-end acceptance (the check that settles it)

A tool list and a raw JSON-RPC call prove the server is correct in isolation.
They do not prove jcode's agent loop can reach it. Run a real session and confirm
the model invokes the tool through jcode's client:

```bash
jcode run --no-update --socket /run/user/1000/jcode-mcp-check.sock \
  'There is an MCP server named ow_createspr. Call its db probe tool and print the raw JSON result verbatim. Do nothing else.'
```

Observed on 2026-09-18: the transcript shows `[mcp__ow_createspr__ow_db_probe]`
and the result contains `"governed_db_reachable": true`, exit 0.

---

## 6. 8000-token threshold analysis

jcode's `[tools] mcp_tools_token_threshold` defaults to 8000
(`crates/jcode-base/src/config.rs:665`). When estimated MCP tool definitions
exceed this threshold in auto mode, the client swaps to the `mcp_search` /
`mcp_call` deferred surface
(`crates/jcode-app-core/src/agent/turn_execution.rs:519-529`).

The estimate is per tool: `len(json({name, description, input_schema})) / 4`,
summed (`crates/jcode-message-types/src/lib.rs:26-65`).

### Measured cost of the §8 implementation

Measured on 2026-09-18 by serializing the live 11-tool `tools/list` reply with
that exact formula:

| Tool | Tokens |
|:-----|-------:|
| `ow_createspr2_plan` | 65 |
| `ow_db_probe` | 133 |
| `ow_resolve_parent` | 153 |
| `ow_query_ci` | 193 |
| `ow_update_author` | 174 |
| `ow_scaffold_spr` | 286 |
| `ow_backpatch_parent` | 168 |
| `ow_register_subdocs` | 171 |
| `ow_upsert_praca` | 186 |
| `ow_populate_success_criteria` | 191 |
| `ow_frontmatter_sweep` | 124 |
| **Total (11 tools)** | **1,844** |

So the real per-tool cost is ~168 tokens, and 11 tools sit comfortably under the
threshold: mode stays eager and the model sees the tools directly. This is why
the §5.5 acceptance run could call `mcp__ow_createspr__ow_db_probe` by name with
no `mcp_search` round-trip.

### Tools worth eager exposure (below threshold)

These are the ~5 highest-value tools that should always be visible to the model
without a search round-trip:

| Tool | Rationale |
|:-----|:----------|
| `next_number` | Called in almost every workflow (allocating IDs for new documents) |
| `ci_transition` | Core EFSM lifecycle — used in every CI action |
| `register_ci` | Entry point for bringing new CIs under governance |
| `resolve_ci` | Universal CI lookup — discoverability |
| `prior_art` | Frequently used for research phase |

Projected at the measured ~168 tokens per tool: ~840 tokens for these five, not
the ~3,000 this document originally estimated. Well under the 8,000 threshold.

### Why the large fan-out should stay deferred

If all ~50 D33 action functions + ~10 CLI tools were exposed eagerly:

- Projected definitions: 60 tools × ~168 tokens each ≈ 10,100 tokens (over the
  threshold, triggering auto-deferral anyway). Using the measured per-tool cost
  rather than the earlier ~150 guess.
- Parameter schema variety is high (numbers, strings, optional structs). The
  `input_schema` values inflate the estimate.
- Many tools are rarely used (e.g. `ow_dump_schema`, `ow_list_dimensions`,
  `ow_backfill_field`, `ow_validate_lessons`). Keeping them behind
  `mcp_search`/`mcp_call` means the model does a targeted retrieval only when
  it actually needs them.

PROPOSED: Eagerly expose the 5-7 most common tools; leave the remaining ~50
behind the deferred surface. If a tool is called often enough to warrant
promotion, move it to the eager list in the generator config. This matches the
intent of the threshold mechanism
(`crates/jcode-app-core/src/agent/turn_execution.rs:519-529`).

---

## 7. Ambiguity flag

**OW_tools holds Python tools/CLIs, not `.agents/workflows/*.md` documents.**

The SPR-0009 problem statement (§Scope) is about `.agents/workflows/*.md`
files as the governed source of procedure definitions. OW_tools is a separate
directory governed by the Overwatch project's own UDRS process (GROUNDED_TRUTHS
Process Rule 12, per `OW_tools/README.md`).

The interpretation used in this document is: **an MCP server wrapping OW_tools
entry points is a valid and useful instantiation of Option D — it turns
real, parameterized, existing procedures into model-callable tools.** But it
does NOT address the literal SPR-0009 problem (invoking
`.agents/workflows/*.md` as slash commands). That would require Option A
(custom command surface) and a workflow-to-command generator pointed at the
`.agents/` directory, not at `OW_tools/`.

If the goal is the literal "run `.agents/workflows/*.md` as commands," the
proper route is:
1. Option A custom command surface in jcode client code (recommendation in
   doc 03, §Recommendation).
2. A generator that converts `.agents/workflows/<name>.md` → command file
   with `source` + `source_sha256` (doc 04, §1).
3. The global `pre_tool` dispatcher (doc 05, §3) for enforcement.
4. OW_tools MCP server as a **complementary** tool provider for the
   enforceable steps *within* those workflows (e.g. "resolve CI" →
   `mcp__ow_tools__resolve_ci`, "allocate next number" →
   `mcp__ow_tools__next_number`).

---

## 8. Related working implementation (2026-09-18)

A narrower, real instantiation of this design exists and has been verified
against jcode's own client: `temp/mcp/ow_createspr/server.py` implements the
createSPR2 workflow (not the full OW_tools fan-out) as 11 tools over stdio.

Evidence it produces, which resolves UNVERIFIED item 1 below:

- The server is hand-rolled stdlib Python, no `fastmcp`/`mcp` SDK. Its
  `tools/list` replies use the camelCase `inputSchema` key, which is what
  `McpToolDef` requires (`crates/jcode-base/src/mcp/protocol.rs:134-140`), and jcode accepted it.
- Registered in `~/.jcode/mcp.json` under `mcpServers.ow_createspr`, then
  `{"action": "reload"}` reported `Connected: 1/1` and listed all 11 tools.
  So jcode's client consumes a stdlib server's definitions directly, and the
  SDK question in item 1 is moot for this shape.
- The naming that actually reaches the model is `mcp__<server>__<tool>`, so the
  `ow_tools__` prefix proposed in §3 Step 3 is redundant: the server name
  already namespaces it.

---

## UNVERIFIED items

1. **Python SDK compatibility**: Whether `fastmcp` or the `mcp` PyPI package
   produces exactly the JSON-RPC 2.0 format that jcode's `McpToolDef`
   (`crates/jcode-base/src/mcp/protocol.rs:134-140`) consumes is UNVERIFIED. The struct uses
   `#[serde(rename = "inputSchema")]` — verify that the SDK's tool definition
   output uses the same camelCase key.

2. **`ow_actions.py` import path from a sibling package**: The import path
   `from OW_tools.ow_actions import ow_register_ci` requires `OW_tools/` to be
   on `sys.path`. Whether the MCP server can reliably import OW_tools without
   a `pip install -e .` or `PYTHONPATH` manipulation is UNVERIFIED.

3. **`execute()` function signature convention**: The discovery logic
   (`discover_cli.py:84-103`) checks for an `execute` function definition or
   import, but the signature (positional args, return type) varies per module.
   The MCP server's inline import dispatch must handle this variation — the
   exact parameter mapping is UNVERIFIED without reading each module's
   `execute()` signature.

4. **Project-root detection behavior**: `detect_project()` calls
   `git rev-parse --show-toplevel` from CWD. When the MCP server is spawned by
   jcode, the CWD is the project root (per the config), but whether `git`
   resolves correctly in all worktree configurations is UNVERIFIED.

5. **`OW_tools/MANIFEST.json`**: No such file exists as of this writing. The
   generator step (Step 7) would need to either create one or compute hashes
   from the existing file listing. The exact hash strategy is UNVERIFIED and
   deferred to implementation.
