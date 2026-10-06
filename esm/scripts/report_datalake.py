"""Data-lake analysis (zero LLM): tables, curves, schema-event and synthetic-event analyses, taxonomy.
usage: ESM_DATA=<E:...esm_data_datalake> ESM_STAGE=datalake python -m esm.scripts.report_datalake
-> esm/results/datalake/{tables.md, results.json, records.parquet, curves_*.png, rederivation_accuracy.png, examples.txt}"""
import json, glob, os
from collections import Counter, defaultdict
os.environ["ESM_LLM_OFFLINE"] = "1"
os.environ.setdefault("ESM_STAGE", "datalake")
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from esm import metrics as M
from esm.common import DATA, RESULTS
from esm.maintain import read_shards
from esm.policies import Context

FROZEN = "ESM-norepair"
LAKES = {"dl_tlc": "TLC", "dl_bb": "Backblaze"}
GRID = {"dl_tlc": "every25", "dl_bb": "every20"}
TTLS = {"dl_tlc": ["TTL25", "TTL50", "TTL100"], "dl_bb": ["TTL20", "TTL40", "TTL100"]}
L, OUT = [], {}


def pct(x):
    return "–" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{100 * x:.1f}"


def ci(c):
    return f"[{100 * c[0]:.1f}, {100 * c[1]:.1f}]"


HDR = ("| policy | facts | served-wrong % [CI] | FF % | FS % | episodes never acted on % | tokens/fact | tokens/read | RDE "
       "| judge calls/fact | re-derivations/fact | changing facts ever served wrong % |\n|---|---|---|---|---|---|---|---|---|---|---|---|")


def line(name, s):
    return (f"| {name} | {s['n']} | {pct(s['sw'])} {ci(s['sw_ci'])} | {pct(s['ff'])} | {pct(s['fs'])} | {pct(s['eps_missed'])} "
            f"| {s['tok_per_fact'] / 1000:.1f}k | {s['tok_per_read']:.0f} | {s['rde_sum']:.2f} | {s['calls_per_fact']:.1f} "
            f"| {s['der_per_fact']:.2f} | {pct(s['ever_sw_chg'])} |")


class Lake:
    """Everything loaded for one lake kind."""

    def __init__(self, kind):
        self.kind, self.name = kind, LAKES.get(kind, kind)
        self.ctx = Context.load(kind)
        self.F = self.ctx.facts
        self.FX = {f["iid"]: f for f in self.F}
        self.RAW = self.ctx.raw
        sub = self.ctx.sub
        self.SUB = {"ALL": set(self.FX)}
        for k in ("S", "SYN", "SYNK"):
            p = sub / f"sub_{k}.json"
            if p.exists():
                self.SUB[k] = set(json.loads(p.read_text())) & set(self.FX)
        self.SUB["natural"] = {i for i in self.FX if self.FX[i]["subset"] == "natural"}
        self.SUB["enriched"] = set(self.FX) - self.SUB["natural"]
        if "S" in self.SUB:
            self.SUB["S-natural"] = self.SUB["S"] & self.SUB["natural"]
        frames, self.PF = [], {}
        for p in sorted(glob.glob(str(sub / "sim" / "*.parquet"))):
            pol, sch = os.path.basename(p)[:-8].split("__")
            d = pd.read_parquet(p)
            d = d[d.iid.isin(self.FX)]
            if not len(d):
                continue
            d["policy"], d["schedule"], d["lake"] = pol, sch, kind
            frames.append(d)
            self.PF[(pol, sch)] = M.per_fact(d, self.F)
        self.REC = (pd.concat(frames, ignore_index=True) if frames else
                    pd.DataFrame(columns=["iid", "t", "policy", "schedule", "served_valid", "stored_valid", "flagged", "action",
                                          "eval_calls", "n_der", "verdict", "served", "reason"]))
        # R = longest prefix of the main run's seeded random order (run_sim --order random:7) whose facts are all complete
        import random as _r
        perm = sorted(self.FX)
        _r.Random(7).shuffle(perm)
        done = set(self.PF[(FROZEN, "every")].index) if (FROZEN, "every") in self.PF else set()
        pre = []
        for i in perm:
            if i not in done:
                break
            pre.append(i)
        self.SUB["R"] = set(pre)
        self.SUB["R-natural"] = self.SUB["R"] & self.SUB["natural"]
        self.SUB["ESMdone"] = done
        self.SETUP = {f["iid"]: (f.get("cert_tokens") or {}).get("certzs") or 0 for f in self.F}

    def pf(self, pol, sch):
        pf = self.PF.get((pol, sch))
        if pf is None:
            return None
        if pol == "CERT-ZS":
            pf = pf.copy()
            pf["tok"] = pf.tok + np.array([self.SETUP.get(i, 0) for i in pf.index], float)
            pf["rde"] = pf.tok / pf.dtok
        return pf

    def summ(self, pol, sch, ids, require_full=True):
        pf = self.pf(pol, sch)
        if pf is None:
            return None
        idx = ids & set(pf.index)
        if not idx or (require_full and len(idx) < len(ids)):
            return None
        return M.summary(pf.loc[sorted(idx)])


