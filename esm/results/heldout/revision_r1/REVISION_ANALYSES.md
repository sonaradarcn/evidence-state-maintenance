# Reviewer round 1: analysis-only revisions

Date: 2026-10-05. Scope: the analysis-only items of `reviews/paper_r1.md`. No LLM call and no GPU were used. Everything was
computed from `esm/results/heldout/records.parquet`, the kept-fact metadata (oracle truth and validity), the cached
observation tables, the derivation store `esm_data_heldout/derivations*.jsonl` and `llm_ledger.jsonl`. The definitions
are those of the paper (`esm/metrics.py`, `esm/scripts/report_heldout.py`), which the scripts call directly. Every
point estimate below that also appears in the paper was reproduced exactly; item 7b lists the Table 4/5 recheck.

How to reproduce: run `python <script>` inside this folder.

* `r1_common.py` holds the shared helpers. It caches fact metadata in `cache/`.
* `states_s0.py` computes the evidence states from the cached observation tables. It uses no LLM.
* `item1_clustered.py` … `item7_minor.py` each write `itemN.md` (full tables), `itemN.json` and the `fig_item*.png`
  figures.

The tables below are condensed. The full tables are in `itemN.md`.

Statistics conventions:

* **Fact CI.** The paper's bootstrap over facts, recomputed with B = 2000. Because it is a fresh Monte-Carlo draw, it can
  differ from the paper's interval by ±0.1 pp.
* **Cluster CI.** Repositories are resampled with replacement (B = 2000), and all facts of a drawn repository are kept.
* **Repo mean.** Each repository's own pooled rate, with every repository weighted equally. Its CI comes from a bootstrap
  over repositories.
* **LORO.** Leave-one-repository-out: the minimum and maximum of the estimate when one repository is dropped.
* **Caveat.** With only 16 clusters (9 for behaviour facts), a percentile cluster bootstrap tends to under-cover. The
  per-repository sign test is therefore given as the most conservative view.

---

## Item 1: clustered statistics (major issue 1)

### Headline rates (ALL, every commit; served-wrong %)

| number | estimate | fact CI | cluster CI | repo mean [CI] | LORO range |
|---|---|---|---|---|---|
| ESM, ALL | 5.8 | [4.8, 6.9] | **[2.5, 10.5]** | 5.7 [2.5, 10.4] | 3.7 (no jinja) – 6.3 |
| NEVER, ALL | 21.5 | [19.9, 23.2] | [16.0, 28.2] | 21.2 [16.2, 27.8] | 18.8 – 22.6 |
| ESM, natural | 5.6 | [4.3, 7.0] | [1.5, 11.4] | 5.4 [1.6, 11.3] | 3.1 – 6.0 |
| ESM, behaviour (9 repos) | 8.7 | [5.9, 11.8] | [3.8, 13.6] | 8.8 [3.9, 13.9] | 7.2 – 9.9 |
| ESM, without jinja | 3.7 | [2.9, 4.5] | [2.1, 5.7] | 3.7 [2.1, 5.6] | 3.0 – 4.0 |
| Detection FF, ALL | 1.9 | [0.9, 2.9] | [0.3, 3.6] | 1.9 [0.4, 3.6] | 1.3 – 2.2 |
| Detection FS, ALL | 4.1 | [3.3, 5.0] | [2.4, 6.6] | 5.1 [2.5, 9.0] | 3.2 – 4.5 |
| Detection FF, behaviour | 10.8 | [2.8, 20.3] | [0.4, 25.8] | 8.7 [1.3, 18.4] | 2.4 – 12.8 |
| ESM, H150 | 6.9 | [4.3, 10.0] | [3.4, 11.2] | 6.9 [3.2, 11.1] | 5.4 – 7.4 |

### Paired differences (ESM − B, pp)

"Repos better / tie / worse" counts the repositories where ESM's own pooled rate is lower than, equal to or higher
than the baseline's.

