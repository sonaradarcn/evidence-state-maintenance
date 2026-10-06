"""Tables, bootstrap CIs, paired differences, the code-repo vs lake contrast and figures
-> esm/results/e2e_lake/
usage: python -m esm.e2e_lake.report_lake"""
import json, os
os.environ.setdefault("ESM_LLM_OFFLINE", "1")
import numpy as np
import pandas as pd
from esm.e2e_lake import common_lake as C

ARMS = ["NO-MEMORY", "NEVER", "TTL", "TTL-mid", "REPLAY", "ESM", "ESM-eager", "ORACLE"]
MEMARMS = ["NEVER", "TTL", "TTL-mid", "REPLAY", "ESM"]
B = 2000
rng = np.random.default_rng(C.SEED)
RES = C.RES
RES.mkdir(parents=True, exist_ok=True)

tasks = json.loads((C.E2E / "tasks.json").read_text(encoding="utf-8"))
mem = pd.read_parquet(C.E2E / "memory.parquet")
M = {(r.policy, r.iid, int(r.t)): r for r in mem.itertuples()}
FACTS = {}
for lake in ("tlc", "bb"):
    d = json.loads((C.ROOT / "datalake" / f"facts_{lake}.json").read_text())
    tr = json.loads((C.E2E / f"truth_{lake}_real.json").read_text())
    for f in d["facts"]:
        FACTS[f["id"]] = {"lake": lake, "type": f["type"], "args": f["args"], "K_oracle": tr[f["id"]][0]}


def load_runs(name):
    out = {}
    p = C.E2E / name
    if p.exists():
        for l in p.read_text(encoding="utf-8").splitlines():
            if l.strip():
                d = json.loads(l)
                out[d["key"]] = d
    return out


runs = load_runs("runs.jsonl")


def mem_correct(task, ans):
    if ans is None or str(ans).strip() == "":
        return False
    try:
        return C.F.canon(FACTS[task["iid"]], str(ans)) == str(task["fact_value"])
    except Exception:
        return False


def offset_rank(t):
    return {25: 1, 50: 2, 100: 3, 20: 1, 40: 2, 80: 3}[t]


def build(runs_, arms):
    rows = []
    for t in tasks:
        for arm in arms:
            if arm == "NO-MEMORY":
                m, mr = None, None
            elif arm == "ORACLE":
                m, mr = str(t["fact_value"]), None
            else:
                mr = M[(arm, t["iid"], t["t"])]
                m = "" if mr.served is None else str(mr.served)
            r = runs_.get(json.dumps([t["tid"], m]))
            if r is None:
                continue
            task_tok = r["prompt_tok"] + r["compl_tok"]
            maint = 0 if mr is None else int(mr.maint_tok)
            mlat = 0.0 if mr is None else (float((mr.judge_lat or 0) + (mr.der_lat or 0)) if arm != "ESM-eager" else np.nan)
            rows.append({"arm": arm, "tid": t["tid"], "iid": t["iid"], "lake": t["lake"], "t": t["t"],
                         "offset": offset_rank(t["t"]), "task_type": t["task_type"], "fact_type": t["fact_type"],
                         "possible": t["truth"]["possible"], "outcome": r["check"]["outcome"], "detail": r["check"]["detail"],
                         "submitted": r["sub"]["kind"], "memory": m,
                         "mem_correct": None if arm == "NO-MEMORY" else (True if arm == "ORACLE" else mem_correct(t, m)),
                         "task_tok": task_tok, "maint_tok": maint, "tok": task_tok + maint, "n_llm": r["n_llm"],
                         "n_tools": r["n_tools"], "task_lat": r["llm_lat"] + r["tool_s"], "maint_lat": mlat,
                         "lat": r["llm_lat"] + r["tool_s"] + (0 if np.isnan(mlat) else mlat),
                         "maint_action": None if mr is None else mr.action,
                         "der_new": None if mr is None else mr.der_new, "der_reused": None if mr is None else mr.der_reused,
                         "judge_new": None if mr is None else mr.judge_new, "judge_reused": None if mr is None else mr.judge_reused,
                         "fetch_wait_s": r.get("fetch_wait_s", 0), "shared_run_first_arm": r["first_arm"]})
    df = pd.DataFrame(rows)
    df["success"] = df.outcome == "success"
    df["wrong"] = df.outcome == "wrong"
    df["fail"] = df.outcome == "fail"
    df["abstain"] = df.submitted == "abstain"
    return df


