"""Build CERT-ZS / CERT-v0h certificates (27B) for a held-out fact subset -> <data>/certs.jsonl.
usage: python -m esm.scripts.heldout_certs --facts FILE --kinds certzs,certv0h [--workers 4] [--q27 ports]"""
import argparse, json, os, time
import concurrent.futures as cf

ap = argparse.ArgumentParser()
ap.add_argument("--facts", required=True)
ap.add_argument("--kinds", default="certzs,certv0h")
ap.add_argument("--workers", type=int, default=4)
ap.add_argument("--q27", default=None)
ap.add_argument("--kind", default="heldout")
a = ap.parse_args()
if a.q27 is not None:
    os.environ["ESM_PORTS_Q27"] = a.q27
from esm.common import DATA
from esm.certs import CertStore
from esm.policies import Context

ctx = Context.load(a.kind)
cs = CertStore(getattr(ctx, "sub", DATA) / "certs.jsonl")
ids = set(json.loads(open(a.facts).read()))
jobs = [(f, k) for k in a.kinds.split(",") for f in ctx.facts if f["iid"] in ids and not (k == "certv0h" and f["slice"] != "static")]
t0, n = time.time(), 0


def one(j):
    try:
        return cs.get(ctx.env, j[0], j[1])
    except Exception as e:
        print("ERR", j[0]["iid"], j[1], repr(e)[:300], flush=True)


with cf.ThreadPoolExecutor(a.workers) as ex:
    for r in ex.map(one, jobs):
        n += 1
        if n % 20 == 0:
            print(f"{n}/{len(jobs)} t={time.time() - t0:.0f}s", flush=True)
print("DONE", n, flush=True)
