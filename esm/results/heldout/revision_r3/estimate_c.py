"""Re-compute estimate C of the anchor-expiry analysis (item6 section 6d; paper Table 9 last
column, Supplementary Table S4a C rows) with the CONSECUTIVE-pair repeat statistic of revision_r2/repeat_error.py instead of
item6's superseded all-pairs statistic.  Zero LLM, zero GPU.

Model C: P(forced re-derivation correct | the derivation that produced the current anchor was right/wrong, truth equal /
different at the two commits).  item6 estimated the four cells from ALL pairs i < j of 27B derivations of the same fact
(pooled store; 10.7 % after a wrong one with the truth unchanged).  Here the cells come from consecutive derivations
(previous -> next only) of the MAIN run (s0 + the frozen ESM's own re-derivations, ALL, every commit) = repeat_error.py
definition D (10.9 %), because the hybrid is ESM plus forced re-derivations and its anchors are exactly these derivations.
The pooled-store consecutive variant (definition B, 9.5 %) is reported as a sensitivity row (not used in the paper).

Everything else is item6_anchoring.py unchanged: the same derivation store (shards up to item6's generation time, as in
repeat_error.py), the same segments, real outcomes where a recorded 27B derivation exists at (fact, expiry commit), the
same token model.  Estimates A and B and the old C are re-computed and checked against item6.json before C is replaced.
Output: estimate_c.md, estimate_c.json."""
import json, sys
from collections import Counter
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "revision_r1"))
from r1_common import *                    # noqa  (defines its own HERE = revision_r1)
OUTDIR = Path(__file__).resolve().parent

CUT = 1791129720.0          # item6.md generation time (same cut-off as revision_r2/repeat_error.py)
MAIN = f"{FROZEN}|every"

# ------------------------------------------------------------------ derivation store (as item6 / repeat_error)
rows = []
for p in [DATA_DIR / "derivations.jsonl"] + sorted(DATA_DIR.glob("derivations.*.jsonl")):
    if p.stat().st_mtime > CUT:
        continue
    for l in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not l.strip():
            continue
        try:
            r = json.loads(l)
        except Exception:
            continue
        if r["iid"] in FX:
            rows.append({"iid": r["iid"], "t": int(r["t"]), "c": bool(r["correct"]), "tok": sum(r["tokens"])})
der = pd.DataFrame(rows).drop_duplicates(["iid", "t"])
der["none"] = [truth(i, t) == "NONE" for i, t in zip(der.iid, der.t)]
dpos = der[der.t > 0].copy()
dpos["bin"] = (dpos.t - 1) // 50
pA = dpos.groupby("bin").c.mean().to_dict()
pB = dpos.groupby(["bin", "none"]).c.mean().to_dict()
tokbin = dpos.groupby("bin").tok.mean().to_dict()
REAL = {(r.iid, r.t): r.c for r in der.itertuples()}

# main-run membership (repeat_error.py): s0, or a t > 0 derivation that the frozen ESM (every commit) triggered
rec = pd.read_parquet(REC_PATH, columns=["policy", "schedule", "iid", "t", "n_der"])
rec = rec[(rec.n_der > 0) & rec.iid.isin(ALL) & (rec.policy == FROZEN) & (rec.schedule == "every")]
main_keys = set(zip(rec.iid, rec.t))
der["main"] = [(t == 0) or ((i, t) in main_keys) for i, t in zip(der.iid, der.t)]


def cells(D, mode):
    """P(next right | prev right/wrong, truth equal at both commits / not); mode 'all' = item6 (every i < j), 'next' = consecutive."""
    n, h = Counter(), Counter()
    for iid, x in D.sort_values("t").groupby("iid"):
        xs = x.to_dict("records")
        for i in range(len(xs)):
            js = range(i + 1, len(xs)) if mode == "all" else range(i + 1, min(i + 2, len(xs)))
            for j in js:
                k = (xs[i]["c"], truth(iid, xs[i]["t"]) == truth(iid, xs[j]["t"]))
                n[k] += 1; h[k] += xs[j]["c"]
    return {k: h[k] / n[k] for k in n}, dict(n)


PC = {"C_old": cells(der, "all"), "C": cells(der[der.main], "next"), "C_pooled": cells(der, "next")}

d = records(FROZEN, "every", columns=["iid", "t", "action", "served_valid"])
d = d[d.iid.isin(ALL)].sort_values(["iid", "t"]).reset_index(drop=True)


