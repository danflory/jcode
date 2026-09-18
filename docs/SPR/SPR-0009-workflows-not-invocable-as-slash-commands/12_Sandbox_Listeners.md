---
# jcode-local frontmatter (SPR folder conversion, 2026-09-17).
# jcode is NOT governed by Overwatch's UDRS: no UDRS/ci_impacted/parent numeric
# ids are fabricated here. Only real, repo-verifiable values are used.
id: SPR-0009-P12
title: Sandbox listener inventory - the erroneous postgres and wildcard binds
status: DRAFT
author: operator
created: 2026-09-18
domain: ENGINEERING
severity: Major
type: RESEARCH
version: "2026-09-18"
---

# SPR-0009-P12: Sandbox Listener Inventory (research)

## 0. Placement note

Like `10_Clone_Isolation.md` and `11_Overwatch_Backup.md`, this document is
**topically outside SPR-0009** and is recorded here by explicit operator decision as
research, intended to migrate to Overwatch later. The placement is intentional and
acknowledged as inconsistent.

## 1. Purpose

Two findings from the sandbox audit in `09_Security_Model.md` §5 are developed here
because they need action rather than a footnote: a database that was installed in error,
and four wildcard listeners whose justification was never established. The second
finding needs a general rule, not just an inventory, because "should this bind be
wildcard?" will recur.

## 2. The erroneous postgres

The second database instance on this guest, `postgresql@16-main` on
`0.0.0.0:5432` with its data directory at `/var/lib/postgresql/16/main`, **was installed
in error and should be deleted immediately**: the expected database for this sandbox is
the `firecontrol-db` pod reached through the k3s hostport at `127.0.0.1:51728`, which is
what `~/.pgpass` resolves to and what the governed tooling actually uses, and this
instance is not it — it holds no application data at all (only the `postgres`,
`template0`, and `template1` defaults, ~7.5 MB each), has no live connections, and its
42-role registry is simply the by-product of running the RBAC bootstrap against the
wrong instance before the schema was relocated into the pod. It is running only because
it was started at provisioning time (2026-09-15 18:00:34) with
`UnitFileState=enabled-runtime`, and it is reachable from the whole
`192.168.122.0/24` segment because nothing constrains inbound traffic (§8), so the cost
of leaving it is an unnecessary authenticated database endpoint in a guest that is
supposed to be internal-only.

**Deletion procedure — documented, not yet executed:**

```bash
# 1. Confirm nothing depends on it (already verified: no connections, no app databases)
ss -tn | grep ':5432' || echo "no connections"
psql -h /var/run/postgresql -d postgres -tAc "select datname from pg_database"

# 2. Stop and disable the service
sudo systemctl stop postgresql@16-main
sudo systemctl disable postgresql@16-main

# 3. Remove the cluster and the package if it is not otherwise required
sudo pg_dropcluster 16 main --stop      # removes /var/lib/postgresql/16/main
sudo apt-get purge -y postgresql-16 postgresql-client-16 postgresql-common
sudo rm -rf /etc/postgresql/16 /var/lib/postgresql/16
```

Re-verify afterwards with `ss -ltn | grep 5432` (expect no output) and by confirming
that the governed DB still answers: `python3 OW_tools/db_write.py query_ci_by_path --path
docs/praca/DAR/DAR-OW-096_Containerized_Amnesiac_Deployment/README.md` (expect id 12979).

## 3. Wildcard listeners: what they are

A listener bound to `0.0.0.0` (IPv4 any) or `::` (IPv6 any) accepts connections on
**every interface the host has**, including interfaces facing networks the operator does
not control. The alternatives are narrower and usually better:

| Bind form | Reachable from |
|:----------|:---------------|
| `127.0.0.1:PORT` | processes on this host only |
| `<interface-ip>:PORT` | the network attached to that one interface |
| `0.0.0.0:PORT` / `[::]:PORT` | **every** interface, including the outward-facing one |
| unix socket | processes with filesystem permission on that socket path |

The distinction that matters is not the port, it is whether an address the operator
chose is being restricted, or whether the service has delegated the decision to
"everything" and relies on something else to filter.

## 4. Why wildcard binds exist

They are rarely malice and usually one of four causes:

1. **Address unknown at configuration time.** A service that may run on a laptop, a VM
   with a DHCP lease, or a cloud instance with an address assigned after boot cannot
   write its own address into a config file, so it binds everything and expects a
   firewall to narrow it.
2. **Multi-homed or multi-node by design.** Kubernetes components are the canonical
   example: a kubelet must answer whichever address its control plane reaches it on, and
   the API server must answer agents whose addresses are not known when it starts.
3. **Package defaults written for the general case.** Distribution packages ship
   permissive defaults because the maintainer cannot know the deployment. `postgresql`
   ships `listen_addresses = '*'`; `sshd` ships `0.0.0.0`.
4. **Legacy of an earlier topology.** A service that was reachable across a network in a
   previous design keeps its bind after the consumers moved away. This is the shape of
   the erroneous postgres in §2.

## 5. When a wildcard bind is justified

Wildcard is justified only when **both** conditions hold:

- **(a) There is a legitimate remote consumer** on a network the operator controls and
  whose membership cannot be enumerated at configuration time. If every consumer is
  local, loopback is strictly better.
- **(b) An external boundary enforces who may reach it** — a host firewall with a
  default-deny policy, a security group, a CNI network policy, or a separate management
  network. The bind then expresses "any interface" while the boundary expresses "these
  peers", and the pairing is deliberate.