| comparison | Δ | fact CI | cluster CI | repos better / tie / worse | sign p | LORO range | significant? fact / cluster |
|---|---|---|---|---|---|---|---|
| vs NEVER, ALL | −15.7 | [−17.2, −14.1] | [−18.5, −12.5] | 16 / 0 / 0 | 3e-5 | −16.5 – −15.0 | yes / yes |
| vs NEVER, natural | −10.2 | [−12.1, −8.4] | [−13.9, −6.7] | 16 / 0 / 0 | 3e-5 | −10.9 – −9.1 | yes / yes |
| vs NEVER, behaviour | −3.0 | [−5.3, −1.1] | [−7.1, −0.05] | 4 / 5 / 0 | 0.13 | −3.5 – −1.3 | yes / borderline |
| vs TTL100@oracle, ALL | −0.6 | [−1.5, +0.4] | [−3.0, +2.2] | 9 / 0 / 7 | 0.80 | −1.7 – −0.2 | no / no |
| vs TTL50@oracle, ALL | +2.5 | [+1.6, +3.5] | **[−0.4, +6.3]** | 6 / 0 / 10 | 0.45 | +0.9 – +2.9 | yes / **no** |
| vs REPLAY@oracle, ALL | +5.7 | [+4.7, +6.7] | [+2.3, +10.3] | 0 / 2 / 14 | 1e-4 | +3.7 – +6.1 | yes / yes |
| vs REPLAY, H150 | −1.6 | [−3.5, −0.005] | [−3.1, −0.2] | 8 / 5 / 3 | 0.23 (Wilcoxon 0.07) | −1.9 – −1.1 | yes (barely) / yes |
| vs CERT-ZS, H150 | −0.2 | [−1.3, +0.9] | [−1.4, +1.0] | 5 / 9 / 2 | 0.45 | −0.6 – +0.1 | no / no |
| vs CERT-v0h, 133 static | −0.3 | [−2.3, +1.4] | [−2.3, +1.4] | 4 / 10 / 2 | 0.69 | −0.8 – +0.4 | no / no |
| vs LLMDIFF, H150 | −1.2 | [−2.6, +0.2] | **[−2.3, −0.01]** | 9 / 6 / 1 | 0.02 | −1.5 – −0.8 | **no / yes (borderline)** |
| vs TTL50, H150 | −5.1 | [−6.9, −3.3] | [−7.0, −3.1] | 15 / 0 / 1 | 5e-4 | −5.7 – −4.5 | yes / yes |
| vs TTL100, H150 | −7.7 | [−10.0, −5.4] | [−10.1, −5.1] | 15 / 0 / 1 | 5e-4 | −8.4 – −7.1 | yes / yes |
| vs NEVER, H150 | −21.9 | [−26.9, −17.0] | [−25.5, −18.2] | 16 / 0 / 0 | 3e-5 | −22.8 – −21.1 | yes / yes |
| vs LLMDIFF, every50 grid | −2.0 | [−3.6, −0.5] | [−3.4, −0.7] | 10 / 5 / 1 | 0.01 | −2.3 – −1.6 | yes / yes |

Other results:

* **Token differences.** Every Table 4 token difference keeps a cluster CI that excludes zero, except two:
  * CERT-v0h: −2.2k [−7.3, +2.6];
  * TTL200: +4.1k [−0.5, +9.6].

  The two headline token differences are CERT-ZS −26.6k [−46.9, −10.2] and LLMDIFF −45.8k [−60.9, −32.0].
* **H150 without jinja.** All signs are kept. The REPLAY difference loses fact-level significance (−1.7 [−3.8, +0.1]) but
  keeps cluster-level significance ([−3.3, −0.3]).
* **Ablations (Table 5).** No verdict changes under clustering (`item1.md` §1f).
* **Per repository.** Per-repository served-wrong rates for ESM, NEVER and the strong baselines are in `item1.md` §1g. This
  answers the minor issue that only an aggregate repo-weighted number is reported.
* **Figures.** `fig_item1_paired.png` and `fig_item1_perrepo.png`.

**Reading.**

* **The intervals widen.** Clustering by repository widens the headline intervals two- to four-fold. ESM on ALL becomes
  5.8 % [2.5, 10.5] instead of [4.8, 6.9], because jinja and werkzeug carry most of the error. The paper should report
  repo-cluster CIs, or both kinds.
* **No conclusion changes sign.** ESM beats blind reuse in every one of the 16 repositories, on ALL and on the natural
  subset. It beats TTL50/100/200 in 15 of 16. It ties CERT-ZS and CERT-v0h under every unit.
* **Three statements need rewording:**
  * "ESM trails TTL50@oracle (+2.5 pp)" is not significant under clustering. Only REPLAY@oracle is robustly better.
  * "At least as accurate as REPLAY" survives both bootstraps, but with 8 / 5 / 3 repositories it is not a repo-level
    result (sign p = 0.23). The paper should keep "at least as accurate" and not claim "more accurate".
  * Against LLMDIFF the cluster CI just excludes zero ([−2.3, −0.01]). Do not claim superiority from this. Section 7.2
    should say the difference is borderline, and the paper should keep the non-inferiority wording of item 2.
* **Behaviour vs NEVER.** The −3.0 pp is at the edge under clustering (upper bound −0.05 pp). In 5 of the 9 behaviour
  repositories the two policies tie exactly.

---

## Item 2: non-inferiority and equivalence (major issue 2)

