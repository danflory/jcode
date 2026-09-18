---
# jcode-local frontmatter (SPR folder conversion, 2026-09-17).
# jcode is NOT governed by Overwatch's UDRS: no UDRS/ci_impacted/parent numeric
# ids are fabricated here. Only real, repo-verifiable values are used.
id: SPR-0008
title: sessionCorruption - client-local session state overrides server session identity and working directory
status: DRAFT
author: operator
created: 2026-09-17
domain: ENGINEERING
severity: Major
type: SPR.DESIGN
version: "2026-09-17"
---

# SPR-0008: sessionCorruption — Session-Prune Tool and New Design

Date: 2026-09-17
Subject: the existing `prune_sessions.py` tool and a prioritized design for its
successor, grounded in this incident's observed evidence.

> **Reference artifact**: `/home/d/dev_env/jcode/temp/tools/prune_sessions.py`
> (294 lines, Python 3, stdlib only: `os`, `re`, `sqlite3`, `sys`, `tarfile`,
> `time`). All function names and line numbers below cite that file under
> `git` tracking at the version of this writing.

## 1. Purpose and Scope

`prune_sessions.py` deletes every jcode session in `~/.jcode/sessions` that is
NOT on an explicit allowlist, plus that session's ancillary state, so that a
clean shared-server install retains exactly the sessions the swarm wants to keep
and "no ghosts" of pruned sessions remain anywhere reachable.

**What it deletes** (for each non-allowlisted session id):

- session artifacts in `~/.jcode/sessions`: `<id>.json`, `<id>.journal.jsonl`,
  `<id>.bak`, and the `.pre-wipe-*.bak` variants (matched because every such
  file begins with a valid session-id prefix);
- `recent_sessions` rows in `~/.jcode/session-metadata-v1.sqlite3`
  (`delete_sqlite_recent_sessions`, lines 120-140);
- pid marker files in `~/.jcode/active_pids`, `~/.jcode/internal_pids`,
  `~/.jcode/streaming_pids` (`collect_ancillary`, lines 106-117);
- `~/.jcode/todos/<id>*` files;
- the session-picker cache `~/.jcode/cache/session-picker-list-v2.json`
  (invalidated by removal, lines 237-242).

**What it preserves**: every allowlisted id's files, its ancillary state, and
this worker's own session. The **allowlist model** is: a `KEEP` set constant
(lines 51-59) initialized with the six swarm members plus this worker's own
hardcoded id (`session_owl_1789682487582_37ddb1632b3d6528`, line 58), extended
by any number of repeated `--keep <id>` flags (`parse_args`, lines 65-84). The
final allowlist used is `KEEP ∪ {--keep ...}`.

## 2. Behavior Reference

| Behavior | Where | Line(s) |
|:----------|:------|:--------|
| DRY-RUN by default; only `--apply` deletes | `parse_args` → `apply_mode` | 76-77, 202-204 |
| Refuses to start without the hardcoded self-id in the allowlist | `run` guard | 152-154 |
| Classifies files to a session id by `SESSION_ID_RE` prefix | `scan_sessions` | 62, 87-103 |
| **Abort (exit 2)** on any unclassifiable filename | `run` | 159-163 |
| Compute candidates = on-disk ids minus allowlist | `run` | 165-166 |
| PID-marker WARNING lines (liveness not used) | `run` | 181-200 |
| Pre-delete tarball backup of the whole sessions dir | `run` | 206-214 |
| First pass: delete files + ancillary; sqlite rows; invalidate picker cache | `run` | 216-242 |
| Second sweep pass: up to **3** bounded rescans | `run` | 244-267 |
| Verify remaining ids vs allowlist; exit 0/1 | `verify_and_exit` | 273-290 |

**Exit codes**: `0` success/no-op (line 290, and dry-run no-op at 176-178, 204);
`1` fail — a non-allowlisted id remains after verification (line 285) or a
fatal argument/guard error; `2` abort — an unclassified filename was found
(line 163).

**Flow on `--apply`**: (1) guard self-id present; (2) scan + classify, aborts
exit 2 on anything unclassifiable; (3) print plan and pid warnings; (4) tar the
entire sessions dir to
`~/.jcode/sessions-prune-backup-<utc>.tar.gz` and print path+size; (5) first
pass deletes files/ancillary, removes sqlite rows, invalidates the picker cache;
(6) second sweep re-scans up to 3 times, deleting any session that reappears
(an in-memory server agent can rewrite a deleted session file); (7) verification
prints remaining ids and exits non-zero if any non-allowlisted id remains.

## 3. What It Did in This Incident (observed evidence)

Run at `2026-09-17T22:04Z`, allowlist = the 7 ids in `KEEP`.

