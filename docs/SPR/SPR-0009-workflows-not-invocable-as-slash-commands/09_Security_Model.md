---
# jcode-local frontmatter (SPR folder conversion, 2026-09-17).
# jcode is NOT governed by Overwatch's UDRS: no UDRS/ci_impacted/parent numeric
# ids are fabricated here. Only real, repo-verifiable values are used.
id: SPR-0009-P09
title: Security model - internal-only network posture, capability, and provenance
status: DRAFT
author: operator
created: 2026-09-18
domain: ENGINEERING
severity: Major
type: SECURITY
version: "2026-09-18"
---

# SPR-0009-P09: Security Model

## 1. Purpose

This document is the full security treatment for the SPR-0009 work: the MCP-based
workflow execution surface described in 06 and 07, running in the operator's
sandbox. It records the posture that actually holds, separates the parts that the
topology makes moot from the parts it makes sharper, and states the current
containment state honestly rather than aspirationally.

It supersedes any security argument in the folder that reasons from *reachability*
of the MCP server. Where earlier documents frame security as exposure, this one
frames it as **capability, read scope, and provenance inside a single trust
domain**.

## 2. Topology (verified)

Everything relevant runs in one KVM guest:

| Component | Where it runs | Evidence |
|:----------|:--------------|:---------|
| MCP server | Child process of the jcode daemon, same guest | `McpClient::connect_in_dir`, `crates/jcode-base/src/mcp/client.rs:155-181` |
| Daemon / agent | Same guest, serves sessions over a unix socket | `/run/user/1000/jcode.sock` |
| Governed DB | Guest-local postgres | `127.0.0.1:51728`; `_dsn.py` notes the old `192.168.1.135:51729` PgBouncer is disabled |
| Cluster | k3s in the same guest | `k3s` and `kubectl` installed; `/etc/rancher/k3s/k3s.yaml` present |
| Git clones | Same guest, one per feature | `/home/d/dev_env/clones/Overwatch_1..5` |

The operator reaches this over SSH, which carries terminal I/O (TUI run in the
guest) or the client protocol to the guest's jcode daemon. Neither carries MCP traffic.
The SDK's SSH transport targets `jcode api --stdio` on the remote and deliberately
disables forwarding, multiplexing, and configured local commands
(`crates/jcode-sdk/src/ssh.rs:1-20`), so the jcode daemon — and therefore the MCP child —
stays in the guest.

**MCP has no network surface at all.** jcode supports stdio only; HTTP/SSE entries
are recognized and skipped at load (`crates/jcode-base/src/mcp/protocol.rs:233-243`,
skipped at `:678-686`). The server communicates over stdin/stdout pipes. It cannot
bind a port unless someone deliberately wraps it in a network transport.

### 2.1 Terminology: which daemon

"Daemon" is ambiguous in this workspace and is disambiguated throughout this folder:

- **jcode daemon** — the long-lived `jcode` server process that owns the unix socket
  (`/run/user/1000/jcode.sock`), spawns sessions, and is the MCP *client*. This is
  what "the daemon" means in this document, and it is the process that spawns the
  MCP child.
