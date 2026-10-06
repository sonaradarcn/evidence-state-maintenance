"""Simulate maintenance policies over read schedules; every LLM call is cached, so re-running is free.

usage: python -m esm.scripts.run_sim --policies ESM,ESM-noanchor --schedules every,every5 [--facts FILE|all]
                                      [--workers 8] [--q27 11495,11496] [--q9 11496,11497] [--offline]
Policies are defined in esm.policies.POLICIES.  A fact whose simulation needs a model that is not configured in this run
(--q27 '' or --q9 '') is skipped and listed as incomplete; re-run later with that model available.
Output: <data>/sim/<policy>__<schedule>.parquet  (complete facts only) + incomplete list in the log.
"""
import argparse, json, os, sys, threading, time, traceback
import concurrent.futures as cf
from dataclasses import asdict

ap = argparse.ArgumentParser()
ap.add_argument("--policies", required=True)
ap.add_argument("--schedules", default="every")
ap.add_argument("--facts", default="all")
ap.add_argument("--workers", type=int, default=8)
ap.add_argument("--q27", default=None)
ap.add_argument("--q9", default=None)
ap.add_argument("--offline", action="store_true")
ap.add_argument("--reverse", action="store_true")
ap.add_argument("--merge", action="store_true", help="merge into an existing parquet (replace these facts only)")
ap.add_argument("--kind", default=None, help="dev | dev27 | heldout (default: $ESM_KIND or dev)")
ap.add_argument("--out", default=None, help="output dir (default <data>/sim, or <data>/dev27/sim for kind dev27)")
ap.add_argument("--save-obs-every", type=int, default=0, help="persist the observation table every N facts")
ap.add_argument("--priority", default=None, help="JSON list of fact ids simulated first (e.g. a subset other arms share)")
ap.add_argument("--order", default=None, help="random:<seed> = seeded random fact order (written to <out>/<policy>__<schedule>.order.json)")
ap.add_argument("--deadline", default=None, help="'YYYY-MM-DD HH:MM': no new fact is started after this time")
ap.add_argument("--save-every", type=int, default=0, help="write the parquet every N completed facts (long runs)")
a = ap.parse_args()
if a.kind:
    os.environ["ESM_KIND"] = a.kind
if a.q27 is not None:
    os.environ["ESM_PORTS_Q27"] = a.q27
if a.q9 is not None:
    os.environ["ESM_PORTS_Q9"] = a.q9
if a.offline:
    os.environ["ESM_LLM_OFFLINE"] = "1"

import pandas as pd
from esm import policies as P
from esm.common import DATA

ctx = P.Context.load()
facts = ctx.facts
if a.facts != "all":
    ids = set(json.loads(open(a.facts).read()))
    facts = [f for f in facts if f["iid"] in ids]
# heavy facts first
if os.environ.get("ESM_KIND", "").startswith(("dl_", "dlsyn_")):
    facts.sort(key=lambda f: -len(f["trace"]))
else:
    if not ctx.n_states:
        ctx.count_states()
    facts.sort(key=lambda f: -ctx.n_states.get(f["iid"], 0))
if a.reverse:
    facts.reverse()
if a.order and a.order.startswith("list:"):          # explicit order (JSON list of iids); facts not listed are dropped
    _ol = json.loads(open(a.order[5:]).read())
    _fx = {f["iid"]: f for f in facts}
    facts = [_fx[i] for i in _ol if i in _fx]
elif a.order and a.order.startswith("random:"):
    import random as _r
    facts.sort(key=lambda f: f["iid"])
    _r.Random(int(a.order.split(":")[1])).shuffle(facts)
if a.priority:
    pri = set(json.loads(open(a.priority).read()))
    facts = [f for f in facts if f["iid"] in pri] + [f for f in facts if f["iid"] not in pri]
_deadline = time.mktime(time.strptime(a.deadline, "%Y-%m-%d %H:%M")) if a.deadline else None
from pathlib import Path
_k = os.environ.get("ESM_KIND", "")
out = Path(a.out) if a.out else (DATA / "dev27" / "sim" if _k == "dev27" else
                                 (getattr(ctx, "sub", DATA) / "sim" if _k.startswith(("dl_", "dlsyn_")) else DATA / "sim"))
out.mkdir(parents=True, exist_ok=True)
for pol in a.policies.split(","):
    for sch in a.schedules.split(","):
        t0 = time.time()
        res, inc, err = {}, [], []
        lock = threading.Lock()
        done = [0]

        dst = out / f"{pol}__{sch}.parquet"
        if a.order or a.deadline:
            (out / f"{pol}__{sch}.order.json").write_text(json.dumps([f["iid"] for f in facts]))

        def flush():
            rows = [asdict(r) for iid in list(res) for r in res[iid]]
            if rows:
                df = pd.DataFrame(rows)
                df["schedule"] = sch
                if a.merge and dst.exists():
                    old = pd.read_parquet(dst)
                    df = pd.concat([old[~old.iid.isin(set(df.iid))], df], ignore_index=True)
                df.to_parquet(dst, index=False)

        def one(f):
            if _deadline and time.time() > _deadline:
                with lock:
                    inc.append(f["iid"])
                return
            try:
                recs = P.run(ctx, pol, f, sch)
                with lock:
                    res[f["iid"]] = recs
            except P.NeedModel as e:
                with lock:
                    inc.append(f["iid"])
            except P.CacheMiss:
                with lock:
                    inc.append(f["iid"])
            except Exception as e:
                with lock:
                    err.append(f["iid"])
                print("ERR", pol, sch, f["iid"], repr(e)[:300], traceback.format_exc()[-1500:], flush=True)
            with lock:
                done[0] += 1
                if done[0] % 20 == 0 or a.save_every:
                    print(f"[{pol}/{sch}] {done[0]}/{len(facts)} complete={len(res)} incomplete={len(inc)} t={time.time() - t0:.0f}s"
                          f" last={f['iid']}", flush=True)
                if a.save_every and len(res) % a.save_every == 0 and f["iid"] in res:
                    try:
                        flush()
                    except Exception as e:
                        print("flush failed", repr(e)[:200], flush=True)

        with cf.ThreadPoolExecutor(a.workers) as ex:
            list(ex.map(one, facts))
        flush()
        print(f"[{pol}/{sch}] DONE complete={len(res)} incomplete={len(inc)} errors={len(err)} t={time.time() - t0:.0f}s", flush=True)
        if inc:
            print(f"[{pol}/{sch}] incomplete: {sorted(inc)[:20]}{' ...' if len(inc) > 20 else ''}", flush=True)
        ctx.save_obs()
