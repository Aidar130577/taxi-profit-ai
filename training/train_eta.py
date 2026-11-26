#!/usr/bin/env python3
"""Train off-device. Accept only explicit, anonymized exports. Never auto-publish."""
import argparse
import json
import math
from pathlib import Path
from datetime import date
import numpy as np
from catboost import CatBoostRegressor

FEATURES = ["road_km","road_min","yandex_km","yandex_min","base_min","surcharge","hour_sin","hour_cos","weekday_sin","weekday_cos"]
MIN_SAMPLES = 200
MIN_TEST = 40

def valid(row):
    try:
        if row.get("schema") != 1 or row.get("confirmed") is not True:
            return False
        if not isinstance(row["sample_id"], str) or len(row["sample_id"]) != 64:
            return False
        date.fromisoformat(row["day"])
        values = [float(row[k]) for k in FEATURES]
        return (all(math.isfinite(v) for v in values)
                and 0.05 <= values[0] <= 300 and 0.5 <= values[1] <= 300
                and 0.05 <= values[2] <= 300 and 0.5 <= values[3] <= 300
                and 0.5 <= values[4] <= 300 and -1 <= values[5] <= 100000
                and all(-1.001 <= v <= 1.001 for v in values[6:])
                and 0.5 <= float(row["actual_min"]) <= 300)
    except (KeyError, ValueError, TypeError):
        return False

def score(actual,pred):
    err=np.abs(pred-actual)
    return {"mae_min":float(err.mean()), "mape":float(np.mean(err/actual)), "p90_min":float(np.quantile(err,.9))}

def arrays(rows):
    x=np.asarray([[float(r[k]) for k in FEATURES] for r in rows],dtype=np.float32)
    actual=np.asarray([float(r["actual_min"]) for r in rows])
    base=x[:,4].astype(float)
    return x,actual,base

def main():
    p=argparse.ArgumentParser()
    p.add_argument("exports",nargs="+",type=Path)
    p.add_argument("--out",required=True,type=Path)
    args=p.parse_args()
    unique={}
    conflicts=set()
    for file in args.exports:
        document=json.loads(file.read_text(encoding="utf-8"))
        if not isinstance(document,list): raise SystemExit("Expected anonymized export JSON array")
        for row in document:
            if not isinstance(row,dict) or not valid(row): continue
            key=row["sample_id"]
            if key in unique and unique[key] != row: conflicts.add(key)
            else: unique[key]=row
    rows=sorted([r for k,r in unique.items() if k not in conflicts],key=lambda r:r["day"])
    args.out.mkdir(parents=True,exist_ok=True)
    for filename in ("candidate.cbm","candidate.json"):
        (args.out/filename).unlink(missing_ok=True)
    report={"samples":len(rows),"conflicts":len(conflicts),"published":False,"status":"insufficient_data"}
    def finish():
        (args.out/"report.json").write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))
    if len(rows)<MIN_SAMPLES:
        finish();return
    boundary=rows[int(len(rows)*.8)]["day"]
    train=[r for r in rows if r["day"]<boundary]
    test=[r for r in rows if r["day"]>=boundary]
    if len(train)<MIN_SAMPLES-MIN_TEST or len(test)<MIN_TEST:
        report["status"]="insufficient_chronological_split";finish();return
    x,y,b=arrays(train)
    xt,yt,bt=arrays(test)
    model=CatBoostRegressor(iterations=240,depth=5,learning_rate=.035,l2_leaf_reg=8,
        loss_function="MAE",random_seed=47,thread_count=2,verbose=False,allow_writing_files=False)
    model.fit(x,np.clip(np.log(y/b),math.log(.65),math.log(1.35)))
    predicted=bt*np.clip(np.exp(model.predict(xt)),.65,1.35)
    median_factor=float(np.clip(np.median(y/b),.65,1.35))
    baseline=score(yt,bt);simple=score(yt,bt*median_factor);candidate=score(yt,predicted)
    report.update(train=len(train),test=len(test),test_start_day=boundary,baseline=baseline,
        median_baseline=simple,catboost=candidate,feature_order=FEATURES)
    if (candidate["mae_min"] < .95*min(baseline["mae_min"],simple["mae_min"])
        and candidate["mape"] <= min(baseline["mape"],simple["mape"])
        and candidate["p90_min"] <= baseline["p90_min"]):
        model.save_model(str(args.out/"candidate.cbm"))
        model.save_model(str(args.out/"candidate.json"),format="json")
        report["status"]="candidate_requires_independent_validation"
    else: report["status"]="rejected_no_improvement"
    finish()

if __name__=="__main__":main()
