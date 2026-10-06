"""Evolving data-lake environment (NYC TLC trip records, Backblaze Drive Stats): `esm.env.Environment` implementation
on top of `datalake/` (lake, tools, fact types, oracles).

variant="real" (headline) removes every synthetic maintenance event from the snapshot sequence (snapshot indices are
kept) and recomputes truth with `facts_dl.oracle`; variant="synth" is the lake as built, used only for the synthetic-event
analysis.  `lake_anchor` / `lake_observe` make each tool's observation drift-robust; the rules are listed in
esm/README.md ("Data-lake anchoring") and esm/results/datalake/PLAN.md.
"""
import copy, difflib, hashlib, json, re, sys
from pathlib import Path
from .. import evidence as E
from .. import llm
from ..env import Environment

ROOT = Path(__file__).resolve().parents[2]
DL = ROOT / "datalake"
if str(DL) not in sys.path:
    sys.path.insert(0, str(DL))
import lake as L          # noqa: E402
import facts_dl as F      # noqa: E402

TOOL_NAMES = "ls, find, file_schema, head, file_rowcount, file_stats, sql, read_text, grep, schema_diff"
DESC = {"tlc": "the NYC TLC trip-record data lake (monthly Parquet files of yellow / green / fhv / fhvhv trips, the taxi zone "
               "lookup table and the data dictionaries)",
        "bb": "the Backblaze Drive Stats data lake (one CSV file per day with one row per drive, plus documentation)"}
SYS = ("You are a careful data-exploration agent working on a snapshot of {desc}. Files are referenced by their logical paths. "
       "Use the tools to find and verify the answer; do not guess. The sql tool has a per-call scan budget ({budget}), so a "
       "question over many files may need several cheaper observations (e.g. row counts from metadata) that you combine "
       "yourself. You may use at most 12 tool calls. When done, call answer(value=...) with only the final answer.")
NONE_HINT = (" If what the question refers to does not exist in this snapshot (for example the file, column or partition "
             "was removed, renamed or moved away), call answer(value='NONE').")
BUDGET_TXT = {"tlc": "at most 3 files and 1.2 million rows per call", "bb": "at most 10 files and 120,000 rows per call"}
ANSWER_TOOL = ("answer", "Submit the final answer.", {"value": "string"}, ["value"])
MAX_CALLS = 12


# ---------------------------------------------------------------- lake variants
class VariantLake(L.Lake):
    """L.Lake with the synthetic events removed (variant 'real') or kept ('synth').  Snapshot ids of the real variant
    carry an 'R' so that datalake's per-snapshot caches never mix the two variants in one process."""

    def __init__(self, name, variant="real"):
        self.name, self.variant = name, variant
        d = json.loads((L.SNAPS / f"{name}.json").read_text())
        evs = copy.deepcopy(d["events"])
        if variant == "real":
            final = {}
            for e in evs:
                if e.get("synthetic") and e["kind"] == "correct":
                    final.update(e["put"])
            late = {}
            for e in evs:
                if e.get("synthetic") and e["kind"] in ("correct", "repartition", "rename_dir", "late_day"):
                    if e["kind"] == "late_day":
                        late.update(e["put"])
                    e["synthetic_noop"] = e["kind"]
                    e["put"], e["remove"] = {}, []
                else:
                    for p in list(e.get("put", {})):
                        if p in final:
                            e["put"][p] = final[p]
                e["synthetic"] = False
            for p, sha in late.items():          # the withheld day arrives with its month batch
                pre = p.rsplit("-", 1)[0] + "-"
                tgt = next(e for e in evs if any(k.startswith(pre) for k in e.get("put", {})))
                tgt["put"][p] = sha
            for e in evs:
                e["snap"] = e["snap"].replace(f"{name}-", f"{name}R-")
        self.meta = d
        self.events = evs
        self.rows = d.get("rows", {})
        self.all_snapshots = [e["snap"] for e in evs]
        trees, cur = {}, {}
        for e in evs:
            for p in e.get("remove", []):
                cur.pop(p, None)
            for p, sha in e.get("put", {}).items():
                cur[p] = sha
            trees[e["snap"]] = {p: (s, Path(p).suffix in L.TEXT_EXT) for p, s in cur.items()}
        self.trees = trees
        self.s0_idx_all = d["s0_index"]
        h0 = d["history_start_index"]
        self.commits = self.all_snapshots[h0:]
        self.snapshots = self.commits
        self.s0_idx = self.s0_idx_all - h0
        self.s0 = self.commits[self.s0_idx]
        self.history = self.commits[:self.s0_idx]
        self.future = self.commits[self.s0_idx + 1:]
        self.event_of = {e["snap"]: e for e in evs}


