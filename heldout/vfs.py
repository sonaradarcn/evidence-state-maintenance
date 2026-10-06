"""Virtual file system over git objects + deterministic tools.

A Repo exposes the first-parent commit list; World(commit) gives a {path: blob_sha} map
plus a text reader.  Overlay worlds (for perturbation counter-examples) are supported
by passing an override {path: text or None}.
"""
import ast, fnmatch, hashlib, json, os, pickle, re, subprocess, configparser
from pathlib import Path
try:
    import tomli
except ImportError:  # Python >= 3.11
    import tomllib as tomli
import threading
_BLOB_LOCK = threading.Lock()

DATA = Path(os.environ.get("ESM_DEV_REPOS", Path(__file__).resolve().parents[1])) / "pilot3_data"
REPOS = DATA / "repos"
TEXT_EXT = {".py", ".pyi", ".toml", ".cfg", ".ini", ".txt", ".rst", ".md", ".yml", ".yaml", ".json", ".in"}
MAX_BLOB = 400_000
MAX_OUT = 4000
N_HIST, N_FUT = 300, 400


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout


class Repo:
    def __init__(self, name):
        self.name = name
        self.path = REPOS / name
        cache = DATA / "trees" / f"{name}.pkl"
        if cache.exists():
            d = pickle.loads(cache.read_bytes())
        else:
            commits = _git(self.path, "rev-list", "--first-parent", "--reverse", "HEAD").decode().split()
            n = len(commits)
            s0 = n - 1 - N_FUT
            sel = commits[s0 - N_HIST: n]
            trees = {}
            for c in sel:
                out = _git(self.path, "ls-tree", "-r", "-l", c).decode("utf-8", "replace")
                t = {}
                for line in out.splitlines():
                    meta, p = line.split("\t", 1)
                    mode, typ, sha, size = meta.split()
                    if typ != "blob":
                        continue
                    if Path(p).suffix not in TEXT_EXT or size == "-" or int(size) > MAX_BLOB:
                        t[p] = (sha, False)   # present but not text-searchable
                    else:
                        t[p] = (sha, True)
                trees[c] = t
            d = {"commits": sel, "trees": trees}
            cache.parent.mkdir(exist_ok=True)
            cache.write_bytes(pickle.dumps(d))
        self.commits = d["commits"]          # HISTORY(300) + s0 + FUTURE(400)
        self.trees = d["trees"]
        self.s0_idx = N_HIST
        self.s0 = self.commits[N_HIST]
        self.history = self.commits[:N_HIST]
        self.future = self.commits[N_HIST + 1:]
        self._blobs = {}
        self._proc = None

    def blob(self, sha):
        b = self._blobs.get(sha)
        if b is not None:
            return b
        with _BLOB_LOCK:
            if self._proc is None:
                self._proc = subprocess.Popen(["git", "-C", str(self.path), "cat-file", "--batch"],
                                              stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            self._proc.stdin.write((sha + "\n").encode()); self._proc.stdin.flush()
            header = self._proc.stdout.readline().split()
            size = int(header[2])
            data = self._proc.stdout.read(size); self._proc.stdout.read(1)
            b = data.decode("utf-8", "replace").replace("\r\n", "\n")
            self._blobs[sha] = b
        return b

    def world(self, commit, overlay=None):
        return World(self, commit, overlay)


class World:
    def __init__(self, repo, commit, overlay=None):
        self.repo, self.commit = repo, commit
        self.tree = dict(repo.trees[commit])
        self.overlay = {}
        if overlay:
            for p, txt in overlay.items():
                if txt is None:
                    self.tree.pop(p, None)
                else:
                    h = "ov:" + hashlib.sha1(txt.encode()).hexdigest()
                    self.tree[p] = (h, True)
                    self.overlay[h] = txt

    def sha(self, p):
        e = self.tree.get(p)
        return e[0] if e else None

    def text(self, p):
        e = self.tree.get(p)
        if e is None:
            return None
        if e[0].startswith("ov:"):
            return self.overlay[e[0]]
        return self.repo.blob(e[0])

    def paths(self):
        return self.tree.keys()

# ---------------------------------------------------------------- tools

def _norm_path(p):
    p = (p or ".").replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    p = p.strip("/")
    return "" if p in (".", "") else p


def _in_scope(path, scope):
    return scope == "" or path == scope or path.startswith(scope + "/")


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


_grep_cache = {}
_ast_cache = {}


def _parse(w, f):
    s = w.sha(f)
    if s is None:
        return None
    if s not in _ast_cache:
        try:
            _ast_cache[s] = (ast.parse(w.text(f)), w.text(f))
        except Exception:
            _ast_cache[s] = None
    return _ast_cache[s]


def _file_grep(w, p, rx_src, rx):
    sha = w.sha(p)
    k = (rx_src, sha)
    r = _grep_cache.get(k)
    if r is None:
        r = []
        for i, line in enumerate(w.text(p).split("\n"), 1):
            if rx.search(line):
                r.append((i, line.strip()[:200]))
        _grep_cache[k] = r
    return r


def t_ls(w, path="."):
    scope = _norm_path(path)
    entries = set()
    for p in w.paths():
        if scope and not p.startswith(scope + "/"):
            continue
        rest = p[len(scope) + 1:] if scope else p
        entries.add(rest.split("/", 1)[0] + ("/" if "/" in rest else ""))
    if not entries:
        return f"error: no such directory: {path}"
    return _trunc("\n".join(sorted(entries)))


def t_find(w, glob="*"):
    m = sorted(p for p in w.paths() if _glob_match(p, glob))
    if not m:
        return "(no matches)"
    if len(m) > 150:
        return _trunc("\n".join(m[:150]) + f"\n... ({len(m) - 150} more)")
    return _trunc("\n".join(m))


def _grep_iter(w, pattern, path, file_glob):
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return None, f"error: bad regex: {e}"
    scope = _norm_path(path)
    if scope and scope in w.tree:      # a single file
        files = [scope]
    else:
        files = sorted(p for p in w.paths() if _in_scope(p, scope) and w.tree[p][1] and _glob_match(p, file_glob))
    out = []
    for p in files:
        if not w.tree[p][1]:
            continue
        for i, line in _file_grep(w, p, pattern, rx):
            out.append((p, i, line))
    return out, None


def t_grep(w, pattern, path=".", file_glob=None):
    out, err = _grep_iter(w, pattern, path, file_glob)
    if err:
        return err
    if not out:
        return "(no matches)"
    lines = [f"{p}:{i}:{t}" for p, i, t in out[:60]]
    if len(out) > 60:
        lines.append(f"... ({len(out) - 60} more matches)")
    return _trunc("\n".join(lines))


def t_grep_count(w, pattern, path=".", file_glob=None):
    out, err = _grep_iter(w, pattern, path, file_glob)
    if err:
        return err
    per = {}
    for p, _, _ in out:
        per[p] = per.get(p, 0) + 1
    lines = [f"total: {len(out)}"] + [f"{p}: {n}" for p, n in sorted(per.items())]
    return _trunc("\n".join(lines))


def t_read(w, file, start=1, end=None):
    f = _norm_path(file)
    txt = w.text(f)
    if txt is None:
        return f"error: no such file: {file}"
    lines = txt.split("\n")
    start = max(1, int(start or 1))
    end = int(end) if end else start + 119
    end = min(end, start + 199, len(lines))
    return _trunc("\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1)))


def _find_node(tree, name):
    parts = name.split(".")
    body = tree.body
    node = None
    for k, part in enumerate(parts):
        node = None
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == part:
                node = n  # last definition wins (python semantics)
        if node is None:
            return None
        body = node.body if isinstance(node, ast.ClassDef) else []
    return node


def t_def_block(w, file, name):
    f = _norm_path(file)
    pr = _parse(w, f)
    if w.text(f) is None:
        return f"error: no such file: {file}"
    if pr is None:
        return "error: file does not parse"
    tree, src = pr
    node = _find_node(tree, name)
    if node is None:
        return f"error: {name} not found in {file}"
    lines = src.split("\n")
    s = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
    return _trunc("\n".join(lines[s:node.end_lineno]))


def t_list_defs(w, file):
    f = _norm_path(file)
    pr = _parse(w, f)
    if w.text(f) is None:
        return f"error: no such file: {file}"
    if pr is None:
        return "error: file does not parse"
    tree, _ = pr
    out = []
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(f"def {n.name}({ast.unparse(n.args)})")
        elif isinstance(n, ast.ClassDef):
            out.append(f"class {n.name}({', '.join(ast.unparse(b) for b in n.bases)})")
            for m in n.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append(f"    def {m.name}({ast.unparse(m.args)})")
    return _trunc("\n".join(out) or "(no defs)")


def _toml(w, f):
    txt = w.text(f)
    if txt is None:
        return None
    try:
        return tomli.loads(txt)
    except Exception:
        return "PARSE_ERROR"


def t_toml_get(w, file, key):
    d = _toml(w, _norm_path(file))
    if d is None:
        return f"error: no such file: {file}"
    if d == "PARSE_ERROR":
        return "error: toml parse error"
    cur = d
    for part in [k for k in re.split(r"\.(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", key) if k]:
        part = part.strip('"')
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return f"error: key not found: {key}"
    return _trunc(json.dumps(cur, indent=1, sort_keys=True))


def _ini(w, f):
    txt = w.text(f)
    if txt is None:
        return None
    cp = configparser.RawConfigParser(strict=False)
    try:
        cp.read_string(txt)
    except Exception:
        return "PARSE_ERROR"
    return cp


def t_ini_get(w, file, section, key):
    cp = _ini(w, _norm_path(file))
    if cp is None:
        return f"error: no such file: {file}"
    if cp == "PARSE_ERROR":
        return "error: ini parse error"
    if not cp.has_section(section) or not cp.has_option(section, key):
        return f"error: [{section}] {key} not found"
    return _trunc(cp.get(section, key).strip())


TOOLS = {"ls": t_ls, "find": t_find, "grep": t_grep, "grep_count": t_grep_count, "read": t_read,
         "def_block": t_def_block, "list_defs": t_list_defs, "toml_get": t_toml_get, "ini_get": t_ini_get}

TOOL_SCHEMAS = [
    ("ls", "List entries directly inside a directory (dirs end with /).", {"path": "string"}, ["path"]),
    ("find", "List file paths matching a glob (a glob without '/' matches basenames, e.g. '*.py' or 'test_*.py'; 'src/**/x.py' style allowed).", {"glob": "string"}, ["glob"]),
    ("grep", "Python-regex search in text files under path (dir or file). Optional file_glob filters files (e.g. '*.py'). Returns file:line:text (max 60 matches).", {"pattern": "string", "path": "string", "file_glob": "string"}, ["pattern", "path"]),
    ("grep_count", "Count regex-matching lines under path; returns total and per-file counts.", {"pattern": "string", "path": "string", "file_glob": "string"}, ["pattern", "path"]),
    ("read", "Read lines start..end (1-based, max 200 lines) of a file, prefixed by line numbers.", {"file": "string", "start": "integer", "end": "integer"}, ["file"]),
    ("def_block", "Source text of a top-level def/class or Class.method in a python file (via ast).", {"file": "string", "name": "string"}, ["file", "name"]),
    ("list_defs", "List top-level functions and classes (with methods and signatures) of a python file.", {"file": "string"}, ["file"]),
    ("toml_get", "Value of a dotted key in a TOML file, as JSON (e.g. key='project.requires-python').", {"file": "string", "key": "string"}, ["file", "key"]),
    ("ini_get", "Value of key in [section] of an INI/cfg file (setup.cfg, tox.ini).", {"file": "string", "section": "string", "key": "string"}, ["file", "section", "key"]),
]


def openai_tools(extra=()):
    out = []
    for name, desc, props, req in list(TOOL_SCHEMAS) + list(extra):
        out.append({"type": "function", "function": {"name": name, "description": desc, "parameters": {
            "type": "object", "properties": {k: {"type": v} for k, v in props.items()}, "required": req}}})
    return out


def run_tool(w, name, args):
    fn = TOOLS.get(name)
    if fn is None:
        return f"error: unknown tool {name}"
    try:
        allowed = {k: v for k, v in (args or {}).items() if k in fn.__code__.co_varnames[1:fn.__code__.co_argcount]}
        return fn(w, **allowed)
    except TypeError as e:
        return f"error: bad arguments: {e}"
    except Exception as e:
        return f"error: {type(e).__name__}: {e}"


_LN_GREP = re.compile(r"^([^:\n]+):\d+:", re.M)
_LN_READ = re.compile(r"^\d+: ", re.M)


def normalise(name, out):
    if name == "grep":
        return _LN_GREP.sub(r"\1:", out)
    if name == "read":
        return _LN_READ.sub("", out)
    return out


def files_touched(name, args, out):
    """Read-set contribution of a call: files read, plus files that appear in grep/find match output."""
    fs = set()
    a = args or {}
    if name in ("read", "def_block", "list_defs", "toml_get", "ini_get") and a.get("file"):
        fs.add(_norm_path(a["file"]))
    elif name in ("grep",):
        for m in _LN_GREP.finditer(out):
            fs.add(m.group(1))
        p = _norm_path(a.get("path"))
        if p and "." in p.rsplit("/", 1)[-1]:
            fs.add(p)
    elif name == "grep_count":
        for line in out.split("\n")[1:]:
            if ": " in line:
                fs.add(line.rsplit(": ", 1)[0])
    elif name == "find":
        for line in out.split("\n"):
            if line and not line.startswith("...") and not line.startswith("("):
                fs.add(line)
    return fs
