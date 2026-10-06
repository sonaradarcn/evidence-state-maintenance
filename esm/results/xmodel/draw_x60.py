"""Cross-model stage, Nemotron: X60 = a seeded stratified half of the X120 facts that Nemotron kept at s0 (zero LLM).
Drawn 2026-10-06 01:10, after s0 and before any maintenance outcome was looked at, because the NIM key is throttled to
~3-12 calls/min after a burst (PLAN.md).  Per half (natural / enriched) 30 facts: behaviour facts first (natural 4,
enriched 6), then static; repositories round-robin in seeded order, each visit adding the least-represented type
(the same procedure as draw_x120.py).  Seed 20261006 + 60.  Output: esm_data_xmodel/nemotron/sub_X60.json, sub_X60rest.json."""
import collections, json, random, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
N = ROOT / "esm_data_xmodel" / "nemotron"
draw = json.loads((HERE / "draw_x120.json").read_text())
recs = {}
for p in [N / "derivations.jsonl"] + sorted(N.glob("derivations.*.jsonl")):
    if p.exists():
        for l in p.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                if r["t"] == 0:
                    recs.setdefault(r["iid"], r)
kept = {i for i, r in recs.items() if r["correct"]}
meta = {f["iid"]: f for f in json.loads(json.dumps(__import__("pickle").loads((ROOT / "esm/results/heldout/revision_r1/cache/meta.pkl").read_bytes())["facts"]))}
rng = random.Random(20261006 + 60)
out, allp = {}, []
for half, nb in (("natural", 4), ("enriched", 6)):
    pool = sorted(set(draw[half]["ids"]) & kept)
    picked, tc = [], collections.Counter()
    for sl, need in (("behav", nb), ("static", 30 - nb)):
        by = collections.defaultdict(list)
        for i in pool:
            if meta[i]["slice"] == sl:
                by[meta[i]["repo"]].append(i)
        for v in by.values():
            rng.shuffle(v)
        repos = sorted(by); rng.shuffle(repos)
        while need > 0 and any(by.values()):
            for r in repos:
                if need == 0 or not by[r]:
                    continue
                best = min(by[r], key=lambda i: (tc[meta[i]["type"]], by[r].index(i)))
                by[r].remove(best); picked.append(best); tc[meta[best]["type"]] += 1; need -= 1
    out[half] = {"n": len(picked), "types": dict(sorted(collections.Counter(meta[i]["type"] for i in picked).items())),
                 "repos": len({meta[i]["repo"] for i in picked}), "changing": sum(not all(meta[i]["valid"]) for i in picked)}
    allp += picked
(N / "sub_X60.json").write_text(json.dumps(sorted(allp)))
(N / "sub_X60rest.json").write_text(json.dumps(sorted(kept - set(allp))))
(HERE / "draw_x60.json").write_text(json.dumps({"kept_s0": len(kept), **out, "ids": sorted(allp)}, indent=1))
print(len(kept), out)

# 01:40: X30 = the same procedure applied to X60 (15 per half; behaviour natural 2, enriched 3), seed 20261006 + 30,
# because the NIM key sustains only ~4-5 calls/min (PLAN.md).  No maintenance outcome existed when this was drawn.
rng = random.Random(20261006 + 30)
x60 = set(allp)
out30, all30 = {}, []
for half, nb in (("natural", 2), ("enriched", 3)):
    pool = sorted(set(draw[half]["ids"]) & x60)
    picked, tc = [], collections.Counter()
    for sl, need in (("behav", nb), ("static", 15 - nb)):
        by = collections.defaultdict(list)
        for i in pool:
            if meta[i]["slice"] == sl:
                by[meta[i]["repo"]].append(i)
        for v in by.values():
            rng.shuffle(v)
        repos = sorted(by); rng.shuffle(repos)
        while need > 0 and any(by.values()):
            for r in repos:
                if need == 0 or not by[r]:
                    continue
                best = min(by[r], key=lambda i: (tc[meta[i]["type"]], by[r].index(i)))
                by[r].remove(best); picked.append(best); tc[meta[best]["type"]] += 1; need -= 1
    out30[half] = {"n": len(picked), "types": dict(sorted(collections.Counter(meta[i]["type"] for i in picked).items())),
                   "repos": len({meta[i]["repo"] for i in picked}), "changing": sum(not all(meta[i]["valid"]) for i in picked)}
    all30 += picked
(N / "sub_X30.json").write_text(json.dumps(sorted(all30)))
(N / "sub_X60rest30.json").write_text(json.dumps(sorted(x60 - set(all30))))
(HERE / "draw_x30.json").write_text(json.dumps({**out30, "ids": sorted(all30)}, indent=1))
print("X30", out30)
