"""Shared helpers for the reviewer-round-1 revision analyses (zero LLM, zero GPU).

Everything is computed from esm/results/heldout/records.parquet (one row per policy x schedule x fact x read, written by
esm/scripts/report_heldout.py) plus the kept-fact metadata (oracle truth / validity, repo, type, slice, subset) loaded
once through esm.policies.Context (offline) and cached in ./cache/meta.pkl.

Per-fact aggregation uses esm.metrics.per_fact, i.e. the SAME definitions as the paper (served-wrong = served answer !=
oracle at t, pooled ratio-of-sums over reads; FF / FS as in pilot7; tokens = evaluator + re-derivation tokens, plus the
one-time certificate construction tokens for CERT-ZS / CERT-v0 exactly as report_heldout.with_setup does).
"""
import json, os, pickle, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
DATA_DIR = ROOT / "esm_data_heldout"
os.environ.setdefault("ESM_DATA", str(DATA_DIR))
os.environ.setdefault("ESM_STAGE", "heldout")
os.environ["ESM_LLM_OFFLINE"] = "1"
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
from esm import metrics as M

CACHE = HERE / "cache"
CACHE.mkdir(exist_ok=True)
REC_PATH = ROOT / "esm" / "results" / "heldout" / "records.parquet"
FROZEN = "ESM-norepair"
B = 2000


def load_meta():
    p = CACHE / "meta.pkl"
    if p.exists():
        return pickle.loads(p.read_bytes())
    from esm.policies import Context
    ctx = Context.load("heldout")
    facts = []
    for f in ctx.facts:
        facts.append({k: f[k] for k in ("iid", "repo", "type", "slice", "subset", "valid", "derive_tokens", "K")}
                     | {"truth": list(f["truth"]), "cert_tokens": f.get("cert_tokens") or {}})
    meta = {"facts": facts, "H150": json.loads((DATA_DIR / "sub_H150.json").read_text()),
            "H80R": json.loads((DATA_DIR / "sub_H80R.json").read_text())}
    p.write_bytes(pickle.dumps(meta))
    return meta


META = load_meta()
FACTS = META["facts"]
FX = {f["iid"]: f for f in FACTS}
ALL = set(FX)
H150 = set(META["H150"]) & ALL
NAT = {i for i in ALL if FX[i]["subset"] == "natural"}
ENR = ALL - NAT
BEH = {i for i in ALL if FX[i]["slice"] == "behav"}
STA = ALL - BEH
NOJ = {i for i in ALL if FX[i]["repo"] != "jinja"}
REPOS = sorted({f["repo"] for f in FACTS})


def truth(iid, t):
    return FX[iid]["truth"][300 + int(t)]


def changing(iid):
    return not all(FX[iid]["valid"])


_REC = None


def records(policy=None, schedule=None, columns=None):
    """Rows of records.parquet for one policy / schedule (row order preserved = the report's order)."""
    filt = []
    if policy is not None:
        filt.append(("policy", "==", policy))
    if schedule is not None:
        filt.append(("schedule", "==", schedule))
    return pd.read_parquet(REC_PATH, filters=filt or None, columns=columns)


def pf(policy, schedule="every"):
    """esm.metrics.per_fact frame for one arm (cached), with setup tokens added for CERT-* (report_heldout.with_setup)."""
    key = CACHE / f"pf__{policy}__{schedule}.pkl"
    if key.exists():
        out = pd.read_pickle(key)
    else:
        d = records(policy, schedule)
        if not len(d):
            return None
        out = M.per_fact(d, FACTS)
        out.to_pickle(key)
    base = policy.split("@")[0]
    if base in ("CERT-ZS", "CERT-v0") and "@oracle" not in policy:
        out = out.copy()
        k = "certzs" if base == "CERT-ZS" else "certv0h"
        out["tok"] = out.tok + np.array([FX[i]["cert_tokens"].get(k) or 0 for i in out.index], float)
        out["rde"] = out.tok / out.dtok
    return out


# ------------------------------------------------------------------ resampling
def _w_fact(n, rng, nb=B):
    return rng.multinomial(n, np.full(n, 1.0 / n), size=nb).astype(float)          # (nb, n) fact weights


def _w_repo(repo_idx, nrep, rng, nb=B):
    """fact weights for a repo-cluster bootstrap: repos drawn with replacement, all facts of a drawn repo kept."""
    draws = rng.integers(0, nrep, size=(nb, nrep))
    cnt = np.zeros((nb, nrep))
    for j in range(nrep):
        cnt[:, j] = (draws == j).sum(1)
    return cnt[:, repo_idx]                                                            # (nb, n)


