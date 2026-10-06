"""Evidence recording and evidence states (no LLM).

1. Drift-robust recording.  `record()` turns a derivation trace into a list of *queries* via `env.anchor_call`.
   For code environments (`code_anchor` below, used by PyRepoEnv):
     * read(file, a, b)  -> def_block of the enclosing top-level def/class or Class.method when the (visible) window lies
                            inside one that is not much larger than the window; otherwise a CONTENT-ANCHORED span located
                            by distinctive first/last non-blank lines of the window (EOF-anchored when the window reached
                            the end of the file); if the anchor line disappears, the original fixed window is shown.
     * grep              -> line-number-insensitive output (`file:N:text` -> `file:text`)
     * ls / find         -> sorted set of lines
     * everything else   -> the original call (def_block, list_defs, toml_get, ini_get are already symbol-addressed)
   mode='original' keeps every call as recorded (pilot7's recording: pilot3 line-number normalisation only).
2. Evidence state = fingerprint of all normalised observation outputs.  Same state as the anchor => REUSE.

`ObsTable` precomputes and memoises observation series (one hash per version, texts stored once per distinct value).
"""
import hashlib, json, re
from . import tools as T

# ---------------------------------------------------------------- generic evidence machinery


def qkey(q):
    return json.dumps({k: v for k, v in q.items() if k != "orig"}, sort_keys=True)


def h(s):
    return hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()[:16]


class Evidence:
    """An anchored evidence record: queries, their reference observations, the answer they support."""
    __slots__ = ("queries", "keys", "ref", "t", "K", "cites", "aid", "origin")

    def __init__(self, queries, ref, t, K, cites, aid, origin):
        self.queries, self.ref, self.t, self.K, self.cites, self.aid, self.origin = queries, ref, t, K, cites, aid, origin
        self.keys = [qkey(q) for q in queries]

    def state(self):
        return fingerprint(self.ref, self.keys)


def fingerprint(obs, keys):
    return h("\x1e".join(h(obs[k]) for k in keys))


def dedup_calls(trace):
    calls, seen = [], set()
    for c in trace:
        k = c["tool"] + "|" + json.dumps(c.get("args") or {}, sort_keys=True)
        if k not in seen:
            seen.add(k)
            calls.append({"tool": c["tool"], "args": c.get("args") or {}})
    return calls


def record(env, fact, trace, t, mode, cites, K, aid, origin="derivation"):
    """Anchor every distinct call of `trace` at time t; reference observations are taken at t."""
    w = env.world(fact, t)
    qs, seen = [], set()
    calls = dedup_calls(trace)
    # an environment may anchor each call in the context of the whole trace (e.g. a data-lake listing anchored on the
    # entries later calls used); default: call by call
    anch = (env.anchor_calls(w, calls, cites, mode, K, question=fact.get("question")) if hasattr(env, "anchor_calls")
            else [env.anchor_call(w, c, cites, mode) for c in calls])
    for q in anch:
        k = qkey(q)
        if k not in seen:
            seen.add(k)
            qs.append(q)
    ref = {qkey(q): env.observe(w, q) for q in qs}
    return Evidence(qs, ref, t, K, cites, aid, origin)


def reanchor(env, fact, ev, t, K, aid, origin="repair"):
    """Re-run the anchored queries at time t (content anchors re-picked on t's content) -> new Evidence."""
    w = env.world(fact, t)
    qs, seen = [], set()
    for q in ev.queries:
        q2 = env.reanchor(w, q)
        k = qkey(q2)
        if k not in seen:
            seen.add(k)
            qs.append(q2)
    ref = {qkey(q): env.observe(w, q) for q in qs}
    return Evidence(qs, ref, t, K, ev.cites, aid, origin)


