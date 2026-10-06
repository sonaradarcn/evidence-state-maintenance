"""Metrics over per-(fact, read) records (one DataFrame per policy x schedule; columns of maintain.Rec).

Definitions (per read t of fact f; "stored" = the answer held before maintenance at t, "served" = after):
  FF   = stored answer wrong (vs oracle at t) and the policy did NOT act (served it as fresh).   rate = #FF / #stored-wrong
  FS   = stored answer right and the policy acted (repair / re-derivation / judged stale).   rate = #FS / #stored-right
  served-wrong  = served answer != oracle at t (includes wrong repairs and wrong re-derivations); rate over all reads
  needless spend = evaluator + re-derivation tokens spent at reads whose stored answer was still right
  cost = evaluator tokens (incl. hierarchical screens) + re-derivation tokens (agent prompt + completion);
         re-derivation-equivalents (RDE) = tokens / the fact's logged s0 derivation tokens
Severity (per fact): ever served a wrong answer; stored-wrong episodes never acted on ("undetected changes");
detection delay = reads from the start of a stored-wrong episode to the first action.
Bootstrap: resample facts (B = 1000; paired B = 2000), ratio-of-sums estimators.
"""
import numpy as np
import pandas as pd

B = 1000


def per_fact(df, facts):
    """Aggregate a records DataFrame to one row per fact."""
    g = df.groupby("iid", sort=False)
    out = pd.DataFrame({
        "reads": g.size(),
        "ninv": g.apply(lambda x: int((~x.stored_valid).sum()), include_groups=False),
        "nval": g.apply(lambda x: int(x.stored_valid.sum()), include_groups=False),
        "ff": g.apply(lambda x: int((~x.stored_valid & ~x.flagged).sum()), include_groups=False),
        "fs": g.apply(lambda x: int((x.stored_valid & x.flagged).sum()), include_groups=False),
        "sw": g.apply(lambda x: int((~x.served_valid).sum()), include_groups=False),
        "eval_tok": g.eval_tok.sum(), "der_tok": g.der_tok.sum(), "eval_calls": g.eval_calls.sum(), "n_der": g.n_der.sum(),
        "nomemo_tok": g.nomemo_tok.sum(), "nomemo_calls": g.nomemo_calls.sum(), "guard_io": g.guard_io.sum(),
        "needless_tok": g.apply(lambda x: int(((x.eval_tok + x.der_tok) * x.stored_valid).sum()), include_groups=False),
        "n_repair": g.apply(lambda x: int((x.action == "repair").sum()), include_groups=False),
        "repair_ok": g.apply(lambda x: int((x.repair_ok == 1).sum()), include_groups=False),
    })
    sev = {}
    meta = {f["iid"]: f for f in facts}
    life = {}
    for iid, x in g:
        x = x.sort_values("t")
        # lifetime kept: reads before the s0 answer's first invalidation, and how many of them were served before the
        # policy's first action (repair / re-derivation / stale verdict)
        val0 = meta[iid]["valid"]
        ts, fl0 = x.t.to_numpy(), x.flagged.to_numpy()
        fi = next((i for i, v in enumerate(val0) if not v), len(val0))   # reads t <= fi are in the s0 answer's valid lifetime
        lt = [i for i, t in enumerate(ts) if t <= fi]
        first_act = next((i for i in range(len(ts)) if fl0[i]), len(ts))
        life[iid] = (len(lt), sum(1 for i in lt if i < first_act))
        inv = (~x.stored_valid).to_numpy()
        fl = x.flagged.to_numpy()
        eps, missed, delays, s = 0, 0, [], None
        for i in range(len(inv) + 1):
            if i < len(inv) and inv[i] and s is None:
                s = i
            if (i == len(inv) or not inv[i]) and s is not None:
                eps += 1
                w = np.where(fl[s:i])[0]
                if len(w):
                    delays.append(int(w[0]))
                else:
                    missed += 1
                s = None
        sev[iid] = (eps, missed, float(np.mean(delays)) if delays else np.nan, int((~x.served_valid).any()))
    sv = pd.DataFrame(sev, index=["eps", "eps_missed", "delay", "ever_sw"]).T
    out = out.join(sv)
    lf = pd.DataFrame(life, index=["life", "life_kept"]).T
    out = out.join(lf)
    out["slice"] = [meta[i]["slice"] for i in out.index]
    out["type"] = [meta[i]["type"] for i in out.index]
    out["repo"] = [meta[i]["repo"] for i in out.index]
    out["dtok"] = [sum(meta[i]["derive_tokens"]) for i in out.index]
    out["changing"] = [not all(meta[i]["valid"]) for i in out.index]
    out["tok"] = out.eval_tok + out.der_tok
    out["rde"] = out.tok / out.dtok
    return out