Δ = ESM − B (served-wrong, pp, H150, every commit); a positive Δ means ESM is worse.

* **Non-inferiority (NI) at margin m.** The one-sided 95 % upper bound (the 95th percentile of the bootstrap) is below m.
* **Equivalence (EQ, TOST at α = 0.05).** The 90 % CI lies inside ±m.

| comparison | facts | ESM % / B % on the same facts | ESM / B tokens per fact | unit | 90 % CI | one-sided 95 % upper bound | NI at 1.0 / 1.5 / 2.0 pp | EQ at 1.0 / 1.5 / 2.0 / 3.0 pp |
|---|---|---|---|---|---|---|---|---|
| ESM − CERT-ZS | 160 | 6.9 / 7.1 | 26.5k / 53.1k | facts | [−1.15, +0.67] | +0.67 | yes / yes / yes | no / yes / yes / yes |
| | | | | repo clusters | [−1.23, +0.80] | +0.80 | yes / yes / yes | no / yes / yes / yes |
| ESM − CERT-v0h | **133 (same facts)** | **6.1 / 6.4** | **24.4k / 26.6k** | facts | [−1.96, +1.11] | +1.11 | no / yes / yes | no / no / yes / yes |
| | | | | repo clusters | [−1.96, +1.08] | +1.08 | no / yes / yes | no / no / yes / yes |
| ESM − LLMDIFF | 160 | 6.9 / 8.1 | 26.5k / 72.3k | facts | [−2.38, +0.01] | +0.01 | yes / yes / yes | no / no / no / yes |
| | | | | repo clusters | [−2.14, −0.19] | −0.19 | yes / yes / yes | no / no / no / yes |

On the shared every50 grid, ESM is non-inferior to all three at 1.0 pp. The fact-level upper bounds are +0.39, +0.75 and −0.70 pp; the cluster upper bounds are +0.39, +0.64 and −0.86 pp. The
repo-mean (equal-weight) unit gives the same verdicts; see `item2.md`. Figure: `fig_item2_tost.png`.

**Reading.**

* **Non-inferiority holds at 1.5 pp.** With both resampling units, ESM is non-inferior to CERT-ZS, CERT-v0h and LLMDIFF
  at a margin of 1.5 pp of served-wrong reads. This is about one fifth of ESM's own 6.9 % on H150. The smallest margins
  that pass are 0.8, 1.1 and 0.0 pp (cluster).
* **Equivalence holds only against CERT-ZS.** TOST equivalence at ±1.5 pp holds only against CERT-ZS. Against CERT-v0h it
  needs ±2 pp. Against LLMDIFF it fails up to ±2 pp, because ESM may be up to 2.4 pp *better*, not because it may be worse.
* **CERT-v0h on its own 133 facts.** On exactly the 133 static facts it covers, ESM is wrong on 6.1 % at 24.4k tokens per
  fact, against 6.4 % at 26.6k for CERT-v0h. Table 4 should show ESM on these 133 facts next to CERT-v0h's 6.4 %, not
  ESM's 6.9 % over 160 facts.
* **The margin is post hoc.** It was not pre-registered, so the paper must say this.
* **Proposed wording:**
  * Replace "statistically tied" / "ties" / "matches" with: "No difference in served-wrong rate was detected between ESM
    and CERT-ZS, CERT-v0h or LLMDIFF. With a non-inferiority margin of 1.5 percentage points, chosen after the fact,
    ESM is non-inferior to all three (one-sided 95 % upper bounds of ESM − baseline: +0.8, +1.1 and −0.2 pp,
    repository-cluster bootstrap)."
  * For CERT-ZS alone one may add "and equivalent within ±1.5 pp (TOST)".
  * Do not write "the same accuracy".

---

## Item 3: cost on the natural distribution (major issue 3)

### Composition (stratum = fact type × changes in FUTURE)

| | T1 | T2 | T3 | T4 | T5 | T6 | T7 | B | total |
|---|---|---|---|---|---|---|---|---|---|
| natural: changing / not | 31/99 | 34/141 | 55/121 | 18/10 | 14/24 | 1/6 | 18/63 | 27/53 | **198 / 517 (28 % changing)** |
| H150: changing / not | 7/9 | 21/13 | 14/12 | 12/1 | 10/8 | 6/6 | 7/7 | 17/10 | **94 / 66 (59 % changing)** |

Every natural stratum has at least one H150 fact, so no natural mass is lost. The effective sample size after weighting
is 95 of 160 facts. The post-stratification weights are in `item3.md` §3a.

### Re-weighted to the natural mix (every commit; ratio = baseline tokens / ESM tokens)