Where both hold, the wildcard is fine and often necessary. Where (a) holds but (b) does
not, the service is exposed to whatever the interface reaches. Where (b) holds but (a)
does not, the wildcard is unnecessary exposure that survives only because something else
is compensating — and compensation is exactly what gets removed later without anyone
re-checking the bind.

A useful corollary: on a single-node guest where every consumer is local, **no wildcard
bind passes this test**, because (a) fails regardless of (b).

## 6. The boundary check on this guest

Whether (b) holds here is measurable, and it does not:

| Check | Result |
|:------|:-------|
| Interfaces | `lo 127.0.0.1/8`, **`enp1s0 192.168.122.55/24`**, `cni0 10.42.0.1/24`, `flannel.1 10.42.0.0/32` |
| Host firewall default policy | **`-P INPUT ACCEPT`** — no default deny |
| `ufw` | inactive |
| Other INPUT rules | only k3s/kube-router insertions (`KUBE-ROUTER-INPUT`, `KUBE-FIREWALL`, `KUBE-NODEPORTS`, …) |
| Reachable segment | the libvirt default bridge, `192.168.122.0/24` (gateway `192.168.122.1`) |

So every wildcard bind below is reachable by anything on `192.168.122.0/24` — the host
and any other VM on that bridge — with nothing filtering. Condition (b) fails for all of
them, and condition (a) fails for all of them on a single-node guest. **No wildcard bind
here is justified.**

## 7. Inventory and judgement

| Bind | Service | Why it is wildcard | Justified here? | Fix |
|:-----|:--------|:-------------------|:----------------|:----|
| `0.0.0.0:5432`, `[::]:5432` | `postgresql@16-main` | Package default (`listen_addresses = '*'`) on an instance installed in error | **No** — and it should not exist at all | Delete per §2 |
| `0.0.0.0:22`, `[::]:22` | `sshd` | Cause 1: must accept a login before its address is known | **Not as configured** — nothing restricts who may connect; key-only auth is the only control | Bind the management interface or add a default-deny INPUT policy allowing 22 from the host only |
| `*:6443` | k3s API server | Cause 2: agents must reach the server on its advertised address | **Not on a single node** with no remote agents | Bind the node address, or restrict 6443 to the host |
| `*:10250` | kubelet | Cause 2: the control plane reaches kubelets to exec, fetch logs, and run probes | **Not on a single node** with no external control plane | Restrict to the pod/cluster networks; note kubelet's own authentication settings are a separate control to verify |
| `127.0.0.1:51728` | k3s hostport → `firecontrol-db` pod | n/a — loopback | Yes, this is the correct form | none |
| `127.0.0.1:10010`, `127.0.0.1:10248-10259`, `127.0.0.1:6444`, `:36411`, `:41837`, `:44763` | k3s internals and local services | n/a — loopback | Yes | none |
| `127.0.0.53:53`, `127.0.0.54:53` | systemd-resolved | n/a — loopback | Yes | none |
| unix socket `/run/user/1000/jcode.sock` (0600) | jcode daemon | n/a — filesystem-scoped | Yes, and it is the model to copy | none |

The jcode daemon is worth naming as the reference pattern: it exposes **no network
socket at all**, and its control surface is a unix socket in a `0700` directory with
`0600` permissions, so reach is decided by filesystem permission rather than by a bind
address. Where a service can be local, that is the shape to prefer.

## 8. Recommended posture

1. **Delete the erroneous postgres** (§2). It fails every justification test and has no
   consumer.
2. **Adopt a default-deny inbound policy** on the guest, then allow only what is
   actually needed: `22` from the host, and the cluster ports from the cluster networks.
   Until such a policy exists, the wildcard binds are the exposure, not a detail.
3. **Re-judge each remaining wildcard bind against §5** rather than leaving it at the
   package or upstream default. On a single-node guest, the expected answer is loopback
   or the node address for every one of them.
4. **Treat new wildcard binds as findings.** The audit that produced this document was
   triggered by one unexplained listener; the cheap version of that check is
   `ss -ltn | grep -v 127.0.0.1` run whenever the guest changes.

## 9. Verification list (L-series)

- **L-1** — The erroneous postgres is identified as such with its measured state, and
  the deletion procedure is written down with a post-deletion verification step.
- **L-2** — "Wildcard listener" is defined against the narrower alternatives, so the
  judgement is not a matter of taste.
- **L-3** — The justification rule states both required conditions (remote consumer,
  external boundary), so single-node cases are decided by rule rather than by opinion.
- **L-4** — The boundary check is measured on this guest, not assumed: default-ACCEPT
  policy, inactive `ufw`, and the reachable segment.
- **L-5** — Every listener in the guest is classified, including the loopback ones and
  the unix socket, so "no findings" is distinguishable from "not looked at".

## 10. Reproduction commands

```bash
# L-1 erroneous postgres
ss -ltn | grep 5432
systemctl is-active postgresql@16-main; systemctl is-enabled postgresql@16-main
psql -h /var/run/postgresql -d postgres -tAc "select datname from pg_database"

# L-4 boundary check
ip -4 -o addr show
sudo iptables -S INPUT | head
sudo ufw status

# L-5 full inventory
ss -ltn | awk 'NR>1 {print $4}' | sort -u
ss -ltnp | grep -i jcode || echo "jcode binds no network socket"
ls -l /run/user/1000/jcode.sock
```

**END.** This document changes no code and no configuration. The deletion in §2 has not
been executed.