def ratio_stats(num, den, repo, seed=0):
    """Pooled ratio sum(num)/sum(den) with (a) fact bootstrap CI, (b) repo-cluster bootstrap CI,
    (c) repo-level equal-weight mean with CI over repos (bootstrap of repos), (d) leave-one-repo-out min / max.
    num/den/repo are per-fact arrays."""
    num, den = np.asarray(num, float), np.asarray(den, float)
    repo = np.asarray(repo)
    reps = sorted(set(repo))
    ridx = np.array([reps.index(r) for r in repo])
    rng = np.random.default_rng(seed)
    est = num.sum() / den.sum()
    wf = _w_fact(len(num), rng)
    fb = (wf @ num) / np.maximum(wf @ den, 1)
    wr = _w_repo(ridx, len(reps), rng)
    cb = (wr @ num) / np.maximum(wr @ den, 1)
    rn = np.array([num[ridx == j].sum() for j in range(len(reps))])
    rd = np.array([den[ridx == j].sum() for j in range(len(reps))])
    rr = rn / np.maximum(rd, 1)
    rm = rr.mean()
    draws = rng.integers(0, len(reps), size=(B, len(reps)))
    rmb = rr[draws].mean(1)
    loro = [(num.sum() - rn[j]) / (den.sum() - rd[j]) for j in range(len(reps))]
    jmin, jmax = int(np.argmin(loro)), int(np.argmax(loro))
    return {"est": est, "fact_ci": np.percentile(fb, [2.5, 97.5]).tolist(), "clu_ci": np.percentile(cb, [2.5, 97.5]).tolist(),
            "repo_mean": rm, "repo_mean_ci": np.percentile(rmb, [2.5, 97.5]).tolist(),
            "loro": (min(loro), max(loro)), "loro_arg": (reps[jmin], reps[jmax]), "n_repos": len(reps),
            "per_repo": dict(zip(reps, rr.tolist()))}


def paired_stats(a, b, ids, seed=1, alpha_levels=(0.05, 0.10)):
    """A - B served-wrong (pooled) and tokens/fact on common facts `ids`, with fact / repo-cluster bootstrap,
    repo-level paired effects and leave-one-repo-out.  Returns percentiles for 95 % and 90 % two-sided CIs."""
    ids = sorted(ids & set(a.index) & set(b.index))
    A, Bf = a.loc[ids], b.loc[ids]
    swa, rda, swb, rdb = (A.sw.to_numpy(float), A.reads.to_numpy(float), Bf.sw.to_numpy(float), Bf.reads.to_numpy(float))
    ta, tb = A.tok.to_numpy(float), Bf.tok.to_numpy(float)
    repo = np.array([FX[i]["repo"] for i in ids])
    reps = sorted(set(repo))
    ridx = np.array([reps.index(r) for r in repo])
    n = len(ids)

    def stat(W):
        d = (W @ swa) / (W @ rda) - (W @ swb) / (W @ rdb)
        dt = (W @ (ta - tb)) / W.sum(1)
        return d, dt

    est = stat(np.ones((1, n)))
    rng = np.random.default_rng(seed)
    fd, ft = stat(_w_fact(n, rng))
    cd, ct = stat(_w_repo(ridx, len(reps), rng))
    q = [2.5, 97.5, 5, 95]
    # per-repo paired effects (equal weight per repo)
    per = {}
    for j, r in enumerate(reps):
        m = ridx == j
        per[r] = (swa[m].sum() / rda[m].sum() - swb[m].sum() / rdb[m].sum(), (ta[m] - tb[m]).mean(), int(m.sum()))
    pe = np.array([v[0] for v in per.values()])
    draws = rng.integers(0, len(reps), size=(B, len(reps)))
    pmb = pe[draws].mean(1)
    loro = []
    for j in range(len(reps)):
        w = (ridx != j).astype(float)[None]
        loro.append(stat(w)[0][0])
    from scipy import stats as S
    nz = pe[pe != 0]
    sign_p = S.binomtest(int((nz < 0).sum()), len(nz), 0.5).pvalue if len(nz) else 1.0
    try:
        wil_p = S.wilcoxon(pe[pe != 0]).pvalue if len(nz) >= 6 else float("nan")
    except Exception:
        wil_p = float("nan")
    return {"n": n, "n_repos": len(reps), "d": est[0][0], "dt": est[1][0],
            "fact": np.percentile(fd, q).tolist(), "clu": np.percentile(cd, q).tolist(),
            "fact_tok": np.percentile(ft, q[:2]).tolist(), "clu_tok": np.percentile(ct, q[:2]).tolist(),
            "repo_mean": pe.mean(), "repo_mean_ci": np.percentile(pmb, q).tolist(),
            "repo_neg": int((pe < 0).sum()), "repo_pos": int((pe > 0).sum()), "repo_zero": int((pe == 0).sum()),
            "sign_p": sign_p, "wilcoxon_p": wil_p, "loro": (min(loro), max(loro)), "per_repo": per,
            "wa": swa.sum() / rda.sum(), "wb": swb.sum() / rdb.sum(), "toka": ta.mean(), "tokb": tb.mean()}


def p1(x):
    return f"{100 * x:.1f}"


def ci1(c):
    return f"[{100 * c[0]:.1f}, {100 * c[1]:.1f}]"


def sci1(c):
    return f"[{100 * c[0]:+.1f}, {100 * c[1]:+.1f}]"