LK = {}
for kind in ("dl_tlc", "dl_bb", "dlsyn_tlc", "dlsyn_bb"):
    try:
        if (DATA / kind / "derivations.jsonl").parent.exists() and read_shards(DATA / kind / "derivations.jsonl"):
            LK[kind] = Lake(kind)
    except Exception as e:                       # a kind that was not run
        print("skip", kind, repr(e)[:200])
REAL = [k for k in ("dl_tlc", "dl_bb") if k in LK]
allrec = [LK[k].REC for k in LK if len(LK[k].REC)]
if allrec:
    pd.concat(allrec, ignore_index=True).to_parquet(RESULTS / "records.parquet", index=False)


def table(lk, title, pols, ids, sch="every", key=None, note=""):
    L.append(f"\n### {title}\n")
    if note:
        L.append(note + "\n")
    L.append(HDR)
    res = {}
    for p in pols:
        s = lk.summ(p, sch, ids)
        if s is None:
            continue
        L.append(line(p, s))
        res[p] = s
    if key:
        OUT[key] = res
    return res


L.append("# ESM on the evolving data lake — tables (generated by esm/scripts/report_datalake.py)\n")
L.append("All rates pooled over (fact, read) pairs; CIs: bootstrap over facts (B = 1000). Headline lakes are REAL-ONLY "
         "(synthetic events removed; PLAN.md). RDE = tokens / the fact's own s0 derivation tokens (27B). '@oracle' = re-derivation "
         "replaced by the oracle answer (idealised; cost = the s0 derivation's tokens). tokens/read = evaluator + re-derivation tokens "
         f"/ reads. Frozen ESM = {FROZEN} (Stage 2): anchored evidence, hierarchical deltas, changed/unsure ⇒ 27B re-derivation.")

# ------------------------------------------------------------------ T0 s0 derivation
L.append("\n## T0. s0 derivation (qwen3.6:27b agent, ≤ 12 tool calls, NONE instruction); kept iff the answer matches the oracle\n")
L.append("| lake | split | facts | correct % | wrong % | no answer % | tokens/derivation | LLM calls | tool calls | kept | changing kept |\n|---|---|---|---|---|---|---|---|---|---|---|")
OUT["T0"] = {}
for kind in REAL + [k for k in LK if k.startswith("dlsyn")]:
    lk = LK[kind]
    raw = pd.DataFrame([{"iid": f["iid"], "type": f["type"], "subset": f["subset"], "status": f.get("s0_status", "missing"),
                         "tok": sum((f.get("s0") or {}).get("tokens") or [0, 0]), "calls": (f.get("s0") or {}).get("n_llm", 0),
                         "ntool": len((f.get("s0") or {}).get("trace") or [])} for f in lk.RAW])
    if kind.startswith("dlsyn") and "SYN" in lk.SUB:
        raw = raw[raw.iid.isin(set(json.loads((lk.ctx.sub / "sub_SYN.json").read_text())))]
    for col in (None, "subset", "type"):
        groups = [("all", raw)] if col is None else [(f"{col}={v}", g) for v, g in raw.groupby(col)]
        for name, g in groups:
            d = g[g.status != "missing"]
            if not len(d):
                continue
            kept = [i for i in d.iid if i in lk.FX]
            r = {"n": len(g), "derived": len(d), "correct": float((d.status == "correct").mean()), "wrong": float((d.status == "wrong").mean()),
                 "noans": float((d.status == "no_answer").mean()), "kept": len(kept),
                 "kept_chg": sum(1 for i in kept if not all(lk.FX[i]["valid"]))}
            OUT["T0"][f"{kind}|{name}"] = r
            L.append(f"| {lk.name if kind in LAKES else kind} | {name} | {len(g)}{'' if len(d) == len(g) else f' ({len(d)} derived)'} | {pct(r['correct'])} "
                     f"| {pct(r['wrong'])} | {pct(r['noans'])} | {d.tok.mean() / 1000:.1f}k | {d.calls.mean():.1f} | {d.ntool.mean():.1f} "
                     f"| {r['kept']} | {r['kept_chg']} |")

