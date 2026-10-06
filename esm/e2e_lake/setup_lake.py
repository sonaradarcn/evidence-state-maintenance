"""Select the facts, build the tasks with ground truth at t (63 after the FHVHV exclusion; 78 planned), and validate the truth
machinery: the Stage-3 truth series value at t must equal facts_dl.oracle_direct (one independent DuckDB statement over
the snapshot's files) for every (fact, t); T-sql reference queries are executed; T-files truths are read off the manifest.
usage: python -m esm.e2e_lake.setup_lake   -> esm_data_e2e_lake/{selection,tasks}.json, esm/results/e2e_lake/validation.json"""
import json, sys, time
from esm.e2e_lake import common_lake as C
from esm.e2e_lake import tasks_lake as TK

t0 = time.time()
sel, tasks = [], []
val = {"truth_eq_oracle_direct": [0, 0], "mismatch": [], "direct_errors": []}
LAKES = sys.argv[1].split(",") if len(sys.argv) > 1 else ["tlc", "bb"]
for lake in LAKES:
    ctx = C.load_context(lake)
    env = ctx.env
    F = {f["iid"]: f for f in ctx.facts}
    ids = TK.select(ctx, lake)
    for iid in ids:
        f = F[iid]
        tt = TK.task_type(f)
        sel.append({"iid": iid, "lake": lake, "fact_type": f["type"], "task_type": tt, "subset": f["subset"],
                    "changes_in_future": len(set(f["truth"])) > 1})
        for t in C.TS[lake]:
            w = env.world(f, t)
            v = f["truth"][t]
            try:
                d = C.F.oracle_direct(w, {"lake": lake, "type": f["type"], "args": f["args"]})
                ok = str(d) == str(v)
            except Exception as e:
                d, ok = f"ERR {type(e).__name__}: {e}"[:200], False
                val["direct_errors"].append([iid, t, d])
            val["truth_eq_oracle_direct"][0] += ok
            val["truth_eq_oracle_direct"][1] += 1
            if not ok:
                val["mismatch"].append([iid, t, str(d)[:100], str(v)[:100]])
            tr = TK.task_truth(f, tt, w, t)
            tasks.append({"tid": f"{iid}@{t}", "iid": iid, "lake": lake, "t": t, "snapshot": w.commit, "task_type": tt,
                          "fact_type": f["type"], "subset": f["subset"], "question": f["question"], "K0": f["K"],
                          "task": TK.task_text(f, tt), "truth": tr, "fact_value": v,
                          "K0_valid": bool(env.answer_matches(f, f["K"], v))})
            print(tasks[-1]["tid"], tt, "possible" if tr["possible"] else "GONE", str(tr["value"])[:60],
                  "K0 valid" if tasks[-1]["K0_valid"] else "K0 STALE", "direct ok" if ok else f"DIRECT MISMATCH {str(d)[:60]}",
                  flush=True)
if (C.E2E / "tasks.json").exists() and len(LAKES) < 2:      # replace only this lake's entries
    old_t = [x for x in json.loads((C.E2E / "tasks.json").read_text(encoding="utf-8")) if x["lake"] not in LAKES]
    old_s = [x for x in json.loads((C.E2E / "selection.json").read_text(encoding="utf-8")) if x["lake"] not in LAKES]
    tasks, sel = [x for x in old_t if x["lake"] == "tlc"] + tasks + [x for x in old_t if x["lake"] != "tlc"], old_s + sel
    tasks.sort(key=lambda x: (x["lake"] != "tlc", x["tid"]))
    sel.sort(key=lambda x: (x["lake"] != "tlc", x["iid"]))
    vp = C.RES / "validation.json"
    if vp.exists():
        ov = json.loads(vp.read_text())
        val["truth_eq_oracle_direct"] = [a + b for a, b in zip(val["truth_eq_oracle_direct"], ov["truth_eq_oracle_direct"])] if ov.get("lakes") and set(ov["lakes"]) - set(LAKES) else val["truth_eq_oracle_direct"]
        val["mismatch"] += ov.get("mismatch", []) if set(ov.get("lakes", [])) - set(LAKES) else []
        val["lakes"] = sorted(set(ov.get("lakes", [])) | set(LAKES))
val.setdefault("lakes", LAKES)
C.jdump(C.E2E / "selection.json", sel)
C.jdump(C.E2E / "tasks.json", tasks)
C.RES.mkdir(parents=True, exist_ok=True)
C.jdump(C.RES / "validation.json", {**val, "n_tasks": len(tasks), "secs": round(time.time() - t0)})
print(json.dumps({k: v for k, v in val.items() if k != "mismatch"}, indent=1)[:2000])
print("mismatches:", val["mismatch"][:20])
