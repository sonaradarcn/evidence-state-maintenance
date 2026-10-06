"""Zero-LLM: replay every kept fact's s0 evidence (anchored + original recording) over all FUTURE snapshots of one lake
kind; report queries per fact, distinct non-s0 evidence states, reads with a changed state, and states where the truth
changed but the evidence did not (observation incompleteness of the recording).  Persists the observation table.
usage: python -m esm.scripts.dl_states --kind dl_tlc [--show N] [--stats FILE]"""
import argparse, json, os, time
from collections import Counter, defaultdict

ap = argparse.ArgumentParser()
ap.add_argument("--kind", required=True)
ap.add_argument("--show", type=int, default=0)
ap.add_argument("--stats", default=None)
ap.add_argument("--modes", default="anchored,original")
a = ap.parse_args()
os.environ["ESM_LLM_OFFLINE"] = "1"
from esm import evidence as E
from esm.policies import Context

ctx = Context.load(a.kind)
env, tab = ctx.env, ctx.tab
n = env.n_steps()
agg = defaultdict(list)
t0 = time.time()
rows = []
for i, f in enumerate(ctx.facts):
    rec = {"iid": f["iid"], "type": f["type"], "subset": f["subset"]}
    for mode in a.modes.split(","):
        ev = E.record(env, f, f["trace"], 0, mode, f["cite"], f["K"], "s0")
        r0 = tab.ref_state(ev)
        sts, nch, inc = set(), 0, 0
        for t in range(1, n + 1):
            s, _ = tab.state(f, ev, t)
            if s != r0:
                sts.add(s); nch += 1
            elif not f["valid"][t - 1]:
                inc += 1
        rec[mode] = {"q": len(ev.keys), "states": len(sts), "changed_reads": nch, "incomplete_reads": inc}
        agg[(mode, f["type"])].append(len(sts))
        if a.show and i < a.show and mode == "anchored":
            print(f"--- {f['iid']} K={f['K']!r} :: {f['question'][:120]}")
            for q, k in zip(ev.queries, ev.keys):
                print(f"   [{q['kind']}] {env.query_label(q)[:160]}\n      {ev.ref[k][:300]!r}")
    rows.append(rec)
    if a.stats:
        with open(a.stats, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
print(f"facts={len(ctx.facts)} t={time.time() - t0:.0f}s")
for mode in a.modes.split(","):
    tot = [r[mode] for r in rows]
    print(f"{mode}: q/fact={sum(x['q'] for x in tot) / max(1, len(tot)):.2f} states/fact={sum(x['states'] for x in tot) / max(1, len(tot)):.2f} "
          f"changed reads/fact={sum(x['changed_reads'] for x in tot) / max(1, len(tot)):.1f} "
          f"incomplete reads={sum(x['incomplete_reads'] for x in tot)} (facts {sum(1 for x in tot if x['incomplete_reads'])})")
    print("   states/fact by type:", {t: round(sum(v) / len(v), 1) for (m, t), v in sorted(agg.items()) if m == mode})
ctx.save_obs()
