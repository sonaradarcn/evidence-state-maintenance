"""Git-repository environment (Python repos): the dev-set implementation of `esm.env.Environment`.

Facts: the 241 static primary instances of pilot3-5 (truth = pilot4's oracle series) and the 44 behaviour facts of
pilot6 (truth = executed values).  All pilot files are only READ.  New repositories: build a `GitRepo` for the clone,
produce fact dicts with the same fields (see esm/env.py) and a truth series (e.g. `pyfacts.oracle` per commit for
static facts), and pass them to `PyRepoEnv(facts=..., repos=...)`.
"""
import json, os, pickle, re
from pathlib import Path
from .. import tools as T
from .. import evidence as E
from .. import llm
from ..env import Environment
from . import pyfacts as FX

ROOT = Path(__file__).resolve().parents[2]
P3, P4, P6 = ROOT / "pilot3", ROOT / "pilot4", ROOT / "pilot6"
# Dev set: clones and tree caches of the pilot studies (<D>/pilot3_data, <D>/pilot6_data) and the pilot outputs
# under <repo>/pilot3, pilot4, pilot6.  These are not part of this release (see README, "Development set").
D = Path(os.environ.get("ESM_DEV_REPOS", ROOT))
STATIC_REPOS = ["requests", "flask", "click", "pytest", "seaborn", "xarray"]
BEHAV_REPOS = ["click", "packaging", "more-itertools", "attrs"]
MTAG = {"nvidia/nemotron-3-super-120b-a12b": "nemotron", "qwen3.5:9b": "qwen", "openai/gpt-oss-120b": "gptoss",
        "qwen/qwen3.8-27b": "groqqwen"}

SYS_STATIC = ("You are a careful code-exploration agent working on a checkout of the Python repository '{repo}'. "
              "Paths are relative to the repository root. Use the tools to find and verify the answer; do not guess. "
              "You may use at most 12 tool calls. When done, call answer(value=...) with only the final answer.")
SYS_BEHAV = ("You are a careful code-exploration agent working on a checkout of the Python repository '{repo}'. "
             "Paths are relative to the repository root. You cannot execute code: read the source with the tools and reason about it. "
             "You may use at most 12 tool calls. When done, call answer(value=...) with only the final answer.")
ANSWER_TOOL = ("answer", "Submit the final answer.", {"value": "string"}, ["value"])
# Held-out stage (27B agent): one sentence added to the agent's system prompt so that "the referent no longer exists" is
# answered in the benchmark's format (the dev-stage 9B agent often answered such cases with prose, scored wrong).
NONE_HINT = (" If what the question refers to does not exist at this commit (for example it was removed, renamed or moved "
             "away), call answer(value='NONE').")
MAX_CALLS = 12


def _repo_paths(name, behav):
    if name in STATIC_REPOS:
        return D / "pilot3_data" / "repos" / name, D / "pilot3_data" / "trees" / f"{name}.pkl"
    return D / "pilot6_data" / "repos" / name, D / "pilot6_data" / "trees" / f"{name}.pkl"


def _load_instances(name):
    """pilot3 kept (correct) LLM-stage instances for one repo (mirrors pilot4 common.load_instances)."""
    out3 = P3 / "out"
    fd = json.loads((out3 / f"facts_{name}.json").read_text())
    facts = {f["id"]: f for f in fd["facts"]}
    meta = json.loads((out3 / f"guardmeta_{name}.json").read_text())
    recs, have = [], set()
    for suffix, default_model in (("", "nvidia/nemotron-3-super-120b-a12b"), (".qwen", "qwen3.5:9b"),
                                  (".gptoss", "openai/gpt-oss-120b"), (".groqqwen", "qwen/qwen3.8-27b")):
        p = out3 / f"llm_{name}{suffix}.jsonl"
        if not p.exists():
            continue
        for l in p.read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            r = json.loads(l)
            if r["id"] not in facts:
                continue
            r.setdefault("model", default_model)
            primary = r["id"] not in have
            have.add(r["id"])
            iid = f"{r['id']}@{MTAG[r['model']]}"
            if iid not in meta or not meta[iid].get("correct"):
                continue
            f = dict(facts[r["id"]])
            f["K"] = f["K_oracle"]
            r.update(fact=f, iid=iid, primary=primary, meta=meta[iid])
            recs.append(r)
    return recs


