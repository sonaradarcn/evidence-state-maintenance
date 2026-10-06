"""Stage 4 report (zero LLM): tables + figures from results/stream/{agg,perfact,stale}.parquet.

usage: python -m esm.stream.report -> results/stream/{tables.md, results.json, pareto.png, timeline_<repo>.png, sensitivity.png}
"""
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker
from . import sim as S

B = 2000
OUT = S.OUT
AG = pd.read_parquet(OUT / "agg.parquet")
PF = pd.read_parquet(OUT / "perfact.parquet")
ST = pd.read_parquet(OUT / "stale.parquet")
META = json.loads((OUT / "arrivals_meta.json").read_text())
CLK = pd.read_parquet(OUT / "clock.parquet")
CLOCK = {r: g.sort_values("t").time.to_numpy() for r, g in CLK.groupby("repo")}
NSEED = AG.seed.nunique()
L, RES = [], {}
REAL_COST_H = ["ESM-norepair", "ESM-verify", "NEVER", "ALWAYS*", "TTL50", "TTL100", "TTL200", "REPLAY", "FILEHASH*", "CERT-ZS", "LLMDIFF"]
ORACLE_H = ["ESM-norepair@oracle", "ALWAYS@oracle", "TTL50@oracle", "TTL100@oracle", "REPLAY@oracle", "FILEHASH@oracle"]


def P(x):
    return f"{100 * x:.1f}"


def per_repo(sel):
    g = sel.groupby("repo")[["tasks", "wrong_tasks", "reads", "wrong_reads", "e_co", "d_co", "e_sum", "d_sum", "judge_n", "der_n",
                             "eager_tok", "setup_tok"]].sum()
    g["tok"] = g.e_co + g.d_co + g.setup_tok
    g["tok_sum"] = g.e_sum + g.d_sum + g.setup_tok
    g["tok_eager"] = g.eager_tok + g.setup_tok
    return g


def ratio_boot(num, den, rng, idx=None):
    n = len(num)
    ix = rng.integers(0, n, (B, n)) if idx is None else idx
    return np.percentile(num[ix].sum(1) / np.maximum(den[ix].sum(1), 1e-12), [2.5, 97.5])


def summary(set_, arrival="real", config="default", pols=None):
    a = AG[(AG.set == set_) & (AG.arrival == arrival) & (AG.config == config)]
    pols = pols or list(dict.fromkeys(a.policy))
    out = {}
    repos = sorted(a.repo.unique())
    rng = np.random.default_rng(0)
    ixr = rng.integers(0, len(repos), (B, len(repos)))
    never = per_repo(a[a.policy == "NEVER"]).reindex(repos) if "NEVER" in set(a.policy) else None
    for p in pols:
        g = per_repo(a[a.policy == p]).reindex(repos)
        wt, ts, tok = g.wrong_tasks.to_numpy(float), g.tasks.to_numpy(float), g.tok.to_numpy(float)
        o = {"tasks": ts.sum() / NSEED, "wrong_tasks": wt.sum() / NSEED, "wt": wt.sum() / ts.sum(),
             "wt_ci": ratio_boot(wt, ts, None, ixr).tolist(),
             "wr": g.wrong_reads.sum() / g.reads.sum(), "reads": g.reads.sum() / NSEED,
             "tok_total": tok.sum() / NSEED, "tok_task": tok.sum() / ts.sum(), "tok_task_ci": ratio_boot(tok, ts, None, ixr).tolist(),
             "judge_tok": g.e_co.sum() / NSEED, "der_tok": g.d_co.sum() / NSEED, "setup_tok": g.setup_tok.sum() / NSEED,
             "judge_n": g.judge_n.sum() / NSEED, "der_n": g.der_n.sum() / NSEED,
             "tok_task_sum": g.tok_sum.sum() / ts.sum(), "tok_task_eager": g.tok_eager.sum() / ts.sum()}
        o["wrong_per_1k_tok"] = o["wrong_tasks"] / (o["tok_total"] / 1000) if o["tok_total"] > 0 else None
        if never is not None and o["tok_total"] > 0:
            o["avoided_per_1M_tok"] = (never.wrong_tasks.sum() / NSEED - o["wrong_tasks"]) / (o["tok_total"] / 1e6)
        # fact bootstrap (read level), default config only
        f = PF[(PF.set == set_) & (PF.arrival == arrival) & (PF.config == config) & (PF.policy == p)]
        if len(f):
            ff = f.groupby("iid")[["reads", "wrong_reads", "tok_co"]].sum()
            # facts never read have no row: they contribute 0 reads (and 0 tokens)
            rng2 = np.random.default_rng(1)
            o["wr_ci_fact"] = ratio_boot(ff.wrong_reads.to_numpy(float), ff.reads.to_numpy(float), rng2).tolist()
            o["n_facts_read"] = len(ff)
        out[p] = o
    return out, ixr, repos