- **Overwatch daemon** — the governed-state subscriber/daemon in the Overwatch world
  (`OW_tools/daemon_contract/`, `daemon_supervisor/`, `ow_daemon_actions.py`), with
  its own socket (`overwatch.sock` / `ow-daemon.sock`, probed by the delivered
  server's `ow_db_probe`). It is unrelated to MCP process spawning.

## 3. What the internal-only posture makes moot

Delete these rather than soften them; they argue about a boundary that does not
exist here:

- **Transport security for MCP** (TLS, tokens, authentication, bind addresses).
  There is no channel to authenticate.
- **Inbound exposure of the MCP server.** No listener, so nothing to firewall.
- **Config scope as a security control.** Global vs project-local is a selection
  mechanism (`crates/jcode-base/src/mcp/protocol.rs:665-671`), never a protection.
- **Egress to the governed DB as a leak path.** The DB is loopback; that concern
  belongs to a multi-host topology, not this one.

## 4. The trust domain, and what replaces the network boundary

MCP, the jcode daemon, the clones, the governed DB, and the cluster are **one trust
domain**. There is no inter-component boundary left to defend, so the controls that
matter are identity, read scope, and capability.

### 4.1 Read scope, because the model API is the only egress

The one unavoidable outbound channel is the HTTPS call to the model provider. It is
also the only channel that carries content off the guest. Anything the agent can
read can leave through it: clone files, DB rows, environment values, and cluster
secrets.

Therefore the effective security question is **"what may the agent read?"**, not
"who can reach the MCP server?". A hardening plan that does not answer the read
question does not change the exfiltration surface at all.

### 4.2 Capability

What the agent process can do once it is running, all inside the guest:

| Capability | Status | Evidence |
|:-----------|:-------|:---------|
| Write governed DB state | Yes, via `OW_tools/db_write.py` | `ow_write_ci`, `upsert_praca`, `upsert_sc`, `close_ci` |
| Write files in any clone | Yes | shell access |
| Execute the clone's Python | Yes | server shells out with `cwd = ow_repo_root`; the dry-run path does `sys.path.insert(0, root)` |
| Reach the k8s API | Yes, via `kubectl` | `k3s`/`kubectl` in the guest; kubeconfig is root-readable |
| Read any file as root | Yes, in practice | see §5 |
| Egress to the model API | Yes, required | provider HTTPS |

### 4.3 Provenance

The server executes **the clone's own `OW_tools`** with the jcode daemon's DB reach. With
several parallel feature clones, "which code is running" is a per-branch decision,
not a one-time one. Doc 06 §3 Step 7 proposes hash pinning for exactly this and it
is **not implemented** (`grep -c SHA256 temp/mcp/ow_createspr/server.py` → 0), so
today a modified `OW_tools` in a clone is executed without a drift check.

## 5. Current containment state (honest)

The posture is **network-internal, not privilege-contained**. Measured on
2026-09-18 in this guest:

- `uid=1000(d)`, groups `d adm cdrom sudo dip plugdev lxd`.
- **Passwordless `sudo` works** (`sudo -n true` succeeds). Effective root.
- `CapEff` is `0` for the interactive shell, but `CapBnd` is full, so any setuid or
  sudo path grants full capabilities.
- Membership in `lxd` is root-equivalent on its own.
- The guest is a KVM VM with no container or seccomp confinement around the agent.
- `/etc/shadow` and `/etc/rancher/k3s/k3s.yaml` are root-only, and both are
  reachable through `sudo`.

**Consequence:** every "internal to the sandbox" statement is true and also
unprotective. The agent is already the highest-privileged principal in the trust
domain. Nothing in jcode enforces privilege separation between the agent, the MCP
child, the cluster, and the governed DB. Internal-only does not reduce the risk; it
means the actor is already inside.

## 6. Credentials — STUB, MUST BE DEVELOPED

> **Status: stub.** Per operator instruction this topic is recorded, not resolved.
> The section is intentionally incomplete; it exists so the gap is visible and
> cannot be mistaken for coverage.

What is known today:

- jcode scrubs a **narrow denylist** from the environment it passes to the MCP
  child: `*_API_KEY`, `*_ACCESS_TOKEN`, `*_AUTH_TOKEN`, plus exactly
  `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`,
  `AZURE_CLIENT_SECRET`, `GOOGLE_APPLICATION_CREDENTIALS`
  (`crates/jcode-base/src/mcp/client.rs:396-418`). The child otherwise inherits the
  jcode daemon environment (`Command::envs` at `:176`; no `env_clear` on this path).
- So `DATABASE_URL`, `PGPASSWORD`, `GITHUB_TOKEN`, `HF_TOKEN`, and `CLIENT_SECRET`
  pass through. The `env` block in config only *adds*; it cannot restrict.
- The governed DB resolves its DSN from `~/.pgpass` or environment
  (`OW_tools/db_write_commands/_connections/_dsn.py`), so credential material may
  live in files as well as the environment.

What a developed section must answer, at minimum:

1. Where each credential lives (env, `~/.pgpass`, k8s secret, file), and which of
   those the agent can read today given §5.
2. Whether the MCP child should run with a scrubbed environment by default rather
   than a denylist, and how that is expressed in config given `env` is additive.
3. Whether the governed DB credential should be scoped to a role that cannot do
   anything the workflow does not need.
4. How cluster credentials are kept out of the agent's read scope, given `kubectl`
   and a root-readable kubeconfig are present.
5. What the rotation and revocation story is once any credential has been in the
   agent's environment.

## 7. Controls that exist today

These are real and verified; they are capability controls, not network controls:

- **Dry-run default** on every mutating tool in the delivered server; a call writes
  governed state only when the caller passes `dry_run: false`.
- **Explicit `artifact_id` required in dry-run**, so no governed number is
  allocated by a sandbox call.
- **Refusal to guess an in-repo target**: `dry_run: false` without an explicit
  `target_dir` is refused rather than defaulting to `docs/praca/SPR`.
- **Read-only allowlist** on the `db_write` passthrough: 11 read subcommands;
  `upsert_sc`, `upsert_praca`, `ow_write_ci`, `apply_migration`, `delete_test_data`,
  and `update_ci_status` were each refused in testing.
- **No MCP network surface** (§2).
- **Daemon socket is filesystem-scoped**: `srw-------` inside `drwx------`.
- **Gateway disabled**: `[gateway] enabled = false` by default
  (`crates/jcode-config-types/src/lib.rs:1480-1497`) and disabled in the operator's
  config; `ss -ltnp` shows no jcode listener.

## 8. Gaps

| Gap | Why it matters here |
|:----|:--------------------|
| No privilege separation | The agent is effective root (§5); the MCP child inherits that |
| No env scrubbing by default | Denylist is narrow; jcode's `env` cannot restrict |
| No read-scope policy | Read scope is the real egress control (§4.1) and is undefined |
| No cluster-scope restriction | `kubectl` plus a root-readable kubeconfig puts the cluster in the agent's capability set |
| No hash pinning | A modified clone's `OW_tools` executes unchecked (§4.3) |
| Hooks are global-only | `pre_tool` is the only gating point and it is not per-project (`05_Enforcement_and_Governance.md` §3) |
| Credentials unresolved | §6 is a stub |

## 9. Target posture (recommended direction)

None of these are network controls; all of them reduce capability or read scope:

1. **Run the MCP child as a distinct uid** with its own kubeconfig and DB
   credentials, so it holds only what the workflow needs. This is the only
   mechanism that gives "internal to the sandbox" any teeth.
2. **Scrub the child environment** with a launcher (`env -i PATH=... OW_REPO_ROOT=...`)
   rather than relying on the denylist, since config `env` is additive.
3. **Use a `pre_tool` dispatcher** (global, keyed on `JCODE_HOOK_CWD`, per doc 05 §3)
   to block cluster-secret and credential-file reads from the agent loop.
4. **Decide one drift mechanism** and implement it: 06's hash pinning is proposed and
   unbuilt, 07's generated index is weaker (see `08_Comparison_06_vs_07.md` §2a).
5. **Define read scope explicitly**, since the model API is the only egress.

## 10. Verification list (S-series)

- **S-1** — MCP has no network surface: stdio-only claim traced to
  `crates/jcode-base/src/mcp/protocol.rs`
  and confirmed by `ss -ltnp` showing no jcode listener.
- **S-2** — The MCP child runs in the same guest as the jcode daemon, spawned by
  that daemon (`crates/jcode-base/src/mcp/client.rs:155-181`).
- **S-3** — The governed DB is guest-local (`127.0.0.1:51728`), verified against
  `_dsn.py`.
- **S-4** — Current privilege state recorded with commands and output (uid, groups,
  passwordless sudo, `CapEff`/`CapBnd`, virt type, file modes).
- **S-5** — Existing capability controls verified by test, not by reading: dry-run
  default, explicit `artifact_id`, in-repo target refusal, read-only allowlist.
- **S-6** — The env denylist gap is stated with the exact key patterns that pass
  through.
- **S-7** — Credentials section is explicitly marked as a stub that must be
  developed.
- **S-8** — Every "moot" claim in §3 is justified by the topology in §2.

## 11. Reproduction commands

```bash
# S-1 no network surface
ss -ltnp | grep -i jcode || echo "no jcode listener"
grep -n "fn is_stdio" -A 8 crates/jcode-base/src/mcp/protocol.rs

# S-3 guest-local DB
grep -n "51728\|51729" /home/d/dev_env/clones/Overwatch/OW_tools/db_write_commands/_connections/_dsn.py

# S-4 privilege state
id; groups; sudo -n true && echo "passwordless sudo"; systemd-detect-virt
grep -E "^Cap(Eff|Bnd)" /proc/self/status
ls -l /etc/shadow /etc/rancher/k3s/k3s.yaml

# S-5 capability controls
python3 temp/mcp/ow_createspr/smoke_test.py
```

## 12. UNVERIFIED

- Whether any credential material is currently present in the jcode daemon's environment
  was not enumerated; §6 is a stub for that reason.
- The cluster's own secret inventory (what a `kubectl`-capable agent could read) was
  not enumerated.
- Whether the guest has outbound filtering beyond the model API was not tested.

**END.** This document changes no code and no configuration.