# ---------------------------------------------------------------- key resolution (partition / basename)
_FLOAT = re.compile(r"(?<![\w.])-?\d+\.\d{11,}(?:[eE][-+]?\d+)?(?![\w.])")


def resolve(w, path):
    """Logical files a file reference denotes now: exact path, else same (dataset, month) partition, else same basename."""
    p = L._norm_path(path)
    if p in w.tree:
        return [p]
    m = F.TLC_RX.search(p)
    if m:
        ps = F.tlc_index(w)["parts"].get((m.group(1), m.group(2)), [])
        if ps:
            return sorted(ps)
    base = p.rsplit("/", 1)[-1]
    hits = [x for x in w.paths() if x.rsplit("/", 1)[-1] == base]
    return hits if len(hits) == 1 else []


def _round_floats(s):
    def r(m):
        try:
            return f"{float(m.group(0)):.10g}"
        except ValueError:
            return m.group(0)
    return _FLOAT.sub(r, s)


def _set_lines(out):
    return "\n".join(sorted(set(out.split("\n"))))


def _obs_file(w, tool, a):
    files = resolve(w, a.get("file", ""))
    if not files:
        return f"error: no such file: {a.get('file')}"
    if tool == "file_schema":
        outs = []
        for f in files:
            s = L.schema_of(w, f)
            if s is None:
                return "error: not a tabular file (use read_text)"
            outs.append(tuple(sorted(s)))
        if len(set(outs)) > 1:
            return "error: part files of this partition have different schemas"
        return f"{len(outs[0])} columns\n" + "\n".join(f"{n}: {t}" for n, t in outs[0])
    if tool == "file_rowcount":
        if not all(f.endswith((".parquet", ".csv")) for f in files):
            return "error: not a tabular file"
        return str(sum(L.rowcount_of(w, f) for f in files))
    if tool == "file_stats":
        col = a.get("column")
        mins, maxs, nulls, rows = [], [], 0, 0
        for f in files:
            o = L.t_file_stats(w, f, col)
            m = re.search(r"\((\d+) rows.*?\): min=(.*) max=(.*) null_count=(\d+)$", o)
            if not m:
                return o
            rows += int(m.group(1)); nulls += int(m.group(4))
            if m.group(2) != "None":
                mins.append(m.group(2)); maxs.append(m.group(3))
        def key(x):
            try:
                return (0, float(x), "")
            except ValueError:
                return (1, 0.0, x)
        return (f"column {col}: rows={rows} min={min(mins, key=key) if mins else None} max={max(maxs, key=key) if maxs else None} "
                f"null_count={nulls}")
    if tool == "head":
        o = L.t_head(w, files[0], a.get("n", 5))
        if o.startswith("error") or o.startswith("(0 rows)"):
            return o
        lines = o.rstrip("\n").split("\n")
        return "\n".join(lines[:1] + sorted(lines[1:]))
    raise ValueError(tool)


def _sql_rewrite(w, query):
    """Re-resolve quoted file literals that no longer exist (partition / basename key)."""
    def sub(m):
        s = m.group(1).replace("''", "'")
        if not L._looks_like_path(s) or any(ch in s for ch in "*?["):
            return m.group(0)
        p = L._norm_path(s)
        if p in w.tree:
            return m.group(0)
        fs = resolve(w, p)
        if not fs:
            return m.group(0)
        if len(fs) == 1:
            return "'" + fs[0] + "'"
        return "[" + ", ".join("'" + x + "'" for x in fs) + "]"
    return L._LIT.sub(sub, query)


_BUDGET_ERR = re.compile(r"^error: scan budget exceeded.*", re.S)


def _obs_sql(w, query):
    out = L.t_sql(w, _sql_rewrite(w, query))
    if out.startswith("error"):
        return "error: scan budget exceeded" if _BUDGET_ERR.match(out) else out
    out = _round_floats(out)
    if re.search(r"\border\s+by\b", query, re.I):
        return out
    lines = out.split("\n")
    tail = [l for l in lines[1:] if l.startswith("... (more rows")]
    body = sorted(l for l in lines[1:] if not l.startswith("... (more rows"))
    return "\n".join(lines[:1] + body + tail)


def visible_text_window(w, a):
    f = L._norm_path(a.get("file", ""))
    txt = w.text(f) if f in w.tree else None
    if txt is None or Path(f).suffix not in L.TEXT_EXT:
        return None
    n = len(txt.split("\n"))
    s = max(1, int(a.get("start") or 1))
    e = int(a.get("end")) if a.get("end") else s + 119
    e = min(e, s + 199, n)
    out = L.t_read_text(w, f, a.get("start") or 1, a.get("end"))
    if "\n[... truncated" in out:
        shown = out[:out.index("\n[... truncated")].split("\n")
        full = [l for l in shown[:-1] if re.match(r"^\d+: ", l)]
        e = s + len(full) - 1 if full else s
    return f, s, e, txt


