---
# jcode-local frontmatter (SPR folder conversion, 2026-09-17).
# jcode is NOT governed by Overwatch's UDRS: no UDRS/ci_impacted/parent numeric
# ids are fabricated here. Only real, repo-verifiable values are used.
id: SPR-0010
title: unstable session context prefix - volatile timestamp in the first provider-visible message defeats prompt cache reuse across swarm workers
status: CONFIRMED
author: operator
created: 2026-09-18
domain: ENGINEERING
severity: Major
type: SPR.README
version: "2026-09-18"
---

# SPR-0010: Unstable Session Context Prefix — Volatile Timestamp in the First Provider-Visible Message Defeats Prompt Cache Reuse Across Swarm Workers

## Document Index

| Document | Type | Purpose |
|:---------|:-----|:--------|
| `SPR-0010.md` | Anchor | Problem statement, root cause, scope, VCL (V-1..V-4) |
| `01_Deficiency_Report.md` | Deficiency Report | Root design failure analysis (volatile-field-ordering class) |
| `02_TP_Change_Report.md` | TP Change Report | Test gap classification (V-1..V-4); no TP/no parent TP exists |
| `03_Cost_Evidence.md` | Evidence Report | `model_cost_replay` measurements, role-split cache hit rates, break-even arithmetic |
| `04_Fix_Explanations.md` | Fix Explanations | Explains the `build_session_context` reorder fix, mechanism, tests, residual risk, and the implemented `JCODE_TRACE` payload dump |

## Status

- **Created**: 2026-09-18
- **Status**: FIXED (verified against real payloads and live swarm workers)
- **Anchor**: `SPR-0010.md`
- **Severity**: Major
- **Branch**: `dev`

---
