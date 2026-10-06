"""Fact selection, task texts, ground truth at commit t (src/-layout aware) and the success checks.

Task types (fact type -> task):
  T-locate   (T1)  one-line `from M import X` importing X from its defining module
  T-api      (T3)  call of f passing every named parameter (not self/cls, not *args/**kwargs) by keyword = None
  T-modify   (T3)  exact text replacement adding parameter `e2e_flag=False` to f
  T-test     (B)   pytest regression test asserting the current value of an expression (executed)
  T-question (T2/T6/T7) the fact's question asked by module/symbol
Outcome: success | wrong (a submitted action that fails the check) | fail (abstained although possible, or nothing submitted).
"""
import ast, json, random, re
from collections import defaultdict
from . import common_e2e as C
from esm import tools as T
from esm.envs import pyfacts as FX

# held-out oracle excluded these top-level dirs in addition to pilot3's (heldout/common_h.EXTRA_EXCL)
FX.EXCL_DIRS |= {"docs_src", "benchmark", "requirements", "news", "stubs", "sample_project", "tutorial", "examples_src",
                 "extras", "misc", "devtools", "playground", "test_data", "testdata"}

QUOTA = [("T-locate", "T1", 8), ("T-api", "T3", 7), ("T-modify", "T3", 7), ("T-test", "B", 8),
         ("T-question", "T2", 4), ("T-question", "T6", 3), ("T-question", "T7", 3)]
NONE = "NONE"


# ---------------------------------------------------------------- selection
def select(facts_by_id, h150, seed=C.SEED, frac_changing=0.7):
    """Seeded stratified draw from H150 (kept facts only).  Returns list of {iid, task_type}."""
    rng = random.Random(seed)
    used, out = set(), []
    for ttype, ftype, q in QUOTA:
        pool = [i for i in sorted(h150) if i in facts_by_id and facts_by_id[i]["type"] == ftype and i not in used
                and eligible(facts_by_id[i], ttype)]
        ch = [i for i in pool if (facts_by_id[i].get("n_future_changed") or 0) > 0]
        st = [i for i in pool if i not in ch]
        rng.shuffle(ch); rng.shuffle(st)
        n_ch = min(len(ch), round(q * frac_changing))
        picks = _spread(ch, n_ch) + _spread(st, q - n_ch)
        if len(picks) < q:                       # top up from whatever is left
            rest = [i for i in ch + st if i not in picks]
            picks += rest[: q - len(picks)]
        for i in picks:
            used.add(i)
            out.append({"iid": i, "task_type": ttype, "fact_type": ftype})
    return out


def _spread(ids, n):
    """First n ids, preferring distinct repos (ids already shuffled)."""
    out, repos = [], set()
    for i in ids:
        if len(out) < n and i.split(":")[0] not in repos:
            out.append(i); repos.add(i.split(":")[0])
    for i in ids:
        if len(out) < n and i not in out:
            out.append(i)
    return out


def eligible(f, ttype):
    if ttype in ("T-api", "T-modify"):
        # the function must exist at s0 without positional-only parameters (keywords must bind)
        return not f.get("_posonly", False)
    return True


# ---------------------------------------------------------------- helpers
def _mod(path):
    return FX.mod_of(path)


def _callee(name):
    parts = name.split(".")
    return parts[-2] if parts[-1] == "__init__" and len(parts) > 1 else parts[-1]


def find_func(w, fact):
    """(resolved file, node, tree, src) of the fact's function/class at w (src/-layout aware), or (file|None, None, ...)."""
    a = fact["args"]
    fr = C.resolve_file(w, a["file"])
    if fr is None:
        return None, None, None, None
    pr = T.parse(w, fr)
    if pr is None:
        return fr, None, None, None
    node = T.find_node(pr[0], a["name"])
    return fr, node, pr[0], pr[1]


def params_of(node):
    """[(name, kind, default-src)] kinds: po, pk, var, ko, kw."""
    a = node.args
    pos = a.posonlyargs + a.args
    defs = [None] * (len(pos) - len(a.defaults)) + list(a.defaults)
    out = []
    for i, (x, d) in enumerate(zip(pos, defs)):
        out.append((x.arg, "po" if i < len(a.posonlyargs) else "pk", ast.unparse(d) if d is not None else None))
    if a.vararg:
        out.append((a.vararg.arg, "var", None))
    for x, d in zip(a.kwonlyargs, a.kw_defaults):
        out.append((x.arg, "ko", ast.unparse(d) if d is not None else None))
    if a.kwarg:
        out.append((a.kwarg.arg, "kw", None))
    return out


