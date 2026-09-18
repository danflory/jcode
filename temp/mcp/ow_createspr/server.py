#!/usr/bin/env python3
"""ow_createspr — a stdlib-only stdio MCP server exposing Overwatch's
/createSPR2 procedure as MCP tools.

Design notes
------------
jcode's MCP client speaks stdio JSON-RPC 2.0 with only `initialize`,
`tools/list`, and `tools/call` (no prompts, no resources, no elicitation) —
see crates/jcode-base/src/mcp/protocol.rs:8 (JsonRpcRequest) and
crates/jcode-base/src/mcp/protocol.rs:150-166 (ToolCallParams/ToolCallResult/
ContentBlock), and crates/jcode-base/src/mcp/protocol.rs:190 (McpServerConfig
is stdio-only; http/sse entries are skipped).
createSPR2 itself mandates one tool call per step and several "STOP and report
to the operator" gates (.agents/workflows/createSPR2.md:23 and :26 for the
mechanical-relay contract, :56 for the Phase 0 TP-gap STOP, :133 for the final
STOP). With no elicitation channel, those gates become *return values*: each
tool returns a structured JSON record and, where the workflow gates, a
`gate` object telling the caller that operator input is required before the
next step.

DRY-RUN IS THE DEFAULT. Every mutating tool takes `dry_run` (default true).
Read-only tools always execute. In dry_run a mutating tool either (a) returns
the exact command it *would* run without running it, or (b) for the scaffold,
runs the real command but sandboxed into scratch with an explicit artifact id.

Only the Python standard library is used.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SERVER_NAME = "ow_createspr"
SERVER_VERSION = "0.1.0"

DEFAULT_OW_REPO = "/home/d/dev_env/clones/Overwatch"
DEFAULT_TIMEOUT = 120.0

# Read-only db_write.py subcommands this server is willing to dispatch.
READ_ONLY_DB_COMMANDS = {
    "lookup_ci",
    "query_ci_by_id",
    "query_ci_by_path",
    "query_ci_active",
    "query_test_execs",
    "query_ci_tags",
    "query_links",
    "query_schema",
    "query_efsm_path",
    "query_lessons",
    "query_actions",
}

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def ow_repo_root(args: dict[str, Any]) -> Path:
    root = args.get("ow_repo_root") or os.environ.get("OW_REPO_ROOT") or DEFAULT_OW_REPO
    return Path(root).expanduser().resolve()


def scratch_dir(args: dict[str, Any]) -> Path:
    base = args.get("scratch_dir") or os.environ.get("JCODE_SCRATCH_DIR")
    if not base:
        base = str(Path.home() / ".jcode" / "scratch")
    return Path(base).expanduser().resolve()


def timeout_for(args: dict[str, Any]) -> float:
    raw = args.get("timeout_secs") or os.environ.get("OW_CMD_TIMEOUT") or DEFAULT_TIMEOUT
    try:
        return max(1.0, float(raw))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT


def is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def parse_json_output(text: str) -> tuple[Any, str | None]:
    """Best-effort parse of a tool's stdout as JSON.

    Returns (parsed, error). Several OW tools print leading log lines before
    their JSON payload, so we try whole-text first, then scan lines backwards
    for the first line/brace block that parses.
    """
    stripped = text.strip()
    if not stripped:
        return None, "empty stdout"
    try:
        return json.loads(stripped), None
    except json.JSONDecodeError:
        pass
    # Try progressively: last JSON object embedded in the stream.
    for start in range(len(stripped)):
        if stripped[start] not in "{[":
            continue
        try:
            return json.loads(stripped[start:]), None
        except json.JSONDecodeError:
            continue
    return None, "stdout was not parseable as JSON"


def run_cmd(
    argv: list[str],
    cwd: Path,
    timeout: float,
) -> dict[str, Any]:
    """Run a command non-interactively and return a structured record."""
    record: dict[str, Any] = {
        "command": " ".join(argv),
        "argv": argv,
        "cwd": str(cwd),
    }
    if not cwd.is_dir():
        record.update({"status": "error", "error": f"cwd does not exist: {cwd}"})
        return record
    started = time.time()
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        record.update(
            {
                "status": "error",
                "error": f"timeout after {timeout}s",
                "stdout": (exc.stdout or ""),
                "stderr": (exc.stderr or ""),
            }
        )
        return record
    except OSError as exc:  # missing interpreter etc.
        record.update({"status": "error", "error": f"OSError: {exc}"})
        return record
    record["duration_secs"] = round(time.time() - started, 3)
    record["exit_code"] = proc.returncode
    record["stdout"] = proc.stdout
    record["stderr"] = proc.stderr
    parsed, perr = parse_json_output(proc.stdout)
    record["parsed"] = parsed
    record["parse_error"] = perr
    if proc.returncode != 0:
        record["status"] = "error"
        record["error"] = f"non-zero exit {proc.returncode}"
    elif parsed is None:
        record["status"] = "error"
        record["error"] = f"exit 0 but output unparseable: {perr}"
    else:
        record["status"] = "ok"
    return record


def list_files(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out.append(str(p))
    return out


def read_frontmatter_field(path: Path, field: str) -> str | None:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return None
    for line in m.group(1).split("\n"):
        line = line.strip()
        if line.startswith(field + ":"):
            return line.partition(":")[2].strip().strip('"').strip("'")
    return None


def now_stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def extract_ci_rows(rec: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the JSON CI rows a db_write read command emits.

    db_write.py prints its `{"status": ..., "command": ...}` envelope on stdout
    and the actual rows as a JSON array on stderr (e.g. query_ci_by_path), so we
    scan both streams for the first JSON array of objects.
    """
    for stream in ("stderr", "stdout"):
        text = rec.get(stream) or ""
        if not text.strip():
            continue
        parsed, _ = parse_json_output(text)
        if isinstance(parsed, list):
            return [r for r in parsed if isinstance(r, dict)]
    return []