df = build(runs, ARMS)
df.to_parquet(RES / "task_outcomes.parquet", index=False)
complete = df.groupby("arm").tid.nunique().to_dict()


def ci(x, cluster=None):
    x = np.asarray(x, float)
    if len(x) == 0:
        return (np.nan, np.nan, np.nan)
    if cluster is None:
        bs = x[rng.integers(0, len(x), (B, len(x)))].mean(1)
    else:
        cl = pd.Series(x).groupby(np.asarray(cluster))
        s, n = cl.sum().values, cl.size().values
        idx = rng.integers(0, len(s), (B, len(s)))
        bs = s[idx].sum(1) / n[idx].sum(1)
    return (x.mean(), *np.percentile(bs, [2.5, 97.5]))


def fmt(c, pct=True, d=1):
    k = 100 if pct else 1
    return f"{c[0] * k:.{d}f} [{c[1] * k:.{d}f}, {c[2] * k:.{d}f}]"


def fk(x):
    return f"{x / 1000:.1f}k"


def table(g, by=None, arms=ARMS):
    out = []
    keys = [None] if by is None else sorted(g[by].unique())
    for key in keys:
        for arm in arms:
            s = g[(g.arm == arm)] if key is None else g[(g.arm == arm) & (g[by] == key)]
            if s.empty:
                continue
            out.append({**({by: key} if by else {}), "arm": arm, "n": len(s),
                        "success %": fmt(ci(s.success)), "wrong action %": fmt(ci(s.wrong)), "failure %": fmt(ci(s.fail)),
                        "abstain %": f"{100 * s.abstain.mean():.1f}",
                        "memory right %": ("–" if arm == "NO-MEMORY" else f"{100 * s.mem_correct.astype(float).mean():.1f}"),
                        "tokens/task (task + maint.)": f"{fk(s.tok.mean())} ({fk(s.task_tok.mean())} + {fk(s.maint_tok.mean())})",
                        "LLM calls/task": f"{s.n_llm.mean():.1f}",
                        "latency s/task (task + maint.)": ("–" if s.lat.isna().all() else
                                                           f"{s.lat.mean():.1f} ({s.task_lat.mean():.1f} + {np.nanmean(s.maint_lat) if s.maint_lat.notna().any() else float('nan'):.1f})")})
    return pd.DataFrame(out)


def paired(g, base, metric, arms=ARMS):
    out = []
    a = g.pivot_table(index="tid", columns="arm", values=metric, aggfunc="first")
    fid = a.index.map(lambda x: x.split("@")[0])
    for arm in arms:
        if arm == base or arm not in a or base not in a:
            continue
        ok = a[arm].notna() & a[base].notna()
        d = (a[arm].astype(float) - a[base].astype(float))[ok]
        c_t, c_f = ci(d.values), ci(d.values, cluster=np.asarray(fid[ok]))
        out.append((arm, len(d), c_t, c_f))
    return out


def paired_md(g, bases, metrics, arms=ARMS):
    md = []
    for base in bases:
        pr = []
        for metric, pct in metrics:
            for arm, n, ct, cf in paired(g, base, metric, arms):
                pr.append({"base": base, "metric": metric, "arm": arm, "n": n, "Δ [task CI]": fmt(ct, pct, 1 if pct else 0),
                           "fact-cluster CI": f"[{cf[1] * (100 if pct else 1):.{1 if pct else 0}f}, {cf[2] * (100 if pct else 1):.{1 if pct else 0}f}]"})
        md.append(pd.DataFrame(pr).to_markdown(index=False))
    return md


