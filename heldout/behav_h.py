"""BEHAVIOUR held-out facts: "what does <expr> return?"; truth = executing <expr> in a subprocess (python -S -B, Python 3.14) with
PYTHONPATH = that commit's package files materialised from git blobs (+ a FIXED per-repo directory of released pure-Python
dependency wheels, identical for every commit).  'raises <Type>' is a value; NONE if the module import fails or the called attribute is
gone; per-call timeout 5 s.  Same value semantics as pilot6 (runner_h.py == pilot6/runner_exec.py for truth runs).

No LLM: candidate calls are generated programmatically at s0 from
  (a) docstring doctest examples (expressions after rewriting doctest-local imports / simple assignments / module globals to fully
      qualified names; `print(x)` -> `str(x)`), and
  (b) synthesised calls of public top-level functions, argument values from annotations / defaults / parameter-name heuristics.
Kept iff deterministic (same value twice in one process AND in a second process with a different PYTHONHASHSEED), fast (< 1 s),
literal-valued (else wrapped in list(...) for iterators or repr(...)), no memory addresses, <= 300 chars.

usage: python behav_h.py imports            # import smoke test at s0 / HEAD for all behaviour repos
       python behav_h.py cands <repo>       # candidates + s0 probe -> heldout_data/behav/<repo>.cands.json
       python behav_h.py truth <repo> [workers]  # truth series over 701 commits -> heldout_data/behav/<repo>.truth.json
       python behav_h.py select             # facts (enriched + natural) for all repos -> heldout_data/behav/behav_facts.json
"""
import ast, builtins, copy, doctest, hashlib, json, os, random, re, shutil, subprocess, sys, time
import concurrent.futures as cf
from collections import Counter, defaultdict
from pathlib import Path
import common_h as C
from common_h import vfs, FX

BDIR = C.DATA / "behav"
EXEC = C.DATA / "exec"
DEPS = C.DATA / "deps"
RUNNER = C.HERE / "runner_h.py"

# repo -> (import tops, fixed deps dir under heldout_data/deps).  Every deps dir holds a stub <dist>-0+heldout.dist-info (so code that
# calls importlib.metadata.version(<own dist>) imports) plus released dependency code, identical for all commits:
#   jinja: MarkupSafe 2.0.1 (pure-Python part of the sdist; s0 needs soft_unicode, removed in 2.1)   werkzeug: MarkupSafe 3.0.3
#   marshmallow: packaging 26.3   isort: mypy_extensions 1.1.0   rich: Pygments 2.21.0, markdown-it-py 4.2.0, mdurl 0.1.2
BEHAV = {
    "boltons": (["boltons"], "boltons"),
    "jinja": (["jinja2"], "jinja"),
    "werkzeug": (["werkzeug"], "werkzeug"),
    "marshmallow": (["marshmallow"], "marshmallow"),
    "isort": (["isort"], "isort"),
    "pygments": (["pygments"], "pygments"),
    "networkx": (["networkx"], "networkx"),
    "rich": (["rich"], "rich"),
    "poetry-core": (["poetry/core"], "poetry-core"),
}
SKIP_PARTS = ("_vendor", "vendored", "_vendored", "tests", "testing", "test", "conftest", "__main__", "benchmarks")
IMPURE = re.compile(r"\b(open|print|input|subprocess|socket|os\.|sys\.std|time\.|random\.|threading|Path\(|shutil|tempfile|"
                    r"getpass|webbrowser|signal|_winconsole|isatty|echo|secho|prompt|confirm|launch|edit\(|clear\(|get_terminal_size|"
                    r"sleep|exit|environ|locale|importlib|warnings\.warn)\b")          # pilot6's purity filter (function bodies)
IMPURE_EXPR = re.compile(r"\b(now|utcnow|today|random|uuid|time|sleep|open|os|sys|input|environ|getcwd|tempfile|id|hash|"
                         r"Console|console|print_|urandom|clock|monotonic|perf_counter|getrandbits|shuffle|choice|sample|"
                         r"gcutils|ecoutils|tbutils|debugutils|socketutils|fileutils|gc|inspect|traceback)\b")
ARTIFACT_RAISES = {"raises NameError", "raises ImportError", "raises ModuleNotFoundError", "raises AttributeError", "raises SyntaxError",
                   "raises RecursionError", "raises MemoryError"}


