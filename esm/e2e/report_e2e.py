"""Tables, bootstrap CIs, paired differences and figures -> esm/results/e2e/
usage: python -m esm.e2e.report_e2e"""
import json
import numpy as np
import pandas as pd
from esm.e2e import common_e2e as C
from esm.envs import pyfacts as FX

ARMS = ["NO-MEMORY", "NEVER", "TTL100", "REPLAY", "ESM", "ESM-eager", "ORACLE"]
REAL = ["NO-MEMORY", "NEVER", "TTL100", "REPLAY", "ESM"]
B = 2000
rng = np.random.default_rng(C.SEED)

tasks = json.loads((C.E2E / "tasks.json").read_text(encoding="utf-8"))
TD = {t["tid"]: t for t in tasks}
mem = pd.read_parquet(C.E2E / "memory.parquet")
runs = {}
for l in (C.E2E / "runs.jsonl").read_text(encoding="utf-8").splitlines():
    if l.strip():
        d = json.loads(l)
        runs[d["key"]] = d
M = {(r.policy, r.iid, int(r.t)): r for r in mem.itertuples()}


def mem_correct(task, ans):
    """Is the remembered answer right at t under the semantic (src/-aware) truth?"""
    v = task["semantic_value"]
    v = "NONE" if v in (None, "MODULE_GONE") else str(v)
    if ans is None or str(ans).strip() == "":
        return False
    if task["fact_type"] == "B":
        return FX.canon_b(ans) == FX.canon_b(v)
    sub = "methods" if "public method names" in task["question"] else None
    try:
        return FX.canon(task["fact_type"], sub, str(ans)) == FX.canon_oracle({"type": task["fact_type"]}, v)
    except Exception:
        return False


rows = []
for t in tasks:
    for arm in ARMS:
        if arm == "NO-MEMORY":
            m, mr = None, None
        elif arm == "ORACLE":
            v = t["semantic_value"]
            m, mr = ("NONE" if v in (None, "MODULE_GONE") else str(v)), None
        else:
            mr = M[(arm, t["iid"], t["t"])]
            m = "" if mr.served is None else str(mr.served)
        r = runs.get(json.dumps([t["tid"], m]))
        if r is None:
            continue
        task_tok = r["prompt_tok"] + r["compl_tok"]
        maint = 0 if mr is None else int(mr.maint_tok)
        mlat = 0.0 if mr is None else float((mr.judge_lat or 0) + (mr.der_lat or 0)) if arm != "ESM-eager" else np.nan
        rows.append({"arm": arm, "tid": t["tid"], "iid": t["iid"], "repo": t["repo"], "t": t["t"], "task_type": t["task_type"],
                     "possible": t["truth"]["possible"], "outcome": r["check"]["outcome"], "detail": r["check"]["detail"],
                     "submitted": r["sub"]["kind"], "memory": m,
                     "mem_correct": (None if arm == "NO-MEMORY" else (True if arm == "ORACLE" else mem_correct(t, m))),
                     "mem_valid_bench": (None if mr is None else bool(mr.served_valid_bench)),
                     "task_tok": task_tok, "maint_tok": maint, "tok": task_tok + maint, "n_llm": r["n_llm"], "n_tools": r["n_tools"],
                     "task_lat": r["llm_lat"] + r["tool_s"], "maint_lat": mlat, "lat": r["llm_lat"] + r["tool_s"] + mlat,
                     "maint_action": None if mr is None else mr.action, "judge_new": None if mr is None else mr.judge_new,
                     "der_new": None if mr is None else mr.der_new, "der_reused": None if mr is None else mr.der_reused,
                     "judge_reused": None if mr is None else mr.judge_reused,
                     "exec_ok": r["check"].get("exec_ok"), "shared_run_first_arm": r["first_arm"]})
df = pd.DataFrame(rows)
df["success"] = df.outcome == "success"
df["wrong"] = df.outcome == "wrong"
df["fail"] = df.outcome == "fail"
df.to_parquet(C.RES / "task_outcomes.parquet", index=False)
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


