#!/usr/bin/env python3
from __future__ import annotations
import argparse, copy, datetime as dt, json, os, tempfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
DEFAULT_MATRIX=HERE/"model_matrix.json"
DEFAULT_POLICY=HERE/"routing_policy.json"
SOURCE_WINDOWS={
  "pricing":"pricing_max_age_hours",
  "model_specs":"model_spec_max_age_hours",
  "arc_benchmarks":"benchmark_max_age_hours",
  "latency":"latency_max_age_hours"
}
MODELS={"gpt-5.6-luna","gpt-5.6-terra","gpt-5.6-sol","gpt-6-astra"}
EFFORTS={"medium","high","xhigh","max"}

def load(p):return json.loads(Path(p).read_text(encoding="utf-8"))
def now():return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00","Z")
def parse(s):return dt.datetime.fromisoformat(s.replace("Z","+00:00"))
def age(s):return (dt.datetime.now(dt.timezone.utc)-parse(s)).total_seconds()/3600

def check(matrix,policy):
    out={}
    for source,wkey in SOURCE_WINDOWS.items():
        rec=matrix["sources"].get(source,{})
        ts=rec.get("last_success_at")
        a=None if not ts else age(ts)
        out[source]={"stale": a is None or a>policy["freshness"][wkey],"age_hours":None if a is None else round(a,1),
                     "urls":rec.get("urls",[])}
    out["refresh_required"]=any(v["stale"] for v in out.values())
    return out

def number(v,lo,hi,label):
    x=float(v)
    if not lo<=x<=hi:raise ValueError(f"{label} out of range: {x}")
    return x

def validate(payload):
    if payload.get("schema_version")!=3:raise ValueError("payload schema_version must be 3")
    if not payload.get("fetched_at"):raise ValueError("fetched_at required")
    for mid,mu in payload.get("model_updates",{}).items():
        if mid not in MODELS:raise ValueError(f"unknown model {mid}; explicit schema review required")
        for effort,eu in mu.get("efforts",{}).items():
            if effort not in EFFORTS:raise ValueError(f"unsupported routing effort {effort}")
            for k,v in eu.get("capability",{}).items():
                if k.startswith("arc"):number(v,0,100,f"{mid}/{effort}/{k}")
            for k,v in eu.get("pricing_usd_per_million_tokens",{}).items():
                number(v,0,10000,f"{mid}/{effort}/price/{k}")
            for wk,lv in eu.get("latency",{}).items():
                if "seconds" in lv:number(lv["seconds"],0,86400,f"{mid}/{effort}/latency/{wk}")

def merge(dst,src):
    for k,v in src.items():
        if isinstance(v,dict) and isinstance(dst.get(k),dict):merge(dst[k],v)
        else:dst[k]=copy.deepcopy(v)

def atomic(path,obj):
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix=path.name+".",suffix=".tmp")
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(obj,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def apply(matrix,payload):
    validate(payload)
    fetched=payload["fetched_at"]
    for sk,su in payload.get("source_updates",{}).items():
        rec=matrix["sources"].setdefault(sk,{})
        rec["last_checked_at"]=fetched
        rec["status"]=su.get("status","unknown")
        if su.get("status")=="ok":rec["last_success_at"]=fetched
        if "urls" in su:rec["urls"]=su["urls"]
        if "note" in su:rec["note"]=su["note"]
    for mid,mu in payload.get("model_updates",{}).items():
        if "available" in mu:matrix["models"][mid]["available"]=bool(mu["available"])
        for effort,eu in mu.get("efforts",{}).items():
            merge(matrix["models"][mid]["efforts"][effort],eu)
    matrix["meta"]["updated_at"]=fetched
    matrix["meta"]["status"]="refreshed"
    return matrix

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--check",action="store_true")
    ap.add_argument("--payload")
    ap.add_argument("--matrix",default=str(DEFAULT_MATRIX))
    ap.add_argument("--policy",default=str(DEFAULT_POLICY))
    a=ap.parse_args()
    matrix=load(a.matrix);policy=load(a.policy)
    if a.check:
        print(json.dumps(check(matrix,policy),ensure_ascii=False,indent=2))
        if not a.payload:return
    if a.payload:
        matrix=apply(matrix,load(a.payload))
        atomic(Path(a.matrix),matrix)
        print(json.dumps({"status":"UPDATED","freshness":check(matrix,policy)},ensure_ascii=False,indent=2))

if __name__=="__main__":main()
