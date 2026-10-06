"""Lazy maintenance of the selected facts at the task snapshots only (TLC 25/50/100, BB 20/40/80).

Policies: NEVER, TTL (TLC 25 / BB 20), TTL-mid (TLC 50 / BB 40), REPLAY, ESM (frozen ESM-norepair), run with the esm
package (real policy logic); every LLM call or re-derivation whose exact request exists from Stage 3 is reused (recorded
tokens / latency), everything else is called now on the e2e server.  Plus ESM-eager (replayed from the Stage-3
every-snapshot records).  Per (policy, fact, t): served answer, tokens, calls, new vs reused, latency.
usage: python -m esm.e2e_lake.maint_lake   -> esm_data_e2e_lake/memory.parquet"""
import json, sys, threading, time
import pandas as pd
from esm.e2e_lake import common_lake as C
from esm import llm
from esm import policies as P
from esm import baselines as B
from esm.maintain import simulate_esm

sel = json.loads((C.E2E / "selection.json").read_text())
TL = threading.local()
_chat = llm.chat


def chat_hook(model, messages, *args, **kw):
    t0 = time.time()
    r = _chat(model, messages, *args, **kw)
    log = getattr(TL, "log", None)
    if log is not None:
        k = llm.key_of(llm.payload_of(model, messages, kw.get("tools"), kw.get("max_tokens", 900), kw.get("temperature", 0.0),
                                      kw.get("extra"), kw.get("nonce")))
        s3 = (C.S3 / "llm_cache" / k[:2] / (k + ".json")).exists()   # request already made in Stage 3
        log.append({"t": getattr(TL, "t", None), "tag": kw.get("tag", ""), "cached": s3,
                    "lat": float(r.get("latency") or 0.0), "wall": time.time() - t0,
                    "p": r["usage"]["prompt"], "c": r["usage"]["completion"]})
    return r


llm.chat = chat_hook
import esm.judge as J  # noqa: E402
J.llm.chat = chat_hook

rows = []
LAKES = sys.argv[1].split(",") if len(sys.argv) > 1 else ["tlc", "bb"]
for lake in LAKES:
    ctx = C.load_context(lake)
    env = ctx.env
    F = {f["iid"]: f for f in ctx.facts}
    ids = [s["iid"] for s in sel if s["lake"] == lake]
    TS = C.TS[lake]
    S3_DERS = C.s3_derivation_keys(lake)
    _truth = env.truth

    def truth_hook(fact, t, _truth=_truth):
        TL.t = t
        return _truth(fact, t)

    env.truth = truth_hook
    _dget = ctx.ders.get

    def ders_hook(fact, t, _dget=_dget, S3_DERS=S3_DERS):
        new = (fact["iid"], t) not in S3_DERS
        r = _dget(fact, t)
        log = getattr(TL, "dlog", None)
        if log is not None:
            log.append({"t": t, "new": new, "secs": float(r.get("secs") or 0.0), "tok": sum(r["tokens"]),
                        "n_llm": r.get("n_llm", 0), "correct": r.get("correct")})
        return r

    ctx.ders.get = ders_hook
    pols = [("NEVER", "NEVER"), ("TTL", f"TTL{C.TTL_SHORT[lake]}"), ("TTL-mid", f"TTL{C.TTL_MID[lake]}"),
            ("REPLAY", "REPLAY"), ("ESM", "ESM-norepair")]
    for arm, pol in pols:
        t0 = time.time()
        for k, iid in enumerate(ids):
            f = F[iid]
            TL.log, TL.dlog = [], []
            if arm == "ESM":
                recs = simulate_esm(env, ctx.tab, f, TS, P.ESM[pol], ctx.ders)
            else:
                recs = B.simulate(ctx, pol, f, TS)
            for r in recs:
                calls = [x for x in TL.log if x["t"] == r.t and not x["tag"].startswith(("esm_derive", "dl_derive"))]
                ders = [x for x in TL.dlog if x["t"] == r.t]
                rows.append({"policy": arm, "policy_name": pol, "lake": lake, "iid": iid, "t": r.t, "served": r.served,
                             "served_valid": r.served_valid, "stored_valid": r.stored_valid, "action": r.action,
                             "verdict": r.verdict, "eval_tok": r.eval_tok, "eval_calls": r.eval_calls, "der_tok": r.der_tok,
                             "n_der": r.n_der, "judge_new": sum(not x["cached"] for x in calls),
                             "judge_reused": sum(x["cached"] for x in calls), "judge_lat": sum(x["lat"] for x in calls),
                             "der_new": sum(x["new"] for x in ders), "der_reused": sum(not x["new"] for x in ders),
                             "der_lat": sum(x["secs"] for x in ders), "der_llm_calls": sum(x["n_llm"] for x in ders),
                             "maint_tok": r.eval_tok + r.der_tok, "reason": (r.reason or "")[:200]})
            print(f"[{lake} {arm}] {k + 1}/{len(ids)} {iid} actions={[r.action for r in recs]} "
                  f"valid={[int(r.served_valid) for r in recs]} t={time.time() - t0:.0f}s", flush=True)
        ctx.save_obs()
        pd.DataFrame(rows).to_parquet(C.E2E / "memory_partial.parquet", index=False)
    env.truth = _truth
    ctx.ders.get = _dget

    # ---- ESM-eager: replay of the Stage-3 every-snapshot frozen ESM run (served at t, tokens spent in (t_prev, t])
    rec = pd.read_parquet(C.S3 / f"dl_{lake}" / "sim" / "ESM-norepair__every.parquet",
                          columns=["iid", "t", "served", "served_valid", "stored_valid", "action", "eval_tok", "der_tok",
                                   "n_der", "eval_calls"])
    rec = rec[rec.iid.isin(ids)]
    assert set(rec.iid) == set(ids), set(ids) - set(rec.iid)
    for iid in ids:
        g = rec[rec.iid == iid].set_index("t")
        prev = 0
        for t in TS:
            w = g.loc[prev + 1: t]
            rows.append({"policy": "ESM-eager", "policy_name": "ESM-norepair@every (Stage 3)", "lake": lake, "iid": iid, "t": t,
                         "served": g.loc[t, "served"], "served_valid": bool(g.loc[t, "served_valid"]),
                         "stored_valid": bool(g.loc[t, "stored_valid"]), "action": g.loc[t, "action"], "verdict": "",
                         "eval_tok": int(w.eval_tok.sum()), "eval_calls": int(w.eval_calls.sum()),
                         "der_tok": int(w.der_tok.sum()), "n_der": int(w.n_der.sum()), "judge_new": 0,
                         "judge_reused": int(w.eval_calls.sum()), "judge_lat": float("nan"), "der_new": 0,
                         "der_reused": int(w.n_der.sum()), "der_lat": float("nan"), "der_llm_calls": 0,
                         "maint_tok": int(w.eval_tok.sum() + w.der_tok.sum()), "reason": ""})
            prev = t
df = pd.DataFrame(rows)
if (C.E2E / "memory.parquet").exists() and len(LAKES) < 2:        # keep the other lake's rows
    old = pd.read_parquet(C.E2E / "memory.parquet")
    df = pd.concat([old[~old.lake.isin(LAKES)], df], ignore_index=True)
df.to_parquet(C.E2E / "memory.parquet", index=False)
print(df.groupby(["lake", "policy"])[["maint_tok", "judge_new", "judge_reused", "der_new", "der_reused", "served_valid"]].agg(
    ["sum", "mean"]).round(3).to_string())
print("LLM stats", llm.STATS)
