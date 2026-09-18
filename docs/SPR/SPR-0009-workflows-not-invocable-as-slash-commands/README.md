---
# jcode-local frontmatter (SPR folder conversion, 2026-09-17).
# jcode is NOT governed by Overwatch's UDRS: no UDRS/ci_impacted/parent numeric
# ids are fabricated here. Only real, repo-verifiable values are used.
id: SPR-0009
title: workflows-not-invocable-as-slash-commands - Gemini workflows (and Overwatch .agents/workflows/*.md) are not invocable as slash commands in jcode
status: DRAFT
author: operator
created: 2026-09-17
domain: ENGINEERING
severity: Major
type: SPR.README
version: "2026-09-17"
---

# SPR-0009: workflows-not-invocable-as-slash-commands

This SPR reports and resolves a **capability gap** (not a defect): Gemini
workflows, and the equivalent Overwatch `.agents/workflows/*.md` set, are
procedures that jcode cannot execute as slash commands. They cannot be invoked
as `/name args`, and when surfaced at all they are read as reference text, never
executed as a procedure. The proposed fix is a decision, not a survey.

## Document Index

| Document | Type | Purpose |
|:---------|:-----|:--------|
| `README.md` | Index | This index + status + folder convention |
| `SPR-0009.md` | Anchor | Problem statement, evidence, scope, requested fix, verification list V-1..V-n |
| `01_Deficiency_Report.md` | Deficiency Report | Root design failure analysis (no command/registry concept in jcode) |
| `02_TP_Change_Report.md` | TP Change Report | TP gap classification (test/verification gap, no TP exists) |
| `03_Options_and_Decisions.md` | Decision | Option A/B/C/D tradeoffs + the recommendation and cross-cutting analysis |
| `04_Command_Surface_Contract.md` | Contract | The proposed custom command surface / interface contract |
| `05_Enforcement_and_Governance.md` | Governance | Governed-CI preservation; enforceable vs advisory split; global dispatcher keyed on `JCODE_HOOK_CWD` |
| `06_MCP_Server_OW_tools_Steps.md` | Steps | Build steps for a generated MCP server wrapping `OW_tools` Python entry points (an Option D instantiation), with registry/error/cwd contracts and the 8000-token exposure analysis |
| `07_MCP_Delivery_Plan.md` | Plan | Hybrid delivery plan (Option A surface + Option D execution) for the 2-series, with the deterministic-vs-judgment boundary and a DAR/RFC/do/check pipeline |
| `08_Comparison_06_vs_07.md` | Compare | How 06 and 07 relate: convergences, real divergences (hash pinning, exposure strategy), and what each resolves in the other |
| `09_Security_Model.md` | Security | Full security treatment: internal-only network posture, single trust domain, capability and read scope, provenance, measured containment state, and the credentials stub |
| `10_Clone_Isolation.md` | Research | Running parallel feature work without cross-talk: per-clone home vs per-user isolation, with measured costs and the two footguns |
| `11_Overwatch_Backup.md` | Research | Backup intent vs observed state: the in-guest 49 GB `backups/` directory, the host HDD mount that already exists, and the migration risks |

**Placement note (operator declaration).** Documents 10 and 11 are topically outside
SPR-0009. They are recorded in this folder as research by explicit operator decision,
on the understanding that they migrate to Overwatch later. The inconsistency is
intentional, not a folder-convention error.

## Open decisions and operator actions

These are recorded here because they are the residue of the research in this folder
and would otherwise live only in conversation. None of them is agent-executable
without an operator decision.

| # | Item | Type | Detail | Where |
|:--|:-----|:-----|:-------|:------|
| 1 | Is firecontrol **one governed record or one per VM**? | Decision | If a VM per entitlement becomes the unit, those VMs must be clients of a central DB or multiplying the VM multiplies the governed truth. | `10_Clone_Isolation.md` §3.5 |
| 2 | Narrow the pre-cutover postgres bind `0.0.0.0:5432` → `127.0.0.1` | Action | The instance is the pre-container local DB: designed RBAC registry, no governed schema, no live connections. `enabled-runtime`, so it will not return after reboot either way. | `09_Security_Model.md` §5.2 |
| 3 | Migrate the 49 GB `backups/` to `/mnt/vm-backups` and leave a symlink | Action | Move, verify, then link. Takes the guest from 31 GB to roughly 80 GB free. Offered; not performed. | `11_Overwatch_Backup.md` §4 |
| 4 | Define read scope / answer the credentials question | Decision | Credentials is an operator-declared stub that must be developed. The model-API egress channel cannot be closed by network policy and is the open security question. | `09_Security_Model.md` §6, §4.1 |
| 5 | Pick one drift mechanism (hash pinning vs generated index) | Decision | 06 proposes hash pinning and never built it; 07 specifies a generated index with no hash. | `08_Comparison_06_vs_07.md` §2a |

## Migration readiness (measured with Overwatch's own validator)

Because these documents are destined for Overwatch, readiness was measured with that
project's real tool rather than by inspection. From the Overwatch repo root:

```bash
python3 -m OW_tools.check_folder_frontmatter <this folder>
```

Observed on 2026-09-18: **22 violations, all FM-1/FM-2** on the 11 sub-documents —
`parent is '' — must be an integer UDRS serial ID pointing to the anchor`, and
`parent is '' but anchor ID is 'SPR-0009' — parent must match anchor's UDRS ID`.

One further violation was found and **fixed**: `02_TP_Change_Report.md` declared
`type: SPR.TP`, which the validator expects as `SPR.TP_CHANGE`. After the fix the count
went 23 → 22 and no FM-3 remains.

What this means for the migration:

- **The anchor passes.** The validator accepted `id: SPR-0009` and did not flag the
  anchor for `parent`.
- **The only remaining gap is the parent link on each sub-document, and it cannot be
  closed in this tree.** `parent` must be the anchor's integer UDRS serial id, which
  does not exist until the anchor is registered in Overwatch's UDRS. This folder's
  convention explicitly forbids fabricating UDRS ids, so leaving it open is correct
  rather than incomplete.
- **Closing it is the normal Overwatch flow**: register the anchor (`ow_write_ci`), then
  backpatch `parent` on each sub-document
  (`praca_scaffold backpatch-parent --dir <folder> --anchor-id <id>`), which is
  createSPR2 Step 2.5/2.6.
- **Control note.** The same validator reports
  `Cannot detect artifact type from folder name: DAR-OW-096_...` for a native Overwatch
  DAR folder, because it only recognizes `RFC-*`, `SPR-*`, and `CAR-*` prefixes. It is a
  valid gate for SPR-shaped folders, not a general-purpose one.

## Status

- **Created**: 2026-09-17
- **Status**: DRAFT (Confirmed — investigating)
- **Anchor**: `SPR-0009.md`
- **Severity**: Major
- **Branch**: `sessionCorruption` (created from `dev`)

## Folder Convention

Each SPR lives in its own folder under `docs/SPR/SPR-NNNN-<slug>/`. Numbering is
sequential and non-reused; `SPR-0009` is the next free number after `SPR-0008`.
Frontmatter follows the jcode-local convention established by
`docs/SPR/SPR-0008-sessionCorruption/`: `id`, `title`, `status`, `author`,
`created`, `domain`, `severity`, `type`, `version`. No fabricated UDRS ids,
`ci_impacted`, or numeric `parent` ids are used. This folder is documentation
only; it makes no code changes.