def table(g, by=None):
    out = []
    keys = [None] if by is None else sorted(g[by].unique())
    for key in keys:
        for arm in ARMS:
            s = g[(g.arm == arm)] if key is None else g[(g.arm == arm) & (g[by] == key)]
            if s.empty:
                continue
            out.append({**({by: key} if by else {}), "arm": arm, "n": len(s),
                        "success %": fmt(ci(s.success)), "wrong action %": fmt(ci(s.wrong)), "failure %": fmt(ci(s.fail)),
                        "memory right %": ("–" if arm == "NO-MEMORY" else f"{100 * s.mem_correct.astype(float).mean():.1f}"),
                        "tokens/task (task + maint.)": f"{s.tok.mean():,.0f} ({s.task_tok.mean():,.0f} + {s.maint_tok.mean():,.0f})",
                        "latency s/task (task + maint.)": ("–" if s.lat.isna().all() else
                                                           f"{s.lat.mean():.1f} ({s.task_lat.mean():.1f} + {s.maint_lat.mean():.1f})")})
    return pd.DataFrame(out)


def paired(g, base, metric):
    out = []
    a = g.pivot_table(index="tid", columns="arm", values=metric, aggfunc="first")
    fid = a.index.map(lambda x: x.split("@")[0])
    for arm in ARMS:
        if arm == base or arm not in a or base not in a:
            continue
        d = (a[arm].astype(float) - a[base].astype(float)).dropna()
        cl = fid[a[arm].notna() & a[base].notna()]
        c_t, c_f = ci(d.values), ci(d.values, cluster=np.asarray(cl))
        out.append((arm, len(d), c_t, c_f))
    return out


md = ["# B3 tables (generated by `python -m esm.e2e.report_e2e`; zero LLM)\n"]
md.append(f"Tasks per arm with a completed run: {complete}\n")
md.append("## T1 main table (all tasks; CIs: bootstrap over tasks, B = 2000)\n")
md.append(table(df).to_markdown(index=False))
md.append("\n## T1c same, CIs clustered by fact (40 clusters)\n")
rows_c = []
for arm in ARMS:
    s = df[df.arm == arm]
    if not s.empty:
        rows_c.append({"arm": arm, "success %": fmt(ci(s.success, s.iid)), "wrong %": fmt(ci(s.wrong, s.iid)),
                       "failure %": fmt(ci(s.fail, s.iid))})
md.append(pd.DataFrame(rows_c).to_markdown(index=False))
for base in ("NEVER", "NO-MEMORY"):
    md.append(f"\n## T2 paired differences: arm − {base} (pp for rates, tokens per task; CI over tasks | clustered by fact)\n")
    pr = []
    for metric, pct in (("success", True), ("wrong", True), ("fail", True), ("tok", False), ("lat", False)):
        for arm, n, ct, cf in paired(df, base, metric):
            pr.append({"metric": metric, "arm": arm, "n": n, "Δ [task CI]": fmt(ct, pct, 1 if pct else 0),
                       "fact-cluster CI": f"[{cf[1] * (100 if pct else 1):.{1 if pct else 0}f}, {cf[2] * (100 if pct else 1):.{1 if pct else 0}f}]"})
    md.append(pd.DataFrame(pr).to_markdown(index=False))
md.append("\n## T2b paired: ESM − TTL100 and ESM − REPLAY (main prompt)\n")
pr = []
for base in ("TTL100", "REPLAY"):
    for metric, pct in (("success", True), ("wrong", True), ("tok", False), ("lat", False)):
        for arm, n, ct, cf in paired(df, base, metric):
            if arm == "ESM":
                pr.append({"base": base, "metric": metric, "n": n, "Δ [task CI]": fmt(ct, pct, 1 if pct else 0),
                           "fact-cluster CI": f"[{cf[1] * (100 if pct else 1):.{1 if pct else 0}f}, {cf[2] * (100 if pct else 1):.{1 if pct else 0}f}]"})