def api_expected(node):
    ps = params_of(node)
    names = [n for n, k, _ in ps if k in ("po", "pk", "ko")]
    if names and names[0] in ("self", "cls") and ps[0][1] in ("po", "pk"):
        names = names[1:]
    return names


# ---------------------------------------------------------------- task texts
def task_text(fact, ttype):
    a = fact["args"]
    if ttype == "T-locate":
        x = a["name"]
        return (f"Write a one-line Python import statement of the form `from <module> import {x}` that imports `{x}` from the "
                f"module in which it is defined (its defining module, not a package that re-exports it). Submit the statement. "
                f"If `{x}` is no longer defined anywhere in the repository's non-test source code, call abstain.")
    if ttype == "T-api":
        n, m = a["name"], _mod(a["file"])
        c = _callee(n)
        return (f"Write a single Python call expression that calls `{n}` from module `{m}`, passing every one of its named "
                f"parameters explicitly as a keyword argument with the value None: all parameters except `self`/`cls` and "
                f"except variadic `*args`/`**kwargs`-style parameters. Write the callee as `{c}`, for example "
                f"`{c}(a=None, b=None)`, and submit only the expression. If `{n}` no longer exists in that module, call abstain.")
    if ttype == "T-modify":
        n, m = a["name"], _mod(a["file"])
        return (f"Modify the repository: add a new parameter `e2e_flag` with default value `False` to the signature of `{n}` "
                f"in module `{m}`, as its last parameter before any `**kwargs`-style parameter (after a bare `*` or `*args` it "
                f"becomes keyword-only, which is fine). Change nothing else. Submit the edit as an exact text replacement: the "
                f"repository-relative path of the file, an `old` snippet copied exactly from the current file (it must occur "
                f"exactly once in that file), and the `new` snippet that replaces it. If `{n}` no longer exists, call abstain.")
    if ttype == "T-test":
        e, fn = a["expr"], a["func"]
        return (f"Add a regression test: write a pytest test function named `test_e2e_regression` that checks what the "
                f"Python expression `{e}` evaluates to in the current version of this repository (the package is importable "
                f"from the repository root; import what you need inside the test). If it returns a value, assert equality "
                f"with a literal (`assert <expression> == <literal>`); if it raises an exception, use "
                f"`with pytest.raises(<ExceptionType>):`. You cannot run code. Submit the test source code. If `{fn}` no "
                f"longer exists, call abstain.")
    if ttype == "T-question":
        t = fact["type"]
        if t == "T2":
            return (f"What is the default value of parameter `{a['param']}` of `{a['name']}` in module `{_mod(a['file'])}`? "
                    f"Answer with the Python default expression exactly as written in the source (answer <NO DEFAULT> if it "
                    f"has none). If `{a['name']}` or that parameter no longer exists, call abstain.")
        if t == "T6":
            return (f"Which non-test source files (excluding tests, docs, examples and top-level scripts) import the module "
                    f"`{a['module']}` (via `import`, `from ... import`, or relative imports, including importing names from it "
                    f"or its submodules), excluding the module's own file? Answer with the sorted list of repository-relative "
                    f"paths, comma-separated, or NONE if no file imports it. If the module no longer exists, call abstain.")
        if t == "T7":
            m = _mod(a["file"])
            if a["sub"] == "bases":
                return (f"In module `{m}`, what are the base classes of class `{a['name']}`, in order (as written, including "
                        f"keyword arguments like metaclass=...)? Answer comma-separated, or (none). If the class no longer "
                        f"exists, call abstain.")
            return (f"In module `{m}`, what are the public method names (defined directly in the class body, not starting with "
                    f"'_') of class `{a['name']}`? Answer sorted, comma-separated. If the class no longer exists, call abstain.")
    raise ValueError(ttype)


# ---------------------------------------------------------------- ground truth at t
def semantic_value(fact, w, oracle_b=None):
    """The fact's value at world w with module identity (src/ moves are the same module), in the oracle's format.
    Behaviour facts: the recorded oracle value at that commit (validated by execution in validate_e2e)."""
    t = fact["type"]
    if t == "B":
        return oracle_b
    a = dict(fact["args"])
    if t in ("T2", "T3", "T7"):
        fr = C.resolve_file(w, a["file"])
        if fr is None:
            return NONE
        a["file"] = fr
    if t == "T6":
        sp = a.get("self_path")
        if sp:
            a["self_path"] = C.resolve_file(w, sp) or sp
        if not C.module_files(w, a["module"]) and not any(FX.mod_of(p).startswith(a["module"] + ".")
                                                         for p in w.paths() if p.endswith(".py")):
            return "MODULE_GONE"
    return FX.oracle(w, {"type": t, "args": a})