def _ratio(num, den, rng, n_boot=B):
    num, den = np.asarray(num, float), np.asarray(den, float)
    n = len(num)
    est = num.sum() / max(den.sum(), 1)
    bs = []
    for _ in range(n_boot):
        ix = rng.integers(0, n, n)
        bs.append(num[ix].sum() / max(den[ix].sum(), 1))
    return est, np.percentile(bs, [2.5, 97.5]).tolist()


def summary(pf, seed=0):
    rng = np.random.default_rng(seed)
    if len(pf) == 0:
        return None
    ff = _ratio(pf.ff, pf.ninv, rng)
    fs = _ratio(pf.fs, pf.nval, rng)
    sw = _ratio(pf.sw, pf.reads, rng)
    tok = pf.tok.to_numpy(float)
    bs = [tok[rng.integers(0, len(tok), len(tok))].mean() for _ in range(B)]
    chg = pf[pf.changing]
    return {"n": len(pf), "n_chg": int(pf.changing.sum()), "reads": int(pf.reads.sum()),
            "ff": ff[0], "ff_ci": ff[1], "fs": fs[0], "fs_ci": fs[1], "sw": sw[0], "sw_ci": sw[1],
            "acc": 1 - sw[0],
            "tok_per_fact": float(tok.mean()), "tok_ci": np.percentile(bs, [2.5, 97.5]).tolist(),
            "eval_tok_per_fact": float(pf.eval_tok.mean()), "der_tok_per_fact": float(pf.der_tok.mean()),
            "rde_sum": float(pf.tok.sum() / pf.dtok.sum()), "rde_mean": float(pf.rde.mean()),
            "tok_per_read": float(pf.tok.sum() / pf.reads.sum()),
            "calls_per_fact": float(pf.eval_calls.mean()), "der_per_fact": float(pf.n_der.mean()),
            "nomemo_tok_per_fact": float(pf.nomemo_tok.mean() + pf.der_tok.mean()),
            "nomemo_calls_per_fact": float(pf.nomemo_calls.mean()),
            "needless_frac": float(pf.needless_tok.sum() / max(pf.tok.sum(), 1)),
            "needless_tok_per_fact": float(pf.needless_tok.mean()),
            "repairs": int(pf.n_repair.sum()), "repair_ok": int(pf.repair_ok.sum()),
            "repair_rate": float(pf.repair_ok.sum() / max(pf.n_repair.sum(), 1)),
            "ever_sw": float(pf.ever_sw.mean()), "ever_sw_chg": float(chg.ever_sw.mean()) if len(chg) else np.nan,
            "eps_missed": float(pf.eps_missed.sum() / max(pf.eps.sum(), 1)), "eps": int(pf.eps.sum()),
            "delay_mean": float(np.nanmean(pf.delay)) if pf.delay.notna().any() else np.nan,
            "guard_io_per_read": float(pf.guard_io.sum() / pf.reads.sum()),
            "life_kept": float(pf.life_kept.sum() / max(pf.life.sum(), 1)) if "life" in pf else np.nan}


def paired(pa, pb, seed=1, n_boot=2000):
    """A - B on common facts: dFF, dFS, d served-wrong (pp of the pooled rates; B's denominators for FF/FS use each
    policy's own stored-answer counts), d tokens per fact."""
    ids = sorted(set(pa.index) & set(pb.index))
    a, b = pa.loc[ids], pb.loc[ids]
    rng = np.random.default_rng(seed)
    n = len(ids)

    def stat(ix):
        aa, bb = a.iloc[ix], b.iloc[ix]
        return (aa.ff.sum() / max(aa.ninv.sum(), 1) - bb.ff.sum() / max(bb.ninv.sum(), 1),
                aa.fs.sum() / max(aa.nval.sum(), 1) - bb.fs.sum() / max(bb.nval.sum(), 1),
                aa.sw.sum() / max(aa.reads.sum(), 1) - bb.sw.sum() / max(bb.reads.sum(), 1),
                aa.tok.mean() - bb.tok.mean())
    est = stat(np.arange(n))
    bs = np.array([stat(rng.integers(0, n, n)) for _ in range(n_boot)])
    ci = np.percentile(bs, [2.5, 97.5], axis=0).T
    return {"n": n, "dff": est[0], "dff_ci": ci[0].tolist(), "dfs": est[1], "dfs_ci": ci[1].tolist(),
            "dsw": est[2], "dsw_ci": ci[2].tolist(), "dtok": est[3], "dtok_ci": ci[3].tolist()}
