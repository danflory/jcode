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