# Sandbox driver for dry_run scaffolding.
#
# The `scaffold-folder` CLI cannot target a directory outside the repo: after
# writing the files it calls _register_file(), which does
# file_path.relative_to(project_root) and raises ValueError (OW_tools/
# praca_scaffold/cli.py:252 -> cli.py:53). It also auto-registers through the
# UDRS subscriber / daemon, which would create governed state. For dry_run we
# therefore call the generator directly, skipping registration entirely.
SANDBOX_SCAFFOLD_DRIVER = r"""
import json, sys
from pathlib import Path

spec = json.loads(sys.argv[1])
root = Path(spec["project_root"])
sys.path.insert(0, str(root))
from OW_tools.praca_scaffold import generator

try:
    created = generator.scaffold_folder(
        base_type=spec["base_type"],
        artifact_id=spec["artifact_id"],
        parent=spec["parent"],
        title=spec["title"],
        target_dir=Path(spec["target_dir"]),
        domain=spec["domain"],
        author=spec["author"],
        project_root=root,
        severity=spec["severity"],
    )
    print(json.dumps({
        "status": "success",
        "created_files": [str(f) for f in created],
        "registration": "skipped (dry-run sandbox)",
    }))
except Exception as exc:
    print(json.dumps({
        "status": "error",
        "error": f"{type(exc).__name__}: {exc}",
    }))
    sys.exit(1)
"""


# ---------------------------------------------------------------------------
# tool implementations
# ---------------------------------------------------------------------------


