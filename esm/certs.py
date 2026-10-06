"""Certificate baselines' LLM stage (held-out): CERT-ZS (pilot3's zero-shot certificate prompt, SkillGuard-style
LLM-extracted checks) and CERT-v0h (pilot3's CERT v0: LLM-proposed candidate certificates -> sufficiency test ->
lowest historical volatility).  Deviation of CERT-v0h from pilot3's CERT v0, stated in the results: the negative
sufficiency test uses only the real HISTORY counter-example (closest HISTORY commit whose oracle value differs from K);
pilot3's two synthetic perturbations are not ported.  Static facts only (as in pilot3/4).
Every call goes through esm.llm (cached).  Results persist in <data>/certs.jsonl, keyed by iid."""
import json, threading
from . import llm
from . import tools as T

API_DOC = "\n".join(f"- {n}({', '.join(p)}): {d}" for n, d, p, _ in T.TOOL_SCHEMAS)
_lock = threading.Lock()


def _trace_text(trace, lim=1500):
    parts = []
    for i, c in enumerate(trace, 1):
        o = c["out"] if len(c["out"]) <= lim else c["out"][:lim] + "\n[...]"
        parts.append(f"[{i}] {c['tool']}({json.dumps(c['args'])})\n{o}")
    return "\n\n".join(parts)


def _clean_calls(calls, maxn, tool_set=None):
    tool_set = T.TOOLS if tool_set is None else tool_set
    out = []
    for c in (calls or [])[:maxn]:
        if not isinstance(c, dict):
            continue
        name = c.get("tool") or c.get("name")
        args = c.get("args") or c.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        if name in tool_set and isinstance(args, dict):
            out.append({"tool": name, "args": args})
    return out


def cert_zs(env, f, model=llm.Q27):
    # code environments: pilot3's prompt unchanged; other environments supply their subject and tool API
    subject = getattr(env, "cert_subject", None)
    head = f"Question about the repository: " if subject is None else f"Question about {subject}: "
    prompt = (f"{head}{f['question']}\nAnswer (verified): {f['K']}\n\nExploration trace:\n{_trace_text(f['trace'])}\n\n"
              f"Tool API:\n{getattr(env, 'tool_api_doc', API_DOC)}\n\n"
              "Write an evidence certificate for this fact: at most 3 tool calls from the API above whose outputs, on their own, are sufficient to "
              "conclude the answer. The certificate will be re-executed later to check whether the fact still holds. "
              'Reply with JSON only: {"calls": [{"tool": "...", "args": {...}}]}')
    r = llm.chat(model, [{"role": "user", "content": prompt}], max_tokens=3000, tag="certzs")
    j = llm.json_from(r["content"]) or {}
    return {"calls": _clean_calls(j.get("calls") if isinstance(j, dict) else None, 3, getattr(env, "tool_set", None)),
            "tokens": [r["usage"]["prompt"], r["usage"]["completion"]]}


PROPOSE = ("We want to store this fact in long-term memory together with an EVIDENCE CERTIFICATE: a small set (at most 3) of deterministic tool calls "
           "whose outputs alone are sufficient to re-derive the answer. Later, the certificate is re-executed on newer commits; if any output changes, "
           "the fact is treated as stale. A good certificate (1) is sufficient: from its outputs alone, someone can conclude exactly this answer and would "
           "notice if the answer changed; (2) is insensitive to irrelevant edits: prefer structural/semantic queries (def_block, toml_get, ini_get, list_defs, "
           "grep_count, narrowly targeted grep patterns) over whole-file reads or line-range reads, which change whenever unrelated lines move; "
           "(3) when the answer is a uniqueness, set or count claim (e.g. 'defined only in file X', 'these files import m', 'there are N tests'), includes an explicit "
           "negative/completeness query over the relevant scope (e.g. a repository-wide grep for the definition or for imports of the module) so that a NEW file "
           "would be noticed.\n"
           "Propose up to 6 DIVERSE candidate certificates (different tools/scopes/patterns). "
           'Reply with JSON only: {"candidates": [{"calls": [{"tool": "...", "args": {...}}], "why": "..."}]}')