def lake_anchor(w, call, mode):
    tool, a = call["tool"], dict(call.get("args") or {})
    if mode == "original":
        return {"kind": "call", "tool": tool, "args": a, "norm": "p3"}
    if tool in ("ls", "find"):
        return {"kind": "call", "tool": tool, "args": a, "norm": "set"}
    if tool == "grep":
        return {"kind": "call", "tool": tool, "args": a, "norm": "grepset"}
    if tool in ("file_schema", "file_rowcount", "file_stats", "head"):
        return {"kind": "file", "tool": tool, "args": a}
    if tool == "sql":
        return {"kind": "sql", "query": str(a.get("query", ""))}
    if tool == "schema_diff":
        return {"kind": "call", "tool": tool, "args": a, "norm": "sdiff"}
    if tool == "read_text":
        vw = visible_text_window(w, a)
        if vw is None:
            return {"kind": "call", "tool": tool, "args": a, "norm": "p3"}
        f, s, e, txt = vw
        q = E.span_query(txt.split("\n"), s, e, f, {"tool": tool, "args": a})
        return q or {"kind": "call", "tool": tool, "args": a, "norm": "p3"}
    return {"kind": "call", "tool": tool, "args": a, "norm": "none"}


# ---------------------------------------------------------------- trace-aware anchoring: listings and file roles
_DIG = re.compile(r"\d+")


def series_of(p):
    """Series pattern of a path: every digit run replaced by '#' (e.g. trip-data/yellow_tripdata_#-#.parquet)."""
    return _DIG.sub("#", p)


def _series_rx(pat):
    return re.compile("^" + re.escape(pat).replace("\\#", r"\d+").replace("#", r"\d+") + "$")


def _skey(p):
    """Sort key within a series: the basename's digit runs as integers (dates), then the path."""
    b = p.rstrip("/").rsplit("/", 1)[-1]
    runs = _DIG.findall(b)
    # year-like (4-digit) runs first, then the others in order: data_Q3_2018 -> (2018, 3); 2018-09-30 -> (2018, 9, 30)
    return (tuple(int(x) for x in runs if len(x) == 4) + tuple(int(x) for x in runs if len(x) != 4), p)


def series_members(w, pat):
    rx = _series_rx(pat)
    return sorted((p for p in w.paths() if rx.match(p)), key=_skey)


def _listing_paths(w, tool, a):
    """Full (untruncated) set of entries a listing call denotes in world w: files (full paths) and dirs ('<path>/')."""
    if tool == "find":
        return sorted(p for p in w.paths() if L._glob_match(p, a.get("glob", "*")))
    scope = L._norm_path(a.get("path", "."))
    out = set()
    for p in w.paths():
        if scope and not p.startswith(scope + "/"):
            continue
        rest = p[len(scope) + 1:] if scope else p
        head = rest.split("/", 1)[0]
        out.add((scope + "/" if scope else "") + head + ("/" if "/" in rest else ""))
    return sorted(out)


def _visible_entries(w, tool, a):
    """Entries the agent actually saw (the tool output may be truncated), as full paths / dir paths."""
    out = L.run_tool(w, tool, a)
    if out.startswith("error") or out.startswith("(no matches)"):
        return []
    scope = L._norm_path(a.get("path", ".")) if tool == "ls" else ""
    ents = []
    for l in out.split("\n"):
        l = l.strip()
        if not l or l.startswith("...") or l.startswith("["):
            continue
        l = re.sub(r"\s+\(\d+ files\)$", "", l)
        ents.append((scope + "/" if scope else "") + l if tool == "ls" else l)
    return ents


def _arg_text(c):
    return json.dumps(c.get("args") or {}, ensure_ascii=False)


def _referenced(entry, others):
    """Is a listing entry used by another call (path / dir prefix in its arguments, or matched by a glob literal there)?"""
    e = entry.rstrip("/")
    for c in others:
        a = c.get("args") or {}
        txt = _arg_text(c)
        if entry.endswith("/"):
            if (c["tool"] == "ls" and L._norm_path(a.get("path", ".")) == e) or (e + "/") in txt:
                return True
            continue
        if e in txt:
            return True
        for v in [a.get("glob")] + [m.group(1) for m in L._LIT.finditer(str(a.get("query", "")))]:
            if v and any(ch in v for ch in "*?[") and (L._glob_match(e, v) or __import__("fnmatch").fnmatch(e, L._norm_path(v))):
                return True
    return False