def tool_createspr2_plan(args: dict[str, Any]) -> dict[str, Any]:
    """Static description of the decomposed procedure: no side effects."""
    steps = [
        {
            "step": "0",
            "tool": "ow_update_author",
            "purpose": "git author provenance enrichment",
            "mutates": True,
        },
        {
            "step": "0.5",
            "tool": "ow_resolve_parent",
            "purpose": "resolve parent UDRS id (never guess)",
            "mutates": False,
        },
        {
            "step": "0/Phase 0",
            "tool": "(agent reasoning + ow_query_ci)",
            "purpose": "TP gap investigation V-1..V-6",
            "gate": {
                "kind": "operator_stop",
                "reason": "createSPR2 Phase 0 step 0e requires STOP and operator report",
                "required_inputs": ["tp_gap_category", "tp_gap_reference"],
            },
            "mutates": False,
        },
        {
            "step": "1",
            "tool": "(agent)",
            "purpose": "set change_class / lesson_key",
            "gate": {
                "kind": "operator_input",
                "required_inputs": ["change_class", "lesson_key"],
            },
            "mutates": False,
        },
        {
            "step": "2",
            "tool": "ow_scaffold_spr",
            "purpose": "scaffold the SPR folder",
            "mutates": True,
        },
        {
            "step": "2.5",
            "tool": "ow_backpatch_parent",
            "purpose": "backpatch sub-document parents to the anchor id",
            "mutates": True,
        },
        {
            "step": "2.6",
            "tool": "ow_register_subdocs",
            "purpose": "register every scaffolded .md as a CI (ow_write_ci)",
            "mutates": True,
        },
        {
            "step": "2b",
            "tool": "ow_upsert_praca",
            "purpose": "register PRACA metadata",
            "mutates": True,
        },
        {
            "step": "3",
            "tool": "ow_populate_success_criteria",
            "purpose": "populate success criteria per VCL row",
            "mutates": True,
        },
        {
            "step": "4",
            "tool": "ow_frontmatter_sweep",
            "purpose": "folder frontmatter sweep FM-1..FM-5",
            "mutates": False,
        },
        {
            "step": "end",
            "tool": "(agent)",
            "purpose": "final operator report",
            "gate": {"kind": "operator_stop", "reason": "createSPR2 END"},
            "mutates": False,
        },
    ]
    return {
        "status": "ok",
        "summary": (
            "Stepwise decomposition: createSPR2 is explicitly one-tool-per-step "
            "with mandatory self-verification, and jcode's MCP client has no "
            "elicitation channel, so operator STOP gates are returned as data."
        ),
        "dry_run_default": True,
        "steps": steps,
        "notes": [
            "Steps with mutates=True are refused unless dry_run=false is passed.",
            "Gate objects must be surfaced to the operator verbatim.",
        ],
    }


def _resolve_summary(via: str, rec: dict[str, Any]) -> dict[str, Any]:
    rows = extract_ci_rows(rec)
    ids = [r.get("id") for r in rows if isinstance(r.get("id"), int)]
    if rec["status"] != "ok":
        status = "error"
    elif not rows:
        status = "not_found"
    elif len(ids) == 1:
        status = "ok"
    else:
        status = "ambiguous"
    return {
        "status": status,
        "via": via,
        "parent_id": ids[0] if len(ids) == 1 else None,
        "candidate_ids": ids,
        "rows": rows,
        "result": rec,
    }


def tool_resolve_parent(args: dict[str, Any]) -> dict[str, Any]:
    root = ow_repo_root(args)
    parent_path = args.get("parent_path")
    parent_type = args.get("parent_type")
    parent_id = args.get("parent_id")
    timeout = timeout_for(args)

    if parent_id is not None:
        rec = run_cmd(
            ["python3", "OW_tools/db_write.py", "query_ci_by_id", "--ci-id", str(parent_id)],
            root,
            timeout,
        )
        return _resolve_summary("query_ci_by_id", rec)

    if parent_path:
        rec = run_cmd(
            ["python3", "OW_tools/db_write.py", "query_ci_by_path", "--path", str(parent_path)],
            root,
            timeout,
        )
        return _resolve_summary("query_ci_by_path", rec)

    if parent_type:
        rec = run_cmd(
            ["python3", "OW_tools/db_write.py", "lookup_ci", "--type", str(parent_type)],
            root,
            timeout,
        )
        return _resolve_summary("lookup_ci", rec)

    return {
        "status": "error",
        "error": "provide one of parent_id, parent_path, or parent_type",
    }


def tool_query_ci(args: dict[str, Any]) -> dict[str, Any]:
    root = ow_repo_root(args)
    command = args.get("command")
    if command not in READ_ONLY_DB_COMMANDS:
        return {
            "status": "error",
            "error": (
                f"command {command!r} is not an allowlisted read-only db_write subcommand"
            ),
            "allowed": sorted(READ_ONLY_DB_COMMANDS),
        }
    extra = args.get("args") or []
    if not isinstance(extra, list) or not all(isinstance(x, str) for x in extra):
        return {"status": "error", "error": "args must be a list of strings"}
    rec = run_cmd(["python3", "OW_tools/db_write.py", command, *extra], root, timeout_for(args))
    return {"status": rec["status"], "result": rec}


