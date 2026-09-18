# ow_createspr — MCP server for Overwatch `/createSPR2`

A single-file, **stdlib-only** stdio MCP server that exposes Overwatch's
`/createSPR2` SPR-scaffolding workflow as MCP tools so a jcode agent can drive it
through jcode's MCP client.

- Entry point: `server.py` (Python 3.9+, no third-party dependencies)
- Inspiration (read-only): `/home/d/dev_env/clones/Overwatch/.agents/workflows/createSPR2.md`
- **Dry-run is the default. No governed state is created unless the caller
  explicitly passes `dry_run: false`.**

## Design: why stepwise tools

`createSPR2` is written as a *mechanical relay*: "Each step is exactly ONE tool
invocation" and "A step is only done when it produces a tool RESULT"
(`createSPR2.md:23`, `:26`). The workflow also has hard operator gates
("STOP. Report the TP-gap analysis to the operator and wait." at
`createSPR2.md:56`, and the final STOP at `createSPR2.md:133`).

jcode's MCP client speaks stdio JSON-RPC 2.0 with only `initialize`,
`tools/list`, and `tools/call` — there is no prompts, resources, or elicitation
channel (`crates/jcode-base/src/mcp/protocol.rs:8` JsonRpcRequest,
`:150-166` ToolCallParams/ToolCallResult/ContentBlock). A server therefore
cannot block waiting for an operator.

Consequence: the decomposition is **stepwise, one tool per procedure step**, and
every operator gate becomes a **return value** (`ow_createspr2_plan` lists each
gate as a `gate` object with `required_inputs`). Tools appear to the model as
`mcp__ow_createspr__<tool>`.

## Tools

| Tool | createSPR2 step | Mutates | Notes |
| --- | --- | --- | --- |
| `ow_createspr2_plan` | — | no | Returns the decomposed procedure and its gates. No side effects. |
| `ow_db_probe` | — | no | Read-only: daemon socket candidates, credential-file presence, governed DB read. |
| `ow_resolve_parent` | 0.5 | no | Resolves the parent CI via `query_ci_by_id` / `query_ci_by_path` / `lookup_ci`; extracts the numeric `id`. Never guesses. |
| `ow_query_ci` | any | no | Allowlisted read-only `db_write.py` subcommands. |
| `ow_update_author` | 0 | yes | `session_lifecycle/update_author.py`. Flag is `--sr-id`, not `--session`. |
| `ow_scaffold_spr` | 2 | yes | `praca_scaffold scaffold-folder`. Sandboxed in dry-run (see below). |
| `ow_backpatch_parent` | 2.5 | yes | `praca_scaffold backpatch-parent --dir FOLDER --anchor-id N`. |
| `ow_register_subdocs` | 2.6 | yes | `db_write.py ow_write_ci` per file; re-reads `id`/`parent` from disk after. |
| `ow_upsert_praca` | 2b | yes | `db_write.py upsert_praca`. |
| `ow_populate_success_criteria` | 3 | yes | `db_write.py upsert_sc` per VCL row; parses the anchor's `## Verification Completion` table when given `anchor_path`. |
| `ow_frontmatter_sweep` | 4 | no | `check_folder_frontmatter`; exit 1 = violations, not a crash. |

Requirement coverage: (a) parent resolution → `ow_resolve_parent`; (b) scaffold
→ `ow_scaffold_spr`; (c) sub-document registration → `ow_register_subdocs`;
(d) PRACA metadata → `ow_upsert_praca`; (e) success criteria →
`ow_populate_success_criteria`; (f) frontmatter sweep → `ow_frontmatter_sweep`.

## Dry-run semantics

Every mutating tool takes `dry_run` (default `true`).

- **Read-only tools** (`ow_createspr2_plan`, `ow_db_probe`, `ow_resolve_parent`,
  `ow_query_ci`, `ow_frontmatter_sweep`) always execute.
- **Mutating tools** with `dry_run: true` return the exact command and `cwd`
  they *would* run, without running it.
- **`ow_scaffold_spr`** is the exception: in dry-run it *does* create files, but
  only in a sandbox. Because the `scaffold-folder` CLI cannot safely target a
  directory outside the repo (see Limits), dry-run calls
  `OW_tools.praca_scaffold.generator.scaffold_folder` directly with registration
  skipped. It requires an explicit `artifact_id` (so no `next_number`
  allocation) and refuses a `target_dir` inside the Overwatch repo
  (defaults to `$JCODE_SCRATCH_DIR/ow_createspr/<timestamp>_<id>`).

