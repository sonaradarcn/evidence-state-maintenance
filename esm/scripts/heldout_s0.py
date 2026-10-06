"""Held-out step 1: s0 derivation of every held-out fact with the 27B agent (pilot3/pilot6 tool loop, thinking off, T = 0).
Results go to <ESM_DATA>/derivations.jsonl (DerivStore, key (iid, 0)); every LLM call is cached.
usage: python -m esm.scripts.heldout_s0 [--workers 6] [--q27 11595,11596,11595,11596] [--repos a,b] [--limit N]"""
import argparse, os, random, time
import concurrent.futures as cf

ap = argparse.ArgumentParser()
ap.add_argument("--workers", type=int, default=6)
ap.add_argument("--q27", default=None)
ap.add_argument("--repos", default="")
ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--facts", default="", help="JSON list of fact ids (only these are derived)")
ap.add_argument("--deriver", default="27b", help="27b (main) | 9b (secondary arm -> derivations_9b.jsonl)")
ap.add_argument("--q9", default=None)
a = ap.parse_args()
if a.q27 is not None:
    os.environ["ESM_PORTS_Q27"] = a.q27
if a.q9 is not None:
    os.environ["ESM_PORTS_Q9"] = a.q9
from esm import llm
from esm.common import DATA
from esm.envs import heldout as H
from esm.maintain import DerivStore

names = a.repos.split(",") if a.repos else H.REPOS
facts = H.load_heldout_raw(names)
env = H.make_env(facts, names)
ders = (DerivStore(env, DATA / "derivations.jsonl", model=llm.Q27) if a.deriver == "27b"
        else DerivStore(env, DATA / "derivations_9b.jsonl", model=llm.Q9))
# round-robin over repos (random order within a repo) so that partial results are representative
rng = random.Random(0)
by = {}
for f in facts:
    by.setdefault(f["repo"], []).append(f)
for v in by.values():
    rng.shuffle(v)
order = []
while any(by.values()):
    for r in names:
        if by.get(r):
            order.append(by[r].pop())
_only = set(__import__("json").loads(open(a.facts).read())) if a.facts else None
todo = [f for f in order if (f["iid"], 0) not in ders.d and (_only is None or f["iid"] in _only)]
if a.limit:
    todo = todo[:a.limit]
print(f"facts={len(facts)} done={len(facts) - len([f for f in facts if (f['iid'], 0) not in ders.d])} todo={len(todo)}", flush=True)
t0, n, ok = time.time(), 0, 0


def one(f):
    try:
        return ders.get(f, 0)
    except Exception as e:
        print("ERR", f["iid"], repr(e)[:300], flush=True)
        return None


with cf.ThreadPoolExecutor(a.workers) as ex:
    for r in ex.map(one, todo):
        n += 1
        ok += bool(r and r["correct"])
        if n % 10 == 0:
            el = time.time() - t0
            print(f"{n}/{len(todo)} correct={ok} ({100 * ok / n:.1f}%) t={el:.0f}s rate={n / el * 3600:.0f}/h "
                  f"eta={(len(todo) - n) / max(n / el, 1e-9) / 3600:.1f}h llm={llm.STATS}", flush=True)
print("DONE", n, ok, flush=True)
