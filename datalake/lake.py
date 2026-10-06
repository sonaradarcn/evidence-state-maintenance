"""Data-lake environment: snapshots over a content-addressed store + deterministic, size-capped tools.

Mirrors pilot3/vfs.py so the same maintenance method can be plugged in:
    lake = Lake("tlc")                      # or "bb"
    lake.commits / lake.snapshots           # ordered snapshot ids  (HISTORY .. s0 .. FUTURE window)
    lake.s0, lake.history, lake.future      # like Repo
    w = lake.world(snap)                    # World: {logical_path: (sha256, is_text)}
    run_tool(w, name, args) -> str          # same signature as vfs.run_tool
    normalise(name, out), files_touched(name, args, out, w)  # read-set helpers
    openai_tools()                          # function-calling schemas
A snapshot = the manifest of file versions present after one lake event (file arrival, correction, doc update, ...).
"""
import fnmatch, json, os, re, threading
from pathlib import Path

DATA = Path(os.environ.get("ESM_LAKE_DATA", Path(__file__).resolve().parents[1] / "datalake_data"))
STORE = DATA / "store"
SNAPS = DATA / "snapshots"
MAX_OUT = 4000
TEXT_EXT = {".txt", ".md", ".csv", ".json"}
# sql() budget: a single call may touch at most this many files / catalogue rows (per lake)
SQL_BUDGET = {"tlc": {"max_files": 3, "max_rows": 1_200_000}, "bb": {"max_files": 10, "max_rows": 120_000}}
SQL_TIMEOUT_S = 30

_duck_local = threading.local()


def duck():
    con = getattr(_duck_local, "con", None)
    if con is None:
        import duckdb
        con = duckdb.connect()
        con.execute("SET enable_progress_bar=false; SET threads=4")
        _duck_local.con = con
    return con


def blob_path(sha, logical):
    return STORE / sha[:2] / f"{sha}{Path(logical).suffix}"


class Lake:
    def __init__(self, name):
        self.name = name
        d = json.loads((SNAPS / f"{name}.json").read_text())
        self.meta = d
        self.events = d["events"]                      # one per snapshot, in order
        self.rows = d.get("rows", {})                  # sha -> row count (catalogue metadata)
        self.all_snapshots = [e["snap"] for e in self.events]
        trees, cur = {}, {}
        for e in self.events:
            for p in e.get("remove", []):
                cur.pop(p, None)
            for p, sha in e.get("put", {}).items():
                cur[p] = sha
            trees[e["snap"]] = {p: (s, Path(p).suffix in TEXT_EXT) for p, s in cur.items()}
        self.trees = trees
        self.s0_idx_all = d["s0_index"]
        h0 = d["history_start_index"]
        self.commits = self.all_snapshots[h0:]          # HISTORY + s0 + FUTURE (vfs-compatible name)
        self.snapshots = self.commits
        self.s0_idx = self.s0_idx_all - h0
        self.s0 = self.commits[self.s0_idx]
        self.history = self.commits[:self.s0_idx]
        self.future = self.commits[self.s0_idx + 1:]
        self.event_of = {e["snap"]: e for e in self.events}

    def list_snapshots(self, scope="window"):
        return list(self.all_snapshots if scope == "all" else self.commits)

    def world(self, snap, overlay=None):
        return World(self, snap, overlay)


class World:
    def __init__(self, lake, snap, overlay=None):
        self.lake, self.repo, self.commit = lake, lake, snap
        self.tree = dict(lake.trees[snap])
        self.overlay = {}
        if overlay:   # {logical_path: sha or None}  (sha must exist in the store)
            for p, s in overlay.items():
                if s is None:
                    self.tree.pop(p, None)
                else:
                    self.tree[p] = (s, Path(p).suffix in TEXT_EXT)

    def sha(self, p):
        e = self.tree.get(p)
        return e[0] if e else None

    def local(self, p):
        s = self.sha(p)
        return None if s is None else blob_path(s, p)

    def paths(self):
        return self.tree.keys()

    def text(self, p):
        lp = self.local(p)
        return None if lp is None else _read_text_cached(self.sha(p), lp)