MET = (("success", True), ("wrong", True), ("fail", True), ("tok", False), ("lat", False))
md = ["# B3-lake tables (generated by `python -m esm.e2e_lake.report_lake`; zero LLM)\n"]
md.append(f"Tasks per arm with a completed run: {complete}\n")
md.append("## T1 main table (both lakes; CIs: bootstrap over tasks, B = 2000)\n")
md.append(table(df).to_markdown(index=False))
md.append("\n## T1-lake per lake\n")
md.append(table(df, "lake").to_markdown(index=False))
md.append("\n## T1c clustered by fact (26 clusters)\n")
rows_c = []
for arm in ARMS:
    s = df[df.arm == arm]
    if not s.empty:
        rows_c.append({"arm": arm, "success %": fmt(ci(s.success, s.iid)), "wrong %": fmt(ci(s.wrong, s.iid)),
                       "failure %": fmt(ci(s.fail, s.iid))})
md.append(pd.DataFrame(rows_c).to_markdown(index=False))
md.append("\n## T2 paired differences: arm − base (pp for rates; tokens and seconds per task; CI over tasks | clustered by fact)\n")
md += paired_md(df, ["NO-MEMORY", "NEVER"], MET)
for lake in ("tlc", "bb"):
    md.append(f"\n### T2-{lake} paired, {lake} only\n")
    md += paired_md(df[df.lake == lake], ["NO-MEMORY", "NEVER"], (("success", True), ("wrong", True), ("tok", False)))
md.append("\n## T2b paired: ESM − TTL and ESM − REPLAY\n")
pr = []
for base in ("TTL", "TTL-mid", "REPLAY"):
    for metric, pct in (("success", True), ("wrong", True), ("tok", False), ("lat", False)):
        for arm, n, ct, cf in paired(df, base, metric):
            if arm == "ESM":
                pr.append({"base": base, "metric": metric, "n": n, "Δ [task CI]": fmt(ct, pct, 1 if pct else 0),
                           "fact-cluster CI": f"[{cf[1] * (100 if pct else 1):.{1 if pct else 0}f}, {cf[2] * (100 if pct else 1):.{1 if pct else 0}f}]"})
md.append(pd.DataFrame(pr).to_markdown(index=False))
md.append("\n## T3 by task type\n")
md.append(table(df, "task_type").to_markdown(index=False))
md.append("\n## T3b by fact type\n")
md.append(table(df, "fact_type", ["NO-MEMORY", "NEVER", "TTL", "REPLAY", "ESM", "ORACLE"]).to_markdown(index=False))
md.append("\n## T4 by snapshot offset (1 = TLC +25 / BB +20; 2 = +50 / +40; 3 = +100 / +80)\n")
md.append(table(df, "offset", ["NO-MEMORY", "NEVER", "TTL", "REPLAY", "ESM", "ORACLE"]).to_markdown(index=False))
md.append("\n## T5 tasks whose referent is gone at t (correct action = abstain / NONE)\n")
md.append(table(df[~df.possible]).to_markdown(index=False) if (~df.possible).any() else "none (no selected task has a gone referent)")
md.append("\n## T6 outcome by memory correctness (memory arms pooled: NEVER, TTL, TTL-mid, REPLAY, ESM)\n")
s = df[df.arm.isin(MEMARMS)]
x = s.groupby("mem_correct")[["success", "wrong", "fail"]].mean().mul(100).round(1)
x["n"] = s.groupby("mem_correct").size()
md.append(x.to_markdown())
nm = df[df.arm == "NO-MEMORY"].set_index("tid")
s2 = s.assign(nomem_success=s.tid.map(nm.success), nomem_tok=s.tid.map(nm.task_tok))
x2 = s2.groupby("mem_correct")[["success", "nomem_success"]].mean().mul(100).round(1)
x2["task tokens (memory arm)"] = s2.groupby("mem_correct").task_tok.mean().round(0)
x2["task tokens (NO-MEMORY, same task)"] = s2.groupby("mem_correct").nomem_tok.mean().round(0)
md.append("\nSame tasks without memory:\n")
md.append(x2.to_markdown())
md.append("\n## T7 maintenance work at the task reads (lazy policies; recorded = identical request made in Stage 3)\n")
mm = mem[mem.policy != "ESM-eager"].groupby(["lake", "policy"]).agg(
    reads=("t", "size"), memory_right=("served_valid", "mean"), tokens_per_read=("maint_tok", "mean"),
    judge_calls_new=("judge_new", "sum"), judge_calls_recorded=("judge_reused", "sum"), rederiv_new=("der_new", "sum"),
    rederiv_recorded=("der_reused", "sum"))