# ------------------------------------------------------------------ package layout / materialisation (pilot6 logic, generalised tops)
def pkg_files(w, name):
    out = {}
    for top in BEHAV[name][0]:
        inits = sorted((p for p in w.paths() if (p == f"{top}/__init__.py" or p.endswith(f"/{top}/__init__.py"))
                        and p[: -len(f"{top}/__init__.py")].count("/") <= 1), key=len)
        if not inits:
            continue
        pref = inits[0][: -len("__init__.py")]
        root = pref[: -len(top) - 1]
        for p in w.paths():
            if p.startswith(pref) and (p.endswith(".py") or p.endswith(".typed") or p.endswith(".pyi")):
                out[p[len(root):]] = p
        # namespace parents (e.g. poetry/ for poetry/core): nothing to add, implicit namespace packages work
    return out


def state_key(w, name):
    pf = pkg_files(w, name)
    return hashlib.sha1(json.dumps(sorted((k, w.sha(p)) for k, p in pf.items())).encode()).hexdigest()[:16], pf


def materialise(w, name, key=None, pf=None):
    if key is None:
        key, pf = state_key(w, name)
    d = EXEC / name / key
    if not (d / ".ok").exists():
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        for rel, p in pf.items():
            q = d / rel
            q.parent.mkdir(parents=True, exist_ok=True)
            q.write_text(w.text(p) or "", encoding="utf-8")
        d.mkdir(parents=True, exist_ok=True)
        (d / ".ok").write_text("ok")
    return key, d


def pythonpath(name, d):
    dep = BEHAV[name][1]
    parts = [str(d)]
    if dep:
        parts.append(str(DEPS / dep))
    return os.pathsep.join(parts)


def run_jobs(name, d, jobs, probe=False, seed="0", per_job_timeout=5):
    """Run jobs in fresh subprocess(es); restarts a new process after a timeout (the runner aborts remaining jobs then)."""
    env = dict(os.environ, PYTHONPATH=pythonpath(name, d), PYTHONIOENCODING="utf-8", PYTHONHASHSEED=seed)
    env.pop("PYTHONSTARTUP", None)
    res, todo = {}, list(jobs)
    while todo:
        payload = json.dumps([dict(j, timeout=per_job_timeout) for j in todo])
        try:
            p = subprocess.run([C.PY, "-S", "-B", "-W", "ignore", str(RUNNER)] + (["probe"] if probe else []), input=payload,
                               capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(d),
                               timeout=60 + per_job_timeout * 2 + 2 * len(todo))
            r = json.loads(p.stdout) if p.stdout.strip() else {}
        except Exception:
            r = {}
        if not r and len(todo) > 1:          # the whole process died (hard crash / exit): isolate the culprit, one job per process
            for j in todo:
                res.update(run_jobs(name, d, [j], probe, seed, per_job_timeout))
            return res
        nxt = []
        for j in todo:
            v = r.get(j["id"])
            vv = v.get("v") if (probe and isinstance(v, dict)) else v
            if vv == "RUNNER_ABORT":
                nxt.append(j)
            else:
                res[j["id"]] = v if v is not None else ({"v": "RUNNER_ERROR"} if probe else "RUNNER_ERROR")
        if len(nxt) == len(todo):      # no progress (should not happen) -> mark error
            for j in nxt:
                res[j["id"]] = {"v": "RUNNER_ERROR"} if probe else "RUNNER_ERROR"
            break
        todo = nxt
    return res


# ------------------------------------------------------------------ import smoke test
def cmd_imports():
    for name in BEHAV:
        repo = C.get_repo(name)
        for lab, cm in (("s0", repo.s0), ("head", repo.commits[-1]), ("hist0", repo.commits[0])):
            w = repo.world(cm)
            key, d = materialise(w, name)
            top = BEHAV[name][0][0].replace("/", ".")
            r = run_jobs(name, d, [{"id": "x", "module": top, "func": None, "expr": f"{top}.__name__"}], probe=True)
            print(name, lab, key, len(state_key(w, name)[1]), "files", r["x"].get("v"), r["x"].get("why", ""), flush=True)