# ------------------------------------------------------------------ T1 main tables (every snapshot)
BASEO = ["ALWAYS@oracle", "REPLAY@oracle", "FILEHASH@oracle", "MANIFEST@oracle", "CERT-ZS@oracle"]
for kind in REAL:
    lk = LK[kind]
    for nm in ("R", "R-natural", "ALL", "natural", "enriched"):
        ids = lk.SUB[nm]
        if not ids:
            continue
        table(lk, f"T1 [{lk.name}, {nm}] every snapshot ({len(ids)} facts)",
              [FROZEN, "NEVER"] + [t + "@oracle" for t in TTLS[kind]] + BASEO + [FROZEN + "@oracle", "DETECT-anchor-hier"],
              ids, key=f"T1|{kind}|{nm}")
# pooled over both lakes (facts of both)
if len(REAL) == 2:
    L.append("\n### T1-pooled. Both lakes pooled (every snapshot)\n")
    L.append("| set | facts | ESM served-wrong % [CI] | NEVER % [CI] | ESM tokens/fact | ESM tokens/read |\n|---|---|---|---|---|---|")
    OUT["T1pooled"] = {}
    for nm in ("R", "R-natural", "ESMdone"):
        pfs, pns = [], []
        for kind in REAL:
            lk = LK[kind]
            a, b = lk.pf(FROZEN, "every"), lk.pf("NEVER", "every")
            if a is None or b is None:
                continue
            ids = sorted(lk.SUB[nm] & set(a.index) & set(b.index))
            pfs.append(a.loc[ids]); pns.append(b.loc[ids])
        if len(pfs) == 2:
            sa, sb = M.summary(pd.concat(pfs)), M.summary(pd.concat(pns))
            OUT["T1pooled"][nm] = {"esm": sa, "never": sb}
            L.append(f"| {nm} | {sa['n']} | {pct(sa['sw'])} {ci(sa['sw_ci'])} | {pct(sb['sw'])} {ci(sb['sw_ci'])} | {sa['tok_per_fact'] / 1000:.1f}k | {sa['tok_per_read']:.0f} |")

# ------------------------------------------------------------------ T1c / T1d real-cost comparisons on S
ABL = ["ESM-norepair-noanchor", "ESM-norepair-trunc", "ESM-norepair-unsurefresh", "ESM-verify", "ESM-norepair-9B"]
REALB = ["REPLAY", "FILEHASH", "MANIFEST", "CERT-ZS", "LLMDIFF"]
for kind in REAL:
    lk = LK[kind]
    if "S" not in lk.SUB:
        continue
    S = lk.SUB["S"]
    table(lk, f"T1c [{lk.name}] S ({len(S)} facts): real 27B re-derivation baselines and ablations, every snapshot",
          [FROZEN] + ABL + TTLS[kind] + REALB + ["NEVER"] + [t + "@oracle" for t in TTLS[kind]] + BASEO + [FROZEN + "@oracle"], S,
          key=f"T1c|{kind}")
    g = GRID[kind]
    table(lk, f"T1d [{lk.name}] S, shared re-derivation grid (schedule {g}: reads AND re-derivations only at grid points; ALWAYS = re-derive at every grid read)",
          [FROZEN, "ALWAYS"] + REALB + TTLS[kind] + ["ESM-norepair-noanchor", "NEVER"] + [b + "@oracle" for b in ("ALWAYS", "REPLAY", "FILEHASH", "MANIFEST")],
          S, sch=g, key=f"T1d|{kind}")

# ------------------------------------------------------------------ T2 paired
L.append("\n## T2. Paired differences A − B (pp; tokens per fact), bootstrap over common facts (B = 2000)\n")
L.append("| lake | A − B | set | schedule | facts | Δserved-wrong [CI] | ΔFF [CI] | ΔFS [CI] | Δtokens/fact [CI] |\n|---|---|---|---|---|---|---|---|---|")
OUT["paired"] = {}
for kind in REAL:
    lk = LK[kind]
    g = GRID[kind]
    pairs = [(FROZEN, "NEVER", s_, "every") for s_ in ("R", "R-natural", "ESMdone", "S")]
    pairs += [(FROZEN, b, "R", "every") for b in [t + "@oracle" for t in TTLS[kind]] + BASEO]
    pairs += [(FROZEN, b, "S", "every") for b in TTLS[kind] + REALB + ABL]
    pairs += [(FROZEN, b, "S", g) for b in ["ALWAYS"] + REALB + TTLS[kind] + ["ESM-norepair-noanchor"]]
    pairs += [(FROZEN, "NEVER", "S", s_) for s_ in ("every5", "every20", "bursty", g)]
    pairs += [(FROZEN, "NEVER", "ALL", s_) for s_ in ("every5", "every20", "bursty")]
    for a_, b_, s_, sch in pairs:
        pa, pb = lk.pf(a_, sch), lk.pf(b_, sch)
        if pa is None or pb is None or s_ not in lk.SUB:
            continue
        ids = lk.SUB[s_] & set(pa.index) & set(pb.index)
        if len(ids) < 5 or len(ids) < 0.9 * len(lk.SUB[s_]):
            continue
        r = M.paired(pa.loc[sorted(ids)], pb.loc[sorted(ids)])
        OUT["paired"][f"{kind}|{a_}-{b_}|{s_}|{sch}"] = r
        L.append(f"| {lk.name} | {a_} − {b_} | {s_} | {sch} | {r['n']} | {100 * r['dsw']:+.1f} [{100 * r['dsw_ci'][0]:+.1f}, {100 * r['dsw_ci'][1]:+.1f}] "
                 f"| {100 * r['dff']:+.1f} [{100 * r['dff_ci'][0]:+.1f}, {100 * r['dff_ci'][1]:+.1f}] "
                 f"| {100 * r['dfs']:+.1f} [{100 * r['dfs_ci'][0]:+.1f}, {100 * r['dfs_ci'][1]:+.1f}] "
                 f"| {r['dtok'] / 1000:+.1f}k [{r['dtok_ci'][0] / 1000:+.1f}, {r['dtok_ci'][1] / 1000:+.1f}] |")

