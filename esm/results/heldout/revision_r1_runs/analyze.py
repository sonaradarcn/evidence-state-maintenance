"""Supplementary runs: analysis (zero LLM; ESM_LLM_OFFLINE=1 via r1_common).

Experiment A: frozen ESM (ESM-norepair) + anchor expiry after N commits, H150 (160 facts), every commit.
Experiment B: strong baselines on NAT100 (seeded uniform sample of 100 natural facts), every commit.

Definitions are the paper's (esm.metrics.per_fact / summary); certificate construction tokens are added to CERT-ZS /
CERT-v0h exactly as report_heldout.with_setup does.  Paired statistics, fact bootstrap and repo-cluster bootstrap
(B = 2000) come from revision_r1/r1_common.paired_stats, NI / TOST exactly as revision_r1/item2 (NI at margin m:
one-sided 95 % upper bound = 95th percentile < m; EQ (TOST): 90 % CI inside (−m, +m)).
Inputs: esm_data_heldout/sim_r1/*.parquet (this stage), esm_data_heldout/sim/ESM-norepair__every.parquet (frozen
H150 arm), esm/results/heldout/records.parquet (H150 baselines, for the cost-ratio comparison), certs*.jsonl.
Outputs (this folder): RESULTS_tables.md, results.json, records_r1.parquet, fig_A_expiry.png, fig_B_ratios.png."""
import json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "revision_r1"))
from r1_common import *                    # noqa: F401,F403  (FACTS, FX, H150, paired_stats, ratio_stats, pf, ...)
R1DIR = HERE                                # r1_common exports its own HERE (= revision_r1/)
HERE = Path(__file__).resolve().parent      # outputs go next to this script
from esm.maintain import read_shards
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SIMR1, SIM = DATA_DIR / "sim_r1", DATA_DIR / "sim"
NAT100 = set(json.loads((DATA_DIR / "sub_NAT100.json").read_text()))
CT = {}
for r in read_shards(DATA_DIR / "certs.jsonl"):
    t = r.get("tokens")
    CT[(r["iid"], r["kind"])] = sum(t) if isinstance(t, list) else (t or 0)
L, OUT, RECS = [], {"A": {}, "B": {}}, []
MARG = (0.010, 0.015, 0.020)


def load(pol, sch="every", path=SIMR1, ids=None):
    p = path / f"{pol}__{sch}.parquet"
    if not p.exists():
        return None, None
    d = pd.read_parquet(p)
    if ids is not None:
        d = d[d.iid.isin(ids)]
    if not len(d):
        return None, None
    d = d.copy()
    d["schedule"] = sch
    f = M.per_fact(d, FACTS)
    base = pol.split("@")[0]
    if base in ("CERT-ZS", "CERT-v0"):
        k = "certzs" if base == "CERT-ZS" else "certv0h"
        f["setup_tok"] = [CT.get((i, k), 0) for i in f.index]
        f["tok"] = f.tok + f.setup_tok
        f["rde"] = f.tok / f.dtok
    return d, f


def boot_ratio(ta, tb, ids, seed=3):
    """tokens ratio mean(B)/mean(A) on facts ids, fact and repo-cluster bootstrap 95 % CIs."""
    ta, tb = np.asarray(ta, float), np.asarray(tb, float)
    repo = np.array([FX[i]["repo"] for i in ids]); reps = sorted(set(repo)); ridx = np.array([reps.index(r) for r in repo])
    rng = np.random.default_rng(seed)
    wf = rng.multinomial(len(ids), np.full(len(ids), 1 / len(ids)), size=B).astype(float)
    draws = rng.integers(0, len(reps), size=(B, len(reps)))
    cnt = np.stack([(draws == j).sum(1) for j in range(len(reps))], 1)[:, ridx].astype(float)
    f = lambda W: (W @ tb) / np.maximum(W @ ta, 1)
    return tb.mean() / ta.mean(), np.percentile(f(wf), [2.5, 97.5]).tolist(), np.percentile(f(cnt), [2.5, 97.5]).tolist()


def sline(s):
    return s