_text_cache = {}


def _read_text_cached(sha, lp):
    t = _text_cache.get(sha)
    if t is None:
        t = lp.read_bytes().decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
        if len(_text_cache) > 64:
            _text_cache.clear()
        _text_cache[sha] = t
    return t


# ---------------------------------------------------------------- helpers
def _norm_path(p):
    p = (p or ".").replace("\\", "/").strip().strip("'\"")
    while p.startswith("./"):
        p = p[2:]
    p = p.strip("/")
    return "" if p in (".", "") else p


def _trunc(s):
    if len(s) > MAX_OUT:
        return s[:MAX_OUT] + f"\n[... truncated {len(s) - MAX_OUT} chars]"
    return s


def _glob_match(path, g):
    if not g:
        return True
    g = g.replace("\\", "/")
    if "/" not in g:
        return fnmatch.fnmatch(path.rsplit("/", 1)[-1], g)
    return fnmatch.fnmatch(path, g) or fnmatch.fnmatch(path, g.replace("**/", ""))


def _need(w, file):
    f = _norm_path(file)
    if f not in w.tree:
        raise FileNotFoundError(f"no such file: {file}")
    return f


_schema_cache, _rows_cache = {}, {}


def schema_of(w, f):
    """[(name, type)] -- Parquet: Arrow schema; CSV: DuckDB type inference over the whole file."""
    sha = w.sha(f)
    k = sha
    if k in _schema_cache:
        return _schema_cache[k]
    lp = w.local(f)
    if f.endswith(".parquet"):
        import pyarrow.parquet as pq
        s = [(x.name, str(x.type)) for x in pq.ParquetFile(lp).schema_arrow]
    elif f.endswith(".csv"):
        r = duck().execute(f"DESCRIBE SELECT * FROM read_csv('{lp.as_posix()}', sample_size=-1, header=true)").fetchall()
        s = [(x[0], x[1]) for x in r]
    else:
        s = None
    _schema_cache[k] = s
    return s


def rowcount_of(w, f):
    sha = w.sha(f)
    if sha in _rows_cache:
        return _rows_cache[sha]
    if sha in w.lake.rows:
        n = w.lake.rows[sha]
    else:
        lp = w.local(f)
        if f.endswith(".parquet"):
            import pyarrow.parquet as pq
            n = pq.ParquetFile(lp).metadata.num_rows
        else:
            n = max(0, len([x for x in w.text(f).split("\n") if x]) - 1)
    _rows_cache[sha] = n
    return n


# ---------------------------------------------------------------- tools
def t_ls(w, path="."):
    scope = _norm_path(path)
    entries = {}
    for p in w.paths():
        if scope and not p.startswith(scope + "/"):
            continue
        rest = p[len(scope) + 1:] if scope else p
        head = rest.split("/", 1)[0]
        if "/" in rest:
            entries[head + "/"] = entries.get(head + "/", 0) + 1
        else:
            entries[head] = None
    if not entries:
        return f"error: no such directory: {path}"
    lines = [f"{k}  ({v} files)" if v else k for k, v in sorted(entries.items())]
    if len(lines) > 200:
        lines = lines[:200] + [f"... ({len(entries) - 200} more entries)"]
    return _trunc("\n".join(lines))


def t_find(w, glob="*"):
    m = sorted(p for p in w.paths() if _glob_match(p, glob))
    if not m:
        return "(no matches)"
    if len(m) > 150:
        return _trunc("\n".join(m[:150]) + f"\n... ({len(m) - 150} more)")
    return _trunc("\n".join(m))


def t_file_schema(w, file):
    f = _need(w, file)
    s = schema_of(w, f)
    if s is None:
        return "error: not a tabular file (use read_text)"
    kind = "parquet (arrow types)" if f.endswith(".parquet") else "csv (types inferred by DuckDB over the whole file)"
    return _trunc(f"# {f}: {len(s)} columns, {kind}\n" + "\n".join(f"{n}: {t}" for n, t in s))