def load_dev_facts():
    """285 dev facts (241 static primary + 44 behaviour) with guard instruments for the baselines."""
    P4A = pickle.loads((P4 / "out" / "analysis.pkl").read_bytes())
    tv, info4 = P4A["tv"], P4A["info"]
    facts = []
    for name in STATIC_REPOS:
        sig = pickle.loads((P4 / "out" / f"sig_{name}.pkl").read_bytes())
        for r in _load_instances(name):
            if not r["primary"]:
                continue
            f = r["fact"]
            iid = r["iid"]
            pick = info4[iid]["CERT-v0"]["pick"]
            if pick and pick.startswith("p3c"):
                cv0 = r["candidates"][int(pick[3:])]["calls"]
            else:
                cv0 = None   # REPLAY
            facts.append({"iid": iid, "slice": "static", "unit": name, "repo": name, "type": f["type"], "model": r["model"],
                          "question": f["question"], "K": str(f["K"]), "args": f["args"], "trace": r["derive"]["trace"],
                          "cite": [c for c in r.get("cite", {}).get("citations", []) if isinstance(c, dict)],
                          "truth": [str(x) for x in sig[iid]["truth"]], "valid": [bool(x) for x in tv[iid]],
                          "derive_tokens": r["derive"]["tokens"],
                          "certzs": (r.get("certzs") or {}).get("calls") or [], "certv0": cv0})
    for b in json.loads((P6 / "out" / "behav_facts.json").read_text(encoding="utf-8")):
        K = str(b["K"])
        truth = [str(x) for x in b["truth"]]
        facts.append({"iid": b["iid"], "slice": "behav", "unit": b["repo"], "repo": b["repo"], "type": "B", "model": b["model"],
                      "question": b["fact"]["question"], "K": K, "args": b["fact"]["args"], "trace": b["trace"],
                      "cite": [c for c in (b.get("cite") or []) if isinstance(c, dict)],
                      "truth": truth, "valid": [truth[301 + i] == K for i in range(400)], "derive_tokens": b["derive_tokens"],
                      "certzs": b.get("certzs") or [], "certv0": None})
    return facts