# ======================================================================== Experiment A
L.append("# Reviewer round 1 — supplementary runs: generated tables (analyze.py)\n")
L.append("## A. Frozen ESM + anchor expiry (H150, every commit, real 27B re-derivations)\n")
dE, fE = load("ESM-norepair", path=SIM, ids=H150)
ESMH = fE
arms_A = [("ESM-norepair", "frozen ESM (no expiry)")] + [(f"ESM-norepair-exp{n}", f"+ expiry, every anchor, N = {n}") for n in (200, 100, 50)] \
    + [(f"ESM-norepair-expS{n}", f"+ expiry, NONE-suspicious anchors only, N = {n}") for n in (200, 100, 50)]
# anchored-wrong reads of the frozen arm (episodes of wrong-served reads that start at a wrong re-derivation)
anch = set()
for iid, x in dE.sort_values(["iid", "t"]).groupby("iid"):
    ts, sv, ac = x.t.to_numpy(), x.served_valid.to_numpy(), x.action.to_numpy()
    k = 0
    while k < len(ts):
        if not sv[k]:
            j = k
            while j < len(ts) and not sv[j]:
                j += 1
            if ac[k] == "rederive":
                anch.update((iid, int(t)) for t in ts[k:j])
            k = j
        else:
            k += 1
ewrong = {(i, int(t)) for i, t, v in zip(dE.iid, dE.t, dE.served_valid) if not v}
hdr = ("| policy | facts | served-wrong % [fact CI] {cluster CI} | FF % | FS % | stored-wrong episodes never acted on % | tokens/fact | RDE | "
       "re-derivations/fact (forced) | forced right % | fallbacks (unverified reads, of which wrong) | judge calls/fact | judge / re-derivation tokens per fact |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|")
L.append(hdr)
rowsA = {}
for pol, lab in arms_A:
    d, f = (dE, fE) if pol == "ESM-norepair" else load(pol, ids=H150)
    if f is None:
        L.append(f"| {lab} | not run | | | | | | | | | |")
        continue
    if pol != "ESM-norepair":
        RECS.append(d.assign(experiment="A"))
    s = M.summary(f)
    rs = ratio_stats(f.sw, f.reads, [FX[i]["repo"] for i in f.index])
    fo = d[d.action.isin(["forced", "forced_keep"])]
    nf = len(f)
    fk = d[d.action == "forced_keep"]
    unv = d[d.verified == 0] if "verified" in d else d.iloc[:0]
    row = {"lab": lab, "n": nf, "sw": s["sw"], "sw_ci": s["sw_ci"], "sw_clu": rs["clu_ci"], "ff": s["ff"], "fs": s["fs"],
           "eps_missed": s["eps_missed"], "eps": s["eps"], "tok": s["tok_per_fact"], "rde": s["rde_sum"], "der": s["der_per_fact"],
           "forced": len(fo) / nf, "forced_ok": float(fo.served_valid.mean()) if len(fo) else np.nan,
           "forced_fix": int((~fo.stored_valid & fo.served_valid).sum()), "forced_break": int((fo.stored_valid & ~fo.served_valid).sum()),
           "forced_wrong_to_wrong": int((~fo.stored_valid & ~fo.served_valid).sum()),
           "fallbacks": len(fk), "unv_reads": len(unv), "unv_wrong": int((~unv.served_valid).sum()) if len(unv) else 0,
           "judge_calls": s["calls_per_fact"], "eval_tok": s["eval_tok_per_fact"], "der_tok": s["der_tok_per_fact"]}
    if len(fo):
        prev = d.sort_values(["iid", "t"]).groupby("iid").served.shift(1)
        prev = prev.reindex(fo.index).fillna(pd.Series({i: FX[x]["K"] for i, x in zip(fo.index, fo.iid)}))
        ww = fo[~fo.stored_valid & ~fo.served_valid]
        row["ww_same"] = int((ww.served.str.strip() == prev.loc[ww.index].astype(str).str.strip()).sum())
        row["wrong_stored_forced"] = int((~fo.stored_valid).sum())
    if pol != "ESM-norepair":
        hw = {(i, int(t)) for i, t, v in zip(d.iid, d.t, d.served_valid) if not v}
        ids_ = set(f.index)
        ew = {k for k in ewrong if k[0] in ids_}
        an = {k for k in anch if k[0] in ids_}
        row |= {"removed": len(ew - hw), "introduced": len(hw - ew), "anch_reads": len(an), "anch_removed": len(an - hw),
                "anch_removed_frac": len(an - hw) / max(len(an), 1)}
        p = paired_stats(f, fE, set(f.index))
        row["paired"] = p
    rowsA[pol] = row
    L.append(f"| {lab} | {nf} | {p1(s['sw'])} {ci1(s['sw_ci'])} {{{p1(rs['clu_ci'][0])}, {p1(rs['clu_ci'][1])}}} | {p1(s['ff'])} | {p1(s['fs'])} "
             f"| {p1(s['eps_missed'])} ({int(round(s['eps_missed'] * s['eps']))}/{s['eps']}) | {s['tok_per_fact'] / 1000:.1f}k | {s['rde_sum']:.2f} "
             f"| {s['der_per_fact']:.2f} ({row['forced']:.2f}) | {'' if np.isnan(row['forced_ok']) else p1(row['forced_ok'])} "
             f"| {row['fallbacks']} ({row['unv_reads']}, {row['unv_wrong']}) | {row['judge_calls']:.1f} | {row['eval_tok'] / 1000:.1f}k / {row['der_tok'] / 1000:.1f}k |")