def t_head(w, file, n=5):
    f = _need(w, file)
    n = max(1, min(int(n or 5), 20))
    if f.endswith(".parquet"):
        import pyarrow.parquet as pq, pyarrow.csv as pacsv, io
        pf = pq.ParquetFile(w.local(f))
        if pf.metadata.num_row_groups == 0 or pf.metadata.num_rows == 0:
            return "(0 rows) " + ",".join(pf.schema_arrow.names)
        t = next(pf.iter_batches(batch_size=n))
        buf = io.BytesIO()
        pacsv.write_csv(t.slice(0, n), buf)
        return _trunc(buf.getvalue().decode())
    txt = w.text(f)
    return _trunc("\n".join(txt.split("\n")[:n + 1]))


def t_file_rowcount(w, file):
    f = _need(w, file)
    if not (f.endswith(".parquet") or f.endswith(".csv")):
        return "error: not a tabular file"
    return str(rowcount_of(w, f))


def t_file_stats(w, file, column):
    f = _need(w, file)
    if f.endswith(".parquet"):
        import pyarrow.parquet as pq
        pf = pq.ParquetFile(w.local(f))
        names = pf.schema_arrow.names
        if column not in names:
            return f"error: column {column} not in {f}"
        md = pf.metadata
        ci = pf.schema_arrow.get_field_index(column)
        mins, maxs, nulls, ok = [], [], 0, True
        for i in range(md.num_row_groups):
            st = md.row_group(i).column(ci).statistics
            if st is None:
                ok = False
                break
            nulls += st.null_count if st.has_null_count else 0
            if st.has_min_max:
                mins.append(st.min)
                maxs.append(st.max)
        if ok:
            mn = min(mins) if mins else None
            mx = max(maxs) if maxs else None
            return f"column {column} ({md.num_rows} rows, from parquet metadata): min={mn} max={mx} null_count={nulls}"
    elif not f.endswith(".csv"):
        return "error: not a tabular file"
    cols = [n for n, _ in schema_of(w, f)]
    if column not in cols:
        return f"error: column {column} not in {f}"
    reader = f"read_parquet('{w.local(f).as_posix()}')" if f.endswith(".parquet") else \
        f"read_csv('{w.local(f).as_posix()}', sample_size=-1, header=true)"
    r = duck().execute(f'SELECT min("{column}"), max("{column}"), count(*) - count("{column}"), count(*) FROM {reader}').fetchone()
    return f"column {column} ({r[3]} rows, computed by scanning this one file): min={r[0]} max={r[1]} null_count={r[2]}"