md.append(mm.round(3).to_markdown())
e = mem[mem.policy == "ESM-eager"].groupby("lake").agg(reads=("t", "size"), memory_right=("served_valid", "mean"),
                                                        tokens_per_read=("maint_tok", "mean"), judge_calls=("eval_calls", "sum"),
                                                        rederivations=("n_der", "sum"))
md.append("\nESM-eager (replayed Stage-3 every-snapshot run; tokens = all spent in (t_prev, t]):\n")
md.append(e.round(3).to_markdown())
fresh = [r for r in runs.values() if not r["cached_all"] and r["n_llm"] > 0]
spt = sum(r["llm_lat"] for r in fresh) / max(1, sum(r["prompt_tok"] + r["compl_tok"] for r in fresh))
md.append(f"\n## T7b maintenance latency re-estimated on this server\n\nRecorded maintenance latencies (T1) are Stage-3 "
          f"wall-clock (two GPUs, other jobs in flight). Re-estimate: maintenance tokens x {spt * 1000:.2f} s per 1k tokens "
          f"(this server's rate on {len(fresh)} fresh task runs, 1 request in flight, same model and tool loop).\n")
le = []
for arm in ["NO-MEMORY", "NEVER", "TTL", "TTL-mid", "REPLAY", "ESM", "ESM-eager"]:
    s_ = df[df.arm == arm]
    if s_.empty:
        continue
    le.append({"arm": arm, "task latency s": round(s_.task_lat.mean(), 1),
               "maint. latency s (recorded)": round(np.nanmean(s_.maint_lat), 1) if s_.maint_lat.notna().any() else None,
               "maint. latency s (est.)": round(s_.maint_tok.mean() * spt, 1),
               "total s (est.)": round(s_.task_lat.mean() + s_.maint_tok.mean() * spt, 1)})
md.append(pd.DataFrame(le).to_markdown(index=False))
md.append("\n## T8 T-sql executions (every submitted query is executed at t)\n")
q = df[(df.task_type == "T-sql") & (df.submitted == "submit")]
if len(q):
    md.append(q.groupby("arm").outcome.value_counts().unstack(fill_value=0).to_markdown())

# ---------------------------------------------------------------- contrast with the code-repo e2e
cr = json.loads((C.ROOT / "esm" / "results" / "e2e" / "results.json").read_text())
res = {"complete_tasks": complete, "arms": {}, "by_lake": {}}
for arm in ARMS:
    s_ = df[df.arm == arm]
    if s_.empty:
        continue
    res["arms"][arm] = {"n": len(s_), "success": ci(s_.success), "wrong": ci(s_.wrong), "fail": ci(s_.fail),
                        "abstain": float(s_.abstain.mean()), "tok": s_.tok.mean(), "task_tok": s_.task_tok.mean(),
                        "maint_tok": s_.maint_tok.mean(), "lat": s_.lat.mean(), "task_lat": s_.task_lat.mean(),
                        "n_llm": s_.n_llm.mean(), "mem_correct": None if arm == "NO-MEMORY" else float(s_.mem_correct.astype(float).mean())}
    for lake in ("tlc", "bb"):
        sl = s_[s_.lake == lake]
        res["by_lake"].setdefault(lake, {})[arm] = {"n": len(sl), "success": ci(sl.success), "wrong": ci(sl.wrong),
                                                    "tok": sl.tok.mean(), "task_tok": sl.task_tok.mean(), "maint_tok": sl.maint_tok.mean()}
res["paired_vs_NEVER"] = {m: {a: [n, ct, cf] for a, n, ct, cf in paired(df, "NEVER", m)} for m in ("success", "wrong", "tok", "lat")}
res["paired_vs_NOMEM"] = {m: {a: [n, ct, cf] for a, n, ct, cf in paired(df, "NO-MEMORY", m)} for m in ("success", "wrong", "tok", "lat")}
res["sec_per_token_this_server"] = spt
res["maint_latency_est"] = {x_["arm"]: x_ for x_ in le}

