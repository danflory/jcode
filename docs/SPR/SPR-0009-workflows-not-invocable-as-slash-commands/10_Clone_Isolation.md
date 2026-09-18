---
# jcode-local frontmatter (SPR folder conversion, 2026-09-17).
# jcode is NOT governed by Overwatch's UDRS: no UDRS/ci_impacted/parent numeric
# ids are fabricated here. Only real, repo-verifiable values are used.
id: SPR-0009-P10
title: Clone isolation - running parallel feature work without cross-talk
status: DRAFT
author: operator
created: 2026-09-18
domain: ENGINEERING
severity: Major
type: RESEARCH
version: "2026-09-18"
---

# SPR-0009-P10: Clone Isolation (research)

## 0. Placement note

This document is **topically outside SPR-0009** (which is about workflows not being
invocable as slash commands). It is recorded here by explicit operator decision as
research, on the understanding that it migrates to Overwatch later. The placement is
intentional and acknowledged as inconsistent; it is not an error in the folder
convention.

## 1. Problem

Parallel feature work in a single repository was abandoned. The reason was not git
itself but attribution: with several feature branches in one working tree, the local
repo's own record no longer showed the changes belonging to one feature, and session
state leaked between features. The requirement that replaces it is:

1. Each feature gets its own clone, so that clone's git record shows exactly that
   feature's changes.
2. Sessions, config, MCP servers, and credentials for one feature cannot see or
   disturb another's.

## 2. Option A — per-clone jcode home, directory-named

Layout the operator proposed:

```
clones/Ow2/.jcode          # JCODE_HOME for this feature
clones/Ow2/Overwatch_2     # the git clone itself
```

### 2.1 Mechanics, verified

- **`JCODE_HOME` fully redirects jcode state.** `jcode_dir()` checks `JCODE_HOME`
  first and only then falls back to `~/.jcode`
  (`crates/jcode-storage/src/lib.rs:150-155`). Sessions, memory, logs, config, state,
  and the global MCP config all move with it.
- **A redirected home disables nothing important on Linux.**
  `running_with_sandboxed_home()` has exactly one non-test caller,
  `crates/jcode-base/src/auth/claude.rs:791`, which skips the macOS Keychain.
- **Socket isolation works per home.** `socket_path()` is `runtime_dir()/jcode.sock`;
  `runtime_dir()` prefers `JCODE_RUNTIME_DIR`, then `XDG_RUNTIME_DIR`, then a private
  temp directory keyed by a user discriminator
  (`crates/jcode-app-core/src/server/socket.rs:6-13`;
  `crates/jcode-storage/src/lib.rs:97-117`).
- **Two different `.jcode` directories exist, with different roles.** The wrapper's
  `.jcode` is the home (global config). A `.jcode` inside the git clone is
  *project-local* config, resolved against the **session working directory**
  (`load_project_locals`, `crates/jcode-base/src/mcp/protocol.rs:580`; asserted by
  `crates/jcode-base/src/mcp/protocol_tests.rs:358`). Because the home is already per clone, the MCP entry can
  live in the home's global `mcp.json` and still be clone-scoped, so no project-local
  file is needed.

### 2.2 Costs, measured

| Item | Measured |
|:-----|:---------|
| jcode home | 172 MB, of which models 87 MB, logs 54 MB, sessions 8.9 MB, memory 3.1 MB |
| jcode daemon RSS | 264 MB (`pid 1137404`, uptime 13h19m) |
| MCP child RSS | 16 MB |
| A real feature clone | 239 MB to 854 MB across `clones/Overwatch_1..5` |
| The main clone | 51 GB, but 49 GB of that is `backups/`, which is git-ignored (see doc 11) |

So five directory-named clones cost roughly 3 GB of clones, ~1 GB of homes (minus
shared models), and ~1.6 GB of daemon RSS. Affordable on a 23 GiB box.

### 2.3 Costs that are not memory

- **`config.toml` is per home, so provider credentials and any tuned setting are
  replicated per clone.** Generate them from one template.
- **The embedding model is per home** (`models_dir()` = `$JCODE_HOME/models/<model>`,
  `crates/jcode-base/src/embedding.rs:402-406`). Share it by symlink or accept ~87 MB
  per clone.
