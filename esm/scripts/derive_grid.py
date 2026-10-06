"""Run agent re-derivations at fixed commits (a grid) for a fact subset -> DerivStore (<data>/derivations.jsonl).
Used for ALWAYS / TTL baselines and to measure re-derivation accuracy over time.
usage: python -m esm.scripts.derive_grid --facts FILE --grid 0,50,100,...  [--workers 2] [--kind dev|dev27|heldout]
                                         [--q9 ports] [--q27 ports] [--deriver 27b|9b]"""
import argparse, json, os, time
import concurrent.futures as cf

ap = argparse.ArgumentParser()
ap.add_argument("--facts", required=True)
ap.add_argument("--grid", required=True)
ap.add_argument("--workers", type=int, default=2)
ap.add_argument("--q9", default=None)
ap.add_argument("--q27", default=None)
ap.add_argument("--kind", default=None)
ap.add_argument("--deriver", default=None)
a = ap.parse_args()
if a.q9 is not None:
    os.environ["ESM_PORTS_Q9"] = a.q9
if a.q27 is not None:
    os.environ["ESM_PORTS_Q27"] = a.q27
if a.kind:
    os.environ["ESM_KIND"] = a.kind
from esm import llm
from esm.policies import Context

ctx = Context.load()
ders = ctx.ders_for({"27b": llm.Q27, "9b": llm.Q9}.get(a.deriver)) if a.deriver else ctx.ders
ids = json.loads(open(a.facts).read())
F = {f["iid"]: f for f in ctx.facts}
grid = [int(x) for x in a.grid.split(",")]
jobs = [(F[i], t) for t in grid for i in ids if i in F]
t0 = time.time()
n = 0


def one(j):
    try:
        return ders.get(*j)
    except Exception as e:
        print("ERR", j[0]["iid"], j[1], repr(e)[:300], flush=True)
        return None


with cf.ThreadPoolExecutor(a.workers) as ex:
    for r in ex.map(one, jobs):
        n += 1
        if n % 20 == 0 and r:
            print(f"{n}/{len(jobs)} t={time.time() - t0:.0f}s last={r['iid']}@{r['t']} correct={r['correct']}", flush=True)
print("DONE", n, flush=True)