def paired(set_, base, others, arrival="real", config="default", other_arrival=None):
    """Paired differences base - other (repo bootstrap on wrong-task % and tokens/task; fact bootstrap on wrong-read %)."""
    a = AG[(AG.set == set_) & (AG.config == config)]
    repos = sorted(a.repo.unique())
    rng = np.random.default_rng(2)
    ixr = rng.integers(0, len(repos), (B, len(repos)))
    def arrs(p, arv):
        g = per_repo(a[(a.policy == p) & (a.arrival == arv)]).reindex(repos)
        return g.wrong_tasks.to_numpy(float), g.tasks.to_numpy(float), g.tok.to_numpy(float)
    wb, tb, kb = arrs(base, arrival)
    out = {}
    for o in others:
        wo, to, ko = arrs(o, other_arrival or arrival)
        d_w = wb.sum() / tb.sum() - wo.sum() / to.sum()
        bw = wb[ixr].sum(1) / tb[ixr].sum(1) - wo[ixr].sum(1) / to[ixr].sum(1)
        d_k = kb.sum() / tb.sum() - ko.sum() / to.sum()
        bk = kb[ixr].sum(1) / tb[ixr].sum(1) - ko[ixr].sum(1) / to[ixr].sum(1)
        r = {"d_wt": d_w, "d_wt_ci": np.percentile(bw, [2.5, 97.5]).tolist(), "d_tok_task": d_k,
             "d_tok_task_ci": np.percentile(bk, [2.5, 97.5]).tolist()}
        fa = PF[(PF.set == set_) & (PF.config == config)]
        fb = fa[(fa.policy == base) & (fa.arrival == arrival)].groupby("iid")[["reads", "wrong_reads"]].sum()
        fo = fa[(fa.policy == o) & (fa.arrival == (other_arrival or arrival))].groupby("iid")[["reads", "wrong_reads"]].sum()
        if len(fb) and len(fo):
            j = fb.join(fo, lsuffix="_b", rsuffix="_o", how="outer").fillna(0)
            n = len(j)
            ix = np.random.default_rng(3).integers(0, n, (B, n))
            A = j.to_numpy(float)
            bs = A[ix, 1].sum(1) / A[ix, 0].sum(1) - A[ix, 3].sum(1) / A[ix, 2].sum(1)
            r["d_wr"] = A[:, 1].sum() / A[:, 0].sum() - A[:, 3].sum() / A[:, 2].sum()
            r["d_wr_ci_fact"] = np.percentile(bs, [2.5, 97.5]).tolist()
        out[o] = r
    return out


def stale_stats(set_, arrival="real", pols=None):
    s = ST[(ST.set == set_) & (ST.arrival == arrival)].copy()
    endw = {r: c[-1] for r, c in CLOCK.items()}
    s["end2"] = np.where(s.censored, s.repo.map(endw), s.end)
    s["days"] = (s.end2 - s.start) / 86400
    out = {}
    for p in pols or sorted(s.policy.unique()):
        x = s[s.policy == p]
        if not len(x):
            out[p] = {"episodes": 0}
            continue
        out[p] = {"episodes": len(x) / NSEED, "median_days": float(x.days.median()), "mean_days": float(x.days.mean()),
                  "p90_days": float(x.days.quantile(0.9)), "censored": float(x.censored.mean()),
                  "wrong_reads_per_ep": float(x.wrong_reads.mean()),
                  "median_days_uncensored": float(x[~x.censored].days.median()) if (~x.censored).any() else None}
    return out