- **Deleting the feature directory deletes that clone's sessions, memory, and logs.**
  If clone history should outlive the feature, put homes outside the feature dir.
- **`launcher_dir()` is derived from `JCODE_HOME`** (`crates/jcode-build-support/src/paths.rs:370`). Irrelevant here
  while the binary is the system install at `/usr/local/bin/jcode` and
  `~/.jcode/builds` is empty, but it matters if the local/self-dev channel is used.
- **Telemetry id is per home**, so each clone reports as a separate install.

### 2.4 The footgun

A wrapper that switches directories but not socket or home leaves clients attached to
the default daemon, which recreates the cross-talk while the files look correctly
separated. `JCODE_HOME` and `JCODE_SOCKET` must both be derived by the launcher.

## 3. Option B — per-user isolation (recommended)

Differentiation by login identity instead of directory name. Six users, each with one
clone and one jcode instance, each clone at the same uniform path.

### 3.1 Why it is stronger

- **The boundary is kernel-enforced.** Different uids mean file permissions and
  process isolation are enforced by the OS rather than by convention.
- **It removes the `JCODE_HOME` problem.** Each user's default home is already
  `~user/.jcode`, so no wrappers, no launcher derivation, no per-clone socket config.
  The socket is per-user automatically through `XDG_RUNTIME_DIR`.
- **Paths become uniform.** Every user's clone lives at the same relative path, so
  prompts, docs, and MCP configs are identical across users and differ only by who
  runs them.

### 3.2 The load-bearing rule

**No user among the six may be in `sudo`.** One sudo-capable account collapses the
model, because it can become every other user. Today the operator account is
`uid=1000(d)` with passwordless `sudo` and membership in `lxd` (see
`09_Security_Model.md` §5), so this rule is not yet satisfied by the current account.

### 3.3 Costs, measured

| Item | Measured |
|:-----|:---------|
| Six clones | ~3 GB total (239-854 MB each) |
| Six jcode homes | ~1 GB, minus shared models |
| Six daemons | ~1.6 GB RSS |
| Credentials | per user, or one shared readable file |

### 3.4 The footgun

`XDG_RUNTIME_DIR`. Running `jcode` as `d2` while inheriting `d`'s environment
(`sudo -u` without a login shell, or a shared systemd unit) can leave
`XDG_RUNTIME_DIR=/run/user/1000`, so `d2` attaches to `d`'s daemon. Use real per-user
login sessions (`su -`, `machinectl shell`, SSH, or `loginctl enable-linger` plus a
login), or set `JCODE_RUNTIME_DIR` explicitly.

### 3.5 Where this does NOT apply: inside a container

Per-user uid isolation works on a **host VM** — which is where this work is happening.
It does **not** work inside a container, and this was established upstream before this
document was written. `DAR-OW-096` research R07 (*Container Principal Model — Credential
Secrecy Is Void*) finds that a container is a **single principal**: the licensed
operator and the agent are indistinguishable inside it, secrets are mounted world- or
group-readable because the application must read its own credentials, and there is no
privilege hierarchy to separate them with. Its conclusions:

- `chattr`, `sudo`, and file ownership are **architecturally void** inside a container.
- PostgreSQL RBAC is the **sole surviving enforcement boundary**, because it is
  external to the container.
- `harden.sh --pod-mode` drops all chattr/sudo/ownership steps accordingly.

So the rule for this document: **uid-per-clone is a host-layer control.** If jcode work
moves into pods, Option B collapses, and the boundary has to become credential-scoped
instead — distinct DB roles, distinct ServiceAccounts, and egress policy per profile.
That is exactly what `DAR-OW-096`'s three pod profiles do.

This also frames the VM question: a VM per entitlement *restores* everything R07
declared void (real uids, file modes, sudoers, `chattr`, per-VM kernel, hypervisor
perimeter), which is a strong argument for it — but it re-opens roughly half of that
DAR's decision tree, because R07, RD-20, R08, R11, R12, and R19 all descend from the
container constraint.

### 3.6 Related upstream design