md.append(pd.DataFrame(pr).to_markdown(index=False))
md.append("\n## T3 by task type\n")
md.append(table(df, "task_type").to_markdown(index=False))
md.append("\n## T4 by commit t\n")
md.append(table(df, "t").to_markdown(index=False))
md.append("\n## T5 tasks whose referent is gone at t (correct action = abstain / NONE)\n")
md.append(table(df[~df.possible]).to_markdown(index=False) if (~df.possible).any() else "none")
md.append("\n## T6 outcome by memory correctness (memory arms, real ones pooled)\n")
s = df[df.arm.isin(["NEVER", "TTL100", "REPLAY", "ESM"])]
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
md.append("\n## T7 maintenance work at the task reads (lazy policies; recorded = request already made in Stage 2)\n")
mm = mem[mem.policy != "ESM-eager"].groupby("policy").agg(
    reads=("t", "size"), memory_right_bench=("served_valid_bench", "mean"), tokens_per_read=("maint_tok", "mean"),
    judge_calls_new=("judge_new", "sum"), judge_calls_recorded=("judge_reused", "sum"), rederiv_new=("der_new", "sum"),
    rederiv_recorded=("der_reused", "sum"))
mm.loc["ESM-eager (replayed)"] = [int((mem.policy == "ESM-eager").sum()), mem[mem.policy == "ESM-eager"].served_valid_bench.mean(),
                                  mem[mem.policy == "ESM-eager"].maint_tok.mean(), 0, mem[mem.policy == "ESM-eager"].eval_calls.sum(),
                                  0, mem[mem.policy == "ESM-eager"].n_der.sum()]
md.append(mm.round(3).to_markdown())
fresh = [r for r in runs.values() if not r["cached_all"] and r["n_llm"] > 0]
spt = sum(r["llm_lat"] for r in fresh) / max(1, sum(r["prompt_tok"] + r["compl_tok"] for r in fresh))
md.append(f"\n## T7b maintenance latency re-estimated on this server\n\nRecorded maintenance latencies (T1) are Stage-2 "
          f"wall-clock with 2-4 requests in flight per GPU. Re-estimate: maintenance tokens x {spt * 1000:.2f} s per 1k tokens "
          f"(this server's rate on {len(fresh)} fresh task runs, 1 request in flight, tool-loop calls of the same model).\n")
le = []
for arm in ["NO-MEMORY", "NEVER", "TTL100", "REPLAY", "ESM", "ESM-eager"]:
    s = df[df.arm == arm]
    le.append({"arm": arm, "task latency s": round(s.task_lat.mean(), 1), "maint. latency s (est.)": round(s.maint_tok.mean() * spt, 1),
               "total s (est.)": round(s.task_lat.mean() + s.maint_tok.mean() * spt, 1)})
md.append(pd.DataFrame(le).to_markdown(index=False))
md.append("\n## T8 execution checks (T-locate import executed where the package is importable)\n")
e = df[(df.task_type == "T-locate") & df.exec_ok.notna()]
if len(e):
    md.append(pd.crosstab(e.outcome, e.exec_ok).to_markdown())
