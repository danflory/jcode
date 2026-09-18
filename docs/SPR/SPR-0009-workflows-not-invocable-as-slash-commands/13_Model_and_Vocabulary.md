---
# jcode-local frontmatter (SPR folder conversion, 2026-09-17).
# jcode is NOT governed by Overwatch's UDRS: no UDRS/ci_impacted/parent numeric
# ids are fabricated here. Only real, repo-verifiable values are used.
id: SPR-0009-P13
title: Model and vocabulary - project VM, workspace, lease
status: DRAFT
author: operator
created: 2026-09-18
domain: ENGINEERING
severity: Major
type: RESEARCH
version: "2026-09-18"
---

# SPR-0009-P13: Model and Vocabulary (research)

## 0. Scope and placement note

This document captures **only the part of the 2026-09-18 working session that is not
already written down**. The earlier material is documented elsewhere and is not
repeated here: the parallelism problem and per-clone versus per-user isolation in
`10_Clone_Isolation.md`, the security posture in `09_Security_Model.md`, the backup
question in `11_Overwatch_Backup.md`, the listener audit in `12_Sandbox_Listeners.md`,
and the delivery design in `06_MCP_Server_OW_tools_Steps.md` and
`07_MCP_Delivery_Plan.md`.

What is distinct here is the **model and its vocabulary**: project VM, workspace,
lease, entitlement, and availability. Like 10, 11 and 12, this is operator-declared
research placed in SPR-0009 despite being topically outside it, intended to migrate to
Overwatch later.

## 1. The model

- **One VM per project.** The VM is a virtual machine (a KVM guest, like this sandbox).
  It is the machine that holds a project's clone store, its tooling, and the root the
  operator is willing to grant. The VM is **never leased**; it persists.
- **Workspaces live inside the VM.** A workspace is the persistent unit of work: a
  **uid**, a **clone**, a **jcode home**, and a **socket**. It exists whether or not
  anyone is using it.
- **Workspaces are leased.** A lease is the temporary right to occupy a workspace,
  held by one occupant at a time.
- **An occupant is a person or an agent.** This is what makes "users could become
  agents" a small step rather than a redesign.
- **An entitlement is the right to acquire a lease** in a given project, with a role.
  It grants permission, not resources.
- **A broker** checks entitlements and issues leases.

The sentence that holds the model together: *the VM hosts workspaces, and a workspace
is leased to an occupant.*

This corrects an earlier framing in conversation, where the unit was described as a VM
per entitlement. It is not: entitlement is a permission, and the resource it grants
access to is a workspace inside a project VM.

## 2. Vocabulary

| Term | Definition | Avoid |
|:-----|:-----------|:------|
| **VM** | Virtual machine; one per project; persists | "instance" for the machine |
| **Project** | The unit that owns a VM | |
| **Workspace** | Persistent unit inside a VM: uid + clone + jcode home + socket | "user space" (that is a process address space), "slot" once the distinction from a lease matters |
| **Clone** | The git working copy inside a workspace | |
| **Lease** | Temporary right to occupy a workspace, one occupant at a time | using "lease" for the machine |
| **Occupant** | Person or agent holding a lease | |
| **Entitlement** | Right to acquire a lease in a project, with a role | "VM per entitlement" |
| **Broker** | Checks entitlements, issues leases | |
| **Availability** | idle **and** quiescent (see §4) | treating availability as one condition |
| **Quiescent** | Clean tree; branch committed and pushed | |
| **Idle** | No occupant | |

"OS user" is the mechanism, not the concept: keep it for the Unix account that
implements a workspace, and use **workspace** for the thing being provisioned.

## 3. What a uid does and does not create

Creating a Unix user does **not** create an address space. An address space belongs to
a process and is created at fork/exec; every process has one regardless of its owner.
A user account creates a **security principal**, and that is what matters here:

| A uid gives you | Why it isolates |
|:----------------|:----------------|
| Distinct uid and gid | The kernel enforces file permissions between occupants |
| A home directory | Its own jcode home, so its own sessions, memory, MCP config, logs |
| A private runtime dir (`/run/user/<uid>`) | Its own socket, so its own daemon |
| Optionally a cgroup scope | CPU and memory accounting per workspace |

What it does **not** give you: isolation between two processes running under the *same*
uid. Same-uid processes can signal each other and read each other's `/proc` entries.
The **uid is the isolation unit**, and a workspace without its own uid is not isolated
from another workspace sharing that uid.

For the model in §1 this means three concrete requirements per workspace, none of which
holds in this sandbox today (one uid, `d`, with all clones under
`/home/d/dev_env/clones/`): the clone moves under the workspace's own home or a private
group directory with `0700` permissions, the jcode home becomes the workspace's own,
and the runtime dir becomes the workspace's own.

**One step up, if ever wanted:** uid plus permissions stops an occupant from *reading*
another workspace, but not from *seeing* that other workspaces exist, and it does not
give separate filesystem views. Hiding existence, or giving each workspace its own view
of `/home` and `/tmp`, needs mount namespaces (bind mounts or `unshare`). That is the
layer a container would otherwise supply.

## 4. Availability: idle and quiescent

Availability has two conditions, and keeping them separate is what makes it checkable:

- **idle** — no occupant holds the workspace.
- **quiescent** — the clone has a clean tree and its branch is committed and pushed.

A workspace is **available** only when both hold. The state that needs its own name is
**idle but not quiescent**: the previous occupant left uncommitted work, so the next
occupant would inherit it. That is the dangerous case, and a single word for
availability hides it.

The handover sequence that follows: lease ends → quiescence check → next lease issued.

