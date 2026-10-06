"""Held-out benchmark loader (16 new repositories, heldout/facts_<repo>.json + oracle tables).

`load_heldout_raw()` returns fact dicts WITHOUT a derivation (trace/K come from the s0 agent run, see
`esm/scripts/heldout_s0.py`); `attach_s0(facts, ders)` fills trace / K / cite / derive_tokens from the s0 derivation
store and returns only the facts whose s0 answer matches the oracle (the kept facts).
Repositories, tree caches and oracle tables are read from $ESM_HELDOUT_DATA (default <repo>/heldout_data)."""
import json, os
from pathlib import Path
import pandas as pd
from .. import tools as T
from .pyrepo import PyRepoEnv

ROOT = Path(__file__).resolve().parents[2]
# ESM_HELDOUT_DATA: location of repos/, trees/, oracle_tables/ (built by heldout/; see README)
HD = Path(os.environ.get("ESM_HELDOUT_DATA", ROOT / "heldout_data"))
REPOS = ["boltons", "httpx", "werkzeug", "black", "poetry-core", "jinja", "typer", "marshmallow", "rich", "kombu", "scrapy",
         "networkx", "pyparsing", "mkdocs", "isort", "pygments"]


def git_repos(names=REPOS):
    return {n: T.GitRepo(n, HD / "repos" / n, HD / "trees" / f"{n}.pkl") for n in names}


def _truth_series(repo):
    o = pd.read_parquet(HD / "oracle_tables" / f"oracle_{repo}.parquet")
    v = pd.read_parquet(HD / "oracle_tables" / f"oracle_values_{repo}.parquet")
    vm = {(a, b): c for a, b, c in zip(v.fact_id, v.value_hash, v.value)}
    o = o.sort_values(["fact_id", "commit_idx"])
    out = {}
    for fid, g in o.groupby("fact_id", sort=False):
        assert list(g.commit_idx) == list(range(701)), fid
        out[fid] = [str(vm[(fid, x)]) for x in g.value_hash]
    return out


def load_heldout_raw(names=REPOS):
    facts = []
    for repo in names:
        d = json.loads((ROOT / "heldout" / f"facts_{repo}.json").read_text(encoding="utf-8"))
        tr = _truth_series(repo)
        for f in d["facts"]:
            truth = tr[f["id"]]
            behav = f["type"] == "B"
            K0 = str(f["K"] if behav else f["K_oracle"])
            assert truth[300] == K0 or not behav, (f["id"], truth[300], K0)
            facts.append({"iid": f["id"], "slice": "behav" if behav else "static", "unit": repo, "repo": repo,
                          "type": f["type"], "subset": f["subset"], "same_fact_as": f.get("same_fact_as"),
                          "question": f["question"], "K_oracle": truth[300], "args": f["args"], "truth": truth,
                          "valid0": [truth[301 + i] == truth[300] for i in range(400)],
                          "source": f.get("source"), "n_future_changed": f.get("n_future_changed")})
    return facts


def attach_s0(facts, ders, env):
    """Fill the s0 derivation into each fact; return (kept, all_with_status)."""
    kept = []
    for f in facts:
        r = ders.d.get((f["iid"], 0))
        f["s0"] = r
        if r is None:
            f["s0_status"] = "missing"
            continue
        ok = bool(r["answer"] is not None and env.answer_matches(f, r["answer"], f["truth"][300]))
        f["s0_status"] = "correct" if ok else ("no_answer" if r["answer"] is None else "wrong")
        if not ok:
            continue
        g = dict(f)
        g["K"] = str(r["answer"]).strip()
        g["trace"] = r["trace"]
        g["derive_tokens"] = r["tokens"]
        g["cite"] = env.auto_cites(g, r["trace"], g["K"])
        # validity of the stored s0 answer at every FUTURE commit (canonicalised comparison with the oracle)
        g["valid"] = [env.answer_matches(g, g["K"], g["truth"][301 + i]) for i in range(400)]
        g["certzs"], g["certv0"] = [], None
        kept.append(g)
    return kept


def make_env(facts, names=REPOS, repos=None):
    return PyRepoEnv(facts=facts, repos=repos if repos is not None else git_repos(names), none_hint=True)