def p_at(model, iid, te, origin_t, origin_ok):
    if (iid, te) in REAL:
        return float(REAL[(iid, te)]), True
    b = min((te - 1) // 50, 7)
    if model == "A":
        return pA[b], False
    if model == "B":
        return pB.get((b, truth(iid, te) == "NONE"), pA[b]), False
    same = truth(iid, te) == truth(iid, origin_t)
    return PC[model][0][(origin_ok, same)], False


def hybrid(N, model, ids, only_rederived=False, optimistic=False):
    """item6_anchoring.hybrid, unchanged."""
    tot_wrong, base_wrong, n_exp, n_real, tok = 0.0, 0, 0, 0, 0.0
    removed, introduced = 0.0, 0.0
    for iid, x in d[d.iid.isin(ids)].groupby("iid", sort=False):
        ts, sv, ac = x.t.to_numpy(), x.served_valid.to_numpy(), x.action.to_numpy()
        tr = [truth(iid, t) for t in ts]
        anchors = [(0, True)] + [(int(ts[k]), bool(sv[k])) for k in range(len(ts)) if ac[k] == "rederive"]
        bounds = [a for a, _ in anchors[1:]] + [401]
        base_wrong += int((~sv).sum())
        for (a, a_ok), nxt in zip(anchors, bounds):
            exps = [e for e in range(a + N, nxt, N) if e <= 400]
            if only_rederived and a == 0:
                exps = []
            if not exps:
                seg = (ts >= max(a, 1)) & (ts < nxt)
                tot_wrong += (~sv[seg]).sum()
                continue
            seg0 = (ts >= max(a, 1)) & (ts < exps[0])
            tot_wrong += (~sv[seg0]).sum()
            for j, e in enumerate(exps):
                end = exps[j + 1] if j + 1 < len(exps) else nxt
                m = (ts >= e) & (ts < end)
                p, real = p_at(model, iid, e, a, a_ok)
                n_exp += 1; n_real += real
                tok += tokbin[min((e - 1) // 50, 7)]
                te = truth(iid, e)
                wrong_if_ok = sum(1 for k in np.where(m)[0] if tr[k] != te)
                exp_wrong = (0 if optimistic else p * wrong_if_ok) + (1 - p) * m.sum()
                act_wrong = (~sv[m]).sum()
                tot_wrong += exp_wrong
                if exp_wrong < act_wrong:
                    removed += act_wrong - exp_wrong
                else:
                    introduced += exp_wrong - act_wrong
    nf = len(ids)
    return {"sw": tot_wrong / (400 * nf), "base_sw": base_wrong / (400 * nf), "removed": removed, "introduced": introduced,
            "exp_per_fact": n_exp / nf, "real_frac": n_real / max(n_exp, 1), "tok_per_fact": tok / nf, "base_wrong": base_wrong}


# wrong reads in wrong-re-derivation episodes (item6 6b), for the 'removed as %' column: taken from item6.json-compatible recount
def wrong_rederive_reads(ids):
    n = 0
    for iid, x in d[d.iid.isin(ids)].groupby("iid", sort=False):
        sv, ac = x.served_valid.to_numpy(), x.action.to_numpy()
        k = 0
        while k < len(sv):
            if sv[k]:
                k += 1; continue
            s = k
            while k < len(sv) and not sv[k]:
                k += 1
            if ac[s] == "rederive":
                n += k - s
    return n


H6 = json.loads((HERE.parent / "revision_r1" / "item6.json").read_text(encoding="utf-8"))["hybrid"]
VARIANTS = (("all anchors", {}), ("re-derived anchors only", {"only_rederived": True}),
            ("all anchors, optimistic", {"optimistic": True}), ("re-derived only, optimistic", {"only_rederived": True, "optimistic": True}))
OUT, check = {"pC": {}, "pairs": {}, "hybrid": {}}, []
for m, (pc, n) in PC.items():
    OUT["pC"][m] = {str(k): v for k, v in pc.items()}; OUT["pairs"][m] = {str(k): v for k, v in n.items()}

L = ["# Round 3, must-fix 2 - estimate C of the anchor-expiry analysis with the consecutive-pair statistic (generated by estimate_c.py)\n",
     "Model C cells (P(next derivation correct | previous derivation right/wrong, truth equal/different at the two commits)):\n",
     "| statistic | prev wrong, truth unchanged | prev wrong, truth changed | prev right, truth unchanged | prev right, truth changed |",
     "|---|---|---|---|---|"]
for m, lab in (("C_old", "item6 (superseded): all pairs i < j, pooled store"), ("C", "**used: main run, consecutive pairs** (repeat_error D)"),
               ("C_pooled", "sensitivity: pooled store, consecutive pairs (repeat_error B)")):
    pc, n = PC[m]
    L.append(f"| {lab} | " + " | ".join(f"{100 * pc[k]:.1f} % (n = {n[k]})" for k in ((False, True), (False, False), (True, True), (True, False))) + " |")

L.append("\n## 6d (revised). Estimated effect of an anchor expiry of N commits (first-order model; NOT a run)\n")
L.append("Estimates A and B are item6's (re-computed here and checked against item6.json); C now uses the main-run consecutive-pair "
         "statistic. Columns as in item6.md 6d.\n")
L.append("| set | expiry applies to | N | P model | ESM served-wrong % (recorded) | hybrid served-wrong % (est.) | wrong reads removed | introduced | net Δ pp | removed as % of wrong-re-derivation reads | forced re-derivations/fact | real outcomes % | extra tokens/fact (re-derivation only) |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|")
SENS = []
for sname, ids in (("ALL", ALL), ("H150", H150)):
    wr = wrong_rederive_reads(ids)
    for variant, kw in VARIANTS:
        for N in (50, 100, 200):
            for model in ("A", "B", "C_old", "C", "C_pooled"):
                r = hybrid(N, model, ids, **kw)
                OUT["hybrid"][f"{sname}|{N}|{model}|{variant}"] = r
                if model in ("A", "B", "C_old"):          # reproduction check against item6.json
                    ref = H6[f"{sname}|{N}|{'C' if model == 'C_old' else model}|{variant}"]
                    check.append(abs(r["sw"] - ref["sw"]) < 1e-9 and abs(r["tok_per_fact"] - ref["tok_per_fact"]) < 1e-6)
                    continue
                row = (f"| {sname} | {variant} | {N} | C | {p1(r['base_sw'])} | {p1(r['sw'])} | {r['removed']:.0f} | {r['introduced']:.0f} "
                       f"| {100 * (r['sw'] - r['base_sw']):+.2f} | {100 * r['removed'] / max(wr, 1):.1f} | {r['exp_per_fact']:.2f} "
                       f"| {100 * r['real_frac']:.0f} | +{r['tok_per_fact'] / 1000:.1f}k |")
                if model == "C_pooled":
                    SENS.append(row.replace("| C |", "| C (pooled consecutive) |"))
                    continue
                for mm in ("A", "B"):
                    ra = OUT["hybrid"][f"{sname}|{N}|{mm}|{variant}"]
                    L.append(f"| {sname} | {variant} | {N} | {mm} | {p1(ra['base_sw'])} | {p1(ra['sw'])} | {ra['removed']:.0f} | {ra['introduced']:.0f} "
                             f"| {100 * (ra['sw'] - ra['base_sw']):+.2f} | {100 * ra['removed'] / max(wr, 1):.1f} | {ra['exp_per_fact']:.2f} "
                             f"| {100 * ra['real_frac']:.0f} | +{ra['tok_per_fact'] / 1000:.1f}k |")
                L.append(row)
OUT["reproduces_item6"] = all(check)
L.append(f"\nReproduction of item6.json (A, B and the old C, every set / variant / N): {'all ' + str(len(check)) + ' match' if all(check) else 'MISMATCH'}.\n")
L.append("\n## Old vs new estimate C (served-wrong %, all anchors / re-derived anchors only)\n")
L.append("| set | N | expiry applies to | old C (all pairs) | new C (main run, consecutive) | sensitivity: pooled consecutive | max |optimistic − standard| over A, B, new C |\n|---|---|---|---|---|---|---|")
for sname in ("ALL", "H150"):
    for variant in ("all anchors", "re-derived anchors only"):
        for N in (50, 100, 200):
            g = lambda m, v=variant: OUT["hybrid"][f"{sname}|{N}|{m}|{v}"]["sw"]
            opt = "all anchors, optimistic" if variant == "all anchors" else "re-derived only, optimistic"
            dopt = max(abs(OUT["hybrid"][f"{sname}|{N}|{m}|{opt}"]["sw"] - g(m)) for m in ("A", "B", "C"))
            L.append(f"| {sname} | {N} | {variant} | {p1(g('C_old'))} | **{p1(g('C'))}** | {p1(g('C_pooled'))} | {100 * dopt:.2f} pp |")
L.append("\nSensitivity rows (pooled-store consecutive pairs; not used in the paper):\n")
L.append("| set | expiry applies to | N | P model | ESM % | hybrid % | removed | introduced | net Δ pp | removed % | forced/fact | real % | extra tokens |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|")
L += [s for s in SENS if "optimistic" not in s]
(OUTDIR / "estimate_c.md").write_text("\n".join(L), encoding="utf-8")
(OUTDIR / "estimate_c.json").write_text(json.dumps(OUT, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)), encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print("\n".join(L))