## 5. The database: inside the VM or outside

The operator's intent is to have the governed database **outside** the project VM, so
one governed record serves all projects. Consequences worth recording:

- **Today the DB is inside this VM** (the `firecontrol-db` pod behind the k3s hostport
  at `127.0.0.1:51728`, per `09_Security_Model.md` §2). So the arrangement described in
  §1 is **single-project by construction** at present.
- **Deferring the move is safe only while there is exactly one project VM.** The second
  project VM is the trigger: without the DB outside, each VM carries its own governed
  record and the shared truth stops being shared.
- **Moving it out changes what project-VM root means.** Right now root in this VM is a
  path to the governed record, because the DB is reachable from inside. With the DB
  outside, project-VM root stops being a path to the record, and the DB credential
  becomes the real boundary. That materially cheapens "grant the agent root in a project
  VM", which was the original reason for wanting a VM rather than the workstation.

## 6. Identity and entitlement

The operator's constraint: in a large organization a developer cannot be issued several
corporate identities. The resolution is to separate **identity** from **entitlement**:
the person holds one corporate identity, and is authorized for several principals. They
are not given identities; they are given entitlements.

Mechanisms, weakest to strongest:

1. **`authorized_keys` per account.** One key authorized in several accounts' files.
   Works today; weak attribution and revocation means editing N files.
2. **SSH certificates (recommended shape).** An internal CA signs the person's key with
   principals (`ow2`, `ow3`, ...) and a short expiry; the VM trusts the CA and carries a
   per-account `AuthorizedPrincipalsFile`. Revocation is central, attribution is the
   certificate ID.
3. **Kerberos/GSSAPI against AD.** `kinit` plus `auth_to_local` mapping. Requires the VM
   to be domain-joined (it is not) and asks AD to map one principal to several accounts,
   which many AD teams refuse.
4. **Switching inside a session (`su` or a sudoers rule).** Creates a shared secret or
   removes authentication from the identity boundary. Break-glass only.

Where a large corporation manages this, and the rule that governs the design: **identity
authority must live outside the VM**, because if the VM's own root is the identity
authority then whoever holds it can mint or become any identity.

| Layer | Owns |
|:------|:-----|
| Corporate IdP (AD, Entra, Okta, LDAP) | Who the person is; group membership |
| Entitlement / IGA (SailPoint, Saviynt, Omada) | "dan is entitled to ow2, ow3 on project X", with recertification |
| PAM / access broker (Teleport, Boundary, CyberArk, or a plain SSH CA) | Enforces it: issues short-lived certificates with principals, records sessions, revokes centrally |
| Configuration management / IaC (Ansible, Puppet, Terraform, cloud-init) | Generates the VM's local state: accounts, sudoers fragments, `sshd_config` blocks, principals files |
| Secrets management (Vault, cloud secret managers, CyberArk) | The VM's own secrets: per-workspace DB credentials and provider keys, issued at login rather than baked into each home |
| Audit / SIEM | Auth logs keyed to certificate IDs, plus session recording |

Current state, measured: no IdP integration at all on this guest (no `sssd`, no
`/etc/krb5.conf`, no `realm`, no `winbind`, no `adcli`), one non-system account (`d`,
uid 1000), and passwordless sudo for `d` via `/etc/sudoers.d/90-ow-d` (root-only, 0440).

## 7. What containerization does and does not do for authorization

- **It does not grant authorization.** The broker decides who may hold a workspace; the
  container is what the occupant lands in after that decision. "The container grants the
  access" is really "the broker grants it and the container is the result".
- **What it buys:** cheap per-lease instantiation (so a lease can track a session rather
  than a machine), a single SSH entry point that fronts provisioning, and exclusivity as
  a lock on the lease rather than a permission.
- **What it costs:** in-band enforcement disappears. Upstream research
  (`DAR-OW-096` R07, *Container Principal Model*) established that a container is a
  single principal, so `ow2` becomes a name for a pod rather than an identity the kernel
  enforces, and no permission inside it can distinguish two occupants. Exclusivity must
  then be enforced by the broker holding the lease, or by one instance per occupancy.
- **On a VM, the OS enforces `ow2 != ow3`.** On a container, the broker does. That is
  the trade, and it is why the VM form is the one that matches §3.

## 8. Verification list (V-series, distinct from earlier V-lists)

- **V-1** — The model is stated with VM per project, workspaces inside, leases as grants,
  and entitlement as permission, with the earlier "VM per entitlement" framing recorded
  as corrected.
- **V-2** — The vocabulary table defines each term and names the words to avoid.
- **V-3** — Workspace/uid is identified as the key concept, with what a uid creates and
  what it does not (same-uid processes are not isolated).
- **V-4** — Availability is split into idle and quiescent, with the idle-but-not-quiescent
  state named as the dangerous one.
- **V-5** — The database placement question records that the DB is currently inside this
  VM, that the second project VM is the trigger, and that moving it out changes what
  project-VM root means.
- **V-6** — Identity versus entitlement is separated, with mechanisms ordered and the
  large-corp management layers named, plus the measured current state (no IdP).
- **V-7** — The container-versus-VM authorization trade is stated with R07 as its basis.

## 9. Status of the claims

- Measured in this session: the absence of IdP integration, the single account and its
  sudo fragment, the DB being an in-guest pod behind 51728, the absence of host
  firewalling (`09_Security_Model.md` §5.1, §5.2).
- Design reasoning, not measured: the model in §1, the vocabulary in §2, the isolation
  requirements in §3, the handover sequence in §4, and the container trade in §7.

**END.** This document changes no code and no configuration.
