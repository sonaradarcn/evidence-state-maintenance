"""Fix the held-out fact subsets (zero LLM, seeded) after the s0 derivations:
  ALL  = every kept fact (s0 answer matches the oracle)
  H150 = stratified subset: 10 facts per repo (behaviour repos: 3 behaviour + 7 static), about half enriched / half natural,
         changing facts (stored K invalid at >= 1 FUTURE commit) preferred up to ~60 % within each cell.
Writes <data>/sub_ALL.json, <data>/sub_H150.json.
usage: python -m esm.scripts.heldout_subsets"""
import json, os, random
os.environ.setdefault("ESM_KIND", "heldout")
os.environ["ESM_LLM_OFFLINE"] = "1"
from esm.policies import Context
from esm.common import DATA

ctx = Context.load("heldout")
F = ctx.facts
rng = random.Random(150)
sel = []


def pick(pool, n):
    """n facts from pool: ~half enriched / half natural; within each, ~60 % changing where available."""
    out = []
    for sub, k in (("enriched", (n + 1) // 2), ("natural", n // 2)):
        p = [f for f in pool if f["subset"] == sub]
        chg = [f for f in p if not all(f["valid"])]
        stb = [f for f in p if all(f["valid"])]
        rng.shuffle(chg); rng.shuffle(stb)
        kc = min(len(chg), round(0.6 * k))
        got = chg[:kc] + stb[:k - kc]
        got += [f for f in chg[kc:] if f not in got][:k - len(got)]
        out += got
    rest = [f for f in pool if f not in out]
    rng.shuffle(rest)
    out += rest[:n - len(out)]
    return out


for repo in sorted({f["repo"] for f in F}):
    fs = [f for f in F if f["repo"] == repo]
    b = [f for f in fs if f["slice"] == "behav"]
    s = [f for f in fs if f["slice"] == "static"]
    nb = min(3, len(b)) if b else 0
    sel += pick(b, nb) + pick(s, 10 - nb)
ids = [f["iid"] for f in sel]
import sys
(DATA / "sub_ALL.json").write_text(json.dumps(sorted(f["iid"] for f in F)))
if (DATA / "sub_H150.json").exists() and "--force" not in sys.argv:
    print("sub_H150.json exists: kept unchanged (use --force to redraw)")
    sel = [f for f in F if f["iid"] in set(json.loads((DATA / "sub_H150.json").read_text()))]
    ids = [f["iid"] for f in sel]
else:
    (DATA / "sub_H150.json").write_text(json.dumps(ids))
from collections import Counter
print("ALL", len(F), "H150", len(ids))
print("H150 by slice", Counter(f["slice"] for f in sel), "subset", Counter(f["subset"] for f in sel),
      "changing", sum(not all(f["valid"]) for f in sel))
print("H150 by type", Counter(f["type"] for f in sel))