OUT["A"]["rows"] = rowsA

L.append("\n### A2. Paired against the frozen ESM (same facts; Δ = hybrid − frozen ESM)\n")
L.append("| policy | facts | Δ served-wrong pp [fact CI] {cluster CI} | repos better / tie / worse (hybrid lower = better) | Δ tokens/fact [cluster CI] "
         "| ESM-wrong reads fixed | ESM-right reads broken | anchored-wrong reads of frozen ESM removed | forced: wrong→right / right→wrong / wrong→wrong | wrong→wrong with the identical answer string |"
         "\n|---|---|---|---|---|---|---|---|---|---|")
for pol, r in rowsA.items():
    if pol == "ESM-norepair":
        continue
    p = r["paired"]
    L.append(f"| {r['lab']} | {p['n']} | {100 * p['d']:+.2f} [{100 * p['fact'][0]:+.2f}, {100 * p['fact'][1]:+.2f}] {{{100 * p['clu'][0]:+.2f}, {100 * p['clu'][1]:+.2f}}} "
             f"| {p['repo_neg']} / {p['repo_zero']} / {p['repo_pos']} | {p['dt'] / 1000:+.1f}k [{p['clu_tok'][0] / 1000:+.1f}, {p['clu_tok'][1] / 1000:+.1f}] "
             f"| {r['removed']} | {r['introduced']} | {r['anch_removed']} / {r['anch_reads']} ({p1(r['anch_removed_frac'])} %) "
             f"| {r['forced_fix']} / {r['forced_break']} / {r['forced_wrong_to_wrong']} | {r.get('ww_same', 0)} |")

# item-6 estimate comparison
try:
    h6 = json.loads((R1DIR / "item6.json").read_text())["hybrid"]
    L.append("\n### A3. Real run vs the item-6 first-order estimates (H150, every anchor expires)\n")
    L.append("| N | frozen ESM % | real hybrid % (facts run) | estimate A / B / C % | real forced re-der./fact | estimated forced/fact | "
             "real extra tokens/fact | estimated extra (re-derivation only) |\n|---|---|---|---|---|---|---|---|")
    for n in (50, 100, 200):
        pol = f"ESM-norepair-exp{n}"
        if pol not in rowsA:
            continue
        r = rowsA[pol]; p = r["paired"]
        e = [h6.get(f"H150|{n}|{m}|all anchors") for m in "ABC"]
        L.append(f"| {n} | {p1(p['wb'])} | {p1(p['wa'])} ({p['n']}) | {' / '.join(p1(x['sw']) for x in e)} | {r['forced']:.2f} | {e[0]['exp_per_fact']:.2f} "
                 f"| {p['dt'] / 1000:+.1f}k | +{e[0]['tok_per_fact'] / 1000:.0f}k |")
        OUT["A"][f"item6_{n}"] = {"est": [x["sw"] for x in e], "real": p["wa"], "base": p["wb"]}
    L.append("\nSuspicious-only variant vs item-6 'expiry of re-derived anchors only' (closest analogue; expS restricts further to "
             "NONE-suspicious re-derived anchors):\n")
    L.append("| N | real expS hybrid % | frozen % | estimate (re-derived anchors only) A / B / C % |\n|---|---|---|---|")
    for n in (50, 100, 200):
        pol = f"ESM-norepair-expS{n}"
        if pol not in rowsA:
            continue
        p = rowsA[pol]["paired"]
        e = [h6.get(f"H150|{n}|{m}|re-derived anchors only") for m in "ABC"]
        L.append(f"| {n} | {p1(p['wa'])} ({p['n']} facts) | {p1(p['wb'])} | {' / '.join(p1(x['sw']) for x in e)} |")
