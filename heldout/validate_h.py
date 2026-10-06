"""Independent re-computation of the oracle for a random sample of facts x commits.

  python validate_h.py [n_static=20] [n_behav=10] [commits_per_fact=5]

Independence from the main pass:
  * files come from a real `git worktree add --detach` checkout of the commit (core.autocrlf=false), read from disk -- not from the
    701-commit tree cache, not from the `git cat-file --batch` blob reader, and in a fresh process (no AST / summary / index caches);
  * static: pilot3's facts.oracle() itself (T5/dir by iterating paths, not the dircount fast path used in static_h.py);
  * behaviour: the expression is executed in a fresh subprocess with PYTHONPATH = <checkout>/<import root> (+ the same fixed deps
    dir), i.e. against the checkout's own package directory rather than the materialised package-state dir, and without result cache.
Writes heldout/VALIDATION.md and heldout_data/validation.json.
"""
import json, os, random, shutil, subprocess, sys, tempfile, time
from pathlib import Path
import pandas as pd
import common_h as C
from common_h import FX, vfs
import behav_h as B

WT = C.DATA / "validate_wt"


class FSRepo:
    def __init__(self, name, commit):
        self.name, self.commit = name + "@fs", commit


class FSWorld:
    """World over a checked-out directory (same interface as vfs.World for the oracle)."""

    def __init__(self, name, commit, root):
        self.repo, self.commit, self.overlay = FSRepo(name, commit), commit, {}
        self.root = Path(root)
        self.tree = {}
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d != ".git"]
            for f in fns:
                full = Path(dp) / f
                rel = full.relative_to(self.root).as_posix()
                if rel == ".git":
                    continue
                self.tree[rel] = None
        self._txt = {}

    def text(self, p):
        if p not in self.tree:
            return None
        if p not in self._txt:
            b = (self.root / p).read_bytes()
            self._txt[p] = b.decode("utf-8", "replace").replace("\r\n", "\n")
        return self._txt[p]

    def sha(self, p):
        t = self.text(p)
        return None if t is None else "fs:" + C.vhash(self.root.as_posix() + "|" + p) + C.vhash(t)

    def paths(self):
        return self.tree.keys()


def checkout(name, commit):
    d = WT / f"{name}_{commit[:10]}"
    if d.exists():
        return d
    WT.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(C.REPOS / name), "-c", "core.autocrlf=false", "-c", "core.symlinks=false", "worktree", "add",
                    "--detach", "--force", str(d), commit], check=True, capture_output=True)
    return d


def drop(name, d):
    subprocess.run(["git", "-C", str(C.REPOS / name), "worktree", "remove", "--force", str(d)], capture_output=True)
    shutil.rmtree(d, ignore_errors=True)


def load_static_values(name):
    df = pd.read_parquet(C.TABLES / f"static_{name}.values.parquet")
    return {(r.fact_id, r.commit_idx): r.value for r in df.itertuples()}


def main(n_static=20, n_behav=10, k=5):
    rng = random.Random(20261002)
    sfacts = []
    for name in C.HELDOUT:
        d = json.loads((C.OUT / f"facts_{name}.static.json").read_text(encoding="utf-8"))
        sfacts += [(name, f, d["commits"]) for f in d["facts"]]
    bd = json.loads((B.BDIR / "behav_facts.json").read_text(encoding="utf-8"))
    btruth = json.loads((B.BDIR / "behav_truth_selected.json").read_text(encoding="utf-8"))
    bfacts = [(f["repo"], f, None) for f in bd["facts"]]
    pick = rng.sample(sfacts, n_static) + rng.sample(bfacts, n_behav)
    svals = {}
    rows = []
    t0 = time.time()
    for name, f, commits in pick:
        repo = C.get_repo(name)
        idxs = sorted(rng.sample(range(len(repo.commits)), k))
        for i in idxs:
            cm = repo.commits[i]
            d = checkout(name, cm)
            try:
                if f["type"] == "B":
                    stored = btruth[f["id"]][i]
                    top = B.BEHAV[name][0][0]
                    w = FSWorld(name, cm, d)
                    inits = sorted((p for p in w.paths() if (p == f"{top}/__init__.py" or p.endswith(f"/{top}/__init__.py"))
                                    and p[: -len(f"{top}/__init__.py")].count("/") <= 1), key=len)
                    if not inits:
                        recomputed = "NONE"
                    else:
                        root = d / inits[0][: -len(f"{top}/__init__.py")]
                        a = f["args"]
                        r = B.run_jobs(name, root, [{"id": "x", "module": a["module"], "func": a["func"], "expr": a["expr"]}])
                        recomputed = r["x"]
                else:
                    if name not in svals:
                        svals[name] = load_static_values(name)
                    stored = svals[name][(f["id"], i)]
                    recomputed = FX.oracle(FSWorld(name, cm, d), f)
            finally:
                drop(name, d)
            rows.append({"fact_id": f["id"], "type": f["type"], "repo": name, "commit_idx": i, "commit": cm,
                         "stored": stored, "recomputed": recomputed, "match": stored == recomputed})
            print(f["id"], i, "OK" if stored == recomputed else f"MISMATCH stored={stored[:80]!r} recomputed={recomputed[:80]!r}", flush=True)
    n = len(rows)
    m = sum(r["match"] for r in rows)
    (C.DATA / "validation.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    lines = ["# Held-out oracle validation", "",
             f"{n_static} static + {n_behav} behaviour facts drawn at random (seed 20261002) from all held-out facts; {k} random commits each "
             f"(from the 701 HISTORY+s0+FUTURE commits). Each value was recomputed from a real `git worktree` checkout (see validate_h.py "
             f"docstring for what is independent of the main pass).", "",
             f"**{m}/{n} (fact, commit) values match** ({time.time()-t0:.0f}s).", "",
             "| fact | type | commit idx | stored | recomputed | match |", "|---|---|---|---|---|---|"]
    for r in rows:
        s = lambda v: str(v).replace("|", "\\|").replace("\n", " ")[:60]
        lines.append(f"| {r['fact_id']} | {r['type']} | {r['commit_idx']} | `{s(r['stored'])}` | `{s(r['recomputed'])}` | {'yes' if r['match'] else '**NO**'} |")
    (C.OUT / "VALIDATION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{m}/{n} match")


if __name__ == "__main__":
    a = [int(x) for x in sys.argv[1:]]
    main(*a)