- **Pre state (from the backup tarball, the authoritative incident snapshot)**:
  74 session files across **28 distinct session ids**. 21 files belonged to the
  7 allowlisted ids; **53 files belonged to 21 non-allowlisted ids**, including
  7 `.pre-wipe-*.bak` variants (swan, t-rex, tiger, whale). 28 ids / 74 files is
  the verifiable count; the coordinator's description of "27 session files" was
  not reproduced from the tarball and is treated as UNVERIFIED.
- **Post state**: 7 distinct session ids remain, all swarm-owned
  (`eagle`, `giraffe`, `hamster`, `ladybug`, `lobster`, `mosquito`, `owl`).
- **Backup**: `~/.jcode/sessions-prune-backup-20260917T220407Z.tar.gz`,
  **3,203,137 bytes (≈ 3.2 MB)**, **75 tar members** (74 files + 1 top
  directory entry). Verified present on disk.
- **Ancillary**: 21 `recent_sessions` rows deleted (`remaining in table: 10`);
  `cache/session-picker-list-v2.json` invalidated (removed).
- **Sweep + verification**: second sweep removed 0 re-appearing files; final
  verification printed `OK: every on-disk session id is in the allowlist.`
  with the 7 remaining ids; process exit code 0.
- **Pid-marker handling**: `session_cricket_...` was reported as a WARNING
  (markers in `active_pids` + `internal_pids`) and pruned, since pid liveness is
  unusable (all markers carry the same shared-daemon pid, observed as 1137404).

## 4. Safety Model and Its Limitations

Safety model (from the module docstring, lines 4-22): allowlist-only deletion,
DRY-RUN by default, a pre-delete tarball, a second sweep, verification with a
non-zero exit, an abort (exit 2) on unclassifiable filenames, and a warning-only
treatment of pid markers because pid liveness cannot distinguish sessions (all
shared-daemon markers carry the same daemon pid). The limitations, stated
plainly:

1. **Abort-on-unclassified makes it not re-runnable while test fixtures exist.**
   Any filename not matching `SESSION_ID_RE` triggers exit 2 (lines 159-163), so
   the tool cannot run against a sessions dir that contains fixture files such
   as `session_resume_stored_cwd_wins` / `session_resume_no_stored_cwd`. Why it
   matters: a test that writes fixtures into the *real* `~/.jcode/sessions`
   (instead of an isolated `JCODE_HOME`) permanently wedges the tool until the
   fixtures are removed by hand. At paper time no such fixture files were on
   disk (verified: zero unclassified filenames in `~/.jcode/sessions`), so the
   abort is conditional, but the fragility is real.
2. **It never cleans pid markers whose session file is already gone.** The tool
   only removes a pid marker when that id is a candidate in the same run. Any
   pre-existing pid marker whose session file no longer exists (ids `llama`,
   `mouse`, `wolf` were observed to survive the run and had to be removed by
   hand) is invisible to `scan_sessions` and is left behind. Why it matters:
   stale markers linger as "ghosts" the tool claims to eliminate.
3. **A new backup tarball is created on every `--apply`.** Lines 207-214 have no
   rotation or dedup, so repeated runs accumulate unbounded
   `sessions-prune-backup-*.tar.gz` files in `~/.jcode`. Why it matters: backups
   are only useful if they can be found and pruned themselves.
4. **The worker's own session id is hardcoded** (line 152) and the run refuses
   to start if it is missing from the allowlist (lines 153-154). Why it
   matters: the tool is coupled to a single operator identity and cannot serve
   a different worker or a generic install without editing source.
5. **Pid liveness is unusable for safety decisions.** Because every pid marker
   in `~/.jcode/active_pids` (and siblings) carries the same shared-daemon pid
   (observed value 1137404), the tool cannot infer which sessions are "live".
   It therefore deliberately does not use pid content to decide what is safe to
   delete; non-allowlisted sessions with markers are merely WARNING lines. Why
   it matters: liveness-based skip logic is not an option in this topology, and
   any future design that wants safe-by-liveness must first fix the marker
   scheme.

## 5. The New Design — Prioritized Improvement Spec

Prioritization: **P1/P2** are "must" items (the ones that would have made the
original run fully self-sufficient); P3-P7 are correctness/ergonomics; P8-P11 are
robustness/coverage. Rationale and acceptance criteria per item.

### P1 — Stop aborting on unclassified names
- **Rationale**: exit 2 (lines 159-163) makes the tool fragile to any
  non-session file and wedges it when fixtures appear in the real sessions dir
  (limitation 1).