def tool_db_probe(args: dict[str, Any]) -> dict[str, Any]:
    """Read-only reachability probe, reported honestly."""
    root = ow_repo_root(args)
    timeout = min(timeout_for(args), 30.0)
    probes: dict[str, Any] = {}

    probes["ow_repo_root"] = {"path": str(root), "exists": root.is_dir()}

    # Daemon socket probe (no writes): look for the Overwatch daemon socket.
    sock_candidates = [
        Path(f"/run/user/{os.getuid()}/overwatch.sock"),
        Path(f"/run/user/{os.getuid()}/ow-daemon.sock"),
        Path("/tmp/overwatch.sock"),
    ]
    probes["daemon_socket"] = {
        "candidates": [
            {"path": str(p), "exists": p.exists(), "is_socket": p.is_socket()}
            for p in sock_candidates
        ],
        "verified": False,
        "note": "candidate paths are UNVERIFIED; socket presence != daemon healthy",
    }

    # Credential presence (never read secrets, only whether the file exists).
    cred_candidates = [
        root / "overwatch" / ".env",
        Path.home() / ".overwatch" / "credentials.json",
    ]
    probes["credentials"] = {
        "candidates": [{"path": str(p), "exists": p.exists()} for p in cred_candidates],
        "verified": False,
        "note": "existence does not imply working governed DB access",
    }

    # Real read-only query against the governed DB.
    rec = run_cmd(
        [
            "python3",
            "OW_tools/db_write.py",
            "query_ci_by_path",
            "--path",
            str(args.get("probe_path") or "docs/praca/RFC/closed/"),
            "--limit",
            "1",
        ],
        root,
        timeout,
    )
    probes["governed_db_query"] = rec
    probes["governed_db_reachable"] = rec["status"] == "ok"

    probes["status"] = "ok"
    probes["conclusion"] = (
        "governed DB read succeeded (dry-run writes still never touch it)"
        if probes["governed_db_reachable"]
        else "governed DB read FAILED; a real (dry_run=false) invocation cannot proceed"
    )
    return probes


def tool_update_author(args: dict[str, Any]) -> dict[str, Any]:
    dry_run = bool(args.get("dry_run", True))
    root = ow_repo_root(args)
    session = args.get("session_id")
    praca = args.get("praca")
    phase = args.get("phase", "scaffolding")
    if session is None or praca is None:
        return {
            "status": "error",
            "error": "session_id and praca are required",
            "note": "OW_tools/session_lifecycle/update_author.py takes --sr-id, not --session",
        }
    argv = [
        "python3",
        "OW_tools/session_lifecycle/update_author.py",
        "--sr-id",
        str(session),
        "--praca",
        str(praca),
        "--phase",
        str(phase),
    ]
    if dry_run:
        return {
            "status": "dry_run",
            "planned_command": " ".join(argv),
            "cwd": str(root),
            "mutates": "git author environment enrichment",
        }
    rec = run_cmd(argv, root, timeout_for(args))
    return {"status": rec["status"], "result": rec}


