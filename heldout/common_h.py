"""Shared setup for the held-out benchmark.  vfs.py / facts.py are the git VFS and the static-fact oracles of the
development set, copied unchanged.
Same commit layout as the dev set: 300 HISTORY + s0 + 400 FUTURE first-parent commits, s0 = HEAD - 400.
No LLM is used anywhere in heldout/."""
import hashlib, json, os, pickle, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = Path(os.environ.get("ESM_HELDOUT_DATA", ROOT / "heldout_data"))
REPOS = DATA / "repos"
OUT = HERE                               # manifests / facts json live in heldout/
TABLES = DATA / "oracle_tables"
sys.path.insert(0, str(HERE))

import vfs  # noqa: E402
import facts as FX  # noqa: E402

N_HIST, N_FUT = vfs.N_HIST, vfs.N_FUT
S0 = N_HIST
PY = os.environ.get("ESM_PYTHON", sys.executable)

# Development repos (pilots 3-7) -- the held-out set must be disjoint from these.
# toolz was cloned in pilot6_data but never used; excluded anyway.
DEV_REPOS = {"requests", "flask", "click", "pytest", "seaborn", "xarray", "packaging", "more-itertools", "attrs", "toolz"}

# name -> GitHub slug
REPO_URLS = {
    "httpx": "encode/httpx", "jinja": "pallets/jinja", "werkzeug": "pallets/werkzeug", "black": "psf/black",
    "poetry-core": "python-poetry/poetry-core", "typer": "fastapi/typer", "rich": "Textualize/rich", "tqdm": "tqdm/tqdm",
    "marshmallow": "marshmallow-code/marshmallow", "networkx": "networkx/networkx", "scrapy": "scrapy/scrapy",
    "kombu": "celery/kombu", "mkdocs": "mkdocs/mkdocs", "arrow": "arrow-py/arrow", "dateutil": "dateutil/dateutil",
    "boltons": "mahmoud/boltons", "pyparsing": "pyparsing/pyparsing", "tomlkit": "python-poetry/tomlkit",
    "markdown-it-py": "executablebooks/markdown-it-py", "sortedcontainers": "grantjenks/python-sortedcontainers",
    "isort": "PyCQA/isort", "pygments": "pygments/pygments", "humanize": "python-humanize/humanize",
}

# Final held-out set (16 repos).  Cloned but dropped: tqdm (445 first-parent commits), tomlkit (454), dateutil (636),
# markdown-it-py (353), sortedcontainers (611), humanize (448) -- all < 800; arrow (813) dropped to keep 16 (smallest: 21 .py
# files; HISTORY starts 2013 in py2-era code).
HELDOUT = ["boltons", "httpx", "werkzeug", "black", "poetry-core", "jinja", "typer", "marshmallow", "rich", "kombu", "scrapy",
           "networkx", "pyparsing", "mkdocs", "isort", "pygments"]

# Extra top-level directories that are not package source in the new repos (added to pilot3's EXCL_DIRS at runtime;
# pilot3's facts.py itself is not modified).  Documented in README.md.
EXTRA_EXCL = {"docs_src", "benchmark", "requirements", "news", "stubs", "sample_project", "tutorial", "examples_src",
              "extras", "misc", "devtools", "playground", "test_data", "testdata"}
FX.EXCL_DIRS |= EXTRA_EXCL


class RepoH(vfs.Repo):
    """vfs.Repo over a held-out clone; tree cache in heldout_data/trees.  Identical layout to pilot3/pilot6."""

    def __init__(self, name):
        self.name = name
        self.path = REPOS / name
        cache = DATA / "trees" / f"{name}.pkl"
        if cache.exists():
            d = pickle.loads(cache.read_bytes())
        else:
            commits = vfs._git(self.path, "rev-list", "--first-parent", "--reverse", "HEAD").decode().split()
            n = len(commits)
            s0 = n - 1 - N_FUT
            assert s0 - N_HIST >= 0, f"{name}: only {n} first-parent commits"
            sel = commits[s0 - N_HIST: n]
            trees = {}
            for c in sel:
                out = vfs._git(self.path, "ls-tree", "-r", "-l", c).decode("utf-8", "replace")
                t = {}
                for line in out.splitlines():
                    meta, p = line.split("\t", 1)
                    mode, typ, sha, size = meta.split()
                    if typ != "blob":
                        continue
                    t[p] = (sha, not (Path(p).suffix not in vfs.TEXT_EXT or size == "-" or int(size) > vfs.MAX_BLOB))
                trees[c] = t
            d = {"commits": sel, "trees": trees, "n_first_parent": n}
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(pickle.dumps(d))
        self.commits = d["commits"]
        self.trees = d["trees"]
        self.n_first_parent = d.get("n_first_parent")
        self.s0_idx = N_HIST
        self.s0 = self.commits[N_HIST]
        self.history = self.commits[:N_HIST]
        self.future = self.commits[N_HIST + 1:]
        self._blobs = {}
        self._proc = None


_repos = {}


def get_repo(name):
    if name not in _repos:
        _repos[name] = RepoH(name)
    return _repos[name]


def h(s):
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()


def vhash(v):
    """Compact 64-bit value hash used in the oracle tables (hex, 16 chars)."""
    return hashlib.sha1(str(v).encode("utf-8", "replace")).hexdigest()[:16]