ctr = []


def crow(env_name, A, P_nm, n_tasks, rederive_cost):
    nmem, esm = A["NO-MEMORY"], A["ESM"]
    never = A["NEVER"]
    ds = P_nm["success"]["ESM"][1]
    dt = P_nm["tok"]["ESM"][1]
    return {"environment": env_name, "tasks": n_tasks, "fact re-derivation cost (s0 derivation, tokens)": rederive_cost,
            "NO-MEMORY task tokens": fk(nmem["task_tok"]), "ESM task tokens": fk(esm["task_tok"]),
            "task tokens saved by memory (NO-MEM − ESM task)": fk(nmem["task_tok"] - esm["task_tok"]),
            "ESM maint. tokens/read": fk(esm["maint_tok"]),
            "NO-MEMORY success / wrong %": f"{100 * nmem['success'][0]:.1f} / {100 * nmem['wrong'][0]:.1f}",
            "NEVER success / wrong %": f"{100 * never['success'][0]:.1f} / {100 * never['wrong'][0]:.1f}",
            "ESM success / wrong %": f"{100 * esm['success'][0]:.1f} / {100 * esm['wrong'][0]:.1f}",
            "ESM − NO-MEM success pp": f"{100 * ds[0]:+.1f} [{100 * ds[1]:+.1f}, {100 * ds[2]:+.1f}]",
            "ESM − NO-MEM total tokens/task": f"{dt[0] / 1000:+.1f}k [{dt[1] / 1000:+.1f}, {dt[2] / 1000:+.1f}]"}


ctr.append(crow("code repositories (B3, cheap re-derivation)", cr["arms"], cr["paired_vs_NOMEM"], 120, "≈ 8–19k"))
ctr.append(crow("data lakes, both (this run)", res["arms"], res["paired_vs_NOMEM"], len(tasks), "TLC ≈ 34k, BB ≈ 70k"))
for lake, cost in (("tlc", "≈ 34k (re-derivation 46k)"), ("bb", "≈ 70k")):
    g = df[df.lake == lake]
    A = {a: {"success": ci(g[g.arm == a].success), "wrong": ci(g[g.arm == a].wrong), "task_tok": g[g.arm == a].task_tok.mean(),
             "maint_tok": g[g.arm == a].maint_tok.mean()} for a in ("NO-MEMORY", "NEVER", "ESM") if (g.arm == a).any()}
    if len(A) == 3:
        Pn = {m: {a: [n, ct, cf] for a, n, ct, cf in paired(g, "NO-MEMORY", m)} for m in ("success", "tok")}
        ctr.append(crow(f"data lake {lake.upper()} only", A, Pn, int(g.tid.nunique()), cost))
md.append("\n## T10 contrast: code-repository e2e (cheap re-derivation) vs data-lake e2e (expensive re-derivation)\n")
md.append(pd.DataFrame(ctr).to_markdown(index=False))
res["contrast"] = ctr

# break-even: per-task saving of memory in task tokens vs maintenance per read, by fact type
be = []
for (lake, ft), g in df.groupby(["lake", "fact_type"]):
    a = g.pivot_table(index="tid", columns="arm", values="task_tok", aggfunc="first")
    mt = g.pivot_table(index="tid", columns="arm", values="maint_tok", aggfunc="first")
    sc = g.pivot_table(index="tid", columns="arm", values="success", aggfunc="first")
    if "NO-MEMORY" in a and "ESM" in a:
        be.append({"lake": lake, "fact type": ft, "tasks": len(a), "NO-MEMORY task tok": fk(a["NO-MEMORY"].mean()),
                   "ESM task tok": fk(a["ESM"].mean()), "ESM maint tok/read": fk(mt["ESM"].mean()),
                   "TTL maint tok/read": fk(mt["TTL"].mean()) if "TTL" in mt else "–",
                   "net saving ESM vs NO-MEM": fk(a["NO-MEMORY"].mean() - a["ESM"].mean() - mt["ESM"].mean()),
                   "success NO-MEM / NEVER / ESM %": f"{100 * sc['NO-MEMORY'].mean():.0f} / {100 * sc['NEVER'].mean():.0f} / {100 * sc['ESM'].mean():.0f}"})