- **Design**: treat the **stem before the first dot** as the session id, and
  treat *everything* in `sessions/` as deletable unless its id is kept. Add an
  opt-in `--strict` mode that restores the current exit-2 behavior for
  deliberately unclassifiable names. **Dry-run must never abort**: it always
  prints the full plan, including unclassified items.
- **Acceptance**: (a) a bare fixture filename in `sessions/` no longer blocks a
  dry-run; (b) with `--apply` (no `--strict`) the fixture is deleted and
  verification still passes; (c) `--strict` reproduces exit 2 on an
  unclassifiable name; (d) dry-run exits 0 in all input states.

### P2 — Sweep the three pid-marker dirs for non-KEEP ids and drop dead markers
- **Rationale**: limitation 2 (llama/mouse/wolf survived). The marker dirs are
  small flat directories the tool can scan independently of `sessions/`.
- **Design**: after the session sweep, list `active_pids/`, `internal_pids/`,
  `streaming_pids/`. For each marker whose id is not in KEEP, remove it; for
  markers whose id IS in KEEP but whose pid is dead (see note: only meaningful
  once the marker scheme is fixed), remove with a report line.
- **Acceptance**: a marker for a non-existent, non-kept id is deleted; no marker
  for a kept id is ever deleted; a report line is printed for each removed
  marker.

### P3 — Resolve "self" dynamically
- **Rationale**: limitation 4 (hardcoded `session_owl_...`, lines 152-154).
- **Design**: read `JCODE_SESSION_ID` env var or an explicit `--self <id>`
  instead of a constant; the guard remains (refuse to run without a self id in
  the allowlist).
- **Acceptance**: `--self <id>` works; `JCODE_SESSION_ID=<id>` works;
  a run with no self id present refuses to start; no source edit needed to
  change identity.

### P4 — Conditional / rotated backups
- **Rationale**: limitation 3 (unbounded `sessions-prune-backup-*` accumulation,
  lines 207-214).
- **Design**: `--no-backup` skips the tarball; skip backup entirely when zero
  candidates exist; and keep only the last N backups (default, e.g., 3),
  deleting older `sessions-prune-backup-*.tar.gz` above the cap.
- **Acceptance**: `--no-backup` creates no tarball; a zero-candidate run creates
  none; after N+1 runs only the newest N tarballs remain.

### P5 — `--keep-file` and `--keep-prefix` for a stable allowlist across runs
- **Rationale**: the current allowlist is `KEEP ∪ --keep` (lines 51-59, 65-84),
  which is per-invocation and error-prone to repeat.
- **Design**: `--keep-file <path>` reads one id per line; `--keep-prefix <p>`
  keeps every on-disk id starting with `p`. Both union into the allowlist.
- **Acceptance**: an id from a keep-file is preserved; `--keep-prefix
  session_eagle_` preserves every eagle id; missing keep-file is a fatal error.

### P6 — Explicit `--dry-run` plus `--list`, `--verify-only`, `--json`
- **Rationale**: "default is dry-run" is implicit (lines 202-204); operators
  need explicit, machine-readable verbs.
- **Design**: `--dry-run` (explicit alias of the default), `--list` (ids only),
  `--verify-only` (run only `verify_and_exit` logic), `--json` (structured
  output for the plan/result).
- **Acceptance**: `--dry-run` matches default behavior; `--verify-only` makes no
  changes and exits 0/1 on the verification result; `--json` parses as JSON on
  stdout.

### P7 — End summary table with per-store before/after counts
- **Rationale**: verification currently prints ids (lines 286-289) but not
  per-store deltas.
- **Design**: a final table with rows per store (sessions/, todos/, each pid
  dir, sqlite, caches) and before/after file/row counts.
- **Acceptance**: the table's after-counts match an independent on-disk count
  for every store.

### P8 — Bounded retry with a short sleep until the set is stable for two passes
- **Rationale**: the current sweep is a fixed 3 rescans with no sleep
  (lines 244-267); a live agent rewriting files can outrace an immediate rescan.
- **Design**: between rescans, sleep a short interval (e.g., 100-250 ms) and
  require two consecutive identical scans before declaring stability, with the
  same bound (e.g., up to 5 attempts) to guarantee termination.
- **Acceptance**: with a scripted rewriter, the tool converges only when the
  on-disk set is identical on two consecutive scans; it always terminates.

### P9 — Single-run `flock` so two runs cannot interleave
- **Rationale**: two concurrent `--apply` runs could each tar and the second
  could observe a partially-pruned state; there is no lock today.
- **Design**: take an exclusive advisory lock on a lockfile (e.g.,
  `~/.jcode/sessions-prune.lock`) for the whole run; a second run exits with a
  clear "already running" message.
- **Acceptance**: a concurrent second invocation exits without modifying
  anything; the lock is released on all exit paths.