def _suff(env, f, calls, outs, model):
    body = "\n\n".join(f"[{i}] {c['tool']}({json.dumps(c['args'])})\n{o}" for i, (c, o) in enumerate(zip(calls, outs), 1))
    p = (f"Question about a Python repository: {f['question']}\n\n"
         f"You are given ONLY the outputs of the following deterministic tool calls, executed on the repository:\n\n{body}\n\n"
         "Using only these outputs (no prior knowledge of the repository), answer the question. If the outputs do not determine the answer "
         'with certainty, answer "INSUFFICIENT". Reply with JSON only: {"answer": "..."}')
    r = llm.chat(model, [{"role": "user", "content": p}], max_tokens=3000, tag="certsuff")
    j = llm.json_from(r["content"])
    ans = str(j.get("answer")) if isinstance(j, dict) and "answer" in j else (r["content"] or "").strip()
    return ans, r["usage"]["prompt"] + r["usage"]["completion"]


def cert_v0h(env, f, model=llm.Q27):
    repo = env.repo(f["unit"])
    w0 = env.world(f, 0)
    p = (f"Question about the repository: {f['question']}\nAnswer (verified): {f['K']}\n\nExploration trace:\n{_trace_text(f['trace'])}\n\n"
         f"Tool API:\n{API_DOC}\n\n" + PROPOSE)
    r = llm.chat(model, [{"role": "user", "content": p}], max_tokens=5000, tag="certprop")
    tok = r["usage"]["prompt"] + r["usage"]["completion"]
    j = llm.json_from(r["content"]) or {}
    raw = j.get("candidates", []) if isinstance(j, dict) else []
    cands, seen = [], set()
    for c in raw[:6]:
        calls = _clean_calls(c.get("calls") if isinstance(c, dict) else None, 3)
        k = json.dumps(calls, sort_keys=True)
        if calls and k not in seen:
            seen.add(k)
            cands.append({"calls": calls})
    # closest HISTORY counter-example (oracle value differs from the s0 value)
    ce = next((i for i in range(299, -1, -1) if f["truth"][i] != f["truth"][300]), None)
    wce = repo.world(repo.history[ce]) if ce is not None else None
    surv = []
    for i, c in enumerate(cands):
        outs0 = [T.run_tool(w0, x["tool"], x["args"]) for x in c["calls"]]
        if all(o.startswith("error") for o in outs0):
            c["pos"] = False
            continue
        a0, t = _suff(env, f, c["calls"], outs0, model)
        tok += t
        c["pos"] = env.answers_agree(f, a0, f["K"])
        if not c["pos"]:
            continue
        c["neg"] = None
        if wce is not None:
            outs = [T.run_tool(wce, x["tool"], x["args"]) for x in c["calls"]]
            if [T.normalise(x["tool"], o) for x, o in zip(c["calls"], outs)] == [T.normalise(x["tool"], o) for x, o in zip(c["calls"], outs0)]:
                c["neg"] = False
                continue
            a1, t = _suff(env, f, c["calls"], outs, model)
            tok += t
            c["neg"] = not env.answers_agree(f, a1, f["K"])
            if not c["neg"]:
                continue
        # historical volatility over the 300 HISTORY commits + s0 (no LLM)
        prev, vol = None, 0
        for cm in repo.history + [repo.s0]:
            w = repo.world(cm)
            o = tuple(T.normalise(x["tool"], T.run_tool(w, x["tool"], x["args"])) for x in c["calls"])
            if prev is not None and o != prev:
                vol += 1
            prev = o
        c["vol"] = vol
        surv.append((vol, len(c["calls"]), i))
    pick = min(surv)[2] if surv else None
    return {"calls": cands[pick]["calls"] if pick is not None else None, "n_cands": len(cands), "n_surv": len(surv),
            "history_ce": ce, "tokens": tok}


class CertStore:
    def __init__(self, path):
        self.path = path
        self.d = {}
        from .maintain import read_shards
        import os
        for r in read_shards(path):
            self.d[(r["iid"], r["kind"])] = r
        self.wpath = path.with_name(f"{path.stem}.{os.getpid()}.jsonl")

    def get(self, env, f, kind, model=llm.Q27):
        k = (f["iid"], kind)
        if k in self.d:
            return self.d[k]
        res = cert_zs(env, f, model) if kind == "certzs" else cert_v0h(env, f, model)
        rec = {"iid": f["iid"], "kind": kind, **res}
        with _lock:
            self.d[k] = rec
            with open(self.wpath, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    def attach(self, facts):
        for f in facts:
            z = self.d.get((f["iid"], "certzs"))
            v = self.d.get((f["iid"], "certv0h"))
            f["certzs"] = (z or {}).get("calls") or []
            f["certv0"] = (v or {}).get("calls")
            f["cert_tokens"] = {"certzs": sum((z or {}).get("tokens") or [0]) if z else None,
                                "certv0h": (v or {}).get("tokens") if v else None}
            f["has_certzs"], f["has_certv0"] = z is not None, v is not None