# ------------------------------------------------------------------ T3 by type and subset (incl. D3 vs D4)
L.append("\n## T3. Frozen ESM by type / subset (every snapshot, ALL) — incl. the D3 (partition aggregate) vs D4 (running aggregate) question\n")
L.append("| lake | split | facts | changing | ESM served-wrong % [CI] | NEVER % | reads served with zero LLM % | judge calls/fact | re-derivations/fact | re-derivations at reads whose stored answer was still right | tokens/fact | episodes never acted on % |\n|---|---|---|---|---|---|---|---|---|---|---|---|")
OUT["T3"] = {}
for kind in REAL:
    lk = LK[kind]
    pf, pn = lk.pf(FROZEN, "every"), lk.pf("NEVER", "every")
    if pf is None:
        continue
    d = lk.REC[(lk.REC.policy == FROZEN) & (lk.REC.schedule == "every")]
    pf = pf.join(pd.Series({i: lk.FX[i]["subset"] for i in pf.index}, name="subset"))
    for col in ("subset", "type"):
        for v, sub in pf.groupby(col):
            s = M.summary(sub)
            sn = M.summary(pn.loc[sub.index]) if pn is not None else None
            dd = d[d.iid.isin(sub.index)]
            zero = float((dd.action.isin(["same", "memo"])).mean())
            needless_der = int(((dd.action == "rederive") & dd.stored_valid).sum())
            OUT["T3"][f"{kind}|{col}={v}"] = {"esm": s, "never": sn, "zero_llm_reads": zero, "needless_der": needless_der}
            L.append(f"| {lk.name} | {col}={v} | {s['n']} | {s['n_chg']} | {pct(s['sw'])} {ci(s['sw_ci'])} | {pct(sn['sw']) if sn else '–'} "
                     f"| {pct(zero)} | {s['calls_per_fact']:.1f} | {s['der_per_fact']:.2f} | {needless_der} | {s['tok_per_fact'] / 1000:.1f}k | {pct(s['eps_missed'])} |")

# ------------------------------------------------------------------ T4 schedules
L.append("\n## T4. Read schedules (cost per read = evaluator + re-derivation tokens / reads)\n")
L.append("| lake | policy | schedule | set | facts | reads/fact | served-wrong % [CI] | FF % | FS % | tokens/fact | tokens/read | judge calls/fact | re-derivations/fact |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|")
OUT["T4"] = {}
for kind in REAL:
    lk = LK[kind]
    for (pol, sch), _ in sorted(lk.PF.items()):
        if pol.startswith("DETECT"):
            continue
        for sname in ("ALL", "S"):
            if sname not in lk.SUB:
                continue
            s = lk.summ(pol, sch, lk.SUB[sname])
            if s is None or (sname == "S" and lk.summ(pol, sch, lk.SUB["ALL"]) is not None):
                continue
            OUT["T4"][f"{kind}|{pol}|{sch}|{sname}"] = s
            L.append(f"| {lk.name} | {pol} | {sch} | {sname} | {s['n']} | {s['reads'] / s['n']:.0f} | {pct(s['sw'])} {ci(s['sw_ci'])} | {pct(s['ff'])} | {pct(s['fs'])} "
                     f"| {s['tok_per_fact'] / 1000:.1f}k | {s['tok_per_read']:.0f} | {s['calls_per_fact']:.1f} | {s['der_per_fact']:.2f} |")

