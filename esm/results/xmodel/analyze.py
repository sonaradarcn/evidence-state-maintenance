"""Cross-model stage: zero-LLM analysis (ESM_LLM_OFFLINE=1).  Writes tables.md, results.json, records.parquet and the
figures next to this script.

Second model = esm_data_xmodel/model.json {"model": ..., "reasoning": ...}.  Qwen-27B numbers are recomputed from the
held-out records (esm_data_heldout/sim and sim_r1, every commit) restricted to the SAME facts.  Definitions are the
paper's (esm.metrics.per_fact / summary); CERT-ZS extraction tokens are added to its cost as in Stage 2; paired
statistics, fact / repo-cluster bootstrap (B = 2000) from revision_r1/r1_common.paired_stats; non-inferiority at margin
m: one-sided 95 % upper bound (95th bootstrap percentile of ESM − B) < m.
"""
import json, os, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
XD = Path(os.environ.get("XM_DATA", str(ROOT / "esm_data_xmodel" / "nemotron")))   # primary: Nemotron; secondary: esm_data_xmodel (gpt-oss)
HD = ROOT / "esm_data_heldout"
SUF = os.environ.get("XM_SUFFIX", "")                                              # output-file suffix (e.g. "_gptoss")
MJ = json.loads((XD / "model.json").read_text())
os.environ["ESM_DATA"] = str(XD)
os.environ["ESM_STAGE"] = "xmodel"
os.environ["ESM_LLM_OFFLINE"] = "1"
os.environ["ESM_MAIN_MODEL"] = MJ["model"]
os.environ["ESM_REASONING"] = MJ.get("reasoning", "none") if MJ["model"].startswith("ollama:") else "none"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "esm" / "results" / "heldout" / "revision_r1"))
import numpy as np
import pandas as pd
from r1_common import FX as QFX, paired_stats, ratio_stats, p1, ci1, B     # Qwen kept-fact metadata + resampling helpers
from esm import metrics as M
from esm.maintain import read_shards
from esm.policies import Context
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SCH = os.environ.get("XM_SCHEDULE", "every")
X120 = json.loads((XD / "sub_X120.json").read_text())
DRAW = json.loads((HERE / "draw_x120.json").read_text())
NATX = set(DRAW["natural"]["ids"])
ctx = Context.load("heldout")
XFACTS = [f for f in ctx.facts if f["iid"] in set(X120)]
XFX = {f["iid"]: f for f in XFACTS}
RAW = {f["iid"]: f for f in ctx.raw}
XK = sorted(XFX)                                      # X120 facts kept by the second model (s0 correct)
QFACTS = [QFX[i] for i in X120]
MODEL = MJ["model"].split(":", 1)[1]
QN, XN = "Qwen3.6-27B", MJ.get("label", MODEL)
L, OUT = [], {"model": MJ, "schedule": SCH}
ARMS = [("ESM-norepair", "ESM (frozen)"), ("NEVER", "NEVER"), ("TTL100", "TTL100 + re-derive"),
        ("CERT-ZS", "CERT-ZS + re-derive (incl. extraction)"), ("LLMDIFF", "LLMDIFF + re-derive"), ("REPLAY", "REPLAY + re-derive")]
MARGINS = (0.005, 0.010, 0.015, 0.020)


def certtok(path):
    out = {}
    for r in read_shards(path):
        t = r.get("tokens")
        out[(r["iid"], r["kind"])] = sum(t) if isinstance(t, list) else (t or 0)
    return out


QCT, XCT = certtok(HD / "certs.jsonl"), certtok(XD / "certs.jsonl")


def qwen_records(pol, sch="every", ids=X120):
    parts, have = [], set()
    for d in (HD / "sim", HD / "sim_r1", ROOT / "esm_data_xmodel" / "qwen50" / "sim"):   # qwen50: every50 grid completion (qwen_every50.py)
        p = d / f"{pol}__{sch}.parquet"
        if p.exists():
            x = pd.read_parquet(p)
            x = x[x.iid.isin(set(ids)) & ~x.iid.isin(have)]
            have |= set(x.iid)
            parts.append(x)
    if not parts:
        return None
    d = pd.concat(parts, ignore_index=True)
    return d if len(d) else None


def x_records(pol, sch=SCH):
    p = XD / "sim" / f"{pol}__{sch}.parquet"
    if not p.exists():
        return None
    d = pd.read_parquet(p)
    d = d[d.iid.isin(set(XK))]
    return d if len(d) else None


