"""Check the re-cloned commit windows, select the facts, build the 120 tasks with ground truth,
and validate the truth machinery against the benchmark oracle (static: un-remapped oracle == recorded truth series;
behaviour: executing the expression in the materialised package == recorded truth).
usage: python -m esm.e2e.setup_e2e            -> esm_data_e2e/{selection,tasks}.json, esm/results/e2e/validation.json"""
import json, sys, time
from esm.e2e import common_e2e as C
from esm.e2e import tasks_e2e as TK
from esm.envs import heldout as H
from esm.envs import pyfacts as FX

t0 = time.time()
h150 = json.loads((C.HELD / "sub_H150.json").read_text())
repos = sorted({i.split(":")[0] for i in h150})

# 1. commit windows of the re-cloned repositories
gr = H.git_repos(repos)
win = {}
for r in repos:
    want = json.loads((C.ROOT / "heldout" / f"facts_{r}.json").read_text(encoding="utf-8"))["commits"]
    win[r] = gr[r].commits == want
    print(r, "window ok" if win[r] else "WINDOW MISMATCH", flush=True)
assert all(win.values()), win

# 2. context on H150 (kept facts) + s0 eligibility
ctx = C.load_context(h150)
env = ctx.env
F = {f["iid"]: f for f in ctx.facts}
print("kept H150 facts:", len(F), flush=True)
for f in F.values():
    if f["type"] == "T3":
        _, node, _, _ = TK.find_func(env.world(f, 0), f)
        f["_posonly"] = node is None or bool(node.args.posonlyargs)
sel = TK.select(F, h150)
C.jdump(C.E2E / "selection.json", sel)
print("selected", len(sel), flush=True)

# 3. tasks + validation
tasks, val = [], {"static_unremapped_eq_benchmark": [0, 0], "behaviour_exec_eq_benchmark": [0, 0], "mismatch": [],
                  "remapped_differs_from_benchmark": []}
for s in sel:
    f = F[s["iid"]]
    for t in C.TS:
        w = env.world(f, t)
        bench = f["truth"][300 + t]
        if f["type"] != "B":
            v_raw = FX.oracle(w, {"type": f["type"], "args": f["args"]})
            ok = v_raw == bench
            val["static_unremapped_eq_benchmark"][0] += ok
            val["static_unremapped_eq_benchmark"][1] += 1
            if not ok:
                val["mismatch"].append([f["iid"], t, str(v_raw)[:100], str(bench)[:100]])
        else:
            d = C.materialise(w, f["repo"])
            code = (f"import {f['args']['module']}\n"
                    f"import importlib, sys\n"
                    f"sys.path.insert(0, {str(C.ROOT / 'heldout')!r})\n"
                    f"from runner_h import canon_repr\n"
                    f"try:\n    _v = canon_repr({f['args']['expr']})[:2000]\n"
                    f"except AttributeError:\n    _v = 'raises AttributeError'\n"
                    f"except Exception as e:\n    _v = 'raises ' + type(e).__name__\n"
                    f"assert _v == {bench!r}, _v\n")
            e = C.run_code(f["repo"], d, code, timeout=20)
            ok = bool(e.get("ok")) or (bench == "NONE" and ("ModuleNotFoundError" in e.get("err", "") or "ImportError" in e.get("err", "")
                                                           or "AttributeError" in e.get("err", "")))
            val["behaviour_exec_eq_benchmark"][0] += ok
            val["behaviour_exec_eq_benchmark"][1] += 1
            if not ok:
                val["mismatch"].append([f["iid"], t, e.get("err", "")[:150], str(bench)[:100]])
        tr = TK.task_truth(f, s["task_type"], w, oracle_b=bench if f["type"] == "B" else None)
        sem = TK.semantic_value(f, w, bench if f["type"] == "B" else None)
        if str(sem) != str(bench):
            val["remapped_differs_from_benchmark"].append([f["iid"], t, str(sem)[:80], str(bench)[:80]])
        tasks.append({"tid": f"{s['iid']}@{t}", "iid": s["iid"], "repo": f["repo"], "t": t, "task_type": s["task_type"],
                      "fact_type": f["type"], "subset": f["subset"], "question": f["question"], "K0": f["K"],
                      "task": TK.task_text(f, s["task_type"]), "truth": tr, "semantic_value": sem, "bench_value": bench,
                      "K0_valid_bench": bool(env.answer_matches(f, f["K"], bench))})
        print(tasks[-1]["tid"], s["task_type"], "possible" if tr["possible"] else "GONE", str(tr.get("value"))[:60], flush=True)
C.jdump(C.E2E / "tasks.json", tasks)
C.RES.mkdir(parents=True, exist_ok=True)
C.jdump(C.RES / "validation.json", {**val, "windows_ok": win, "n_tasks": len(tasks), "secs": round(time.time() - t0)})
print(json.dumps({k: v for k, v in val.items() if k != "mismatch"}, indent=1)[:3000])
print("mismatches:", val["mismatch"][:20])