## Registration snippet

`mcp.snippet.json` in this directory. Install by merging `mcpServers` into
`~/.jcode/mcp.json` (global) or `.jcode/mcp.json` (project). jcode accepts both
`servers` and the canonical Claude Code key `mcpServers`
(`crates/jcode-base/src/mcp/protocol.rs:264-268`). Per-server `timeout_secs`
defaults to 30s (`crates/jcode-base/src/mcp/protocol.rs:229`); the snippet
raises it to 120s because governed DB calls can be slow. Only stdio
(command-based) servers are supported (`:190`).

After installing, restart jcode so the client reconnects. There is no `jcode mcp`
subcommand in this build (`jcode --help` lists none), so confirm connection from
a session (the tools appear as `mcp__ow_createspr__*`).

## Environment

- `OW_REPO_ROOT` — Overwatch repo root (default `/home/d/dev_env/clones/Overwatch`).
  Callers may also pass `ow_repo_root` per call.
- `OW_CMD_TIMEOUT` — per-command timeout in seconds (default 120).
- `JCODE_SCRATCH_DIR` — root for dry-run sandboxes (default `~/.jcode/scratch`).

Commands are always run non-interactively (`stdin=/dev/null`) with the Overwatch
repo as cwd.

## Where createSPR2 is inherently split, and what this server does

`createSPR2` is not a single mechanical sequence. There are three places where
it cannot be driven end-to-end by an MCP server, and the server is explicit
about each:

1. **Operator gates (Phase 0 step 0e; Step 1 change_class/lesson_key; final
   STEP 4 report).** Phase 0 requires the agent to stop and report a TP-gap
   analysis (V-1..V-6, OPF-011 §8) and wait; Step 1 requires the operator to
   choose `change_class` / `lesson_key`. MCP has no elicitation, so these are
   returned as `gate` objects by `ow_createspr2_plan`. The server will not
   fabricate a `tp_gap_category` or a `change_class`.
2. **DB / daemon dependency.** Steps 0, 0.5, 2.6, 2b, 3 write to the governed
   DB; Step 2 posts to the UDRS subscriber and depends on whether the daemon is
   active. `ow_db_probe` reports read reachability honestly and the server never
   pretends a write succeeded: a non-zero exit or unparseable output is always a
   structured error with `status: "error"`.
3. **Two-phase anchor registration (Step 2 / 2.5).** `scaffold-folder`
   registers the anchor immediately only when the UDRS daemon is *inactive*; if
   the daemon is active it defers and prints "anchor registration will occur
   automatically" (`OW_tools/praca_scaffold/cli.py:251-263`). Either way the
   anchor's UDRS id may not exist yet when the sub-documents are written, which
   is why Step 2.5 backpatches parents and Step 2.6 registers each file
   separately. `ow_register_subdocs` re-reads `id:`/`parent:` from disk after
   each upsert so the caller uses the DB-assigned id, as the workflow requires.

## Known limits

- **Out-of-repo `scaffold-folder` is broken upstream.** The CLI, after writing
  files, calls `_register_file()`, which does
  `file_path.relative_to(project_root)` and raises `ValueError` for any target
  outside the repo (`OW_tools/praca_scaffold/cli.py:252` → `cli.py:53`). This
  server therefore never uses the CLI for dry-run sandboxes.
- **Dry-run sandboxes are not registered**, so `ow_frontmatter_sweep` on a
  sandbox reports FM-1/FM-5 violations for empty `id:` and `parent: UNASSIGNED`.
  That is expected, not a bug.
- **`check_folder_frontmatter` prints its violation envelope on stderr** and
  exits 1; `ow_frontmatter_sweep` parses both streams and surfaces the
  violations array.
- **`db_write.py` read commands print their JSON rows on stderr** and a
  `{"status": "success", "command": ...}` envelope on stdout. The server scans
  both streams.
- **Daemon socket paths are UNVERIFIED.** `ow_db_probe` checks a few candidate
  paths and says so; socket presence would not prove a healthy daemon.
- Only `initialize`, `tools/list`, `tools/call`, and `ping` are implemented.
  `notifications/initialized` is accepted and ignored (no reply), as JSON-RPC
  requires.

## Verification

```bash
python3 smoke_test.py
```

Runs a scripted `initialize` + `tools/list` + several `tools/call` requests and
asserts on the raw JSON-RPC replies (schema presence, 11 tools, 4 scaffolded
files, dry-run guards, unknown-tool error, notification silence).
