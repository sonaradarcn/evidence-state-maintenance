"""Stage 4 driver: replay every policy on the task streams (real arrivals and Poisson control) for all configurations.

Fact sets: ALL (1,419 kept facts; ESM, NEVER and the @oracle baselines), H150 (160 facts; every real-cost policy),
H150s (the 133 static H150 facts; adds CERT-v0h, which is static-only).
Configurations (one factor varied at a time around the default): volume x0.3 / x1 / x3, k = U{1,2,3} / 1 / 3,
Zipf exponent 1.0 / 0 (uniform) / 1.5.  Seeds 0..9 (task -> fact assignment, popularity order, Poisson times).

usage: python -m esm.stream.run -> results/stream/{agg.parquet, perfact.parquet, stale.parquet, imputation.json}
"""
import json, time
import numpy as np
import pandas as pd
from . import sim as S

SEEDS = range(10)
CONFIGS = {"default": (1.0, "u13", 1.0), "vol0.3": (0.3, "u13", 1.0), "vol3": (3.0, "u13", 1.0), "k1": (1.0, "k1", 1.0),
           "k3": (1.0, "k3", 1.0), "zipf0": (1.0, "u13", 0.0), "zipf1.5": (1.0, "u13", 1.5)}


def main():
    t0 = time.time()
    facts = S.load_facts()
    arr = pd.read_parquet(S.OUT / "arrivals.parquet")
    clk = pd.read_parquet(S.OUT / "clock.parquet")
    clock = {r: g.sort_values("t").time.to_numpy() for r, g in clk.groupby("repo")}
    sets = {"ALL": (list(facts), S.POL_ALL),
            "H150": ([i for i in facts if facts[i]["H150"]], S.POL_H),
            "H150s": ([i for i in facts if facts[i]["H150"] and facts[i]["slice"] == "static"], S.POL_HS)}
    AG, PF, ST, IMP = [], [], [], {}
    for sname, (ids, pols) in sets.items():
        M, imp = S.build_mats(facts, ids, pols)
        IMP[sname] = imp
        miss = {p: int((~m.ok).sum()) for p, m in M.items() if (~m.ok).any()}
        print(sname, len(ids), "facts; policies missing facts:", miss, f"{time.time() - t0:.0f}s", flush=True)
        by_repo = {}
        for i in ids:
            by_repo.setdefault(facts[i]["repo"], []).append(i)
        cfgs = CONFIGS if sname != "H150s" else {"default": CONFIGS["default"]}
        for cname, (vol, kmode, zs) in cfgs.items():
            for arrival in ("real", "poisson"):
                for seed in SEEDS:
                    tasks = S.gen_tasks(arr, clock, by_repo, arrival, vol, kmode, zs, seed)
                    res = S.evaluate(tasks, M, ids, facts)
                    key = {"set": sname, "config": cname, "arrival": arrival, "seed": seed}
                    AG.append(S.aggregate(res, M, ids, facts, tasks, key))
                    if cname == "default":
                        PF.append(S.per_fact(res, key))
                        ST.append(S.stale_windows(res, key))
                print(sname, cname, arrival, f"{time.time() - t0:.0f}s", flush=True)
    pd.concat(AG, ignore_index=True).to_parquet(S.OUT / "agg.parquet", index=False)
    pd.concat(PF, ignore_index=True).to_parquet(S.OUT / "perfact.parquet", index=False)
    pd.concat(ST, ignore_index=True).to_parquet(S.OUT / "stale.parquet", index=False)
    (S.OUT / "imputation.json").write_text(json.dumps(IMP, indent=1, default=float))
    print("done", f"{time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
