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
type: SPR.DEBUG_GUIDE
version: "2026-09-17"
---

# SPR-0008: sessionCorruption — Debugging Session Mix-Ups

Date: 2026-09-17
Subject: a repeatable, evidence-driven debugging procedure for the SPR-0008
defect class ("session mix-ups": client-local session state overriding server
truth), built around the index tool
`/home/d/dev_env/jcode/temp/tools/session_mixup_scan.py` (option 2c prototype).

> Companion docs: `04_Semantic_Index_Options.md` (why 2c was picked),
> `03_Tool_and_Design.md` (the session-prune tool and new design),
> `05_Fix_Explanations.md` (the two fix commits; **absent at the time of
> writing** but listed in the README index by another worker — if you are
> reading this after 05 lands, cross-reference it for the fix mechanics).
>
> Every command below was run and verified against the current
> `~/.jcode/sessions` and `~/.jcode/logs/jcode-2026-09-17.log`. Items that could
> not be re-verified because their source files were deleted during cleanup are
> marked **UNVERIFIED** and attributed to the anchor where they are documented.

## 1. When to Use This Guide

Use this procedure when you observe any symptom of a "session mix-up", i.e.
client-local state overriding server truth. The canonical signals are:

- A session's tools (e.g. `bash`) act on a **different repository** than the
  session's persisted `working_dir`; the session "thinks" it is in repo A but
  commands run in repo B. This is the t-rex failure.
- `/info` (or the terminal footer / session title) names a **different session**
  than the one actually serving the turn, often a client-local stub such as
  `Session: snail (session_)`.
- **Content appears in the wrong session**: a message, todo, or tool result that
  belongs to session A shows up in session B; or two sessions carry identical
  content that should be distinct.
- A `--resume <id>` silently changes the resumed session's cwd (symptom A in
  the anchor, `SPR-0008.md:35-68`).

If you are here after a **coordinator hand-off** (per
`workPatterns/01_Approval_Gated_Assignment_Flow.md`), treat the checklist in
Section 6 as the single-task brief and report evidence, not impressions.

## 2. Evidence Sources and How to Read Them

### 2.1 Session transcripts: `~/.jcode/sessions/<id>.json` (+ journal/bak)

| File | Meaning | How to read it |
|:-----|:--------|:---------------|
| `<id>.json` | The persisted session object (messages, `working_dir`, `short_name`, `model`, `env_snapshots`). | `working_dir`, `short_name`, `model` are the declared/recorded values. |
| `<id>.journal.jsonl` | Write-ahead log of metadata updates since the last snapshot. | `meta.updated_at`, `meta.working_dir`, `meta.model` per entry; the tail shows recent changes. |
| `<id>.bak` | The **previous snapshot** before the last persist. | Compare it to the live `.json`: a differing field shows a value **CHANGE**. |
| `<id>.*.pre-wipe-*.bak` | Pre-wipe backups written before a destructive rewrite. | Strongest change evidence (e.g. the t-rex `.json.pre-wipe-...` vs live `.json`). |

Reading a field is trivial:

```bash
python3 - <<'PY'
import json,os
p=os.path.expanduser('~/.jcode/sessions/session_eagle_1789679128564_f4d2f322b75ec5cc.json')
d=json.load(open(p))
print('working_dir:', d.get('working_dir'))
print('short_name:', d.get('short_name'))
print('model:', d.get('model'))
print('#messages:', len(d.get('messages', [])))
for m in d.get('messages', [])[:2]:
    print(' ', m.get('role'), str(m.get('content'))[:80])
PY
```

To detect a value **change**, diff live vs previous snapshot:

```bash
python3 - <<'PY'
import json,os,glob
d=os.path.expanduser('~/.jcode/sessions')
for sid in ['session_eagle_1789679128564_f4d2f322b75ec5cc']:
    cur=json.load(open(os.path.join(d,sid+'.json')))
    bak=json.load(open(os.path.join(d,sid+'.bak')))
    print(sid)
    for k in ('working_dir','short_name','model'):
        a,b=bak.get(k),cur.get(k)
        print('  %-12s bak=%r -> json=%r %s' % (k,a,b,'' if a==b else '  <-- CHANGED'))
PY
```

