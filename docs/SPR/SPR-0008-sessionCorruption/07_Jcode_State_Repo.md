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
type: SPR.FIX_REPORT
version: "2026-09-17"
---

# SPR-0008: sessionCorruption — Jcode State Repo at `~/.jcode` (Fix Log)

Date: 2026-09-17
Component: local machine state under `~/.jcode` (`/home/d/.jcode`)

This document logs the new local git repository at `~/.jcode` — the mechanism
that makes SPR-0008's *state* corruption visible as diffs — and the removal of
the leaked test fixtures. It is a fix log for the "invisible state changes"
portion of the incident, complementary to `05_Fix_Explanations.md`.

## 1. The problem

Before this fix there was **no version history** under `~/.jcode`. State changes
were invisible:

- A session's `working_dir` was silently rewritten (SPR-0008 symptom A, session
  `t-rex`) with no record of the before/after.
- Leaked test fixtures kept appearing (e.g. the `synthetic-fixture/` and
  `synthetic-fixture-multi/` folders created outside the real `sessions/` dir).
- Stale markers and bookkeeping files churned with no diff to inspect.

Because nothing tracked this directory, an operator had only indirect evidence
(a pre-wipe `.bak` file, server logs) that state had changed. There was no way to
ask *"exactly when did this file change, and from what to what?"*

## 2. The fix

`~/.jcode` is now a local git repository with a strict `.gitignore`, so any
tracked state change shows up as a diff.

- `git init` run in `~/.jcode`; repo-local identity set so it does not depend on
  global config: `user.name=d`, `user.email=d@sandbox.local`.
- `.gitignore` written to never track heavy artifacts or credentials (see
  Security Rule below).
- Tracked meaningful state: `sessions/`, `todos/`, `memory/`, `state/`,
  `migrations/`, `active_pids/`, `internal_pids/`, `streaming_pids/`,
  `keymap-snapshot.json`, `last_focused_client_session`,
  `session-metadata-v1.sqlite3`.
- **Baseline commit**: `f509bf1756e2a55e8836d552d89e1c3a56dd7f7a`
  (`chore(state): baseline snapshot of meaningful ~/.jcode state`).
  Pre-commit scan confirmed no secret-bearing file and no file over ~5MB staged
  (largest staged file was `sessions/session_eagle_...json` at ~1.1MB; a
  pattern-scan for credential *values* found none — flagged hits were the
  normal words "token/secret/password" in transcripts, not real keys).

Verified after commit: `config.toml` is ignored and appears in **no** commit; no
`provider_activity*`, `telemetry_*`, `prompt-history.jsonl`, `*.tar.gz`, `*.sock`,
`*.lock`, or anything under `builds/ models/ logs/` is tracked.

## 3. How to use it

Because `~/.jcode` is a git repo, an operator can now inspect state deltas
directly:

- `git -C ~/.jcode status` — see what state has changed since the last commit
  (e.g. a session journal updated, the sqlite metadata changed).
- `git -C ~/.jcode diff` — see the unstaged working change under `~/.jcode`,
  including whether a session's `working_dir` was rewritten.
- `git -C ~/.jcode log -p -- sessions/` — see the history of the `sessions/`
  tree and the exact commit at which a session's record changed.

For example, a session `working_dir` rewrite now surfaces as a tracked diff in
`sessions/<id>.json` / `.journal.jsonl` instead of being silent.

## 4. Security rule

`config.toml` is CREDENTIAL-BEARING (10 key/token/secret-looking lines) and is
gitignored **on purpose**. `provider_activity*.json/.bak`, `telemetry_*`,
`prompt-history.jsonl`, and the heavy dirs (`builds/ models/ logs/ browser/
cache/ scratch/`) and artifacts (`*.tar.gz *.sock *.lock`) are likewise ignored.
**These must never be added to the repo.** Before any `git -C ~/.jcode add`,
re-run the staged scan (`git status --short`, `git diff --cached --stat`) and
confirm no secret-bearing file and no large (>~5MB) file is staged. If one is,
extend `.gitignore` first.

## 5. What is NOT covered

- **Binary sqlite diffs are opaque.** `session-metadata-v1.sqlite3` is tracked,
  but it is a binary file, so `git diff` shows "Binary files differ" rather than
  readable field-level changes.
- **The repo only shows state that is tracked.** Anything gitignored (logs,
  models, telemetry, provider spend, prompt history, credentials) and anything
  outside `~/.jcode` has no history here. Untracked stray folders (like the
  fixtures removed below) are only visible while they exist on disk and appear
  only via `git status` before they are committed/removed.

## 6. Stray fixture removal

Two leaked test-fixture folders lived outside the real `sessions/` dir and were
never auto-removed (verified: jcode only prunes `sessions/*.bak` older than 30
days and log files). They were removed and committed as a clean delete diff:

- Removed: `/home/d/.jcode/synthetic-fixture/`
- Removed: `/home/d/.jcode/synthetic-fixture-multi/`
- **Removal commit**: `380b75d1b09d5553058a72fcf05a0f294b9a7f84`
  (`chore(state): remove stray synthetic fixture folders`); stat:
  `8 files changed, 88 deletions(-)` (both `mixup.sqlite3`, both `report.txt`,
  four fixture session `.json` files).

Commit hashes (verified via `git -C ~/.jcode log --oneline`):
- `f509bf1 chore(state): baseline snapshot of meaningful ~/.jcode state`
- `380b75d chore(state): remove stray synthetic fixture folders`

## 7. Verification status

| Check | Result |
|:------|:-------|
| `~/.jcode` is a git repo (`git rev-parse --is-inside-work-tree`) | **VERIFIED** — yes |
| Baseline scan: no secret-bearing file staged | **VERIFIED** — pattern-scan found no real credential values; `config.toml` absent from all commits (`git log --all -- config.toml` empty; `git check-ignore config.toml` confirms ignored) |
| Baseline scan: no file >~5MB staged | **VERIFIED** — largest staged file ~1.1MB |
| Fixtures removed from disk and repo | **VERIFIED** — dirs absent from disk; removal commit `380b75d` |
| Tracked state still records live changes as diffs | **VERIFIED** — `git status` shows `session-metadata-v1.sqlite3` and `sessions/session_ox_...journal.jsonl` modified by the running daemon since baseline |

Note: the two commit operations above are the only commits made in `~/.jcode`.
The jcode source repo (`docs/SPR/...`) changes are left **uncommitted** per task
constraints.