def task_truth(fact, ttype, w, oracle_b=None):
    """{possible, value, ...} for the task at world w."""
    v = semantic_value(fact, w, oracle_b)
    if ttype == "T-locate":
        defs = FX.commit_index(w)["defs"].get(fact["args"]["name"], [])
        return {"possible": bool(defs), "value": "|".join(sorted(defs)) or NONE}
    if ttype in ("T-api", "T-modify"):
        fr, node, _, _ = find_func(w, fact)
        ok = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        return {"possible": ok, "value": v, "file": fr, "expected": api_expected(node) if ok else None}
    if ttype == "T-test":
        return {"possible": v not in (NONE, None), "value": v}
    if ttype == "T-question":
        if v == "MODULE_GONE":
            return {"possible": False, "value": NONE}
        if fact["type"] in ("T2", "T7") and v == NONE:
            return {"possible": False, "value": NONE}
        return {"possible": True, "value": v}
    raise ValueError(ttype)


# ---------------------------------------------------------------- checks
def check(fact, ttype, w, truth, sub, repo_exec=True):
    """sub = {'kind': 'abstain'|'submit'|'none', ...args}.  Returns {outcome, detail, ...}."""
    if sub is None or sub.get("kind") == "none":
        return {"outcome": "fail", "detail": "no submission"}
    if sub["kind"] == "abstain":
        if not truth["possible"]:
            return {"outcome": "success", "detail": "correct abstention"}
        return {"outcome": "fail", "detail": "abstained although possible"}
    try:
        fn = {"T-locate": _chk_locate, "T-api": _chk_api, "T-modify": _chk_modify, "T-test": _chk_test,
              "T-question": _chk_question}[ttype]
        return fn(fact, w, truth, sub, repo_exec)
    except Exception as e:                                  # malformed submission
        return {"outcome": "wrong", "detail": f"check error {type(e).__name__}: {str(e)[:150]}"}


def _strip_code(s):
    s = (s or "").strip()
    m = re.match(r"^```(?:python|py)?\s*\n?(.*?)\n?```$", s, re.S)
    return m.group(1).strip() if m else s


def _chk_question(fact, w, truth, sub, repo_exec):
    ans = str(sub.get("answer", "")).strip()
    if not truth["possible"]:
        return {"outcome": "success" if ans.upper() in ("NONE", "N/A") else "wrong", "detail": f"gone; answered {ans[:80]}"}
    v = truth["value"]
    ok = FX.canon(fact["type"], fact["args"].get("sub"), ans) == FX.canon_oracle({"type": fact["type"]}, v)
    return {"outcome": "success" if ok else "wrong", "detail": f"answer={ans[:120]} truth={str(v)[:120]}"}


def _chk_locate(fact, w, truth, sub, repo_exec):
    x = fact["args"]["name"]
    stmt = _strip_code(sub.get("import_statement", ""))
    if not truth["possible"]:
        return {"outcome": "wrong", "detail": f"X gone; submitted {stmt[:100]}"}
    tree = ast.parse(stmt)
    imps = [n for n in tree.body if isinstance(n, ast.ImportFrom)]
    if len(tree.body) != 1 or not imps or imps[0].level != 0 or x not in [a.name for a in imps[0].names]:
        return {"outcome": "wrong", "detail": f"not a from-import of {x}: {stmt[:100]}"}
    m = imps[0].module
    defs = truth["value"].split("|")
    ok = any(FX.mod_of(p) == m for p in defs)
    r = {"outcome": "success" if ok else "wrong", "detail": f"module={m} defs={truth['value'][:120]}"}
    if repo_exec and fact["repo"] in C.BEHAV_TOPS:
        d = C.materialise(w, fact["repo"])
        e = C.run_code(fact["repo"], d, stmt, timeout=20)
        r["exec_ok"] = bool(e.get("ok"))
        r["exec_err"] = e.get("err", "")
    return r


def _chk_api(fact, w, truth, sub, repo_exec):
    s = _strip_code(sub.get("call", ""))
    if not truth["possible"]:
        return {"outcome": "wrong", "detail": f"f gone; submitted {s[:100]}"}
    e = ast.parse(s, mode="eval").body
    if not isinstance(e, ast.Call):
        return {"outcome": "wrong", "detail": "not a call"}
    names = [k.arg for k in e.keywords]
    if e.args or None in names or len(set(names)) != len(names):
        return {"outcome": "wrong", "detail": f"positional/starred/duplicate args: {s[:120]}"}
    exp = truth["expected"]
    ok = set(names) == set(exp)
    return {"outcome": "success" if ok else "wrong",
            "detail": f"missing={sorted(set(exp) - set(names))} extra={sorted(set(names) - set(exp))}"}