except Exception as ex:
    L.append(f"(item-6 comparison failed: {ex!r})")

# coverage of the NONE-suspicious rule on the frozen arm's own re-derivations (reason field = first 200 chars of the verdict)
from esm.maintain import _none_suspicious
rd = dE[dE.action == "rederive"].copy()
rd["susp"] = [_none_suspicious(a if a else None, r) for a, r in zip(rd.served, rd.reason)]
rd["none_truth"] = [truth(i, t) == "NONE" for i, t in zip(rd.iid, rd.t)]
w, ok = rd[~rd.served_valid], rd[rd.served_valid]
L.append("\n### A4. The NONE-suspicious rule on the frozen arm's 27B re-derivations (H150, every commit)\n")
L.append(f"* re-derivations: {len(rd)}; wrong: {len(w)} (oracle NONE at {int(w.none_truth.sum())} of them).")
L.append(f"* flagged suspicious: {int(rd.susp.sum())} — {int(w.susp.sum())} of the {len(w)} wrong ones ({p1(w.susp.mean())} % recall) and "
         f"{int(ok.susp.sum())} of the {len(ok)} right ones (precision {p1(w.susp.sum() / max(rd.susp.sum(), 1))} %).")
L.append(f"* wrong re-derivations with oracle NONE that the rule flags: {int((w.susp & w.none_truth).sum())} of {int(w.none_truth.sum())}.")
OUT["A"]["susp_rule"] = {"n": len(rd), "wrong": len(w), "flag": int(rd.susp.sum()), "flag_wrong": int(w.susp.sum()), "flag_right": int(ok.susp.sum())}

# ======================================================================== Experiment B
L.append("\n## B. Strong baselines on NAT100 (100 natural facts, seeded uniform draw; every commit, real 27B re-derivations)\n")
arms_B = [("ESM-norepair", "every", "ESM (frozen)"), ("NEVER", "every", "NEVER"), ("TTL100", "every", "TTL100"),
          ("CERT-ZS", "every", "CERT-ZS (incl. extraction)"), ("CERT-v0", "every", "CERT-v0h (static only, incl. construction)"),
          ("LLMDIFF", "every", "LLMDIFF"), ("REPLAY", "every", "REPLAY")]
PFB = {}
for pol, sch, lab in arms_B:
    d, f = load(pol, sch, ids=NAT100)
    if f is not None:
        PFB[pol] = (d, f, lab)
        if pol not in ("ESM-norepair", "NEVER"):
            RECS.append(d.assign(experiment="B"))
# also ESM on the every50 grid if the REPLAY fallback ran
for pol in ("ESM-norepair", "REPLAY"):
    d, f = load(pol, "every50", ids=NAT100)
    if f is not None:
        PFB[pol + "|every50"] = (d, f, pol + " (every50 grid)")
        RECS.append(d.assign(experiment="B"))
fESM = PFB["ESM-norepair"][1]
L.append("| policy | facts | served-wrong % [fact CI] {cluster CI} | FF % | FS % | episodes never acted on % | tokens/fact | re-derivations/fact | LLM judge calls/fact |"
         "\n|---|---|---|---|---|---|---|---|---|")