`DAR-OW-096` (`/home/d/dev_env/clones/Overwatch/docs/praca/DAR/DAR-OW-096_Containerized_Amnesiac_Deployment/`)
solves the same parallelism problem one layer down, with the same four root causes in
its README (daemon contention, hook collision, per-filesystem signature gates, and
global agent-memory context bleed) and a container-based answer. Where it overlaps:
ephemeral AI state versus preserved code, one-identity-many-entitlements
(`auth.user_project_roles` plus a project/role picker), and per-profile credential
scoping. Where it differs: its boundary is external (DB RBAC plus a crypto server)
because the container has no internal one, whereas this document's host-layer options
rely on the kernel's own separation.

## 3.7 The model this feeds

The vocabulary that sits above these options (project VM, workspace, lease, entitlement,
and availability as idle-and-quiescent) is recorded in `13_Model_and_Vocabulary.md`,
together with the correction that the unit is a VM per **project** with leases inside it,
not a VM per entitlement. This document supplies the mechanics for one workspace; 13
supplies the model that arranges them.

## 4. Comparison

| Dimension | Option A (per-clone home) | Option B (per-user) |
|:----------|:--------------------------|:--------------------|
| Session/state cross-talk | Removed | Removed |
| Kernel-enforced isolation | No (same uid) | Yes |
| Clone readability across features | Not restricted | Restricted by file mode |
| Uniform paths across features | No (needs naming) | Yes |
| Wrapper required | Yes (`JCODE_HOME` + `JCODE_SOCKET`) | No (defaults are per-user) |
| Extra setup | Config templating | Users, sudoers, shared model dir, per-user credentials |

## 5. What neither option buys

- **Authority separation if any account has sudo.** Option A is a state boundary, not
  a capability one; Option B becomes one only once §3.2 holds.
- **Read scope or egress control.** The model API remains the only outbound channel
  that carries content, and each agent can read whatever its uid can read
  (`09_Security_Model.md` §4.1).
- **A partitioned governed DB.** The firecontrol DB is one shared resource for every
  clone and every user. `next_number` allocation is atomic, but ordering is not, so
  concurrent `createSPR` runs can interleave UDS ids and CI registrations. This is
  the one remaining cross-talk channel and needs its own serialization decision (a
  lock, or a single governed-writer path).
- **Cluster separation.** There is one k3s cluster. A root-only kubeconfig plus no
  sudo makes that restriction enforced rather than conventional, which is an
  improvement, but it is still one cluster.

## 6. Recommended shape

Six unprivileged users, none in `sudo`, one clone each at a uniform path, per-user
home and runtime dir, one shared read-only model cache, one serialized
governed-writer path for the DB, and the admin account kept separate from the six.

## 7. Verification list (I-series)

- **I-1** — `JCODE_HOME` redirects state: `jcode_dir()` order verified in source.
- **I-2** — Socket isolation path verified in source, with the fallback documented.
- **I-3** — The two `.jcode` roles (home vs project-local) distinguished with
  citations, so the layout cannot be misread.
- **I-4** — Per-clone and per-home costs measured rather than estimated.
- **I-5** — Both footguns (`JCODE_HOME`/`JCODE_SOCKET` wrapper, `XDG_RUNTIME_DIR`
  inheritance) documented with the failure each causes.
- **I-6** — The one remaining shared resource (the governed DB) named explicitly
  rather than left implied.

## 8. Reproduction commands

```bash
# I-1 / I-2
sed -n '150,155p' crates/jcode-storage/src/lib.rs
sed -n '97,117p' crates/jcode-storage/src/lib.rs
sed -n '6,13p' crates/jcode-app-core/src/server/socket.rs

# I-3
sed -n '575,585p' crates/jcode-base/src/mcp/protocol.rs
grep -n "resolves_against_given_dir_not_cwd" -A 6 crates/jcode-base/src/mcp/protocol_tests.rs

# I-4
du -sh ~/.jcode; du -sh ~/.jcode/* | sort -h | tail -5
ps -eo pid,rss,cmd | grep -E "jcode.*serve" | grep -v grep
for c in /home/d/dev_env/clones/Overwatch_*; do du -sh "$c"; done
```

**END.** This document changes no code and no configuration.
