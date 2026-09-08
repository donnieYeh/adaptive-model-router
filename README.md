# Adaptive Model Router V3

Stateless deterministic model router built around four abilities:

1. collect only quota pressure + latency preference;
2. instruct the executing Agent to refresh model evidence;
3. mathematically HOLD-filter and Pareto-eliminate candidates;
4. output one automatic route or 2–3 concrete options for the user.

Key files:
- `SKILL.md`
- `DECISION_FLOW.md`
- `MODEL_MATRIX_REFRESH.md`
- `router.py`
- `refresh_matrix.py`
- `routing_policy.json`
- `model_matrix.json`
- `example_task.json`

V3 intentionally removes:
- historical task-state learning;
- user "quality preference";
- time-to-token utility coefficients;
- exact LLM-predicted ARC-equivalent scores;
- weighted overall model scores.