for k, (d, f, lab) in PFB.items():
    s = M.summary(f); rs = ratio_stats(f.sw, f.reads, [FX[i]["repo"] for i in f.index])
    OUT["B"][k] = {"n": len(f), "sw": s["sw"], "sw_ci": s["sw_ci"], "sw_clu": rs["clu_ci"], "tok": s["tok_per_fact"], "der": s["der_per_fact"],
                   "ff": s["ff"], "fs": s["fs"], "eps_missed": s["eps_missed"]}
    L.append(f"| {lab} | {len(f)} | {p1(s['sw'])} {ci1(s['sw_ci'])} {{{p1(rs['clu_ci'][0])}, {p1(rs['clu_ci'][1])}}} | {p1(s['ff'])} | {p1(s['fs'])} "
             f"| {p1(s['eps_missed'])} | {s['tok_per_fact'] / 1000:.1f}k | {s['der_per_fact']:.2f} | {s['calls_per_fact']:.1f} |")
# ESM on the sample vs on the whole natural population (representativeness check)
popE = pf(FROZEN).loc[sorted(NAT)]
L.append(f"\nRepresentativeness: frozen ESM on all 715 natural facts = {p1(popE.sw.sum() / popE.reads.sum())} % at {popE.tok.mean() / 1000:.1f}k "
         f"tokens/fact; on NAT100 = {p1(fESM.sw.sum() / fESM.reads.sum())} % at {fESM.tok.mean() / 1000:.1f}k "
         f"(fact-bootstrap 95 % CI of the sample's tokens/fact [{M.summary(fESM)['tok_ci'][0] / 1000:.1f}, {M.summary(fESM)['tok_ci'][1] / 1000:.1f}]k). Changing facts: "
         f"{int(fESM.changing.sum())}/100 in NAT100 vs {int(popE.changing.sum())}/715 = {100 * popE.changing.mean():.0f} % in the population.\n")
OUT["B"]["pop_ESM"] = {"sw": popE.sw.sum() / popE.reads.sum(), "tok": popE.tok.mean(), "chg": float(popE.changing.mean()),
                       "sample_chg": int(fESM.changing.sum())}

L.append("### B2. Paired ESM − baseline (pp; positive = ESM worse), non-inferiority / TOST, cost ratio\n")
L.append("| comparison | facts | ESM % / B % | Δ [95 % fact CI] | 95 % cluster CI | 90 % CI fact / cluster | one-sided 95 % upper bound fact / cluster "
         "| NI at 1.5 pp (fact / cluster) | EQ ±1.5 pp (fact / cluster) | ESM / B tokens per fact | ratio B/ESM [fact CI] {cluster CI} | repos ESM better / tie / worse |"
         "\n|---|---|---|---|---|---|---|---|---|---|---|---|")
for k, (d, f, lab) in PFB.items():
    if k.startswith("ESM-norepair"):
        continue
    base = fESM if "|every50" not in k else PFB["ESM-norepair|every50"][1]
    ids = set(f.index) & set(base.index)
    p = paired_stats(base, f, ids)
    idl = sorted(ids)
    rt, rf, rc = boot_ratio(base.loc[idl].tok, f.loc[idl].tok, idl)
    lo95, hi95, lo90, hi90 = p["fact"]; c95a, c95b, c90a, c90b = p["clu"]
    ni = ("yes" if hi90 < 0.015 else "no", "yes" if c90b < 0.015 else "no")
    eq = ("yes" if (lo90 > -0.015 and hi90 < 0.015) else "no", "yes" if (c90a > -0.015 and c90b < 0.015) else "no")
    OUT["B"][f"paired|{k}"] = {"p": p, "ratio": rt, "ratio_fact_ci": rf, "ratio_clu_ci": rc, "ni15": ni, "eq15": eq}
    L.append(f"| ESM − {lab} | {p['n']} | {p1(p['wa'])} / {p1(p['wb'])} | {100 * p['d']:+.2f} [{100 * lo95:+.2f}, {100 * hi95:+.2f}] "
             f"| [{100 * c95a:+.2f}, {100 * c95b:+.2f}] | [{100 * lo90:+.2f}, {100 * hi90:+.2f}] / [{100 * c90a:+.2f}, {100 * c90b:+.2f}] "
             f"| {100 * hi90:+.2f} / {100 * c90b:+.2f} | {ni[0]} / {ni[1]} | {eq[0]} / {eq[1]} | {p['toka'] / 1000:.1f}k / {p['tokb'] / 1000:.1f}k "
             f"| {rt:.2f} [{rf[0]:.2f}, {rf[1]:.2f}] {{{rc[0]:.2f}, {rc[1]:.2f}}} | {p['repo_neg']} / {p['repo_zero']} / {p['repo_pos']} |")