def _turns(paths):
    out = {}
    for pth in paths:
        for r in read_shards(pth):
            out.setdefault((r["iid"], r["t"]), r.get("n_llm", 0))
    return out


TURNS = {"q": _turns([HD / "derivations.jsonl", ROOT / "esm_data_xmodel" / "qwen50" / "derivations.jsonl"]),
         "x": _turns([XD / "derivations.jsonl"])}


def perfact(d, facts, pol, ct):
    if d is None:
        return None
    d = d.copy()
    mk = "q" if facts is QFACTS else "x"
    d["turns"] = [TURNS[mk].get((i, int(t)), 0) if n else 0 for i, t, n in zip(d.iid, d.t, d.n_der)]
    if SCH != "every" and d.schedule.iloc[0] == "every":           # Qwen every-commit records thinned to the schedule's reads
        k = int(SCH[5:])
        d = d[d.t % k == 0]
    f = M.per_fact(d, facts)
    f["calls"] = f.eval_calls + d.groupby("iid").turns.sum().reindex(f.index).fillna(0)   # LLM calls: judge calls + agent turns
    if pol in ("CERT-ZS",):
        f["calls"] = f.calls + 1                                                       # the extraction call
        f["setup_tok"] = [ct.get((i, "certzs"), 0) for i in f.index]
        f["tok"] = f.tok + f.setup_tok
        f["rde"] = f.tok / f.dtok
    return f


# ------------------------------------------------------------------ s0
L.append(f"# Cross-model generalisation: generated tables (analyze.py; second model = {MJ['model']}, reasoning_effort={MJ.get('reasoning')}, schedule = {SCH})\n")
s0 = [(i, RAW[i].get("s0_status", "missing"), RAW[i].get("s0")) for i in X120]
st = pd.DataFrame([{"iid": i, "status": s, "slice": RAW[i]["slice"], "type": RAW[i]["type"], "half": "natural" if i in NATX else "enriched",
                    "tok": sum(r["tokens"]) if r else np.nan, "calls": len(r["trace"]) if r else np.nan, "nllm": r["n_llm"] if r else np.nan,
                    "qtok": sum(QFX[i]["derive_tokens"])} for i, s, r in s0])
OUT["s0"] = {"n": len(st), "correct": int((st.status == "correct").sum()), "wrong": int((st.status == "wrong").sum()),
             "no_answer": int((st.status == "no_answer").sum()), "missing": int((st.status == "missing").sum())}
L.append("## T0. s0 derivation on X120 (Qwen-27B solved all 120 by construction: X120 ⊂ Qwen-kept facts; Qwen on all 1,478 held-out facts: 96.0 %)\n")
L.append(f"| split | facts | {XN} correct % | wrong | no answer | {XN} tokens/derivation | {XN} tool calls | {QN} tokens/derivation (same facts) |\n|---|---|---|---|---|---|---|---|")
for lab, g in [("all", st), ("static", st[st.slice == "static"]), ("behaviour", st[st.slice == "behav"]),
               ("natural half", st[st.half == "natural"]), ("enriched half", st[st.half == "enriched"])] + \
        [(f"type {t}", st[st.type == t]) for t in sorted(st.type.unique())]:
    L.append(f"| {lab} | {len(g)} | {p1((g.status == 'correct').mean())} | {int((g.status == 'wrong').sum())} | {int((g.status == 'no_answer').sum())} "
             f"| {g.tok.mean() / 1000:.1f}k | {g.calls.mean():.1f} | {g.qtok.mean() / 1000:.1f}k |")
L.append(f"\nCommon fact set for every comparison: **{len(XK)} facts** (X120 facts the second model got right at s0; "
         f"natural {len(set(XK) & NATX)}, enriched {len(set(XK) - NATX)}).\n")
OUT["XK"] = XK

# ------------------------------------------------------------------ per-policy frames
PF, REC = {}, []
for pol, lab in ARMS + [("DETECT-anchor-hier", "detector only")]:
    dq = qwen_records(pol, "every")
    dx = x_records(pol)
    PF[("q", pol)] = perfact(dq, QFACTS, pol, QCT)
    PF[("x", pol)] = perfact(dx, XFACTS, pol, XCT)
    if dx is not None:
        REC.append(dx.assign(model=MJ["model"]))
    if dq is not None:
        REC.append(dq[dq.iid.isin(set(XK))].assign(model="ollama:qwen3.6:27b"))

