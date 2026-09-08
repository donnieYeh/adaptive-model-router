---
name: adaptive-model-router
description: Deterministic cost-aware model router. Luna XHigh performs semantic classification only; a local script selects the model using capability gates, economic cost, latency, and marginal return.
---

# Adaptive Model Router

## Architecture

Split routing into two layers.

### Layer A — semantic classifier (Luna XHigh)

Do NOT choose the final model.

Read the current task context and emit ONLY the routing parameters:

```json
{
  "R": 0,
  "A": 0,
  "C": 0,
  "Q": 0,
  "input_tokens": 0,
  "output_tokens": 0,
  "cached_input_ratio": 0.0,
  "stateful_agent_runtime": false,
  "semantic_confidence": 0.8
}
```

Definitions:

- `R`: static reasoning depth, 0–3.
- `A`: agentic/environmental difficulty, 0–3.
- `C`: context/state complexity, 0–3.
- `Q`: reliability requirement, 0–3.
- `input_tokens` / `output_tokens`: best estimates for the execution model, not the router itself.
- `cached_input_ratio`: expected fraction of reusable cached input.
- `stateful_agent_runtime`: true only if execution provides persistent reasoning/state machinery comparable to a provider adapter / durable agent state.
- `semantic_confidence`: confidence in classification.

The semantic classifier MUST NOT manually compare model prices, benchmark scores, or latency.

### Layer B — deterministic optimizer

Run:

```bash
python router.py --task task.json
```

The script:

1. reads `model_matrix.json`;
2. reads `routing_policy.json`;
3. calculates required ARC capability thresholds;
4. applies the hard HOLD gate;
5. eliminates incapable candidates;
6. estimates direct and expected total economic cost;
7. compares latency;
8. uses marginal efficiency only as a final tie-break;
9. returns route + fallback.

Objective order is strict:

`HOLD > economic cost > latency > marginal return`

This is lexicographic optimization, not a weighted-score contest.

---

# Freshness / metadata update

Before routing, inspect `model_matrix.json.meta.updated_at` and `routing_policy.json.freshness`.

If metadata is stale, missing, or inconsistent, refresh it before relying on the result.

Refresh sources in this order:

1. Official OpenAI model documentation — model IDs, availability, effort support, context limits.
2. Official OpenAI pricing — input / cached-input / output pricing.
3. ARC Prize Verified Results — ARC-AGI-1 / 2 / 3 by model and effort.
4. Reproducible fixed-workload latency sources or deployment-local telemetry.

Important rules:

- ARC-AGI-3 Standard Harness and Provider Adapter values must remain separate.
- Use Standard Harness for cross-generation routing unless the execution runtime actually has equivalent persistent state.
- Never store a latency number without workload identity and measurement date.
- Never replace verified values with guesses after refresh failure.
- If stale metadata can materially change the route, lower confidence or choose modest capability headroom.

The data refresh operation may be implemented by an environment-specific fetch/update command. After refresh it must update:

- `meta.updated_at`
- per-source `last_checked_at`
- per-source `last_success_at`
- source `status`
- `meta.change_log`

---

# Semantic classification rubric

## R
- R0: transform/extract/rewrite/simple summarize/classify.
- R1: infer/apply clear rules; ordinary structured analysis/debugging.
- R2: substantial multi-step reasoning; interacting constraints; causal/hypothesis analysis.
- R3: frontier closed-world reasoning; long dependency chains, difficult proofs/novel algorithms/research-grade synthesis.

## A
- A0: closed context.
- A1: straightforward retrieval.
- A2: adaptive investigation where findings determine next search/action.
- A3: sustained explore → model → plan → act → observe → revise loop.

## C
- C0: small/local context.
- C1: several docs/files/functions.
- C2: large context with many cross-dependencies.
- C3: evolving state across many actions/steps.

## Q
- Q0: cheap/easy-to-detect failure.
- Q1: normal productivity.
- Q2: meaningful rework/decision cost.
- Q3: expensive, consequential, or hard-to-detect failure.

Do not use task length, "coding", "math", or "web access" as direct proxies for difficulty.

---

# Execution

1. Perform semantic classification.
2. Write classification to a temporary `task.json`.
3. Run `router.py`.
4. If router returns `NO_HOLD_CANDIDATE`, escalate to the strongest available runtime or return that no registered candidate meets the configured HOLD threshold.
5. Otherwise dispatch to `route.model / route.effort`.
6. If execution hits the fallback trigger, dispatch to the returned fallback.
7. Record actual latency, tokens, retries, and outcome when telemetry is available. This telemetry should later feed a separate local latency/reliability dataset rather than overwriting public benchmark data.

---

# Output to caller

Return concise routing metadata:

- Route
- R/A/C/Q
- metadata freshness
- estimated cost
- expected latency source
- fallback
- confidence

Do not expose internal benchmark arithmetic unless diagnostics are requested.
