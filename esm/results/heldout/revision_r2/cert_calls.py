"""Certificate construction LLM calls per fact (zero LLM, zero GPU).
Replays esm.certs.cert_zs / cert_v0h offline (ESM_LLM_OFFLINE=1, every call must be a cache hit) and counts the LLM calls
each construction made; the no-LLM history-volatility loop of cert_v0h is skipped (it makes no LLM call).
Checks the replayed token totals against certs.jsonl. Output: revision_r2/cert_calls.json."""
import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
os.environ.setdefault("ESM_DATA", str(ROOT / "esm_data_heldout")); os.environ.setdefault("ESM_STAGE", "heldout")
os.environ["ESM_LLM_OFFLINE"] = "1"
sys.path.insert(0, str(ROOT))
from esm import llm, certs
from esm import tools as T
from esm.maintain import read_shards
from esm.policies import Context

DATA = Path(os.environ["ESM_DATA"])
CNT = {"n": 0}
_chat = llm.chat
def chat(*a, **k):
    CNT["n"] += 1
    return _chat(*a, **k)
certs.llm.chat = chat

def v0h_calls(env, f, model=llm.Q27):
    """cert_v0h without the (LLM-free) volatility loop; returns tokens."""
    repo = env.repo(f["unit"]); w0 = env.world(f, 0)
    p = (f"Question about the repository: {f['question']}\nAnswer (verified): {f['K']}\n\nExploration trace:\n{certs._trace_text(f['trace'])}\n\n"
         f"Tool API:\n{certs.API_DOC}\n\n" + certs.PROPOSE)
    r = chat(model, [{"role": "user", "content": p}], max_tokens=5000, tag="certprop")
    tok = r["usage"]["prompt"] + r["usage"]["completion"]
    j = llm.json_from(r["content"]) or {}
    raw = j.get("candidates", []) if isinstance(j, dict) else []
    cands, seen = [], set()
    for c in raw[:6]:
        calls = certs._clean_calls(c.get("calls") if isinstance(c, dict) else None, 3)
        kk = json.dumps(calls, sort_keys=True)
        if calls and kk not in seen:
            seen.add(kk); cands.append({"calls": calls})
    ce = next((i for i in range(299, -1, -1) if f["truth"][i] != f["truth"][300]), None)
    wce = repo.world(repo.history[ce]) if ce is not None else None
    for c in cands:
        outs0 = [T.run_tool(w0, x["tool"], x["args"]) for x in c["calls"]]
        if all(o.startswith("error") for o in outs0):
            continue
        a0, t = certs._suff(env, f, c["calls"], outs0, model); tok += t
        if not env.answers_agree(f, a0, f["K"]):
            continue
        if wce is not None:
            outs = [T.run_tool(wce, x["tool"], x["args"]) for x in c["calls"]]
            if [T.normalise(x["tool"], o) for x, o in zip(c["calls"], outs)] == [T.normalise(x["tool"], o) for x, o in zip(c["calls"], outs0)]:
                continue
            a1, t = certs._suff(env, f, c["calls"], outs, model); tok += t
    return tok

ctx = Context.load("heldout")
rec = {(r["iid"], r["kind"]): r for r in read_shards(DATA / "certs.jsonl")}
F = {f["iid"]: f for f in ctx.facts}
out, bad = {}, []
for (iid, kind), r in sorted(rec.items()):
    if iid not in F:
        continue
    f = F[iid]; CNT["n"] = 0
    try:
        if kind == "certzs":
            z = certs.cert_zs(ctx.env, f); tok = sum(z["tokens"])
            want = sum(r["tokens"])
        else:
            tok = v0h_calls(ctx.env, f); want = r["tokens"]
    except llm.CacheMiss as e:
        bad.append((iid, kind, "miss")); continue
    if tok != want:
        bad.append((iid, kind, tok, want))
    out[f"{iid}|{kind}"] = {"calls": CNT["n"], "tokens": want}
(Path(__file__).resolve().parent / "cert_calls.json").write_text(json.dumps({"per_fact": out, "mismatch": bad}, indent=0))
print(len(out), "records;", len(bad), "mismatches", bad[:5])
