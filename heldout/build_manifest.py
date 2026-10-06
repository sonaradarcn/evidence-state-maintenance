"""Merge static + behaviour facts into heldout/facts_<repo>.json, write compact oracle tables and MANIFEST.md.

  python build_manifest.py

Tables (heldout_data/oracle_tables/):
  oracle_<repo>.parquet         fact_id, commit_idx (0..700; 300 = s0), value_hash (sha1[:16] of the value string),
                                changed (value != value at s0), is_none (value == 'NONE')
  oracle_values_<repo>.parquet  fact_id, value_hash, value  (distinct values; join to recover the full value)
  commits_<repo>.parquet        commit_idx, commit, segment (HISTORY / s0 / FUTURE), committer date
  oracle_all.parquet            all repos concatenated (repo, fact_id, subset, type, commit_idx, value_hash, changed, is_none)
"""
import json, subprocess
from collections import Counter, defaultdict
import pandas as pd
import common_h as C
import behav_h as B

TYPES = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "B"]
S = C.S0


def git_date(name, c):
    return subprocess.run(["git", "-C", str(C.REPOS / name), "log", "-1", "--format=%cs", c], capture_output=True, text=True).stdout.strip()


def main():
    bd = json.loads((B.BDIR / "behav_facts.json").read_text(encoding="utf-8"))
    btruth = json.loads((B.BDIR / "behav_truth_selected.json").read_text(encoding="utf-8"))
    bfacts = defaultdict(list)
    for f in bd["facts"]:
        bfacts[f["repo"]].append(f)
    allrows = []
    per_repo = []
    allfacts = []
    for name in C.HELDOUT:
        d = json.loads((C.OUT / f"facts_{name}.static.json").read_text(encoding="utf-8"))
        sv = pd.read_parquet(C.TABLES / f"static_{name}.values.parquet")
        series = {fid: g.sort_values("commit_idx")["value"].tolist() for fid, g in sv.groupby("fact_id")}
        for f in bfacts.get(name, []):
            series[f["id"]] = btruth[f["id"]]
        facts = d["facts"] + bfacts.get(name, [])
        # sanity: series length and s0 value == K
        for f in facts:
            s = series[f["id"]]
            assert len(s) == len(d["commits"]) == 701, (f["id"], len(s))
            assert s[S] == f["K_oracle"], (f["id"], s[S], f["K_oracle"])
            fut = s[S + 1:]
            diff = [v for v in fut if v != s[S]]
            f["future_invalid_frac"] = round(len(diff) / len(fut), 4)
            f["change_only_by_disappearance"] = bool(diff) and all(v == "NONE" for v in diff)
            f["first_future_change"] = next((i for i, v in enumerate(fut, 1) if v != s[S]), None)
            f["changes_to_other_value"] = any(v != "NONE" for v in diff)       # differs from s0 by a real (non-NONE) value
            f["transient_none_only"] = bool(diff) and all(v == "NONE" for v in diff) and fut[-1] == s[S]   # breaks, then recovers
            f["n_distinct_future_values"] = len(set(fut))
        rows_c, vals = [], {}
        for f in facts:
            for i, v in enumerate(series[f["id"]]):
                hv = C.vhash(v)
                vals[(f["id"], hv)] = v
                rows_c.append((f["id"], f["subset"], f["type"], i, hv, v != f["K_oracle"], v == "NONE"))
        df = pd.DataFrame(rows_c, columns=["fact_id", "subset", "type", "commit_idx", "value_hash", "changed", "is_none"])
        df[["fact_id", "commit_idx", "value_hash", "changed", "is_none"]].to_parquet(C.TABLES / f"oracle_{name}.parquet", index=False)
        pd.DataFrame([(a, b, v) for (a, b), v in vals.items()], columns=["fact_id", "value_hash", "value"]).to_parquet(
            C.TABLES / f"oracle_values_{name}.parquet", index=False)
        seg = ["HISTORY"] * S + ["s0"] + ["FUTURE"] * (701 - S - 1)
        pd.DataFrame({"commit_idx": range(701), "commit": d["commits"], "segment": seg}).to_parquet(C.TABLES / f"commits_{name}.parquet", index=False)
        df.insert(0, "repo", name)
        allrows.append(df)
        bst = bd["stats"].get(name)
        out = dict(d)
        out["layout"] = {"n_history": S, "s0_idx": S, "n_future": 400, "commits": "first-parent, oldest first; index 300 = s0"}
        out["stats"] = {"static": d["stats"], "behaviour": bst}
        out["facts"] = facts
        if name in B.BEHAV:
            out["behaviour_runtime"] = {"python": "3.14.5 (-S -B)", "import_tops": B.BEHAV[name][0], "deps_dir": f"heldout_data/deps/{B.BEHAV[name][1]}",
                                        "import_root_at_s0": B.import_root(name)}
        (C.OUT / f"facts_{name}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
        per_repo.append({"repo": name, "url": d["url"], "n_fp": d["n_first_parent"], "s0": d["s0"], "head": d["head"],
                         "first": d["first_history"], "d_first": git_date(name, d["first_history"]), "d_s0": git_date(name, d["s0"]),
                         "d_head": git_date(name, d["head"]), "facts": facts})
        allfacts += facts
    pd.concat(allrows).to_parquet(C.TABLES / "oracle_all.parquet", index=False)
    write_manifest(per_repo, allfacts, bd["stats"])


def pct(x):
    return f"{100 * x:.1f}"


def rate_table(facts, label=""):
    lines = [f"| type | n enriched | changes in FUTURE % (enr.) | ... to a non-NONE value % (enr.) | invalid FUTURE pairs % (enr.) | n natural | changes in FUTURE % (nat.) | ... to a non-NONE value % (nat.) | invalid FUTURE pairs % (nat.) | natural changing: only by disappearance / of which transient |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for t in TYPES + ["all static", "all"]:
        sel = lambda sub: [f for f in facts if f["subset"] == sub and (f["type"] == t or (t == "all") or (t == "all static" and f["type"] != "B"))]
        e, n = sel("enriched"), sel("natural")
        if not e and not n:
            continue
        ce = sum(f["n_future_changed"] > 0 for f in e)
        cn = sum(f["n_future_changed"] > 0 for f in n)
        dn = sum(f["change_only_by_disappearance"] for f in n)
        oe = sum(f["changes_to_other_value"] for f in e)
        on = sum(f["changes_to_other_value"] for f in n)
        tn = sum(f["transient_none_only"] for f in n)
        lines.append(f"| {t} | {len(e)} | {pct(ce / max(1, len(e)))} | {pct(oe / max(1, len(e)))} | {pct(sum(f['future_invalid_frac'] for f in e) / max(1, len(e)))} | {len(n)} | "
                     f"{pct(cn / max(1, len(n)))} | {pct(on / max(1, len(n)))} | {pct(sum(f['future_invalid_frac'] for f in n) / max(1, len(n)))} | {dn} / {tn} of {cn} |")
    return lines


def write_manifest(per_repo, allfacts, bstats):
    L = ["# Held-out benchmark manifest", "",
         "Generated by `build_manifest.py` (no LLM, no GPU). Protocol identical to the dev set (pilot3/pilot6): first-parent history of the "
         "default branch, s0 = HEAD - 400 first-parent commits, HISTORY = 300 commits before s0, FUTURE = 400 commits after s0 "
         "(701 commits per repo, index 300 = s0). Oracle values exist for every fact at all 701 commits (NONE = referent gone).", "",
         "Development repos excluded: requests, flask, click, pytest, seaborn, xarray (pilot3), packaging, more-itertools, attrs (pilot6 "
         "behaviour slice); toolz (cloned in pilot6_data, unused) excluded as well.", "",
         "## Repositories", "",
         "| repo | URL | first-parent commits | HISTORY start | s0 | HEAD | static enriched (chg) | static natural (chg) | behaviour enriched (chg) | behaviour natural (chg) |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for r in per_repo:
        fs = r["facts"]
        c = lambda sub, b: (sum(1 for f in fs if f["subset"] == sub and (f["type"] == "B") == b),
                            sum(1 for f in fs if f["subset"] == sub and (f["type"] == "B") == b and f["n_future_changed"] > 0))
        se, sn, be, bn = c("enriched", False), c("natural", False), c("enriched", True), c("natural", True)
        beh = lambda x: f"{x[0]} ({x[1]})" if r["repo"] in B.BEHAV else "–"
        L.append(f"| {r['repo']} | {r['url']} | {r['n_fp']} | {r['d_first']} `{r['first'][:10]}` | {r['d_s0']} `{r['s0'][:10]}` | "
                 f"{r['d_head']} `{r['head'][:10]}` | {se[0]} ({se[1]}) | {sn[0]} ({sn[1]}) | {beh(be)} | {beh(bn)} |")
    st = [f for f in allfacts if f["type"] != "B"]
    bh = [f for f in allfacts if f["type"] == "B"]
    tot = lambda fs, sub: (sum(f["subset"] == sub for f in fs), sum(f["subset"] == sub and f["n_future_changed"] > 0 for f in fs))
    L += ["", f"Full 40-char hashes of s0 / HEAD / every commit: `facts_<repo>.json` (`s0`, `head`, `commits`) and `heldout_data/oracle_tables/commits_<repo>.parquet`.", "",
          "## Totals", "",
          "| slice | enriched facts (changing in FUTURE) | natural facts (changing in FUTURE) | total |", "|---|---|---|---|",
          f"| static (T1–T7) | {tot(st, 'enriched')[0]} ({tot(st, 'enriched')[1]}) | {tot(st, 'natural')[0]} ({tot(st, 'natural')[1]}) | {len(st)} |",
          f"| behaviour (B) | {tot(bh, 'enriched')[0]} ({tot(bh, 'enriched')[1]}) | {tot(bh, 'natural')[0]} ({tot(bh, 'natural')[1]}) | {len(bh)} |",
          f"| all | {tot(allfacts, 'enriched')[0]} ({tot(allfacts, 'enriched')[1]}) | {tot(allfacts, 'natural')[0]} ({tot(allfacts, 'natural')[1]}) | {len(allfacts)} |", "",
          f"Facts appearing in both subsets (same type+args / same expression): {sum(1 for f in allfacts if f['subset'] == 'natural' and f['same_fact_as'])} "
          "(kept in both; `same_fact_as` links them).", "",
          "## Base rate of truth change within FUTURE, by type and subset", "",
          "\"changes in FUTURE\" = fraction of facts whose oracle value differs from the s0 value at >= 1 of the 400 FUTURE commits. "
          "\"invalid FUTURE pairs\" = mean over facts of the fraction of FUTURE commits at which the value differs from s0. "
          "\"change only by disappearance\" = changing natural facts whose every differing FUTURE value is NONE (file/symbol moved or deleted).", ""]
    L += rate_table(allfacts, "")
    # reference per-type natural rates (larger uniform samples, stats only)
    ref = defaultdict(lambda: [0, 0.0])
    for r in per_repo:
        d = json.loads((C.OUT / f"facts_{r['repo']}.static.json").read_text(encoding="utf-8"))
        for t, v in d["stats"]["reference"].items():
            ref[t][0] += v["n"]
            ref[t][1] += v["n"] * v["frac_changing_future"]
    L += ["", "Reference natural base rates from larger uniform samples (up to 120 eligible candidates per type per repo, not facts; "
          "`heldout_data/oracle_tables/static_<repo>.reference.parquet`):", "",
          "| type | n sampled | changes in FUTURE % |", "|---|---|---|"]
    for t in ["T1", "T2", "T3", "T4", "T5", "T6", "T7"]:
        n, s = ref[t]
        L.append(f"| {t} | {n} | {pct(s / max(1, n))} |")
    # ever change
    ev = lambda fs: sum(1 for f in fs if f["n_future_changed"] > 0 or f["n_history_changed"] > 0)
    L += ["", "## How many facts ever change", "",
          f"* FUTURE (vs s0): {sum(f['n_future_changed'] > 0 for f in allfacts)} / {len(allfacts)} facts "
          f"(static {sum(f['n_future_changed'] > 0 for f in st)} / {len(st)}, behaviour {sum(f['n_future_changed'] > 0 for f in bh)} / {len(bh)}).",
          f"* HISTORY or FUTURE differs from s0: {ev(allfacts)} / {len(allfacts)} (static {ev(st)}, behaviour {ev(bh)}).",
          f"* Value is NONE at HEAD (referent gone by the end of FUTURE): {sum(f['none_at_future_end'] for f in allfacts)} facts.", "",
          "## Behaviour candidate funnel (per repo)", "",
          "| repo | probed at s0 | deterministic & valid at s0 | valid after truth re-run (s0 re-run identical) | dropped I/O-error values | valid pool changing in FUTURE % | sources (doctest / synth) |",
          "|---|---|---|---|---|---|---|"]
    for name, s in bstats.items():
        L.append(f"| {name} | {s['n_probed']} | {s['n_ok_at_s0']} | {s['n_valid']} | {s['n_io_raises_dropped']} | {pct(s['valid_frac_changing'])} | "
                 f"{s['by_source'].get('doctest', 0)} / {s['by_source'].get('synth', 0)} |")
    L += ["", "## Repositories considered and dropped", "",
          "All candidates were cloned in full from github.com directly (no mirror needed). Required: >= 800 first-parent commits on the default branch.", "",
          "| repo | first-parent commits | reason |", "|---|---|---|",
          "| tqdm/tqdm | 445 | < 800 first-parent commits |", "| python-poetry/tomlkit | 454 | < 800 |",
          "| dateutil/dateutil | 636 | < 800 |", "| executablebooks/markdown-it-py | 353 | < 800 |",
          "| grantjenks/python-sortedcontainers | 611 | < 800 |", "| python-humanize/humanize | 448 | < 800 |",
          "| arrow-py/arrow | 813 | eligible; dropped to keep 16 repos: smallest (21 .py files), s0 in 2017, HISTORY from 2013 (py2-era code that does not parse/import under 3.14) |",
          "| pydantic, sqlalchemy, pip, pillow | – | not cloned: compiled core / very large / vendored code (as anticipated in the brief) |", "",
          "Behaviour slice: 9 of the 16 repos (pure-Python, importable from a checkout with at most a few fixed released dependencies). Not in it: "
          "httpx, black, typer, kombu, scrapy, mkdocs (runtime dependencies) and pyparsing (no `>>>` doctests; 3 synthesised candidates, all "
          "in a module needing an uninstalled dependency).", "",
          "## Validation", "", "See `VALIDATION.md`: 20 static + 10 behaviour facts, 5 random commits each, recomputed from real `git worktree` "
          "checkouts in a fresh process: 150/150 values match. (No T7 fact happened to be drawn; T1-T6 and B are covered.)"]
    (C.OUT / "MANIFEST.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
