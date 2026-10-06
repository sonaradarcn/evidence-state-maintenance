"""STATIC held-out facts (types T1-T7, pilot3 oracles, unmodified) for one repo.

  python static_h.py <repo>

Two subsets per repo:
  enriched : pilot3's dev-set protocol (facts.sample_facts): per type, candidates shuffled, half the sort keys biased towards files
             modified often in HISTORY, pool of <= 250 candidates per type, then >= half of the picks (where possible) are facts
             whose oracle value changes within FUTURE.  PER_TYPE = 6 -> <= 42 facts.
  natural  : N_NATURAL facts sampled uniformly at random from ALL eligible candidates (all types pooled; eligible = enumerated at
             s0 by pilot3's enumerate_candidates and oracle(s0) != NONE).  Selection never looks at HISTORY or FUTURE.
  reference (stats only, not facts): up to N_REF uniformly sampled eligible candidates per type -> natural per-type base rates.

Oracle values are computed for every selected fact at all 701 commits (HISTORY 300 + s0 + FUTURE 400), commit-outer loop.
Outputs: heldout/facts_<repo>.static.json (merged into facts_<repo>.json by build_manifest.py) and
         heldout_data/oracle_tables/static_<repo>.values.parquet (fact_id, commit_idx, value).
"""
import json, random, sys, time
from collections import Counter
import common_h as C
from common_h import FX, vfs

PER_TYPE, POOL_PER_TYPE, N_NATURAL, N_REF = 6, 250, 40, 120
TYPES = ["T1", "T2", "T3", "T4", "T5", "T6", "T7"]
NONE = FX.NONE


def akey(t, a):
    return t + "|" + json.dumps(a, sort_keys=True)


def oracle_fast(w, f, idx):
    """FX.oracle, except T5/dir uses the per-commit dircount index (same definition: number of *.py paths whose dirname == dir)."""
    if f["type"] == "T5" and f["args"]["sub"] == "dir":
        n = idx["dircount"].get(f["args"]["dir"], 0)
        return str(n) if n else NONE
    return FX.oracle(w, f)


def series_for(repo, facts, commits):
    """{akey: [value per commit]} -- commit-outer so each commit index is built once."""
    out = {k: [] for k in facts}
    for i, c in enumerate(commits):
        if len(vfs._ast_cache) > 4000:
            vfs._ast_cache.clear()
        w = repo.world(c)
        idx = FX.commit_index(w)
        for k, f in facts.items():
            out[k].append(oracle_fast(w, f, idx))
    return out


