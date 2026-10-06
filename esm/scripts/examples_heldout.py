"""Concrete examples for the error taxonomy (zero LLM: replays one fact's ESM simulation offline from the cache and
prints, for each action, the judge's verdict / reason / proposed answer, the verifier, re-derivation answers, and the
evidence queries; for misses with an unchanged evidence state, which files changed between the anchor and t).
usage: python -m esm.scripts.examples_heldout --policy ESM-verify --iid <id> [--iid ...] [--out FILE]"""
import argparse, json, os
os.environ["ESM_LLM_OFFLINE"] = "1"
ap = argparse.ArgumentParser()
ap.add_argument("--policy", required=True)
ap.add_argument("--iid", action="append", required=True)
ap.add_argument("--out", default=None)
a = ap.parse_args()
import pandas as pd
from esm import judge as J
from esm import evidence as E
from esm.common import DATA
from esm.policies import Context, ESM

ctx = Context.load("heldout")
F = {f["iid"]: f for f in ctx.facts}
cfg = ESM[a.policy]
rec = pd.read_parquet(DATA / "sim" / f"{a.policy}__every.parquet")
lines = []
orig_eval = J.evaluate
log = []


def ev_hook(env, fact, ev, cur, **kw):
    res = orig_eval(env, fact, ev, cur, **kw)
    log.append({"aid": ev.aid, "K": ev.K, "verdict": res["verdict"], "new_answer": res["new_answer"], "reason": res["reason"],
                "info": {k: res["info"].get(k) for k in ("n_changed", "hunks", "groups", "retained", "trunc", "final_chars")},
                "queries": [env.query_label(q) for q in ev.queries]})
    return res


J.evaluate = ev_hook
for iid in a.iid:
    f = F[iid]
    log.clear()
    d = rec[rec.iid == iid].sort_values("t")
    lines.append(f"\n## {iid} ({f['type']}, {f['slice']}, {f['subset']})\nQ: {f['question']}\nK(s0) = {f['K']!r}")
    lines.append("s0 evidence: " + "; ".join(ctx.env.query_label(q) for q in E.record(ctx.env, f, f["trace"], 0, cfg.mode, f["cite"], f["K"], "a0").queries))
    tv = [f["truth"][300 + t] for t in range(401)]
    chg = [t for t in range(1, 401) if tv[t] != tv[t - 1]]
    lines.append("truth changes at t = " + ", ".join(f"{t}: {tv[t - 1][:40]!r}->{tv[t][:40]!r}" for t in chg[:8]))
    acts = d[d.action.isin(["valid", "repair", "rederive", "unsure_fresh"])]
    for r in acts.itertuples():
        lines.append(f"  t={r.t}: action={r.action} verdict={r.verdict} served={str(r.served)[:60]!r} served_valid={r.served_valid} "
                     f"truth={tv[r.t][:60]!r} reason={str(r.reason)[:220]!r}")
    wrong = d[~d.served_valid]
    if len(wrong):
        lines.append(f"  wrong-served reads: {len(wrong)} (first t={int(wrong.t.min())}, actions: {dict(wrong.action.value_counts())})")
    # replay offline to get the deltas' metadata
    from esm.maintain import simulate_esm
    try:
        simulate_esm(ctx.env, ctx.tab, f, list(range(1, 401)), cfg, ctx.ders_for(cfg.deriver))
        for x in log:
            lines.append(f"  judge on anchor {x['aid']} (K={x['K'][:40]!r}): {x['verdict']} new={str(x['new_answer'])[:50]!r} "
                         f"delta={x['info']} queries={x['queries'][:4]}")
    except Exception as e:
        lines.append(f"  (offline replay failed: {type(e).__name__} {str(e)[:100]})")
txt = "\n".join(lines)
print(txt)
if a.out:
    open(a.out, "a", encoding="utf-8").write(txt + "\n")
