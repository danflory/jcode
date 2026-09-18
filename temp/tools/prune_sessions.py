#!/usr/bin/env python3
"""prune_sessions.py - Delete every jcode session EXCEPT the swarm's allowlist.

Safety model
------------
* DRY-RUN by default: prints exactly what would be deleted. Only acts with --apply.
* The ONLY allowlist is the KEEP constant below plus any repeated --keep flags.
* Before any --apply deletion, the entire ~/.jcode/sessions directory is tarred to
  ~/.jcode/sessions-prune-backup-<utc-timestamp>.tar.gz and the path/size printed.
* Delete, for every session id NOT in the allowlist, all of its artifacts on disk and
  its ancillary state (sqlite recent_sessions row, pid markers, todos files, cache).
* NEVER deletes an allowlisted id's files. NEVER deletes this worker's own session
  (it is part of KEEP).
* All pid markers in ~/.jcode/active_pids share the same shared-daemon pid, so pid
  liveness cannot distinguish sessions. Parsed pid content is therefore NOT used to
  decide what is safe to delete; a non-allowlisted session that has a pid marker file
  is reported as a WARNING line and still pruned.
* A second sweep pass runs after the first pass (an in-memory server agent can
  rewrite a deleted session file), then a verification report is printed. The process
  exits non-zero if any non-allowlisted session id remains on disk.
* Any file in ~/.jcode/sessions that cannot be classified to a session id aborts the
  run with a report instead of deleting it.

Usage
-----
    python3 prune_sessions.py [--keep <session_id>]... [--apply]
"""

import os
import re
import sqlite3
import sys
import tarfile
import time

HOME = os.path.expanduser("~")
JCODE_DIR = os.path.join(HOME, ".jcode")
SESSIONS_DIR = os.path.join(JCODE_DIR, "sessions")
METADATA_DB = os.path.join(JCODE_DIR, "session-metadata-v1.sqlite3")
PID_DIRS = ["active_pids", "internal_pids", "streaming_pids"]
TODOS_DIR = os.path.join(JCODE_DIR, "todos")
PICKER_CACHE = os.path.join(JCODE_DIR, "cache", "session-picker-list-v2.json")

# ---------------------------------------------------------------------------
# KEEP - the explicit allowlist. Every id below is preserved; every other
# session id discovered on disk is a deletion candidate. Comments document the
# intent so the allowlist is auditable.
#   6 member sessions of the swarm...
#   ...plus THIS worker's own session ("owl"), which must never be deleted.
# ---------------------------------------------------------------------------
KEEP = {
    "session_eagle_1789679128564_f4d2f322b75ec5cc",   # swarm member
    "session_lobster_1789681643280_ccebc4d7dcc0175b", # swarm member
    "session_mosquito_1789681804776_445e6491e16409a2",# swarm member
    "session_giraffe_1789681407162_7b7598972df46db1", # swarm member
    "session_hamster_1789681443194_a1320fc95a79f438", # swarm member
    "session_ladybug_1789681478197_6c0226a8fde1b180", # swarm member
    "session_owl_1789682487582_37ddb1632b3d6528",     # THIS worker's own session
}

# A jcode session id looks like: session_<animal>_<epoch_ms>_<hash>
SESSION_ID_RE = re.compile(r"^(session_[a-z0-9-]+_\d+_[0-9a-f]+)")


def parse_args(argv):
    keep = set(KEEP)
    apply_mode = False
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--keep":
            i += 1
            if i >= len(argv):
                sys.exit("--keep requires a value")
            keep.add(argv[i])
        elif arg == "--apply":
            apply_mode = True
        elif arg in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        else:
            sys.exit("Unknown argument: %r" % arg)
        i += 1
    return keep, apply_mode


def scan_sessions(sessions_dir):
    """Return (id_to_files, unclassified_files).

    Every filename in the sessions dir is classified to a session id via its
    leading prefix. All files belonging to an id are returned together.
    """
    id_to_files = {}
    unclassified = []
    if not os.path.isdir(sessions_dir):
        return id_to_files, unclassified
    for name in sorted(os.listdir(sessions_dir)):
        m = SESSION_ID_RE.match(name)
        if m:
            id_to_files.setdefault(m.group(1), []).append(name)
        else:
            unclassified.append(name)
    return id_to_files, unclassified


def collect_ancillary(session_id):
    """Return the ancillary paths owned by this session id."""
    paths = []
    for d in PID_DIRS:
        p = os.path.join(JCODE_DIR, d, session_id)
        if os.path.exists(p):
            paths.append(p)
    if os.path.isdir(TODOS_DIR):
        for name in os.listdir(TODOS_DIR):
            if name == session_id or name.startswith(session_id + "-") or name.startswith(session_id + "."):
                paths.append(os.path.join(TODOS_DIR, name))
    return paths


def delete_sqlite_recent_sessions(session_ids):
    """DELETE recent_sessions rows for session_ids. Returns (deleted, remaining_count)."""
    if not os.path.exists(METADATA_DB):
        return 0, None
    deleted = 0
    remaining = None
    con = sqlite3.connect(METADATA_DB)
    try:
        cur = con.cursor()
        placeholders = ",".join("?" * len(session_ids))
        cur.execute(
            "DELETE FROM recent_sessions WHERE session_id IN (%s)" % placeholders,
            list(session_ids),
        )
        deleted = cur.rowcount
        cur.execute("SELECT COUNT(*) FROM recent_sessions")
        remaining = cur.fetchone()[0]
        con.commit()
    finally:
        con.close()
    return deleted, remaining