# ------------------------------------------------------------------ candidate generation (no LLM)
def module_of(rel):
    q = rel[:-3]
    parts = q.split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def module_globals(tree, modname, is_init, pkgtops):
    """{global name: fully qualified replacement or None}.  Definitions/assignments -> '<module>.<name>'; imports -> their
    absolute target if it is inside the package (relative imports resolved), else None (external: not usable)."""
    g = {}
    pkg = modname if is_init else modname.rsplit(".", 1)[0]
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            g[n.name] = f"{modname}.{n.name}"
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                for x in ast.walk(t):
                    if isinstance(x, ast.Name):
                        g[x.id] = f"{modname}.{x.id}"
        elif isinstance(n, ast.Import):
            for a in n.names:
                local = a.asname or a.name.split(".")[0]
                tgt = a.name if a.asname else a.name.split(".")[0]
                g[local] = tgt if tgt.split(".")[0] in pkgtops else None
        elif isinstance(n, ast.ImportFrom):
            if n.level:
                parts = pkg.split(".")
                if n.level - 1 > len(parts) - 1:
                    continue
                base = ".".join(parts[:len(parts) - (n.level - 1)] + ([n.module] if n.module else []))
            else:
                base = n.module or ""
            for a in n.names:
                if a.name == "*":
                    continue
                g[a.asname or a.name] = f"{base}.{a.name}" if base.split(".")[0] in pkgtops else None
    return g


# Names that a repo's own doctest configuration injects into every doctest namespace (networkx/conftest.py: add_nx -> nx)
DOCTEST_GLOBALS = {"networkx": {"nx": "networkx"}}


BUILTINS = set(dir(builtins))


class Rewriter(ast.NodeTransformer):
    """Rewrite free names of a doctest expression to fully qualified package references."""

    def __init__(self, aliases, assigned, modname, mglobals, pkgtops):
        self.aliases, self.assigned, self.modname, self.mglobals, self.pkgtops = aliases, assigned, modname, mglobals, pkgtops
        self.ok, self.bound = True, set()

    def visit_Lambda(self, node):
        saved = set(self.bound)
        for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
            self.bound.add(a.arg)
        if node.args.vararg:
            self.bound.add(node.args.vararg.arg)
        if node.args.kwarg:
            self.bound.add(node.args.kwarg.arg)
        self.generic_visit(node)
        self.bound = saved
        return node

    def _comp(self, node):
        saved = set(self.bound)
        for g in node.generators:
            for x in ast.walk(g.target):
                if isinstance(x, ast.Name):
                    self.bound.add(x.id)
        self.generic_visit(node)
        self.bound = saved
        return node

    visit_ListComp = visit_SetComp = visit_DictComp = visit_GeneratorExp = _comp

    def visit_NamedExpr(self, node):
        self.ok = False
        return node

    def visit_Name(self, node):
        if not isinstance(node.ctx, ast.Load) or node.id in self.bound:
            return node
        if node.id in self.aliases:
            path = self.aliases[node.id]
            if path is None:
                self.ok = False
                return node
            return ast.copy_location(ast.parse(path, mode="eval").body, node)
        if node.id in self.assigned:
            v = self.assigned[node.id]
            if v is None:
                self.ok = False
                return node
            return copy.deepcopy(v)
        if node.id in self.mglobals:
            path = self.mglobals[node.id]
            if path is None:
                self.ok = False
                return node
            return ast.copy_location(ast.parse(path, mode="eval").body, node)
        if node.id in BUILTINS:
            return node
        self.ok = False
        return node


def rewrite(expr_node, env, modname, mglobals, pkgtops):
    rw = Rewriter(env["aliases"], env["assigned"], modname, mglobals, pkgtops)
    new = rw.visit(copy.deepcopy(expr_node))
    return new if rw.ok else None


def handle_import(stmt, env, pkgtops):
    for a in stmt.names:
        if isinstance(stmt, ast.Import):
            local = a.asname or a.name.split(".")[0]
            target = a.name if a.asname else a.name.split(".")[0]
            root = a.name.split(".")[0]
        else:
            if stmt.level or not stmt.module or a.name == "*":
                if a.name == "*":
                    env["star"] = True
                env["aliases"][a.asname or a.name] = None
                continue
            local = a.asname or a.name
            target = f"{stmt.module}.{a.name}"
            root = stmt.module.split(".")[0]
        env["aliases"][local] = target if root in pkgtops else None