_PERIOD = re.compile(r"\d{4}(?:-\d{2}){0,2}")


def _in_question(p, question):
    """The file's period token (YYYY, YYYY-MM or YYYY-MM-DD from its basename, any prefix) is named in the question."""
    if not question:
        return False
    for tok in _PERIOD.findall(p.rsplit("/", 1)[-1].replace("_", " ")):
        parts = tok.split("-")
        if any("-".join(parts[:k]) in question for k in range(1, len(parts) + 1)):
            return True
    return False


def _named_prefix(p, question):
    """Number of leading date parts of the basename's period token (YYYY[-MM[-DD]]) that the question names (0 = none)."""
    if not question:
        return 0
    best = 0
    for tok in _PERIOD.findall(p.rsplit("/", 1)[-1].replace("_", " ")):
        parts = tok.split("-")
        for k in range(len(parts), 0, -1):
            if "-".join(parts[:k]) in question:
                best = max(best, k)
                break
    return best


def restricted_series(p, question):
    """series_of(p), with the basename's leading date parts that the question names kept literal
    (e.g. question '... 2022 ...': trip-data/fhv_tripdata_2022-#.parquet)."""
    k = _named_prefix(p, question)
    d, b = (p.rsplit("/", 1) + [""])[:2] if "/" in p else ("", p)
    if "/" not in p:
        d, b = "", p
    if k == 0:
        return series_of(p)
    m = _PERIOD.search(b.replace("_", " "))
    if not m:
        return series_of(p)
    parts = m.group(0).split("-")
    keep = "-".join(parts[:k])
    i = m.start()
    tail = b[i + len(keep):]
    nb = _DIG.sub("#", b[:i]) + keep + _DIG.sub("#", tail)
    return (series_of(d) + "/" if d else "") + nb


def lake_anchor_trace(w, calls, mode, K, question=None):
    """Anchored queries for a whole trace (see module docstring); file-addressed calls on the newest member of a file
    series are anchored by ROLE (they follow the series' newest file), and listings keep only what later calls used."""
    if mode == "original":
        return [lake_anchor(w, c, mode) for c in calls]
    qs, roles = [], []
    globs = [v for c in calls for v in [(c.get("args") or {}).get("glob")] +
             [m.group(1) for m in L._LIT.finditer(str((c.get("args") or {}).get("query", "")))]
             if v and any(ch in v for ch in "*?[") and _DIG.search(v)]
    for c in calls:
        q = lake_anchor(w, c, mode)
        if q["kind"] == "file":
            p = L._norm_path(q["args"].get("file", ""))
            # a file picked through a period-restricted glob (e.g. yellow_tripdata_2022-*) is NOT the newest of its series
            # by role; it keeps its literal path
            narrowed = any(L._glob_match(p, g) or __import__("fnmatch").fnmatch(p, L._norm_path(g)) for g in globs)
            narrowed = narrowed or _in_question(p, question)
            if p in w.tree and not narrowed:
                pat = series_of(p)
                mem = series_members(w, pat)
                if len(mem) >= 2 and mem[-1] == p:
                    a = {k: v for k, v in q["args"].items() if k != "file"}
                    q = {"kind": "role", "tool": q["tool"], "args": a, "series": pat, "role": "latest", "orig_file": p}
                    roles.append(p)
        qs.append(q)
    out = []
    for c, q in zip(calls, qs):
        if not (q["kind"] == "call" and q["tool"] in ("ls", "find")):
            out.append(q)
            continue
        a = q["args"]
        others = [x for x in calls if x is not c]
        vis = _visible_entries(w, c["tool"], a)
        ref = [e for e in vis if _referenced(e, others)]
        if not ref and K and len(str(K).strip()) >= 4:          # the listing itself gave the answer (e.g. the latest month)
            ref = [e for e in vis if str(K).strip() in e]
        covered = lambda e: any(r == e or r.startswith(e.rstrip("/") + "/") for r in roles)
        allp = _listing_paths(w, c["tool"], a)
        present, latest, earliest, count = [], set(), set(), set()
        for e in ref:
            if covered(e):
                continue
            present.append(e)
            pat = restricted_series(e, question)
            mem = sorted([x for x in allp if _series_rx(pat).match(x)], key=_skey)
            if len(mem) >= 2 and mem[-1] == e:
                latest.add(pat)
            if len(mem) >= 2 and mem[0] == e:
                earliest.add(pat)
        # count role: the stored answer equals the number of entries of a series in this listing
        if K is not None and re.fullmatch(r"\d+", str(K).strip() or "x"):
            for pat in {series_of(e) for e in vis}:
                if sum(1 for x in allp if _series_rx(pat).match(x)) == int(str(K).strip()):
                    count.add(pat)
        out.append({"kind": "listing", "tool": c["tool"], "args": a, "present": sorted(set(present)),
                    "latest": sorted(latest), "earliest": sorted(earliest), "count": sorted(count)})
    return out