def main(name):
    t0 = time.time()
    repo = C.get_repo(name)
    w0 = repo.world(repo.s0)
    cands = FX.enumerate_candidates(w0)
    idx0 = FX.commit_index(w0)
    # ---- eligible pool (s0 value != NONE)
    elig = {}
    for t in TYPES:
        for a in cands.get(t, []):
            f = {"type": t, "args": a}
            k = oracle_fast(w0, f, idx0)
            if k != NONE:
                elig[akey(t, a)] = (t, a, k)
    n_cands = {t: len(cands.get(t, [])) for t in TYPES}
    n_elig = Counter(v[0] for v in elig.values())
    print(name, "candidates", n_cands, "eligible", dict(n_elig), f"{time.time()-t0:.0f}s", flush=True)

    # ---- enriched pools (pilot3 protocol)
    rng = random.Random(0)
    hot = Counter()
    for a, b in zip(repo.history, repo.history[1:] + [repo.s0]):
        ta, tb = repo.trees[a], repo.trees[b]
        for p in set(ta) | set(tb):
            if ta.get(p) != tb.get(p):
                hot[p] += 1
    pools = {}
    for t in TYPES:
        cs = list(cands.get(t, []))
        rng.shuffle(cs)
        cs.sort(key=lambda a: -hot.get(FX.fact_file(t, a), 0) if rng.random() < 0.5 else 0)
        pools[t] = cs[:POOL_PER_TYPE]
    # ---- natural sample (uniform over all eligible, pooled; no HISTORY/FUTURE information)
    rn = random.Random(int(C.h(f"heldout-natural|{name}")[:8], 16))
    elig_keys = sorted(elig)
    nat_keys = rn.sample(elig_keys, min(N_NATURAL, len(elig_keys)))
    # ---- per-type uniform reference sample (stats only)
    rr = random.Random(int(C.h(f"heldout-ref|{name}")[:8], 16))
    ref_keys = []
    for t in TYPES:
        ks = [k for k in elig_keys if elig[k][0] == t]
        ref_keys += rr.sample(ks, min(N_REF, len(ks)))
    # ---- evaluate everything needed, all 701 commits
    todo = {}
    for t in TYPES:
        for a in pools[t]:
            todo[akey(t, a)] = {"type": t, "args": a}
    for k in nat_keys + ref_keys:
        t, a, _ = elig[k]
        todo[k] = {"type": t, "args": a}
    print(name, "evaluating", len(todo), "facts x", len(repo.commits), "commits", flush=True)
    ser = series_for(repo, todo, repo.commits)
    print(name, f"series done {time.time()-t0:.0f}s", flush=True)
    S = C.S0

    def nchg(k):
        s = ser[k]
        return sum(1 for v in s[S + 1:] if v != s[S])

    # ---- enriched selection (pilot3 sample_facts logic)
    facts, stats = [], {"n_candidates": n_cands, "n_eligible": dict(n_elig), "enriched": {}, "reference": {}}
    for t in TYPES:
        evals = []
        for a in pools[t]:
            k = akey(t, a)
            if ser[k][S] == NONE:
                continue
            evals.append((a, ser[k][S], nchg(k)))
        stats["enriched"][t] = {"n_candidates": n_cands[t], "pool": len(evals),
                                "pool_frac_changing": round(sum(1 for e in evals if e[2] > 0) / max(1, len(evals)), 3)}
        chg = [e for e in evals if e[2] > 0]
        stay = [e for e in evals if e[2] == 0]
        n_c = min(len(chg), max((PER_TYPE + 1) // 2, PER_TYPE - len(stay)))
        pick = rng.sample(chg, n_c) + rng.sample(stay, min(len(stay), PER_TYPE - n_c))
        for a, k, nc in pick:
            fid = f"{name}:{t}:{len(facts)}"
            f = {"id": fid, "repo": name, "type": t, "args": a, "K_oracle": k, "n_future_changed": nc, "subset": "enriched"}
            f["question"] = FX.question(f)
            facts.append(f)
    # ---- natural facts
    for j, k in enumerate(nat_keys):
        t, a, kv = elig[k]
        assert ser[k][S] == kv
        fid = f"{name}:{t}:n{j}"
        f = {"id": fid, "repo": name, "type": t, "args": a, "K_oracle": kv, "n_future_changed": nchg(k), "subset": "natural"}
        f["question"] = FX.question(f)
        facts.append(f)
    # ---- overlap flags, history stats
    ek = {akey(f["type"], f["args"]): f["id"] for f in facts if f["subset"] == "enriched"}
    nk = {akey(f["type"], f["args"]): f["id"] for f in facts if f["subset"] == "natural"}
    for f in facts:
        k = akey(f["type"], f["args"])
        other = nk if f["subset"] == "enriched" else ek
        f["same_fact_as"] = other.get(k)
        s = ser[k]
        f["n_history_changed"] = sum(1 for v in s[:S] if v != s[S])
        f["none_at_future_end"] = s[-1] == NONE
        f["file_hot_history"] = hot.get(FX.fact_file(f["type"], f["args"]), 0)
    # ---- reference base rates
    for t in TYPES:
        ks = [k for k in ref_keys if elig[k][0] == t]
        stats["reference"][t] = {"n": len(ks), "frac_changing_future": round(sum(1 for k in ks if nchg(k) > 0) / max(1, len(ks)), 3)}
    ks = ref_keys
    # ---- write
    import pandas as pd
    rows_f, rows_c, rows_v = [], [], []
    for f in facts:
        s = ser[akey(f["type"], f["args"])]
        for i, v in enumerate(s):
            rows_f.append(f["id"]); rows_c.append(i); rows_v.append(v)
    C.TABLES.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"fact_id": rows_f, "commit_idx": rows_c, "value": rows_v}).to_parquet(C.TABLES / f"static_{name}.values.parquet", index=False)
    # reference series kept too (stats provenance), small
    rf, rc, rv, rt = [], [], [], []
    for k in ref_keys:
        for i, v in enumerate(ser[k]):
            rf.append(k); rc.append(i); rv.append(v)
    pd.DataFrame({"ref_key": rf, "commit_idx": rc, "value": rv}).to_parquet(C.TABLES / f"static_{name}.reference.parquet", index=False)
    out = {"repo": name, "url": f"https://github.com/{C.REPO_URLS[name]}", "s0": repo.s0, "head": repo.commits[-1],
           "first_history": repo.commits[0], "n_first_parent": repo.n_first_parent, "commits": repo.commits,
           "stats": stats, "facts": facts}
    (C.OUT / f"facts_{name}.static.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    ne = sum(f["subset"] == "enriched" for f in facts)
    print(name, "facts enriched", ne, "natural", len(facts) - ne, "changing enriched",
          sum(f["n_future_changed"] > 0 for f in facts if f["subset"] == "enriched"),
          "natural", sum(f["n_future_changed"] > 0 for f in facts if f["subset"] == "natural"), f"{time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
