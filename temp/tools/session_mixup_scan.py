#!/usr/bin/env python3
"""session_mixup_scan.py - Incremental index of jcode SESSION transcripts plus
deterministic detectors for the SPR-0008 "session mix-up" defect class.

Purpose
-------
jcode's SPR-0008 defect class is "client-local session state overrides server
truth": e.g. resuming a session silently rewrites its persisted working_dir
(session t-rex rewritten from clone B to clone A), and /info reports a
client-local stub session instead of the server-bound session. This tool is the
option-2c prototype: a plain-SQLite (stdlib sqlite3) index over jcode SESSION
TRANSCRIPTS (not source code) that REPEATABLY detects evidence of such mix-ups.

Storage
-------
DB: ~/.jcode/cache/session-mixup-index.sqlite3 (override with --db).

Schema (created if missing):
  - files(session_id, path, mtime_ms, size, PRIMARY KEY(session_id, path))
      Incremental invalidation identity is (mtime_ms, size). This is the same
      identity design as jcode's IndexFileSpec (key, mtime_ms, size):
        crates/jcode-app-core/src/tool/session_search_index.rs:69-75
        (struct IndexFileSpec { key, mtime_ms, size })
      and the rebuild/reuse logic at ...:388-400 and stat_ms_size ...:482-495.
  - messages(session_id, msg_idx, role, ts, sha256, text, embedding BLOB,
             model_id, PRIMARY KEY(session_id, msg_idx))
      embedding/model_id are created but left NULL (vectors drop in later).
  - an FTS5 virtual table over messages.text. FTS5 availability is detected at
    runtime; if unavailable the tool falls back to LIKE and says so explicitly.
  - session_meta(session_id, working_dir, short_name, model,
                 id_short_name)  -- helper table holding per-session metadata
      extracted from each session .json so the detectors need no live file
      reads and stay pure functions of the DB (deterministic reports).

Scope decision
--------------
Each session is indexed from its canonical <session_id>.json file (the
persisted transcript with messages, working_dir, short_name, model). The
.journal.jsonl (write-ahead append) and .bak (backup) copies are not separately
indexed. This keeps the incremental identity simple and the detectors pure; the
canonical .json is the authority for the persisted transcript.

Safety
------
- Default action is scan/report. READ-ONLY on ~/.jcode/sessions: this tool
  NEVER modifies or deletes session files. It writes only its own DB and an
  optional --report file.
- Re-runs are incremental: only session files whose (mtime_ms, size) changed are
  re-read. A re-run with no changes is a no-op and says so.
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys

HOME = os.path.expanduser("~")
CACHE_DIR = os.path.join(HOME, ".jcode", "cache")
DEFAULT_DB = os.path.join(CACHE_DIR, "session-mixup-index.sqlite3")
DEFAULT_SESSIONS = os.path.join(HOME, ".jcode", "sessions")

# A jcode session id: session_<name>_<epoch_ms>_<hash>. Shared with the
# prune tool's SESSION_ID_RE (temp/tools/prune_sessions.py:62).
SESSION_ID_RE = re.compile(r"^session_([a-z0-9-]+)_(\d+)_([0-9a-f]+)$")
ID_PREFIX_RE = re.compile(r"^(session_[a-z0-9-]+_\d+_[0-9a-f]+)")

# Absolute filesystem path with >= 2 path segments (used by detector D1).
# A negative lookbehind avoids grabbing the tail of a relative path (e.g.
# "y/SPR/x" -> we do NOT want "/SPR/x"); the leading segment must be a known
# Unix absolute root so dot/config tails like "/.jcode/..." and "/SPR/..." are
# rejected. This keeps D1 a genuine cwd-drift witness (paths under /home, /tmp,
# /root, ...) rather than matching noisy relative-path tails.
PATH_RE = re.compile(r"(?<![A-Za-z0-9_.~-])/(?:[A-Za-z0-9_.+-]+/)+[A-Za-z0-9_.+-]+")
ABS_ROOTS = {
    "home", "tmp", "root", "usr", "opt", "var", "srv", "etc", "media",
    "mnt", "data", "workspace", "Users", "private", "repo", "workspaces",
}


def is_abs_root_path(p):
    m = re.match(r"^/([A-Za-z0-9_.+-]+)/", p)
    return bool(m and m.group(1) in ABS_ROOTS)

# Non-trivial text threshold for D2 (sha256 collisions on substantive text).
D2_MIN_TEXT = 40
# D1: "substantial share" of transcript paths outside declared working_dir.
D1_MIN_OUTSIDE_SHARE = 0.5
D1_MIN_PATHS = 3


def open_db(path):
    """Open/create the index DB, WAL mode (recent_session_index precedent
    crates/jcode-base/src/recent_session_index.rs:46-58), and schema."""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute(
        """CREATE TABLE IF NOT EXISTS files(
               session_id TEXT NOT NULL,
               path TEXT NOT NULL,
               mtime_ms INTEGER,
               size INTEGER,
               PRIMARY KEY(session_id, path))"""
    )
    # Incremental identity = (mtime_ms, size); mirrors IndexFileSpec:
    #   crates/jcode-app-core/src/tool/session_search_index.rs:69-75
    con.execute(
        """CREATE TABLE IF NOT EXISTS messages(
               session_id TEXT NOT NULL,
               msg_idx INTEGER NOT NULL,
               role TEXT,
               ts TEXT,
               sha256 TEXT,
               text TEXT,
               embedding BLOB,          -- reserved; NULL for now
               model_id TEXT,           -- reserved; NULL for now
               PRIMARY KEY(session_id, msg_idx))"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS session_meta(
               session_id TEXT PRIMARY KEY,
               working_dir TEXT,
               short_name TEXT,
               model TEXT,
               id_short_name TEXT)"""
    )
    # FTS5 over messages.text; external-content is avoided to sidestep rowid
    # coupling; this is a standalone mirror populated transactionally.
    fts5 = None
    try:
        con.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5("
            "session_id UNINDEXED, msg_idx UNINDEXED, text)"
        )
        fts5 = True
    except sqlite3.OperationalError:
        fts5 = False  # fall back to LIKE; reported to the caller
    con.commit()
    return con, fts5


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def block_text(block):
    """Return the text contribution of one content block (dict or str)."""
    if isinstance(block, str):
        return block
    if isinstance(block, dict):
        t = block.get("type")
        if t == "text":
            return block.get("text") or ""
        if t == "tool_use":
            name = block.get("name") or "?"
            inp = block.get("input")
            if inp is not None:
                return "[tool_use:%s] %s" % (name, json.dumps(inp, sort_keys=True))
            return "[tool_use:%s]" % name
        if "text" in block:
            v = block["text"]
            return v if isinstance(v, str) else str(v)
    return ""


def flatten_message(message):
    """Return (role, ts, text) from one message dict; robust to content shape."""
    role = message.get("role") or message.get("display_role") or ""
    ts = message.get("timestamp") or message.get("ts") or ""
    content = message.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "\n".join(block_text(b) for b in content)
    else:
        text = message.get("text") or ""
    return role, ts, text


def id_short_name(session_id):
    m = SESSION_ID_RE.match(session_id)
    return m.group(1) if m else None


def parse_session_file(path):
    """Parse one session .json -> (meta dict, list of (role,ts,text))."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        data = json.load(fh)
    session_id = data.get("id")
    messages = []
    for mi, m in enumerate(data.get("messages", [])):
        role, ts, text = flatten_message(m)
        messages.append((role, ts, text))
    meta = {
        "session_id": session_id,
        "working_dir": data.get("working_dir"),
        "short_name": data.get("short_name"),
        "model": data.get("model"),
        "id_short_name": id_short_name(session_id) if session_id else None,
    }
    return meta, messages


