# SPR-0006: Create a personal GitHub fork, wire remotes, and protect pushes to the official repo

**Files:**
- `.git/config` — remotes renamed and added: `origin` -> `upstream` (official,
  `1jehuang/jcode`, fetch-only, push poisoned to `NO_PUSH_PERSONAL`); new
  `personal` remote (fork `danflory/jcode`, fetch + push)
- `.git/hooks/pre-push` — rewritten from an unconditional all-push block to a
  URL-guarded block: pushes to the official upstream are refused, pushes to the
  personal fork are allowed
- `docs/SPR/SPR-0006-personal-fork-remotes-push-guard.md` — this document
- `docs/SPR/update-log.md` — appended a row for this SPR

**Commit:** `a3d5c3f1f` — `docs(spr): SPR-0006 personal fork + remotes + push guard`
(2026-09-16, local)

**Status:** Committed on the personal `dev` branch and pushed to the personal
fork `danflory/jcode`. The official repo `1jehuang/jcode` remains push-proof.

**Author:** Operator (d) + jcode agent (this session).

---

## Who

| Party | Role |
|---|---|
| Operator (d) | Not a contributor to `1jehuang/jcode`; must carry local fixes; requested the fork, the branch, and push protection |
| jcode agent (this session) | Inspected existing no-push setup, created the GitHub fork, re-wired remotes, adjusted the pre-push hook, pushed the custom `dev` branch |

## What

`~/.jcode/config.toml` setup aside, the workspace clone of jcode had a
"personal no-push" guard (poisoned `pushurl=NO_PUSH_PERSONAL` plus an
unconditional `pre-push` hook that `exit 1`) so local fixes could never be
pushed to the official repo. The operator, not being a contributor, still needs
an off-machine home for `dev` work. This SPR creates that home and wires it up.

## Why (motivation)

The operator maintains custom changes on this clone (e.g. the SPR docs, the
DeepInfra service-tier passthrough, the visible-swarm persistence fix). The only
remote was `origin -> https://github.com/1jehuang/jcode.git` with a poisoned
push URL, so there was no backup anywhere off-machine. Prior to this SPR the
"push: false, no fork" state meant the operator had no safe destination for
their work.

## How (changes)

1. **Fork created** via `gh repo fork 1jehuang/jcode --fork-name jcode`:
   `danflory/jcode` at https://github.com/danflory/jcode, default branch
   `master` matching upstream.
2. **Remotes re-wired** in `.git/config`:
   - `origin` renamed to `upstream` (`https://github.com/1jehuang/jcode.git`),
     push URL remains poisoned to `NO_PUSH_PERSONAL`.
   - New `personal` remote (`https://github.com/danflory/jcode.git`), fetch and
     push.
3. **`dev` branch** created at the current `master` (carrying all 23 custom
   commits including SPR-0001..0005 and `update-log.md`), and pushed to
   `personal`:
   `git push personal dev` -> `danflory/jcode` branch `dev`.
4. **Pre-push hook** rewritten from an unconditional block to a URL-conditional
   guard: pushes whose URL matches the personal fork (`danflory/jcode`) are
   allowed; every other push (notably the official upstream) is refused with
   `PUSH BLOCKED`.

## Verification

- `git push personal dev` succeeded; fork `dev` tip matches local:
  `1cabb6cc4d66c0ef758ea8916bb6959b52f7e980`.
- `git push upstream master` fails with
  `fatal: 'NO_PUSH_PERSONAL' does not appear to be a git repository` — the
  official repo remains push-proof at the transport layer.
- Fork `master` `5f33d6239...` equals local `upstream/master` — clean mirror
  for future rebases.

## Recommended ongoing workflow

- Keep `master` a clean mirror of upstream; do all custom work on `dev`.
- Pull official updates and rebase the fix branch:
  ```bash
  git checkout master
  git fetch upstream && git merge upstream/master
  git checkout dev && git rebase master
  git push personal dev --force-with-lease
  ```

## Revert guard

To undo: remove the `personal` remote (`git remote remove personal`), rename
`upstream` back to `origin`, delete `dev`, and restore the prior blocking
`pre-push` hook. The fork `danflory/jcode` can be deleted via
`gh repo delete danflory/jcode --yes`. No code changed; nothing to revert in
the tree beyond this doc and the config.