| baseline | ESM % (rw) | B % (rw) | Δ pp, cluster CI | ESM tokens (rw) | B tokens (rw) | ratio (rw) [cluster CI] | ratio unweighted | ratio range over churn bins | ratio on the 71 natural H150 facts |
|---|---|---|---|---|---|---|---|---|---|
| CERT-ZS | 3.3 | 3.2 | +0.1 [−0.4, +0.8] | 14.8k | 42.1k | **2.85 [1.65, 4.09]** | 2.00 | 1.20 – 3.13 | 2.04 |
| CERT-v0h (133) | 3.0 | 3.0 | +0.1 [−1.2, +1.1] | 13.5k | 19.6k | 1.45 [0.95, 2.14] | 1.09 | 0.96 – 1.33 | 1.27 |
| LLMDIFF | 3.3 | 3.2 | +0.1 [−0.4, +0.8] | 14.8k | 53.5k | **3.63 [2.51, 5.18]** | 2.72 | 2.21 – 4.30 | 2.55 |
| REPLAY | 3.3 | 3.7 | −0.4 [−1.0, +0.2] | 14.8k | 92.8k | 6.28 [5.19, 7.49] | 6.12 | 4.77 – 9.69 | 5.89 |
| TTL50 | 3.3 | 5.3 | −2.0 [−2.8, −1.1] | 14.8k | 60.0k | 4.06 [3.08, 5.67] | 3.25 | 2.50 – 7.00 | 2.85 |
| TTL100 | 3.3 | 6.5 | −3.2 [−4.4, −2.0] | 14.8k | 30.4k | 2.06 [1.57, 2.87] | 1.66 | 1.28 – 3.49 | 1.45 |

Churn bins are 0, 1–100, 101–200 and 201–400 FUTURE commits at which the stored answer is invalid. A mixture of the bins
has a ratio between the smallest and largest bin ratio. The every50-grid rows are in `item3.md` §3c.

### Validation, and ESM on the whole natural subset

* **Validation.** Policies run on all facts let the re-weighting be checked. It reproduces the @oracle TTL served-wrong
  rates (TTL100@oracle 3.9 vs 4.3 %; TTL50@oracle 2.2 vs 2.3 %). It does **not** reproduce ESM's own natural-subset
  numbers:
  * served-wrong: re-weighted 3.3 %, actual 5.6 %;
  * cost: re-weighted 14.8k tokens per fact, actual 23.0k;
  * NEVER: re-weighted 13.2 %, actual 15.8 %.
* **Why it fails.** Type × changing does not capture how much a fact changes, nor jinja: all 47 natural jinja facts
  change. A churn-bin × jinja stratification validates better for served-wrong (ESM 5.3 vs 5.6 %). It still
  underestimates ESM's cost (19.3k vs 23.0k). Under it the ratios are CERT-ZS 2.01, LLMDIFF 2.96, REPLAY 6.98 and TTL100
  2.02 (`item3.md` §3h).
* **ESM alone on the full natural subset** (715 facts, every commit): 5.6 % [cluster 1.5, 11.4] at **23.0k tokens per
  fact** [13.3, 34.5].
  * Changing facts (198) cost 63.7k each; non-changing facts (517) cost 7.5k.
  * Judge calls per fact: 7.2.
  * Re-derivations per fact: 0.88.

**Reading.**

* **Cost depends on churn, as the reviewer suspected, but the ratio moves in ESM's favour.** On non-changing facts the
  baselines cost 3–10 times as much as ESM. On changing facts they cost 1.3–5.5 times as much. Moving from H150's 59 %
  changing facts to the natural 28 % therefore raises the CERT-ZS and LLMDIFF ratios from 2.0 / 2.7 to about
  2.0–2.9 / 3.0–3.6, depending on the stratification.
* **The ratio is not uniform.** On the heaviest-churn facts (201–400 invalid commits) ESM is only 1.2 times cheaper than
  CERT-ZS. Against CERT-v0h there is no meaningful cost advantage (0.96–1.33 times).
* **Accuracy.** On the natural mix, the differences to CERT-ZS, LLMDIFF and REPLAY shrink to ≤ 0.4 pp (none
  significant), because non-changing facts are served correctly by every policy.
* **Absolute numbers.** The re-weighting fails validation for ESM's absolute cost. Absolute natural-subset numbers
  should therefore come from the ALL run (23.0k, 5.6 %), and the re-weighted ratios should be presented as estimates.

**Narrower claim the data support:**

> On the 160-fact subset, which is enriched for change (59 % changing), ESM used 2.0 times fewer LLM tokens than CERT-ZS
> and 2.7 times fewer than LLMDIFF, with no detected accuracy difference. Re-weighting the subset to the natural subset's
> mix of fact types and change (28 % changing) gives estimated ratios of 2.0–2.9 and 3.0–3.6. ESM was cheaper than both
> in every churn stratum (1.2–3.1 times and 2.2–4.3 times). ESM had no material cost advantage over the history-tested
> certificate CERT-v0h, which covers static facts only.

