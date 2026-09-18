---
# jcode-local frontmatter (SPR folder conversion, 2026-09-17).
# jcode is NOT governed by Overwatch's UDRS: no UDRS/ci_impacted/parent numeric
# ids are fabricated here. Only real, repo-verifiable values are used.
id: SPR-0009-P11
title: Overwatch backup - host HDD target versus in-guest backup directory
status: DRAFT
author: operator
created: 2026-09-18
domain: ENGINEERING
severity: Major
type: RESEARCH
version: "2026-09-18"
---

# SPR-0009-P11: Overwatch Backup (research)

## 0. Placement note

Like `10_Clone_Isolation.md`, this document is **topically outside SPR-0009** and is
recorded here by explicit operator decision as research, intended to migrate to
Overwatch later. The placement is intentional and acknowledged as inconsistent.

## 1. Intent versus observed state

**Intent:** backups live on the host HDD, not inside the sandbox; the path inside the
clone is a link only.

**Observed:** the link does not exist. `backups/` is a real directory inside the
sandbox, and it is the reason the guest disk is nearly full.

| Check | Result |
|:------|:-------|
| `clones/Overwatch/backups` type | real directory (`drwxrwxr-x`), not a symlink |
| Size | 49 GB |
| Filesystem | `/dev/vda2` ext4, 158 GB total, 120 GB used, **31 GB free (80%)** |
| Tracked by git | No: `.gitignore:68` ignores `backups/` |
| Present in other clones | No: `clones/Overwatch_1..5` have no `backups/` (they are `git clone`s, and the path is ignored) |
| Second block device in guest | None: `lsblk` shows only `vda` plus two CD-ROMs (`sr0`, `sr1`) |

## 2. The host plumbing already exists

The intended target is mounted and in use. From `/etc/fstab` and `/proc/mounts`:

```
host_dev_env    /mnt/host/dev_env      virtiofs  ro,nofail
vm_backups      /mnt/vm-backups        virtiofs  rw,nofail
vm_sandbox_jcode /mnt/vm-sandbox-jcode virtiofs  rw,nofail
```

`/mnt/vm-backups` is the host HDD target: **2.8 TB total, 986 GB used, 1.8 TB free**.
It already holds backup content:

- hourly `firecontrol_*.dump` files, ~30 MB each (hourly cadence, dates from 2026-09-14 onward)
- `dar-ow-158-n6` — 914 MB
- `dar-ow-158-n12-images` — 11 GB
- `baseline_premove_20260425_1437.dump` — 2.4 MB

So the state is **half-done**: the mount is real, working, and already the destination
for other backup classes; the clone's `backups/` directory was simply never moved onto
it and replaced with a link. A symlink alone cannot reach the host — the mount has to
exist first, and it does.

## 3. Impact of finishing it

Moving 49 GB out of the guest takes the root filesystem from 31 GB free to roughly
80 GB free. That is the largest single reclaim available, and it is a precondition for
any multi-clone or multi-user expansion, since the guest disk is the binding
constraint (see `10_Clone_Isolation.md` §2.2).

Note also that `backups/` being git-ignored means a `git clone` does **not** carry it.
Per-clone cost is therefore unaffected by backups: the measured feature clones are
239-854 MB each.

## 4. Migration plan and risks

1. **Move the content, then link.** A symlink to a target that does not yet hold the
   data produces a broken path and tools will either fail or write into the wrong
   place. Copy to `/mnt/vm-backups/<target>/`, verify (count and total size, plus a
   sample checksum), and only then remove the original and create the link.
2. **Symlinks can trip realpath-versus-root checks.** `praca_scaffold` already raises
   `ValueError` when a path is not under the project root
   (`OW_tools/praca_scaffold/cli.py:252` → `OW_tools/praca_scaffold/cli.py:53`), which is the same class of
   check that a symlinked path can break. Test the tools that write into `backups/`
   specifically, not just the move.
3. **Do not point six clones at one target.** If each clone links to the same host
   directory, six writers collide. Use a per-user or per-clone subdirectory, e.g.
   `/mnt/vm-backups/<user>/...`.
4. **virtiofs is not POSIX-complete.** Hardlinks, `flock`, and some rename semantics
   differ from ext4. Backup output is mostly write-once files, which fits well, but
   anything relying on locking in that directory must be tested before being trusted.
5. **Retention.** `/mnt/vm-backups` already holds hourly dumps and multi-GB image
   sets. Moving another 49 GB there is fine against 1.8 TB free, but the retention
   policy for the moved class should be stated rather than assumed.

## 5. Related pattern worth reusing

`/mnt/vm-sandbox-jcode` is a host-mounted, read-write virtiofs copy of a jcode home
(`config.toml`, `sessions/`, `cache/`, `builds/`, …). That is an existing, working
pattern for hosting per-user jcode homes on the host instead of on the guest disk, and
it is directly applicable to the multi-user layout in `10_Clone_Isolation.md` §3.

## 6. Verification list (B-series)

- **B-1** — `backups/` recorded as a real directory with its filesystem, size, and
  free-space impact, not as a link.
- **B-2** — The host mount recorded with its fstab entry, transport, size, and
  existing contents, so "the plumbing exists" is evidence rather than assumption.
- **B-3** — The `git clone` exclusion recorded, since it explains why other clones
  have no `backups/` and why per-clone cost is unaffected.
- **B-4** — Migration risks enumerated, including the realpath-check class that has
  already bitten this toolchain once.
- **B-5** — The reclaim figure (31 GB → ~80 GB free) stated as the consequence.

## 7. Reproduction commands

```bash
# B-1
ls -ld /home/d/dev_env/clones/Overwatch/backups
stat -c '%F %n' /home/d/dev_env/clones/Overwatch/backups
du -sh /home/d/dev_env/clones/Overwatch/backups
df -h / | tail -1

# B-2
grep -v '^#' /etc/fstab | grep -v '^$'
grep -E 'virtiofs' /proc/mounts
df -h /mnt/vm-backups | tail -1
ls -la /mnt/vm-backups | head

# B-3
git -C /home/d/dev_env/clones/Overwatch check-ignore -v backups
for c in /home/d/dev_env/clones/Overwatch_*; do ls -d "$c/backups" 2>/dev/null || echo "none: $c"; done

# B-5
lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT
```

**END.** This document changes no code and no configuration. No files were moved.
