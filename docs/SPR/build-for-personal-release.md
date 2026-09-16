# Build for Personal Release

A practical, step-by-step guide for producing a **stable** release of **jcode**
as a personal tool with custom work (our `WithLocalMods` branch), and making
the **running daemon serve that build**. No standalone copy is produced or
needed; the goal is simply that jcode works with our custom code.

## Decision (the goal, restated)

- We want **one stable release channel built from our custom `WithLocalMods`
  branch** — we do **not** want nightly/weekly/bleeding-edge builds.
- We need the **running daemon** to actually use the new code (that is the whole
  point of the `/clear`, pricing, and auth fixes). A build that the daemon does
  not serve is inert.
- We do **not** need a standalone copy or a second parallel install.
  `WithLocalMods` *is* our stable.
- Therefore the personal-release path and the self-dev build path are the **same
  thing** for us: rebuild our checkout, install it as the active stable, and
  reload the daemon onto it.
- `scripts/install_release.sh --fast` already does **build + install + daemon
  reload in one command** (see step 4), so no separate reload hand-off is
  needed after it runs.

## Why this guide exists (what we found)

We investigated the upstream release process (`scripts/quick-release.sh` and
CI) to understand how a release is built and tested. Key findings:

- The upstream **standard** release path cross-compiles a portable Linux binary
  inside a Docker container (`quay.io/pypa/manylinux2014_x86_64`) via
  `scripts/build_linux_compat.sh`, targeting a **CentOS 7 / glibc 2.17
  baseline**, plus a macOS build via osxcross.
- **That portability baseline exists to serve a broad, anonymous user base**
  (old distros + Terminal-Bench CI containers). It is not needed for a personal
  tool that runs on machines we control.
- Docker is therefore **not required** for a personal release. Neither is
  osxcross if we target Linux only. The Docker/manylinux step is purely about
  distro portability, which we do not need.
- The GitHub publish step (`gh release`, tag push) requires **origin access**.
  Our `master` is configured **pull-only** (pushurl blocked), so we do not
  publish upstream; we build and install locally.

## Branch naming (verified)

No repository document (README, AGENTS.md, CONTRIBUTING.md, or `docs/`) names,
predicts, or mandates a specific "personal mods" branch. AGENTS.md only states
the general principle: **work on your own branch and keep work scoped.** The name
`WithLocalMods` is our own choice, invented in this work, not predicted by any
document.

## Install architecture (the important constraint)

There is **one launcher** and **one daemon**, so the "alongside" model needs an
explicit decision (see below):

- `~/.local/bin/jcode` — the single launcher symlink used from `PATH`.
- `~/.jcode/builds/stable/jcode` — the stable release channel
  (`scripts/install.sh` installs upstream here and points the launcher here).
- `~/.jcode/builds/current/jcode` — the active local/source-build channel
  (self-dev builds and `scripts/install_release.sh` point the launcher here).
- `~/.jcode/builds/versions/<version>/jcode` — immutable versioned binaries.
- `~/.jcode/builds/shared-server/jcode` — the long-lived daemon, a symlink into
  `~/.jcode/builds/versions/<version>/`. **This is what actually serves `jcode
  run` and interactive sessions.** Until this symlink is repointed to our build
  and the daemon restarted (`jcode self-dev --build`), a freshly built binary is
  inert.

### Side-by-side caveat (decided)

The architecture has a single launcher and a single shared daemon, so running
upstream stable and our custom build as **two live swaps under the same `jcode`
command is not natively supported** and is not documented. Our decision:

- **`WithLocalMods` is the active stable build.** Upstream is not a parallel
  live install; it is our **source-update feed**. When we want newer upstream,
  we `git pull` on `master` and merge into `WithLocalMods`, then rebuild and
  reinstall. This matches "stable with my custom in it" and keeps the VM simple.
- We do **not** run `scripts/install.sh` for our custom build — that would
  replace the active stable with upstream and drop our work from the running
  daemon. `scripts/install_release.sh` is the tool that installs *our* build.

## Prerequisites

- This repo checked out on the **`WithLocalMods`** branch (holds all our local
  custom work; `master` remains pull-only against upstream as the update feed).
- A working Rust toolchain (`cargo` on `PATH`).
- Enough disk for a release build (`target/release`).
  Docker, osxcross, and `gh` are **not** required.

## Step-by-step personal release process

### 1. Ensure we are on the local-mods branch

```bash
git checkout WithLocalMods
git status --porcelain   # expect a clean tree before building
```

Release binaries should come from a **clean, committed** tree so the embedded
git hash/version reflects the source exactly.

### 2. Run the test suite (the "testing" half of a release)

Validate the branch before building. The fast test loop runs the library and
primary `jcode` binary unit tests with a minimal feature profile:

```bash
scripts/test_fast.sh
```

For a fuller run, use the end-to-end script:

```bash
scripts/test_e2e.sh
```

Optional real-provider smoke (only if we want it, requires credentials):

