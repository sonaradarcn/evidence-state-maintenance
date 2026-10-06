"""Stage 4: end-to-end task-stream SIMULATION replayed from recorded held-out decisions (zero LLM, zero GPU).

Nothing here calls a model.  Every served answer and every token comes from the held-out stage's recorded per-(fact,
commit) runs (esm/results/heldout/records.parquet, schedule "every") or, for the two composed policies, from recorded
27B re-derivations (esm_data_heldout/derivations*.jsonl, via cache/facts.pkl).

Deployment model (LAZY, on-read maintenance; see README for why and for its validation):
  * a fact is maintained only when a task reads it; several reads of one fact at the same commit share one maintenance;
  * the answer served at a read at commit t = the answer the recorded every-commit run held at t (served_valid[t]);
  * the cost charged at a read at commit r, previous read of that fact at commit p (p = 0 for the first read):
      COALESCED (main):  one judgement if the recorded run judged anything in (p, r] (tokens of the last judgement in
                         that interval) + one re-derivation if it re-derived in (p, r] (tokens of the last one);
      SUM (sensitivity): all recorded judge + re-derivation tokens in (p, r]  (= paying every skipped commit);
  * EAGER (commit-hook) cost is also reported: the full recorded cost over all 400 commits for every fact in the set,
    independent of reads; under EAGER the served answers are exactly the recorded ones.
  * reads at t = 0 (before the first FUTURE commit) serve the verified s0 answer at zero cost.
Composed policies (labelled "composed" everywhere):
  * ALWAYS*  : re-derive at every read; the re-derivation at commit u is the RECORDED 27B re-derivation of that fact at
               the nearest commit with the same oracle value (exact commit when recorded); its answer is scored against
               the oracle at u; its tokens are its recorded tokens.
  * FILEHASH*: triggers = recorded FILEHASH@oracle re-derivation commits (s0 read set); the re-derivation at a trigger
               is imputed as for ALWAYS* and its answer is kept until the next trigger.
Certificate construction tokens (CERT-ZS, CERT-v0h) are added once per fact in the set.
"""
import json, pickle, time
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "esm" / "results" / "stream"
CACHE = OUT / "cache"
REC = ROOT / "esm" / "results" / "heldout" / "records.parquet"
N = 401   # commit index 0 = s0, 1..400 FUTURE

POL_ALL = ["ESM-norepair", "NEVER", "ALWAYS@oracle", "TTL50@oracle", "TTL100@oracle", "TTL200@oracle", "REPLAY@oracle",
           "FILEHASH@oracle", "ASTHASH@oracle", "CITE@oracle"]
POL_H = ["ESM-norepair", "ESM-verify", "NEVER", "ALWAYS*", "TTL50", "TTL100", "TTL200", "REPLAY", "FILEHASH*", "CERT-ZS",
         "LLMDIFF", "ESM-norepair@oracle", "ALWAYS@oracle", "TTL50@oracle", "TTL100@oracle", "REPLAY@oracle", "FILEHASH@oracle"]
POL_HS = POL_H + ["CERT-v0"]
LABEL = {"ESM-norepair": "ESM (frozen)", "ESM-norepair@oracle": "ESM@oracle", "CERT-v0": "CERT-v0h",
         "ALWAYS*": "ALWAYS (composed)", "FILEHASH*": "FILEHASH (composed)"}


def label(p):
    return LABEL.get(p, p)


# ------------------------------------------------------------------ data
def load_facts():
    with open(CACHE / "facts.pkl", "rb") as fh:
        return pickle.load(fh)


def impute(fx, u):
    """Recorded re-derivation standing in for a re-derivation of fact fx at commit u (nearest same-truth commit)."""
    ders = fx["ders"]
    if not ders:
        return None, "none"
    tr = fx["truth"]
    same = [d for d in ders if tr[d["t"]] == tr[u]]
    pool, kind = (same, "same_truth") if same else (ders, "other_truth")
    d = min(pool, key=lambda d: (abs(d["t"] - u), d["t"]))
    if d["t"] == u:
        kind = "exact"
    return d, kind


class Mats:
    """Per-policy matrices over (fact, commit 0..400)."""

    def __init__(self, ids):
        n = len(ids)
        self.ids = ids
        self.sv = np.ones((n, N), bool)
        self.et = np.zeros((n, N), np.int64)
        self.ec = np.zeros((n, N), np.int64)
        self.dt = np.zeros((n, N), np.int64)
        self.nd = np.zeros((n, N), np.int64)
        self.setup = np.zeros(n, np.int64)
        self.ok = np.ones(n, bool)       # fact covered by this policy's records

    def finish(self):
        idx = np.arange(N)[None, :]
        self.ce, self.cd = np.cumsum(self.et, 1), np.cumsum(self.dt, 1)
        self.cec, self.cnd = np.cumsum(self.ec, 1), np.cumsum(self.nd, 1)
        self.le = np.maximum.accumulate(np.where(self.ec > 0, idx, 0), 1)
        self.ld = np.maximum.accumulate(np.where(self.nd > 0, idx, 0), 1)
        self.eager = (self.et.sum(1) + self.dt.sum(1))
        return self


