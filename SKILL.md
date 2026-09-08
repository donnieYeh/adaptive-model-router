---
name: adaptive-model-router-v3
description: Stateless model router. Collects only quota/time preferences, refreshes model evidence, converts task semantics into capability bands, mathematically eliminates dominated candidates, and returns one best route or a small set of real trade-off options.
---

# Adaptive Model Router V3

## Core principle

The Skill is stateless with respect to task history.

It does NOT learn user preferences from history and does NOT maintain empirical
success telemetry. Each route is determined by:

`Current task + Current user policy + Current model matrix`

The only semantic routing model should be Luna XHigh. Luna XHigh must not
manually choose the final execution model.

## 0. Collect only decision-relevant user information

If the two values are not already supplied for the current route/session, ask:

1. `quota_pressure`
   - `tight` — 当前额度吃紧，优先降低额度消耗
   - `normal` — 当前额度正常
   - `loose` — 当前额度宽松，可提高能力余量

2. `latency_preference`
   - `patient` — 可以多等，愿意用时间换额度
   - `normal` — 正常；有明显 trade-off 就给选项
   - `fast` — 尽量快

Do not ask "how much quality do you want". Higher quality is not a useful
preference question.

Do not ask users to quantify seconds-per-token, money-per-minute, or a utility
coefficient.

## 1. Refresh model evidence before routing

Run:

```bash
python refresh_matrix.py --check
```

If `refresh_required=true`, follow `MODEL_MATRIX_REFRESH.md`.

The executing agent is responsible for web/browser retrieval; the script is
responsible for validation and atomic matrix update.

Never update benchmark/pricing/model availability from model memory alone.

## 2. Luna XHigh performs semantic classification only

Do NOT ask Luna to output an exact "ARC2-equivalent = 57.3".

Instead choose one discrete capability band for each axis:

```json
{
  "capability_profile": {
    "arc1_band": "A0",
    "arc2_band": "A3",
    "arc3_band": "A0"
  }
}
```

Band definitions live in `routing_policy.json`.

Interpretation:
- ARC1: rule abstraction / induction.
- ARC2: deep static multi-step/compositional reasoning.
- ARC3: adaptive agentic explore→act→observe→revise reasoning.

Choose the band by matching qualitative task requirements to the band meanings.
The deterministic router converts the band to an interval `[L,U]`.

Example: ARC2 A3 = `[45,65]`.

## 3. Quota pressure chooses position inside the requirement interval

No subjective quality question is used.

For every active capability axis:

`Requirement = L + p × (U-L)`

where:
- tight → p=0
- normal → p=0.5
- loose → p=1

Thus `[45,65]` becomes:
- tight → 45
- normal → 55
- loose → 65

This is a policy choice, not a claim that ARC score is a literal task success probability.

## 4. Relative quota/compute matrix

User-supplied model base multipliers:

- Luna = 1
- Terra = 10
- Sol = 20
- Astra = 40

User-supplied effort multipliers:

- Medium = 1
- High = 3
- XHigh = 6
- Max = 10

Compute Cost Index:

`CCI(model,effort) = model_multiplier × effort_multiplier`

Matrix:

| | Medium | High | XHigh | Max |
|---|---:|---:|---:|---:|
| Luna | 1 | 3 | 6 | 10 |
| Terra | 10 | 30 | 60 | 100 |
| Sol | 20 | 60 | 120 | 200 |
| Astra | 40 | 120 | 240 | 400 |

This CCI is a relative quota/compute assumption. It is NOT the API invoice.
Official token prices are kept separately in `model_matrix.json`.

## 5. HOLD filter

For candidate `i`, with capability vector `S_i` and task requirement `R`:

`HOLD(i) iff S_i,k >= R_k for every active axis k`

A candidate that fails HOLD is eliminated regardless of cost or speed.

No weighted average may rescue a failed active capability axis.

## 6. Mathematical elimination

For each HOLD candidate compute:

- capability headroom;
- CCI;
- estimated API direct cost when token estimates are supplied;
- workload-specific latency estimate when available.

Use 3D Pareto dominance.

Candidate A dominates B only when A is:
- no more expensive in CCI;
- no slower when both have comparable known latency;
- no lower in capability headroom;
- strictly better in at least one dimension.

Dominated candidates are removed.

Unknown latency must never be treated as zero or used to claim time dominance.

## 7. Generate representative choices, not a long model list

From the Pareto frontier generate at most 3 roles:

- `Economy`: lowest CCI that HOLDs.
- `Fast`: lowest known latency that HOLDs.
- `Headroom`: only when extra capability is materially larger and cost increase
  remains within policy limits.

If Economy == Fast and there is no material Headroom option:
return `AUTO_SELECT`.

If real trade-offs remain:
return `USER_CHOICE_REQUIRED`.

`latency_preference` changes presentation/recommendation only:
- patient → put Economy first;
- fast → put Fast first;
- normal → do not invent a synthetic utility function; present choices.

Do not convert time into money or token units.

## 8. User-facing output

For `AUTO_SELECT`, say approximately:

"最优项：Luna XHigh。它满足当前能力要求，且在有效候选中同时没有更值得展示的成本/时间 trade-off。相对额度成本约 6×；参考延迟约 59 秒。"

For `USER_CHOICE_REQUIRED`, show 2–3 concise options, e.g.:

"A — Economy: Luna Max，约 10×额度成本，参考延迟约 341 秒，能力刚好覆盖。  
B — Fast: Sol Medium，约 20×额度成本，参考延迟约 45 秒，能力余量更高。"

Then ask the user to choose A/B.

Always label benchmark latency as reference/workload-specific rather than a guarantee.

## 9. Run deterministic router

Build `task.json`:

```json
{
  "capability_profile": {
    "arc1_band": "A0",
    "arc2_band": "A3",
    "arc3_band": "A0"
  },
  "user_policy": {
    "quota_pressure": "tight",
    "latency_preference": "patient"
  },
  "input_tokens": 12000,
  "output_tokens": 2500,
  "cached_input_ratio": 0.0,
  "stateful_agent_runtime": false
}
```

Run:

```bash
python router.py --task task.json
```

Do not manually override a HOLD rejection merely because a model is cheaper.

## 10. Boundary conditions

- If no candidate HOLDs: return `NO_HOLD_CANDIDATE`; do not silently choose a weaker model.
- If latency is stale/unknown: still route by capability and CCI, but disclose
  that time comparison is incomplete.
- Provider Adapter ARC3 may only be used when the runtime really provides
  comparable persisted reasoning state; otherwise use Standard ARC3.
- Low/None are excluded from the default CCI routing matrix because the user
  has not assigned relative effort multipliers to them.