# ---------------------------------------------------------------------------
# Indexing (incremental)
# ---------------------------------------------------------------------------

def discover_session_files(sessions_dir):
    """Map session_id -> list of canonical .json file paths on disk."""
    out = {}
    if not os.path.isdir(sessions_dir):
        return out
    for name in sorted(os.listdir(sessions_dir)):
        m = ID_PREFIX_RE.match(name)
        if not m:
            continue
        if not (name.endswith(".json") and not name.endswith(".bak")):
            continue
        out.setdefault(m.group(1), []).append(os.path.join(sessions_dir, name))
    return out


def stat_ms_size(path):
    st = os.stat(path)
    # st_mtime_ns only exists on Unix; fall back to int(st_mtime * 1000) elsewhere.
    ms = getattr(st, "st_mtime_ns", None)
    if ms is not None:
        return int(ms // 1_000_000), st.st_size
    return int(st.st_mtime * 1000), st.st_size


def rebuild_all(con, sessions_dir, fts5):
    con.execute("DELETE FROM files")
    con.execute("DELETE FROM messages")
    con.execute("DELETE FROM session_meta")
    if fts5:
        con.execute("DELETE FROM messages_fts")
    con.commit()
    n = 0
    for session_id, files in sorted(discover_session_files(sessions_dir).items()):
        idx_session(con, session_id, files, fts5, force=True)
        n += 1
    return n, None


def idx_session(con, session_id, files, fts5, force=False):
    """Index one session from its canonical .json file(s)."""
    if not files:
        return "no-files"
    path = files[0]  # canonical <id>.json; multiple .json unlikely
    mtime_ms, size = stat_ms_size(path)
    if not force:
        row = con.execute(
            "SELECT mtime_ms, size FROM files WHERE session_id=? AND path=?",
            (session_id, path),
        ).fetchone()
        if row is not None and row[0] == mtime_ms and row[1] == size:
            return "unchanged"
    meta, messages = parse_session_file(path)
    con.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
    con.execute("DELETE FROM session_meta WHERE session_id=?", (session_id,))
    if fts5:
        con.execute("DELETE FROM messages_fts WHERE session_id=?", (session_id,))
    sid = meta.get("session_id") or session_id
    con.execute(
        "INSERT OR REPLACE INTO session_meta VALUES (?,?,?,?,?)",
        (sid,
         meta.get("working_dir"),
         meta.get("short_name"),
         meta.get("model"),
         meta.get("id_short_name")),
    )
    for mi, (role, ts, text) in enumerate(messages):
        sha = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
        con.execute(
            "INSERT OR REPLACE INTO messages(session_id,msg_idx,role,ts,sha256,text,embedding,model_id)"
            " VALUES (?,?,?,?,?,?,NULL,NULL)",
            (sid, mi, role, ts, sha, text),
        )
        if fts5:
            con.execute(
                "INSERT INTO messages_fts(session_id,msg_idx,text) VALUES (?,?,?)",
                (sid, mi, text),
            )
    con.execute(
        "INSERT OR REPLACE INTO files(session_id,path,mtime_ms,size) VALUES (?,?,?,?)",
        (sid, path, mtime_ms, size),
    )
    con.commit()
    return "indexed"


def sync_and_index(con, sessions_dir, fts5, rebuild):
    """Incremental pass. Returns (report text describing new/changed/no-op)."""
    if rebuild:
        n, _ = rebuild_all(con, sessions_dir, fts5)
        return "rebuilt: indexed %d session(s) from scratch (--rebuild)" % n

    on_disk = discover_session_files(sessions_dir)
    changes = 0
    new_sessions = 0
    changed_sessions = set()
    for session_id, files in sorted(on_disk.items()):
        res = idx_session(con, session_id, files, fts5, force=False)
        if res == "indexed":
            changes += 1
            changed_sessions.add(session_id)
    # Drop sessions that no longer exist on disk (pruned).
    known = set(r[0] for r in con.execute("SELECT DISTINCT session_id FROM session_meta"))
    for sid in sorted(known - set(on_disk)):
        con.execute("DELETE FROM messages WHERE session_id=?", (sid,))
        con.execute("DELETE FROM session_meta WHERE session_id=?", (sid,))
        con.execute("DELETE FROM files WHERE session_id=?", (sid,))
        if fts5:
            con.execute("DELETE FROM messages_fts WHERE session_id=?", (sid,))
        changes += 1
        changed_sessions.add(sid)
    con.commit()
    if changes == 0:
        return "no-op: no session (mtime_ms, size) changed; nothing to re-read"
    rest = ", ".join(sorted(changed_sessions))
    return "indexed/changed %d session(s): %s" % (changes, rest)


# ---------------------------------------------------------------------------
# Detectors (pure functions of the DB; deterministic ordering)
# ---------------------------------------------------------------------------

def detect_cwd_drift(con):
    """D1 - cwd drift: transcript paths outside the declared working_dir."""
    flags = []
    rows = con.execute(
        "SELECT session_id, working_dir FROM session_meta"
    ).fetchall()
    for session_id, wd in sorted(rows):
        if not wd:
            continue
        texts = con.execute(
            "SELECT text FROM messages WHERE session_id=?", (session_id,)
        ).fetchall()
        paths = set()
        for (text, ) in texts:
            for pm in PATH_RE.findall(text or ""):
                p = pm.rstrip("./,;:!?)]}")
                if not is_abs_root_path(p):
                    continue
                paths.add(p)
        if len(paths) < D1_MIN_PATHS:
            continue
        inside = 0
        outside = 0
        outside_examples = []
        for p in sorted(paths):
            if p == wd or p.startswith(wd + "/"):
                inside += 1
            else:
                outside += 1
                if len(outside_examples) < 5:
                    outside_examples.append(p)
        total = inside + outside
        share = (outside / total) if total else 0.0
        if outside >= 1 and share >= D1_MIN_OUTSIDE_SHARE:
            flags.append({
                "session_id": session_id,
                "working_dir": wd,
                "distinct_paths": total,
                "inside": inside,
                "outside": outside,
                "outside_share": round(share, 3),
                "examples": outside_examples,
            })
    flags.sort(key=lambda f: f["session_id"])
    return flags


def detect_cross_session_bleed(con):
    """D2 - identical (or near-identical) messages across different sessions."""
    rows = con.execute(
        "SELECT session_id, sha256, text FROM messages"
    ).fetchall()
    by_sha = {}
    for session_id, sha, text in rows:
        if not sha or text is None or len(text) < D2_MIN_TEXT:
            continue
        by_sha.setdefault(sha, []).append((session_id, text))
    pairs = {}
    examples = {}
    for sha, items in sorted(by_sha.items()):
        sessions = sorted(set(s for s, _ in items))
        if len(sessions) < 2:
            continue
        pair_key = tuple(sessions)
        pairs[pair_key] = pairs.get(pair_key, 0) + 1
        if pair_key not in examples:
            examples[pair_key] = items[0][1][:120]
    flags = []
    for sessions in sorted(pairs):
        flags.append({
            "sessions": list(sessions),
            "identical_msg_groups": pairs[sessions],
            "example": examples[sessions],
        })
    flags.sort(key=lambda f: f["sessions"])
    return flags


def detect_identity_mismatch(con):
    """D3 - identity mismatch: id/short_name/working-dir claims contradict
    recorded metadata, or transcript self-reference names a different session."""
    flags = []
    meta_rows = con.execute("SELECT session_id, working_dir, short_name, id_short_name FROM session_meta").fetchall()
    for session_id, wd, short_name, id_name in sorted(meta_rows):
        # R1: recorded short_name contradicts the name derived from the id.
        if short_name and id_name and short_name != id_name:
            flags.append({
                "session_id": session_id,
                "rule": "R1-short_name_vs_id",
                "evidence": "metadata short_name=%r but id-derived name=%r" % (short_name, id_name),
            })
        # R2: the transcript's embedded 'Working directory:' claim (the first
        # declaration it prints, e.g. system-reminder/ENV_SNAPSHOT) differs
        # from the recorded working_dir metadata.
        texts = con.execute(
            "SELECT text FROM messages WHERE session_id=? ORDER BY msg_idx", (session_id,)
        ).fetchall()
        claim = None
        for (text, ) in texts:
            m = re.search(r"[Ww]orking [Dd]irectory:\s*(\S+)", text or "")
            if m:
                claim = m.group(1).rstrip(",.;")
                break
        if claim and wd and claim != wd and claim.startswith("/") and wd.startswith("/"):
            flags.append({
                "session_id": session_id,
                "rule": "R2-working_dir_claim_vs_metadata",
                "evidence": "transcript claims working directory %r but metadata records %r" % (claim, wd),
            })
        # R3: a /info-style self-reference 'Session: <name> (...)' that names a
        # different session than this one.
        own_name = id_name or ""
        for (text, ) in texts:
            for m in re.finditer(r"Session:\s*([A-Za-z0-9_-]+)\s*\(session_", text or ""):
                named = m.group(1)
                if named and own_name and named != own_name and named not in (session_id,):
                    flags.append({
                        "session_id": session_id,
                        "rule": "R3-info_self_reference",
                        "evidence": "transcript /info-style line names session %r but this is %r" % (named, own_name),
                    })
                    break
            else:
                continue
            break
    flags.sort(key=lambda f: (f["session_id"], f["rule"]))
    return flags


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def render_report(con, fts5, flags, rescan_note):
    d1, d2, d3 = flags
    lines = []
    lines.append("== session_mixup_scan report ==")
    lines.append("fts5_available: %s" % ("yes" if fts5 else "no (falling back to LIKE)"))
    lines.append("index_pass: %s" % rescan_note)
    n_sessions = con.execute("SELECT COUNT(*) FROM session_meta").fetchone()[0]
    n_messages = con.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    lines.append("indexed_sessions: %d" % n_sessions)
    lines.append("indexed_messages: %d" % n_messages)
    lines.append("")
    summary = {"D1_cwd_drift": len(d1), "D2_cross_session_bleed": len(d2),
               "D3_identity_mismatch": len(d3)}
    lines.append("== summary ==")
    for k in ("D1_cwd_drift", "D2_cross_session_bleed", "D3_identity_mismatch"):
        lines.append("  %-28s %d" % (k, summary[k]))
    overall = "FAIL" if any(summary.values()) else "PASS"
    lines.append("  OVERALL: %s" % overall)
    lines.append("")
    if d1:
        lines.append("== D1 cwd drift (t-rex class) ==")
        for f in d1:
            lines.append("  session %s declared working_dir=%s paths=%d inside=%d outside=%d share=%.3f"
                         % (f["session_id"], f["working_dir"], f["distinct_paths"],
                            f["inside"], f["outside"], f["outside_share"]))
            for e in f["examples"]:
                lines.append("      outside path: %s" % e)
    else:
        lines.append("== D1 cwd drift: none ==")
    lines.append("")
    if d2:
        lines.append("== D2 cross-session bleed ==")
        for f in d2:
            lines.append("  sessions: %s identical_msgs=%d" % (", ".join(f["sessions"]), f["identical_msg_groups"]))
            lines.append("      example: %s" % f["example"])
    else:
        lines.append("== D2 cross-session bleed: none ==")
    lines.append("")
    if d3:
        lines.append("== D3 identity mismatch ==")
        for f in d3:
            lines.append("  session %s [%s] %s" % (f["session_id"], f["rule"], f["evidence"]))
    else:
        lines.append("== D3 identity mismatch: none ==")
    lines.append("")
    return "\n".join(lines), summary, overall


def main(argv):
    ap = argparse.ArgumentParser(description="jcode session mix-up scan/DB index")
    ap.add_argument("--rebuild", action="store_true", help="force full reindex")
    ap.add_argument("--json", action="store_true", help="print report as JSON")
    ap.add_argument("--only", choices=["D1", "D2", "D3"], help="run one detector")
    ap.add_argument("--db", default=DEFAULT_DB, help="index DB path")
    ap.add_argument("--report", default=None, help="write report to this path")
    ap.add_argument("--sessions", default=DEFAULT_SESSIONS, help="sessions dir")
    args = ap.parse_args(argv)

    con, fts5 = open_db(args.db, )
    note = sync_and_index(con, args.sessions, fts5, args.rebuild)

    sel = [args.only] if args.only else ["D1", "D2", "D3"]
    d1 = detect_cwd_drift(con) if "D1" in sel else []
    d2 = detect_cross_session_bleed(con) if "D2" in sel else []
    d3 = detect_identity_mismatch(con) if "D3" in sel else []
    flags = (d1, d2, d3)

    report_text, summary, overall = render_report(con, fts5, flags, note)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            if args.json:
                json.dump({"summary": summary, "overall": overall, "fts5": fts5,
                           "index_pass": note}, fh, indent=2, sort_keys=True)
            else:
                fh.write(report_text + "\n")

    if args.json:
        print(json.dumps({"summary": summary, "overall": overall, "fts5": fts5,
                          "index_pass": note},
                         indent=2, sort_keys=True))
    else:
        print(report_text)

    con.close()
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