def build_mats(facts, ids, policies, records=None, log=None):
    pos = {i: k for k, i in enumerate(ids)}
    need = sorted({p for p in policies if not p.endswith("*")} | ({"FILEHASH@oracle"} if "FILEHASH*" in policies else set()))
    if records is None:
        records = load_records(need, set(ids))
    M = {}
    for p in need:
        m = Mats(ids)
        d = records[records.policy == p]
        got = set(d.iid)
        m.ok = np.array([i in got for i in ids])
        fi = d.iid.map(pos).to_numpy()
        t = d.t.to_numpy()
        m.sv[fi, t] = d.served_valid.to_numpy()
        m.et[fi, t] = d.eval_tok.to_numpy()
        m.ec[fi, t] = d.eval_calls.to_numpy()
        m.dt[fi, t] = d.der_tok.to_numpy()
        m.nd[fi, t] = d.n_der.to_numpy()
        if p in ("CERT-ZS", "CERT-v0"):
            key = "setup_certzs" if p == "CERT-ZS" else "setup_certv0"
            m.setup = np.array([facts[i][key] for i in ids], np.int64)
        M[p] = m
    imp_stats = {}
    if "ALWAYS*" in policies:
        m = Mats(ids)
        kinds = []
        for k, i in enumerate(ids):
            fx = facts[i]
            for u in range(1, N):
                d, kind = impute(fx, u)
                kinds.append(kind)
                if d is None:
                    m.ok[k] = False
                    break
                m.sv[k, u] = d["valid"][u - 1]
                m.dt[k, u] = d["tok"]
                m.nd[k, u] = 1
        M["ALWAYS*"] = m
        imp_stats["ALWAYS*"] = pd.Series(kinds).value_counts(normalize=True).to_dict()
    if "FILEHASH*" in policies:
        fo = M["FILEHASH@oracle"]
        m = Mats(ids)
        kinds = []
        for k, i in enumerate(ids):
            fx = facts[i]
            cur = [None] + list(fx["valid0"])       # validity of the held answer at u (index u)
            for u in range(1, N):
                if fo.nd[k, u] > 0:
                    d, kind = impute(fx, u)
                    kinds.append(kind)
                    if d is None:
                        m.ok[k] = False
                        break
                    cur = [None] + list(d["valid"])
                    m.dt[k, u] = d["tok"]
                    m.nd[k, u] = 1
                m.sv[k, u] = cur[u]
        M["FILEHASH*"] = m
        imp_stats["FILEHASH*"] = pd.Series(kinds).value_counts(normalize=True).to_dict()
    if "FILEHASH@oracle" not in policies:
        M.pop("FILEHASH@oracle", None)
    for m in M.values():
        m.finish()
    return M, imp_stats


def load_records(policies, ids, schedule="every"):
    cols = ["policy", "iid", "t", "served_valid", "eval_tok", "eval_calls", "der_tok", "n_der"]
    tb = pq.read_table(REC, columns=cols + ["schedule"], filters=[("policy", "in", list(policies)), ("schedule", "==", schedule)])
    d = tb.to_pandas()
    return d[d.iid.isin(ids)]


# ------------------------------------------------------------------ tasks
def gen_tasks(arr, clock, facts_by_repo, arrival, vol, kmode, zipf_s, seed):
    """One realisation of the task stream: DataFrame task, repo, time, t, iid."""
    rows = []
    for ri, (repo, fl) in enumerate(sorted(facts_by_repo.items())):
        rng = np.random.default_rng([seed, ri, 7])
        a = arr[arr.repo == repo]
        times = a.time.to_numpy()
        C = clock[repo]
        n = len(times)
        if arrival == "poisson":
            rngp = np.random.default_rng([seed, ri, 11])
            times = np.sort(rngp.uniform(C[0], C[-1], n))
        if vol < 1:
            times = times[np.random.default_rng([seed, ri, 13]).random(len(times)) < vol]
        elif vol > 1:
            times = np.repeat(times, int(round(vol)))
        ts = np.clip(np.searchsorted(C, times, side="right") - 1, 0, 400)
        nf = len(fl)
        rank = rng.permutation(nf)
        p = 1.0 / (rank + 1.0) ** zipf_s
        p /= p.sum()
        rngk = np.random.default_rng([seed, ri, 17])
        for j, (x, t) in enumerate(zip(times, ts)):
            k = {"u13": int(rngk.integers(1, 4)), "k1": 1, "k3": 3, "k5": 5}[kmode]
            k = min(k, nf)
            for f in rngk.choice(nf, k, replace=False, p=p):
                rows.append((f"{repo}#{j}", repo, x, int(t), fl[f]))
    return pd.DataFrame(rows, columns=["task", "repo", "time", "t", "iid"])