### 2.2 Server log: `~/.jcode/logs/jcode-<date>.log`

The server log is the authoritative timeline of lifecycle events. Two line kinds
matter most (both verified present in `jcode-2026-09-17.log`):

- **`ENV_SNAPSHOT`** lines carry a `reason` (`create`, `resume`, ...) and a
  `working_dir`, plus a `working_git.root/branch` when a git repo is detected.
  They record what directory a session was *bound to* at a point in time.
- **`SESSION_LIFECYCLE`** lines with `phase=resume_start` record
  `source_session_id` (the session being resumed FROM / the client's local
  session) and `target_session_id` (the session being resumed INTO). This is
  exactly where a cwd override is smuggled in.

Grep for them:

```bash
LOG=~/.jcode/logs/jcode-2026-09-17.log

# All ENV_SNAPSHOT bindings for one session, oldest first:
grep -n "ENV_SNAPSHOT" "$LOG" | grep "session_t-rex" | head

# The resume that bound a target to a directory:
grep -n "phase=resume_start" "$LOG" | grep "session_t-rex"
```

### 2.3 Git history / reflog

A worker may have committed, amended, or reset in the wrong repo. If a session
"should" be in repo A but committed in repo B, check both:

```bash
cd /home/d/dev_env/clones/Overwatch
git log --oneline -5          # where did recent commits land?
git reflog | head -20          # resets / checkouts the worker may have done
git status
```

This is a **cross-check**, not the primary evidence: the log and transcript are
the authority for what the session believed its cwd was.

## 3. The Index-Based Detection Procedure

The tool is `session_mixup_scan.py`. It is **read-only** on
`~/.jcode/sessions` (NEVER modifies or deletes session files); it writes only
its own database `~/.jcode/cache/session-mixup-index.sqlite3` and an optional
`--report` file. Re-runs are incremental: only session files whose
`(mtime_ms, size)` changed are re-read
(`temp/tools/session_mixup_scan.py:94-149`; identity mirrors
`IndexFileSpec`, `crates/jcode-app-core/src/tool/session_search_index.rs:69-75`).

### 3.1 Real flags (all used below)

```text
--rebuild            force full reindex (else incremental)
--only <D1|D2|D3>    run a single detector
--json               machine-readable summary
--db <path>          index DB path (default ~/.jcode/cache/session-mixup-index.sqlite3)
--report <path>      write the report to a file
--sessions <dir>     sessions dir (default ~/.jcode/sessions)
```

Exit codes: `0` = PASS (nothing flagged); `1` = FAIL (at least one detector
fired). All output is deterministically sorted so two runs over unchanged data
are byte-identical.

### 3.2 Run the scanner (the whole procedure)

```bash
cd /home/d/dev_env/jcode
python3 temp/tools/session_mixup_scan.py --rebuild --report ~/.jcode/cache/mixup-report.txt
echo "exit=$?"        # 0=PASS, 1=FAIL
cat ~/.jcode/cache/mixup-report.txt
```

Expected output shape (real, at time of writing):

```text
== session_mixup_scan report ==
fts5_available: yes
index_pass: rebuilt: indexed 7 session(s) from scratch (--rebuild)
indexed_sessions: 7
indexed_messages: 588

== summary ==
  D1_cwd_drift           0
  D2_cross_session_bleed 0
  D3_identity_mismatch   2
  OVERALL: FAIL
...
```

A second identical run is a **no-op** and proves idempotency:

```bash
python3 temp/tools/session_mixup_scan.py
# index_pass: no-op: no session (mtime_ms, size) changed; nothing to re-read
```

### 3.3 Which detector answers which question

