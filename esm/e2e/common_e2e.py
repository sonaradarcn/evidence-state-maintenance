"""End-to-end task evaluation: shared paths, the held-out context rebuilt on the re-cloned repositories, and the
execution sandbox.

Nothing in the esm package or in esm_data_heldout is modified.  The held-out loader's data path is
redirected (module attribute) to esm_data_e2e, where the re-cloned repositories, rebuilt tree caches and the archived
oracle tables live.  Stage-2 LLM responses are read through (copied into the e2e cache on a hit); Stage-2
re-derivations are imported read-only from copies of their shards.
"""
import hashlib, json, os, shutil, subprocess, sys, threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
E2E = ROOT / "esm_data_e2e"
HELD = ROOT / "esm_data_heldout"
RES = ROOT / "esm" / "results" / "e2e"
os.environ.setdefault("ESM_DATA", str(E2E))
os.environ.setdefault("ESM_STAGE", "e2e")
os.environ.setdefault("ESM_PORTS_Q27", "11641")
assert Path(os.environ["ESM_DATA"]).resolve() == E2E.resolve(), "ESM_DATA must point at esm_data_e2e"
PY = os.environ.get("ESM_PYTHON", sys.executable)
TS = [100, 250, 400]
SEED = 20261005

from esm import llm  # noqa: E402
from esm import tools as T  # noqa: E402
from esm.envs import heldout as H  # noqa: E402
from esm.envs import pyfacts as FX  # noqa: E402

H.HD = E2E                                   # repos/, trees/, oracle_tables/ under esm_data_e2e
llm.READ_THROUGH[:] = [HELD / "llm_cache"]   # Stage-2 responses (identical request => identical response)
assert 11434 not in llm.PORTS["qwen3.6:27b"]

BEHAV_TOPS = {"boltons": ["boltons"], "jinja": ["jinja2"], "werkzeug": ["werkzeug"], "marshmallow": ["marshmallow"],
              "isort": ["isort"], "pygments": ["pygments"], "networkx": ["networkx"], "rich": ["rich"],
              "poetry-core": ["poetry/core"]}
DEPS = E2E / "deps"
EXEC = E2E / "exec"
SHIM = E2E / "shim"


def import_stage2_derivations():
    """Copy Stage-2 27B derivation shards (read-only source) into esm_data_e2e once, as derivations.s2_<n>.jsonl."""
    dst = E2E / "derivations.jsonl"
    if not dst.exists():
        dst.write_text("", encoding="utf-8")
    flag = E2E / ".s2_imported"
    if flag.exists():
        return
    srcs = [HELD / "derivations.jsonl"] + sorted(HELD.glob("derivations.*.jsonl"))
    for i, p in enumerate(srcs):
        shutil.copyfile(p, E2E / f"derivations.s2_{i:03d}.jsonl")
    flag.write_text(json.dumps([str(p) for p in srcs]))


def load_context(ids=None):
    """(ctx, raw) like policies.Context.load('heldout') but on esm_data_e2e; facts restricted to `ids` if given."""
    from esm import evidence as E
    from esm.maintain import DerivStore
    from esm.policies import Context
    import_stage2_derivations()
    repos_needed = H.REPOS if ids is None else sorted({i.split(":")[0] for i in ids})
    raw = H.load_heldout_raw(repos_needed)
    if ids is not None:
        raw = [f for f in raw if f["iid"] in set(ids)]
    env0 = H.make_env(raw, repos_needed)
    d0 = DerivStore(env0, E2E / "derivations.jsonl", model=llm.Q27)
    kept = H.attach_s0(raw, d0, env0)
    env = H.make_env(kept, repos=env0._repos)
    tab = E.ObsTable(env)
    obs_dir = E2E / "obs"
    for p in sorted(obs_dir.glob("*.pkl")):
        if p.stem in repos_needed:
            tab.load(p)
    ctx = Context(env, tab, DerivStore(env, E2E / "derivations.jsonl", model=llm.Q27), None, obs_dir)
    ctx.raw = raw
    return ctx


# ---------------------------------------------------------------- execution sandbox
def pkg_files(w, name):
    """{import-relative path: repo path} of the package files at world w (same layout logic as heldout/behav_h.py)."""
    out = {}
    for top in BEHAV_TOPS[name]:
        inits = sorted((p for p in w.paths() if (p == f"{top}/__init__.py" or p.endswith(f"/{top}/__init__.py"))
                        and p[: -len(f"{top}/__init__.py")].count("/") <= 1), key=len)
        if not inits:
            continue
        pref = inits[0][: -len("__init__.py")]
        root = pref[: -len(top) - 1]
        for p in w.paths():
            if p.startswith(pref) and (p.endswith(".py") or p.endswith(".typed") or p.endswith(".pyi")):
                out[p[len(root):]] = p
    return out


_mat_lock = threading.Lock()


