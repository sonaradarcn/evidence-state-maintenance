"""Python-repository fact types, programmatic oracles, canonicalisers and fact sampling.

Copied from pilot3/facts.py (unchanged semantics) so ESM is self-contained; only the imports differ.
Behaviour-fact canonicaliser `canon_b` copied from pilot6/behav.py."""
import ast, json, random, re, sys
from collections import Counter, defaultdict
from pathlib import Path
from .. import tools as vfs
from ..tools import parse as _parse, load_toml as _toml, load_ini as _ini, find_node as _find_node

NONE = "NONE"
EXCL_DIRS = {"tests", "test", "testing", "docs", "doc", "examples", "example", "ci", "asv_bench", "benchmarks",
             "scripts", "tools", "properties", "design_notes", "bench", "extra", "changelog", "artwork", ".github"}


def is_test(p):
    parts = p.split("/")
    b = parts[-1]
    return any(x in ("tests", "test", "testing") for x in parts[:-1]) or b.startswith("test_") or b.endswith("_test.py") or b == "conftest.py"


def is_source(p):
    if not p.endswith(".py") or "/" not in p:
        return False
    parts = p.split("/")
    if parts[0] in EXCL_DIRS or parts[0].startswith("."):
        return False
    return not is_test(p)


def mod_of(p):
    q = p[:-3]
    if q.startswith("src/"):
        q = q[4:]
    parts = q.split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


# ---------------------------------------------------------------- per-file summaries
_sum = {}


def summary(w, p):
    s = w.sha(p)
    if s is None:
        return None
    if s in _sum:
        return _sum[s]
    pr = _parse(w, p)
    if pr is None:
        _sum[s] = None
        return None
    tree, _ = pr
    top = defaultdict(int)
    imports = []
    ntests = 0
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_"):
            ntests += 1
        elif isinstance(n, ast.Import):
            for a in n.names:
                imports.append((0, a.name, None))
        elif isinstance(n, ast.ImportFrom):
            imports.append((n.level, n.module or "", tuple(a.name for a in n.names)))
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            top[n.name] += 1
    d = {"top": dict(top), "imports": imports, "ntests": ntests}
    _sum[s] = d
    return d


def imported_modules(p, imports):
    mods = set()
    me = mod_of(p)
    pkg = me if p.endswith("__init__.py") else me.rsplit(".", 1)[0] if "." in me else ""
    for level, mod, names in imports:
        if level == 0:
            base = mod
        else:
            parts = pkg.split(".") if pkg else []
            if level - 1 > len(parts):
                continue
            parts = parts[:len(parts) - (level - 1)]
            base = ".".join(parts + ([mod] if mod else []))
        if names is None:
            mods.add(base)
        else:
            if base:
                mods.add(base)
            for nm in names:
                mods.add(f"{base}.{nm}" if base else nm)
    return mods


# ---------------------------------------------------------------- per-commit global indexes
_idx = {}


def commit_index(w):
    key = (w.repo.name, w.commit) if not w.overlay else None
    if key and key in _idx:
        return _idx[key]
    defs = defaultdict(list)
    importers = defaultdict(set)
    dircount = Counter()
    for p in w.paths():
        if p.endswith(".py"):
            d = p.rsplit("/", 1)[0] if "/" in p else "."
            dircount[d] += 1
        if not is_source(p):
            continue
        s = summary(w, p)
        if s is None:
            continue
        for name in s["top"]:
            defs[name].append(p)
        for m in imported_modules(p, s["imports"]):
            importers[m].add(p)
    r = {"defs": defs, "importers": importers, "dircount": dircount}
    if key:
        if len(_idx) > 50:
            _idx.clear()
        _idx[key] = r
    return r


def importers_of(idx, m, self_path=None):
    out = set()
    for mod, files in idx["importers"].items():
        if mod == m or mod.startswith(m + "."):
            out |= files
    out.discard(self_path)
    return sorted(out)


