"""Data-lake step 1: s0 derivation of every fact of one lake with the 27B agent (lake tool loop, <= 12 tool calls, thinking
off, T = 0, NONE instruction).  Results -> <ESM_DATA>/<kind>/derivations.jsonl (key (iid, 0)); every LLM call is cached.
usage: python -m esm.scripts.dl_s0 --kind dl_tlc|dl_bb|dlsyn_tlc|dlsyn_bb [--workers 4] [--q27 11595,11596] [--limit N]
       [--deriver 27b|9b] [--ids FILE]"""
import argparse, json, os, random, time
import concurrent.futures as cf

ap = argparse.ArgumentParser()
ap.add_argument("--kind", required=True)
ap.add_argument("--workers", type=int, default=4)
ap.add_argument("--q27", default=None)
ap.add_argument("--q9", default=None)
ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--deriver", default="27b")
ap.add_argument("--ids", default=None)
a = ap.parse_args()
if a.q27 is not None:
    os.environ["ESM_PORTS_Q27"] = a.q27
if a.q9 is not None:
    os.environ["ESM_PORTS_Q9"] = a.q9
from esm import llm
from esm.common import DATA
from esm.envs import datalake as DLE
from esm.maintain import DerivStore

variant = "synth" if a.kind.startswith("dlsyn_") else "real"
lake = a.kind.split("_", 1)[1]
facts, lk = DLE.load_facts(lake, variant, DATA)
env = DLE.DataLakeEnv(lake, variant, facts=facts, lk=lk)
sub = DATA / a.kind
sub.mkdir(parents=True, exist_ok=True)
ders = (DerivStore(env, sub / "derivations.jsonl", model=llm.Q27) if a.deriver == "27b"
        else DerivStore(env, sub / "derivations_9b.jsonl", model=llm.Q9))
# round-robin over fact types (seeded random order within a type) so that partial results are representative
rng = random.Random(0)
by = {}
for f in facts:
    by.setdefault(f["type"], []).append(f)
for v in by.values():
    rng.shuffle(v)
order = []
while any(by.values()):
    for t in sorted(by):
        if by[t]:
            order.append(by[t].pop())
if a.ids:
    keep = set(json.loads(open(a.ids).read()))
    order = [f for f in order if f["iid"] in keep]
todo = [f for f in order if (f["iid"], 0) not in ders.d]
if a.limit:
    todo = todo[:a.limit]
print(f"facts={len(facts)} todo={len(todo)}", flush=True)
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
        if n % 10 == 0 or n == len(todo):
            el = time.time() - t0
            print(f"{n}/{len(todo)} correct={ok} ({100 * ok / n:.1f}%) t={el:.0f}s rate={n / el * 3600:.0f}/h "
                  f"eta={(len(todo) - n) / max(n / el, 1e-9) / 3600:.1f}h llm={llm.STATS}", flush=True)
print("DONE", n, ok, flush=True)