# H150 comparison of cost ratios (same definitions, from the held-out records)
L.append("\n### B3. Cost ratio B / ESM: natural sample vs the change-enriched H150 subset\n")
L.append("| baseline | NAT100 ratio [cluster CI] | H150 ratio (measured, every commit) | item-3 re-weighted estimate (type × changing / churn × jinja) | Δ served-wrong pp NAT100 | Δ served-wrong pp H150 |\n|---|---|---|---|---|---|")
RW = {"CERT-ZS": "2.85 / 2.01", "CERT-v0": "1.45 / –", "LLMDIFF": "3.63 / 2.96", "REPLAY": "6.28 / 6.98", "TTL100": "2.06 / 2.02"}
for b in ("TTL100", "CERT-ZS", "CERT-v0", "LLMDIFF", "REPLAY"):
    if f"paired|{b}" not in OUT["B"]:
        continue
    q = OUT["B"][f"paired|{b}"]
    try:
        hb = pf(b); hE = pf(FROZEN)
        ids = sorted(set(hb.index) & set(hE.index) & H150)
        hr = hb.loc[ids].tok.mean() / hE.loc[ids].tok.mean()
        hd = hE.loc[ids].sw.sum() / hE.loc[ids].reads.sum() - hb.loc[ids].sw.sum() / hb.loc[ids].reads.sum()
        OUT["B"][f"h150|{b}"] = {"ratio": hr, "d": hd, "n": len(ids)}
        hs = f"{hr:.2f} ({len(ids)} facts)"; hds = f"{100 * hd:+.1f}"
    except Exception as ex:
        hs, hds = f"n/a ({ex!r})"[:40], ""
    L.append(f"| {b.replace('CERT-v0', 'CERT-v0h')} | {q['ratio']:.2f} {{{q['ratio_clu_ci'][0]:.2f}, {q['ratio_clu_ci'][1]:.2f}}} | {hs} | {RW[b]} | {100 * q['p']['d']:+.1f} | {hds} |")

# by churn: changing vs non-changing facts within NAT100
L.append("\n### B4. Tokens per fact within NAT100, changing vs non-changing facts\n")
L.append("| policy | changing facts: n, tokens/fact, served-wrong % | non-changing facts: n, tokens/fact, served-wrong % |\n|---|---|---|")
for k, (d, f, lab) in PFB.items():
    c, nc = f[f.changing], f[~f.changing]
    fmt = lambda g: f"{len(g)}, {g.tok.mean() / 1000:.1f}k, {p1(g.sw.sum() / max(g.reads.sum(), 1))}" if len(g) else "–"
    L.append(f"| {lab} | {fmt(c)} | {fmt(nc)} |")

# sensitivity: post-stratify NAT100 to the natural population's churn mix (bins of #FUTURE commits at which the s0
# answer is invalid: 0, 1-100, 101-200, 201-400), validated on ESM's own population cost / served-wrong
def cbin(i):
    n = sum(1 for v in FX[i]["valid"] if not v)
    return 0 if n == 0 else (1 if n <= 100 else (2 if n <= 200 else 3))
popb = pd.Series([cbin(i) for i in sorted(NAT)]).value_counts(normalize=True).sort_index()
smpb = pd.Series({i: cbin(i) for i in fESM.index})
L.append("\n### B5. Sensitivity: NAT100 post-stratified to the natural population's churn mix\n")
L.append("Churn bin = number of FUTURE commits at which the s0 answer is invalid (0 / 1–100 / 101–200 / 201–400). "
         f"Population shares (715 natural facts): {' / '.join(f'{100 * popb.get(b, 0):.0f} %' for b in range(4))}; "
         f"NAT100 counts: {' / '.join(str(int((smpb == b).sum())) for b in range(4))}.\n")


def rw_mean(f, col="tok"):
    s = pd.Series({i: cbin(i) for i in f.index})
    return sum(popb.get(b, 0) * f.loc[s[s == b].index, col].mean() for b in range(4) if (s == b).any()) / \
        sum(popb.get(b, 0) for b in range(4) if (s == b).any())


