"""Validate the LAZY replay approximation against held-out runs that were actually executed on sparse schedules.

For each recorded sparse run (policy P, schedule S in every5 / every20 / every50 / bursty), the stream engine is applied
to P's EVERY-commit record with the reads placed at S's commits, and its served-wrong rate and tokens per fact are
compared with the recorded S run (which made its own lazy decisions and LLM calls at those reads).
Composed policies: ALWAYS* vs the recorded ALWAYS__every50, FILEHASH* vs the recorded FILEHASH__every50.
Also: leave-one-out check of the re-derivation imputation (predict a recorded re-derivation's correctness from the
nearest OTHER recorded re-derivation of that fact with the same oracle value).

usage: python -m esm.stream.validate -> results/stream/validation.md, validation.json
"""
import json, random
import numpy as np
import pandas as pd
from . import sim as S


def schedule(name, n=400):   # identical to esm.maintain.schedule
    if name == "every":
        return list(range(1, n + 1))
    if name.startswith("every") and name[5:].isdigit():
        k = int(name[5:])
        return list(range(k, n + 1, k))
    if name == "bursty":
        rng = random.Random(7)
        reads = set()
        while len(reads) < 80:
            s = rng.randint(1, n)
            reads.update(range(s, min(n, s + 9) + 1))
        return sorted(reads)[:80]
    raise ValueError(name)


def main():
    facts = S.load_facts()
    H = [i for i in facts if facts[i]["H150"]]
    ALL = list(facts)
    cases = [("H150", "ESM-norepair", "ESM-norepair", s) for s in ("every5", "every20", "every50", "bursty")]
    cases += [("H150", p, p, "every50") for p in ("NEVER", "TTL50", "TTL100", "TTL200", "REPLAY", "CERT-ZS", "CERT-v0", "LLMDIFF")]
    cases += [("H150", "ALWAYS*", "ALWAYS", "every50"), ("H150", "FILEHASH*", "FILEHASH", "every50")]
    cases += [("ALL", p, p, s) for p in ("TTL50@oracle", "TTL100@oracle", "TTL200@oracle", "REPLAY@oracle", "FILEHASH@oracle",
                                          "CITE@oracle", "NEVER") for s in ("every5", "every20", "every50", "bursty")]
    rows, imp_all = [], {}
    for setname in ("H150", "ALL"):
        ids = H if setname == "H150" else ALL
        cs = [c for c in cases if c[0] == setname]
        M, imp = S.build_mats(facts, ids, sorted({c[1] for c in cs}))
        imp_all.update(imp)
        for _, pe, pr, sch in cs:
            rec = S.load_records([pr], set(ids), sch)
            if not len(rec):
                continue
            fids = sorted(set(rec.iid))
            reads = schedule(sch)
            tasks = pd.DataFrame([(f"{i}#{t}", facts[i]["repo"], float(t), t, i) for i in fids for t in reads],
                                 columns=["task", "repo", "time", "t", "iid"])
            x = S.evaluate(tasks, {pe: M[pe]}, ids, facts)[pe]
            nf = len(fids)
            mr = rec.merge(x[["iid", "t", "sv"]], on=["iid", "t"])
            rows.append({"set": setname, "policy": pr, "engine": pe, "schedule": sch, "facts": nf,
                         "rec_sw": 1 - rec.served_valid.mean(), "eng_sw": 1 - x.sv.mean(),
                         "rec_tok_fact": (rec.eval_tok.sum() + rec.der_tok.sum()) / nf,
                         "eng_co_tok_fact": (x.e_co.sum() + x.d_co.sum()) / nf,
                         "eng_sum_tok_fact": (x.e_sum.sum() + x.d_sum.sum()) / nf,
                         "rec_der_fact": rec.n_der.sum() / nf, "eng_der_fact": x.n_co.sum() / nf,
                         "read_agreement": float((mr.served_valid == mr.sv).mean())})
            print(rows[-1], flush=True)
    df = pd.DataFrame(rows)
    # leave-one-out imputation check
    hit = tot = 0
    by = {"exact_t_excluded_same_truth": [0, 0], "fallback_other_truth": [0, 0]}
    for i, fx in facts.items():
        ds = fx["ders"]
        for d in ds:
            rest = [e for e in ds if e is not d]
            if not rest:
                continue
            tr = fx["truth"]
            same = [e for e in rest if tr[e["t"]] == tr[d["t"]]]
            pool = same or rest
            e = min(pool, key=lambda e: (abs(e["t"] - d["t"]), e["t"]))
            pred = e["valid"][d["t"] - 1]
            k = "exact_t_excluded_same_truth" if same else "fallback_other_truth"
            by[k][0] += int(pred == d["correct"])
            by[k][1] += 1
    imp = imp_all
    loo = {k: {"agree": v[0], "n": v[1], "rate": v[0] / max(v[1], 1)} for k, v in by.items()}
    (S.OUT / "validation.json").write_text(json.dumps({"rows": rows, "imputation_kinds": imp, "loo": loo}, indent=1, default=float))
    L = ["# Validation of the lazy-replay approximation\n",
         "Engine = this stage's replay of the EVERY-commit record with reads placed at the schedule's commits; "
         "recorded = the held-out run actually executed on that schedule (its own lazy decisions and LLM calls).\n",
         "| set | policy | schedule | facts | served-wrong % recorded | engine | per-read agreement % | tokens/fact recorded | engine coalesced | engine sum | re-derivations/fact recorded | engine |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['set']} | {S.label(r['engine'])} | {r['schedule']} | {r['facts']} | {100*r['rec_sw']:.1f} | {100*r['eng_sw']:.1f} | "
                 f"{100*r['read_agreement']:.1f} | {r['rec_tok_fact']/1000:.1f}k | {r['eng_co_tok_fact']/1000:.1f}k | "
                 f"{r['eng_sum_tok_fact']/1000:.1f}k | {r['rec_der_fact']:.2f} | {r['eng_der_fact']:.2f} |")
    L.append("\nNote on TTL rows: the recorded sparse TTL runs expire by AGE since the last re-derivation (the clock restarts at "
             "the read that re-derived); the stream uses EPOCH expiry (the answer expires at commits k, 2k, ...; the first read "
             "after an expiry re-derives), which is what the replay of the every-commit record gives. The two coincide on "
             "every5 / every50 and differ on every20 / bursty (the engine then charges more re-derivations than the age-based run).")
    L.append("\nRe-derivation imputation (composed policies), share of imputed re-derivations by kind: "
             + json.dumps({k: {a: round(b, 3) for a, b in v.items()} for k, v in imp.items()}))
    L.append("\nLeave-one-out: a recorded re-derivation's correctness predicted from the nearest other recorded re-derivation "
             "of the same fact (same oracle value when available): "
             + "; ".join(f"{k}: {v['agree']}/{v['n']} = {100*v['rate']:.1f} %" for k, v in loo.items()))
    (S.OUT / "validation.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