def doctest_candidates(name, tree, modname, rel, mglobals, pkgtops):
    out = []
    parser = doctest.DocTestParser()
    objs = [("", tree)]
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            objs.append((n.name, n))
            if isinstance(n, ast.ClassDef):
                for m in n.body:
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        objs.append((n.name, m))   # methods are documented under their class
    for owner, node in objs:
        try:
            doc = ast.get_docstring(node, clean=True)
        except Exception:
            doc = None
        if not doc or ">>>" not in doc:
            continue
        try:
            exs = parser.get_examples(doc)
        except Exception:
            continue
        env = {"aliases": {}, "assigned": {}, "star": False}
        for ex in exs:
            src = ex.source.strip()
            try:
                mod = ast.parse(src)
            except SyntaxError:
                continue
            if len(mod.body) != 1:
                poison(mod, env)
                continue
            st = mod.body[0]
            if isinstance(st, (ast.Import, ast.ImportFrom)):
                handle_import(st, env, pkgtops)
                continue
            if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
                v = rewrite(st.value, env, modname, mglobals, pkgtops) if not env["star"] else None
                env["assigned"][st.targets[0].id] = v
                continue
            if isinstance(st, ast.Expr) and not env["star"]:
                e = st.value
                if isinstance(e, ast.Call) and isinstance(e.func, ast.Name) and e.func.id == "print" and len(e.args) == 1 and not e.keywords:
                    e = ast.Call(func=ast.Name("str", ast.Load()), args=[e.args[0]], keywords=[])
                if isinstance(e, ast.Constant):
                    continue
                r = rewrite(e, env, modname, mglobals, pkgtops)
                if r is None:
                    continue
                expr = ast.unparse(r)
                if len(expr) > 400 or IMPURE_EXPR.search(expr):
                    continue
                out.append({"src": "doctest", "owner": owner, "expr": expr, "want": ex.want.strip()[:300], "doc_module": modname})
                # a method call on a doctest variable may mutate it: later lines must not inline the fresh object
                if isinstance(st.value, ast.Call):
                    poison(st.value.func, env)
                continue
            poison(st, env)
    return out


