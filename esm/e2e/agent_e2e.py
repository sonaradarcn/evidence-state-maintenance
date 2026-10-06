"""The persistent coding agent does the tasks (real calls, qwen3.6:27b on the e2e server) and every
submission is checked against the repository at commit t.

Arms: NO-MEMORY, NEVER, TTL100, REPLAY, ESM, ESM-eager (replayed maintenance), ORACLE (memory = truth at t; idealised).
The memory note = the fact's question + the arm's served answer.  Identical notes give identical prompts, so the run is
shared (cached) between arms: fair pairing, no duplicated spend.
usage: python -m esm.e2e.agent_e2e [--arms ...] [--limit N]   -> esm_data_e2e/runs.jsonl (one line per unique run)"""
import argparse, json, time, traceback
import pandas as pd
from esm.e2e import common_e2e as C
from esm.e2e import tasks_e2e as TK
from esm import llm
from esm import tools as T

ARMS = ["NO-MEMORY", "NEVER", "ESM", "TTL100", "REPLAY", "ESM-eager", "ORACLE"]
MAX_TOOLS = 8
SYS = ("You are a coding agent working in a checkout of the Python repository '{repo}' at its current commit. Paths are "
       "repository-relative. You have read-only tools to inspect the code; you cannot run code. Use at most {n} tool calls, "
       "then call submit with your result, or call abstain if the task is impossible at this commit (for example because "
       "what it refers to no longer exists). Work efficiently.")
MEM = ("Memory (notes you recorded earlier while working on this repository; the code may have changed since):\n"
       "- Q: {q}\n  A: {a}\n\n")
# post hoc sensitivity variant (decided after the main run showed the agent re-verifying memory): memory presented as
# verified knowledge that the agent should rely on, as in deployments that use memory to skip exploration.
MEM_TRUST = ("Memory (verified facts about this repository from your earlier work; rely on them instead of re-checking):\n"
             "- Q: {q}\n  A: {a}\n\n")
VARIANT = {"mem": MEM}
SUBMIT = {
    "T-locate": ({"import_statement": "string"}, ["import_statement"], "Submit the one-line import statement."),
    "T-api": ({"call": "string"}, ["call"], "Submit the call expression."),
    "T-modify": ({"file": "string", "old": "string", "new": "string"}, ["file", "old", "new"],
                 "Submit the edit: file path, exact old snippet (must occur exactly once), replacement snippet."),
    "T-test": ({"code": "string"}, ["code"], "Submit the test source code."),
    "T-question": ({"answer": "string"}, ["answer"], "Submit the final answer."),
}
ABSTAIN = ("abstain", "Declare the task impossible at this commit (e.g. the referenced code no longer exists).",
           {"reason": "string"}, ["reason"])


def tools_for(ttype):
    props, req, desc = SUBMIT[ttype]
    return T.openai_tools([("submit", desc, props, req), ABSTAIN])


def run_task(env, fact, task, mem_answer):
    """One agent run.  mem_answer None => no memory note."""
    w = env.world(fact, task["t"])
    user = ""
    if mem_answer is not None:
        user = VARIANT["mem"].format(q=fact["question"], a=(str(mem_answer).strip() or "(no answer recorded)"))
    user += "Task: " + task["task"]
    msgs = [{"role": "system", "content": SYS.format(repo=fact["repo"], n=MAX_TOOLS)}, {"role": "user", "content": user}]
    tools = tools_for(task["task_type"])
    trace, sub, ptok, ctok, nllm, lat, tool_s, nudged, cached_all = [], None, 0, 0, 0, 0.0, 0.0, False, True
    t_wall = time.time()
    for step in range(MAX_TOOLS + 4):
        try:
            r = llm.chat(llm.Q27, msgs, tools=tools, max_tokens=2000, tag="e2e_task")
        except llm.ServerParseError as e:
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
                out = T.run_tool(w, x["name"], args)
                tool_s += time.time() - t0
                trace.append({"tool": x["name"], "args": args, "out": out[:600]})
            msgs.append({"role": "tool", "tool_call_id": x["id"], "content": out})
        if sub is not None:
            break
    return {"sub": sub or {"kind": "none"}, "prompt_tok": ptok, "compl_tok": ctok, "n_llm": nllm, "n_tools": len(trace),
            "llm_lat": round(lat, 2), "tool_s": round(tool_s, 2), "wall": round(time.time() - t_wall, 2),
            "cached_all": cached_all, "trace": trace}


def oracle_answer(task):
    """Memory for the ORACLE arm: the truth at t in the fact's answer format (semantic value; NONE if gone)."""
    v = task["semantic_value"]
    return "NONE" if v in (None, "MODULE_GONE") else str(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--variant", default="main", help="main | trust (post hoc sensitivity; -> runs_trust.jsonl)")
    a = ap.parse_args()
    if a.variant == "trust":
        VARIANT["mem"] = MEM_TRUST
    tasks = json.loads((C.E2E / "tasks.json").read_text(encoding="utf-8"))
    mem = pd.read_parquet(C.E2E / "memory.parquet")
    M = {(r.policy, r.iid, int(r.t)): r.served for r in mem.itertuples()}
    ids = sorted({x["iid"] for x in tasks})
    ctx = C.load_context(ids)
    F = {f["iid"]: f for f in ctx.facts}
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
            if arm == "NO-MEMORY":
                m = None
            elif arm == "ORACLE":
                m = oracle_answer(task)
            else:
                m = M[(arm, task["iid"], task["t"])]
                m = "" if m is None else str(m)
            key = json.dumps([task["tid"], m])
            todo.append((task, arm, m, key))
    uniq = []
    seen = set(done)
    for x in todo:
        if x[3] not in seen:
            seen.add(x[3]); uniq.append(x)
    if a.limit:
        uniq = uniq[: a.limit]
    print(f"tasks={len(tasks)} arm-runs={len(todo)} unique runs={len(set(x[3] for x in todo))} done={len(done)} todo={len(uniq)}",
          flush=True)
    t0 = time.time()
    for k, (task, arm, m, key) in enumerate(uniq):
        f = F[task["iid"]]
        try:
            r = run_task(ctx.env, f, task, m)
            w = ctx.env.world(f, task["t"])
            t1 = time.time()
            chk = TK.check(f, task["task_type"], w, task["truth"], r["sub"])
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