def _obs_listing(w, q):
    allp = _listing_paths(w, q["tool"], q["args"])
    have = set(allp)
    lines = [f"{'present' if e in have else 'absent'}: {e}" for e in q["present"]]
    for pat in q["latest"]:
        mem = sorted([x for x in allp if _series_rx(pat).match(x)], key=_skey)
        lines.append(f"newest entry matching {pat}: {mem[-1] if mem else '(none)'}")
    for pat in q["earliest"]:
        mem = sorted([x for x in allp if _series_rx(pat).match(x)], key=_skey)
        lines.append(f"oldest entry matching {pat}: {mem[0] if mem else '(none)'}")
    for pat in q["count"]:
        lines.append(f"number of entries matching {pat}: {sum(1 for x in allp if _series_rx(pat).match(x))}")
    return "\n".join(lines)


def _obs_role(w, q):
    mem = series_members(w, q["series"])
    if not mem:
        return f"error: no file matches {q['series']}"
    o = _obs_file(w, q["tool"], dict(q["args"], file=mem[-1]))
    if q["tool"] == "head" and not o.startswith("error"):
        return o.split("\n", 1)[0]          # the newest file's sample rows always differ: its header (columns) is the evidence
    return o


def lake_observe(w, q):
    k = q["kind"]
    if k == "listing":
        return _obs_listing(w, q)
    if k == "role":
        return _obs_role(w, q)
    if k == "call":
        if q["norm"] == "sdiff":
            a = q["args"]
            fa, fb = resolve(w, a.get("file_a", "")), resolve(w, a.get("file_b", ""))
            out = L.run_tool(w, "schema_diff", {"file_a": fa[0] if fa else a.get("file_a"), "file_b": fb[0] if fb else a.get("file_b")})
            return _set_lines(out)
        out = L.run_tool(w, q["tool"], q["args"])
        if q["norm"] == "p3":
            return L.normalise(q["tool"], out)
        if q["norm"] == "set":
            return _set_lines(out)
        if q["norm"] == "grepset":
            return _set_lines(L.normalise("grep", out))
        return out
    if k == "file":
        return _obs_file(w, q["tool"], q["args"])
    if k == "sql":
        return _obs_sql(w, q["query"])
    if k == "span":
        fs = resolve(w, q["file"])
        txt = w.text(fs[0]) if fs else None
        if txt is None:
            return f"error: no such file: {q['file']}"
        lines = txt.split("\n")
        ix = E._span_indices(lines, q)
        if ix is None:
            o = q["orig"]
            return "[content anchor not found; original fixed window shown]\n" + L.normalise("read_text", L.run_tool(w, "read_text", o["args"]))
        return "\n".join(lines[ix[0]: ix[1] + 1])
    raise ValueError(q)


def lake_reanchor(w, q):
    if q["kind"] != "span":
        return q
    fs = resolve(w, q["file"])
    txt = w.text(fs[0]) if fs else None
    if txt is None:
        return q
    lines = txt.split("\n")
    ix = E._span_indices(lines, q)
    if ix is None:
        vw = visible_text_window(w, q["orig"]["args"])
        if vw is None:
            return q
        _, s, e, _ = vw
    else:
        s, e = ix[0] + 1, ix[1] + 1
    return E.span_query(lines, s, e, q["file"], q["orig"]) or q


def _cs(tool, a):
    return f"{tool}(" + ", ".join(f"{k}={json.dumps(v)}" for k, v in (a or {}).items()) + ")"


def lake_label(q):
    k = q["kind"]
    if k == "listing":
        what = []
        if q["present"]:
            what.append("presence of the entries used later")
        if q["latest"] or q["earliest"]:
            what.append("newest/oldest entry of the series used")
        if q["count"]:
            what.append("number of entries of the series")
        return _cs(q["tool"], q["args"]) + f"  [anchored: {', '.join(what) or 'nothing used'}]"
    if k == "role":
        return (_cs(q["tool"], dict(q["args"], file=f"<newest file matching {q['series']}>")) +
                f"  [anchored by role: at the earlier snapshot this was {q['orig_file']}]")
    if k == "call":
        return _cs(q["tool"], q["args"])
    if k == "file":
        return _cs(q["tool"], q["args"])
    if k == "sql":
        return _cs("sql", {"query": q["query"]})
    first = q["first"].strip()[:60]
    last = "end of file" if q["last"] is None else q["last"].strip()[:60]
    return f'read_text(file={json.dumps(q["file"])}) span anchored on content: from `{first}` to `{last}`'