# comparison set: the kept facts on which the second model's core arms (ESM, TTL100, CERT-ZS) all finished
XKALL = XK
CORE = set(XK)
for pol in ("ESM-norepair", "TTL100", "CERT-ZS"):
    if PF[("x", pol)] is not None:
        CORE &= set(PF[("x", pol)].index)
if os.environ.get("XM_CORE_IDS"):                     # optional restriction (e.g. Nemotron X30, where every arm ran)
    CORE &= set(json.loads(Path(os.environ["XM_CORE_IDS"]).read_text()))
XK = sorted(CORE)
OUT["core"] = XK
L.append(f"**Comparison set (all tables below): {len(XK)} facts** on which the second model's ESM, TTL100 and CERT-ZS runs all finished "
         f"(natural {len(set(XK) & NATX)}, enriched {len(set(XK) - NATX)}). Arms that finished on fewer facts are marked (n=…); their "
         f"paired comparisons use the facts both arms have.\n")
OUT["XK"] = XK

def summ(f, ids):
    if f is None:
        return None
    ids = sorted(set(ids) & set(f.index))
    if not ids:
        return None
    g = f.loc[ids]
    s = M.summary(g)
    rs = ratio_stats(g.sw, g.reads, [QFX[i]["repo"] for i in ids])
    s["clu_ci"] = rs["clu_ci"]
    s["n"] = len(ids)
    return s


L.append(f"## T1. Side by side on the same {len(XK)} facts ({SCH}; served-wrong % [fact CI] {{repo-cluster CI}}; B = 2000 cluster, 1000 fact)\n")
L.append(f"| policy | {QN}: served-wrong % | {QN}: tokens/fact | {QN}: re-der./fact | {XN}: served-wrong % | {XN}: tokens/fact | {XN}: re-der./fact | {XN}: judge calls/fact |\n|---|---|---|---|---|---|---|---|")
S = {}
for pol, lab in ARMS:
    sq, sx = summ(PF[("q", pol)], XK), summ(PF[("x", pol)], XK)
    S[pol] = (sq, sx)
    fmt = lambda s: (f"{p1(s['sw'])} {ci1(s['sw_ci'])} {{{p1(s['clu_ci'][0])}, {p1(s['clu_ci'][1])}}}" + ("" if s["n"] == len(XK) else f" (n={s['n']})"),
                     f"{s['tok_per_fact'] / 1000:.1f}k", f"{s['der_per_fact']:.2f}", f"{s['calls_per_fact']:.1f}") if s else ("not run",) * 4
    a, b = fmt(sq), fmt(sx)
    L.append(f"| {lab} | {a[0]} | {a[1]} | {a[2]} | {b[0]} | {b[1]} | {b[2]} | {b[3]} |")
    OUT[f"T1|{pol}"] = {"q": sq, "x": sx}


def ranks(model):
    vals = {pol: S[pol][0 if model == "q" else 1] for pol, _ in ARMS}
    vals = {k: v for k, v in vals.items() if v}
    sw = sorted(vals, key=lambda k: vals[k]["sw"])
    tk = sorted(vals, key=lambda k: vals[k]["tok_per_fact"])
    return sw, tk


rq, rx = ranks("q"), ranks("x")
L.append(f"\nRanking by served-wrong (best first): {QN}: {' < '.join(rq[0])}; {XN}: {' < '.join(rx[0])}.")
L.append(f"Ranking by tokens/fact (cheapest first): {QN}: {' < '.join(rq[1])}; {XN}: {' < '.join(rx[1])}.")
try:
    from scipy.stats import kendalltau
    com = [p for p in rq[0] if p in rx[0]]
    OUT["kendall_sw"] = kendalltau([rq[0].index(p) for p in com], [rx[0].index(p) for p in com]).statistic
    L.append(f"Kendall τ between the two served-wrong rankings ({len(com)} policies): {OUT['kendall_sw']:.2f}.\n")
except Exception as ex:
    L.append(f"(kendall failed {ex!r})")