def rw_rate(f):
    s = pd.Series({i: cbin(i) for i in f.index})
    num = sum(popb.get(b, 0) * f.loc[s[s == b].index, "sw"].sum() / f.loc[s[s == b].index, "reads"].sum() for b in range(4) if (s == b).any())
    return num / sum(popb.get(b, 0) for b in range(4) if (s == b).any())


L.append(f"Validation on ESM: re-weighted NAT100 = {p1(rw_rate(fESM))} % at {rw_mean(fESM) / 1000:.1f}k tokens/fact vs the actual population "
         f"{p1(popE.sw.sum() / popE.reads.sum())} % at {popE.tok.mean() / 1000:.1f}k.\n")
L.append("| baseline | ratio B/ESM unweighted | ratio re-weighted to the population churn mix | Δ served-wrong pp re-weighted |\n|---|---|---|---|")
for k, (d, f, lab) in PFB.items():
    if k.startswith("ESM-norepair") or k == "NEVER":
        continue
    ids = sorted(set(f.index) & set(fESM.index))
    e, b = fESM.loc[ids], f.loc[ids]
    rr = rw_mean(b) / rw_mean(e)
    OUT["B"][f"rw|{k}"] = {"ratio": rr, "d": rw_rate(e) - rw_rate(b)}
    L.append(f"| {lab} | {b.tok.mean() / e.tok.mean():.2f} | {rr:.2f} | {100 * (rw_rate(e) - rw_rate(b)):+.2f} |")

# ======================================================================== figures
try:
    fig, ax = plt.subplots(figsize=(6.4, 4))
    for pol, r in rowsA.items():
        mk = "o" if "expS" not in pol else "s"
        col = "#c2452d" if pol == "ESM-norepair" else ("#3b6fb6" if "expS" not in pol else "#5a9e4b")
        ax.errorbar(r["tok"] / 1000, 100 * r["sw"], yerr=[[100 * (r["sw"] - r["sw_clu"][0])], [100 * (r["sw_clu"][1] - r["sw"])]],
                    fmt=mk, color=col, capsize=2, ms=5)
        ax.annotate(pol.replace("ESM-norepair", "ESM").replace("-exp", " exp"), (r["tok"] / 1000, 100 * r["sw"]), fontsize=7,
                    xytext=(4, 3), textcoords="offset points")
    ax.set_xlabel("LLM tokens per fact (k)"); ax.set_ylabel("served-wrong % (cluster 95 % CI)")
    ax.set_title("Experiment A: H150, every commit, real runs", fontsize=9)
    fig.tight_layout(); fig.savefig(HERE / "fig_A_expiry.png", dpi=140); plt.close(fig)
    fig, ax = plt.subplots(figsize=(6.4, 4))
    for k, (d, f, lab) in PFB.items():
        if "|every50" in k:
            continue
        s = OUT["B"][k]
        ax.errorbar(s["tok"] / 1000, 100 * s["sw"], yerr=[[100 * (s["sw"] - s["sw_clu"][0])], [100 * (s["sw_clu"][1] - s["sw"])]], fmt="o",
                    capsize=2, ms=5, color="#c2452d" if k == "ESM-norepair" else "#3b6fb6")
        ax.annotate(lab.split(" (")[0], (s["tok"] / 1000, 100 * s["sw"]), fontsize=7, xytext=(4, 3), textcoords="offset points")
    ax.set_xscale("symlog", linthresh=1); ax.set_xlabel("LLM tokens per fact (k, symlog)"); ax.set_ylabel("served-wrong % (cluster 95 % CI)")
    ax.set_title("Experiment B: NAT100 (natural random sample), every commit", fontsize=9)
    fig.tight_layout(); fig.savefig(HERE / "fig_B_natural.png", dpi=140); plt.close(fig)
except Exception as ex:
    L.append(f"(figure failed: {ex!r})")

if RECS:
    pd.concat(RECS, ignore_index=True).to_parquet(HERE / "records_r1.parquet", index=False)
(HERE / "RESULTS_tables.md").write_text("\n".join(L), encoding="utf-8")
(HERE / "results.json").write_text(json.dumps(OUT, indent=1, default=lambda o: float(o) if np.isscalar(o) else str(o)), encoding="utf-8")
print("\n".join(L))