md.append("\n## T11 where memory pays: task-token saving vs maintenance, by lake x fact type\n")
md.append(pd.DataFrame(be).to_markdown(index=False))

# ---------------------------------------------------------------- pre-registered secondary: trust prompt
rt = load_runs("runs_trust.jsonl")
tr = None
if rt:
    tr = build(rt, ["NEVER", "TTL", "TTL-mid", "REPLAY", "ESM", "ORACLE"])
    tr.to_parquet(RES / "task_outcomes_trust.parquet", index=False)
    both = pd.concat([df[df.arm == "NO-MEMORY"], tr], ignore_index=True)
    md.append("\n## T9 pre-registered secondary: memory presented as verified facts to rely on (NO-MEMORY row = main run)\n")
    md.append(table(both).to_markdown(index=False))
    md.append("\n### T9 paired (trust variant)\n")
    md += paired_md(both, ["NO-MEMORY", "NEVER"], (("success", True), ("wrong", True), ("tok", False)))
    md.append("\n### T9 by task type (trust variant)\n")
    md.append(table(both, "task_type", ["NO-MEMORY", "NEVER", "TTL", "REPLAY", "ESM", "ORACLE"]).to_markdown(index=False))
    s3 = tr[tr.arm.isin(MEMARMS)]
    x = s3.groupby("mem_correct")[["success", "wrong", "fail"]].mean().mul(100).round(1)
    x["n"] = s3.groupby("mem_correct").size()
    md.append("\n### T9 outcome by memory correctness (trust variant)\n")
    md.append(x.to_markdown())
    res["trust"] = {arm: {"n": int((both.arm == arm).sum()), "success": ci(both[both.arm == arm].success),
                          "wrong": ci(both[both.arm == arm].wrong), "fail": ci(both[both.arm == arm].fail),
                          "tok": float(both[both.arm == arm].tok.mean()), "task_tok": float(both[both.arm == arm].task_tok.mean())}
                    for arm in both.arm.unique()}
    res["trust_paired_vs_NOMEM"] = {m: {a: [n, ct, cf] for a, n, ct, cf in paired(both, "NO-MEMORY", m)} for m in ("success", "wrong", "tok")}
    res["trust_paired_vs_NEVER"] = {m: {a: [n, ct, cf] for a, n, ct, cf in paired(both, "NEVER", m)} for m in ("success", "wrong", "tok")}
(RES / "tables.md").write_text("\n".join(md) + "\n", encoding="utf-8")
C.jdump(RES / "results.json", res)
df.to_json(RES / "task_outcomes.json", orient="records", indent=1, force_ascii=False)

# ---------------------------------------------------------------- figures
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
COL = {"success": "#2a78d6", "wrong": "#eb6834", "fail": "#b9b8b2"}
plt.rcParams.update({"font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2,
                     "figure.facecolor": SURF, "axes.facecolor": SURF})
arms = [a for a in ARMS if a in res["arms"]]
fig, ax = plt.subplots(figsize=(7.2, 3.6))
for i, a in enumerate(arms):
    left = 0
    for k in ("success", "wrong", "fail"):
        v = res["arms"][a][k][0] * 100
        ax.barh(i, v, left=left, color=COL[k], height=0.62, edgecolor=SURF, linewidth=2,
                label={"success": "success", "wrong": "wrong action", "fail": "failure / abstention"}[k] if i == 0 else None)
        if v >= 7:
            ax.text(left + v / 2, i, f"{v:.0f}", ha="center", va="center", color="white" if k != "fail" else INK, fontsize=8)
        left += v
ax.set_yticks(range(len(arms)), [a + (" *" if a in ("ORACLE", "ESM-eager") else "") for a in arms])
ax.invert_yaxis()
ax.set_xlim(0, 100)
ax.set_xlabel(f"% of tasks ({len(tasks)} per arm, both lakes)")
ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.16), ncol=3, frameon=False)
for s_ in ("top", "right"):
    ax.spines[s_].set_visible(False)