def remove_file(path):
    if os.path.isfile(path):
        os.remove(path)


def run():
    keep, apply_mode = parse_args(sys.argv[1:])

    # Guard: this worker's own session must always be kept.
    own = "session_owl_1789682487582_37ddb1632b3d6528"
    if own not in keep:
        sys.exit("Refusing to run: this worker's own session id is missing from the allowlist.")

    sessions_dir = os.path.realpath(SESSIONS_DIR)
    id_to_files, unclassified = scan_sessions(sessions_dir)

    if unclassified:
        print("ABORT: unclassified files in sessions dir (cannot classify):")
        for u in unclassified:
            print("   " + u)
        sys.exit(2)

    all_ids = set(id_to_files)
    candidates = sorted(all_ids - keep)

    print("== prune_sessions ==")
    print("Keep allowlist (%d):" % len(keep))
    for k in sorted(keep):
        print("   KEEP %s" % k)
    print("Discovered session ids on disk: %d" % len(all_ids))
    print("Deletion candidates (not in allowlist): %d" % len(candidates))
    print("Mode: %s" % ("APPLY" if apply_mode else "DRY-RUN"))

    if not candidates and not apply_mode:
        print("Nothing to delete.")
        verify_and_exit(keep)

    # --- Report plan / warn on pid markers ---
    warnings = []
    for sid in candidates:
        pid_hits = []
        for d in PID_DIRS:
            p = os.path.join(JCODE_DIR, d, sid)
            if os.path.exists(p):
                pid_hits.append(d)
        if pid_hits:
            warnings.append((sid, pid_hits))
        files = id_to_files.get(sid, [])
        anc = collect_ancillary(sid)
        print("DELETE session %s" % sid)
        for f in files:
            print("     ~/.jcode/sessions/%s" % f)
        for p in anc:
            print("     <ancillary> %s" % p)
    if warnings:
        print("\n== PID-MARKER WARNINGS (pid liveness NOT used; pruning continues) ==")
        for sid, dirs in warnings:
            print("   WARNING %s has pid markers in: %s" % (sid, ", ".join(dirs)))

    if not apply_mode:
        print("\nDRY-RUN complete. Re-run with --apply to delete. No changes made.")
        return 0

    # --- Backup entire sessions dir BEFORE deleting ---
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_path = os.path.join(JCODE_DIR, "sessions-prune-backup-%s.tar.gz" % ts)
    print("\n== Creating backup ==")
    with tarfile.open(backup_path, "w:gz") as tar:
        tar.add(sessions_dir, arcname=os.path.basename(sessions_dir))
    backup_size = os.path.getsize(backup_path)
    print("Backup tarball: %s" % backup_path)
    print("Backup size   : %d bytes" % backup_size)

    # --- First pass: delete files + ancillary for candidates ---
    print("\n== First pass ==")
    deleted_sessions = set()
    for sid in candidates:
        removed_any = False
        for f in id_to_files.get(sid, []):
            p = os.path.join(sessions_dir, f)
            if os.path.exists(p):
                os.remove(p)
                removed_any = True
        for p in collect_ancillary(sid):
            if os.path.exists(p):
                remove_file(p)
                removed_any = True
        deleted_sessions.add(sid)
        print("Deleted session %s" % sid)

    # sqlite recent_sessions rows for all candidates
    sql_deleted, sql_remaining = delete_sqlite_recent_sessions(list(candidates))
    print("Deleted recent_sessions rows: %d (remaining in table: %s)" % (sql_deleted, sql_remaining))

    # Invalidate session-picker cache
    cache_touched = False
    if os.path.exists(PICKER_CACHE):
        os.remove(PICKER_CACHE)
        cache_touched = True
    print("Invalidated %s: %s" % (PICKER_CACHE, "yes" if cache_touched else "not present"))

    # --- Second sweep pass ---
    print("\n== Second sweep pass ==")
    sweep_deleted = 0
    for _ in range(3):  # bounded re-scans in case a live agent keeps rewriting
        fresh, fresh_unclassified = scan_sessions(sessions_dir)
        if fresh_unclassified:
            print("ABORT: unclassified files appeared during sweep:")
            for u in fresh_unclassified:
                print("   " + u)
            verify_and_exit(keep)
        ghosts = sorted(set(fresh) - keep)
        if not ghosts:
            break
        for sid in ghosts:
            for f in fresh.get(sid, []):
                p = os.path.join(sessions_dir, f)
                if os.path.exists(p):
                    os.remove(p)
                    sweep_deleted += 1
            for p in collect_ancillary(sid):
                if os.path.exists(p):
                    remove_file(p)
            print("Sweep removed %s" % sid)
    print("Sweep pass files removed: %d" % sweep_deleted)

    # --- Verification ---
    return verify_and_exit(keep)


def verify_and_exit(keep):
    id_to_files, unclassified = scan_sessions(SESSIONS_DIR)
    remaining = set(id_to_files)
    print("\n== Verification ==")
    if unclassified:
        print("UNCLASSIFIED files remain (not session ids):")
        for u in unclassified:
            print("   " + u)
    if remaining - keep:
        print("FAIL: these non-allowlisted session ids remain on disk:")
        for sid in sorted(remaining - keep):
            print("   " + sid)
        return 1
    print("OK: every on-disk session id is in the allowlist.")
    print("Remaining on-disk ids (%d):" % len(remaining))
    for sid in sorted(remaining):
        print("   " + sid)
    return 0


if __name__ == "__main__":
    sys.exit(run())
