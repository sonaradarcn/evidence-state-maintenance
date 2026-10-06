"""Clone the 16 held-out repositories at the HEAD commits recorded in facts_<repo>.json, check the 701-commit
first-parent window, and copy the archived oracle tables next to them.

    python heldout/clone_repos.py [repo ...]

Target: $ESM_HELDOUT_DATA (default heldout_data/ at the repository root) with repos/, trees/ (built on first use)
and oracle_tables/.
"""
import json, os, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = Path(os.environ.get("ESM_HELDOUT_DATA", ROOT / "heldout_data"))
HELDOUT = ["boltons", "httpx", "werkzeug", "black", "poetry-core", "jinja", "typer", "marshmallow", "rich", "kombu", "scrapy",
           "networkx", "pyparsing", "mkdocs", "isort", "pygments"]


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def clone(name):
    meta = json.loads((HERE / f"facts_{name}.json").read_text(encoding="utf-8"))
    dest = DATA / "repos" / name
    if not dest.exists():
        git("clone", "--bare", "--quiet", meta["url"] + ".git", str(dest))
    # The window is defined relative to HEAD, so HEAD must be the recorded commit, not the current tip.
    git("-C", str(dest), "update-ref", "--no-deref", "HEAD", meta["head"])
    fp = git("-C", str(dest), "rev-list", "--first-parent", "--reverse", "HEAD").split()
    ok = fp[-len(meta["commits"]):] == meta["commits"]
    print(f"{name:12s} head {meta['head'][:10]}  first-parent {len(fp)}  window {'ok' if ok else 'MISMATCH'}", flush=True)
    return ok


if __name__ == "__main__":
    names = sys.argv[1:] or HELDOUT
    (DATA / "repos").mkdir(parents=True, exist_ok=True)
    src = ROOT / "data" / "heldout_oracle_tables"
    shutil.copytree(src, DATA / "oracle_tables", dirs_exist_ok=True)
    bad = [n for n in names if not clone(n)]
    sys.exit(f"window mismatch: {bad}" if bad else 0)