# ---- post hoc sensitivity: memory presented as verified facts to rely on (runs_trust.jsonl)
tr = None
tp = C.E2E / "runs_trust.jsonl"
if tp.exists():
    rt = {}
    for l in tp.read_text(encoding="utf-8").splitlines():
        if l.strip():
            d = json.loads(l)
            rt[d["key"]] = d
    trows = []
    for t in tasks:
        for arm in ["NEVER", "TTL100", "REPLAY", "ESM", "ORACLE"]:
            if arm == "ORACLE":
                v = t["semantic_value"]
                m, mr = ("NONE" if v in (None, "MODULE_GONE") else str(v)), None
            else:
                mr = M[(arm, t["iid"], t["t"])]
                m = "" if mr.served is None else str(mr.served)
            r = rt.get(json.dumps([t["tid"], m]))
            if r is None:
                continue
            maint = 0 if mr is None else int(mr.maint_tok)
            mlat = 0.0 if mr is None else float((mr.judge_lat or 0) + (mr.der_lat or 0))
            trows.append({"arm": arm, "tid": t["tid"], "iid": t["iid"], "task_type": t["task_type"], "t": t["t"],
                          "possible": t["truth"]["possible"], "outcome": r["check"]["outcome"], "detail": r["check"]["detail"],
                          "mem_correct": True if arm == "ORACLE" else mem_correct(t, m),
                          "task_tok": r["prompt_tok"] + r["compl_tok"], "maint_tok": maint,
                          "tok": r["prompt_tok"] + r["compl_tok"] + maint, "task_lat": r["llm_lat"] + r["tool_s"],
                          "maint_lat": mlat, "lat": r["llm_lat"] + r["tool_s"] + mlat, "n_tools": r["n_tools"]})
    tr = pd.DataFrame(trows)
    tr["success"], tr["wrong"], tr["fail"] = tr.outcome == "success", tr.outcome == "wrong", tr.outcome == "fail"
    tr.to_parquet(C.RES / "task_outcomes_trust.parquet", index=False)
    nm2 = df[df.arm == "NO-MEMORY"]
    both = pd.concat([nm2[[c for c in tr.columns if c in nm2.columns]], tr], ignore_index=True)
    md.append("\n## T9 POST HOC sensitivity: memory presented as verified facts to rely on (same tasks; NO-MEMORY row = main run)\n")
    md.append(table(both).to_markdown(index=False))
    for base in ("NEVER", "NO-MEMORY"):
        md.append(f"\n### T9 paired: arm − {base} (trust variant)\n")
        pr = []
        for metric, pct in (("success", True), ("wrong", True), ("tok", False)):
            for arm, n, ct, cf in paired(both, base, metric):
                pr.append({"metric": metric, "arm": arm, "n": n, "Δ [task CI]": fmt(ct, pct, 1 if pct else 0),
                           "fact-cluster CI": f"[{cf[1] * (100 if pct else 1):.{1 if pct else 0}f}, {cf[2] * (100 if pct else 1):.{1 if pct else 0}f}]"})
        md.append(pd.DataFrame(pr).to_markdown(index=False))
    md.append("\n### T9 by task type (trust variant)\n")
    md.append(table(both, "task_type").to_markdown(index=False))
    s3 = tr[tr.arm.isin(["NEVER", "TTL100", "REPLAY", "ESM"])]
    x = s3.groupby("mem_correct")[["success", "wrong", "fail"]].mean().mul(100).round(1)
    x["n"] = s3.groupby("mem_correct").size()
    md.append("\n### T9 outcome by memory correctness (trust variant)\n")
    md.append(x.to_markdown())
(C.RES / "tables.md").write_text("\n".join(md) + "\n", encoding="utf-8")

# results.json (headline numbers)
res = {"complete_tasks": complete, "arms": {}}
for arm in ARMS:
    s = df[df.arm == arm]
    if s.empty:
        continue
    res["arms"][arm] = {"n": len(s), "success": ci(s.success), "wrong": ci(s.wrong), "fail": ci(s.fail),
                        "tok": s.tok.mean(), "task_tok": s.task_tok.mean(), "maint_tok": s.maint_tok.mean(),
                        "lat": s.lat.mean(), "task_lat": s.task_lat.mean(), "maint_lat": s.maint_lat.mean(),
                        "mem_correct": None if arm == "NO-MEMORY" else float(s.mem_correct.astype(float).mean())}
res["paired_vs_NEVER"] = {m: {a: [n, ct, cf] for a, n, ct, cf in paired(df, "NEVER", m)} for m in ("success", "wrong", "tok")}
res["paired_vs_NOMEM"] = {m: {a: [n, ct, cf] for a, n, ct, cf in paired(df, "NO-MEMORY", m)} for m in ("success", "wrong", "tok")}
res["sec_per_token_this_server"] = spt
res["maint_latency_est"] = {x["arm"]: x for x in le}
if tr is not None:
    res["trust"] = {arm: {"n": int((tr.arm == arm).sum()), "success": ci(tr[tr.arm == arm].success), "wrong": ci(tr[tr.arm == arm].wrong),
                          "fail": ci(tr[tr.arm == arm].fail), "tok": float(tr[tr.arm == arm].tok.mean())}
                    for arm in tr.arm.unique()}
