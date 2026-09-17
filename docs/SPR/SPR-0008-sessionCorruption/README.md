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
type: SPR.README
version: "2026-09-17"
---

# SPR-0008: sessionCorruption — client-local session state overrides server session identity and working directory

## Document Index

| Document | Type | Purpose |
|:---------|:-----|:--------|
| `SPR-0008.md` | Anchor | Problem statement, root cause, scope, VCL (V-1..V-4) |
| `01_Deficiency_Report.md` | Deficiency Report | Root design failure analysis (client-local-state-as-authority class) |
| `02_TP_Change_Report.md` | TP Change Report | Test gap classification (V-1..V-6); no TP/no parent TP exists |
| `03_Tool_and_Design.md` | Design | Session-prune tool documentation and the prioritized new design (P1..P11) |
| `04_Semantic_Index_Options.md` | Options Report | Options for a persistent semantic index of the jcode source tree, with a ranked recommendation |

## Status

- **Created**: 2026-09-17
- **Status**: DRAFT (Confirmed — investigating)
- **Anchor**: `SPR-0008.md`
- **Severity**: Major
- **Branch**: `sessionCorruption` (created from `dev`)