OUT["rank"] = {"q": rq, "x": rx}
L.append("\n### T1c. LLM calls per fact (judge calls + agent turns of every re-derivation; CERT-ZS + 1 extraction) and the completion share of tokens\n")
L.append(f"| policy | {QN}: calls/fact | {XN}: calls/fact | facts |\n|---|---|---|---|")
for pol, lab in ARMS[2:] + [ARMS[0]]:
    fq, fx = PF[("q", pol)], PF[("x", pol)]
    if fx is None or fq is None:
        continue
    ids = sorted(set(XK) & set(fx.index) & set(fq.index))
    L.append(f"| {lab} | {fq.loc[ids].calls.mean():.1f} | {fx.loc[ids].calls.mean():.1f} | {len(ids)} |")

# ------------------------------------------------------------------ paired, NI, cost ratio
def boot_ratio(ta, tb, ids, seed=3):
    ta, tb = np.asarray(ta, float), np.asarray(tb, float)
    repo = np.array([QFX[i]["repo"] for i in ids]); reps = sorted(set(repo)); ridx = np.array([reps.index(r) for r in repo])
    rng = np.random.default_rng(seed)
    wf = rng.multinomial(len(ids), np.full(len(ids), 1 / len(ids)), size=B).astype(float)
    draws = rng.integers(0, len(reps), size=(B, len(reps)))
    cnt = np.stack([(draws == j).sum(1) for j in range(len(reps))], 1)[:, ridx].astype(float)
    f = lambda W: (W @ tb) / np.maximum(W @ ta, 1)
    return tb.mean() / max(ta.mean(), 1), np.percentile(f(wf), [2.5, 97.5]).tolist(), np.percentile(f(cnt), [2.5, 97.5]).tolist()


L.append("## T2. Paired ESM − baseline on the same facts (pp; positive = ESM worse), non-inferiority, cost ratio B / ESM\n")
L.append("NI at m: the one-sided 95 % upper bound of ESM − B (95th bootstrap percentile) is below m (fact / cluster bootstrap).\n")
L.append("| model | baseline | facts | ESM % / B % | Δ pp [fact 95 %] {cluster 95 %} | one-sided 95 % upper bound fact / cluster | NI 0.5 / 1.0 / 1.5 / 2.0 pp (fact; cluster) | repos ESM better / tie / worse | tokens ESM / B | token ratio B/ESM [fact] {cluster} | LLM-call ratio B/ESM {cluster} |"
         "\n|---|---|---|---|---|---|---|---|---|---|---|")
for mk, mn in (("q", QN), ("x", XN)):
    fE = PF[(mk, "ESM-norepair")]
    if fE is None:
        continue
    for pol, lab in ARMS[1:]:
        fB = PF[(mk, pol)]
        if fB is None:
            continue
        ids = set(XK) & set(fE.index) & set(fB.index)
        p = paired_stats(fE, fB, ids)
        idl = sorted(ids)
        rt, rf, rc = boot_ratio(fE.loc[idl].tok, fB.loc[idl].tok, idl)
        ct_, cf_, cc_ = boot_ratio(fE.loc[idl].calls, fB.loc[idl].calls, idl)
        hf, hc = p["fact"][3], p["clu"][3]
        ni = [("y" if hf < m else "n") + "/" + ("y" if hc < m else "n") for m in MARGINS]
        OUT[f"paired|{mk}|{pol}"] = {"p": p, "ratio": rt, "ratio_fact": rf, "ratio_clu": rc, "ni": ni,
                                     "cratio": ct_, "cratio_clu": cc_, "calls_e": float(fE.loc[idl].calls.mean()), "calls_b": float(fB.loc[idl].calls.mean())}
        rs = (f"{rt:.2f} [{rf[0]:.2f}, {rf[1]:.2f}] {{{rc[0]:.2f}, {rc[1]:.2f}}} | {ct_:.2f} {{{cc_[0]:.2f}, {cc_[1]:.2f}}}"
              if pol != "NEVER" else "– | –")
        L.append(f"| {mn} | {lab} | {p['n']} | {p1(p['wa'])} / {p1(p['wb'])} | {100 * p['d']:+.2f} [{100 * p['fact'][0]:+.2f}, {100 * p['fact'][1]:+.2f}] "
                 f"{{{100 * p['clu'][0]:+.2f}, {100 * p['clu'][1]:+.2f}}} | {100 * hf:+.2f} / {100 * hc:+.2f} | {' · '.join(ni)} "
                 f"| {p['repo_neg']} / {p['repo_zero']} / {p['repo_pos']} | {p['toka'] / 1000:.1f}k / {p['tokb'] / 1000:.1f}k | {rs} |")