The "2–3× lower cost" headline should be restated as "2–3× fewer LLM tokens than CERT-ZS and LLMDIFF on a change-enriched
subset (estimated 2–3.6× at the natural mix)", and should not be applied to CERT-v0h.

---

## Item 4: memoisation ablation (major issue 5)

### Why the counterfactual is exact

A memo hit is the only path memoisation changes:

* The memo stores only `still_valid` verdicts (`maintain.simulate_esm`).
* The judge prompt is a function of the anchor evidence and of the current outputs, and those outputs are what the
  evidence state hashes.
* Every 27B call is at T = 0 and goes through the LLM cache.

Without memoisation, the same prompt would therefore be sent again and would return the same verdict. Served answers,
re-derivations and accuracy are identical; only the judge cost changes. This is exact for every arm except n = 2
(T = 0.7), whose no-memo row is indicative only.

### ESM, every commit: with and without memoisation

| set | changed-state reads/fact | distinct (anchor, state) judgements/fact | judge calls/fact, memo → none | tokens/fact with memo | without memo | × | served-wrong (both) |
|---|---|---|---|---|---|---|---|
| ALL | 207.3 | 7.58 | 7.8 → 209.5 | 26.5k | 246.8k | 9.3 | 5.8 % |
| natural | 214.1 | 6.98 | 7.2 → 216.7 | 23.0k | 252.5k | 11.0 | 5.6 % |
| static | 196.2 | 7.07 | 7.2 → 197.4 | 24.6k | 229.7k | 9.3 | 5.5 % |
| behaviour | 298.7 | 11.75 | 12.9 → 309.1 | 42.3k | 387.6k | 9.2 | 8.7 % |
| H150 | 202.6 | 7.69 | 7.8 → 203.7 | 26.5k | 226.7k | 8.5 | 6.9 % |

### H150 by read schedule

| schedule | reads/fact | tokens with memo | without memo | × |
|---|---|---|---|---|
| every | 400 | 26.5k | 226.7k | 8.5 |
| every5 | 80 | 24.0k | 59.4k | 2.5 |
| bursty | 80 | 14.6k | 44.5k | 3.0 |
| every20 | 20 | 19.1k | 25.1k | 1.3 |
| every50 | 8 | 16.6k | 17.9k | 1.1 |

### Row for Table 5 (H150, every commit)

| Variant | Wrong % | Δ wrong [CI] | Tok./fact | Re-der. |
|---|---|---|---|---|
| no memoisation (counterfactual; identical verdicts) | 6.9 | +0.0 (identical) | 226.7k (Δ −200k, cluster CI [−242k, −165k]) | 1.31 |

### Isolating semantic transition judging

REPLAY uses the same un-anchored ("original") evidence as ESM-noanchor. It re-derives on any change instead of asking
the judge. ESM-noanchor − REPLAY on H150 is −1.8 pp [cluster −3.2, −0.5] at −122k tokens per fact [−186k, −69k]: the
judge plus memoisation, without anchoring, is both more accurate and 4 times cheaper than re-deriving on every evidence
change.

**Reading.**

* **Memoisation is the cost mechanism.** At every commit, each fact sees about 200 changed-state reads but only 7.6
  distinct evidence states. Memoisation turns about 200 judge calls into about 8 and cuts the cost 9.3-fold on ALL
  (8.5-fold on H150), at identical accuracy.
* **It matters only for dense reads.** The saving falls to 1.1–1.3 times when reads are 20–50 commits apart, because
  there are then few repeated states.
* **What Table 5 should contain.** Add the no-memo row, and also the ESM-noanchor vs REPLAY comparison, so that both
  memoisation and semantic judging are isolated, as the reviewer asked.

---

## Item 5: observation completeness (major issue 6)

### Setup

The analysis uses the detection-only records of the frozen ESM detector (DETECT-anchor-hier, ALL, every commit): the
stored answer is always the s0 answer K and the reference is always the s0 evidence. There are 122,042 stored-wrong reads.
Each is classified as follows:

* **caught:** the detector flagged the read;
* **blind:** the evidence state equals the s0 state;
* **judge still_valid:** the evidence changed, and a fresh or memoised verdict said the answer was still valid.

These classes are crossed with whether the oracle value is NONE.

A detector-independent test is added. The evidence states were recomputed from the cached observation tables and agree
with the recorded actions on 100 % of reads. A stored-wrong read whose evidence state is *identical* to a state at which K
was right is an observation-completeness violation: identical recorded evidence, different truth.