def materialise(w, name, overlay=None):
    """Write the package at world w (+ overlay {repo path: new text}) to a content-addressed directory; returns it."""
    pf = pkg_files(w, name)
    overlay = overlay or {}
    key = hashlib.sha1(json.dumps(sorted((k, w.sha(p), hashlib.sha1(overlay[p].encode()).hexdigest() if p in overlay else "")
                                         for k, p in pf.items())).encode()).hexdigest()[:16]
    d = EXEC / name / key
    with _mat_lock:
        if not (d / ".ok").exists():
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
            for rel, p in pf.items():
                q = d / rel
                q.parent.mkdir(parents=True, exist_ok=True)
                q.write_text(overlay[p] if p in overlay else (w.text(p) or ""), encoding="utf-8")
            d.mkdir(parents=True, exist_ok=True)
            (d / ".ok").write_text("ok")
    return d


def _ensure_shim():
    """Minimal `pytest` stand-in (raises / approx) so tests run under python -S without site-packages."""
    SHIM.mkdir(parents=True, exist_ok=True)
    (SHIM / "pytest.py").write_text(
        "import contextlib, math\n"
        "class _Info:\n    value = None\n    type = None\n"
        "@contextlib.contextmanager\n"
        "def raises(exc, match=None):\n"
        "    info = _Info()\n"
        "    try:\n        yield info\n"
        "    except exc as e:\n"
        "        info.value, info.type = e, type(e)\n"
        "        if match is not None:\n            import re\n            assert re.search(match, str(e)), 'pattern not found'\n"
        "        return\n"
        "    raise AssertionError('DID NOT RAISE')\n"
        "class approx:\n"
        "    def __init__(self, v, rel=1e-6, abs=1e-12):\n        self.v, self.rel, self.abs = v, rel, abs\n"
        "    def __eq__(self, o):\n        return math.isclose(o, self.v, rel_tol=self.rel, abs_tol=self.abs)\n"
        "def fail(msg=''):\n    raise AssertionError(msg)\n", encoding="utf-8")


RUN_SRC = r'''
import json, sys, threading, io, os, traceback
job = json.loads(sys.stdin.read())
real = sys.stdout
sys.stdout = io.StringIO()
res = {}
def go():
    ns = {"__name__": "e2e_test"}
    try:
        exec(compile(job["code"], "e2e_code.py", "exec"), ns)
        if job.get("call"):
            ns[job["call"]]()
        res["ok"] = True
    except AssertionError as e:
        res["ok"] = False; res["err"] = "AssertionError: " + str(e)[:300]
    except BaseException as e:
        res["ok"] = False; res["err"] = type(e).__name__ + ": " + str(e)[:300]
th = threading.Thread(target=go, daemon=True); th.start(); th.join(float(job.get("timeout", 10)))
if th.is_alive():
    res = {"ok": False, "err": "TIMEOUT"}
real.write(json.dumps(res)); real.flush(); os._exit(0)
'''


def run_code(name, pkg_dir, code, call=None, timeout=10):
    """Execute `code` (then call function `call`) with PYTHONPATH = package dir + fixed deps + pytest shim.
    Returns {ok, err}."""
    _ensure_shim()
    rp = E2E / "runner_e2e.py"
    if not rp.exists() or rp.read_text(encoding="utf-8") != RUN_SRC:
        rp.write_text(RUN_SRC, encoding="utf-8")
    pp = os.pathsep.join([str(pkg_dir), str(DEPS / name), str(SHIM)])
    env = dict(os.environ, PYTHONPATH=pp, PYTHONIOENCODING="utf-8", PYTHONHASHSEED="0")
    env.pop("PYTHONSTARTUP", None)
    try:
        p = subprocess.run([PY, "-S", "-B", "-W", "ignore", str(rp)], input=json.dumps({"code": code, "call": call, "timeout": timeout}),
                           capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(pkg_dir), timeout=timeout + 60)
        return json.loads(p.stdout) if p.stdout.strip() else {"ok": False, "err": "RUNNER_NO_OUTPUT " + p.stderr[-300:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "err": "TIMEOUT"}


# ---------------------------------------------------------------- module resolution (src/ layout aware)
def resolve_file(w, f):
    """The file at world w that holds the module of repo path f: f itself, or the same module after a src/ layout move."""
    if w.sha(f) is not None:
        return f
    if w.sha("src/" + f) is not None:
        return "src/" + f
    if f.startswith("src/") and w.sha(f[4:]) is not None:
        return f[4:]
    # same module name elsewhere (e.g. module -> package: kombu/transport/SQS.py -> kombu/transport/SQS/__init__.py)
    if f.endswith(".py"):
        c = module_files(w, FX.mod_of(f))
        if len(c) == 1:
            return c[0]
    return None


def module_files(w, mod):
    """Source files at w whose module name (pyfacts.mod_of, src/ stripped) is `mod`."""
    return sorted(p for p in w.paths() if p.endswith(".py") and FX.mod_of(p) == mod)


def jdump(path, obj):
    Path(path).write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
