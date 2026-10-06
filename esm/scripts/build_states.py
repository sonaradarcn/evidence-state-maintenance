"""Zero-LLM: replay the s0 evidence of every fact of one unit (repo) at all 400 FUTURE commits, in both recording modes
(anchored / original), and persist the observation table to <data>/obs/<unit>.pkl.
usage: python -m esm.scripts.build_states <unit|all> [--kind dev|heldout] [--modes anchored,original] [--stats FILE]
With --stats, one JSON line per fact (iid, mode, n_queries, distinct non-s0 states, reads with a changed state) is
appended to FILE."""
import argparse, json, os, sys, time

ap = argparse.ArgumentParser()
ap.add_argument("unit")
ap.add_argument("--kind", default=None)
ap.add_argument("--modes", default="anchored,original")
ap.add_argument("--stats", default=None)
a = ap.parse_args()
if a.kind:
    os.environ["ESM_KIND"] = a.kind
os.environ["ESM_LLM_OFFLINE"] = "1"
from esm import evidence as E
from esm.policies import Context

if (a.kind or os.environ.get("ESM_KIND", "dev")) == "dev":
    from esm.envs.pyrepo import PyRepoEnv
    from esm.common import DATA
    env = PyRepoEnv()
    tab = E.ObsTable(env)
    obs_dir = DATA / "obs"
    facts = env.facts()
else:
    ctx = Context.load()
    env, tab, obs_dir, facts = ctx.env, ctx.tab, ctx.obs_dir, ctx.facts
obs_dir.mkdir(parents=True, exist_ok=True)
units = sorted({f["unit"] for f in facts}) if a.unit == "all" else [a.unit]
for unit in units:
    path = obs_dir / f"{unit}.pkl"
    tab.load(path)
    t0 = time.time()
    for f in [f for f in facts if f["unit"] == unit]:
        out = []
        for mode in a.modes.split(","):
            ev = E.record(env, f, f["trace"], 0, mode, f["cite"], f["K"], "s0")
            r0 = tab.ref_state(ev)
            sts, nst = set(), 0
            for t in range(1, env.n_steps() + 1):
                s, _ = tab.state(f, ev, t)
                if s != r0:
                    sts.add(s); nst += 1
            out.append(f"{mode}: q={len(ev.keys)} states={len(sts)} stale={nst}")
            if a.stats:
                with open(a.stats, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"iid": f["iid"], "unit": unit, "mode": mode, "q": len(ev.keys), "states": len(sts),
                                         "stale_reads": nst}) + "\n")
        print(f"[{unit}] {f['iid']} " + " | ".join(out) + f" t={time.time() - t0:.0f}s", flush=True)
    tab.save(path, unit)
    print("DONE", unit, flush=True)