### Read level (stored-wrong reads)

| slice | stored-wrong reads | FF (missed) | missed, blind (= s0 evidence) | missed, judge still_valid | missed with oracle NONE | missed reads with evidence identical to a K-right state (strict OC violation) | missed reads with distinct evidence (judge error or indirect cause) |
|---|---|---|---|---|---|---|---|
| ALL | 122,042 | 1.9 % (2,258) | 0.4 % (8 reads, 4 facts) | 99.6 % | 57.7 % | **6.3 %** | **93.7 %** |
| static | 114,806 | 1.3 % (1,476) | 0.5 % | 99.5 % | 44.4 % | **0.8 %** | **99.2 %** |
| behaviour | 7,236 | 10.8 % (782) | 0 % | 100 % | 82.9 % | **16.6 %** | **83.4 %** |

By type, the misses of T2, T3, T5, T6 and T7 are 99–100 % judge misses on distinct evidence. T1 has only 9 missed reads,
6 of them at the boltons transient commit (`item5.md` §5b, §5d).

### Episode level (601 stored-wrong episodes)

| slice | episodes | never caught | never caught, evidence never changed (blind) | never caught, onset evidence identical to a K-right state |
|---|---|---|---|---|
| static | 499 | 11 (2.2 %) | 4 (0.8 %) | 7 (all boltons, at t = 79 (the transient unparseable commit) and t = 328) |
| behaviour | 102 | 45 (44.1 %) | 0 | 37: 34 from one fact (`networkx:B:maximal_independent_set`, executed value flips), 2 isort, 1 boltons |

Figure: `fig_item5_blind.png`.

**Reading.**

* **Static facts: the assumption holds almost perfectly.** Only 0.01 % of stored-wrong reads have evidence identical to a state where K was right: 7 boltons facts, at t = 79–80
  (the transient unparseable commit) and at t = 328, whose cause was not traced. 99 % of the residual FF is the judge
  misreading a visible change.
* **Behaviour facts: the share is larger, but concentrated.** 16.6 % of missed reads, and 37 of the 45 never-caught
  episodes, are strict violations. Most of the episode count comes from one fact whose executed value flips with no
  recorded-evidence change (34 episodes). Excluding it, 3 of 11 never-caught behaviour episodes are strict violations.
* **The other 83 % of missed behaviour reads have distinct evidence.** They are either judge errors or indirect causes
  that a judge cannot infer from the visible delta; the poetry-core case is one of them. This test cannot separate the
  two. Those reads are therefore an *upper bound* on weak-form incompleteness, and the 16.6 % is a lower bound.
* **NONE share.** The oracle is NONE in 57.7 % of all missed reads (static 44 %, behaviour 83 %).
* **Proposed wording.** Replace "we measured rather than assumed observation completeness" with: "For static facts, a
  change in truth under identical recorded evidence occurred on 0.01 % of stale reads. For behaviour facts it explains at
  least 17 % of the detector's missed reads (four facts); the remaining misses are judge errors or indirect causes we
  cannot separate." The claim should be scoped to facts whose dependencies are read by the derivation trace.

---

## Item 6: anchored wrong re-derivations (major issue 4, analysis only)

### The paper's 92.7 % is confirmed

30,727 of 33,139 wrong-served reads (ALL, every commit) persist after a wrong re-derivation; 93.8 % if the 372 wrong
re-derivation reads themselves are included. The rest are:

* memoised still_valid on a changed truth: 1,981 reads;
* judge said valid on a changed state: 51;
* evidence unchanged: 8.

### Episode-level decomposition (239 maximal runs of wrong-served reads)

This also answers the minor issue about Fig. 6.

| cause at the first wrong read | episodes | wrong reads | median length (commits) | still wrong at t = 400 |
|---|---|---|---|---|
| wrong re-derivation | 178 (74.5 %) | 30,599 (92.3 %) | 175 | 69 % |
| memoised still_valid | 41 (17.2 %) | 318 (1.0 %) | 3 | 2 % |
| judge said valid | 16 (6.7 %) | 2,214 (6.7 %) | 161 | 62 % |
| evidence unchanged | 4 (1.7 %) | 8 | 2 | 0 % |

**Wrong re-derivation episodes** (178 episodes in 171 facts):

* Length in commits: p10 2, p25 38, median 175, p75 298, p90 298, mean 172.
* How they end: 23 % are ended by a correct re-derivation, 8 % because the truth returns to the served answer, and 69 %
  are still wrong at t = 400.
* 90 % start at an oracle-NONE read. jinja accounts for 69 episodes and 13,246 reads.
* The 83 episodes longer than 200 commits hold 24,093 of these reads (79 %).

