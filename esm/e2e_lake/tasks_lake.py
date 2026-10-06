"""Fact selection, task texts, ground truth at snapshot t and the success checks.

Task types (fact type -> task):
  T-sql      (D2)       one DuckDB SELECT over the most recent file: count of distinct non-null values of the column that
                        holds concept X, aliased with that column's exact name (executed with the lake sql tool at t)
  T-report   (D3/D4/D6) report the statistic (the fact's question) - canonicalised value vs oracle at t
  T-files    (BB D4 latest-date facts) which daily file to load for the most recent day (of a year) - vs the manifest at t
  T-question (D1/D8)    the schema / coverage question - canonicalised value vs oracle at t
Outcome: success | wrong (a submitted action that fails the check) | fail (abstained although possible, or nothing submitted).
"""
import re
from esm.e2e_lake import common_lake as C

L, F = C.L, C.F
NONE = "NONE"
TASK_OF = {"D1": "T-question", "D8": "T-question", "D2": "T-sql", "D3": "T-report", "D6": "T-report"}
KEEP_TYPES = ("D1", "D2", "D3", "D4", "D6", "D8")


def task_type(fact):
    t = fact["type"]
    if t == "D4":
        return "T-files" if (fact["lake"] == "bb" and fact["args"].get("agg") == "latest_date_in_year") else "T-report"
    return TASK_OF[t]


def select(ctx, lake):
    """The Stage-3 blind stratified subset S restricted to D1/D2/D3/D4/D6/D8 (all kept facts)."""
    import json
    S = json.loads((C.E2E / f"dl_{lake}" / "sub_S.json").read_text())
    kept = {f["iid"]: f for f in ctx.facts}
    # TLC facts on the High Volume FHV dataset are excluded (its source files were not re-fetched; PLAN.md)
    return [i for i in S if i in kept and i.split(":")[1] in KEEP_TYPES and kept[i]["args"].get("ds") != "fhvhv"]


# ---------------------------------------------------------------- helpers
def latest_file(w, fact, year=None):
    """Logical path of the most recent file of the fact's dataset (TLC) / the most recent daily file (BB) at w."""
    if fact["lake"] == "tlc":
        ps = F.latest_paths(F.tlc_index(w), fact["args"]["ds"])
        return ps[0] if len(ps) == 1 else (ps or [None])[0]
    days = F.bb_index(w)["days"]
    ks = sorted(k for k in days if year in (None, "all") or k.startswith(year))
    return days[ks[-1]] if ks else None


def _d2_parts(q):
    m = re.search(r"In the most recent (.+?), what is", q)
    n = re.search(r"column (?:that holds|holding) (.+?)\?", q)
    return m.group(1), n.group(1)


def task_text(fact, ttype):
    q = fact["question"]
    if ttype == "T-question":
        return (q + " Submit only the answer. If what the question refers to no longer exists in this snapshot, call abstain.")
    if ttype == "T-report":
        return ("You are preparing a data report and need this statistic, computed on the lake as it is now: " + q +
                " Submit only the value. If what it refers to no longer exists in this snapshot, call abstain.")
    if ttype == "T-sql":
        what, concept = _d2_parts(q)
        return (f"Write one DuckDB SQL SELECT statement over the most recent {what} in the lake (reference the file by its "
                f"quoted logical path) that returns exactly one row with exactly one column: the number of distinct non-null "
                f"values of the column that holds {concept}. Alias the output column with the exact, case-sensitive name "
                f"of that source column (downstream code selects the result by that name). Submit the query. If no column "
                f"holds it in the most recent file, call abstain.")
    if ttype == "T-files":
        y = fact["args"]["year"]
        scope = "in the lake" if y == "all" else f"of calendar year {y} present in the lake"
        return (f"You need to load the daily Drive Stats CSV file that holds the most recent day of data {scope} (for a "
                f"daily report on that day). Which file is it? Submit its logical path. If there is no such file, call abstain.")
    raise ValueError(ttype)


def task_truth(fact, ttype, w, t):
    """{possible, value, ...} at snapshot t (world w)."""
    v = fact["truth"][t]
    if ttype in ("T-question", "T-report"):
        return {"possible": v != NONE, "value": v}
    if ttype == "T-sql":
        if v == NONE:
            return {"possible": False, "value": NONE}
        lf = latest_file(w, fact)
        ref_q = f'SELECT count(DISTINCT "{v}") AS "{v}" FROM \'{lf}\''
        ref = L.t_sql(w, ref_q)
        assert not ref.startswith("error"), (fact["iid"], t, ref)
        return {"possible": True, "value": v, "latest": lf, "ref_query": ref_q, "ref_out": ref}
    if ttype == "T-files":
        lf = latest_file(w, fact, fact["args"]["year"])
        if lf is None:
            return {"possible": False, "value": NONE}
        return {"possible": True, "value": lf, "fact_value": v}
    raise ValueError(ttype)


# ---------------------------------------------------------------- checks
def check(env, fact, ttype, w, truth, sub):
    if sub is None or sub.get("kind") == "none":
        return {"outcome": "fail", "detail": "no submission"}
    if sub["kind"] == "abstain":
        if not truth["possible"]:
            return {"outcome": "success", "detail": "correct abstention"}
        return {"outcome": "fail", "detail": "abstained although possible"}
    try:
        return {"T-question": _chk_value, "T-report": _chk_value, "T-sql": _chk_sql, "T-files": _chk_files}[ttype](
            env, fact, w, truth, sub)
    except Exception as e:
        return {"outcome": "wrong", "detail": f"check error {type(e).__name__}: {str(e)[:150]}"}


def _strip(s):
    s = (s or "").strip()
    m = re.match(r"^```(?:sql|python|text)?\s*\n?(.*?)\n?```$", s, re.S)
    return m.group(1).strip() if m else s


def _chk_value(env, fact, w, truth, sub):
    ans = _strip(str(sub.get("answer", "")))
    if not truth["possible"]:
        ok = ans.upper() in ("NONE", "N/A") or F.canon(fact, ans) == NONE
        return {"outcome": "success" if ok else "wrong", "detail": f"gone; answered {ans[:80]}"}
    ok = env.answer_matches(fact, ans, truth["value"])
    return {"outcome": "success" if ok else "wrong", "detail": f"answer={ans[:100]} truth={str(truth['value'])[:100]}"}


def _chk_sql(env, fact, w, truth, sub):
    q = _strip(str(sub.get("query", ""))).rstrip(";").strip()
    if not truth["possible"]:
        return {"outcome": "wrong", "detail": f"column gone; submitted {q[:100]}"}
    try:
        _, files = L.sql_resolve(w, q)
    except Exception as e:
        files = []
    out = L.t_sql(w, q)
    reads_latest = truth["latest"] in set(files)
    same = out.strip() == truth["ref_out"].strip()
    ok = reads_latest and same
    return {"outcome": "success" if ok else "wrong", "executed": True, "reads_latest": reads_latest, "same_result": same,
            "detail": f"out={out[:120]!r} ref={truth['ref_out'][:80]!r} files={files[:3]}"}


def _chk_files(env, fact, w, truth, sub):
    s = _strip(str(sub.get("files", "")))
    paths = [L._norm_path(x) for x in re.split(r"[,\n]", s) if x.strip()]
    if not truth["possible"]:
        return {"outcome": "wrong", "detail": f"no such file; submitted {s[:100]}"}
    ok = paths == [truth["value"]]
    return {"outcome": "success" if ok else "wrong", "detail": f"submitted={paths[:3]} truth={truth['value']}",
            "in_manifest": all(p in w.tree for p in paths)}