class PyRepoEnv(Environment):
    name = "pyrepo"
    domain = "a Python repository"
    tool_names = "ls, find, grep, read, def_block, list_defs, toml_get, ini_get"

    def __init__(self, facts=None, repos=None, none_hint=False):
        self.none_hint = none_hint
        self._facts = facts if facts is not None else load_dev_facts()
        self._repos = repos or {}
        self._worlds = {}

    # ---- data
    def facts(self):
        return self._facts

    def n_steps(self):
        return T.N_FUT

    def repo(self, unit):
        if unit not in self._repos:
            p, tc = _repo_paths(unit, None)
            self._repos[unit] = T.GitRepo(unit, p, tc)
        return self._repos[unit]

    def world(self, fact, t):
        k = (fact["unit"], t)
        w = self._worlds.get(k)
        if w is None:
            r = self.repo(fact["unit"])
            w = r.world(r.s0 if t == 0 else r.future[t - 1])
            self._worlds[k] = w
        return w

    def truth(self, fact, t):
        return fact["truth"][300 + t]

    def answer_matches(self, fact, answer, value):
        if answer is None:
            return False
        if fact["slice"] == "behav":
            return FX.canon_b(answer) == FX.canon_b(value)
        try:
            return FX.canon(fact["type"], fact["args"].get("sub"), str(answer)) == FX.canon_oracle({"type": fact["type"]}, value)
        except Exception:
            return False

    def answers_agree(self, fact, a, b):
        """Two answer strings denote the same value (canonicalised; no oracle involved)."""
        if a is None or b is None:
            return False
        if fact["slice"] == "behav":
            return FX.canon_b(a) == FX.canon_b(b)
        try:
            sub = fact["args"].get("sub")
            return FX.canon(fact["type"], sub, str(a)) == FX.canon(fact["type"], sub, str(b))
        except Exception:
            return False

    # ---- tools and evidence
    def run_call(self, world, call):
        return T.run_tool(world, call["tool"], call.get("args") or {})

    def anchor_call(self, world0, call, cites, mode):
        return E.code_anchor(world0, call, mode)

    def observe(self, world, query):
        return E.code_observe(world, query)

    def reanchor(self, world, query):
        return E.code_reanchor(world, query)

    def query_label(self, query):
        return E.code_label(query)

    def cite_texts(self, fact, cites):
        out = []
        for c in cites:
            q = str(c.get("line", "")).rstrip("\n")
            q = re.sub(r"^\s*\d+:", "", q) if fact["slice"] == "behav" else q
            q = q.strip()
            if q:
                out.append(q)
        return out

    def auto_cites(self, fact, trace, answer):
        """Zero-LLM citations for a re-derived trace: output lines that contain the answer (or one of its items)."""
        if not answer:
            return []
        parts = [p.strip().strip("'\"`") for p in re.split(r"[,|\n]", str(answer))]
        parts = [p for p in parts if len(p) >= 3][:8] or ([str(answer).strip()] if str(answer).strip() else [])
        out, seen = [], set()
        for c in trace:
            for l in T.normalise(c["tool"], c.get("out") or "").split("\n"):
                s = l.strip()
                if s and s not in seen and any(p in s for p in parts):
                    seen.add(s)
                    out.append({"file": "", "line": s})
                    if len(out) >= 8:
                        return out
        return out

    # ---- baselines
    def read_set(self, trace):
        rs = set()
        for c in trace:
            rs |= T.files_touched(c["tool"], c.get("args") or {}, c.get("out") or "")
        return sorted(rs)

    def item_hash(self, world, item, kind):
        if kind == "file":
            return world.sha(item)
        return T.ast_fingerprint(world, item)

    def readset_diff(self, wa, wb, items, cap=8000):
        import difflib
        parts = []
        for p in items:
            if wa.sha(p) == wb.sha(p):
                continue
            a, b = wa.text(p), wb.text(p)
            if b is None:
                parts.append(f"--- a/{p}\n+++ (file deleted)")
                continue
            parts.append("".join(difflib.unified_diff((a or "").splitlines(True), b.splitlines(True), f"a/{p}", f"b/{p}", n=2)))
        s = "\n".join(parts)
        full = len(s)
        if len(s) > cap:
            s = s[:cap] + f"\n[... diff truncated, {len(s) - cap} more chars]"
        return s, full

    # ---- derivation agent (pilot3/pilot6 agent loop, same prompts and tools)
    def derive(self, fact, t, model=llm.Q9, tag="esm_derive"):
        w = self.world(fact, t)
        sysmsg = (SYS_BEHAV if fact["slice"] == "behav" else SYS_STATIC).format(repo=fact["repo"])
        if self.none_hint:
            sysmsg += NONE_HINT
        msgs = [{"role": "system", "content": sysmsg}, {"role": "user", "content": fact["question"]}]
        tools = T.openai_tools([ANSWER_TOOL])
        trace, answer, ntok, nllm, nnew = [], None, [0, 0], 0, 0
        for step in range(MAX_CALLS + 2):
            try:
                r = llm.chat(model, msgs, tools=tools, max_tokens=3000, tag=tag)
            except llm.ServerParseError:
                # the model emitted a malformed tool call that the server rejects: the derivation fails (no answer)
                break
            nllm += 1
            nnew += 0 if r.get("cached") else 1
            ntok[0] += r["usage"]["prompt"]; ntok[1] += r["usage"]["completion"]
            tcs = r["tool_calls"]
            if not tcs:
                if r["content"].strip():
                    answer = r["content"].strip().splitlines()[-1]
                break
            msgs.append({"role": "assistant", "content": r["content"] or None, "tool_calls": [
                {"id": x["id"], "type": "function", "function": {"name": x["name"], "arguments": x["arguments"]}} for x in tcs]})
            for x in tcs:
                try:
                    args = json.loads(x["arguments"] or "{}")
                    args = args if isinstance(args, dict) else {}
                except Exception:
                    args = {}
                if x["name"] == "answer":
                    answer = str(args.get("value", ""))
                    out = "ok"
                elif len(trace) >= MAX_CALLS:
                    out = "error: tool budget exhausted; call answer now"
                else:
                    out = T.run_tool(w, x["name"], args)
                    trace.append({"tool": x["name"], "args": args, "out": out})
                msgs.append({"role": "tool", "tool_call_id": x["id"], "content": out})
            if answer is not None:
                break
        return {"trace": trace, "answer": answer, "tokens": ntok, "n_llm": nllm, "n_new": nnew}