L.append("\n### T2b. Direction check: does each paired effect and cost ratio have the same sign under both models?\n")
L.append(f"| baseline | ESM − B, {QN} | ESM − B, {XN} | direction (no significant opposite effects) | token ratio {QN} | token ratio {XN} | both token ratios > 1 | LLM-call ratio {QN} / {XN} |\n|---|---|---|---|---|---|---|---|")
for pol, lab in ARMS[2:]:
    a, b = OUT.get(f"paired|q|{pol}"), OUT.get(f"paired|x|{pol}")
    if not a or not b:
        continue
    sig = lambda p: (p["clu"][1] < 0 and -1) or (p["clu"][0] > 0 and 1) or 0          # repo-cluster 95 % CI excludes 0
    word = lambda p: {-1: "ESM better*", 1: "ESM worse*", 0: "n.s."}[sig(p)] + f" ({100 * p['d']:+.2f})"
    same = "consistent" if sig(a["p"]) * sig(b["p"]) >= 0 else "OPPOSITE"
    L.append(f"| {lab} | {word(a['p'])} | {word(b['p'])} | {same} | {a['ratio']:.2f} | {b['ratio']:.2f} | {'yes' if a['ratio'] > 1 and b['ratio'] > 1 else 'no'} | {a['cratio']:.2f} / {b['cratio']:.2f} |")

# ------------------------------------------------------------------ halves
L.append("\n## T3. By half (natural / change-enriched): served-wrong % and tokens/fact\n")
L.append(f"| policy | half | facts | {QN} % | {QN} tok/fact | {XN} % | {XN} tok/fact |\n|---|---|---|---|---|---|---|")
for pol, lab in ARMS:
    for hn, hs in (("natural", set(XK) & NATX), ("enriched", set(XK) - NATX)):
        fq, fx = PF[("q", pol)], PF[("x", pol)]
        cell = lambda f: (f"{p1(f.loc[sorted(hs & set(f.index))].sw.sum() / f.loc[sorted(hs & set(f.index))].reads.sum())}",
                          f"{f.loc[sorted(hs & set(f.index))].tok.mean() / 1000:.1f}k") if f is not None and hs & set(f.index) else ("–", "–")
        a, b = cell(fq), cell(fx)
        L.append(f"| {lab} | {hn} | {len(hs)} | {a[0]} | {a[1]} | {b[0]} | {b[1]} |")

# ------------------------------------------------------------------ anchoring phenomenon / re-derivation accuracy
def anchored_share(d):
    """share of wrong-served reads that lie in episodes starting at a wrong re-derivation (ESM)."""
    if d is None:
        return np.nan, 0, 0
    anch = tot = 0
    for iid, x in d.sort_values(["iid", "t"]).groupby("iid"):
        sv, ac = x.served_valid.to_numpy(), x.action.to_numpy()
        k = 0
        while k < len(sv):
            if not sv[k]:
                j = k
                while j < len(sv) and not sv[j]:
                    j += 1
                tot += j - k
                if ac[k] == "rederive":
                    anch += j - k
                k = j
            else:
                k += 1
    return anch / max(tot, 1), anch, tot


def repeat_pairs(d, facts_fx):
    """consecutive re-derivation pairs of the same fact under one policy: (first wrong, second wrong, identical answer)."""
    rows = []
    if d is None:
        return rows
    r = d[d.n_der > 0].sort_values(["iid", "t"])
    for iid, x in r.groupby("iid"):
        v = x.served_valid.to_numpy()
        s = x.served.astype(str).str.strip().to_numpy()
        for k in range(len(v) - 1):
            rows.append((iid, not v[k], not v[k + 1], s[k] == s[k + 1]))
    return rows


L.append("\n## T4. The 'wrong re-derivation gets anchored' phenomenon\n")
L.append(f"| quantity | {QN} | {XN} |\n|---|---|---|")
dq_e, dx_e = qwen_records("ESM-norepair"), x_records("ESM-norepair")
if dq_e is not None:
    dq_e = dq_e[dq_e.iid.isin(set(XK))]
aq, ax_ = anchored_share(dq_e), anchored_share(dx_e)
L.append(f"| ESM: wrong-served reads in episodes that start at a wrong re-derivation | {p1(aq[0])} % ({aq[1]}/{aq[2]}) | {p1(ax_[0])} % ({ax_[1]}/{ax_[2]}) |")
OUT["anchored"] = {"q": aq, "x": ax_}