# ---------------------------------------------------------------- oracles
def _func_params(node):
    a = node.args
    pos = a.posonlyargs + a.args
    defaults = [None] * (len(pos) - len(a.defaults)) + list(a.defaults)
    out = [(x.arg, d) for x, d in zip(pos, defaults)]
    if a.vararg:
        out.append((a.vararg.arg, None))
    out += [(x.arg, d) for x, d in zip(a.kwonlyargs, a.kw_defaults)]
    if a.kwarg:
        out.append((a.kwarg.arg, None))
    return out


def _cfg_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return ", ".join(_cfg_value(x) for x in v)
    return re.sub(r"\s+", " ", str(v)).strip()


def oracle(w, f):
    t, a = f["type"], f["args"]
    if t == "T1":
        files = commit_index(w)["defs"].get(a["name"], [])
        return "|".join(sorted(files)) if files else NONE
    if t in ("T2", "T3", "T7"):
        pr = _parse(w, a["file"])
        if pr is None:
            return NONE
        node = _find_node(pr[0], a["name"])
        if t == "T7":
            if not isinstance(node, ast.ClassDef):
                return NONE
            if a["sub"] == "bases":
                return ", ".join([ast.unparse(b) for b in node.bases] + [f"{k.arg}={ast.unparse(k.value)}" for k in node.keywords]) or "(none)"
            ms = sorted({m.name for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and not m.name.startswith("_")})
            return ", ".join(ms) or "(none)"
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return NONE
        params = _func_params(node)
        if t == "T3":
            return ", ".join(p for p, _ in params)
        for p, d in params:
            if p == a["param"]:
                return ast.unparse(d) if d is not None else "<NO DEFAULT>"
        return NONE
    if t == "T4":
        if a["kind"] == "toml":
            d = _toml(w, a["file"])
            if not isinstance(d, dict):
                return NONE
            cur = d
            for k in a["key"]:
                if isinstance(cur, dict) and k in cur:
                    cur = cur[k]
                else:
                    return NONE
            if a.get("dep"):
                if not isinstance(cur, list):
                    return NONE
                for e in cur:
                    if isinstance(e, str) and _req_name(e) == a["dep"]:
                        return re.sub(r"\s+", "", e)
                return NONE
            return _cfg_value(cur)
        cp = _ini(w, a["file"])
        if cp is None or cp == "PARSE_ERROR" or not cp.has_option(a["section"], a["key"]):
            return NONE
        return _cfg_value(cp.get(a["section"], a["key"]))
    if t == "T5":
        if a["sub"] == "tests":
            s = summary(w, a["file"])
            return str(s["ntests"]) if s else NONE
        n = sum(1 for p in w.paths() if p.endswith(".py") and (p.rsplit("/", 1)[0] if "/" in p else ".") == a["dir"])
        return str(n) if n else NONE
    if t == "T6":
        idx = commit_index(w)
        r = importers_of(idx, a["module"], a.get("self_path"))
        return ", ".join(r) if r else NONE
    raise ValueError(t)


def _req_name(e):
    return re.split(r"[\s<>=!~;\[(@]", e.strip(), 1)[0].lower().replace("_", "-")


# ---------------------------------------------------------------- canonicalisers for LLM answers
def _strip_q(s):
    s = s.strip().strip("`").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1]
    return s


def _split_list(s):
    s = s.strip()
    if s.startswith("[") and s.endswith("]"):
        try:
            v = json.loads(s)
            if isinstance(v, list):
                return [str(x) for x in v]
        except Exception:
            try:
                v = ast.literal_eval(s)
                if isinstance(v, (list, tuple)):
                    return [str(x) for x in v]
            except Exception:
                s = s[1:-1]
    return [x for x in re.split(r"[,\n]", s) if x.strip()]


def _cpath(p):
    p = _strip_q(p).replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.strip("/")


