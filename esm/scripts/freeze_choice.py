"""Dev calibration -> frozen repair policy (rule fixed in esm/results/heldout/PLAN.md before the runs):
lowest served-wrong % on dev S1 (27B deriver); if another candidate is within 0.5 pp, the cheaper (tokens/fact) of the two.
Writes <data>/frozen.json.  Zero LLM.
usage: python -m esm.scripts.freeze_choice"""
import json, os
os.environ["ESM_LLM_OFFLINE"] = "1"
import pandas as pd
from esm import metrics as M
from esm.common import DATA, DEV_DATA
from esm.envs.pyrepo import load_dev_facts

CANDS = ["ESM", "ESM-verify", "ESM-norepair"]
F = load_dev_facts()
S1 = set(json.load(open(DEV_DATA / "sub_S1.json")))
res = {}
for c in CANDS:
    p = DATA / "dev27" / "sim" / f"{c}__every.parquet"
    if not p.exists():
        raise SystemExit(f"missing {p}")
    pf = M.per_fact(pd.read_parquet(p), F)
    pf = pf[pf.index.isin(S1)]
    assert len(pf) == len(S1), (c, len(pf))
    s = M.summary(pf)
    res[c] = {"sw": s["sw"], "sw_ci": s["sw_ci"], "tok_per_fact": s["tok_per_fact"], "der_per_fact": s["der_per_fact"],
              "repairs": s["repairs"], "repair_rate": s["repair_rate"]}
best = min(CANDS, key=lambda c: res[c]["sw"])
close = [c for c in CANDS if res[c]["sw"] - res[best]["sw"] <= 0.005]
choice = min(close, key=lambda c: res[c]["tok_per_fact"])
out = {"policy": choice, "lowest_sw": best, "within_0.5pp": close, "candidates": res,
       "rule": "lowest served-wrong on dev S1 (27B deriver); within 0.5 pp -> cheaper"}
(DATA / "frozen.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