### Probability that a forced re-derivation is correct (27B agent; `item6.md` §6c)

* **A (by commit):** 96.7 % at t ≤ 50, then 66–94 %, then about 80 % after t = 300.
* **B (also split by whether the oracle is NONE):** referent present 91–98 %; oracle NONE 21–88 %.
* **C (same-fact persistence):** after a wrong derivation of the same fact, with the truth unchanged since, the next
  derivation is right only **10.7 %** of the time (7,390 pairs; 20 % when every fact is weighted equally; 9.5 % for
  consecutive derivations). With the truth changed since, it is right 44 %. After a right derivation it is right 95 %
  (truth unchanged) or 76 % (truth changed).

### Estimated effect of an anchor expiry of N commits

This is a first-order model, not a run. The recorded segment boundaries are kept. A forced answer that is correct is
right where the truth equals its value. A forced answer that is wrong is wrong until the next expiry. Where a recorded 27B
derivation exists at exactly that fact and commit, its real outcome is used: 69–80 % of forced re-derivations on H150
(all anchors), 0–8 % on ALL.

| set | expiry applies to | N | served-wrong %, recorded → estimated (A / B / C) | share of anchored-wrong reads removed (A / B / C) | extra re-derivations per fact | extra tokens per fact |
|---|---|---|---|---|---|---|
| ALL | all anchors | 50 | 5.8 → 13.6 / 8.9 / 8.7 | 63 / 48 / 12 % | 7.4 | +103k |
| ALL | all anchors | 100 | 5.8 → 10.8 / 8.2 / 8.1 | 44 / 33 / 9 % | 3.4 | +48k |
| ALL | all anchors | 200 | 5.8 → 9.9 / 7.9 / 7.2 | 18 / 13 / 4 % | 1.5 | +21k |
| ALL | re-derived anchors only | 50 | 5.8 → 5.2 / 6.1 / 6.2 | 60 / 45 / 9 % | 1.7 | +25k |
| ALL | re-derived anchors only | 100 | 5.8 → 5.4 / 6.1 / 6.1 | 41 / 31 / 6 % | 0.7 | +10k |
| ALL | re-derived anchors only | 200 | 5.8 → 5.6 / 5.8 / 5.9 | 16 / 12 / 2 % | 0.2 | +3k |
| H150 | all anchors | 50 | 6.9 → 8.0 / 8.1 / 8.7 | 59 / 48 / 12 % | 7.1 | +100k |
| H150 | all anchors | 100 | 6.9 → 7.9 / 7.8 / 8.1 | 36 / 29 / 9 % | 3.2 | +45k |
| H150 | all anchors | 200 | 6.9 → 7.2 / 7.2 / 7.3 | 12 / 10 / 6 % | 1.3 | +18k |
| H150 | re-derived anchors only | 50 | 6.9 → 7.1 / 7.2 / 7.8 | 54 / 43 / 7 % | 2.3 | +34k |
| H150 | re-derived anchors only | 100 | 6.9 → 7.4 / 7.3 / 7.6 | 31 / 24 / 4 % | 0.9 | +14k |
| H150 | re-derived anchors only | 200 | 6.9 → 7.2 / 7.2 / 7.2 | 7 / 5 / 1 % | 0.3 | +4k |

An "optimistic" variant assumes a correct forced answer stays right for the rest of its interval. It changes the
estimates by at most 0.1 pp (`item6.md` §6d). Figures: `fig_item6_episodes.png` and `fig_item6_expiry.png`; the latter
puts the H150 estimates on the cost–wrong plane.

**Reading.**

* **Wrong re-derivation episodes are long.** The anchoring failure mode is confirmed exactly as stated (92.7 %).
* **Expiring every anchor is estimated to be worse.** It makes ESM less accurate under all three estimates: +0.3 to +1.8
  pp on H150, where most forced outcomes are real recorded derivations. It also costs 18k–100k extra tokens per fact,
  because forced re-derivations of correct answers introduce errors that then persist. This is the same mechanism that
  makes TTL lose.
* **Expiring only re-derived anchors is a closer call.**
  * It helps only under the optimistic estimate A, which ignores that errors repeat: −0.3 to −0.6 pp on ALL.
  * Under C, the realistic same-fact estimate, it removes only 2–9 % of the anchored-wrong reads and adds 0.1–0.3 pp,
    because the agent repeats its own mistake about 90 % of the time. Most of these errors are NONE cases, such as moved
    paths, where it confidently finds the moved code again.
* **What this suggests.** The data suggest that an anchor expiry will not cut the dominant error unless the forced
  re-derivation differs from the original one, for example with a NONE-aware prompt or a different model.