def rd_acc(mk, fx, ids):
    """re-derivations made by the compared arms (records with n_der > 0), one per (fact, commit)."""
    parts = []
    for pol, _ in ARMS[1:]:
        d = qwen_records(pol) if mk == "q" else x_records(pol)
        if d is not None:
            parts.append(d[(d.n_der > 0) & d.iid.isin(ids) & (d.t > 0)])
    if not parts:
        return pd.DataFrame(columns=["correct", "changed", "none", "noans", "tok"])
    d = pd.concat(parts).drop_duplicates(["iid", "t"])
    tr = [fx[i]["truth"][300 + int(t)] for i, t in zip(d.iid, d.t)]
    return pd.DataFrame({"iid": d.iid.values, "t": d.t.values, "correct": d.served_valid.values.astype(bool),
                         "changed": [a != fx[i]["truth"][300] for a, i in zip(tr, d.iid)], "none": [a == "NONE" for a in tr],
                         "noans": (d.served.astype(str).str.strip() == "").values, "tok": d.der_tok.values})


rq_ = rd_acc("q", QFX, set(XK))
rx_ = rd_acc("x", XFX, set(XK))
for lab, fn in [("re-derivations at t > 0 made by the compared arms (one per fact × commit), n", lambda d: f"{len(d)}"),
                ("  correct %", lambda d: p1(d.correct.mean())),
                ("  correct % when the truth differs from s0", lambda d: p1(d[d.changed].correct.mean()) + f" (n={int(d.changed.sum())})"),
                ("  correct % when the truth equals s0", lambda d: p1(d[~d.changed].correct.mean()) + f" (n={int((~d.changed).sum())})"),
                ("  correct % when the oracle is NONE", lambda d: p1(d[d.none].correct.mean()) + f" (n={int(d.none.sum())})"),
                ("  no answer %", lambda d: p1(d.noans.mean())),
                ("  tokens per re-derivation", lambda d: f"{d.tok.mean() / 1000:.1f}k")]:
    try:
        L.append(f"| {lab} | {fn(rq_)} | {fn(rx_)} |")
    except Exception as ex:
        L.append(f"| {lab} | ? | ? ({ex!r})"[:200])
OUT["rd_acc"] = {"q": float(rq_.correct.mean()) if len(rq_) else None, "x": float(rx_.correct.mean()) if len(rx_) else None}
L.append("\nRepeat-error rate on consecutive re-derivation pairs (same fact, same policy): P(2nd wrong | 1st wrong) "
         "[identical answer string among wrong→wrong], and P(2nd wrong | 1st right) for contrast.\n")
L.append(f"| policy | {QN}: pairs, P(w→w) [identical] | {QN}: P(r→w) | {XN}: pairs, P(w→w) [identical] | {XN}: P(r→w) |\n|---|---|---|---|---|")
tot = {"q": [], "x": []}
for pol, lab in ARMS:
    if pol == "NEVER":
        continue
    cells = []
    for mk, fx, recf in (("q", QFX, lambda p: (lambda d: d[d.iid.isin(set(XK))] if d is not None else None)(qwen_records(p))),
                         ("x", XFX, x_records)):
        rows = repeat_pairs(recf(pol), fx)
        tot[mk] += rows
        w = [r for r in rows if r[1]]
        rr = [r for r in rows if not r[1]]
        ww = [r for r in w if r[2]]
        cells.append((f"{len(rows)}, {p1(len(ww) / max(len(w), 1))} % of {len(w)} [{sum(r[3] for r in ww)}]",
                      f"{p1(sum(r[2] for r in rr) / max(len(rr), 1))} % of {len(rr)}"))
    L.append(f"| {lab} | {cells[0][0]} | {cells[0][1]} | {cells[1][0]} | {cells[1][1]} |")
for mk in ("q", "x"):
    rows = tot[mk]
    w = [r for r in rows if r[1]]; ww = [r for r in w if r[2]]; rr = [r for r in rows if not r[1]]
    OUT[f"repeat|{mk}"] = {"pairs": len(rows), "w": len(w), "ww": len(ww), "ww_ident": sum(r[3] for r in ww),
                           "rw": sum(r[2] for r in rr), "r": len(rr)}
