"""Lazy maintenance of the selected facts at the task commits t = 100, 250, 400 (reads only there).

Policies: NEVER, TTL100, REPLAY, ESM (frozen ESM-norepair) run with the esm package (real policy logic); every LLM call
or re-derivation whose exact request exists from Stage 2 is reused (recorded tokens / latency), everything else is
called now on the e2e server.  Plus ESM-eager (replayed from Stage-2 every-commit records) and ORACLE (truth at t).
Per (policy, fact, t): served answer, tokens, calls, new vs reused, latency (measured for new calls; recorded for reused).
usage: python -m esm.e2e.maint_e2e [--policies NEVER,TTL100,REPLAY,ESM]   -> esm_data_e2e/memory.parquet"""
import argparse, json, threading, time
import pandas as pd
from esm.e2e import common_e2e as C
from esm import llm
from esm import policies as P
from esm import baselines as B
from esm.maintain import simulate_esm

ap = argparse.ArgumentParser()
ap.add_argument("--policies", default="NEVER,TTL100,REPLAY,ESM")
a = ap.parse_args()

sel = json.loads((C.E2E / "selection.json").read_text())
tasks = json.loads((C.E2E / "tasks.json").read_text(encoding="utf-8"))
ids = [s["iid"] for s in sel]
ctx = C.load_context(ids)
env = ctx.env
F = {f["iid"]: f for f in ctx.facts}
assert set(ids) <= set(F), set(ids) - set(F)

# ---- attribution of LLM calls / derivations to the read t (thread-local "current read")
TL = threading.local()
_truth = env.truth


def truth_hook(fact, t):
    TL.t = t
    return _truth(fact, t)


env.truth = truth_hook
_chat = llm.chat


def chat_hook(model, messages, *args, **kw):
    t0 = time.time()
    r = _chat(model, messages, *args, **kw)
    log = getattr(TL, "log", None)
    if log is not None:
        k = llm.key_of(llm.payload_of(model, messages, kw.get("tools"), kw.get("max_tokens", 900), kw.get("temperature", 0.0),
                                      kw.get("extra"), kw.get("nonce")))
        s2 = (C.HELD / "llm_cache" / k[:2] / (k + ".json")).exists()   # request already made in Stage 2
        log.append({"t": getattr(TL, "t", None), "tag": kw.get("tag", ""), "cached": s2,
                    "lat": float(r.get("latency") or 0.0), "wall": time.time() - t0,
                    "p": r["usage"]["prompt"], "c": r["usage"]["completion"]})
    return r


llm.chat = chat_hook
import esm.judge as J  # noqa: E402  (judge imported llm as module: patch its reference too)
J.llm.chat = chat_hook
_dget = ctx.ders.get


from esm.maintain import read_shards  # noqa: E402
S2_DERS = {(r["iid"], r["t"]) for p in sorted(C.E2E.glob("derivations.s2_*.jsonl")) for r in read_shards(p)}


def ders_hook(fact, t):
    new = (fact["iid"], t) not in S2_DERS
    t0 = time.time()
    r = _dget(fact, t)
    log = getattr(TL, "dlog", None)
    if log is not None:
        log.append({"t": t, "new": new, "secs": float(r.get("secs") or 0.0),
                    "tok": sum(r["tokens"]), "n_llm": r.get("n_llm", 0)})
    return r


ctx.ders.get = ders_hook

rows = []
for pol in a.policies.split(","):
    t0 = time.time()
    for k, iid in enumerate(ids):
        f = F[iid]
        TL.log, TL.dlog = [], []
        if pol == "ESM":
            recs = simulate_esm(env, ctx.tab, f, C.TS, P.ESM["ESM-norepair"], ctx.ders)
        else:
            recs = B.simulate(ctx, pol, f, C.TS)
        for r in recs:
            calls = [x for x in TL.log if x["t"] == r.t and not x["tag"].startswith("esm_derive")]
            ders = [x for x in TL.dlog if x["t"] == r.t]
            rows.append({"policy": pol, "iid": iid, "t": r.t, "served": r.served, "served_valid_bench": r.served_valid,
                         "stored_valid_bench": r.stored_valid, "action": r.action, "verdict": r.verdict,
                         "eval_tok": r.eval_tok, "eval_calls": r.eval_calls, "der_tok": r.der_tok, "n_der": r.n_der,
                         "judge_new": sum(not x["cached"] for x in calls), "judge_reused": sum(x["cached"] for x in calls),
                         "judge_lat": sum(x["lat"] for x in calls),
                         "der_new": sum(x["new"] for x in ders), "der_reused": sum(not x["new"] for x in ders),
                         "der_lat": sum(x["secs"] for x in ders), "der_llm_calls": sum(x["n_llm"] for x in ders),
                         "maint_tok": r.eval_tok + r.der_tok})
        print(f"[{pol}] {k + 1}/{len(ids)} {iid} actions={[r.action for r in recs]} t={time.time() - t0:.0f}s", flush=True)
    ctx.save_obs()
    pd.DataFrame(rows).to_parquet(C.E2E / "memory_partial.parquet", index=False)

# ---- ESM-eager: replay of the Stage-2 every-commit ESM run (served answer at t, tokens spent in (t_prev, t])
rec = pd.read_parquet(C.ROOT / "esm" / "results" / "heldout" / "records.parquet",
                      filters=[("schedule", "==", "every"), ("policy", "==", "ESM-norepair")],
                      columns=["iid", "t", "served", "served_valid", "stored_valid", "action", "eval_tok", "der_tok", "n_der", "eval_calls"])
rec = rec[rec.iid.isin(ids)]
for iid in ids:
    g = rec[rec.iid == iid].set_index("t")
    prev = 0
    for t in C.TS:
        w = g.loc[prev + 1: t]
        rows.append({"policy": "ESM-eager", "iid": iid, "t": t, "served": g.loc[t, "served"],
                     "served_valid_bench": bool(g.loc[t, "served_valid"]), "stored_valid_bench": bool(g.loc[t, "stored_valid"]),
                     "action": g.loc[t, "action"], "verdict": "", "eval_tok": int(w.eval_tok.sum()), "eval_calls": int(w.eval_calls.sum()),
                     "der_tok": int(w.der_tok.sum()), "n_der": int(w.n_der.sum()), "judge_new": 0, "judge_reused": int(w.eval_calls.sum()),
                     "judge_lat": float("nan"), "der_new": 0, "der_reused": int(w.n_der.sum()), "der_lat": float("nan"),
                     "der_llm_calls": 0, "maint_tok": int(w.eval_tok.sum() + w.der_tok.sum())})
        prev = t
df = pd.DataFrame(rows)
df.to_parquet(C.E2E / "memory.parquet", index=False)
print(df.groupby("policy")[["maint_tok", "judge_new", "judge_reused", "der_new", "der_reused", "served_valid_bench"]].agg(
    ["sum", "mean"]).round(3).to_string())
print("LLM stats", llm.STATS)