def tool_scaffold_spr(args: dict[str, Any]) -> dict[str, Any]:
    """scaffold-folder, sandboxed when dry_run."""
    dry_run = bool(args.get("dry_run", True))
    root = ow_repo_root(args)
    base_type = args.get("base_type", "spr")
    title = args.get("title")
    if not title:
        return {"status": "error", "error": "title is required"}
    parent = args.get("parent", "UNASSIGNED")
    artifact_id = args.get("artifact_id")
    target_dir = args.get("target_dir")
    timeout = timeout_for(args)

    warnings: list[str] = []

    if dry_run and not artifact_id:
        return {
            "status": "error",
            "error": (
                "dry_run requires an explicit artifact_id so no governed number "
                "allocation (next_number) happens"
            ),
            "hint": "pass artifact_id e.g. SPR-DRYRUN-001, or dry_run=false to allocate",
        }

    if dry_run:
        if target_dir:
            tpath = Path(target_dir)
            if not tpath.is_absolute():
                tpath = (root / tpath).resolve()
            if is_inside(tpath, root):
                return {
                    "status": "error",
                    "error": (
                        "dry_run refuses a target_dir inside the Overwatch repo: "
                        f"{tpath}. Use a scratch path."
                    ),
                }
            sandbox = tpath
        else:
            sandbox = scratch_dir(args) / "ow_createspr" / f"{now_stamp()}_{artifact_id}"
            warnings.append("dry_run: target_dir defaulted to scratch sandbox")
        if parent == "UNASSIGNED":
            warnings.append(
                "parent UNASSIGNED: resolve it with ow_resolve_parent before a real run"
            )
    else:
        if not target_dir:
            return {
                "status": "error",
                "error": (
                    "dry_run=false requires an explicit target_dir (refusing to "
                    "guess a governed docs/praca/SPR path)"
                ),
            }
        tpath = Path(target_dir)
        sandbox = tpath if tpath.is_absolute() else (root / tpath)
        warnings.append("REAL RUN: this writes governed state under the Overwatch repo")

    sandbox.mkdir(parents=True, exist_ok=True)

    if dry_run:
        spec = {
            "project_root": str(root),
            "base_type": str(base_type),
            "artifact_id": str(artifact_id),
            "parent": str(parent),
            "title": str(title),
            "target_dir": str(sandbox),
            "domain": str(args.get("domain") or "governance"),
            "author": str(args.get("author") or "operator"),
            "severity": args.get("severity"),
        }
        argv = ["python3", "-c", SANDBOX_SCAFFOLD_DRIVER, json.dumps(spec)]
    else:
        argv = [
            "python3",
            "-m",
            "OW_tools.praca_scaffold",
            "scaffold-folder",
            "--base-type",
            str(base_type),
            "--artifact-id",
            str(artifact_id),
            "--parent",
            str(parent),
            "--title",
            str(title),
            "--target-dir",
            str(sandbox),
        ]
        if args.get("domain"):
            argv += ["--domain", str(args["domain"])]
        if args.get("severity") is not None:
            argv += ["--severity", str(args["severity"])]
        if args.get("prefix"):
            argv += ["--prefix", str(args["prefix"])]

    before = set(list_files(sandbox))
    rec = run_cmd(argv, root, timeout)
    after = set(list_files(sandbox))
    created = sorted(after - before)

    out: dict[str, Any] = {
        "status": rec["status"],
        "dry_run": dry_run,
        "sandbox": str(sandbox),
        "warnings": warnings,
        "result": rec,
        "created_files": created,
    }
    if rec["status"] != "ok":
        out["error"] = rec.get("error")
    else:
        parsed = rec.get("parsed") or {}
        if isinstance(parsed, dict):
            out["tool_status"] = parsed.get("status")
            out["created_files_reported"] = parsed.get("created_files")
            if parsed.get("registration"):
                out["registration"] = parsed["registration"]
            named_anchor = [p for p in created if Path(p).name == f"{artifact_id}.md"]
            anchors = named_anchor or [p for p in created if Path(p).parent == sandbox]
            if anchors:
                anchor = Path(anchors[0])
                out["anchor_file"] = str(anchor)
                out["anchor_id"] = read_frontmatter_field(anchor, "id")
        out["self_check"] = {
            "tool_status_is_success": out.get("tool_status") == "success",
            "created_file_count": len(created),
        }
    return out


def tool_backpatch_parent(args: dict[str, Any]) -> dict[str, Any]:
    dry_run = bool(args.get("dry_run", True))
    root = ow_repo_root(args)
    folder = args.get("folder")
    anchor_id = args.get("anchor_id")
    if not folder:
        return {"status": "error", "error": "folder is required"}
    if anchor_id is None:
        return {"status": "error", "error": "anchor_id is required (resolve it, never guess)"}
    argv = [
        "python3",
        "-m",
        "OW_tools.praca_scaffold",
        "backpatch-parent",
        "--dir",
        str(folder),
        "--anchor-id",
        str(anchor_id),
    ]
    if args.get("extra_args"):
        argv += [str(x) for x in args["extra_args"]]
    if dry_run:
        return {
            "status": "dry_run",
            "planned_command": " ".join(argv),
            "cwd": str(root),
            "mutates": "sub-document frontmatter parent/ci_impacted",
        }
    rec = run_cmd(argv, root, timeout_for(args))
    return {"status": rec["status"], "result": rec}