a, b = OUT["repeat|q"], OUT["repeat|x"]
L.append(f"| **pooled** | {a['pairs']}, **{p1(a['ww'] / max(a['w'], 1))} %** of {a['w']} [{a['ww_ident']}] | {p1(a['rw'] / max(a['r'], 1))} % | "
         f"{b['pairs']}, **{p1(b['ww'] / max(b['w'], 1))} %** of {b['w']} [{b['ww_ident']}] | {p1(b['rw'] / max(b['r'], 1))} % |")

# ------------------------------------------------------------------ detection only
L.append(f"\n## T5. Transition judge, detection only (pilot7 definitions: stored answer = s0 K; per-commit FF / FS) on the same facts\n")
L.append(f"| model | facts | FF % [CI] | FS % [CI] | static FF / FS | behaviour FF / FS | judge calls/fact |\n|---|---|---|---|---|---|---|")
for mk, mn in (("q", QN), ("x", XN)):
    f = PF[(mk, "DETECT-anchor-hier")]
    if f is None:
        L.append(f"| {mn} | not run | | | | | |")
        continue
    g = f.loc[sorted(set(XK) & set(f.index))]
    s = M.summary(g)
    sub = lambda h: (lambda z: f"{p1(z.ff.sum() / max(z.ninv.sum(), 1))} / {p1(z.fs.sum() / max(z.nval.sum(), 1))}")(g[g.slice == h]) if (g.slice == h).any() else "–"
    OUT[f"detect|{mk}"] = s
    L.append(f"| {mn} | {len(g)} | {p1(s['ff'])} {ci1(s['ff_ci'])} | {p1(s['fs'])} {ci1(s['fs_ci'])} | {sub('static')} | {sub('behav')} | {s['calls_per_fact']:.1f} |")

# ------------------------------------------------------------------ cost breakdown
L.append("\n## T6. Where ESM's tokens go\n")
L.append(f"| quantity | {QN} | {XN} |\n|---|---|---|")
for lab, k in [("judge tokens/fact", "eval_tok_per_fact"), ("re-derivation tokens/fact", "der_tok_per_fact"), ("judge calls/fact", "calls_per_fact"),
               ("re-derivations/fact", "der_per_fact"), ("RDE (unit: the fact's own s0 derivation of the same model)", "rde_sum"),
               ("needless-spend share", "needless_frac"), ("lifetime kept", "life_kept"), ("FS (maintenance)", "fs"),
               ("stored-wrong episodes never acted on", "eps_missed")]:
    sq, sx = S["ESM-norepair"]
    fm = (lambda v: f"{v / 1000:.1f}k") if "tok" in k else ((lambda v: f"{v:.2f}") if k in ("calls_per_fact", "der_per_fact", "rde_sum") else (lambda v: f"{p1(v)} %"))
    L.append(f"| {lab} | {fm(sq[k]) if sq else '–'} | {fm(sx[k]) if sx else '–'} |")

# ------------------------------------------------------------------ shared 50-commit grid (REPLAY fallback)
def grid_frames(mk, pol):
    if mk == "q":
        d = qwen_records(pol, "every50")
        return perfact(d, QFACTS, pol, QCT) if d is not None else None
    p = XD / "sim" / f"{pol}__every50.parquet"
    if not p.exists():
        return None
    d = pd.read_parquet(p)
    d = d[d.iid.isin(set(XK))]
    if not len(d):
        return None
    f = M.per_fact(d, XFACTS)
    return f


G = {(mk, pol): grid_frames(mk, pol) for mk in ("q", "x") for pol in ("ESM-norepair", "REPLAY", "NEVER")}
if G[("x", "ESM-norepair")] is not None:
    L.append("\n## T7. Shared 50-commit grid (reads and re-derivations only at t = 50, 100, ..., 400)\n")
    L.append("Qwen every50 records: Stage 2 (H150 part of X120) + qwen_every50.py (the other X120 facts, Stage-2 cache + 24 new 27B judge calls). Rows are on the facts both models have.\n")
    L.append("| model | policy | facts | served-wrong % | tokens/fact | re-der./fact | Δ ESM − policy pp [fact] {cluster} | ratio policy/ESM |\n|---|---|---|---|---|---|---|---|")
    ids_g = set(XK)
    for k, v in G.items():
        if v is not None:
            ids_g &= set(v.index)
    for mk, mn in (("q", QN), ("x", XN)):
        fE = G[(mk, "ESM-norepair")]
        for pol in ("ESM-norepair", "REPLAY", "NEVER"):
            f = G[(mk, pol)]
            if f is None or fE is None:
                continue
            g = f.loc[sorted(ids_g)]
            ex = ""
            if pol != "ESM-norepair":
                p = paired_stats(fE, f, ids_g)
                ex = f"{100 * p['d']:+.2f} [{100 * p['fact'][0]:+.2f}, {100 * p['fact'][1]:+.2f}] {{{100 * p['clu'][0]:+.2f}, {100 * p['clu'][1]:+.2f}}}"
                OUT[f"grid|{mk}|{pol}"] = p
            rt = g.tok.mean() / max(fE.loc[sorted(ids_g)].tok.mean(), 1)
            L.append(f"| {mn} | {pol} | {len(g)} | {p1(g.sw.sum() / g.reads.sum())} | {g.tok.mean() / 1000:.1f}k | {g.n_der.mean():.2f} | {ex} | {rt:.2f} |")

