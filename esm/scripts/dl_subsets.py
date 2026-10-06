"""Fix the data-lake fact subsets (zero LLM, seeded) right after the s0 derivations, before any maintenance run:
  ALL = every kept fact of the lake;  S = stratified subset of N facts per lake: types round-robin (seeded order), each pick
  alternating natural / enriched, changing facts (stored K invalid at >= 1 FUTURE snapshot) preferred ~60 % where available.
Writes <data>/<kind>/sub_ALL.json, sub_S.json (never redrawn unless --force).
usage: python -m esm.scripts.dl_subsets --kind dl_tlc [--n 20]"""
import argparse, json, os, random
ap = argparse.ArgumentParser()
ap.add_argument("--kind", required=True)
ap.add_argument("--n", type=int, default=20)
ap.add_argument("--force", action="store_true")
a = ap.parse_args()
os.environ["ESM_LLM_OFFLINE"] = "1"
from collections import Counter
from esm.policies import Context

ctx = Context.load(a.kind)
F = ctx.facts
rng = random.Random(150)
types = sorted({f["type"] for f in F})
rng.shuffle(types)
pools = {}
for t in types:
    for sub in ("natural", "enriched"):
        p = [f for f in F if f["type"] == t and f["subset"] == sub]
        chg = [f for f in p if not all(f["valid"])]
        stb = [f for f in p if all(f["valid"])]
        rng.shuffle(chg); rng.shuffle(stb)
        pools[(t, sub)] = (chg, stb)
sel, k, taken = [], 0, Counter()
while len(sel) < a.n and any(c or s for c, s in pools.values()):
    t = types[k % len(types)]
    sub = ("natural", "enriched")[(k // len(types)) % 2] if k % 2 == 0 else ("enriched", "natural")[(k // len(types)) % 2]
    k += 1
    for s in (sub, "enriched" if sub == "natural" else "natural"):
        chg, stb = pools[(t, s)]
        n_chg = sum(1 for f in sel if not all(f["valid"]))
        want_chg = n_chg < 0.6 * (len(sel) + 1)
        src = chg if (want_chg and chg) or not stb else stb
        if src:
            sel.append(src.pop())
            break
sub_all = sorted(f["iid"] for f in F)
(ctx.sub / "sub_ALL.json").write_text(json.dumps(sub_all))
p = ctx.sub / "sub_S.json"
if p.exists() and not a.force:
    print("sub_S.json exists: kept unchanged")
    ids = set(json.loads(p.read_text()))
    sel = [f for f in F if f["iid"] in ids]
else:
    p.write_text(json.dumps([f["iid"] for f in sel]))
print("ALL", len(F), "S", len(sel), "changing", sum(not all(f["valid"]) for f in sel))
print("S by type", dict(Counter(f["type"] for f in sel)), "subset", dict(Counter(f["subset"] for f in sel)))