class ObsTable:
    """Memoised observation series per (unit, query): series[t] = hash, texts[hash] = observation."""

    def __init__(self, env):
        self.env = env
        self.series, self.texts = {}, {}

    def obs(self, fact, q, t):
        k = (fact["unit"], qkey(q))
        s = self.series.get(k)
        if s is None:
            s = [None] * (self.env.n_steps() + 1)
            self.series[k] = s
        if s[t] is None:
            o = self.env.observe(self.env.world(fact, t), q)
            hh = h(o)
            self.texts.setdefault(hh, o)
            s[t] = hh
        return s[t]

    def text(self, hh):
        return self.texts[hh]

    def state(self, fact, ev, t):
        """(fingerprint, {qkey: hash}) of the evidence's queries at time t."""
        hs = {k: self.obs(fact, q, t) for k, q in zip(ev.keys, ev.queries)}
        return h("\x1e".join(hs[k] for k in ev.keys)), hs

    def ref_state(self, ev):
        return h("\x1e".join(h(ev.ref[k]) for k in ev.keys))

    # ---- persistence (one pickle per unit; merged on load)
    def save(self, path, unit=None):
        import os, pickle
        ser = {k: v for k, v in self.series.items() if unit is None or k[0] == unit}
        need = {x for s in ser.values() for x in s if x is not None}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_bytes(pickle.dumps({"series": ser, "texts": {x: self.texts[x] for x in need}}))
        import time
        for k in range(10):          # the file may be open in another process (Windows): retry, then give up (cache only)
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                time.sleep(2 + k)
        try:
            os.remove(tmp)
        except OSError:
            pass

    def load(self, path):
        import pickle
        if not path.exists():
            return
        d = pickle.loads(path.read_bytes())
        for k, s in d["series"].items():
            cur = self.series.get(k)
            if cur is None:
                self.series[k] = s
            else:
                for i, x in enumerate(s):
                    if cur[i] is None and x is not None:
                        cur[i] = x
        self.texts.update(d["texts"])

    def outputs(self, fact, ev, t):
        hs = {k: self.obs(fact, q, t) for k, q in zip(ev.keys, ev.queries)}
        return {k: self.texts[v] for k, v in hs.items()}


# ---------------------------------------------------------------- code-environment anchoring (used by PyRepoEnv)
_HDR = re.compile(r"^\d+: ")


def visible_window(w, call):
    """Effective [s, e] of a read call, restricted to lines fully visible in the (possibly 4000-char truncated) output."""
    a = call.get("args") or {}
    b = T.read_bounds(w, a.get("file", ""), a.get("start") or 1, a.get("end"))
    if b is None:
        return None
    s, e = b
    out = T.t_read(w, a.get("file", ""), a.get("start") or 1, a.get("end"))
    if "\n[... truncated" in out:
        body = out[:out.index("\n[... truncated")]
        shown = body.split("\n")
        # the last shown line may be cut in the middle
        full = [l for l in shown[:-1] if _HDR.match(l)]
        e = s + len(full) - 1 if full else s
    return s, e


def _distinct(lines, i, counts):
    st = lines[i].strip()
    return len(st) >= 6 and counts.get(lines[i], 0) == 1