```bash
JCODE_REAL_PROVIDER=1 scripts/test_e2e.sh
```

If any test fails, fix it on `WithLocalMods` before proceeding.

### 3. Build the release binary (native, no Docker)

```bash
cargo build --release
```

This produces the ready-to-run binary at:

```bash
target/release/jcode
```

Sanity-check it runs and reports a version:

```bash
./target/release/jcode --version
```

(Optional) If we later decide we DO need a portable binary for old distros, we
can use the docker-based path:
`scripts/build_linux_compat.sh <out-dir>` — but that requires Docker and is not
needed for personal use on our own machines.

### 4. Install AND make the running daemon use it (mandatory, not optional)

This is the step that actually matters. Building alone does nothing; we must
install our build as the active stable and reload the daemon onto it. The
install script does all of this **in one command**:

```bash
scripts/install_release.sh --fast
```

What `--fast` does here, end to end:

1. **Builds** — runs `cargo build --profile release` with the embedded git
   hash/date/dirty metadata.
2. **Installs** — copies the binary into `~/.jcode/builds/versions/<hash>/`,
   then symlinks `stable`, `current`, and `~/.local/bin/jcode` to it.
3. **Reloads the daemon** — runs `jcode server reload` (issue #291), which
   hands any running background server onto the new binary. It only reloads when
   the running daemon is genuinely older, hands live headless/swarm sessions to
   the new process, and is a no-op if no server is running, so it is safe to
   call every time.

(Use `--fast` for the non-LTO `release` profile; omit it for the default
`release-lto` if we want the smaller but slower-to-build LTO binary. For a
personal tool, `--fast` is usually sufficient.)

> **Never** run `scripts/install.sh` — that installs upstream stable and would
> point the launcher away from our custom build.
>
> **No separate reload is needed** after `install_release.sh`, because it
> already performs the daemon reload. `jcode self-dev --build` is an
> alternative path that rebuilds/repoints the shared-server chain and reloads,
> but for our personal-release flow `install_release.sh --fast` is the one
> command that does build + install + reload together.

### 5. Verify the running binary is OUR build

Because a rebuilt binary is inert until promoted, confirm the daemon actually
serves our code. Resolve what is actually running:

```bash
readlink -f ~/.local/bin/jcode
readlink -f ~/.jcode/builds/shared-server/jcode
jcode --version
```

The version string and resolved paths must match our `WithLocalMods` build
(its git hash / version), not an upstream stable. If they point elsewhere, the
install/reload in step 4 did not take effect.

### 6. Record the build in the version log

Append a dated line to `docs/SPR/VERSION_UPDATE_LOG.md`:

```markdown
- **YYYY-MM-DD** — Personal release. Built `WithLocalMods` at
  <short-hash>, installed + daemon reloaded via `scripts/install_release.sh
  --fast`; tests passed (test_fast.sh).
```

## Keeping our stable current with upstream (the update cycle)

Upstream is our **source-update feed**, not a parallel install:

```bash
git checkout master
git pull origin master        # master is pull-only; this works
git checkout WithLocalMods
git merge master              # bring newer upstream into our custom branch
scripts/test_fast.sh          # test the merge
scripts/install_release.sh --fast   # build + install + reload daemon in one
```

This is the "stable with my custom in it, refreshed periodically" cycle — not a
nightly/weekly auto-update. We control exactly when a new upstream release is
merged in.

## Version numbering

- The crate version lives in `Cargo.toml` (`version = "0.84.0"` here).
- Upstream uses `vMAJOR.MINOR.PATCH` tags (`git ls-remote --tags origin`).
- For a personal tool we do **not** need to bump the version or tag it unless
  we want to distinguish one personal build from the next. If we do, bump the
  version in `Cargo.toml`/`Cargo.lock` on `WithLocalMods` and commit.

## What we explicitly skip (and why)

| Upstream step | Tool | Why we skip it |
|---------------|------|----------------|
| Portable Linux build | Docker / manylinux | Old-distro portability we don't need for personal use |
| macOS cross-build | osxcross | We target Linux only |
| Tag + GitHub draft release | `git push` + `gh` | `master` is pull-only; we don't publish upstream |
| CI platform assets / signing | GitHub Actions | Not needed for a local personal binary |
| Upstream stable install (`scripts/install.sh`) | — | Would replace our custom build with upstream |
| Parallel live channels | — | Single launcher/daemon; `WithLocalMods` is our one active stable |

## Summary

```
git checkout WithLocalMods
scripts/test_fast.sh                 # test
scripts/install_release.sh --fast    # build + install + reload daemon (one shot)
jcode --version                      # verify it's OUR build
# append a line to docs/SPR/VERSION_UPDATE_LOG.md
```

That is the complete base process for a **personal, stable jcode release that
the running daemon actually serves**. It keeps the VM light (no Docker), keeps
`master` pull-only, and makes `WithLocalMods` the stable channel without a
standalone copy or parallel installs.