| Detector | Question it answers | Implementation |
|:---------|:--------------------|:---------------|
| **D1 cwd drift** | "Does this session's own transcript act on paths outside its declared `working_dir`?" | `detect_cwd_drift` at `...py:335`; thresholds `D1_MIN_OUTSIDE_SHARE=0.5`, `D1_MIN_PATHS=3` at `...py:90-91`; only absolute root paths (`PATH_RE`/`ABS_ROOTS` `...py:76-85`) |
| **D2 cross-session bleed** | "Do distinct sessions carry identical/near-identical messages?" | `detect_cross_session_bleed` at `...py:382`; exact sha256 grouping on text ≥ `D2_MIN_TEXT=40` chars (`...py:88`) |
| **D3 identity mismatch** | "Does a session's id/short_name / working-dir claim contradict its recorded metadata?" | `detect_identity_mismatch` at `...py:413`; rules R1 (short_name vs id), R2 (transcript `Working directory:` claim vs metadata), R3 (`/info` self-reference names another session) |

Read the summary this way: a nonzero D1 is a strong cwd-drift signal (the
t-rex class); a nonzero D3 R2/R3 is an identity-contradiction signal (the /info
class); a nonzero D2 means content is duplicated across sessions and needs a
manual look at who owns what.

### 3.4 From a flag to the underlying record (read-only SQLite queries)

The DB schema (created by the tool): tables `files`, `messages`,
`session_meta`, and an FTS5 virtual table `messages_fts`. Columns are honest to
the tool's `CREATE TABLE` statements (`...py:104,114,126`).

Use `sqlite3` or the Python module. Example read-only queries (all verified to
execute against the live index DB):

```bash
DB=~/.jcode/cache/session-mixup-index.sqlite3
# The full per-session metadata used by the detectors:
sqlite3 "$DB" "SELECT session_id, working_dir, short_name, id_short_name FROM session_meta ORDER BY session_id;"

# D1 input: every distinct absolute transcript path per session:
python3 - <<'PY'
import sqlite3,os,re,sys
con=sqlite3.connect(os.path.expanduser('~/.jcode/cache/session-mixup-index.sqlite3'))
for sid,wd in con.execute("SELECT session_id,working_dir FROM session_meta"):
    if not wd: continue
    paths=set()
    for (text,) in con.execute("SELECT text FROM messages WHERE session_id=?",(sid,)):
        paths.update(re.findall(r"(?<![A-Za-z0-9_.~-])/(?:[A-Za-z0-9_.+-]+/)+[A-Za-z0-9_.+-]+", text or ""))
    print(sid, 'wd=', wd)
    for p in sorted(paths): print('   ', p)
PY

# D2 input: groups of messages whose sha256 collides across >=2 sessions:
sqlite3 "$DB" "SELECT sha256, group_concat(session_id,' | '), COUNT(*) FROM messages
               WHERE length(text) >= 40 GROUP BY sha256
               HAVING COUNT(DISTINCT session_id) >= 2 ORDER BY sha256;"

# D1/D3 input: the messages that mention a working-dir outside the declared one:
sqlite3 "$DB" "SELECT session_id, substr(text,1,80) FROM messages WHERE text LIKE '%/clones/%';"

# Index files tracked (invalidation identity):
sqlite3 "$DB" "SELECT session_id, path, mtime_ms, size FROM files ORDER BY session_id;"
```

Which table answers which: `session_meta` = the "recorded" truth the tool
compares against; `messages.sha256` = the D2 collision key; `messages.text` =
the D1/D3 evidence; `files.(mtime_ms,size)` = what a re-run re-reads.

## 4. Worked End-to-End Example: the Real t-rex Incident

Symptom: a client launched in `/home/d/dev_env/clones/Overwatch`, created a
fresh `chick` session bound to that cwd, then immediately resumed `t-rex`,
silently rewriting `t-rex`'s persisted `working_dir` from
`/home/d/dev_env/clones/Overwatch_2` to
`/home/d/dev_env/clones/Overwatch`
(anchor reproduction, `SPR-0008.md:35-68`).

**A. Log evidence** (all verified against
`~/.jcode/logs/jcode-2026-09-17.log`):

