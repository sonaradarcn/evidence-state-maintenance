"""Zero-LLM: re-run the success checks of every recorded agent run against the current tasks.json (used after the
ground-truth fix of 2026-10-06 00:20, see PLAN.md).  Old files are kept as <name>.pre_recheck.jsonl.
usage: python -m esm.e2e.recheck_e2e"""
import json, shutil
from esm.e2e import common_e2e as C
from esm.e2e import tasks_e2e as TK

tasks = {t["tid"]: t for t in json.loads((C.E2E / "tasks.json").read_text(encoding="utf-8"))}
ctx = C.load_context(sorted({t["iid"] for t in tasks.values()}))
F = {f["iid"]: f for f in ctx.facts}
for name in ("runs.jsonl", "runs_trust.jsonl"):
    p = C.E2E / name
    if not p.exists():
        continue
    bak = p.with_name(p.stem + ".pre_recheck.jsonl")
    if not bak.exists():
        shutil.copyfile(p, bak)
    out, changed = [], 0
    for l in bak.read_text(encoding="utf-8").splitlines():
        if not l.strip():
            continue
        d = json.loads(l)
        t = tasks[d["tid"]]
        f = F[t["iid"]]
        chk = TK.check(f, t["task_type"], ctx.env.world(f, t["t"]), t["truth"], d["sub"])
        if chk["outcome"] != d["check"]["outcome"]:
            changed += 1
            print("changed", name, d["tid"], d["first_arm"], d["check"]["outcome"], "->", chk["outcome"], chk["detail"][:80])
        d["check_pre_recheck"] = d["check"]
        d["check"] = chk
        out.append(json.dumps(d, ensure_ascii=False))
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(name, "runs", len(out), "outcomes changed", changed)
