#!/usr/bin/env python3
"""Smoke test for the ow_createspr MCP server.

Pipes a scripted MCP handshake (initialize + tools/list + several tools/call
requests) into server.py and asserts on the raw JSON-RPC replies.

Usage:
    python3 smoke_test.py [--keep]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVER = HERE / "server.py"
OW_REPO = os.environ.get("OW_REPO_ROOT", "/home/d/dev_env/clones/Overwatch")
SCRATCH = Path(os.environ.get("JCODE_SCRATCH_DIR", Path.home() / ".jcode" / "scratch"))


def build_requests(sandbox: Path) -> list[dict]:
    return [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "smoke-test", "version": "0.1.0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "ow_createspr2_plan", "arguments": {}},
        },
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "ow_scaffold_spr",
                "arguments": {
                    "title": "Smoke Test Dry Run",
                    "artifact_id": "SPR-DRYRUN-SMOKE",
                    "parent": "UNASSIGNED",
                    "target_dir": str(sandbox),
                    "domain": "governance",
                    "severity": "3",
                },
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "ow_register_subdocs",
                "arguments": {
                    "paths": ["docs/praca/SPR/SPR-999_Example/README.md"],
                },
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "ow_frontmatter_sweep", "arguments": {"folder": str(sandbox)}},
        },
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "ow_scaffold_spr",
                "arguments": {"title": "No artifact id"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {"name": "does_not_exist", "arguments": {}},
        },
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "ow_resolve_parent",
                "arguments": {
                    "parent_path": "docs/praca/RFC/closed/RFC-WF-022_closeSPR_Deferral_Pre-Scan.md"
                },
            },
        },
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="keep the sandbox dir")
    args = ap.parse_args()

    sandbox = SCRATCH / "ow_createspr_smoke" / "run"
    if sandbox.exists() and not args.keep:
        import shutil

        shutil.rmtree(sandbox)
    sandbox.mkdir(parents=True, exist_ok=True)

    payload = "\n".join(json.dumps(r) for r in build_requests(sandbox)) + "\n"
    proc = subprocess.run(
        [sys.executable, str(SERVER)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(HERE),
    )
    print(f"server exit code: {proc.returncode}")
    if proc.stderr.strip():
        print("stderr:", proc.stderr.strip())

    replies = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    print(f"raw replies: {len(replies)}")
    by_id = {r.get("id"): r for r in replies}

    failures: list[str] = []
    if 1 not in by_id:
        failures.append("no initialize reply")
    if 2 not in by_id:
        failures.append("no tools/list reply")
    else:
        tools = by_id[2]["result"]["tools"]
        print(f"tools: {[t['name'] for t in tools]}")
        if len(tools) != 11:
            failures.append(f"expected 11 tools, got {len(tools)}")
        for t in tools:
            if "inputSchema" not in t or not isinstance(t["inputSchema"], dict):
                failures.append(f"tool {t['name']} missing inputSchema")

    r4 = by_id.get(4, {})
    if r4.get("result", {}).get("isError"):
        failures.append("dry-run scaffold reported isError")
    else:
        body = json.loads(r4["result"]["content"][0]["text"])
        print(f"scaffold status={body['status']} created={len(body['created_files'])}")
        for f in body["created_files"]:
            print("  created:", f)
        if len(body["created_files"]) != 4:
            failures.append(f"expected 4 created files, got {len(body['created_files'])}")

    r5 = by_id.get(5, {})
    if not r5:
        failures.append("no dry-run register reply")
    else:
        body = json.loads(r5["result"]["content"][0]["text"])
        print(f"register dry_run status={body['status']} planned={body['results'][0]['planned_command']}")

    r7 = by_id.get(7, {})
    if not r7 or not r7.get("result", {}).get("isError"):
        failures.append("missing artifact_id in dry_run should be an error")

    r8 = by_id.get(8, {})
    if r8 and "error" not in r8:
        failures.append("unknown tool should return a JSON-RPC error")

    # The server must not respond to notifications.
    if any(r.get("id") is None for r in replies):
        failures.append("server responded to a notification")

    r9 = by_id.get(9, {})
    if not r9:
        failures.append("no ow_resolve_parent reply")
    else:
        body = json.loads(r9["result"]["content"][0]["text"])
        print(f"resolve_parent status={body['status']} parent_id={body['parent_id']}")
        if body["status"] == "ok" and not isinstance(body["parent_id"], int):
            failures.append("resolve_parent returned ok without an integer parent_id")
        if body["status"] not in ("ok", "not_found", "ambiguous", "error"):
            failures.append(f"unexpected resolve_parent status {body['status']!r}")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print("\nALL SMOKE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