### P10 — Trash-then-restore instead of hard delete; restore on verification failure
- **Rationale**: deletion is `os.remove` (lines 143-145, 224, 261); a failed
  verification has no rollback path beyond the manual tarball.
- **Design**: move deleted files to a trash dir (e.g.,
  `~/.jcode/sessions-prune-trash-<ts>/`) and, if the final verification fails,
  restore (move back) everything from that trash dir.
- **Acceptance**: a forced verification failure leaves the on-disk state at (or
  restored to) the pre-run state; a successful run leaves the trash dir for
  manual review.

### P11 — Widen coverage to `*.pre-wipe-*.bak` and `sessions.shared-pre-carveout/`; invalidate the session_search cache too
- **Rationale**: today the pre-wipe variants are captured only because they
  begin with a valid id prefix and end in `.bak`; the tool does not touch the
  `sessions.shared-pre-carveout/` directory, and it invalidates only
  `session-picker-list-v2.json` (lines 237-242), leaving the
  `session_search_jcode_index_v2.bin` search cache live.
- **Design**: recognize the `.pre-wipe-<ts>.bak` pattern explicitly; treat
  `sessions.shared-pre-carveout/` as a deletable store when it is not part of
  the allowlist; invalidate the session-search cache alongside the picker cache.
- **Acceptance**: spurious `*.pre-wipe-*.bak` files are covered by the stem
  classification (P1); `sessions.shared-pre-carveout/` non-kept ids are pruned;
  both caches are invalidated on `--apply`.

**Which items would have made the original run fully self-sufficient: P1 and
P2.** P1 removes the exit-2 wedge (the only thing that can stop the tool
today), and P2 removes the hand-removed pid ghosts (llama/mouse/wolf) that the
original run left behind. The remaining items are correctness, ergonomics, and
robustness hardening.

## 6. Root Cause Note

The exit-2 limitation (P1) traces to how fixtures reached the real state: a
test wrote fixture files into the **real** `~/.jcode/sessions` instead of an
isolated `JCODE_HOME`, so the sessions directory became the test's scratch
space. Repeated pruning treats only the symptom; each run deletes whatever
accumulated. **The real fix is test isolation** — point tests at a throwaway
`JCODE_HOME` so fixtures never touch the production sessions dir, and the tool
never has to make policy about foreign names. This is recommended as follow-up
work independent of the P1..P11 tool improvements. (The specific fixture names
`session_resume_stored_cwd_wins` / `session_resume_no_stored_cwd` are reported
by the coordinating operator; at the time of writing neither was present in
`~/.jcode/sessions`.)

## 7. Reproduction / How to Re-Run

Dry-run (safe; prints the full plan, makes no changes):

```bash
python3 /home/d/dev_env/jcode/temp/tools/prune_sessions.py \
  --keep session_eagle_1789679128564_f4d2f322b75ec5cc \
  --keep session_giraffe_1789681407162_7b7598972df46db1 \
  --keep session_hamster_1789681443194_a1320fc95a79f438 \
  --keep session_ladybug_1789681478197_6c0226a8fde1b180 \
  --keep session_lobster_1789681643280_ccebc4d7dcc0175b \
  --keep session_mosquito_1789681804776_445e6491e16409a2 \
  --keep session_owl_1789682487582_37ddb1632b3d6528
```

Apply (backup first, then prune, sweep, and verify):

```bash
python3 /home/d/dev_env/jcode/temp/tools/prune_sessions.py --apply \
  --keep session_eagle_1789679128564_f4d2f322b75ec5cc \
  --keep session_giraffe_1789681407162_7b7598972df46db1 \
  --keep session_hamster_1789681443194_a1320fc95a79f438 \
  --keep session_ladybug_1789681478197_6c0226a8fde1b180 \
  --keep session_lobster_1789681643280_ccebc4d7dcc0175b \
  --keep session_mosquito_1789681804776_445e6491e16409a2 \
  --keep session_owl_1789682487582_37ddb1632b3d6528
```

Verify status independently (what the tool's final verification reports and
what the incident left behind):

```bash
ls -1 ~/.jcode/sessions/ | sed -E 's/\..*//' | sort -u   # remaining ids
python3 - <<'PY'
import os,re
d=os.path.expanduser('~/.jcode/sessions')
ids=set()
for n in os.listdir(d):
    m=re.match(r'^(session_[a-z0-9-]+_\d+_[0-9a-f]+)',n)
    if m: ids.add(m.group(1))
print(sorted(ids))
PY
```

**Exit status interpretation**: `0` = ok (all on-disk ids allowlisted);
`1` = fail (a non-allowlisted id remains or a fatal argument/guard error);
`2` = abort (an unclassifiable filename was found).