C.jdump(C.RES / "results.json", res)
df.drop(columns=[]).to_json(C.RES / "task_outcomes.json", orient="records", indent=1, force_ascii=False)

# ---------------------------------------------------------------- figures
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
COL = {"success": "#2a78d6", "wrong": "#eb6834", "fail": "#b9b8b2"}
plt.rcParams.update({"font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2,
                     "figure.facecolor": SURF, "axes.facecolor": SURF})
arms = [a for a in ARMS if a in res["arms"]]
fig, ax = plt.subplots(figsize=(7.2, 3.4))
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
ax.set_xlabel("% of tasks (120 per arm)")
ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.16), ncol=3, frameon=False)
for s_ in ("top", "right"):
    ax.spines[s_].set_visible(False)
ax.text(0, -0.2, "* ORACLE = idealised memory; ESM-eager = replayed maintenance", transform=ax.transAxes, color=INK2, fontsize=7.5)
fig.tight_layout()
fig.savefig(C.RES / "fig_outcomes.png", dpi=180)
plt.close(fig)

fig, axs = plt.subplots(1, 2, figsize=(8.0, 3.4), sharey=True, gridspec_kw={"width_ratios": [1.15, 1]})
arms2 = [x for x in ["NO-MEMORY", "NEVER", "TTL100", "REPLAY", "ESM", "ORACLE"] if x in res["arms"]]
ax = axs[0]
for i, a_ in enumerate(arms2):
    r = res["arms"][a_]
    ax.barh(i, r["task_tok"] / 1000, color="#2a78d6", height=0.62, edgecolor=SURF, linewidth=2, label="task agent" if i == 0 else None)
    ax.barh(i, r["maint_tok"] / 1000, left=r["task_tok"] / 1000, color="#1baf7a", height=0.62, edgecolor=SURF, linewidth=2,
            label="maintenance at the read" if i == 0 else None)
    ax.text((r["task_tok"] + r["maint_tok"]) / 1000 + 0.4, i, f"{r['tok'] / 1000:.1f}k", va="center", fontsize=8, color=INK)
ax.set_yticks(range(len(arms2)), [x + (" *" if x == "ORACLE" else "") for x in arms2])
ax.invert_yaxis()
ax.set_xlabel("tokens per task (thousands)")
ax.set_xlim(0, max(res["arms"][x]["tok"] for x in arms2) / 1000 * 1.18)
ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, frameon=False, fontsize=7.5)
ax = axs[1]
for i, a_ in enumerate(arms2):
    y0, lo, hi = (v * 100 for v in res["arms"][a_]["wrong"])
    ax.plot([lo, hi], [i - 0.12] * 2, color="#2a78d6", lw=2, alpha=0.35)
    ax.plot(y0, i - 0.12, "o", ms=6, color="#2a78d6", label="main prompt" if i == 0 else None)
    tt = res.get("trust", {}).get(a_) if a_ != "NO-MEMORY" else None
    if tt:
        y1, l1, h1 = (v * 100 for v in tt["wrong"])
        ax.plot([l1, h1], [i + 0.12] * 2, color="#4a3aa7", lw=2, alpha=0.35)
        ax.plot(y1, i + 0.12, "s", ms=6, mfc="white", mec="#4a3aa7", mew=1.6, label="'rely on memory' prompt (post hoc)" if a_ == "NEVER" else None)
ax.set_xlabel("wrong-action % of tasks (95 % CI)")
ax.set_xlim(0, 22)
ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, frameon=False, fontsize=7.5)
for ax in axs:
    ax.grid(True, axis="x", color=GRID, linewidth=0.6)
    for s_ in ("top", "right"):
        ax.spines[s_].set_visible(False)
fig.text(0.01, 0.01, "* ORACLE = memory equals the truth at t (idealised)", color=INK2, fontsize=7.5)
fig.tight_layout(rect=(0, 0.03, 1, 1))
fig.savefig(C.RES / "fig_cost_vs_outcome.png", dpi=180)
plt.close(fig)
print((C.RES / "tables.md").read_text(encoding="utf-8")[:6000])