def tool_register_subdocs(args: dict[str, Any]) -> dict[str, Any]:
    dry_run = bool(args.get("dry_run", True))
    root = ow_repo_root(args)
    paths = args.get("paths")
    folder = args.get("folder")
    if not paths and folder:
        fpath = Path(folder)
        if not fpath.is_absolute():
            fpath = root / fpath
        if is_inside(fpath, root):
            paths = sorted(str(p) for p in fpath.rglob("*.md"))
    if not paths or not isinstance(paths, list):
        return {
            "status": "error",
            "error": "provide paths (list) or a folder containing .md sub-documents",
        }
    timeout = timeout_for(args)
    results = []
    for p in paths:
        argv = ["python3", "OW_tools/db_write.py", "ow_write_ci", "--path", str(p)]
        if dry_run:
            results.append(
                {
                    "path": str(p),
                    "status": "dry_run",
                    "planned_command": " ".join(argv),
                }
            )
        else:
            rec = run_cmd(argv, root, timeout)
            entry: dict[str, Any] = {"path": str(p), "status": rec["status"], "result": rec}
            abs_p = Path(p) if Path(p).is_absolute() else root / p
            entry["id_after"] = read_frontmatter_field(abs_p, "id")
            entry["parent_after"] = read_frontmatter_field(abs_p, "parent")
            results.append(entry)
    any_err = any(r["status"] == "error" for r in results)
    return {
        "status": "error" if any_err else ("dry_run" if dry_run else "ok"),
        "dry_run": dry_run,
        "count": len(results),
        "results": results,
    }


def tool_upsert_praca(args: dict[str, Any]) -> dict[str, Any]:
    dry_run = bool(args.get("dry_run", True))
    root = ow_repo_root(args)
    artifact_id = args.get("artifact_id")
    domain = args.get("domain")
    severity = args.get("severity")
    if artifact_id is None or domain is None or severity is None:
        return {"status": "error", "error": "artifact_id, domain, severity are required"}
    argv = [
        "python3",
        "OW_tools/db_write.py",
        "upsert_praca",
        "--artifact-id",
        str(artifact_id),
        "--domain",
        str(domain),
        "--severity",
        str(severity),
    ]
    if args.get("ci_ids"):
        ci = args["ci_ids"]
        if isinstance(ci, list):
            ci = ",".join(str(x) for x in ci)
        argv += ["--ci-ids", str(ci)]
    if args.get("project"):
        argv += ["--project", str(args["project"])]
    if dry_run:
        return {"status": "dry_run", "planned_command": " ".join(argv), "cwd": str(root)}
    rec = run_cmd(argv, root, timeout_for(args))
    return {"status": rec["status"], "result": rec}


