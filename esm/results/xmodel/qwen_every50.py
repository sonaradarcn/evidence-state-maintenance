"""Cross-model stage: Qwen-27B records on the shared every50 grid (ESM-norepair, REPLAY, NEVER) for the X120 facts that
Stage 2 ran only at every commit (the natural facts outside H150).  Needed so that the Nemotron REPLAY-on-the-grid
comparison has a like-for-like Qwen counterpart.

Stage-2 data are only READ: the 27B derivation shards are copied once into esm_data_xmodel/qwen50/, the Stage-2 LLM
cache is read through (identical request => identical response, as in the e2e stage), observations come from a copy.
New 27B calls (re-derivations at grid points Stage 2 never derived, judge calls on new transitions) go to
esm_data_xmodel/qwen50/ and need an Ollama server with qwen3.6:27b (ESM_PORTS_Q27).  --offline only counts what is missing.
usage: python esm/results/xmodel/qwen_every50.py [--offline] [--workers 4]
"""
import argparse, json, os, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
Q50 = ROOT / "esm_data_xmodel" / "qwen50"
HELD = ROOT / "esm_data_heldout"
ap = argparse.ArgumentParser()
ap.add_argument("--offline", action="store_true")
ap.add_argument("--workers", type=int, default=4)
a = ap.parse_args()
os.environ["ESM_DATA"] = str(Q50)
os.environ["ESM_KIND"] = "heldout"
os.environ.setdefault("ESM_HELDOUT_DATA", str(ROOT / "esm_data_xmodel" / "hd"))
for k in ("ESM_MAIN_MODEL", "ESM_REASONING", "ESM_JUDGE_MAXTOK"):
    os.environ.pop(k, None)                       # Qwen-27B with the Stage-2 settings (cache keys identical to Stage 2)
if a.offline:
    os.environ["ESM_LLM_OFFLINE"] = "1"
Q50.mkdir(parents=True, exist_ok=True)
flag = Q50 / ".imported"
if not flag.exists():
    (Q50 / "obs").mkdir(exist_ok=True)
    for p in (HELD / "obs").glob("*.pkl"):
        shutil.copyfile(p, Q50 / "obs" / p.name)
    srcs = [HELD / "derivations.jsonl"] + sorted(HELD.glob("derivations.[0-9]*.jsonl"))
    for i, p in enumerate(srcs):
        shutil.copyfile(p, Q50 / f"derivations.s2_{i:03d}.jsonl")
    (Q50 / "derivations.jsonl").write_text("", encoding="utf-8")
    for p in [HELD / "certs.jsonl"] + sorted(HELD.glob("certs.[0-9]*.jsonl")):
        if p.exists():
            shutil.copyfile(p, Q50 / ("certs.s2_" + p.name))
    flag.write_text(json.dumps([str(p) for p in srcs]))
sys.path.insert(0, str(ROOT))
from esm import llm
llm.READ_THROUGH[:] = [HELD / "llm_cache"]
assert llm.Q27 == "ollama:qwen3.6:27b" and 11434 not in llm.PORTS["qwen3.6:27b"]
import concurrent.futures as cf
import pandas as pd
from dataclasses import asdict
from esm import policies as P

ctx = P.Context.load("heldout")
X = set(json.loads((ROOT / "esm_data_xmodel" / "sub_X120.json").read_text()))
have = set(pd.read_parquet(HELD / "sim" / "ESM-norepair__every50.parquet", columns=["iid"]).iid)
facts = [f for f in ctx.facts if f["iid"] in X and f["iid"] not in have]
print(f"{len(facts)} X120 facts without Stage-2 every50 records", flush=True)
(Q50 / "sim").mkdir(exist_ok=True)
for pol in ("NEVER", "ESM-norepair", "REPLAY"):
    res, inc = {}, []

    def one(f):
        try:
            return f["iid"], P.run(ctx, pol, f, "every50")
        except (P.NeedModel, P.CacheMiss) as e:
            return f["iid"], None

    with cf.ThreadPoolExecutor(a.workers) as ex:
        for iid, r in ex.map(one, facts):
            if r is None:
                inc.append(iid)
            else:
                res[iid] = r
    rows = [asdict(r) for v in res.values() for r in v]
    if rows:
        df = pd.DataFrame(rows)
        df["schedule"] = "every50"
        df.to_parquet(Q50 / "sim" / f"{pol}__every50.parquet", index=False)
    print(f"{pol}: complete {len(res)}, need new 27B calls {len(inc)}", flush=True)
print("llm", llm.STATS, flush=True)
