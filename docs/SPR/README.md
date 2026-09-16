# Software Problem Reports (SPR)

This directory holds **Software Problem Reports** (SPRs).

## What is an SPR?

A Software Problem Report (SPR) is a structured, self-contained record of a
defect, anomaly, or unexpected behavior observed in a software system. An SPR
captures enough information for someone who has never seen the issue to
understand it, reproduce it, and act on it, without needing to reconstruct the
original context from memory or conversation history.

An SPR is a *problem report*, not a general design note or proposal. It centers
on something that is wrong, missing, or behaving incorrectly, and it follows up
with the facts needed to investigate and resolve it.

## Why keep SPRs?

- **Traceability** — each reported problem has a single, durable record.
- **Reproducibility** — a written repro keeps the issue alive even if the
  original reporter is unavailable.
- **Accountability** — each SPR tracks its own status, from report through
  resolution.
- **Knowledge retention** — root causes and fixes are preserved for future
  reference without relying on memory.

## When to write an SPR

Write an SPR when you observe (or are asked to track) any of the following:

- A crash, panic, or hard failure.
- Incorrect behavior that contradicts documented or expected semantics.
- A missing feature whose absence causes a functional gap or regression.
- An integration defect, such as a provider or authentication incompatibility.
- A performance or resource problem (slowdown, leak, unbounded growth).
- A correctness or accounting problem (for example, cost or token accounting).

## Typical contents of an SPR

Each SPR is a single markdown file (for example, `SPR-0001.md`). A good SPR
includes the following sections:

| Section | Purpose |
|---------|---------|
| **ID + title** | `SPR-0001: <short title>` |
| **Status** | Proposed / Confirmed / Investigating / Fixed / Verified / Closed |
| **Severity** | Blocker / Critical / Major / Minor / Cosmetic |
| **Affected component** | Crate, module, feature, or subsystem |
| **Environment** | Version, branch, OS, config, provider (if relevant) |
| **Observed behavior** | What actually happened |
| **Expected behavior** | What should have happened |
| **Reproduction steps** | Minimal, concrete steps or commands |
| **Impact** | Who or what is affected and how badly |
| **Root cause (optional)** | Filled in once known |
| **Fix / resolution (optional)** | What changed to address it |
| **Follow-ups** | Any related work still outstanding |

## Numbering and naming

- SPR files are named `SPR-<NNNN>.md`, zero-padded, in monotonically increasing
  order (`SPR-0001.md`, `SPR-0002.md`, ...).
- Assign the next free number when a new report is created.
- Use a short, descriptive title after the ID.

## Status lifecycle

```
Proposed -> Confirmed -> Investigating
                                |
                                +-> Fixed -> Verified -> Closed
```

- **Proposed** — reported, not yet triaged.
- **Confirmed** — reproduced/validated.
- **Investigating** — actively being worked.
- **Fixed** — a change addresses it, awaiting verification.
- **Verified** — confirmed resolved against the reported repro.
- **Closed** — fully resolved; no further action expected.

An SPR may be reopened if the problem recurs or the fix is found incomplete.