# ------------------------------------------------------------------ T5 detection only
L.append("\n## T5. Detection only, pilot7 framework (stored answer always the s0 K; FF/FS per snapshot)\n")
L.append("| lake | detector | set | facts | FF % [CI] | FS % [CI] | natural FF / FS | judge calls/fact | tokens/fact |\n|---|---|---|---|---|---|---|---|---|")
OUT["T5"] = {}
for kind in REAL:
    lk = LK[kind]
    for pol in ("DETECT-anchor-hier", "DETECT-noanchor-hier", "DETECT-9B"):
        pf = lk.pf(pol, "every")
        if pf is None:
            continue
        for sname in ("ALL", "S"):
            ids = lk.SUB.get(sname, set()) & set(pf.index)
            if not ids or len(ids) < len(lk.SUB[sname]):
                continue
            sub = pf.loc[sorted(ids)]
            s = M.summary(sub)
            na = M.summary(sub[[lk.FX[i]["subset"] == "natural" for i in sub.index]])
            OUT["T5"][f"{kind}|{pol}|{sname}"] = {"all": s, "natural": na}
            L.append(f"| {lk.name} | {pol} | {sname} | {s['n']} | {pct(s['ff'])} {ci(s['ff_ci'])} | {pct(s['fs'])} {ci(s['fs_ci'])} "
                     f"| {pct(na['ff']) if na else '–'} / {pct(na['fs']) if na else '–'} | {s['calls_per_fact']:.1f} | {s['tok_per_fact'] / 1000:.1f}k |")
        if pol == "DETECT-anchor-hier" and pf is not None:
            L.append("\nDetection by type (ALL): " + "; ".join(
                f"{t} FF {pct(M.summary(g)['ff'])} / FS {pct(M.summary(g)['fs'])}" for t, g in pf.groupby("type")))

