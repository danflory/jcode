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
type: SPR.EVIDENCE
version: "2026-09-18"
---

# SPR-0010: Cost Evidence

Date: 2026-09-18
Environment: project sandbox VM (`sandbox` → `d@192.168.122.55`),
`~/dev_env/clones/Overwatch/`

This report records the measurements that establish SPR-0010's impact, the
method used to obtain them, and one correction to a tool result that was relied
on mid-investigation and later found to be wrong.

## 1. Rate cards (DeepInfra, fetched live 2026-09-18)

| Model | Cached input | Uncached input | Output |
|---|---|---|---|
| `deepseek-ai/DeepSeek-V4-Flash-0731` | $0.015 | $0.06 | $0.18 |
| `deepseek-ai/DeepSeek-V4.1-Flash` | $0.006 | $0.20 | $0.60 |

Note the **inversion**: the more expensive model has the cheaper cached rate
(`V4.1-Flash` cached is $0.006 vs `V4-Flash-0731`'s $0.015, 2.5x cheaper), while
costing 3.33x more on both uncached input and output. This inversion is why a
suppressed cache hit rate does not merely inflate cost, it distorts which model
appears optimal. Fetch with:

```bash
curl -s "https://api.deepinfra.com/models/<model-id>" | \
  python3 -c "import sys,json; print(json.load(sys.stdin)['pricing'])"
```

`V4.1-Flash` reported `discount: 0.3`, `discount_ends_at: null` — the $0.20/$0.60
figures are discounted and may change.

## 2. Common-prefix measurement (the core evidence)

Measured across 13 worker (child) sessions from `~/.jcode/sessions/*.json` in
the sandbox VM, grouped by model, longest common prefix computed per group:

| Model | Workers | Common prefix |
|---|---|---|
| `DeepSeek-V4.1-Flash` | 3 | **60 chars** |
| `DeepSeek-V4-Flash-0731` | 8 | **60 chars** |
| `DeepSeek-V4-Flash` | 2 | **60 chars** |

All three truncate at the same point, mid-timestamp:

```
<system-reminder>\n# Session Context\nDate: 2026-09-18\nTime: 0
```

Method: extract `messages[0].content[].text` (joining text blocks), then compute
the longest common prefix pairwise across the group. The measurement is
robust — it holds across three different models, so it is not a sampling
artifact.

## 3. Role-split cache hit rates

The aggregate figure reported by `model_cost_replay` was found to be wrong (see
§5). The correct figures, computed directly from `messages[].token_usage`:

| Role | Model | Turns | Cache read | Uncached in | Hit rate |
|---|---|---|---|---|---|
| root | `DeepSeek-V4.1-Flash` | 664 | 150,285,952 | 6,727,143 | **95.7%** |
| child | `DeepSeek-V4.1-Flash` | 99 | 6,361,472 | 240,254 | **96.4%** |
| child | `DeepSeek-V4-Flash-0731` | 151 | 8,072,192 | 810,427 | **90.9%** |
| child | `DeepSeek-V4-Flash` | 28 | 1,318,912 | 178,188 | **88.1%** |
| root | `DeepSeek-V4-Flash-0731` | 37 | 1,729,536 | 212,713 | **89.0%** |

**The child figures are the ones SPR-0010 suppresses.** Workers on
`V4-Flash-0731` sit at 90.9%. Whether a stable prefix lifts them high enough to
change the optimal worker model depends on the break-even in §4.

Cost of the observed mixes on each card:

| Role | Observed mix | On `V4-Flash-0731` | On `V4.1-Flash` |
|---|---|---|---|
| root | 152.0M cached, 6.94M uncached, 0.47M out | $2.78 | **$2.58** |
| child | 15.75M cached, 1.23M uncached, 0.22M out | **$0.35** | $0.47 |

The coordinator is *already* cheaper on `V4.1-Flash` despite its 3.33x list
price, because its traffic is 95.7% cached and its cached rate is the lowest of
the three. This confirms the tier split (`V4.1-Flash` coordinator,
`V4-Flash-0731` workers) is correct as configured, and locates the defect's cost
entirely in the worker column.

## 4. Break-even analysis for the worker tier

Holding the observed child `output:input` ratio (0.0128) fixed and varying the
cache hit rate:

| Hit rate | `V4-Flash-0731` | `V4.1-Flash` | Cheaper |
|---|---|---|---|
| 90.0% | 0.02181 | 0.03310 | `V4-Flash-0731` |
| 90.9% (observed) | 0.02140 | 0.03135 | `V4-Flash-0731` |
| 95.0% | 0.01956 | 0.02340 | `V4-Flash-0731` |
| 96.4% | 0.01893 | 0.02068 | `V4-Flash-0731` |
| **97.58%** | — | — | **break-even** |

**Break-even is 97.58%.** Below it, `V4-Flash-0731` is the correct worker
model. Workers currently sit at 90.9%, so the configured choice is correct
today, and SPR-0010 is the reason they are not closer to the break-even.

This is the concrete stake: a stable prefix is the mechanism by which the worker
tier could legitimately be reconsidered, and without it the question cannot be
answered.

## 5. Correction: `model_cost_replay` `mix` accounting defect

Mid-investigation, `OW_tools/model_cost_replay` reported an aggregate
`cache_hit_rate` of **0.4881** across 19 sessions / 986 turns. That figure is
**wrong** and was relied upon before being caught.

**Cause.** The tool sums `input_tokens` as the uncached class without
subtracting the portion already counted as cached. In jcode's session format,
`token_usage.input_tokens` is the *total* input for the call, with
`cache_read_input_tokens` a subset of it. Treating the two as disjoint
double-counts input and roughly halves the apparent hit rate.

**Correct figure.** Summing directly with `uncached = input_tokens −
cache_read_input_tokens` yields per-role hit rates of 88–96% (§3), not 48.8%.

**Consequence if uncorrected.** A break-even computed against the 48.8% mix gave
**94.5%**, versus the correct **97.58%** from the child mix. Both the diagnosis
and the model-choice conclusion invert depending on which figure is used. This
defect is recorded as a follow-up to SPR-0010 and should be filed against
`model_cost_replay`.

## 6. Reproduction

Token counts live under `messages[].token_usage` — **not** `usage`. Available
fields: `cache_read_input_tokens`, `input_tokens`, `output_tokens`. Session files
also carry `model` and `parent_id`, which is how root/child separation is
derived (root = no `parent_id`).

To re-measure after the fix, recompute §2 (common prefix) and §3 (role-split hit
rates) with the same scripts. The §2 measurement is the direct verification of
V-1 in the anchor.

## 7. Caveats

- Costs here are **token-based only**. They do not model cache-write charges,
  retries, or tokens billed but not reported.
- The price store is a snapshot; refresh from jcode before reusing these rates.
- The sandbox VM has its own `~/.jcode` (separate sessions and price store) from
  the host. Measurements in this report are from the sandbox. The host's session
  set differs, and child counts there were lower (13 vs an unknown host count).
- The `model_cost_replay` tool carries `authorized_by: PENDING-DAR` in its own
  README and is flagged there as a governance gap requiring an operator
  decision. It was used here for rate-card arithmetic only, and its `mix` output
  was independently corrected per §5.

## 8. Host baseline, larger sample (2026-09-18, post-fix investigation)

Re-measured on the **host** over the full session history rather than the
sandbox's small sample, and classified pre/post-fix by the *context block
ordering itself* (post-fix = `Date:` appears after `OS:`) rather than by version
string, after a version-string match proved unreliable (see §9).

| Tag | Role | Model | Turns | Cache read | Hit rate |
|---|---|---|---|---|---|
| pre-fix | child | `deepseek-ai/DeepSeek-V4-Flash-0731` | **2525** | 115,737,856 | **88.6%** |
| pre-fix | root | `deepseek-ai/DeepSeek-V4.1-Flash` | 1410 | 346,856,320 | **96.2%** |
| pre-fix | root | `deepseek-ai/DeepSeek-V4-Flash-0731` | 1830 | 230,458,624 | 54.9% |
| pre-fix | root | `zai-org/GLM-5.3-Flash` | 2155 | 403,748,224 | 87.5% |
| pre-fix | child | `zai-org/GLM-5.3-Flash` | 60 | 646,912 | 62.0% |
| POST-FIX | root | `deepseek-ai/DeepSeek-V4.1-Flash` | **2** | 26,624 | 98.2% |

Two conclusions:

1. **The worker baseline is 88.6% on 2525 turns**, materially more reliable than
   the 151-turn sandbox figure (90.9%) used earlier in this report. Against the
   97.58% break-even (§4), switching workers to `V4.1-Flash` costs more, and that
   conclusion now rests on a solid sample.
2. **Root/coordinator hit rate depends heavily on model**: 96.2% on
   `V4.1-Flash` versus 54.9% on `V4-Flash-0731` (1830 turns). This supports the
   configured split (coordinator on `V4.1-Flash`).

**Post-fix measurement is still outstanding.** Only 2 post-fix turns exist, from
throwaway probes, which is far too little to measure a rate. A real worker run
with meaningful token volume is required for V-4's second half.

## 9. Measurement pitfall found

An initial attempt to classify sessions as pre/post-fix by searching the session
JSON for the new build hash (`a007b44aa`) produced **false positives**: the hash
appears elsewhere in the file (e.g. in tool output and session metadata), so two
long-running *pre-fix* coordinator sessions were misclassified as post-fix and
reported as 97.6%/98.6% "post-fix" results. Their context blocks in fact showed
the old ordering (`Date`/`Time` before `OS`) and version `572f2eb0d`.

Classify by the **context block ordering** (does `Date:` appear after `OS:`), not
by a substring match on the file. Anything else reintroduces this error.
