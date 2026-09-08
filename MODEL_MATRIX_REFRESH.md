# MODEL_MATRIX_REFRESH.md

`model_matrix.json` must be refreshed when its source groups exceed the TTL in
`routing_policy.json`.

## Step 1 — Check

```bash
python refresh_matrix.py --check
```

Refresh only stale source groups unless a contradiction/model-availability
change requires broader checking.

## Step 2 — Agent retrieves evidence

The executing Agent should use current web/browser/search capability.

### Model specs / supported effort
Priority:
1. exact official OpenAI model page;
2. official OpenAI model comparison/docs.

Retrieve:
- exact model ID;
- availability;
- supported reasoning efforts;
- context/output limits if relevant;
- runtime/state features that affect ARC3 harness comparability.

### Pricing
Priority:
1. exact official model page;
2. official pricing/model comparison page.

Retrieve:
- input / cached-input / output price;
- long-context multiplier if applicable;
- execution-mode multipliers only when relevant.

Do not average conflicting official values. Prefer the exact-model page and
record the discrepancy.

### ARC capability
Use ARC Prize Verified Results exact model page.

Keep separately:
- ARC-AGI-1;
- ARC-AGI-2;
- ARC-AGI-3 Standard;
- ARC-AGI-3 Provider Adapter.

Never substitute Provider Adapter ARC3 for Standard unless runtime semantics match.

### Latency
Latency is workload-specific.

Priority:
1. same-workload local measurement supplied by user/runtime;
2. reproducible fixed-workload benchmark;
3. published reference benchmark.

Record workload identity. Never invent a universal latency number.

## Step 3 — Normalize into refresh payload

Example:

```json
{
  "schema_version": 3,
  "fetched_at": "2026-09-08T07:00:00Z",
  "source_updates": {
    "pricing": {
      "status": "ok",
      "urls": ["https://developers.openai.com/api/docs/models/gpt-5.6-luna"]
    }
  },
  "model_updates": {
    "gpt-5.6-luna": {
      "efforts": {
        "medium": {
          "pricing_usd_per_million_tokens": {
            "input": 0.2,
            "cached_input": 0.02,
            "output": 1.2
          }
        }
      }
    }
  }
}
```

Never write a value that was merely inferred from memory.

## Step 4 — Validate and atomically update

```bash
python refresh_matrix.py --payload refresh_payload.json
python refresh_matrix.py --check
```

If validation fails, keep the last-known-good matrix.

If web retrieval is unavailable, do not fabricate freshness. Tell the calling
Skill which source groups remain stale.

## New model policy

Do not auto-add a newly discovered model just because it exists. It first needs:
- supported effort mapping;
- economic multiplier or explicit policy;
- comparable capability evidence;
- optional latency evidence.

Until then it is not a routable candidate.