# ------------------------------------------------------------------ evaluation
def evaluate(tasks, M, ids, facts):
    """Per-policy read-level results for one task stream.  Returns dict policy -> DataFrame of reads with served_valid and
    charged costs (costs on the first read of a (fact, commit) only)."""
    pos = {i: k for k, i in enumerate(ids)}
    r = tasks.copy()
    r["fi"] = r.iid.map(pos)
    r = r.sort_values(["fi", "t", "time"], kind="stable").reset_index(drop=True)
    first = ~r.duplicated(["fi", "t"])                       # first read of that fact at that commit pays
    u = r[first][["fi", "t"]].copy()
    u["p"] = u.groupby("fi").t.shift(1).fillna(0).astype(int)
    fi, t, p = u.fi.to_numpy(), u.t.to_numpy(), u.p.to_numpy()
    out = {}
    for pol, m in M.items():
        sv = m.sv[r.fi.to_numpy(), r.t.to_numpy()]
        le, ld = m.le[fi, t], m.ld[fi, t]
        has_e, has_d = (le > p) & (t > 0), (ld > p) & (t > 0)
        e_co = np.where(has_e, m.et[fi, le], 0)
        d_co = np.where(has_d, m.dt[fi, ld], 0)
        e_sum = m.ce[fi, t] - m.ce[fi, p]
        d_sum = m.cd[fi, t] - m.cd[fi, p]
        x = r[["task", "repo", "time", "t", "iid", "fi"]].copy()
        x["sv"] = sv
        for col, val in (("e_co", e_co), ("d_co", d_co), ("e_sum", e_sum), ("d_sum", d_sum),
                         ("j_co", has_e.astype(int)), ("n_co", has_d.astype(int))):
            z = np.zeros(len(r), np.int64)
            z[first.to_numpy()] = val
            x[col] = z
        out[pol] = x
    return out


def aggregate(res, M, ids, facts, tasks, key):
    """Per (policy, repo) sums."""
    rows = []
    repo_of = np.array([facts[i]["repo"] for i in ids])
    for pol, x in res.items():
        m = M[pol]
        tw = x.groupby(["repo", "task"]).sv.all()
        tw = (~tw).groupby(level=0).agg(["sum", "size"])
        g = x.groupby("repo")
        agg = pd.DataFrame({"reads": g.size(), "wrong_reads": (~x.sv).groupby(x.repo).sum(),
                            "e_co": g.e_co.sum(), "d_co": g.d_co.sum(), "e_sum": g.e_sum.sum(), "d_sum": g.d_sum.sum(),
                            "judge_n": g.j_co.sum(), "der_n": g.n_co.sum()})
        agg["tasks"] = tw["size"]
        agg["wrong_tasks"] = tw["sum"]
        for repo in agg.index:
            sel = repo_of == repo
            agg.loc[repo, "eager_tok"] = int(m.eager[sel & m.ok].sum())
            agg.loc[repo, "setup_tok"] = int(m.setup[sel].sum())
        agg["policy"] = pol
        for k, v in key.items():
            agg[k] = v
        rows.append(agg.reset_index())
    return pd.concat(rows, ignore_index=True)


def per_fact(res, key):
    rows = []
    for pol, x in res.items():
        g = x.groupby("iid")
        d = pd.DataFrame({"reads": g.size(), "wrong_reads": (~x.sv).groupby(x.iid).sum(), "tok_co": g.e_co.sum() + g.d_co.sum(),
                          "tok_sum": g.e_sum.sum() + g.d_sum.sum()})
        d["policy"] = pol
        for k, v in key.items():
            d[k] = v
        rows.append(d.reset_index())
    return pd.concat(rows, ignore_index=True)


def stale_windows(res, key):
    """Episodes of wrong answers in service, from the reader's view: an episode starts at a wrong read whose previous read
    of that fact was right (or that is the fact's first read) and ends at the next right read (censored at window end)."""
    rows = []
    for pol, x in res.items():
        x = x.sort_values(["iid", "time"], kind="stable")
        for iid, g in x.groupby("iid", sort=False):
            sv, tm = g.sv.to_numpy(), g.time.to_numpy()
            i = 0
            while i < len(sv):
                if not sv[i]:
                    j = i
                    while j < len(sv) and not sv[j]:
                        j += 1
                    rows.append({"policy": pol, "iid": iid, "repo": g.repo.iat[0], "start": tm[i],
                                 "end": tm[j] if j < len(sv) else np.nan, "wrong_reads": j - i,
                                 "censored": j >= len(sv)})
                    i = j
                else:
                    i += 1
    d = pd.DataFrame(rows)
    for k, v in key.items():
        d[k] = v
    return d