def span_query(lines, s, e, file, orig):
    """Content-anchored span for 1-based window [s, e] of `lines`."""
    n = len(lines)
    s, e = max(1, s), min(e, n)
    counts = {}
    for l in lines:
        counts[l] = counts.get(l, 0) + 1
    idx = [i for i in range(s - 1, e) if lines[i].strip()]
    if not idx:
        return None
    first = next((i for i in idx[: max(1, len(idx) // 2)] if _distinct(lines, i, counts)), idx[0])
    eof = e >= n
    last = None
    if not eof:
        last = next((i for i in reversed(idx[len(idx) // 2:]) if _distinct(lines, i, counts) and i >= first), idx[-1])
    # blank/indistinct lines before `first` inside the window are dropped from the observation (they carry no content)
    return {"kind": "span", "file": file, "first": lines[first], "last": None if eof else lines[last],
            "pos": first + 1, "len": (n - 1 - first) if eof else (last - first), "orig": orig}


def code_anchor(w, call, mode):
    tool, a = call["tool"], call.get("args") or {}
    if mode == "original":
        return {"kind": "call", "tool": tool, "args": a, "norm": "p3"}
    if tool == "read":
        f = T.norm_path(a.get("file", ""))
        txt = w.text(f)
        vw = visible_window(w, call) if txt is not None else None
        if vw is None:
            return {"kind": "call", "tool": tool, "args": a, "norm": "p3"}
        s, e = vw
        lines = txt.split("\n")
        if f.endswith(".py"):
            pr = T.parse(w, f)
            if pr is not None:
                best = None
                for n in pr[0].body:
                    if not isinstance(n, (T.ast.FunctionDef, T.ast.AsyncFunctionDef, T.ast.ClassDef)):
                        continue
                    cands = [(n.name, n)]
                    if isinstance(n, T.ast.ClassDef):
                        cands += [(f"{n.name}.{m.name}", m) for m in n.body
                                  if isinstance(m, (T.ast.FunctionDef, T.ast.AsyncFunctionDef, T.ast.ClassDef))]
                    for name, node in cands:
                        ns = min([node.lineno] + [d.lineno for d in node.decorator_list])
                        if ns <= s and e <= node.end_lineno and T.find_node(pr[0], name) is node:
                            size = node.end_lineno - ns + 1
                            if best is None or size < best[1]:
                                best = (name, size)
                if best is not None and best[1] <= 1.5 * (e - s + 1) + 20:
                    return {"kind": "def", "file": f, "name": best[0], "orig": {"tool": tool, "args": a}}
        q = span_query(lines, s, e, f, {"tool": tool, "args": a})
        return q or {"kind": "call", "tool": tool, "args": a, "norm": "p3"}
    if tool == "grep":
        return {"kind": "call", "tool": tool, "args": a, "norm": "grep"}
    if tool in ("ls", "find"):
        return {"kind": "call", "tool": tool, "args": a, "norm": "set"}
    return {"kind": "call", "tool": tool, "args": a, "norm": "none"}


def _span_indices(lines, q):
    """(i1, i2) 0-based inclusive, or None if the first anchor line is gone."""
    c1 = [i for i, l in enumerate(lines) if l == q["first"]]
    if not c1:
        return None
    i1 = min(c1, key=lambda i: abs(i + 1 - q["pos"]))
    if q["last"] is None:
        i2 = min(len(lines) - 1, i1 + max(q["len"] + 50, 200))
    else:
        c2 = [i for i, l in enumerate(lines) if l == q["last"] and i >= i1]
        i2 = min(c2, key=lambda i: abs(i - i1 - q["len"])) if c2 else min(len(lines) - 1, i1 + q["len"])
    i2 = min(i2, i1 + 400)
    return i1, i2


def code_observe(w, q):
    if q["kind"] == "call":
        out = T.run_tool(w, q["tool"], q["args"])
        if q["norm"] in ("p3", "grep"):
            return T.normalise(q["tool"], out)
        if q["norm"] == "set":
            return "\n".join(sorted(set(out.split("\n"))))
        return out
    if q["kind"] == "def":
        return T.t_def_block(w, q["file"], q["name"])
    if q["kind"] == "span":
        txt = w.text(q["file"])
        if txt is None:
            return f"error: no such file: {q['file']}"
        lines = txt.split("\n")
        ix = _span_indices(lines, q)
        if ix is None:
            o = q["orig"]
            return "[content anchor not found; original fixed window shown]\n" + T.normalise("read", T.run_tool(w, "read", o["args"]))
        return "\n".join(lines[ix[0]: ix[1] + 1])
    raise ValueError(q)


def code_reanchor(w, q):
    if q["kind"] != "span":
        return q
    txt = w.text(q["file"])
    if txt is None:
        return q
    lines = txt.split("\n")
    ix = _span_indices(lines, q)
    if ix is None:
        vw = visible_window(w, q["orig"])
        if vw is None:
            return q
        s, e = vw
    else:
        s, e = ix[0] + 1, ix[1] + 1
    return span_query(lines, s, e, q["file"], q["orig"]) or q


def code_label(q):
    def cs(tool, a):
        return f"{tool}(" + ", ".join(f"{k}={json.dumps(v)}" for k, v in (a or {}).items()) + ")"
    if q["kind"] == "call":
        return cs(q["tool"], q["args"])
    if q["kind"] == "def":
        return f'def_block(file={json.dumps(q["file"])}, name={json.dumps(q["name"])})  [anchored form of {cs(q["orig"]["tool"], q["orig"]["args"])}]'
    first = q["first"].strip()[:60]
    last = "end of file" if q["last"] is None else q["last"].strip()[:60]
    return f'read(file={json.dumps(q["file"])}) span anchored on content: from `{first}` to `{last}`'