def kendall(a, b):
    ks = list(a)
    c = d = 0
    for i in range(len(ks)):
        for j in range(i + 1, len(ks)):
            s = np.sign(a[ks[i]] - a[ks[j]]) * np.sign(b[ks[i]] - b[ks[j]])
            c += s > 0
            d += s < 0
    return (c - d) / max(c + d, 1)


# ------------------------------------------------------------------ tables
def main_table(set_, pols, title, key):
    s, _, _ = summary(set_, pols=pols)
    st = stale_stats(set_, pols=pols)
    RES[key] = {"summary": s, "stale": st}
    L.append(f"\n### {title}\n")
    L.append("| policy | wrong-served tasks % [repo CI] | wrong tasks / run | wrong reads % [fact CI] | tokens / task [repo CI] | total tokens / run "
             "| judge : re-deriv. (: setup) tokens | judge calls / re-derivations per run | wrong tasks per 1k tokens | wrong tasks avoided vs NEVER per 1M tokens "
             "| stale window: episodes / run, median days (p90), % censored |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for p in pols:
        o, t = s[p], st.get(p, {})
        tot = o["judge_tok"] + o["der_tok"] + o["setup_tok"]
        split = (f"{100 * o['judge_tok'] / tot:.0f} : {100 * o['der_tok'] / tot:.0f}" + (f" : {100 * o['setup_tok'] / tot:.0f}" if o["setup_tok"] else "")) if tot else "–"
        w1k = f"{o['wrong_per_1k_tok']:.3f}" if o.get("wrong_per_1k_tok") is not None else "– (0 tokens)"
        av = f"{o['avoided_per_1M_tok']:.1f}" if o.get("avoided_per_1M_tok") is not None else "–"
        stw = (f"{t['episodes']:.0f}, {t['median_days']:.1f} ({t['p90_days']:.0f}), {100 * t['censored']:.0f} %" if t.get("episodes") else "0")
        wrci = f"[{P(o['wr_ci_fact'][0])}, {P(o['wr_ci_fact'][1])}]" if "wr_ci_fact" in o else ""
        L.append(f"| {S.label(p)} | {P(o['wt'])} [{P(o['wt_ci'][0])}, {P(o['wt_ci'][1])}] | {o['wrong_tasks']:.0f} / {o['tasks']:.0f} "
                 f"| {P(o['wr'])} {wrci} | {o['tok_task']:,.0f} [{o['tok_task_ci'][0]:,.0f}, {o['tok_task_ci'][1]:,.0f}] "
                 f"| {o['tok_total'] / 1e6:.2f}M | {split} | {o['judge_n']:.0f} / {o['der_n']:.0f} | {w1k} | {av} | {stw} |")
    return s


def paired_table(set_, base, others, title, key, other_arrival=None, arrival="real"):
    d = paired(set_, base, others, arrival=arrival, other_arrival=other_arrival)
    RES[key] = d
    L.append(f"\n### {title}\n")
    L.append("| comparison | Δ wrong-served tasks, pp [repo CI] | Δ wrong reads, pp [fact CI] | Δ tokens / task [repo CI] |")
    L.append("|---|---|---|---|")
    for o, r in d.items():
        fc = f"{100 * r['d_wr']:+.1f} [{100 * r['d_wr_ci_fact'][0]:+.1f}, {100 * r['d_wr_ci_fact'][1]:+.1f}]" if "d_wr" in r else "–"
        L.append(f"| {S.label(base)} − {S.label(o)} | {100 * r['d_wt']:+.1f} [{100 * r['d_wt_ci'][0]:+.1f}, {100 * r['d_wt_ci'][1]:+.1f}] "
                 f"| {fc} | {r['d_tok_task']:+,.0f} [{r['d_tok_task_ci'][0]:+,.0f}, {r['d_tok_task_ci'][1]:+,.0f}] |")


def real_vs_poisson(set_, pols, key):
    sr, _, _ = summary(set_, "real", pols=pols)
    sp, _, _ = summary(set_, "poisson", pols=pols)
    d = {}
    for p in pols:
        d[p] = paired(set_, p, [p], arrival="real", other_arrival="poisson")[p]
    stp = stale_stats(set_, "poisson", pols)
    str_ = stale_stats(set_, "real", pols)
    L.append(f"\n### Real arrivals vs Poisson control ({set_}, default configuration; Δ = real − Poisson, repo bootstrap)\n")
    L.append("| policy | wrong tasks % real | Poisson | Δ pp [CI] | tokens/task real | Poisson | Δ [CI] | median stale days real / Poisson |")
    L.append("|---|---|---|---|---|---|---|---|")
    for p in pols:
        r = d[p]
        L.append(f"| {S.label(p)} | {P(sr[p]['wt'])} | {P(sp[p]['wt'])} | {100 * r['d_wt']:+.1f} [{100 * r['d_wt_ci'][0]:+.1f}, {100 * r['d_wt_ci'][1]:+.1f}] "
                 f"| {sr[p]['tok_task']:,.0f} | {sp[p]['tok_task']:,.0f} | {r['d_tok_task']:+,.0f} [{r['d_tok_task_ci'][0]:+,.0f}, {r['d_tok_task_ci'][1]:+,.0f}] "
                 f"| {str_[p].get('median_days', float('nan')):.1f} / {stp[p].get('median_days', float('nan')):.1f} |")
    rk = {}
    for name, f in (("wrong-task %", lambda s, p: s[p]["wt"]), ("tokens/task", lambda s, p: s[p]["tok_task"])):
        a = {p: f(sr, p) for p in pols}
        b = {p: f(sp, p) for p in pols}
        ra = {p: i for i, p in enumerate(sorted(pols, key=lambda p: a[p]))}
        rb = {p: i for i, p in enumerate(sorted(pols, key=lambda p: b[p]))}
        moved = [f"{S.label(p)} {ra[p] + 1}→{rb[p] + 1}" for p in pols if ra[p] != rb[p]]
        rk[name] = {"kendall_tau": kendall(a, b), "rank_real": ra, "rank_poisson": rb, "moved": moved}
        L.append(f"\nRanking by {name}: Kendall τ(real, Poisson) = {kendall(a, b):.3f}; rank changes (real→Poisson): "
                 + (", ".join(moved) if moved else "none"))
    RES[key] = {"real": sr, "poisson": sp, "paired": d, "ranking": rk}


def sensitivity(set_, pols, key):
    rows = {}
    L.append(f"\n### Sensitivity ({set_}, real arrivals): wrong-served tasks % / tokens per task\n")
    cfgs = ["vol0.3", "default", "vol3", "k1", "k3", "zipf0", "zipf1.5"]
    L.append("| policy | " + " | ".join({"default": "default (×1, k∈{1,2,3}, Zipf 1)", "vol0.3": "volume ×0.3", "vol3": "volume ×3",
                                          "k1": "k = 1", "k3": "k = 3", "zipf0": "uniform popularity", "zipf1.5": "Zipf 1.5"}[c] for c in cfgs) + " |")
    L.append("|---|" + "---|" * len(cfgs))
    for c in cfgs:
        rows[c] = summary(set_, config=c, pols=pols)[0]
    for p in pols:
        L.append(f"| {S.label(p)} | " + " | ".join(f"{P(rows[c][p]['wt'])} / {rows[c][p]['tok_task']:,.0f}" for c in cfgs) + " |")
    # ranking stability across configurations (by wrong-task %)
    base = {p: rows["default"][p]["wt"] for p in pols}
    L.append("\nKendall τ of the wrong-task ranking vs default: " + ", ".join(
        f"{c} {kendall(base, {p: rows[c][p]['wt'] for p in pols}):.2f}" for c in cfgs if c != "default"))
    RES[key] = rows
    return rows


def cost_models(set_, pols, key):
    s, _, _ = summary(set_, pols=pols)
    L.append(f"\n### Cost accounting variants ({set_}, real arrivals, default): tokens per task\n")
    L.append("| policy | LAZY coalesced (main) | LAZY sum over skipped commits (upper bound) | EAGER commit-hook (exact replay; all facts, every commit) |")
    L.append("|---|---|---|---|")
    for p in pols:
        o = s[p]
        L.append(f"| {S.label(p)} | {o['tok_task']:,.0f} | {o['tok_task_sum']:,.0f} | {o['tok_task_eager']:,.0f} |")
    RES[key] = {p: {k: s[p][k] for k in ("tok_task", "tok_task_sum", "tok_task_eager")} for p in pols}


def repo_table():
    s = AG[(AG.set == "ALL") & (AG.arrival == "real") & (AG.config == "default")]
    L.append("\n### Per repository (ALL facts, real arrivals, default; per run = mean over 10 seeds)\n")
    L.append("| repo | arrival source | window (days) | issues | tasks / run | facts | ESM wrong tasks % | NEVER | TTL100@oracle | REPLAY@oracle | ESM tokens / task |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    from collections import Counter
    import pickle
    facts = S.load_facts()
    nf = Counter(v["repo"] for v in facts.values())
    out = {}
    for repo in sorted(s.repo.unique()):
        m = META[repo]
        g = {p: s[(s.repo == repo) & (s.policy == p)][["tasks", "wrong_tasks", "e_co", "d_co"]].sum() for p in ("ESM-norepair", "NEVER", "TTL100@oracle", "REPLAY@oracle")}
        src = ("own" if m["source"] == "own" else "proxy") + f": {m['trace_asset']}"
        days = (CLOCK[repo][-1] - CLOCK[repo][0]) / 86400
        e = g["ESM-norepair"]
        L.append(f"| {repo} | {src} | {days:.0f} | {m['n_issues']} | {e.tasks / NSEED:.0f} | {nf[repo]} | {P(e.wrong_tasks / e.tasks)} | "
                 f"{P(g['NEVER'].wrong_tasks / g['NEVER'].tasks)} | {P(g['TTL100@oracle'].wrong_tasks / g['TTL100@oracle'].tasks)} | "
                 f"{P(g['REPLAY@oracle'].wrong_tasks / g['REPLAY@oracle'].tasks)} | {(e.e_co + e.d_co) / e.tasks:,.0f} |")
        out[repo] = {"source": src, "days": days, "issues": m["n_issues"]}
    RES["per_repo"] = out


# ------------------------------------------------------------------ figures
def fig_pareto():
    fig, axs = plt.subplots(1, 2, figsize=(13, 5.2))
    for ax, (set_, pols) in zip(axs, (("H150", REAL_COST_H + ORACLE_H), ("ALL", S.POL_ALL))):
        sr, _, _ = summary(set_, "real", pols=pols)
        sp, _, _ = summary(set_, "poisson", pols=pols)
        floor = 30
        pts = []
        for p in pols:
            o, q = sr[p], sp[p]
            x, xq = max(o["tok_task"], floor), max(q["tok_task"], floor)
            orc = "@oracle" in p
            col = "C3" if p.startswith("ESM") else ("0.55" if orc else "C0")
            ax.errorbar(x, 100 * o["wt"], yerr=[[100 * (o["wt"] - o["wt_ci"][0])], [100 * (o["wt_ci"][1] - o["wt"])]],
                        fmt="s" if orc else "o", color=col, mfc=col, ms=6, capsize=2, lw=0.8)
            ax.plot(xq, 100 * q["wt"], "o" if not orc else "s", mfc="none", color=col, ms=7, lw=0)
            ax.annotate(S.label(p).replace(" (composed)", "*"), (x, 100 * o["wt"]), fontsize=7, xytext=(4, 3), textcoords="offset points")
            if not orc:
                pts.append((x, 100 * o["wt"]))
        pts.sort()
        front, best = [], 1e9
        for x, y in pts:
            if y < best:
                front.append((x, y))
                best = y
        ax.step([f[0] for f in front], [f[1] for f in front], where="post", color="C3", alpha=0.35, lw=1.5)
        ax.set_xscale("log")
        ax.set_xlabel(f"tokens per task (log; 0 drawn at {floor})")
        ax.set_ylabel("tasks served ≥1 wrong answer (%)")
        ax.set_title(f"{set_}: real arrivals (filled, repo-bootstrap CI) vs Poisson (hollow)\ncircles = real re-derivation cost, squares = @oracle (idealised)", fontsize=9)
        ax.grid(alpha=0.3)
    fig.suptitle("Stage 4 task-stream SIMULATION replayed from recorded held-out decisions (lazy maintenance, default config, 10 seeds)", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "pareto.png", dpi=150)
    plt.close(fig)


def fig_timeline(repo="networkx", set_="ALL", seed=0, nfacts=8):
    facts = S.load_facts()
    arr = pd.read_parquet(OUT / "arrivals.parquet")
    ids = [i for i in facts if (facts[i]["H150"] or set_ == "ALL")]
    by = {}
    for i in ids:
        by.setdefault(facts[i]["repo"], []).append(i)
    pols = ["ESM-norepair", "NEVER"]
    M, _ = S.build_mats(facts, ids, pols)
    tasks = S.gen_tasks(arr, CLOCK, {repo: by[repo]}, "real", 1.0, "u13", 1.0, seed)
    res = S.evaluate(tasks, M, ids, facts)
    e, nv = res["ESM-norepair"], res["NEVER"]
    # facts to show: most-read facts with any ESM action or any wrong read under NEVER
    cnt = e.groupby("iid").size()
    act = set(e[(e.j_co > 0) | (e.n_co > 0)].iid) | set(nv[~nv.sv].iid)
    wr = set(e[~e.sv].iid)
    order = list(cnt.sort_values(ascending=False).index)
    show = [i for i in order if i in wr][:nfacts // 2]
    show += [i for i in order if i in act and i not in show][:nfacts - len(show)]
    C = CLOCK[repo]
    d0 = C[0]
    day = lambda x: (np.asarray(x) - d0) / 86400
    fig, ax = plt.subplots(figsize=(13, 0.55 * len(show) + 2.2))
    ax.vlines(day(C[1:]), len(show) + 0.6, len(show) + 1.0, color="0.4", lw=0.5)
    ax.vlines(day(tasks.drop_duplicates("task").time), len(show) + 1.15, len(show) + 1.55, color="C0", lw=0.5)
    ax.text(day(C[-1]) * 1.005, len(show) + 0.8, "commits", fontsize=7, va="center")
    ax.text(day(C[-1]) * 1.005, len(show) + 1.35, "tasks (issues)", fontsize=7, va="center", color="C0")
    for k, iid in enumerate(show):
        y = len(show) - 1 - k + 0.5
        x = e[e.iid == iid].sort_values("time")
        xn = nv[nv.iid == iid].sort_values("time")
        # wrong-served episodes (reader's view) under ESM (red band) and NEVER (grey band)
        for xx, col, dy in ((xn, "0.75", -0.28), (x, "C3", 0.0)):
            sv, tm = xx.sv.to_numpy(), xx.time.to_numpy()
            i = 0
            while i < len(sv):
                if not sv[i]:
                    j = i
                    while j < len(sv) and not sv[j]:
                        j += 1
                    end = tm[j] if j < len(sv) else C[-1]
                    ax.add_patch(plt.Rectangle((day(tm[i]), y - 0.18 + dy), day(end) - day(tm[i]), 0.12 if dy else 0.36,
                                               color=col, alpha=0.35 if dy == 0 else 0.8, lw=0))
                    i = j
                else:
                    i += 1
        ax.plot(day(x[x.sv].time), [y] * int(x.sv.sum()), "o", ms=3.5, color="C2")
        ax.plot(day(x[~x.sv].time), [y] * int((~x.sv).sum()), "x", ms=5, color="C3")
        jc = x[(x.j_co > 0) & (x.n_co == 0)]
        rd = x[x.n_co > 0]
        ax.plot(day(jc.time), [y + 0.3] * len(jc), "v", ms=5, color="C1")
        ax.plot(day(rd.time), [y + 0.3] * len(rd), "s", ms=5, color="C4")
        ax.text(-0.01 * day(C[-1]), y, iid, ha="right", va="center", fontsize=7)
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    ax.legend(handles=[Line2D([], [], marker="o", color="C2", lw=0, label="read, right answer served (ESM)"),
                       Line2D([], [], marker="x", color="C3", lw=0, label="read, wrong answer served (ESM)"),
                       Line2D([], [], marker="v", color="C1", lw=0, label="judge call (ESM, no re-derivation)"),
                       Line2D([], [], marker="s", color="C4", lw=0, label="judge + re-derivation (ESM)"),
                       Patch(color="C3", alpha=0.35, label="wrong answer in service (ESM)"),
                       Patch(color="0.75", label="wrong answer in service (NEVER)")],
              fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3)
    ax.set_yticks([])
    ax.set_xlim(-0.005 * day(C[-1]), day(C[-1]) * 1.09)
    ax.set_ylim(-0.2, len(show) + 1.8)
    ax.set_xlabel(f"days since s0 ({pd.to_datetime(d0, unit='s').date()}); {META[repo]['source']} arrivals from {META[repo]['trace_asset']}")
    ax.set_title(f"{repo}: one simulated task stream (seed {seed}, default config) replayed from recorded ESM / NEVER decisions; "
                 f"{len(show)} facts", fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT / f"timeline_{repo}.png", dpi=150)
    plt.close(fig)
    return show


def fig_sensitivity(rows, pols, set_="H150"):
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.3))
    vols = [("vol0.3", 0.3), ("default", 1), ("vol3", 3)]
    for p in pols:
        ls = "-" if "@oracle" not in p else ":"
        axs[0].plot([v for _, v in vols], [100 * rows[c][p]["wt"] for c, _ in vols], "o" + ls, label=S.label(p), ms=4)
        if p != "NEVER":
            axs[1].plot([v for _, v in vols], [rows[c][p]["tok_task"] for c, _ in vols], "o" + ls, label=S.label(p), ms=4)
    for ax in axs:
        ax.set_xscale("log")
        ax.set_xticks([0.3, 1, 3])
        ax.set_xticklabels(["×0.3", "×1", "×3"])
        ax.xaxis.set_minor_locator(matplotlib.ticker.NullLocator())
        ax.set_xlabel("read volume (tasks relative to the real issue volume)")
        ax.grid(alpha=0.3)
    axs[0].set_ylabel("tasks served ≥1 wrong answer (%)")
    axs[1].set_ylabel("tokens per task (log; NEVER = 0 not drawn)")
    axs[1].set_yscale("log")
    axs[1].legend(fontsize=7, ncol=2)
    fig.suptitle(f"{set_}, real arrivals: sensitivity to read volume (SIMULATION from recorded decisions)", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "sensitivity.png", dpi=150)
    plt.close(fig)


def main():
    L.append("# Stage 4 tables (generated by `python -m esm.stream.report`; SIMULATION replayed from recorded held-out decisions)")
    L.append(f"\nSeeds per configuration: {NSEED}. 'per run' = mean over seeds. Wrong-served task = a task with ≥ 1 of its k reads served a wrong answer.")
    main_table("H150", REAL_COST_H + ORACLE_H, "T1. H150 (160 facts), real arrivals, default configuration", "T1_H150")
    paired_table("H150", "ESM-norepair", [p for p in REAL_COST_H + ORACLE_H if p != "ESM-norepair"],
                 "T2. Paired differences on H150 (real arrivals, default)", "T2_paired_H150")
    main_table("H150s", ["ESM-norepair", "CERT-v0", "CERT-ZS", "REPLAY", "NEVER"], "T1s. H150 static subset (133 facts; CERT-v0h is static-only)", "T1s")
    paired_table("H150s", "ESM-norepair", ["CERT-v0", "CERT-ZS", "REPLAY"], "T2s. Paired, H150 static subset", "T2s")
    main_table("ALL", S.POL_ALL, "T3. ALL (1,419 facts), real arrivals, default configuration (baselines other than ESM / NEVER are @oracle = idealised)", "T3_ALL")
    paired_table("ALL", "ESM-norepair", [p for p in S.POL_ALL if p != "ESM-norepair"], "T4. Paired differences on ALL", "T4_paired_ALL")
    real_vs_poisson("H150", REAL_COST_H + ORACLE_H, "T5_poisson_H150")
    real_vs_poisson("ALL", S.POL_ALL, "T5_poisson_ALL")
    rows = sensitivity("H150", REAL_COST_H + ORACLE_H, "T6_sens_H150")
    sensitivity("ALL", S.POL_ALL, "T6_sens_ALL")
    cost_models("H150", REAL_COST_H + ORACLE_H, "T7_cost_H150")
    repo_table()
    fig_pareto()
    show = fig_timeline()
    RES["timeline_facts"] = show
    fig_sensitivity(rows, ["ESM-norepair", "NEVER", "ALWAYS*", "TTL50", "TTL100", "REPLAY", "FILEHASH*", "CERT-ZS", "LLMDIFF", "REPLAY@oracle"])
    (OUT / "tables.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (OUT / "results.json").write_text(json.dumps(RES, indent=1, default=lambda x: x.item() if hasattr(x, "item") else str(x)))
    print("\n".join(L))


if __name__ == "__main__":
    main()