def canon(ftype, sub, s):
    if s is None:
        return None
    s = str(s).strip()
    if s.upper() in ("NONE", "N/A") and ftype not in ("T2",):
        return NONE
    if ftype == "T1":
        return "|".join(sorted({_cpath(x) for x in re.split(r"[|,\n]", s) if x.strip()}))
    if ftype == "T2":
        s = _strip_q(s) if s.startswith("`") else s
        if s.upper() in ("<NO DEFAULT>", "NO DEFAULT"):
            return "<NO DEFAULT>"
        try:
            return ast.unparse(ast.parse(s, mode="eval"))
        except Exception:
            return s
    if ftype == "T3":
        out = []
        for x in _split_list(s):
            x = _strip_q(x).split(":")[0].split("=")[0].strip().lstrip("*").strip()
            if x and x != "/":
                out.append(x)
        return ", ".join(out)
    if ftype == "T4":
        items = [_strip_q(x) for x in _split_list(s)] if (s.startswith("[") or "," in s) else [_strip_q(s)]
        v = ",".join(items)
        v = re.sub(r"\s+", "", v)
        return v.lower() if v.lower() in ("true", "false") else v
    if ftype == "T5":
        m = re.search(r"-?\d+", s)
        return m.group(0) if m else s
    if ftype == "T6":
        return ", ".join(sorted({_cpath(x) for x in _split_list(s)}))
    if ftype == "T7":
        if sub == "methods":
            return ", ".join(sorted({_strip_q(x).strip() for x in _split_list(s)}))
        v = ", ".join(_strip_q(x).strip() for x in _split_list(s))
        return v
    return s


def canon_oracle(f, v):
    """Oracle values are canonical already except T4 needs the same whitespace treatment."""
    if v == NONE:
        return NONE
    if f["type"] == "T4":
        return canon("T4", None, v if not ("," in v) else v)
    return v


def matches(f, answer, value):
    return canon(f["type"], f["args"].get("sub"), answer) == canon_oracle(f, value)


# ---------------------------------------------------------------- questions
def question(f):
    t, a = f["type"], f["args"]
    if t == "T1":
        return (f"Which file defines the top-level class or function `{a['name']}` in the non-test source code of this repository? "
                f"Answer with the repository-relative file path (if several files define it, list all paths separated by '|').")
    if t == "T2":
        return (f"In file `{a['file']}`, what is the default value of parameter `{a['param']}` of `{a['name']}`? "
                f"Answer with the Python default expression exactly as written in the source (answer <NO DEFAULT> if it has none).")
    if t == "T3":
        return (f"In file `{a['file']}`, what are the parameter names of `{a['name']}`, in order? "
                f"Answer with the names only (including self/cls, *args and **kwargs names, without stars, annotations or defaults), comma-separated.")
    if t == "T4":
        if a["kind"] == "toml":
            if a.get("dep"):
                return (f"In `{a['file']}`, what is the full requirement string (name plus version specifier/markers) of dependency "
                        f"`{a['dep']}` in the list at key `{'.'.join(a['key'])}`?")
            return (f"In `{a['file']}`, what is the value of the key `{'.'.join(a['key'])}`? "
                    f"For a list, answer with all items comma-separated in order.")
        return f"In `{a['file']}`, what is the value of `{a['key']}` in section [{a['section']}]? For a multi-line value, answer with the items separated by spaces."
    if t == "T5":
        if a["sub"] == "tests":
            return f"How many test functions (functions or methods whose name starts with `test_`, at any nesting level) are defined in `{a['file']}`? Answer with an integer."
        return f"How many `.py` files are located directly in directory `{a['dir']}` (not in its subdirectories)? Answer with an integer."
    if t == "T6":
        return (f"Which non-test source files (excluding tests, docs, examples and top-level scripts) import the module `{a['module']}` "
                f"(via `import`, `from ... import`, or relative imports, including importing names from it or its submodules), "
                f"excluding the module's own file? Answer with the sorted list of repository-relative paths, comma-separated.")
    if t == "T7":
        if a["sub"] == "bases":
            return f"In `{a['file']}`, what are the base classes of class `{a['name']}`, in order (as written, including keyword arguments like metaclass=...)? Answer comma-separated, or (none)."
        return f"In `{a['file']}`, what are the public method names (defined directly in the class body, not starting with '_') of class `{a['name']}`? Answer sorted, comma-separated."