def _criteria_from_anchor(anchor_path: Path) -> list[str]:
    """Parse the anchor's `## Verification Completion` table.

    Real anchors use `| N | Criterion | Status |` rows (e.g.
    docs/praca/SPR/SPR-1105.md:101-109); createSPR2.md Step 3 refers to them as
    `V-N` rows. Accept a numeric or `V-N` first column and take the second.
    """
    try:
        text = anchor_path.read_text(errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    start: int | None = None
    for i, line in enumerate(lines):
        if re.match(r"^#{1,6}\s+Verification Completion", line.strip()):
            start = i + 1
            break
    section = lines[start:] if start is not None else lines

    rows: list[str] = []
    for line in section:
        if start is not None and re.match(r"^#{1,6}\s", line.strip()):
            break  # next heading ends the section
        m = re.match(r"^\s*\|\s*(V-\d+|\d+)\s*\|\s*(.+?)\s*\|", line)
        if not m:
            continue
        desc = m.group(2).strip()
        if not desc or desc.lower() in ("criterion", "criteria", "description"):
            continue
        rows.append(desc)
    return rows


def tool_populate_success_criteria(args: dict[str, Any]) -> dict[str, Any]:
    dry_run = bool(args.get("dry_run", True))
    root = ow_repo_root(args)
    ci_id = args.get("ci_id")
    criteria = args.get("criteria")
    anchor_path = args.get("anchor_path")
    if criteria is None and anchor_path:
        p = Path(anchor_path)
        if not p.is_absolute():
            p = root / p
        criteria = _criteria_from_anchor(p)
    if not criteria or not isinstance(criteria, list):
        return {
            "status": "error",
            "error": "provide criteria (list of strings) or anchor_path with a VCL table",
        }
    if ci_id is None and not dry_run:
        return {"status": "error", "error": "ci_id (anchor UDRS id) is required for a real run"}
    timeout = timeout_for(args)
    results = []
    for i, desc in enumerate(criteria, start=1):
        argv = [
            "python3",
            "OW_tools/db_write.py",
            "upsert_sc",
            "--ci-id",
            str(ci_id),
            "--sc-num",
            str(i),
            "--desc",
            str(desc),
            "--checked",
            "false",
        ]
        if dry_run:
            results.append({"sc_num": i, "status": "dry_run", "planned_command": " ".join(argv)})
        else:
            rec = run_cmd(argv, root, timeout)
            results.append({"sc_num": i, "status": rec["status"], "result": rec})
    any_err = any(r["status"] == "error" for r in results)
    return {
        "status": "error" if any_err else ("dry_run" if dry_run else "ok"),
        "dry_run": dry_run,
        "count": len(results),
        "results": results,
    }


def tool_frontmatter_sweep(args: dict[str, Any]) -> dict[str, Any]:
    root = ow_repo_root(args)
    folder = args.get("folder")
    if not folder:
        return {"status": "error", "error": "folder is required"}
    rec = run_cmd(
        ["python3", "-m", "OW_tools.check_folder_frontmatter", str(folder)],
        root,
        timeout_for(args),
    )
    # This tool exits 1 on violations and writes its JSON error envelope to
    # stderr (stdout stays empty), so inspect both streams.
    ok_exit = rec.get("exit_code", 1)
    parsed = rec.get("parsed")
    if parsed is None:
        parsed, _ = parse_json_output(rec.get("stderr", "") or "")
    violations: list[str] = []
    if isinstance(parsed, dict):
        err = parsed.get("error")
        if isinstance(err, dict):
            details = err.get("details") or {}
            if isinstance(details, dict):
                violations = list(details.get("violations") or [])
    out: dict[str, Any] = {
        "result": rec,
        "parsed": parsed,
        "clean": ok_exit == 0,
        "violations_present": ok_exit == 1,
        "violations": violations,
    }
    out["status"] = "ok" if ok_exit in (0, 1) else "error"
    return out


# ---------------------------------------------------------------------------
# tool registry / schemas
# ---------------------------------------------------------------------------

DRY_RUN_PROP = {
    "type": "boolean",
    "description": "When true (default) no governed state is written.",
}

COMMON_PROPS = {
    "ow_repo_root": {
        "type": "string",
        "description": f"Overwatch repo root (default {DEFAULT_OW_REPO}).",
    },
    "timeout_secs": {"type": "number", "description": "Per-command timeout in seconds."},
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "ow_createspr2_plan",
        "description": (
            "Return the createSPR2 procedure decomposed into this server's tools, "
            "including which steps are operator gates. No side effects."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "ow_db_probe",
        "description": (
            "Read-only probe of Overwatch daemon socket, credential-file presence, "
            "and governed DB reachability. Reports honestly; never writes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "probe_path": {"type": "string", "description": "storage_path to probe."},
                **COMMON_PROPS,
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "ow_resolve_parent",
        "description": (
            "createSPR2 step 0.5: resolve the parent CI strictly through the DB "
            "(query_ci_by_id / query_ci_by_path / lookup_ci). Never guesses."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "parent_id": {"type": "integer"},
                "parent_path": {"type": "string"},
                "parent_type": {"type": "string", "enum": ["workflow", "rfc", "spr", "car"]},
                **COMMON_PROPS,
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "ow_query_ci",
        "description": "Dispatch an allowlisted read-only db_write.py subcommand.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "enum": sorted(READ_ONLY_DB_COMMANDS)},
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Raw CLI args passed through, e.g. ['--type','workflow'].",
                },
                **COMMON_PROPS,
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
    {
        "name": "ow_update_author",
        "description": "createSPR2 step 0: enrich git author with PRACA id and phase.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Maps to update_author --sr-id."},
                "praca": {"type": "string"},
                "phase": {"type": "string", "default": "scaffolding"},
                "dry_run": DRY_RUN_PROP,
                **COMMON_PROPS,
            },
            "required": ["session_id", "praca"],
            "additionalProperties": False,
        },
    },
    {
        "name": "ow_scaffold_spr",
        "description": (
            "createSPR2 step 2: run praca_scaffold scaffold-folder. In dry_run the "
            "real command runs sandboxed: artifact_id must be explicit and target_dir "
            "must be outside the Overwatch repo (defaults to scratch)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "base_type": {"type": "string", "enum": ["spr", "rfc", "car"], "default": "spr"},
                "artifact_id": {"type": "string", "description": "Required when dry_run."},
                "parent": {
                    "type": "string",
                    "description": "Parent UDRS integer id or UNASSIGNED.",
                    "default": "UNASSIGNED",
                },
                "target_dir": {"type": "string"},
                "domain": {"type": "string"},
                "severity": {"type": "integer", "minimum": 1, "maximum": 5},
                "prefix": {"type": "string"},
                "scratch_dir": {"type": "string"},
                "dry_run": DRY_RUN_PROP,
                **COMMON_PROPS,
            },
            "required": ["title"],
            "additionalProperties": False,
        },
    },
    {
        "name": "ow_backpatch_parent",
        "description": "createSPR2 step 2.5: backpatch sub-document parents to the anchor UDRS id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "folder": {"type": "string"},
                "anchor_id": {"type": "integer"},
                "extra_args": {"type": "array", "items": {"type": "string"}},
                "dry_run": DRY_RUN_PROP,
                **COMMON_PROPS,
            },
            "required": ["folder", "anchor_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "ow_register_subdocs",
        "description": (
            "createSPR2 step 2.6: register every scaffolded .md as a CI via "
            "ow_write_ci, then re-read id/parent from disk."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}},
                "folder": {"type": "string", "description": "Alternative: glob *.md under it."},
                "dry_run": DRY_RUN_PROP,
                **COMMON_PROPS,
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "ow_upsert_praca",
        "description": "createSPR2 step 2b: register PRACA metadata.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "artifact_id": {"type": "string"},
                "domain": {"type": "string"},
                "severity": {"type": "integer", "minimum": 1, "maximum": 5},
                "ci_ids": {"type": "array", "items": {"type": "integer"}},
                "project": {"type": "string"},
                "dry_run": DRY_RUN_PROP,
                **COMMON_PROPS,
            },
            "required": ["artifact_id", "domain", "severity"],
            "additionalProperties": False,
        },
    },
    {
        "name": "ow_populate_success_criteria",
        "description": (
            "createSPR2 step 3: upsert_sc per VCL row. Parses the anchor's "
            "`## Verification Completion` table when given anchor_path."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ci_id": {"type": "integer", "description": "Anchor UDRS id."},
                "anchor_path": {"type": "string", "description": "Path to the anchor .md."},
                "criteria": {"type": "array", "items": {"type": "string"}},
                "dry_run": DRY_RUN_PROP,
                **COMMON_PROPS,
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "ow_frontmatter_sweep",
        "description": (
            "createSPR2 step 4: run check_folder_frontmatter on the SPR folder. "
            "Exit 1 means violations, not a crash."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"folder": {"type": "string"}, **COMMON_PROPS},
            "required": ["folder"],
            "additionalProperties": False,
        },
    },
]

