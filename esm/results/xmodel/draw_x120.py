"""Cross-model stage: draw the stratified 120-fact subset X120 (zero LLM; run once, before any cross-model LLM call).

Pools (both have complete Qwen-27B records for every compared policy at every commit, so Qwen's numbers can be recomputed
on exactly the same facts):
  natural  = NAT100 (seeded uniform random sample of the 715 natural kept facts, revision_r1_runs/draw_nat100.py)
  enriched = the change-enriched (subset != natural) facts of H150 (89 facts)
Quota per pool: 60 facts.  Behaviour facts first (natural: all 8 available; enriched: 12 of 18), then static facts.
Within a slice: repositories are visited round-robin in a seeded random order; at each visit the repository contributes
one fact, chosen as the fact whose type is least represented in the draw so far (ties: seeded random order).  This
balances repositories and types.  Seed 20261006.  Output: esm_data_xmodel/sub_X120.json (+ draw_x120.json here).
"""
import collections, hashlib, json, pickle, random
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
HD = ROOT / "esm_data_heldout"
XD = ROOT / "esm_data_xmodel"
SEED = 20261006
meta = pickle.loads((ROOT / "esm/results/heldout/revision_r1/cache/meta.pkl").read_bytes())
FX = {f["iid"]: f for f in meta["facts"]}
H150 = set(json.loads((HD / "sub_H150.json").read_text()))
NAT100 = set(json.loads((HD / "sub_NAT100.json").read_text()))
pools = {"natural": sorted(NAT100), "enriched": sorted(i for i in H150 if FX[i]["subset"] != "natural")}
quota = {"natural": {"behav": 8, "static": 52}, "enriched": {"behav": 12, "static": 48}}
rng = random.Random(SEED)
draw, out = [], {}
for pname, pool in pools.items():
    picked = []
    tcount = collections.Counter()
    for sl in ("behav", "static"):
        by = collections.defaultdict(list)
        for i in pool:
            if FX[i]["slice"] == sl:
                by[FX[i]["repo"]].append(i)
        for v in by.values():
            rng.shuffle(v)
        repos = sorted(by)
        rng.shuffle(repos)
        need = quota[pname][sl]
        while need > 0 and any(by.values()):
            for r in repos:
                if need == 0 or not by[r]:
                    continue
                best = min(by[r], key=lambda i: (tcount[FX[i]["type"]], by[r].index(i)))
                by[r].remove(best)
                picked.append(best)
                tcount[FX[best]["type"]] += 1
                need -= 1
    out[pname] = {"n": len(picked), "types": dict(sorted(collections.Counter(FX[i]["type"] for i in picked).items())),
                  "repos": dict(sorted(collections.Counter(FX[i]["repo"] for i in picked).items())),
                  "changing": sum(not all(FX[i]["valid"]) for i in picked), "ids": sorted(picked)}
    draw += picked
assert len(draw) == len(set(draw)) == 120
XD.mkdir(exist_ok=True)
(XD / "sub_X120.json").write_text(json.dumps(sorted(draw)))
out["seed"] = SEED
out["pool_hash"] = {k: hashlib.sha256("\n".join(v).encode()).hexdigest()[:16] for k, v in pools.items()}
out["subset_hash"] = hashlib.sha256("\n".join(sorted(draw)).encode()).hexdigest()[:16]
(HERE / "draw_x120.json").write_text(json.dumps(out, indent=1))
for k in ("natural", "enriched"):
    print(k, out[k]["n"], out[k]["types"], "changing", out[k]["changing"], "repos", len(out[k]["repos"]), out[k]["repos"])
print("subset hash", out["subset_hash"])
