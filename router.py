
#!/usr/bin/env python3
"""
Deterministic model router.

Semantic model responsibilities:
- classify task into R/A/C/Q
- estimate input/output token ranges
- identify whether stateful agent infrastructure is available
- optionally provide confidence and task-type flags

This script responsibilities:
- load model_matrix.json and routing_policy.json
- reject stale/invalid metadata if configured
- compute capability requirement
- filter candidates that cannot HOLD
- minimize expected economic cost
- then latency
- then maximize marginal return
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
import argparse, json, math, datetime as dt

HERE = Path(__file__).resolve().parent

ARC_KEYS = ("arc1", "arc2", "arc3")

@dataclass
class TaskSpec:
    R: int
    A: int
    C: int
    Q: int
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_ratio: float = 0.0
    stateful_agent_runtime: bool = False
    semantic_confidence: float = 0.8

def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def parse_time(s: str) -> dt.datetime:
    x = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    if x.tzinfo is None:
        x = x.replace(tzinfo=dt.timezone.utc)
    return x.astimezone(dt.timezone.utc)

def age_hours(s: str, now: Optional[dt.datetime] = None) -> float:
    now = now or dt.datetime.now(dt.timezone.utc)
    return (now - parse_time(s)).total_seconds() / 3600.0

def dominant_weights(task: TaskSpec) -> Dict[str, float]:
    """
    Maps task class to capability demand.
    Weights are intentionally simple and policy-controlled.
    """
    # Static baseline
    if task.R <= 0:
        w = {"arc1": 0.85, "arc2": 0.15, "arc3": 0.0}
    elif task.R == 1:
        w = {"arc1": 0.75, "arc2": 0.25, "arc3": 0.0}
    elif task.R == 2:
        w = {"arc1": 0.15, "arc2": 0.80, "arc3": 0.05}
    else:
        w = {"arc1": 0.05, "arc2": 0.90, "arc3": 0.05}

    # Agentic shift
    if task.A == 1:
        w["arc3"] += 0.05
        w["arc2"] += 0.05
        w["arc1"] -= 0.10
    elif task.A == 2:
        w["arc3"] += 0.35
        w["arc2"] += 0.15
        w["arc1"] -= 0.50
    elif task.A >= 3:
        w = {"arc1": 0.05, "arc2": 0.20, "arc3": 0.75}

    # Normalize
    for k in w:
        w[k] = max(0.0, w[k])
    s = sum(w.values())
    return {k: v / s for k, v in w.items()}

def required_thresholds(task: TaskSpec, policy: Dict[str, Any]) -> Dict[str, float]:
    """
    Produces per-axis minimum scores (0..100).
    This is the capability gate; cost is considered only afterwards.
    """
    table = policy["capability_thresholds"]

    req = {"arc1": 0.0, "arc2": 0.0, "arc3": 0.0}

    # R thresholds
    rrow = table["R"][str(task.R)]
    for k in ARC_KEYS:
        req[k] = max(req[k], float(rrow.get(k, 0.0)))

    # A thresholds
    arow = table["A"][str(task.A)]
    for k in ARC_KEYS:
        req[k] = max(req[k], float(arow.get(k, 0.0)))

    # Reliability/context headroom
    headroom = (
        float(policy["headroom"]["Q"][str(task.Q)]) +
        float(policy["headroom"]["C"][str(task.C)])
    )

    # Apply headroom only to active axes.
    weights = dominant_weights(task)
    for k in ARC_KEYS:
        if weights[k] > 0.08 and req[k] > 0:
            req[k] = min(100.0, req[k] + headroom)

    return req

def capability_scores(entry: Dict[str, Any], task: TaskSpec) -> Dict[str, float]:
    """
    Selects the appropriate ARC3 score by runtime capability.
    """
    arc = entry["capability"]
    arc3_key = "arc3_provider_adapter" if task.stateful_agent_runtime else "arc3_standard"
    return {
        "arc1": float(arc.get("arc1", 0.0)),
        "arc2": float(arc.get("arc2", 0.0)),
        "arc3": float(arc.get(arc3_key, arc.get("arc3_standard", 0.0))),
    }

def hold_margin(scores: Dict[str, float], req: Dict[str, float], weights: Dict[str, float]) -> Tuple[bool, float]:
    """
    Hard axis gate + weighted surplus.
    Any required axis below threshold => FAIL.
    """
    for k in ARC_KEYS:
        if req[k] > 0 and scores[k] + 1e-9 < req[k]:
            return False, min(scores[k] - req[k], 0.0)

    surplus = sum(weights[k] * (scores[k] - req[k]) for k in ARC_KEYS)
    return True, surplus

def direct_cost(entry: Dict[str, Any], task: TaskSpec) -> float:
    p = entry["pricing_usd_per_million_tokens"]
    in_tok = max(task.input_tokens, 0)
    out_tok = max(task.output_tokens, 0)
    cached = min(max(task.cached_input_ratio, 0.0), 1.0)

    uncached_in = in_tok * (1.0 - cached)
    cached_in = in_tok * cached

    return (
        uncached_in * float(p.get("input", 0.0)) +
        cached_in * float(p.get("cached_input", p.get("input", 0.0))) +
        out_tok * float(p.get("output", 0.0))
    ) / 1_000_000.0

def expected_total_cost(entry: Dict[str, Any], task: TaskSpec, margin: float, policy: Dict[str, Any]) -> float:
    """
    Deterministic expected-cost approximation.
    We do NOT pretend this is a calibrated probability model.
    It imposes a retry/escalation penalty when capability margin is thin.
    """
    base = direct_cost(entry, task)

    risk_cfg = policy["failure_risk"]
    # Thin margin => larger deterministic risk penalty.
    # Higher Q/C also amplifies penalty.
    margin_scale = float(risk_cfg["margin_scale"])
    base_risk = float(risk_cfg["base_risk"])
    q_mult = float(risk_cfg["Q_multiplier"][str(task.Q)])
    c_mult = float(risk_cfg["C_multiplier"][str(task.C)])

    risk = base_risk * math.exp(-max(margin, 0.0) / max(margin_scale, 1e-6))
    risk *= q_mult * c_mult
    risk = min(float(risk_cfg["max_risk"]), risk)

    recovery_multiplier = float(risk_cfg["recovery_cost_multiplier"])
    return base * (1.0 + risk * recovery_multiplier)

def latency_seconds(entry: Dict[str, Any], policy: Dict[str, Any]) -> float:
    obs = entry.get("latency", {})
    preferred = policy["latency"]["preferred_workload"]
    if preferred in obs and obs[preferred].get("seconds") is not None:
        return float(obs[preferred]["seconds"])

    vals = [
        float(v["seconds"]) for v in obs.values()
        if isinstance(v, dict) and v.get("comparable", False) and v.get("seconds") is not None
    ]
    if vals:
        return min(vals)

    # Unknown latency is not free. Give a soft penalty.
    return float(policy["latency"]["unknown_seconds_penalty"])

def marginal_efficiency(scores: Dict[str, float], req: Dict[str, float], weights: Dict[str, float], cost: float, latency: float) -> float:
    """
    Tie-breaker only, after HOLD > cost > latency.
    Measures useful capability surplus per small combined resource denominator.
    """
    useful = sum(weights[k] * max(0.0, scores[k] - req[k]) for k in ARC_KEYS)
    denom = max(cost, 1e-8) * (1.0 + latency / 60.0)
    return useful / denom

def validate_freshness(matrix: Dict[str, Any], policy: Dict[str, Any]) -> Dict[str, Any]:
    f = policy["freshness"]
    global_age = age_hours(matrix["meta"]["updated_at"])
    stale = global_age > float(f["max_age_hours"])
    return {
        "global_age_hours": round(global_age, 2),
        "stale": stale,
        "refresh_required": stale
    }

def iter_candidates(matrix: Dict[str, Any]):
    for model_id, model in matrix["models"].items():
        if not model.get("available", True):
            continue
        for effort, entry in model["efforts"].items():
            if not entry.get("available", True):
                continue
            yield model_id, model, effort, entry

def route(task: TaskSpec, matrix: Dict[str, Any], policy: Dict[str, Any]) -> Dict[str, Any]:
    weights = dominant_weights(task)
    req = required_thresholds(task, policy)

    candidates = []
    rejected = []

    for model_id, model, effort, entry in iter_candidates(matrix):
        scores = capability_scores(entry, task)
        hold, margin = hold_margin(scores, req, weights)
        row = {
            "model": model_id,
            "display_name": model.get("display_name", model_id),
            "effort": effort,
            "scores": scores,
            "hold": hold,
            "margin": round(margin, 4),
        }
        if not hold:
            rejected.append(row)
            continue

        dcost = direct_cost(entry, task)
        ecost = expected_total_cost(entry, task, margin, policy)
        lat = latency_seconds(entry, policy)
        me = marginal_efficiency(scores, req, weights, ecost, lat)

        row.update({
            "direct_cost_usd": dcost,
            "expected_total_cost_usd": ecost,
            "latency_seconds": lat,
            "marginal_efficiency": me,
        })
        candidates.append(row)

    if not candidates:
        return {
            "status": "NO_HOLD_CANDIDATE",
            "task": task.__dict__,
            "weights": weights,
            "requirements": req,
            "rejected": rejected,
        }

    # Lexicographic objective:
    # 1) HOLD already enforced
    # 2) expected economic cost
    # 3) latency
    # 4) maximize marginal efficiency
    candidates.sort(
        key=lambda x: (
            round(x["expected_total_cost_usd"], 8),
            round(x["latency_seconds"], 3),
            -x["marginal_efficiency"],
        )
    )

    best = candidates[0]

    # Fallback: choose next candidate with meaningfully stronger weighted capability,
    # otherwise simply next in sorted list.
    def weighted_score(row):
        return sum(weights[k] * row["scores"][k] for k in ARC_KEYS)

    best_ws = weighted_score(best)
    stronger = [x for x in candidates[1:] if weighted_score(x) >= best_ws + policy["fallback"]["min_weighted_capability_gain"]]
    fallback = min(
        stronger,
        key=lambda x: (x["expected_total_cost_usd"], x["latency_seconds"])
    ) if stronger else (candidates[1] if len(candidates) > 1 else None)

    return {
        "status": "OK",
        "task": task.__dict__,
        "weights": weights,
        "requirements": req,
        "route": best,
        "fallback": fallback,
        "top_candidates": candidates[:8],
        "metadata": validate_freshness(matrix, policy),
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, help="JSON file with R/A/C/Q and optional token/runtime fields")
    ap.add_argument("--matrix", default=str(HERE / "model_matrix.json"))
    ap.add_argument("--policy", default=str(HERE / "routing_policy.json"))
    args = ap.parse_args()

    matrix = load_json(Path(args.matrix))
    policy = load_json(Path(args.policy))
    task_data = load_json(Path(args.task))
    task = TaskSpec(**task_data)
    print(json.dumps(route(task, matrix, policy), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