HANDLERS = {
    "ow_createspr2_plan": tool_createspr2_plan,
    "ow_db_probe": tool_db_probe,
    "ow_resolve_parent": tool_resolve_parent,
    "ow_query_ci": tool_query_ci,
    "ow_update_author": tool_update_author,
    "ow_scaffold_spr": tool_scaffold_spr,
    "ow_backpatch_parent": tool_backpatch_parent,
    "ow_register_subdocs": tool_register_subdocs,
    "ow_upsert_praca": tool_upsert_praca,
    "ow_populate_success_criteria": tool_populate_success_criteria,
    "ow_frontmatter_sweep": tool_frontmatter_sweep,
}


# ---------------------------------------------------------------------------
# JSON-RPC / MCP plumbing
# ---------------------------------------------------------------------------


def make_result(payload: dict[str, Any], is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, indent=2, default=str)}],
        "isError": is_error,
    }


def rpc_error(req_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def handle(req: dict[str, Any]) -> dict[str, Any] | None:
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params") or {}

    # Notifications (no id) get no response.
    if "id" not in req:
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        handler = HANDLERS.get(name)
        if handler is None:
            return rpc_error(req_id, -32602, f"unknown tool: {name}")
        if not isinstance(arguments, dict):
            return rpc_error(req_id, -32602, "arguments must be an object")
        try:
            payload = handler(arguments)
        except Exception as exc:  # never crash the server on one call
            payload = {
                "status": "error",
                "error": f"unhandled {type(exc).__name__}: {exc}",
            }
        is_error = payload.get("status") == "error"
        return {"jsonrpc": "2.0", "id": req_id, "result": make_result(payload, is_error)}

    if method in ("ping",):
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    return rpc_error(req_id, -32601, f"method not found: {method}")


def main() -> None:
    # Any diagnostics go to stderr; stdout carries only JSON-RPC frames.
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            sys.stdout.write(
                json.dumps(rpc_error(None, -32700, f"parse error: {exc}")) + "\n"
            )
            sys.stdout.flush()
            continue
        resp = handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, default=str) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