# ---------------------------------------------------------------- facts + truth
def _real_truth(lk, facts):
    """Oracle series (s0 + FUTURE) of every fact on a lake variant, via facts_dl.oracle (exact per-file profiles)."""
    P = F.Profiles(lk.name)
    P.save = lambda: None               # never write the shared profile cache on D:
    worlds = [lk.world(s) for s in [lk.s0] + lk.future]
    memo, out = {}, {}
    for f in facts:
        out[f["id"]] = F.series(lk, {"lake": f["lake"], "type": f["type"], "args": f["args"]}, P, worlds, memo)
    return out


def load_facts(lake, variant, cache_dir):
    d = json.loads((DL / f"facts_{lake}.json").read_text())
    raw = d["facts"]
    lk = VariantLake(lake, variant)
    cp = Path(cache_dir) / f"truth_{lake}_{variant}.json"
    if cp.exists():
        tr = json.loads(cp.read_text())
    elif variant == "synth":
        import pandas as pd
        o = pd.read_parquet(DL / "oracle" / f"oracle_{lake}.parquet")
        o = o[o.phase != "history"].sort_values(["fact_id", "window_idx"])
        tr = {fid: [str(x) for x in g.value] for fid, g in o.groupby("fact_id")}
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(tr))
    else:
        tr = _real_truth(lk, raw)
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(tr))
    facts = []
    for f in raw:
        truth = tr[f["id"]]
        assert len(truth) == len(lk.future) + 1, (f["id"], len(truth))
        facts.append({"iid": f["id"], "lake": lake, "slice": lake, "unit": lake, "repo": lake, "type": f["type"],
                      "subset": "natural" if f["subset"] == "natural" else "enriched", "subset_raw": f["subset"],
                      "question": f["question"], "args": f["args"], "K_oracle": truth[0], "K_oracle_synth": f["K_oracle"],
                      "truth": truth, "valid0": [v == truth[0] for v in truth[1:]]})
    return facts, lk