* **Status.** These are clearly labelled estimates. The planned real run of the hybrid is what decides the question, and
  the paper should cite that run rather than these numbers.

---

## Item 7: minor issues that are factual

### 7a. "H150" is 160 facts: every occurrence

* **`sections/06_setup.tex`, 3 occurrences:**
  * line 23 (Table 2 row "of which H150");
  * line 44 (twice: the definition "H150 is a stratified subset of 160 facts …", and "Because H150 over-represents …").
* **`sections/07_results.tex`, 14 occurrences:**
  * line 32 (Table 4 caption);
  * line 55;
  * line 68 (Fig. 3 caption);
  * line 76 (Fig. 4 caption, twice, incl. "the 160 H150 facts");
  * line 81;
  * line 86 (Fig. 5 caption);
  * line 90;
  * line 93 (Table 5 caption);
  * line 115;
  * line 160 (Table 7 caption);
  * line 187 (Fig. 7 caption);
  * line 191;
  * line 207.
* **`sections/08_discussion.tex`, 3 occurrences:** lines 4, 7 and 16.
* **Figure labels in `figs/make_figs.py`:** line 230 (y-label "per-commit rate (%), H150"), line 265 (panel title) and
  line 272 (x-label "H150 grid"). The other make_figs hits are data keys (`DETECT-…|H150`, `T5_poisson_H150`) and need
  not change.
* **Not found:** no "150 facts" or "H80R" appears in the tex. `main.tex` says "160-fact subset".
* **Data keys stay.** The data keys in `results.json` (`H150`, `sub_H150.json`) can stay; a footnote can explain the
  name.

### 7b. Table 4 and Table 5 recheck

Every served-wrong, tokens/fact and re-derivations/fact value in Table 4 and Table 5 was recomputed from the records and
matches the paper.

### 7c. Other wording the review flags

| wording | where it appears |
|---|---|
| "statistically tied" | `07_results.tex:59`, `08_discussion.tex:4`, `main.tex:51` (abstract) |
| "ties" | `main.tex:58` (highlight) and `07_results.tex:27` (vs TTL100@oracle) |
| "same accuracy" | `07_results.tex:90` (unsure-as-fresh) |
| "measured rather than assumed" | `08_discussion.tex:19`; replacement in item 5 |
| "two to three times lower token cost" | `08_discussion.tex:4`, `09_conclusion.tex:3`, `main.tex:51` (abstract, "2.0–2.7 times lower token cost") |
| "2.0–2.7 times lower cost" | `main.tex:58` (highlight); add "LLM-token" |
| Section 4 title | `04_negative.tex:1` "Why cheap certified guards are hard" |

### 7d. Non-token cost

This addresses the minor issue "LLM-token cost; add tool-call / wall-clock". Values are per fact on H150 at every commit.

| policy | guard tool executions | re-derivations | re-derivation tool calls | LLM calls (re-derivation + judge) | estimated serial LLM minutes |
|---|---|---|---|---|---|
| ESM | 1,512 | 1.31 | 6.4 | 15.6 | 5.7 |
| REPLAY | 1,513 | 10.07 | 55.7 | 67.0 | 24.8 |
| CERT-ZS | 595 | 4.60 | 19.0 | 23.8 | 8.8 |
| CERT-v0h | 471 | 2.31 | 8.3 | 10.7 | 4.0 |
| LLMDIFF | 863 | 2.07 | 8.4 | 33.9 | 12.3 |
| TTL50 | 0 | 8.00 | 31.1 | 39.5 | 14.6 |

How these were computed:

* **Guard tool executions** are evidence queries or files replayed on every read. They are deterministic tool calls, not
  LLM calls; ESM's and REPLAY's are the same.
* **Serial LLM minutes** are calls multiplied by the median per-call latency in the ledger: 21.5 s for a judge call and
  22.2 s for a derivation turn, measured with 2–4 requests in flight per GPU. This is an indicative estimate, not a
  wall-clock measurement. The every50 rows (FILEHASH, ASTHASH, CITE) are in `item7.md` §7c.

### 7e. Factual checks of review statements

All of the following match the paper:

* jinja: 93 kept facts, 90 of them changing.
* H150: 160 facts, 94 changing, 89 enriched and 71 natural.
* H150: 10 facts per repository; 27 behaviour facts, so CERT-v0h covers 133.
* ALL: 1,419 kept facts, 555 changing.
* Behaviour episodes never acted on: 44 % (T3 44.0 % in the main run; 45 of 102 = 44.1 % in detection-only).
* Fig. 6 / §7.7 counts: 33,139 wrong reads, 30,727 persisting, 1,981 memoised, 51 judge, 8 evidence-unchanged.
