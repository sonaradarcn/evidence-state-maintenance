"""The persistent data agent does the tasks (real calls, qwen3.6:27b on the e2e server) and every
submission is checked against the lake snapshot at t.

Arms: NO-MEMORY, NEVER, TTL (TLC 25 / BB 20), TTL-mid (TLC 50 / BB 40), REPLAY, ESM, ESM-eager (replayed maintenance),
ORACLE (memory = truth at t; idealised).  The memory note = the fact's question + the arm's served answer.  Identical
notes give identical prompts, so the run is shared (cached) between arms: fair pairing, no duplicated spend.
usage: python -m esm.e2e_lake.agent_lake [--arms ...] [--variant main|trust] [--lake tlc|bb] [--limit N]
       -> esm_data_e2e_lake/runs[_trust].jsonl (one line per unique run)"""
import argparse, json, time, traceback
import pandas as pd
from esm.e2e_lake import common_lake as C
from esm.e2e_lake import tasks_lake as TK
from esm import llm

L, DLE = C.L, C.DLE
ARMS = ["NO-MEMORY", "NEVER", "TTL", "TTL-mid", "REPLAY", "ESM", "ESM-eager", "ORACLE"]
MAX_TOOLS = 12
SYS = ("You are a data-analysis agent working on a snapshot of {desc}. Files are referenced by their logical paths. You "
       "have read-only tools to inspect the lake. The sql tool has a per-call scan budget ({budget}), so a task over many "
       "files may need several cheaper observations (e.g. row counts from metadata) that you combine yourself. Use at most "
       "{n} tool calls, then call submit with your result, or call abstain if the task is impossible in this snapshot (for "
       "example because what it refers to no longer exists). Work efficiently.")
MEM = ("Memory (notes you recorded earlier while working with this data lake; the data may have changed since):\n"
       "- Q: {q}\n  A: {a}\n\n")
# pre-registered secondary variant (PLAN.md): memory presented as verified knowledge the agent should rely on
MEM_TRUST = ("Memory (verified facts about this data lake from your earlier work; rely on them instead of re-checking):\n"
             "- Q: {q}\n  A: {a}\n\n")
VARIANT = {"mem": MEM}
SUBMIT = {
    "T-question": ({"answer": "string"}, ["answer"], "Submit the final answer (only the value)."),
    "T-report": ({"answer": "string"}, ["answer"], "Submit the statistic (only the value)."),
    "T-sql": ({"query": "string"}, ["query"], "Submit the DuckDB SQL query."),
    "T-files": ({"files": "string"}, ["files"], "Submit the logical path of the file to load."),
}
ABSTAIN = ("abstain", "Declare the task impossible in this snapshot (e.g. what it refers to no longer exists).",
           {"reason": "string"}, ["reason"])


def tools_for(ttype):
    props, req, desc = SUBMIT[ttype]
    return L.openai_tools([("submit", desc, props, req), ABSTAIN])


def run_task(env, fact, task, mem_answer):
    """One agent run.  mem_answer None => no memory note."""
    w = env.world(fact, task["t"])
    lake = fact["lake"]
    user = ""
    if mem_answer is not None:
        user = VARIANT["mem"].format(q=fact["question"], a=(str(mem_answer).strip() or "(no answer recorded)"))
    user += "Task: " + task["task"]
    msgs = [{"role": "system", "content": SYS.format(desc=DLE.DESC[lake], budget=DLE.BUDGET_TXT[lake], n=MAX_TOOLS)},
            {"role": "user", "content": user}]
    tools = tools_for(task["task_type"])
    trace, sub, ptok, ctok, nllm, lat, tool_s, nudged, cached_all = [], None, 0, 0, 0, 0.0, 0.0, False, True
    fetch0 = getattr(C.FETCH_WAIT, "s", 0.0)
    t_wall = time.time()
    for step in range(MAX_TOOLS + 4):
        try:
            r = llm.chat(llm.Q27, msgs, tools=tools, max_tokens=2000, tag="e2e_lake_task")
        except llm.ServerParseError:
            trace.append({"error": "server parse error"})
            break
        nllm += 1
        ptok += r["usage"]["prompt"]; ctok += r["usage"]["completion"]
        lat += float(r.get("latency") or 0.0)
        cached_all &= bool(r.get("cached"))
        tcs = r["tool_calls"]
        if not tcs:
            if not nudged:
                nudged = True
                msgs.append({"role": "assistant", "content": r["content"] or ""})
                msgs.append({"role": "user", "content": "Please finish by calling the submit tool (or abstain)."})
                continue
            break
        msgs.append({"role": "assistant", "content": r["content"] or None, "tool_calls": [
            {"id": x["id"], "type": "function", "function": {"name": x["name"], "arguments": x["arguments"]}} for x in tcs]})
        for x in tcs:
            try:
                args = json.loads(x["arguments"] or "{}")
                args = args if isinstance(args, dict) else {}
            except Exception:
                args = {}
            if x["name"] in ("submit", "abstain") and sub is None:
                sub = {"kind": x["name"], **{k: str(v) for k, v in args.items()}}
                out = "ok"
            elif x["name"] in ("submit", "abstain"):
                out = "ok"
            elif len(trace) >= MAX_TOOLS:
                out = "error: tool budget exhausted; call submit or abstain now"
            else:
                t0 = time.time()
                f0 = getattr(C.FETCH_WAIT, "s", 0.0)
                out = L.run_tool(w, x["name"], args)
                tool_s += (time.time() - t0) - (getattr(C.FETCH_WAIT, "s", 0.0) - f0)
                trace.append({"tool": x["name"], "args": args, "out": out[:600]})
            msgs.append({"role": "tool", "tool_call_id": x["id"], "content": out})
        if sub is not None:
            break
    return {"sub": sub or {"kind": "none"}, "prompt_tok": ptok, "compl_tok": ctok, "n_llm": nllm, "n_tools": len(trace),
            "llm_lat": round(lat, 2), "tool_s": round(tool_s, 2), "wall": round(time.time() - t_wall, 2),
            "fetch_wait_s": round(getattr(C.FETCH_WAIT, "s", 0.0) - fetch0, 1), "cached_all": cached_all, "trace": trace}