class DataLakeEnv(Environment):
    name = "datalake"
    tool_names = TOOL_NAMES
    tool_set = set(L.TOOLS)
    llmdiff_listings = True
    tool_api_doc = "\n".join(f"- {n}({', '.join(p)}): {d}" for n, d, p, _ in L.TOOL_SCHEMAS)

    def __init__(self, lake, variant="real", facts=None, lk=None, cache_dir=None, none_hint=True):
        self.lake_name, self.variant, self.none_hint = lake, variant, none_hint
        if facts is None:
            facts, lk = load_facts(lake, variant, cache_dir)
        self._facts, self.lk = facts, lk
        self.domain = DESC[lake]
        self.cert_subject = DESC[lake]
        self._worlds = {}
        self._ocache = {}

    def facts(self):
        return self._facts

    def n_steps(self):
        return len(self.lk.future)

    def world_t(self, t):
        w = self._worlds.get(t)
        if w is None:
            w = self.lk.world(self.lk.s0 if t == 0 else self.lk.future[t - 1])
            self._worlds[t] = w
        return w

    def world(self, fact, t):
        return self.world_t(t)

    def truth(self, fact, t):
        return fact["truth"][t]

    def answer_matches(self, fact, answer, value):
        if answer is None:
            return False
        try:
            return F.canon(fact, str(answer)) == value
        except Exception:
            return False

    def answers_agree(self, fact, a, b):
        if a is None or b is None:
            return False
        try:
            return F.canon(fact, str(a)) == F.canon(fact, str(b))
        except Exception:
            return False

    # ---- tools and evidence
    def run_call(self, world, call):
        return L.run_tool(world, call["tool"], call.get("args") or {})

    def anchor_call(self, world0, call, cites, mode):
        return lake_anchor(world0, call, mode)

    def anchor_calls(self, world0, calls, cites, mode, K=None, question=None):
        return lake_anchor_trace(world0, calls, mode, K, question)

    def observe(self, world, query):
        """lake_observe, memoised by the query and the exact file versions / listing it depends on (zero LLM)."""
        try:
            dep = self._deps(world, query)
        except Exception:
            dep = None
        if dep is None:
            return lake_observe(world, query)
        k = (E.qkey(query), dep)
        o = self._ocache.get(k)
        if o is None:
            o = lake_observe(world, query)
            self._ocache[k] = o
        return o

    def _deps(self, w, q):
        k = q["kind"]
        if k in ("listing",):
            return ("list", hashlib.sha1("\n".join(sorted(w.paths())).encode()).hexdigest())
        if k == "role":
            mem = series_members(w, q["series"])
            return ("role", mem[-1] if mem else None, w.sha(mem[-1]) if mem else None)
        if k == "sql":
            try:
                _, files = L.sql_resolve(w, _sql_rewrite(w, q["query"]))
            except ValueError:
                return None
            return tuple((f, w.sha(f)) for f in files)
        if k == "file":
            fs = resolve(w, q["args"].get("file", ""))
            return ("file",) + tuple((f, w.sha(f)) for f in fs)
        if k == "span":
            fs = resolve(w, q["file"])
            return ("span",) + tuple((f, w.sha(f)) for f in fs)
        tool, a = q["tool"], q["args"]
        if tool in ("ls", "find"):
            return ("list", hashlib.sha1("\n".join(sorted(w.paths())).encode()).hexdigest())
        if tool == "grep":
            return ("grep",) + tuple(sorted((p, w.sha(p)) for p in w.paths()
                                            if Path(p).suffix in (".txt", ".md", ".csv") and not F.BB_RX.search(p)))
        if tool in ("file_schema", "file_rowcount", "file_stats", "head", "read_text"):
            f = L._norm_path(a.get("file", ""))
            return ("f", f, w.sha(f))
        if tool == "schema_diff":
            fa, fb = resolve(w, a.get("file_a", "")), resolve(w, a.get("file_b", ""))
            return ("sd",) + tuple((f, w.sha(f)) for f in fa + fb)
        return None

    def reanchor(self, world, query):
        return lake_reanchor(world, query)

    def query_label(self, query):
        return lake_label(query)

    def cite_texts(self, fact, cites):
        return [str(c.get("line", "")).strip() for c in cites if str(c.get("line", "")).strip()]

    def auto_cites(self, fact, trace, answer):
        """Zero-LLM citations: output lines of the trace that contain the answer (or one of its items)."""
        if not answer:
            return []
        parts = [p.strip().strip("'\"`") for p in re.split(r"[,|\n]", str(answer))]
        parts = [p for p in parts if len(p) >= 3][:8] or ([str(answer).strip()] if str(answer).strip() else [])
        out, seen = [], set()
        for c in trace:
            for l in L.normalise(c["tool"], c.get("out") or "").split("\n"):
                s = l.strip()
                if s and s not in seen and any(p in s for p in parts):
                    seen.add(s)
                    out.append({"file": "", "line": s[:300]})
                    if len(out) >= 8:
                        return out
        return out

    # ---- baselines: manifest read set (files + consulted listings)
    def read_set(self, trace, world=None, listings=False):
        """Files the trace read (sql literals / globs resolved in `world`).  listings=True adds the listings it consulted
        (find globs, ls directories, sql globs, grep scopes) as items whose hash is the sorted (path, sha) listing."""
        w = world if world is not None else self.world_t(0)
        rs = set()
        for c in trace:
            a = c.get("args") or {}
            if not listings:
                if c["tool"] not in ("find", "ls", "grep"):
                    rs |= {p for p in L.files_touched(c["tool"], a, c.get("out") or "", w) if p}
                elif c["tool"] == "grep":
                    rs |= {p for p in L.files_touched(c["tool"], a, c.get("out") or "", w) if p}
                continue
            if c["tool"] == "find":
                rs.add("glob:" + str(a.get("glob", "*")))
            elif c["tool"] == "ls":
                rs.add("dir:" + L._norm_path(a.get("path", ".")))
            elif c["tool"] == "sql":
                for m in L._LIT.finditer(str(a.get("query", ""))):
                    s = m.group(1)
                    if L._looks_like_path(s) and any(ch in s for ch in "*?["):
                        rs.add("glob:" + L._norm_path(s))
            elif c["tool"] == "grep":
                rs.add("dir:" + L._norm_path(a.get("path", ".")) + "|grep")
            rs |= {p for p in L.files_touched(c["tool"], a, c.get("out") or "", w) if p}
        return sorted(rs)

    def _listing(self, world, item):
        if item.startswith("glob:"):
            g = item[5:]
            return sorted((p, world.sha(p)) for p in world.paths() if L._glob_match(p, g) or
                          (("/" in g) and __import__("fnmatch").fnmatch(p, g)))
        if item.startswith("dir:"):
            d = item[4:].split("|")[0]
            return sorted((p, world.sha(p)) for p in world.paths() if not d or p.startswith(d + "/"))
        return None

    def item_hash(self, world, item, kind="file"):
        lst = self._listing(world, item)
        if lst is None:
            return world.sha(item)
        return hashlib.sha1(json.dumps(lst).encode()).hexdigest()[:16]

    def readset_diff(self, wa, wb, items, cap=8000):
        """Manifest diff of the read set: added / removed / replaced files (with row counts and schema differences);
        unified diffs for text files (docs, lookup tables)."""
        parts = []
        files = set()
        for it in items:
            lst_a, lst_b = self._listing(wa, it), self._listing(wb, it)
            if lst_a is None:
                files.add(it)
                continue
            da, db = dict(lst_a), dict(lst_b)
            add = sorted(set(db) - set(da))
            rem = sorted(set(da) - set(db))
            if add or rem:
                parts.append(f"listing {it}: " + "; ".join([f"+ {p} ({self._rows(wb, p)})" for p in add[:40]] +
                                                          [f"- {p}" for p in rem[:40]]))
            files |= {p for p in set(da) & set(db) if da[p] != db[p]}
        for p in sorted(files):
            sa, sb = wa.sha(p), wb.sha(p)
            if sa == sb:
                continue
            if sb is None:
                parts.append(f"--- {p}\n+++ (file removed)")
                continue
            if sa is None:
                parts.append(f"+++ {p} (new file, {self._rows(wb, p)})")
                continue
            if Path(p).suffix in L.TEXT_EXT and not re.search(r"\d{4}-\d{2}-\d{2}\.csv$", p):
                parts.append("".join(difflib.unified_diff((wa.text(p) or "").splitlines(True), (wb.text(p) or "").splitlines(True),
                                                          f"a/{p}", f"b/{p}", n=2)))
            else:
                sd = ""
                try:
                    if (L.schema_of(wa, p) or []) != (L.schema_of(wb, p) or []):
                        sd = "; schema: " + L.t_schema_diff(_Two(wa, wb, p), "A", "B").replace("\n", "; ")
                except Exception:
                    pass
                parts.append(f"~ {p} replaced (rows {self._rows(wa, p)} -> {self._rows(wb, p)}{sd})")
        s = "\n".join(parts)
        full = len(s)
        if len(s) > cap:
            s = s[:cap] + f"\n[... diff truncated, {len(s) - cap} more chars]"
        return s, full

    @staticmethod
    def _rows(w, p):
        try:
            return f"{L.rowcount_of(w, p)} rows" if p.endswith((".parquet", ".csv")) else "text"
        except Exception:
            return "?"

    # ---- derivation agent
    def derive(self, fact, t, model=llm.Q27, tag="dl_derive"):
        w = self.world_t(t)
        sysmsg = SYS.format(desc=DESC[self.lake_name], budget=BUDGET_TXT[self.lake_name])
        if self.none_hint:
            sysmsg += NONE_HINT
        msgs = [{"role": "system", "content": sysmsg}, {"role": "user", "content": fact["question"]}]
        tools = L.openai_tools([ANSWER_TOOL])
        trace, answer, ntok, nllm, nnew = [], None, [0, 0], 0, 0
        for step in range(MAX_CALLS + 2):
            try:
                r = llm.chat(model, msgs, tools=tools, max_tokens=3000, tag=tag)
            except llm.ServerParseError:
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
                    out = L.run_tool(w, x["name"], args)
                    trace.append({"tool": x["name"], "args": args, "out": out})
                msgs.append({"role": "tool", "tool_call_id": x["id"], "content": out})
            if answer is not None:
                break
        return {"trace": trace, "answer": answer, "tokens": ntok, "n_llm": nllm, "n_new": nnew}