def t_read_text(w, file, start=1, end=None):
    f = _need(w, file)
    if Path(f).suffix not in TEXT_EXT:
        return "error: binary file (use head / file_schema)"
    lines = w.text(f).split("\n")
    start = max(1, int(start or 1))
    end = int(end) if end else start + 119
    end = min(end, start + 199, len(lines))
    return _trunc("\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1)))


def t_grep(w, pattern, path="."):
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return f"error: bad regex: {e}"
    scope = _norm_path(path)
    files = [scope] if scope in w.tree else sorted(p for p in w.paths() if (not scope or p.startswith(scope + "/")))
    files = [p for p in files if Path(p).suffix in (".txt", ".md") or (p.endswith(".csv") and "lookup" in p)]
    out = []
    for p in files:
        for i, line in enumerate(w.text(p).split("\n"), 1):
            if rx.search(line):
                out.append(f"{p}:{i}:{line.strip()[:200]}")
    if not out:
        return "(no matches)"
    if len(out) > 60:
        out = out[:60] + [f"... ({len(out) - 60} more matches)"]
    return _trunc("\n".join(out))


def t_schema_diff(w, file_a, file_b):
    a, b = _need(w, file_a), _need(w, file_b)
    sa, sb = schema_of(w, a), schema_of(w, b)
    if sa is None or sb is None:
        return "error: not a tabular file"
    da, db = dict(sa), dict(sb)
    out = []
    added = [c for c in db if c not in da]
    removed = [c for c in da if c not in db]
    lower_a = {c.lower(): c for c in removed}
    for c in added:
        if c.lower() in lower_a:
            out.append(f"renamed (case only): {lower_a[c.lower()]} -> {c}  [{da[lower_a[c.lower()]]} -> {db[c]}]")
    ren = {l for l in lower_a if any(c.lower() == l for c in added)}
    out += [f"added: {c}: {db[c]}" for c in added if c.lower() not in ren]
    out += [f"removed: {c}: {da[c]}" for c in removed if c.lower() not in ren]
    out += [f"type changed: {c}: {da[c]} -> {db[c]}" for c in db if c in da and da[c] != db[c]]
    if [c for c in sa if c in db] != [c for c in sb if c in da]:
        out.append("column order changed")
    return _trunc("\n".join(out) or "(identical schemas)")


_FORBID = re.compile(r"\b(attach|copy|export|import|install|load|pragma|set|reset|create|insert|update|delete|drop|alter|call|"
                     r"read_text|read_blob|read_json\w*|glob|checkpoint|detach|use|vacuum|getenv)\b", re.I)
_LIT = re.compile(r"'((?:[^']|'')*)'")


def _looks_like_path(s):
    return "/" in s or "\\" in s or re.search(r"\.(parquet|csv|txt|json|zip|gz)$", s, re.I) is not None


def sql_resolve(w, query):
    """Rewrite logical file literals to store paths; returns (sql, [logical files]) or raises ValueError."""
    if ";" in query.strip().rstrip(";"):
        raise ValueError("only a single statement is allowed")
    if _FORBID.search(query) or re.search(r"(https?|s3|gcs|file)://", query, re.I):
        raise ValueError("statement type / function not allowed (read-only SELECT over lake files only)")
    files = []

    def sub(m):
        s = m.group(1).replace("''", "'")
        if not _looks_like_path(s):
            return m.group(0)
        p = _norm_path(s)
        if any(ch in p for ch in "*?["):
            hits = sorted(x for x in w.paths() if fnmatch.fnmatch(x, p))
            if not hits:
                raise ValueError(f"glob matches no file: {s}")
            files.extend(hits)
            return "[" + ", ".join("'" + w.local(x).as_posix() + "'" for x in hits) + "]"
        if p not in w.tree:
            raise ValueError(f"no such file: {s}")
        files.append(p)
        return "'" + w.local(p).as_posix() + "'"

    q = _LIT.sub(sub, query.strip().rstrip(";"))
    if not files:
        raise ValueError("the query must read at least one lake file given as a quoted path literal")
    return q, sorted(set(files))


def t_sql(w, query):
    try:
        q, files = sql_resolve(w, query)
    except ValueError as e:
        return f"error: {e}"
    bud = SQL_BUDGET[w.lake.name]
    rows = sum(rowcount_of(w, f) for f in files if f.endswith((".parquet", ".csv")))
    if len(files) > bud["max_files"] or rows > bud["max_rows"]:
        return (f"error: scan budget exceeded ({len(files)} files / {rows} rows; limit {bud['max_files']} files / "
                f"{bud['max_rows']} rows per call)")
    con = duck()
    timer = threading.Timer(SQL_TIMEOUT_S, con.interrupt)
    timer.start()
    try:
        cur = con.execute(q)
        cols = [d[0] for d in cur.description]
        res = cur.fetchmany(51)
    except Exception as e:
        msg = str(e).split("\n")[0]
        for f in files:
            msg = msg.replace(w.local(f).as_posix(), f)
        return f"error: {type(e).__name__}: {msg[:500]}"
    finally:
        timer.cancel()
    lines = ["\t".join(cols)] + ["\t".join("NULL" if v is None else str(v) for v in r) for r in res[:50]]
    if len(res) > 50:
        lines.append("... (more rows; showing 50)")
    return _trunc("\n".join(lines))


TOOLS = {"ls": t_ls, "find": t_find, "file_schema": t_file_schema, "head": t_head, "file_rowcount": t_file_rowcount,
         "file_stats": t_file_stats, "sql": t_sql, "read_text": t_read_text, "grep": t_grep, "schema_diff": t_schema_diff}

TOOL_SCHEMAS = [
    ("ls", "List entries directly inside a lake directory (dirs end with / and show their file count).", {"path": "string"}, ["path"]),
    ("find", "List lake file paths matching a glob (a glob without '/' matches basenames, e.g. 'yellow_*.parquet').", {"glob": "string"}, ["glob"]),
    ("file_schema", "Column names and types of a Parquet (Arrow types) or CSV (DuckDB-inferred types) file.", {"file": "string"}, ["file"]),
    ("head", "First n rows (n <= 20) of a tabular file, as CSV text.", {"file": "string", "n": "integer"}, ["file"]),
    ("file_rowcount", "Number of data rows of a tabular file (from metadata / catalogue, no scan).", {"file": "string"}, ["file"]),
    ("file_stats", "min / max / null count of one column of one file (Parquet: from row-group metadata; CSV: single-file scan).", {"file": "string", "column": "string"}, ["file", "column"]),
    ("sql", "Run one read-only DuckDB SELECT. Reference lake files as quoted paths, e.g. SELECT count(*) FROM 'trip-data/x.parquet' "
            "or read_parquet('trip-data/yellow_*_2023-0[1-2].parquet'). Budget per call: few files / rows (see README). Max 50 result rows.",
     {"query": "string"}, ["query"]),
    ("read_text", "Read lines start..end (1-based, max 200) of a text file (docs, data dictionaries, lookup CSV).", {"file": "string", "start": "integer", "end": "integer"}, ["file"]),
    ("grep", "Regex search in documentation text files and lookup tables under path. Returns file:line:text (max 60).", {"pattern": "string", "path": "string"}, ["pattern", "path"]),
    ("schema_diff", "Compare the schemas of two tabular files: added / removed / renamed (case) / type-changed columns.", {"file_a": "string", "file_b": "string"}, ["file_a", "file_b"]),
]


def openai_tools(extra=()):
    out = []
    for name, desc, props, req in list(TOOL_SCHEMAS) + list(extra):
        out.append({"type": "function", "function": {"name": name, "description": desc, "parameters": {
            "type": "object", "properties": {k: {"type": v} for k, v in props.items()}, "required": req}}})
    return out


def tools(w):
    """Bound tool callables for a snapshot: tools(w)['ls'](path='.')."""
    import functools
    return {n: functools.partial(_bound, w, n) for n in TOOLS}


def _bound(w, name, **kw):
    return run_tool(w, name, kw)


def run_tool(w, name, args):
    fn = TOOLS.get(name)
    if fn is None:
        return f"error: unknown tool {name}"
    try:
        allowed = {k: v for k, v in (args or {}).items() if k in fn.__code__.co_varnames[1:fn.__code__.co_argcount]}
        return fn(w, **allowed)
    except FileNotFoundError as e:
        return f"error: {e}"
    except TypeError as e:
        return f"error: bad arguments: {e}"
    except Exception as e:
        return f"error: {type(e).__name__}: {str(e)[:300]}"


_LN = re.compile(r"^([^:\n]+):\d+:", re.M)
_LN_READ = re.compile(r"^\d+: ", re.M)


def normalise(name, out):
    if name == "grep":
        return _LN.sub(r"\1:", out)
    if name == "read_text":
        return _LN_READ.sub("", out)
    return out


def files_touched(name, args, out, w=None):
    a = args or {}
    fs = set()
    if name in ("file_schema", "head", "file_rowcount", "file_stats", "read_text") and a.get("file"):
        fs.add(_norm_path(a["file"]))
    elif name == "schema_diff":
        fs |= {_norm_path(a.get("file_a")), _norm_path(a.get("file_b"))}
    elif name == "grep":
        fs |= {m.group(1) for m in _LN.finditer(out)}
    elif name == "find":
        fs |= {l for l in out.split("\n") if l and not l.startswith(("...", "("))}
    elif name == "sql" and w is not None:
        try:
            fs |= set(sql_resolve(w, a.get("query", ""))[1])
        except ValueError:
            pass
    return fs