- Line 8547 — `ENV_SNAPSHOT reason=create`, `session_id=chick`,
  `working_dir=/home/d/dev_env/clones/Overwatch` (the client's launch cwd).
- Line 8567 — `SESSION_LIFECYCLE phase=resume_start`,
  `source_session_id=chick`, `target_session_id=t-rex` (the resume that passes
  the client cwd through). Actual line, abridged:

  ```text
  [2026-09-17 20:43:46.336] EVENT event=SESSION_LIFECYCLE ... phase=resume_start
    request_id=1 source_session_id=session_chick_1789677826145_9af79213e7bc7045
    target_session_id=session_t-rex_1789662214733_691326d2e2194bf2
  ```

- Line 8579 — `ENV_SNAPSHOT reason=resume`, `session_id=t-rex`,
  `working_dir=/home/d/dev_env/clones/Overwatch`, with
  `working_git.root=/home/d/dev_env/clones/Overwatch`, `branch=main` (the
  rewrite landing on the wrong clone).

The causal chain is: line 8547 (chick bound to Overwatch) -> line 8567
(resume_start passes that cwd into t-rex) -> line 8579 (t-rex now bound to
Overwatch).

**B. Transcript diff** — the persisted value change. The anchor documents that
the pre-wipe backup `session_t-rex_....json.pre-wipe-1789671862548.bak` held
`working_dir = /home/d/dev_env/clones/Overwatch_2` while the live `.json` held
Overwatch (`SPR-0008.md:48-53`). The live artifact was deleted during the
session-prune cleanup, so this specific diff is **UNVERIFIED** on the current
disk; the anchor is the source. The same `compare .bak vs .json` technique in
Section 2.1 is what a re-check uses.

**C. How the index would have surfaced it.** Run the scanner per Section 3:

- **D1 cwd drift** would fire if the *pre-rewrite* `t-rex` transcript carried
  many `.../Overwatch_2` paths while its metadata (post-rewrite) said Overwatch,
  or vice-versa. After the rewrite both the metadata and a session restarted in
  Overwatch would agree, so D1 is strongest **before** the rewrite is masked —
  which is exactly why you scan the pre-wipe/`.bak` copies and the log, not only
  the live `.json`.
- **D3 R2** (transcript `Working directory:` claim vs recorded `working_dir`)
  catches the moment a transcript's own embedded claim disagrees with the
  recorded metadata.
- **D3 R3** catches the /info variant: the scanner flagged the *real* stub line
  `Session: snail (session_` in the eagle and lobster transcripts during the
  option-2c prototype run (matches anchor symptom B, `SPR-0008.md:70-89`).

So the index gives you repeatable *suspicion* (D1/D3), and the log + transcript
diff give you *proof* (A + B above).

## 5. Why This Cannot Be Trusted Alone

The index is a transcript-text scanner. It cannot see corruption with no textual
trace. State honestly what it CANNOT detect:

- **Metadata-only corruption with no textual trace.** If only the `working_dir`
  field changed and no message text mentions any path, D1/D3 find nothing. The
  `.bak`-vs-`.json` diff (Section 2.1) is the only detector for that case.
- **Corruption that happened before indexing started.** The DB only contains
  what was read since the first run (or `--rebuild`). It has no memory of
  sessions it never indexed; history is in the log, not the DB.
- **Deletions.** If a session file was removed (as t-rex was during cleanup),
  the index drops it and leaves no trace of what it said. A deleted session's
  evidence must come from the backup tarball and the server log.
- **Anything not present in transcripts.** Cross-session status, enqueued
  messages, side-panel/todo state, terminal titles — anything that exists in
  client-local state but never lands in a persisted transcript — is invisible
  to this tool.
- **Non-absolute or relative path references.** D1 deliberately counts only
  absolute root paths (`ABS_ROOTS`, `...py:76-85`) and may miss a session whose
  drift is expressed in relative terms only.

**What must still be checked by hand:** the server log
(`ENV_SNAPSHOT` / `SESSION_LIFECYCLE`), the `.bak`/`.pre-wipe` diffs, git
reflog, and any client-local state (todo files, side panel, `/info` output).
The index narrows the search; it does not close it.

## 6. The Debugging Procedure (numbered checklist)

Follow mechanically. Stop and report if a step contradicts the one before it.

1. **Snapshot the unknown.** Record the on-disk sessions:
   `ls -1 ~/.jcode/sessions/`. Note any session whose `working_dir` you are
   about to investigate.
2. **Run the scanner (fresh index):**
   `python3 temp/tools/session_mixup_scan.py --rebuild --report /tmp/mixup.txt`.
   Read the summary. Record exit code (0 PASS / 1 FAIL).
3. **For each flagged session**, identify which detector fired from the report
   body (D1/D2/D3), then pull the underlying rows with the Section 3.4 queries.
4. **Confirm with the log:**
   `grep -n "session_<id>" ~/.jcode/logs/jcode-<date>.log | grep -E "ENV_SNAPSHOT|phase="`
   and read the `reason`/`source_session_id`/`target_session_id` chain.
5. **Confirm the value change:** compare `<id>.json` vs `<id>.bak` (and any
   `*.pre-wipe-*.bak`) for `working_dir`; record the before/after values.
6. **Check the repo side:** in the session's git root, run `git log`,
   `git reflog`, and `git status` to see whether a worker committed/reset in the
   wrong place (Section 2.3).
7. **Classify** the mix-up: cwd drift (D1 + log resume chain), identity
   (D3 R3 + `/info`), or bleed (D2 + duplicate ownership). State which.
8. **Prove the fix worked.** Re-run the scanner without `--rebuild`
   (`python3 temp/tools/session_mixup_scan.py`); the `index_pass` line must show
   the fix's working_dir change was re-read (that session indexed/changed) and
   the flagged detector count must drop to 0 (exit 0). Then **attach from a
   sibling clone** and assert the persisted `working_dir` is unchanged:

   ```bash
   # after the resume-cwd fix: resume t-rex-like session from clone A
   jcode --resume <target_session_id> &
   sleep 3
   python3 - <<'PY'
   import json,os
   # read the TARGET session's persisted working_dir before and after attach
   p=os.path.expanduser('~/.jcode/sessions/<target_session_id>.json')
   print(json.load(open(p)).get('working_dir'))
   PY
   # The printed working_dir must still be the ORIGINAL dir, not the client's cwd.
   ```

   A green re-run plus an unchanged `working_dir` after a sibling-clone attach
   is the acceptance proof for the resume-cwd fix.

## 7. How the Coordinator Reviews This

The reviewer validates the document itself with these checks:

1. `test -f docs/SPR/SPR-0008-sessionCorruption/06_Debugging_Session_Mixups.md`
   and confirm frontmatter `type: SPR.DEBUG_GUIDE` (folder convention).
2. `grep -n "06_Debugging_Session_Mixups" docs/SPR/SPR-0008-sessionCorruption/README.md`
   returns the index row in numeric order after `05`.
3. **Every detector flag is real:** run
   `python3 temp/tools/session_mixup_scan.py --rebuild --report /tmp/mixup.txt`
   and confirm the `D3_identity_mismatch` count is >= 2 and names `snail` for
   eagle/lobster (the live evidence cited in Section 4).
4. **Idempotency:** run it a second time and confirm `index_pass: no-op` and a
   byte-identical report (`diff <(run1) <(run2)`).
5. **Each documented command actually ran:** spot-check the Section 3.4 sqlite
   queries against `~/.jcode/cache/session-mixup-index.sqlite3`, and the log
   greps against `~/.jcode/logs/jcode-2026-09-17.log` (lines 8547, 8567, 8579).
6. **No scope leak:** `git status` shows only the new `06_...md` and the edited
   `README.md` (plus the other workers' SPR docs); nothing under `crates/` and
   nothing under `temp/tools/` modified by this guide.
7. **Honesty:** every claim marked **UNVERIFIED** (the t-rex `.bak` diff, the
   absent `05` doc) is genuinely unverifiable from current disk, and the
   "cannot detect" list in Section 5 is present and explicit.