class _Two:
    """Minimal world pair for t_schema_diff between two snapshots' versions of one file."""

    def __init__(self, wa, wb, p):
        self.tree = {"A": wa.tree[p], "B": wb.tree[p]}
        self._w = {"A": (wa, p), "B": (wb, p)}
        self.lake = wa.lake

    def sha(self, k):
        w, p = self._w[k]
        return w.sha(p)

    def local(self, k):
        w, p = self._w[k]
        return w.local(p)


def attach_s0(facts, ders, env):
    """Fill the s0 derivation into each fact; return the kept facts (s0 answer matches the oracle)."""
    kept = []
    for f in facts:
        r = ders.d.get((f["iid"], 0))
        f["s0"] = r
        if r is None:
            f["s0_status"] = "missing"
            continue
        ok = bool(r["answer"] is not None and env.answer_matches(f, r["answer"], f["truth"][0]))
        f["s0_status"] = "correct" if ok else ("no_answer" if r["answer"] is None else "wrong")
        if not ok:
            continue
        g = dict(f)
        g["K"] = str(r["answer"]).strip()
        g["trace"] = r["trace"]
        g["derive_tokens"] = r["tokens"]
        g["cite"] = env.auto_cites(g, r["trace"], g["K"])
        g["valid"] = [env.answer_matches(g, g["K"], g["truth"][t]) for t in range(1, len(g["truth"]))]
        g["certzs"], g["certv0"] = [], None
        kept.append(g)
    return kept