# ------------------------------------------------------------------ T6 re-derivation accuracy
L.append("\n## T6. Re-derivation accuracy of the 27B agent over time\n")
L.append("| lake | subset | derivations | facts | correct % | answered % | tokens/derivation |\n|---|---|---|---|---|---|---|")
OUT["T6"] = {}
DER = {}
for kind in REAL:
    lk = LK[kind]
    rows = []
    for r in read_shards(lk.ctx.sub / "derivations.jsonl"):
        if r["iid"] in lk.FX:
            f = lk.FX[r["iid"]]
            rows.append({"iid": r["iid"], "t": r["t"], "correct": r["correct"], "tok": sum(r["tokens"]), "answered": r["answer"] is not None,
                         "type": f["type"], "changed": f["truth"][r["t"]] != f["truth"][0], "none": f["truth"][r["t"]] == "NONE"})
    dd = pd.DataFrame(rows).drop_duplicates(["iid", "t"]) if rows else pd.DataFrame()
    DER[kind] = dd
    if not len(dd):
        continue
    n = lk.ctx.env.n_steps()
    parts = [("all t > 0", dd[dd.t > 0]), ("t > 0, truth differs from s0", dd[(dd.t > 0) & dd.changed]),
             ("t > 0, truth equal to s0", dd[(dd.t > 0) & ~dd.changed])]
    q = [0, n // 4, n // 2, 3 * n // 4, n]
    parts += [(f"t in ({q[i]}, {q[i + 1]}]", dd[(dd.t > q[i]) & (dd.t <= q[i + 1])]) for i in range(4)]
    parts += [(f"t > 0, type {t}", g) for t, g in dd[dd.t > 0].groupby("type")]
    o = {}
    for name, sub in parts:
        if len(sub):
            o[name] = {"n": len(sub), "acc": float(sub.correct.mean()), "tok": float(sub.tok.mean())}
            L.append(f"| {lk.name} | {name} | {len(sub)} | {sub.iid.nunique()} | {pct(sub.correct.mean())} | {pct(sub.answered.mean())} | {sub.tok.mean() / 1000:.1f}k |")
    OUT["T6"][kind] = o
    L.append(f"| {lk.name} | RDE unit: kept facts' s0 derivation | {len(lk.F)} | | | | {np.mean([sum(f['derive_tokens']) for f in lk.F]) / 1000:.1f}k |")


# ------------------------------------------------------------------ T9 real schema-change events
def event_times(lk):
    """Real schema / lookup events in FUTURE (t indices of the real-only lake)."""
    lake = lk.ctx.env.lk
    ev = []
    fut = lake.future
    prev = {}
    if lk.kind == "dl_tlc":
        wanted = {("yellow", "2023-02"): "yellow 2023-02: airport_fee→Airport_fee rename + 6 type changes",
                  ("green", "2023-02"): "green 2023-02: 9 type changes", ("fhv", "2023-02"): "fhv 2023-02: 5 type changes",
                  ("fhvhv", "2023-02"): "fhvhv 2023-02: 10 type changes",
                  ("yellow", "2025-01"): "yellow 2025-01: + cbd_congestion_fee", ("green", "2025-01"): "green 2025-01: + cbd_congestion_fee",
                  ("fhvhv", "2025-01"): "fhvhv 2025-01: + cbd_congestion_fee",
                  ("yellow", "2026-06"): "yellow 2026-06: + request_source", ("green", "2026-06"): "green 2026-06: + request_source"}
        for t, s in enumerate(fut, 1):
            e = lake.event_of[s]
            if e["kind"] == "lookup":
                ev.append((t, "zone lookup revision (264/265 relabelled)"))
            if e["kind"] == "arrive" and (e.get("dataset"), e.get("month")) in wanted:
                ev.append((t, wanted[(e["dataset"], e["month"])]))
    else:
        firsts = {"2019-10": "SMART 18 added (131 cols)", "2020-10": "SMART +9 attributes (149 cols)", "2021-07": "SMART +10 (169)",
                  "2021-10": "SMART +5 (179)", "2023-04": "vault_id, pod_id, is_legacy_format + SMART 71/90 (186)",
                  "2023-07": "datacenter, cluster_id, pod_slot_num + SMART 27/82 (193)", "2024-04": "SMART 211/212 (197)"}
        for t, s in enumerate(fut, 1):
            e = lake.event_of[s]
            ms = {p.rsplit("/", 1)[-1][:7] for p in e.get("put", {})}
            for m in ms:
                if m in firsts:
                    ev.append((t, firsts[m]))
    return ev


L.append("\n## T9. Real schema-change events: behaviour of each policy around the event (facts on which the frozen ESM ran: TLC 81, Backblaze 57; every snapshot)\n")
L.append("Affected = facts whose oracle value changes at the event snapshot. For each policy: served-wrong % of the affected facts' reads "
         "in the 10 snapshots from the event on; acted = % of affected facts on which the policy acted (judge-stale / re-derivation) "
         "at the event read; spurious = facts NOT affected whose stored answer was right at the event and on which the policy acted there.\n")
L.append("| lake | t | event | affected facts | policy | served-wrong % (10 reads) | acted at event % | spurious actions | judge calls at event | re-derivations at event |\n|---|---|---|---|---|---|---|---|---|---|")
OUT["T9"] = []
for kind in REAL:
    lk = LK[kind]
    if not len(lk.REC):
        continue
    for t, desc in event_times(lk):
        aff = [i for i in lk.SUB["ESMdone"] if lk.FX[i]["truth"][t] != lk.FX[i]["truth"][t - 1]]
        for pol in [FROZEN, "DETECT-anchor-hier", "NEVER", TTLS[kind][0] + "@oracle", "REPLAY@oracle", "FILEHASH@oracle", "MANIFEST@oracle"]:
            d = lk.REC[(lk.REC.policy == pol) & (lk.REC.schedule == "every") & lk.REC.iid.isin(lk.SUB["ESMdone"])]
            if not len(d):
                continue
            win = d[(d.t >= t) & (d.t < t + 10) & d.iid.isin(aff)]
            at = d[d.t == t]
            acted = at[at.iid.isin(aff)].flagged.mean() if len(aff) and len(at[at.iid.isin(aff)]) else np.nan
            spur = int((at[~at.iid.isin(aff)].flagged & at[~at.iid.isin(aff)].stored_valid).sum())
            r = {"lake": kind, "t": t, "event": desc, "affected": len(aff), "policy": pol,
                 "sw": float((~win.served_valid).mean()) if len(win) else np.nan, "acted": float(acted) if acted == acted else np.nan,
                 "spurious": spur, "judge": int(at.eval_calls.sum()), "der": int(at.n_der.sum())}
            OUT["T9"].append(r)
            L.append(f"| {lk.name} | {t} | {desc} | {len(aff)} | {pol} | {pct(r['sw'])} | {pct(r['acted'])} | {spur} | {r['judge']} | {r['der']} |")

# ------------------------------------------------------------------ T10 synthetic events (separate)
L.append("\n## T10. SYNTHETIC events (as-built lake, flagged; NOT in any headline number): affected facts kept at s0 on the as-built lake\n")
L.append("Run on the as-built lake: the ESM detector (DETECT-anchor-hier: stored answer = s0 K, 27B judge on anchored evidence; FF/FS per "
         "snapshot) and zero-LLM baselines (NEVER, @oracle). The frozen ESM with real re-derivation was NOT run here (budget).\n")
L.append(HDR.replace("| policy |", "| lake / policy |"))
OUT["T10"] = {}
for kind in ("dlsyn_tlc", "dlsyn_bb"):
    if kind not in LK:
        continue
    lk = LK[kind]
    ids = lk.SUB.get("SYNK") or lk.SUB.get("SYN")
    if not ids or not len(lk.REC):
        continue
    for pol in ["DETECT-anchor-hier", "NEVER"] + [t + "@oracle" for t in TTLS["dl_" + kind.split("_")[1]]] + ["REPLAY@oracle", "FILEHASH@oracle", "MANIFEST@oracle"]:
        s_ = lk.summ(pol, "every", ids, require_full=False)
        if s_ is None:
            continue
        OUT["T10"][f"{kind}|{pol}"] = s_
        L.append(line(f"{kind} / {pol}", s_))
    ev = json.loads((lk.ctx.sub / "synth_events.json").read_text())
    L.append(f"\nPer synthetic event ({kind}, {len(ids)} facts): facts whose truth changes at the event; share the ESM detector flags at the "
             "event snapshot; share of the touched-but-unchanged facts it flags there (spurious); NEVER served-wrong in the 10 snapshots from the event.\n")
    L.append("| t | kind | facts with truth change | detector flags them at t % | detector spurious flags at t (unchanged facts) | NEVER served-wrong % (10 reads, changed facts) |\n|---|---|---|---|---|---|")
    dd = lk.REC[(lk.REC.schedule == "every") & lk.REC.iid.isin(ids)]
    de, dn = dd[dd.policy == "DETECT-anchor-hier"], dd[dd.policy == "NEVER"]
    for e in ev:
        t = e["t"]
        chg = [i for i in ids if lk.FX[i]["truth"][t] != lk.FX[i]["truth"][t - 1]]
        at = de[de.t == t]
        fl = at[at.iid.isin(chg)].flagged.mean() if len(chg) and len(at) else np.nan
        sp = int((at[~at.iid.isin(chg)].flagged & at[~at.iid.isin(chg)].stored_valid & (at[~at.iid.isin(chg)].action != "same")).sum()) if len(at) else 0
        w2 = dn[(dn.t >= t) & (dn.t < t + 10) & dn.iid.isin(chg)]
        OUT["T10"][f"{kind}|event|{t}"] = {"kind": e["kind"], "n_chg": len(chg), "flag": fl, "spurious": sp}
        L.append(f"| {t} | {e['kind']} | {len(chg)} | {pct(fl) if fl == fl else '–'} | {sp} | {pct((~w2.served_valid).mean()) if len(w2) else '–'} |")


# ------------------------------------------------------------------ T7 taxonomy + examples
def taxonomy(lk, pol=FROZEN, sch="every"):
    d = lk.REC[(lk.REC.policy == pol) & (lk.REC.schedule == sch)].sort_values(["iid", "t"])
    cats, fcats, ex = Counter(), defaultdict(set), defaultdict(list)
    for iid, x in d.groupby("iid"):
        origin, origin_ok = "s0", True
        for r in x.itertuples():
            if r.action in ("repair", "rederive"):
                origin, origin_ok = r.action, bool(r.served_valid)
            if r.served_valid:
                continue
            tr = lk.FX[iid]["truth"][int(r.t)]
            sv = "" if r.served is None or str(r.served) in ("nan", "None") else str(r.served)
            if not origin_ok and r.action not in ("repair", "rederive"):
                c = f"persisting wrong {origin}" + (" (agent gave no answer)" if not sv else " (wrong value)")
            elif r.action == "rederive":
                c = "wrong re-derivation" + (" (no answer)" if not sv else "")
            elif r.action == "same":
                c = "missed: evidence state unchanged (change outside the recorded evidence)"
            elif r.action == "memo":
                c = "missed: memoised still_valid reused on a state whose truth differs"
            elif r.action in ("valid", "unsure_fresh"):
                c = f"missed: judge said {r.verdict} on a changed state"
            else:
                c = r.action
            c += " | truth NONE" if tr == "NONE" else ""
            cats[c] += 1
            fcats[c].add(iid)
            if len(ex[c]) < 8 and (not ex[c] or ex[c][-1][0] != iid):
                ex[c].append((iid, int(r.t), lk.FX[iid]["K"][:60], sv[:60], tr[:60], str(getattr(r, "reason", ""))[:200]))
    return cats, fcats, ex


EXLINES = []
for kind in REAL:
    lk = LK[kind]
    if (FROZEN, "every") not in lk.PF or not len(lk.REC):
        continue
    cats, fcats, ex = taxonomy(lk)
    tot = sum(cats.values())
    nrec = len(lk.REC[(lk.REC.policy == FROZEN) & (lk.REC.schedule == "every")])
    OUT[f"taxonomy|{kind}"] = {k: {"reads": v, "facts": len(fcats[k])} for k, v in cats.items()}
    L.append(f"\n## T7 [{lk.name}]. Error taxonomy of {FROZEN}'s wrong-served reads (every snapshot, ALL): {tot} of {nrec} reads\n")
    L.append("| cause | reads | % of wrong reads | facts | examples (fact, t, K, served, truth) |\n|---|---|---|---|---|")
    for k, v in cats.most_common():
        exs = "; ".join(f"`{a}` t={b}: K={c!r} served={d!r} truth={e!r}" for a, b, c, d, e, _ in ex[k][:2])
        L.append(f"| {k} | {v} | {100 * v / max(tot, 1):.1f} | {len(fcats[k])} | {exs} |")
    for k, v in ex.items():
        for a, b, c, d, e, rs in v:
            EXLINES.append(f"[{kind}] {k}\n  fact {a} t={b}\n  Q: {lk.FX[a]['question']}\n  K={c!r} served={d!r} truth={e!r}\n  judge: {rs}\n")
(RESULTS / "examples.txt").write_text("\n".join(EXLINES), encoding="utf-8")


# ------------------------------------------------------------------ curves
def curve(lk, ids_name, sch="every"):
    ids_all = lk.SUB.get(ids_name)
    if not ids_all:
        return
    pts = []
    for (pol, s_), pf in lk.PF.items():
        if s_ != sch or pol.startswith("DETECT"):
            continue
        s = lk.summ(pol, sch, ids_all)
        if s is not None:
            pts.append((pol, s))
    if len(pts) < 2:
        return
    OUT[f"curve|{lk.kind}|{ids_name}|{sch}"] = {p: {k: s[k] for k in ("ff", "fs", "sw", "tok_per_fact", "rde_sum", "tok_per_read")} for p, s in pts}
    fig, ax = plt.subplots(1, 2, figsize=(13, 5.2))
    for pol, s in pts:
        c = "C3" if pol.startswith("ESM") and "@oracle" not in pol else ("C7" if "@oracle" in pol else "C0")
        ax[0].scatter(100 * s["ff"], 100 * s["fs"], color=c, s=25)
        ax[0].annotate(pol, (100 * s["ff"], 100 * s["fs"]), fontsize=7)
        ax[1].scatter(max(s["rde_sum"], 1e-2), 100 * s["sw"], color=c, s=25)
        ax[1].annotate(pol, (max(s["rde_sum"], 1e-2), 100 * s["sw"]), fontsize=7)
    real = sorted([(max(s["rde_sum"], 1e-2), 100 * s["sw"], p) for p, s in pts if "@oracle" not in p])
    fr, best = [], 1e9
    for x, y, p in real:
        if y < best:
            fr.append((x, y)); best = y
    if fr:
        ax[1].step([a for a, _ in fr], [b for _, b in fr], where="post", color="k", lw=0.8, alpha=0.6)
    ax[0].set_xlabel("FF % (stored answer wrong, served)"); ax[0].set_ylabel("FS % (stored answer right, maintained)")
    ax[1].set_xscale("log"); ax[1].set_xlabel("cost: re-derivation-equivalents per fact (log)"); ax[1].set_ylabel("served-wrong % of reads")
    ax[0].set_title(f"FF–FS ({lk.name}, {ids_name}, {sch})")
    ax[1].set_title(f"served-wrong vs cost ({lk.name}, {ids_name}, {sch}); red ESM, blue real, grey @oracle", fontsize=9)
    fig.tight_layout()
    fig.savefig(RESULTS / f"curves_{lk.kind}_{ids_name}_{sch}.png", dpi=130)
    plt.close(fig)


for kind in REAL:
    lk = LK[kind]
    curve(lk, "ALL", "every")
    curve(lk, "S", "every")
    curve(lk, "S", GRID[kind])

if any(len(DER.get(k, [])) for k in REAL):
    fig, ax = plt.subplots(figsize=(6.5, 4))
    for i, kind in enumerate(REAL):
        dd = DER.get(kind)
        if dd is None or not len(dd):
            continue
        dd = dd[dd.t > 0].copy()
        n = LK[kind].ctx.env.n_steps()
        dd["bin"] = np.ceil(dd.t / (n / 6)).astype(int)
        g = dd.groupby("bin").correct.agg(["mean", "size"])
        ax.plot((g.index * n / 6) / n, 100 * g["mean"], "o-", color=f"C{i}", label=f"{LK[kind].name} (n={len(dd)})")
    ax.set_xlabel("position in FUTURE (fraction of the lake's snapshots)"); ax.set_ylabel("correct %"); ax.set_ylim(0, 100)
    ax.legend(fontsize=8); ax.set_title("27B re-derivation accuracy over time (data lake)")
    fig.tight_layout(); fig.savefig(RESULTS / "rederivation_accuracy.png", dpi=130); plt.close(fig)

(RESULTS / "tables.md").write_text("\n".join(L), encoding="utf-8")
(RESULTS / "results.json").write_text(json.dumps(OUT, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)), encoding="utf-8")
print("written", RESULTS / "tables.md")