def poison(node, env):
    """Names (re)bound or possibly mutated by a statement that is not inlined: assignment targets of any kind (x[...] = , x.a = ,
    x += , del x[...], for x in ...) and receivers of method calls."""
    for x in ast.walk(node):
        if isinstance(x, ast.Name) and isinstance(x.ctx, (ast.Store, ast.Del)):
            env["assigned"][x.id] = None
        elif isinstance(x, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
            for t in (x.targets if isinstance(x, (ast.Assign, ast.Delete)) else [x.target]):
                for y in ast.walk(t):
                    if isinstance(y, ast.Name):
                        env["assigned"][y.id] = None
        elif isinstance(x, ast.Attribute):
            base = x.value
            while isinstance(base, (ast.Attribute, ast.Subscript)):
                base = base.value
            if isinstance(base, ast.Name) and base.id in env["assigned"]:
                env["assigned"][base.id] = None


# ---- synthesised calls
POOL = {
    "str": ["abc", "Hello World", "", "a_b-c d", "x1,y2;z3"],
    "int": [3, 0, 12, -2, 1],
    "float": [0.5, 2.0, -1.25],
    "bool": [True, False],
    "list": [[3, 1, 2], [], ["a", "b", "a"]],
    "dict": [{"a": 1, "b": 2}, {}],
    "bytes": [b"abc", b""],
    "tuple": [(1, 2), ()],
}
ANN = {"str": "str", "int": "int", "float": "float", "bool": "bool", "bytes": "bytes", "list": "list", "List": "list",
       "Sequence": "list", "Iterable": "list", "Collection": "list", "dict": "dict", "Dict": "dict", "Mapping": "dict",
       "tuple": "tuple", "Tuple": "tuple", "Text": "str", "AnyStr": "str"}
NAMEH = [(re.compile(r"^(s|text|string|name|word|prefix|suffix|sep|separator|line|source|src|pattern|value_str|title|key|label|url|path_str|fmt|template|char|chars|ident|identifier|token|msg|message)$"), "str"),
         (re.compile(r"^(n|num|count|size|length|width|height|index|idx|i|k|base|limit|depth|level|indent|precision|digits|start|stop|step|max_\w+|min_\w+|number)$"), "int"),
         (re.compile(r"^(seq|items|iterable|lst|values|seqs|elements|sequence|data_list|it|xs|nums)$"), "list"),
         (re.compile(r"^(mapping|d|dct|dictionary|kwargs_dict)$"), "dict"),
         (re.compile(r"^(flag|strict|reverse|enabled)$"), "bool")]


def ann_type(a):
    if a is None:
        return None
    if isinstance(a, ast.Constant) and isinstance(a.value, str):
        try:
            a = ast.parse(a.value, mode="eval").body
        except Exception:
            return None
    if isinstance(a, ast.Name):
        return ANN.get(a.id)
    if isinstance(a, ast.Attribute):
        return ANN.get(a.attr)
    if isinstance(a, ast.Subscript):
        base = a.value.attr if isinstance(a.value, ast.Attribute) else getattr(a.value, "id", None)
        if base == "Optional":
            return ann_type(a.slice)
        return ANN.get(base)
    if isinstance(a, ast.BinOp) and isinstance(a.op, ast.BitOr):
        l, r = ann_type(a.left), ann_type(a.right)
        if isinstance(a.right, ast.Constant) and a.right.value is None:
            return l
        return l or r
    return None


def default_type(d):
    if isinstance(d, ast.Constant) and d.value is not None:
        return {str: "str", int: "int", float: "float", bool: "bool", bytes: "bytes"}.get(type(d.value))
    if isinstance(d, ast.List):
        return "list"
    if isinstance(d, ast.Dict):
        return "dict"
    if isinstance(d, ast.Tuple):
        return "tuple"
    return None


def name_type(n):
    for rx, t in NAMEH:
        if rx.match(n):
            return t
    return None


def synth_candidates(tree, src, modname):
    out = []
    lines = src.split("\n")
    topc = Counter(n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
    for n in tree.body:
        if not isinstance(n, ast.FunctionDef) or n.name.startswith("_") or topc[n.name] != 1:
            continue
        if n.decorator_list:
            continue
        body = "\n".join(lines[n.lineno - 1:n.end_lineno])
        if IMPURE.search(body) or n.end_lineno - n.lineno > 80 or n.end_lineno - n.lineno < 2:
            continue
        a = n.args
        pos = a.posonlyargs + a.args
        defaults = [None] * (len(pos) - len(a.defaults)) + list(a.defaults)
        req, opt = [], []
        bad = False
        for x, d in zip(pos, defaults):
            t = ann_type(x.annotation) or (default_type(d) if d is not None else None) or name_type(x.arg)
            if d is None:
                if t is None:
                    bad = True
                    break
                req.append((x.arg, t))
            elif t is not None:
                opt.append((x.arg, t, d))
        for x, d in zip(a.kwonlyargs, a.kw_defaults):
            if d is None:
                bad = True
            else:
                t = ann_type(x.annotation) or default_type(d) or name_type(x.arg)
                if t:
                    opt.append((x.arg, t, d, "kw"))
        if bad or (not req and not opt):
            continue
        calls = []
        for v in range(2):
            args = [repr(POOL[t][v % len(POOL[t])]) for _, t in req]
            calls.append(f"{modname}.{n.name}({', '.join(args)})")
        if opt:
            o = opt[int(hashlib.sha1(n.name.encode()).hexdigest(), 16) % len(opt)]
            dv = None
            try:
                dv = ast.literal_eval(o[2])
            except Exception:
                pass
            alt = next((x for x in POOL[o[1]] if x != dv), POOL[o[1]][0])
            args = [repr(POOL[t][0]) for _, t in req] + [f"{o[0]}={alt!r}"]
            calls.append(f"{modname}.{n.name}({', '.join(args)})")
        for e in dict.fromkeys(calls):
            out.append({"src": "synth", "owner": n.name, "expr": e, "want": None, "doc_module": modname})
    return out


def ref_func(expr, modname, owner, pkgtops):
    """(module, func) for the runner: the referenced dotted name whose last part is the documented object (owner)."""
    try:
        t = ast.parse(expr, mode="eval")
    except SyntaxError:
        return None
    best = None
    for x in ast.walk(t):
        if isinstance(x, ast.Attribute) and x.attr == owner:
            try:
                path = ast.unparse(x.value)
            except Exception:
                continue
            if re.fullmatch(r"[A-Za-z_][\w.]*", path) and path.split(".")[0] in pkgtops:
                if best is None or path == modname:
                    best = (path, owner)
    return best


def cmd_cands(name):
    BDIR.mkdir(parents=True, exist_ok=True)
    repo = C.get_repo(name)
    w0 = repo.world(repo.s0)
    pf = pkg_files(w0, name)
    pkgtops = {t.split("/")[0] for t in BEHAV[name][0]}
    raw = []
    for rel, p in sorted(pf.items()):
        if not p.endswith(".py") or any(x in SKIP_PARTS for x in rel[:-3].split("/")):
            continue
        pr = vfs._parse(w0, p)
        if pr is None:
            continue
        tree, src = pr
        modname = module_of(rel)
        mg = dict(DOCTEST_GLOBALS.get(name, {}))
        mg.update(module_globals(tree, modname, rel.endswith("__init__.py"), pkgtops))
        cs = doctest_candidates(name, tree, modname, rel, mg, pkgtops)
        if not any(x.startswith("_") for x in modname.split(".")[1:]):
            cs += synth_candidates(tree, src, modname)
        for c in cs:
            owner = c["owner"]
            if not owner:
                continue
            rf = ref_func(c["expr"], modname, owner, pkgtops)
            if rf is None:
                continue
            c.update({"repo": name, "file": p, "module": rf[0], "func": rf[1]})
            raw.append(c)
    # dedupe by expression
    seen, cands = set(), []
    for c in raw:
        if c["expr"] in seen:
            continue
        seen.add(c["expr"])
        cands.append(c)
    print(name, "raw candidates", len(raw), "unique", len(cands), Counter(c["src"] for c in cands), flush=True)
    key, d = materialise(w0, name)

    def probe(cs, seed):
        jobs = [{"id": str(i), "module": c["module"], "func": c["func"], "expr": c["expr"]} for i, c in enumerate(cs)]
        r = {}
        for k in range(0, len(jobs), 150):
            r.update(run_jobs(name, d, jobs[k:k + 150], probe=True, seed=seed))
        return [r.get(str(i), {"v": "RUNNER_ERROR"}) for i in range(len(cs))]

    p1 = probe(cands, "0")
    wrapped = []
    for c, r in zip(cands, p1):
        v = r.get("v")
        c["probe1"] = r
        if v is None or v in ("NONE", "TIMEOUT", "RUNNER_ERROR", "RUNNER_ABORT") or v.startswith("raises"):
            continue
        if not r.get("literal"):
            wexpr = f"list({c['expr']})" if r.get("iter") else f"repr({c['expr']})"
            wc = dict(c, expr=wexpr, wrapped=True)
            wc.pop("probe1", None)
            wrapped.append(wc)
    p1w = probe(wrapped, "0")
    for c, r in zip(wrapped, p1w):
        c["probe1"] = r
    allc = cands + wrapped
    # second process, different hash seed: determinism across processes
    p2 = probe(allc, "1")
    keep = []
    for c, r2 in zip(allc, p2):
        r1 = c["probe1"]
        v = r1.get("v")
        ok = (v is not None and v not in ("NONE", "TIMEOUT", "RUNNER_ERROR", "RUNNER_ABORT") and v not in ARTIFACT_RAISES
              and r1.get("v2") == v and r2.get("v") == v and r2.get("v2") == v and r1.get("t", 9) < 1.0
              and " at 0x" not in v and len(v) <= 300 and v != "None")      # None = mutator / no-result call: dropped
        if ok and not v.startswith("raises"):
            try:
                ast.literal_eval(v)
            except Exception:
                ok = False
        c["det_ok"] = r1.get("v2") == v and r2.get("v") == v and r2.get("v2") == v
        c["ok"] = ok
        c["K"] = v
        c["probe2"] = r2
        if ok:
            keep.append(c)
    for i, c in enumerate(allc):
        c["cid"] = f"{name}:B:{c['func']}:{hashlib.sha1(c['expr'].encode()).hexdigest()[:8]}"
    nd = sum(1 for c in allc if c["probe1"].get("v") not in (None, "NONE", "TIMEOUT", "RUNNER_ERROR") and not c["det_ok"])
    print(name, "probed", len(allc), "valid", len(keep), "nondeterministic", nd, Counter(c["src"] for c in keep),
          "raises", sum(c["K"].startswith("raises") for c in keep), flush=True)
    (BDIR / f"{name}.cands.json").write_text(json.dumps({"repo": name, "s0_state": key, "cands": allc}, indent=0), encoding="utf-8")


# ------------------------------------------------------------------ truth series
def cmd_truth(name, workers=4):
    d = json.loads((BDIR / f"{name}.cands.json").read_text(encoding="utf-8"))
    cs = [c for c in d["cands"] if c["ok"]]
    repo = C.get_repo(name)
    jobs = [{"id": c["cid"], "module": c["module"], "func": c["func"], "expr": c["expr"]} for c in cs]
    keys, states = [], {}
    for cm in repo.commits:
        w = repo.world(cm)
        k, pf = state_key(w, name)
        keys.append(k)
        if k not in states:
            states[k] = (cm, pf)
    print(name, "jobs", len(jobs), "distinct package states", len(states), flush=True)
    rdir = BDIR / "results" / name
    rdir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    def one(k):
        rp = rdir / f"{k}.json"
        if rp.exists():
            r = json.loads(rp.read_text(encoding="utf-8"))
            if all(j["id"] in r for j in jobs):
                return k, r
        cm, pf = states[k]
        w = repo.world(cm)
        _, dd = materialise(w, name, k, pf)
        r = run_jobs(name, dd, jobs)
        rp.write_text(json.dumps(r), encoding="utf-8")
        if k != d["s0_state"]:
            shutil.rmtree(dd, ignore_errors=True)
        return k, r

    res = {}
    with cf.ThreadPoolExecutor(workers) as ex:
        for i, (k, r) in enumerate(ex.map(one, list(states)), 1):
            res[k] = r
            if i % 50 == 0:
                print(name, f"{i}/{len(states)} states {time.time()-t0:.0f}s", flush=True)
    truth = {}
    for c in cs:
        s = [res[k][c["cid"]] for k in keys]
        truth[c["cid"]] = {"truth": s, "det": s[C.S0] == c["K"], "n_fut_invalid": sum(1 for v in s[C.S0 + 1:] if v != s[C.S0]),
                           "n_hist_diff": sum(1 for v in s[:C.S0] if v != s[C.S0])}
    (BDIR / f"{name}.truth.json").write_text(json.dumps({"repo": name, "state_keys": keys, "truth": truth}), encoding="utf-8")
    print(name, "truth done", len(truth), "s0-mismatch", sum(not t["det"] for t in truth.values()), "changing",
          sum(t["n_fut_invalid"] > 0 for t in truth.values()), f"{time.time()-t0:.0f}s", flush=True)


# ------------------------------------------------------------------ selection (enriched + natural)
N_ENR, N_NAT, RAISE_FRAC = 10, 10, 0.2
IO_RAISES = {"raises FileNotFoundError", "raises PermissionError", "raises OSError", "raises IsADirectoryError",
             "raises NotADirectoryError", "raises TimeoutError", "raises ConnectionError"}


def question(expr, root):
    # identical wording to pilot6/behav.py question()
    return (f"In this repository (the package is importable from `{root or '.'}`), what does the Python expression `{expr}` evaluate to "
            f"at the current commit? Determine it by reading the source code (you cannot run it). Answer with the Python repr of the value "
            f"(e.g. 'abc', [1, 2], None, True), or 'raises <ExceptionType>' if it raises an exception.")


def import_root(name):
    repo = C.get_repo(name)
    w0 = repo.world(repo.s0)
    top = BEHAV[name][0][0]
    inits = sorted((p for p in w0.paths() if p == f"{top}/__init__.py" or p.endswith(f"/{top}/__init__.py")), key=len)
    return inits[0][: -len(f"{top}/__init__.py")].rstrip("/")


def _take(pool, n, cands, per_fn_cap, raise_cap, pick, per_fn, nraise):
    for cid in pool:
        if sum(1 for x in pick if x in pool) >= n:
            break
        c = cands[cid]
        if cid in pick or per_fn[c["func"]] >= per_fn_cap:
            continue
        r = c["K"].startswith("raises")
        if r and nraise[0] >= raise_cap:
            continue
        pick.append(cid)
        per_fn[c["func"]] += 1
        nraise[0] += r


def select_repo(name):
    cd = json.loads((BDIR / f"{name}.cands.json").read_text(encoding="utf-8"))
    td = json.loads((BDIR / f"{name}.truth.json").read_text(encoding="utf-8"))
    cands = {c["cid"]: c for c in cd["cands"] if c["ok"]}
    truth = td["truth"]
    valid = sorted(cid for cid, c in cands.items() if c["K"] not in IO_RAISES and cid in truth and truth[cid]["det"])
    stats = {"n_probed": len(cd["cands"]), "n_ok_at_s0": len(cands), "n_valid": len(valid),
             "n_s0_rerun_mismatch": sum(1 for cid in cands if cid in truth and not truth[cid]["det"]),
             "n_io_raises_dropped": sum(1 for c in cands.values() if c["K"] in IO_RAISES),
             "valid_frac_changing": round(sum(truth[c]["n_fut_invalid"] > 0 for c in valid) / max(1, len(valid)), 3),
             "by_source": dict(Counter(cands[c]["src"] for c in valid))}
    # enriched: pilot6 cmd_select logic (changing first up to >= half, <= 4 per function for changing, <= 2 for stable)
    order = sorted(valid, key=lambda c: C.h("heldout-bsel|" + c))
    chg = [c for c in order if truth[c]["n_fut_invalid"] > 0]
    stay = [c for c in order if truth[c]["n_fut_invalid"] == 0]
    n_e = min(N_ENR, len(valid))
    rcap = max(1, int(RAISE_FRAC * n_e))
    pick, per_fn, nr = [], Counter(), [0]
    _take(chg, max(n_e // 2, n_e - len(stay)), cands, 4, rcap, pick, per_fn, nr)
    _take(stay, n_e - len(pick), cands, 2, rcap, pick, per_fn, nr)
    _take(chg, n_e - len(pick), cands, 4, rcap, pick, per_fn, nr)
    enr = list(pick)
    # natural: uniform random order (seeded by repo), no FUTURE/HISTORY information; <= 2 per function, same raise cap
    rn = random.Random(int(C.h(f"heldout-bnat|{name}")[:8], 16))
    order_n = list(valid)
    rn.shuffle(order_n)
    n_n = min(N_NAT, len(valid))
    pick, per_fn, nr = [], Counter(), [0]
    _take(order_n, n_n, cands, 2, max(1, int(RAISE_FRAC * n_n)), pick, per_fn, nr)
    nat = list(pick)
    root = import_root(name)
    out = []
    for subset, ids in (("enriched", enr), ("natural", nat)):
        other = set(nat if subset == "enriched" else enr)
        for cid in ids:
            c, t = cands[cid], truth[cid]
            fid = cid if subset == "enriched" else cid.rsplit(":", 1)[0] + ":n-" + cid.rsplit(":", 1)[1]
            out.append({"id": fid, "repo": name, "type": "B", "args": {"module": c["module"], "func": c["func"], "expr": c["expr"], "file": c["file"]},
                        "question": question(c["expr"], root), "K": c["K"], "K_oracle": c["K"], "n_future_changed": t["n_fut_invalid"],
                        "n_history_changed": t["n_hist_diff"], "subset": subset, "source": c["src"], "doctest_want": c.get("want"),
                        "wrapped": bool(c.get("wrapped")), "cid": cid,
                        "same_fact_as": (cid if subset == "natural" else cid.rsplit(":", 1)[0] + ":n-" + cid.rsplit(":", 1)[1]) if cid in other else None,
                        "none_at_future_end": t["truth"][-1] == "NONE"})
    return out, stats, {f["id"]: truth[f["cid"]]["truth"] for f in out}


def cmd_select():
    allf, allstats, alltruth = [], {}, {}
    for name in BEHAV:
        if not (BDIR / f"{name}.truth.json").exists():
            print("no truth for", name)
            continue
        fs, st, tr = select_repo(name)
        allf += fs
        allstats[name] = st
        alltruth.update(tr)
        print(name, st, "enriched", sum(f["subset"] == "enriched" for f in fs), "chg",
              sum(f["n_future_changed"] > 0 for f in fs if f["subset"] == "enriched"), "natural", sum(f["subset"] == "natural" for f in fs),
              "chg", sum(f["n_future_changed"] > 0 for f in fs if f["subset"] == "natural"), flush=True)
    (BDIR / "behav_facts.json").write_text(json.dumps({"stats": allstats, "facts": allf}, indent=1), encoding="utf-8")
    (BDIR / "behav_truth_selected.json").write_text(json.dumps(alltruth), encoding="utf-8")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "select":
        cmd_select()
    if cmd == "imports":
        cmd_imports()
    elif cmd == "cands":
        cmd_cands(sys.argv[2])
    elif cmd == "truth":
        cmd_truth(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 4)