def _strip_param(node, name):
    a = node.args
    for lst, dl in ((a.args, a.defaults), (a.kwonlyargs, a.kw_defaults)):
        for i, x in enumerate(lst):
            if x.arg == name:
                if lst is a.kwonlyargs:
                    del a.kwonlyargs[i]; del a.kw_defaults[i]
                else:
                    n_pos = len(a.posonlyargs) + len(a.args)
                    j = len(a.posonlyargs) + i
                    k = j - (n_pos - len(a.defaults))           # index into defaults, if it has one
                    del a.args[i]
                    if k >= 0:
                        del a.defaults[k]
                return True
    return False


def _chk_modify(fact, w, truth, sub, repo_exec):
    f = T.norm_path(str(sub.get("file", "")))
    old, new = sub.get("old", ""), sub.get("new", "")
    if not truth["possible"]:
        return {"outcome": "wrong", "detail": f"f gone; edited {f}"}
    txt = w.text(f)
    if txt is None:
        return {"outcome": "wrong", "detail": f"no such file {f}"}
    if f != truth["file"]:
        return {"outcome": "wrong", "detail": f"edited {f}, function lives in {truth['file']}"}
    if not old or txt.count(old) != 1:
        return {"outcome": "wrong", "detail": f"old snippet occurs {txt.count(old) if old else 0} times"}
    nt = txt.replace(old, new, 1)
    try:
        t_new = ast.parse(nt)
    except SyntaxError as e:
        return {"outcome": "wrong", "detail": f"patched file does not parse: {e.msg}"}
    t_old = ast.parse(txt)
    node = T.find_node(t_new, fact["args"]["name"])
    if node is None or not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return {"outcome": "wrong", "detail": "function not found after edit"}
    ps = {n: (k, d) for n, k, d in params_of(node)}
    if "e2e_flag" not in ps or ps["e2e_flag"][1] != "False" or ps["e2e_flag"][0] not in ("pk", "ko"):
        return {"outcome": "wrong", "detail": f"e2e_flag missing or wrong: {ps.get('e2e_flag')}"}
    _strip_param(node, "e2e_flag")
    same = ast.dump(t_new, include_attributes=False) == ast.dump(t_old, include_attributes=False)
    r = {"outcome": "success" if same else "wrong", "detail": "exact" if same else "other changes besides e2e_flag"}
    if same and repo_exec and fact["repo"] in C.BEHAV_TOPS:
        m = FX.mod_of(f)
        d0 = C.materialise(w, fact["repo"])
        e0 = C.run_code(fact["repo"], d0, f"import {m}", timeout=30)
        d1 = C.materialise(w, fact["repo"], overlay={f: nt})
        e1 = C.run_code(fact["repo"], d1, f"import {m}", timeout=30)
        r["import_before"], r["import_after"] = bool(e0.get("ok")), bool(e1.get("ok"))
        if e0.get("ok") and not e1.get("ok"):
            r["outcome"], r["detail"] = "wrong", "module no longer imports: " + e1.get("err", "")[:150]
    return r


def _chk_test(fact, w, truth, sub, repo_exec):
    code = _strip_code(sub.get("code", ""))
    if not truth["possible"]:
        return {"outcome": "wrong", "detail": "function gone; test submitted"}
    tree = ast.parse(code)
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "test_e2e_regression"]
    if not fns:
        return {"outcome": "wrong", "detail": "no test_e2e_regression"}
    fn_name = fact["args"]["func"]
    calls = [n for n in ast.walk(fns[0]) if isinstance(n, ast.Call)]
    names = {(c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, "id", None)) for c in calls}
    has_assert = any(isinstance(n, ast.Assert) for n in ast.walk(fns[0]))
    has_raises = "raises" in names
    if fn_name not in names and fn_name not in code:
        return {"outcome": "wrong", "detail": f"test does not call {fn_name}"}
    if not (has_assert or has_raises):
        return {"outcome": "wrong", "detail": "no assertion"}
    d = C.materialise(w, fact["repo"])
    e = C.run_code(fact["repo"], d, code, call="test_e2e_regression", timeout=20)
    return {"outcome": "success" if e.get("ok") else "wrong", "detail": "passes" if e.get("ok") else e.get("err", "")[:200],
            "truth": str(truth["value"])[:200]}
