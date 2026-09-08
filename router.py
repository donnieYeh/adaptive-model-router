#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, math
from pathlib import Path

HERE=Path(__file__).resolve().parent
AXES=("arc1","arc2","arc3")

def load(p): return json.loads(Path(p).read_text(encoding="utf-8"))

def requirement(profile, quota, policy):
    pos=float(policy["quota_to_requirement_position"][quota])
    out={}
    bands={}
    for axis in AXES:
        band=profile[f"{axis}_band"]
        lo,hi=policy["capability_bands"][axis][band]["range"]
        out[axis]=lo+pos*(hi-lo)
        bands[axis]={"band":band,"range":[lo,hi],"selected":out[axis]}
    return out,bands

def score(entry,stateful=False):
    c=entry["capability"]
    return {
      "arc1":float(c.get("arc1",0)),
      "arc2":float(c.get("arc2",0)),
      "arc3":float(c.get("arc3_provider_adapter",c.get("arc3_standard",0))) if stateful
             else float(c.get("arc3_standard",0))
    }

def hold(scores,req):
    failed=[a for a in AXES if req[a]>0 and scores[a] < req[a]]
    return not failed,failed

def headroom(scores,req):
    active=[a for a in AXES if req[a]>0]
    if not active:return 100.0
    return min(scores[a]-req[a] for a in active)

def cost_index(mid,effort,policy):
    return policy["cost_index"]["model_multiplier"][mid]*policy["cost_index"]["effort_multiplier"][effort]

def api_cost(entry,task):
    p=entry["pricing_usd_per_million_tokens"]
    i=max(0,int(task.get("input_tokens",0)))
    o=max(0,int(task.get("output_tokens",0)))
    cr=max(0.0,min(1.0,float(task.get("cached_input_ratio",0.0))))
    if i==0 and o==0:return None
    return (((1-cr)*i*p["input"])+(cr*i*p["cached_input"])+(o*p["output"]))/1_000_000

def latency(entry):
    obs=entry.get("latency",{})
    if "openai_build_hours_reference" in obs:
        return float(obs["openai_build_hours_reference"]["seconds"]),"reference"
    vals=[float(v["seconds"]) for v in obs.values() if v.get("comparable") and "seconds" in v]
    return (min(vals),"reference") if vals else (None,"unknown")

def dominates(a,b):
    # a dominates b if no worse on cost/time, no lower capability headroom,
    # and strictly better on at least one known dimension.
    if a["cost_index"]>b["cost_index"]: return False
    if a["headroom"]<b["headroom"]: return False
    at,bt=a["latency_seconds"],b["latency_seconds"]
    if at is not None and bt is not None and at>bt:return False
    # Unknown latency never gets used to claim time dominance.
    if at is None and bt is not None:return False
    strict=(a["cost_index"]<b["cost_index"] or a["headroom"]>b["headroom"])
    if at is not None and bt is not None and at<bt: strict=True
    return strict

def pareto(rows):
    return [r for r in rows if not any(o is not r and dominates(o,r) for o in rows)]

def uniq(rows):
    seen=set();out=[]
    for r in rows:
        k=(r["model"],r["effort"])
        if k not in seen: seen.add(k);out.append(r)
    return out

def representative(frontier, latency_pref, policy):
    econ=min(frontier,key=lambda r:(r["cost_index"], -(r["headroom"]), r["latency_seconds"] if r["latency_seconds"] is not None else math.inf))
    known=[r for r in frontier if r["latency_seconds"] is not None]
    fast=min(known,key=lambda r:(r["latency_seconds"],r["cost_index"])) if known else econ

    selected=[econ]
    if fast is not econ:selected.append(fast)

    # Optional headroom option: only if gain is meaningful and not absurdly expensive.
    cfg=policy["option_generation"]
    best_head=max(frontier,key=lambda r:(r["headroom"],-r["cost_index"]))
    if (best_head["headroom"]-econ["headroom"] >= cfg["headroom_min_gain_points"]
        and best_head["cost_index"] <= econ["cost_index"]*cfg["headroom_max_cost_ratio_vs_economy"]):
        selected.append(best_head)

    selected=uniq(selected)[:cfg["max_options"]]
    if len(selected)==1:
        selected[0]["role"]="optimal"
        return "AUTO_SELECT",selected,selected[0]

    for r in selected:
        if r is econ:r["role"]="economy"
        elif r is fast:r["role"]="fast"
        else:r["role"]="headroom"

    # Preference changes ordering/recommendation, not the underlying trade-off set.
    recommended=None
    if latency_pref=="patient":
        recommended=econ
    elif latency_pref=="fast":
        recommended=fast
    # "normal": deliberately no synthetic utility function.
    if recommended:
        selected=sorted(selected,key=lambda r:0 if r is recommended else 1)
    return "USER_CHOICE_REQUIRED",selected,recommended

def route(task,matrix,policy):
    profile=task["capability_profile"]
    quota=task["user_policy"]["quota_pressure"]
    lpref=task["user_policy"]["latency_preference"]
    req,bands=requirement(profile,quota,policy)
    stateful=bool(task.get("stateful_agent_runtime",False))
    candidates=[];rejected=[]

    for mid,m in matrix["models"].items():
        if not m.get("available",True):continue
        for effort,e in m["efforts"].items():
            if not e.get("available",True):continue
            s=score(e,stateful)
            ok,failed=hold(s,req)
            row={
              "model":mid,"display_name":m["display_name"],"effort":effort,
              "capability":s,"required":req,"failed_axes":failed,
              "headroom":headroom(s,req),
              "cost_index":cost_index(mid,effort,policy),
              "estimated_api_cost_usd":api_cost(e,task)
            }
            t,ts=latency(e);row["latency_seconds"]=t;row["latency_source"]=ts
            (candidates if ok else rejected).append(row)

    if not candidates:
        return {"status":"NO_HOLD_CANDIDATE","requirements":bands,"rejected":rejected}

    pf=pareto(candidates)
    pf.sort(key=lambda r:(r["cost_index"], r["latency_seconds"] if r["latency_seconds"] is not None else math.inf, -r["headroom"]))
    status,options,recommended=representative(pf,lpref,policy)

    return {
      "status":status,
      "user_policy":task["user_policy"],
      "requirements":bands,
      "pareto_count":len(pf),
      "options":options,
      "recommended":None if recommended is None else {"model":recommended["model"],"effort":recommended["effort"],"role":recommended["role"]},
      "pareto_frontier":pf
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--task",required=True)
    ap.add_argument("--matrix",default=str(HERE/"model_matrix.json"))
    ap.add_argument("--policy",default=str(HERE/"routing_policy.json"))
    a=ap.parse_args()
    print(json.dumps(route(load(a.task),load(a.matrix),load(a.policy)),ensure_ascii=False,indent=2))

if __name__=="__main__":main()