def oracle_answer(task):
    """Memory for the ORACLE arm: the fact's value at t (NONE if gone)."""
    return str(task["fact_value"])


def memory_for(task, arm, M):
    if arm == "NO-MEMORY":
        return None
    if arm == "ORACLE":
        return oracle_answer(task)
    m = M[(arm, task["iid"], task["t"])]
    return "" if m is None else str(m)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--lake", default="tlc,bb")
    ap.add_argument("--variant", default="main", help="main | trust (pre-registered secondary; -> runs_trust.jsonl)")
    a = ap.parse_args()
    if a.variant == "trust":
        VARIANT["mem"] = MEM_TRUST
    tasks = [t for t in json.loads((C.E2E / "tasks.json").read_text(encoding="utf-8")) if t["lake"] in a.lake.split(",")]
    mem = pd.read_parquet(C.E2E / "memory.parquet")
    M = {(r.policy, r.iid, int(r.t)): r.served for r in mem.itertuples()}
    out = C.E2E / ("runs.jsonl" if a.variant == "main" else f"runs_{a.variant}.jsonl")
    done = {}
    if out.exists():
        for l in out.read_text(encoding="utf-8").splitlines():
            if l.strip():
                d = json.loads(l)
                done[d["key"]] = d
    arms = a.arms.split(",")
    todo = []
    for task in tasks:
        for arm in arms:
            m = memory_for(task, arm, M)
            todo.append((task, arm, m, json.dumps([task["tid"], m])))
    uniq, seen = [], set(done)
    for x in todo:
        if x[3] not in seen:
            seen.add(x[3]); uniq.append(x)
    # NO-MEMORY runs (the most expensive) interleaved with the memory runs, lake by lake
    if a.limit:
        uniq = uniq[: a.limit]
    print(f"tasks={len(tasks)} arm-runs={len(todo)} unique runs={len(set(x[3] for x in todo))} done={len(done)} todo={len(uniq)}",
          flush=True)
    ctxs = {lake: C.load_context(lake) for lake in sorted({t["lake"] for t in tasks})}
    t0 = time.time()
    for k, (task, arm, m, key) in enumerate(uniq):
        ctx = ctxs[task["lake"]]
        f = next(x for x in ctx.facts if x["iid"] == task["iid"])
        try:
            r = run_task(ctx.env, f, task, m)
            w = ctx.env.world(f, task["t"])
            t1 = time.time()
            chk = TK.check(ctx.env, f, task["task_type"], w, task["truth"], r["sub"])
            r["check_s"] = round(time.time() - t1, 2)
        except Exception as e:
            print("ERR", task["tid"], arm, repr(e)[:200], traceback.format_exc()[-800:], flush=True)
            continue
        rec = {"key": key, "tid": task["tid"], "first_arm": arm, "memory": m, **r, "check": chk}
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[{k + 1}/{len(uniq)}] {task['tid']} {task['task_type']} {arm}: {chk['outcome']} ({chk['detail'][:70]}) "
              f"tok={r['prompt_tok'] + r['compl_tok']} llm={r['n_llm']} tools={r['n_tools']} {r['wall']:.0f}s "
              f"elapsed={time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