# ---------------------------------------------------------------- candidate enumeration at s0
def enumerate_candidates(w):
    idx = commit_index(w)
    C = defaultdict(list)
    src = [p for p in w.paths() if is_source(p)]
    for name, files in idx["defs"].items():
        if len(files) == 1 and summary(w, files[0])["top"][name] == 1 and not name.startswith("__"):
            C["T1"].append({"name": name, "file_hint": files[0]})
    for p in src:
        pr = _parse(w, p)
        if pr is None:
            continue
        tree = pr[0]
        topc = Counter(n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
        funcs = []
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and topc[n.name] == 1:
                funcs.append((n.name, n))
            if isinstance(n, ast.ClassDef) and topc[n.name] == 1:
                mc = Counter(m.name for m in n.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
                for m in n.body:
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and mc[m.name] == 1:
                        funcs.append((f"{n.name}.{m.name}", m))
                C["T7"].append({"file": p, "name": n.name, "sub": "bases"})
                if sum(1 for m in n.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and not m.name.startswith("_")) >= 2:
                    C["T7"].append({"file": p, "name": n.name, "sub": "methods"})
        for qn, node in funcs:
            params = _func_params(node)
            if len(params) >= 2:
                C["T3"].append({"file": p, "name": qn})
            for pn, d in params:
                if d is not None and len(ast.unparse(d)) <= 60:
                    C["T2"].append({"file": p, "name": qn, "param": pn})
    # configs
    for p in w.paths():
        b = p.rsplit("/", 1)[-1]
        if "/" in p:
            continue
        if b == "pyproject.toml":
            d = _toml(w, p)
            if isinstance(d, dict):
                def walk(cur, path):
                    for k, v in cur.items():
                        if not re.fullmatch(r"[A-Za-z0-9_-]+", str(k)):
                            continue
                        kp = path + [k]
                        if isinstance(v, dict):
                            walk(v, kp)
                        elif isinstance(v, list) and all(isinstance(x, str) for x in v) and v:
                            if any(re.match(r"^[A-Za-z0-9_.-]+\s*([<>=!~;\[]|$)", x) for x in v) and kp[-1] in ("dependencies", "requires") or (len(kp) >= 3 and kp[-3:-1] == ["project", "optional-dependencies"]):
                                for x in v:
                                    C["T4"].append({"kind": "toml", "file": p, "key": kp, "dep": _req_name(x)})
                            elif len(v) <= 12 and len(_cfg_value(v)) <= 200:
                                C["T4"].append({"kind": "toml", "file": p, "key": kp})
                        elif isinstance(v, (str, int, float, bool)) and len(str(v)) <= 200:
                            C["T4"].append({"kind": "toml", "file": p, "key": kp})
                walk(d, [])
        if b in ("setup.cfg", "tox.ini"):
            cp = _ini(w, p)
            if cp and cp != "PARSE_ERROR":
                for s in cp.sections():
                    for k in cp.options(s):
                        v = _cfg_value(cp.get(s, k))
                        if v and len(v) <= 200:
                            C["T4"].append({"kind": "ini", "file": p, "section": s, "key": k})
    for p in w.paths():
        if p.endswith(".py") and is_test(p) and p.rsplit("/", 1)[-1].startswith("test_"):
            s = summary(w, p)
            if s and s["ntests"] >= 1:
                C["T5"].append({"sub": "tests", "file": p})
    for d, n in idx["dircount"].items():
        if n >= 2 and d != ".":
            C["T5"].append({"sub": "dir", "dir": d})
    for p in src:
        m = mod_of(p)
        if "." not in m and not p.endswith("__init__.py"):
            continue
        r = importers_of(idx, m, p)
        if 2 <= len(r) <= 12 and not p.endswith("__init__.py"):
            C["T6"].append({"module": m, "self_path": p})
    return C


def fact_file(t, a):
    if t in ("T2", "T3", "T7", "T4"):
        return a["file"]
    if t == "T5":
        return a.get("file") or a.get("dir")
    if t == "T1":
        return a["file_hint"]
    if t == "T6":
        return a["self_path"]


def sample_facts(repo, per_type=7, pool_per_type=250, seed=0):
    rng = random.Random(seed)
    w0 = repo.world(repo.s0)
    C = enumerate_candidates(w0)
    # history modification frequency (no FUTURE leakage)
    hot = Counter()
    for a, b in zip(repo.history, repo.history[1:] + [repo.s0]):
        ta, tb = repo.trees[a], repo.trees[b]
        for p in set(ta) | set(tb):
            if ta.get(p) != tb.get(p):
                hot[p] += 1
    futw = [repo.world(c) for c in repo.future]
    facts, stats = [], {}
    for t in ["T1", "T2", "T3", "T4", "T5", "T6", "T7"]:
        cands = C.get(t, [])
        rng.shuffle(cands)
        cands.sort(key=lambda a: -hot.get(fact_file(t, a), 0) if rng.random() < 0.5 else 0)  # half hot-biased
        pool = cands[:pool_per_type]
        evals = []
        for a in pool:
            f = {"type": t, "args": a}
            k = oracle(w0, f)
            if k == NONE:
                continue
            series = [oracle(fw, f) for fw in futw]
            nchg = sum(1 for v in series if v != k)
            evals.append((a, k, nchg))
        stats[t] = {"n_candidates": len(cands), "pool": len(evals),
                    "pool_frac_changing": round(sum(1 for e in evals if e[2] > 0) / max(1, len(evals)), 3)}
        chg = [e for e in evals if e[2] > 0]
        stay = [e for e in evals if e[2] == 0]
        n_chg = min(len(chg), max((per_type + 1) // 2, per_type - len(stay)))
        pick = rng.sample(chg, n_chg) + rng.sample(stay, min(len(stay), per_type - n_chg))
        for a, k, nchg in pick:
            fid = f"{repo.name}:{t}:{len(facts)}"
            f = {"id": fid, "repo": repo.name, "type": t, "args": a, "K_oracle": k, "n_future_changed": nchg}
            f["question"] = question(f)
            facts.append(f)
    return facts, stats



# ---------------------------------------------------------------- behaviour facts (pilot6)
def _canon_val(v):
    if isinstance(v, (set, frozenset)):
        return ("set", tuple(sorted((_canon_val(x) for x in v), key=repr)))
    if isinstance(v, (list, tuple)):
        return (type(v).__name__, tuple(_canon_val(x) for x in v))
    if isinstance(v, dict):
        return ("dict", tuple(sorted(((repr(_canon_val(k)), _canon_val(x)) for k, x in v.items()))))
    return (type(v).__name__, v)


def canon_b(s):
    if s is None:
        return None
    s = str(s).strip()
    if s.startswith("```"):
        s = s.strip("`").strip()
        if s.startswith("python"):
            s = s[6:].strip()
    s = s.strip("`").strip()
    if s.upper() == "NONE" and s != "None":
        return "NONE"
    m = re.match(r"^(?:it\s+)?raises?\s*:?\s*([\w.]+)", s, re.I) or re.match(r"^([\w.]*(?:Error|Exception|Warning))\b", s)
    if m:
        return "raises " + m.group(1).split(".")[-1]
    try:
        return repr(_canon_val(ast.literal_eval(s)))
    except Exception:
        return re.sub(r"\s+", " ", s)