# ------------------------------------------------------------------ figures
try:
    fig, axs = plt.subplots(1, 2, figsize=(10, 4), sharey=True)
    for ax, (mk, mn) in zip(axs, (("q", QN), ("x", XN))):
        for pol, lab in ARMS:
            s = S[pol][0 if mk == "q" else 1]
            if not s:
                continue
            x = max(s["tok_per_fact"] / 1000, 0.3)
            ax.errorbar(x, 100 * s["sw"], yerr=[[100 * (s["sw"] - s["clu_ci"][0])], [100 * (s["clu_ci"][1] - s["sw"])]], fmt="o", capsize=2, ms=5,
                        color="#c2452d" if pol == "ESM-norepair" else "#3b6fb6")
            ax.annotate(lab.split(" ")[0], (x, 100 * s["sw"]), fontsize=7, xytext=(4, 3), textcoords="offset points")
        ax.set_xscale("log"); ax.set_xlabel("LLM tokens per fact (k, log; NEVER drawn at 0.3k)")
        ax.set_title(f"{mn} (same {len(XK)} facts, {SCH})", fontsize=9)
    axs[0].set_ylabel("served-wrong % (repo-cluster 95 % CI)")
    fig.tight_layout(); fig.savefig(HERE / f"fig_xmodel_tradeoff{SUF}.png", dpi=140); plt.close(fig)
    fig, axs = plt.subplots(1, 2, figsize=(10, 3.6))
    bl = [p for p, _ in ARMS[2:]]
    for j, (mk, mn, c) in enumerate((("q", QN, "#7a7a7a"), ("x", XN, "#c2452d"))):
        for i, pol in enumerate(bl):
            o = OUT.get(f"paired|{mk}|{pol}")
            if not o:
                continue
            y = i + (0.15 if j else -0.15)
            p = o["p"]
            axs[0].errorbar(100 * p["d"], y, xerr=[[100 * (p["d"] - p["clu"][0])], [100 * (p["clu"][1] - p["d"])]], fmt="o", color=c, capsize=2,
                            label=mn if i == 0 else None)
            axs[1].errorbar(o["ratio"], y, xerr=[[o["ratio"] - o["ratio_clu"][0]], [o["ratio_clu"][1] - o["ratio"]]], fmt="o", color=c, capsize=2)
    for ax in axs:
        ax.set_yticks(range(len(bl))); ax.set_yticklabels(bl)
    axs[0].axvline(0, color="k", lw=0.6); axs[1].axvline(1, color="k", lw=0.6)
    axs[0].set_xlabel("ESM − baseline, served-wrong pp (cluster 95 % CI)"); axs[1].set_xlabel("token ratio baseline / ESM (cluster 95 % CI)")
    axs[1].set_xscale("log"); axs[0].legend(fontsize=7)
    fig.tight_layout(); fig.savefig(HERE / f"fig_xmodel_paired{SUF}.png", dpi=140); plt.close(fig)
except Exception as ex:
    L.append(f"(figure failed: {ex!r})")

if REC:
    pd.concat(REC, ignore_index=True).to_parquet(HERE / f"records{SUF}.parquet", index=False)
(HERE / f"tables{SUF}.md").write_text("\n".join(L), encoding="utf-8")
(HERE / f"results{SUF}.json").write_text(json.dumps(OUT, indent=1, default=lambda o: float(o) if np.isscalar(o) else str(o)), encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")
print("\n".join(L))