ax.text(0, -0.2, "* ORACLE = idealised memory; ESM-eager = replayed Stage-3 maintenance", transform=ax.transAxes, color=INK2, fontsize=7.5)
fig.tight_layout()
fig.savefig(RES / "fig_outcomes.png", dpi=180)
plt.close(fig)

# contrast figure: tokens per task, code repos vs lakes
fig, axs = plt.subplots(1, 2, figsize=(8.4, 3.4), sharex=False)
for ax, (title, A) in zip(axs, [("code repositories (cheap re-derivation)", cr["arms"]),
                                ("data lakes (expensive re-derivation)", res["arms"])]):
    arms2 = [x for x in ["NO-MEMORY", "NEVER", "TTL", "REPLAY", "ESM", "ORACLE"] if x in A or (x == "TTL" and "TTL100" in A)]
    for i, a_ in enumerate(arms2):
        r = A.get(a_) or A.get("TTL100")
        ax.barh(i, r["task_tok"] / 1000, color="#2a78d6", height=0.62, edgecolor=SURF, linewidth=2, label="task agent" if i == 0 else None)
        ax.barh(i, r["maint_tok"] / 1000, left=r["task_tok"] / 1000, color="#1baf7a", height=0.62, edgecolor=SURF, linewidth=2,
                label="maintenance at the read" if i == 0 else None)
        ax.text((r["task_tok"] + r["maint_tok"]) / 1000 * 1.02 + 0.2, i, f"{r['tok'] / 1000:.1f}k  ({100 * r['success'][0]:.0f} %)",
                va="center", fontsize=7.5, color=INK)
    ax.set_yticks(range(len(arms2)), [x + (" (TTL100)" if (x == "TTL" and "TTL100" in A) else "") + (" *" if x == "ORACLE" else "") for x in arms2])
    ax.invert_yaxis()
    ax.set_title(title, fontsize=9, color=INK)
    ax.set_xlabel("tokens per task (thousands); label: total (success %)")
    ax.set_xlim(0, max(A[x]["tok"] for x in A if x in arms2 or x == "TTL100") / 1000 * 1.45)
    ax.grid(True, axis="x", color=GRID, linewidth=0.6)
    for s_ in ("top", "right"):
        ax.spines[s_].set_visible(False)
axs[0].legend(loc="lower right", frameon=False, fontsize=7.5)
fig.text(0.01, 0.01, "* ORACLE = memory equals the truth at t (idealised)", color=INK2, fontsize=7.5)
fig.tight_layout(rect=(0, 0.03, 1, 1))
fig.savefig(RES / "fig_cost_contrast.png", dpi=180)
plt.close(fig)

# wrong-action CIs, main vs trust
fig, ax = plt.subplots(figsize=(5.6, 3.4))
arms3 = [x for x in ["NO-MEMORY", "NEVER", "TTL", "REPLAY", "ESM", "ORACLE"] if x in res["arms"]]
for i, a_ in enumerate(arms3):
    y0, lo, hi = (v * 100 for v in res["arms"][a_]["wrong"])
    ax.plot([lo, hi], [i - 0.12] * 2, color="#2a78d6", lw=2, alpha=0.35)
    ax.plot(y0, i - 0.12, "o", ms=6, color="#2a78d6", label="main prompt" if i == 0 else None)
    tt = res.get("trust", {}).get(a_) if a_ != "NO-MEMORY" else None
    if tt:
        y1, l1, h1 = (v * 100 for v in tt["wrong"])
        ax.plot([l1, h1], [i + 0.12] * 2, color="#4a3aa7", lw=2, alpha=0.35)
        ax.plot(y1, i + 0.12, "s", ms=6, mfc="white", mec="#4a3aa7", mew=1.6, label="'rely on memory' prompt" if a_ == "NEVER" else None)
ax.set_yticks(range(len(arms3)), arms3)
ax.invert_yaxis()
ax.set_xlabel("wrong-action % of tasks (95 % CI)")
ax.grid(True, axis="x", color=GRID, linewidth=0.6)
ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, frameon=False, fontsize=7.5)
for s_ in ("top", "right"):
    ax.spines[s_].set_visible(False)
fig.tight_layout()
fig.savefig(RES / "fig_wrong_actions.png", dpi=180)
plt.close(fig)
print("written", RES)
