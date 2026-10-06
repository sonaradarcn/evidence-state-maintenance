# ESM held-out evaluation: 16 new repositories, 1,478 facts

Date: 2026-10-04.

* **Sources of the numbers.** Every number comes from `python -m esm.scripts.report_heldout`, which writes `tables.md`,
  `results.json`, `records.parquet` and `curves_*.png`, or from the logs and ledger in `esm_data_heldout`.
* **Plan and decisions.** `PLAN.md` holds the plan, written before any held-out maintenance run, plus a timestamped log of
  every decision taken during the run.
* **Data and cache.** All new data is on E:. The dev data on D: was only read. Every LLM call is cached in
  `esm_data_heldout/llm_cache`, and the ledger is `esm_data_heldout/llm_ledger.jsonl`.

## 0. Verdict

* **Main arm, all 1,419 facts.** Frozen configuration: anchored evidence, hierarchical deltas, and "changed"/"unsure"
  verdicts trigger a re-derivation by the 27B agent. The arm read every commit, all 400 FUTURE commits, with real
  re-derivations.
  * ESM serves a wrong answer on **5.8 % [4.9, 6.8]** of reads; blind reuse (NEVER) serves 21.5 % [19.9, 23.1].
  * Natural subset: 5.6 % vs 15.8 %. Behaviour slice: 8.7 % vs 11.7 %.
  * Cost: **26.5k tokens per fact over 400 commits**. That is 66 tokens per read, 3.2 re-derivation-equivalents (RDE),
    7.8 judge calls and 1.1 agent re-derivations per fact.
* **Against real-cost baselines on H150** (160 stratified facts, every commit, the same 27B re-derivation agent):
  * ESM 6.9 % at 26.5k tokens per fact.
  * TTL50 12.0 % at 86k, TTL100 14.6 % at 44k.
  * REPLAY + re-derive 8.5 % at 162k.
  * CERT-ZS 7.1 % at 53k.
  * LLM-on-diff (LLMDIFF) 8.1 % at 72k.
  * Paired, ESM − baseline:

    | baseline | served-wrong (pp) | tokens per fact |
    |---|---|---|
    | REPLAY | −1.6 [−3.5, −0.0] | −136k |
    | TTL50 | −5.1 [−6.9, −3.4] | −60k |
    | TTL100 | −7.7 [−10.0, −5.5] | −18k |
    | CERT-ZS | −0.2 [−1.4, +0.9], a tie | −27k [−40, −15] |

  * CERT-v0h (static facts only) is also a tie, at about equal cost.
* **Detection itself (pilot7 definitions, all 1,419 facts): FF 1.9 % [0.9, 3.0] / FS 4.1 % [3.3, 5.0].** On H150, pilot7's
  TRIAGE-a detector scores FF 1.3 / FS 14.5 and the ESM detector 2.3 / 6.3.
  * Behaviour facts remain hard: FF 10.8 / FS 13.0 on ALL.
* **What is left is mostly not a detection problem.** 89.8 % of ESM's wrong-served reads are reads where the oracle value is
  **NONE**: the referent was removed, its pinned file path moved, or its file does not parse at that commit. At those
  reads the 27B agent re-derives a *value*, and ESM then protects it.
  * On reads whose referent is present, ESM is wrong on **0.7 %** of reads (NEVER 10.2 %).
  * 13.2k of the 29.7k NONE-reads come from one event: jinja's move to `src/`, where the benchmark's pinned paths stop
    existing.
  * With the re-derivation replaced by the oracle, an idealised reference, ESM drops to 0.7 % on H150 at 20k tokens per
    fact. REPLAY@oracle reaches 0.1 % at 118k.
  * The answer source, not the detector, now bounds accuracy.
* **Dev calibration and frozen choice.** The repair choice was frozen on dev before held-out: `ESM-norepair`, chosen by
  a pre-registered rule.
  * On held-out, verified repair (`ESM-verify`) is just as accurate: 6.8 % vs 6.9 % on H150, paired +0.1 [−0.8, +1.2].
    It is 21 % cheaper: −5.6k tokens per fact.
  * Plain repair is clearly worse: +4.1 pp [1.5, 6.8].
  * The blind verifier raised the correctness of accepted repairs from 72–73 % (plain) to 91 %.

## 1. What was run

| item | value |
|---|---|
| facts | 1,478 held-out facts (16 repos; static T1–T7 + behaviour; enriched + natural subsets), 400 FUTURE commits each, oracle tables from `heldout/` |
| s0 derivation | qwen3.6:27b agent (pilot3/pilot6 tool loop, ≤ 12 tool calls, thinking off, T = 0) plus one sentence: answer `NONE` if the referent does not exist (PLAN.md; added after the first 190 derivations showed prose answers; all s0 derivations were redone with it). Kept iff canonicalised answer = oracle at s0: **1,419 / 1,478 (96.0 %)**. Stored K = the agent's own answer string; evidence = its trace; citations = zero-LLM `auto_cites` (no LLM citation step, unlike the dev set). The 9B agent (secondary arm) scored 1,324 / 1,478 (89.6 %) at s0. |
| ESM (frozen) | `ESM-norepair`: anchored recording, hierarchical deltas (pilot7 capped delta when complete; ≤ 12 KB single call; else 12 KB groups + screening + final call ≤ 20 KB, else re-derive), 27B judge with pilot7's prompt, verdict changed / unsure / too-large / parse-fail ⇒ re-derivation by the 27B agent at t (new evidence from the new trace); memoised per (anchor, state). |
| subsets | **ALL** = 1,419 kept facts. **H150** = 160 facts, 10 per repo (behaviour repos: 3 behaviour + 7 static), 89 enriched / 71 natural, changing facts over-represented (94 changing); drawn by seed from the first 1,096 kept facts (a random ~74 % of the kept set, PLAN.md). **H80R** = seeded random half of H150 (used first for REPLAY; REPLAY was later completed on all of H150). |
| schedules | every (400 reads), every5 (80), every20 (20), every50 (8), bursty (80 reads in 10-read bursts, seed 7). |
| servers | own Ollama: 11595 (GPU0) and 11596 (GPU1), qwen3.6:27b, 2–4 requests in flight each; a second machine's Ollama (qwen3.5:9b) via ssh tunnel 11597. 11434 never touched. All stopped at the end. |
| LLM volume | see §11 (realised budget). |

Arms with **real** 27B re-derivations:

| arm | facts | schedules |
|---|---|---|
| ESM (frozen) | ALL | every |
| ESM (frozen) | H150 | every5, every20, every50, bursty |
| ablations: no anchoring, truncation, unsure-as-fresh, plain repair, verified repair, n = 2 self-consistency | H150 | every |
| 9B evaluator, 9B deriver (remote 9B) | H150 | every |
| TTL50/100/200, CERT-ZS, CERT-v0h (static only) | H150 | every |
| REPLAY | H150 | every |
| LLMDIFF (read-set diff judge) | H150 | every |
| ALWAYS, TTL*, REPLAY, FILEHASH, ASTHASH, CITE, CERT-ZS, CERT-v0h, LLMDIFF, ESM (shared 50-commit grid) | H150 | every50 |

Detection only (pilot7 framework):

* ESM detector (`DETECT-anchor-hier`), ALL.
* pilot7 TRIAGE-a (`DETECT-p7a`), 9B detector, truncation / no-anchor detector ablations, H150.

**@oracle** (re-derivation replaced by the oracle answer; an idealised reference, always labelled):

* NEVER, ALWAYS, TTL*, REPLAY, FILEHASH, ASTHASH and CITE on ALL, all schedules;
* ESM@oracle on H150.

## 2. Dev calibration of the repair policy (before any held-out maintenance run)

Setup:

* dev S1 (86 facts), every commit;
* 27B judge and 27B re-deriver;
* rule fixed in PLAN.md beforehand: lowest served-wrong wins; if within 0.5 pp, the cheaper policy wins.

| policy | served-wrong % [CI] | tokens/fact | re-derivations/fact | accepted repairs (correct) |
|---|---|---|---|---|
| **ESM-norepair** (chosen) | **8.2 [4.1, 12.8]** | 42.5k | 1.33 | – |
| ESM-verify (blind verifier) | 8.9 [4.9, 13.6] | 39.6k | 0.88 | 39 (84.6 %) |
| ESM (plain repair) | 12.4 [7.6, 17.5] | 32.5k | 0.55 | 65 (49.2 %) |
| *reference, dev stage:* ESM, 9B deriver | 15.8 | 43.5k | 0.66 | 62 (56.5 %) |
| *reference, dev stage:* ESM-norepair, 9B deriver | 14.6 | 60.0k | 1.57 | – |

Paired results on S1:

| comparison | served-wrong (pp) | tokens per fact |
|---|---|---|
| verify − norepair | +0.7 [0.0, +1.7] | −2.9k |
| verify − plain | −3.5 [−6.8, −0.7] | |
| plain − norepair | +4.2 [+1.4, +7.5] | |

* **The rule chose `ESM-norepair`.** `ESM-verify` was 0.74 pp worse, just outside the 0.5 pp margin.
* **The 27B deriver alone** cut dev served-wrong roughly in half: 15.8 → 12.4 % for plain repair, 14.6 → 8.2 % for no repair.
* **The verifier.** One 27B call answers the question blind, from the re-anchored evidence at t, with the same NONE
  instruction. On dev it rejected 31 of 70 proposals; only 3 of the rejected proposals were correct.
* **Answer check after re-derivation (option c) was not adopted.**
  * On dev 9B re-derivations, a static answer with no supporting trace line was wrong 79 % of the time (vs 38 %).
  * The remedy would cost another derivation.
  * On held-out, 27B re-derivations failed mainly by answering a value where the oracle says NONE (§7). A
    supporting-line check cannot catch that, because the moved or broken file still contains the line.

## 3. s0 derivation (step 1)

| split | facts | correct % | wrong % | no answer % | tokens/derivation | tool calls |
|---|---|---|---|---|---|---|
| all | 1,478 | **96.0** | 2.2 | 1.8 | 9.4k | 3.3 |
| static | 1,304 | 97.0 | 1.5 | 1.5 | 8.1k | 2.9 |
| behaviour | 174 | 88.5 | 6.9 | 4.6 | 19.2k | 5.8 |
| enriched | 751 | 93.7 | 3.3 | 2.9 | 10.9k | 3.7 |
| natural | 727 | 98.3 | 1.0 | 0.7 | 7.9k | 2.8 |

* By type, T1, T2, T3, T4, T5 and T7 are ≥ 96 %.
* **T6 is the weak type:** 76.5 % correct. "Which files import module m" hits the 12-call limit, giving 19 % no-answer.
* By repo, success ranges from 91.2 % (jinja) to 99.0 % (poetry-core) (`tables.md` T0).
* **Kept facts:** 1,419, of which 555 change in FUTURE with respect to the stored answer; 21.5 % of (fact, commit) pairs are
  invalid.
* **Evidence:** 3.06 queries per fact; 5.45 distinct non-s0 anchored evidence states per fact (dev: ~13).

## 4. Main table: maintenance at every commit (all reads, pooled; CIs: bootstrap over facts)

| set | facts | ESM served-wrong % [CI] | NEVER | TTL100@oracle | TTL50@oracle | REPLAY@oracle | ESM tokens/fact | ESM RDE |
|---|---|---|---|---|---|---|---|---|
| **ALL (pooled)** | 1,419 | **5.8 [4.9, 6.8]** | 21.5 | 6.4 | 3.3 | 0.1 | 26.5k | 3.16 |
| **natural subset** | 715 | **5.6 [4.2, 7.0]** | 15.8 | 4.3 | 2.3 | 0.1 | 23.0k | 3.11 |
| enriched subset | 704 | 6.1 [4.8, 7.6] | 27.3 | 8.6 | 4.4 | 0.2 | 30.1k | 3.20 |
| **behaviour slice** | 154 | **8.7 [5.8, 12.0]** | 11.7 | 4.8 | 2.3 | 0.9 | 42.3k | 2.59 |
| static slice | 1,265 | 5.5 [4.5, 6.6] | 22.7 | 6.6 | 3.5 | 0.0 | 24.6k | 3.32 |
| without jinja | 1,326 | 3.7 [3.0, 4.5] | 18.8 | 5.4 | 2.9 | 0.0 | 22.6k | 2.68 |
| repo-weighted (1/16 each) | 1,419 | 5.7 [4.9, 6.6] | 21.2 | 6.4 | 3.3 | 0.1 | – | – |
| repo-weighted, natural | 715 | 5.4 [4.4, 6.5] | 15.5 | 4.2 | 2.3 | 0.1 | – | – |

Other ESM metrics (ALL):

* FS 0.1 %.
* Stored-wrong episodes never acted on: 7.5 % (natural 4.4 %, behaviour 44 %).
* Lifetime kept: 94.7 % of the reads before the s0 answer first became invalid were served without any action.
* Changing facts that were ever served wrong: 34.6 %.
* Per-read FF is 96.9 %. As on dev it is dominated by persistence (a wrong new answer is served again on every later read),
  so it is not comparable to pilot7's FF; §6 gives the detection-only numbers.

Paired against NEVER:

| set | served-wrong (pp) |
|---|---|
| ALL | −15.7 [−17.3, −14.1] |
| natural | −10.2 [−12.1, −8.3] |
| behaviour | −3.0 [−5.4, −1.0] |

Paired against the idealised oracle-re-derivation baselines (ALL):

| baseline | served-wrong (pp) | tokens per fact |
|---|---|---|
| TTL100@oracle | −0.6 [−1.5, +0.4] | −7k |
| TTL50@oracle | +2.5 [+1.6, +3.5] | −41k |
| REPLAY@oracle | +5.7 [+4.8, +6.7] | −77k |

ESM is not ahead of baselines that are handed a *perfect* re-derivation, except TTL200@oracle (−5.6 pp).

**Sensitivity: reads whose oracle value is NONE removed** (12.6 % of reads; `tables.md` T1-nn):

| set | ESM | NEVER | TTL100@oracle |
|---|---|---|---|
| ALL | 0.7 % | 10.2 % | 3.6 % |
| H150 | 1.3 % | 18.4 % | – |

**Per repo** (`tables.md` T3):

* **jinja dominates:** ESM 35.6 % vs NEVER 60.3 %, with 90 of its 93 facts changing. It accounts for 13.2k of the 33.1k
  wrong-served reads.
* **werkzeug:** 13.7 % vs 36.4 %.
* **The other 14 repos:** between 0.0 and 7.1 %.

**Per type:**

* T1 0.8 %, T4 1.5 %, T5 1.6 %, T6 3.8 %;
* T2 7.6 %, T3 9.5 %, T7 8.6 %;
* behaviour 8.7 %.

## 5. Real-cost comparison on H150 (same 160 facts, same 27B re-derivation agent)

**Every commit** (`tables.md` T1c; paired = ESM − B, bootstrap over the same facts):

| policy | served-wrong % [CI] | tokens/fact | re-derivations/fact | Δ served-wrong vs ESM, pp [CI] | Δ tokens/fact |
|---|---|---|---|---|---|
| **ESM (frozen)** | **6.9 [4.1, 9.8]** | **26.5k** | 1.31 | – | – |
| REPLAY + re-derive | 8.5 [5.5, 11.6] | 162.4k | 10.1 | −1.6 [−3.5, −0.0] | −136k [−190, −94] |
| CERT-ZS + re-derive (incl. extraction) | 7.1 [4.4, 10.2] | 53.1k | 4.6 | −0.2 [−1.4, +0.9] | −27k [−40, −15] |
| CERT-v0h + re-derive (133 static) | 6.4 [3.3, 10.0] | 26.6k | 2.3 | −0.3 [−2.4, +1.4] | −2k [−11, +5] |
| LLMDIFF + re-derive | 8.1 [5.4, 11.1] | 72.3k | 2.1 | −1.2 [−2.6, +0.2] | −46k [−57, −35] |
| TTL50 | 12.0 [9.1, 15.0] | 86.3k | 8 | −5.1 [−6.9, −3.4] | −60k |
| TTL100 | 14.6 [11.4, 17.6] | 44.0k | 4 | −7.7 [−10.0, −5.5] | −18k |
| TTL200 | 20.9 [17.0, 25.1] | 22.5k | 2 | −14.0 [−17.6, −10.5] | +4k |
| NEVER | 28.8 [23.6, 34.2] | 0 | 0 | −21.9 [−27.0, −17.1] | +27k |
| *REPLAY@oracle (idealised)* | 0.1 | 118k | 8.0 | +6.8 [+4.1, +9.7] | −91k |
| *TTL50@oracle (idealised)* | 4.9 | 75k | 8 | +2.0 [−0.9, +5.0] | −49k |

**Shared 50-commit grid** (schedule every50: every policy reads and re-derives only at t = 50, …, 400, so re-derivations
are literally shared; `tables.md` T1d, paired = ESM − B):

| policy | served-wrong % | tokens/fact | Δ vs ESM, pp [CI] |
|---|---|---|---|
| **ESM** | **7.4** | **16.6k** | – |
| ALWAYS (= TTL50 here) | 8.9 | 86.3k | −1.5 [−3.5, +0.5] |
| REPLAY | 8.9 | 55.6k | −1.5 [−3.6, +0.7] |
| FILEHASH / ASTHASH | 9.3 / 9.3 | 65.9k / 64.8k | −1.9 [−3.9, +0.2] |
| CERT-ZS | 8.2 | 29.3k | −0.8 [−2.3, +0.5] |
| CERT-v0h (133 static) | 7.1 | 19.1k | −0.7 [−2.7, +0.9] |
| LLMDIFF | 9.4 | 25.4k | −2.0 [−3.7, −0.5] |
| CITE | 13.0 | 18.9k | −5.5 [−8.7, −2.9] |
| TTL100 | 12.0 | 44.0k | −4.5 [−6.7, −2.4] |
| TTL200 | 19.0 | 22.5k | −11.6 [−14.7, −8.5] |

**Reading.**

* With real re-derivations, every guard that re-derives often (ALWAYS, REPLAY, FILEHASH) inherits the agent's errors. The
  27B agent is 98 % right at t = 50 but 86–89 % at t ≥ 200 (§8).
* ESM re-derives less (0.93 vs 3.9–8 re-derivations per fact here) and keeps the verified s0 answer when nothing relevant
  changed. It is therefore at least as accurate as ALWAYS / REPLAY / FILEHASH at 1/3–1/5 of their cost.
* The two certificate baselines (CERT-ZS, CERT-v0h) are **statistically tied** with ESM in accuracy. CERT-ZS costs 1.8× more
  at every commit. CERT-v0h costs about the same, but covers static facts only and needs a ~7-call construction step per
  fact.

## 6. Ablations (H150, every commit; paired ESM − variant)

| variant | served-wrong % | Δ vs ESM, pp [CI] | tokens/fact | Δ tokens/fact [CI] | note |
|---|---|---|---|---|---|
| ESM (frozen: no repair) | 6.9 | – | 26.5k | – | |
| verified repair (`ESM-verify`) | 6.8 | +0.1 [−0.8, +1.2] | 20.9k | +5.6k [+3.2, +8.6] | the verifier rejected 32 of 124 proposals, 7 of them correct; accepted repairs 91.3 % correct |
| plain repair (`ESM`) | 11.0 | −4.1 [−6.8, −1.5] | 16.2k | +10.4k | accepted repairs 72.3 % correct |
| no anchoring | 6.7 | +0.2 [−0.3, +0.9] | 40.5k | **−14.0k [−19.4, −8.8]** | 2.5 vs 1.3 re-derivations per fact; FS 0.4 vs 0.1 |
| truncated deltas | 6.9 | +0.0 [+0.0, +0.0] | 25.4k | +1.2k | hierarchy only matters when a delta exceeds 12 KB; rare with 27B traces (3 queries per fact) |
| unsure ⇒ fresh | 6.6 | +0.3 [+0.0, +0.9] | 22.6k | +3.9k | 1.05 vs 1.31 re-derivations per fact; episodes never acted on 7.6 vs 3.4 % |
| 9B evaluator (27B deriver) | 8.4 | −1.5 [−2.9, −0.3] | 57.6k | −31k | the 9B judge flags more: 2.7 re-derivations per fact, lifetime kept 85 % |
| 9B deriver (27B judge) | 11.1 | −4.2 [−7.0, −1.8] | 41.1k | −15k | 9B re-derivations 64 % correct when the truth changed (27B: 73 %) |
| n = 2 self-consistency (T = 0.7, unanimous) | 6.7 | +0.2 [−0.2, +1.0] | 42.8k | −16.2k [−21.2, −12.1] | 1.74 re-derivations per fact; no accuracy gain for 1.6× the cost |
| *ESM@oracle (re-derivation replaced by the oracle; idealised)* | *0.7 [0.0, 1.7]* | *+6.2* | *20.2k* | | *with a perfect answer source, ESM's residual is 0.7 % (REPLAY@oracle 0.1 % at 118k)* |

**On held-out, anchoring buys cost, not accuracy.** It saves 35 % of the tokens and half of the re-derivations; on dev it
also bought 3 pp of accuracy. Hierarchical deltas are irrelevant here because the 27B agent's evidence is small.

## 7. Detection only, pilot7 framework

The stored answer is always the s0 K. FF and FS are per commit, with pilot7's definitions.

| detector | facts | FF % [CI] | FS % [CI] | static FF / FS | behaviour FF / FS | natural FF / FS | judge calls/fact |
|---|---|---|---|---|---|---|---|
| **ESM detector (anchored + hierarchical, 27B)** | ALL 1,419 | **1.9 [0.9, 3.0]** | **4.1 [3.3, 5.0]** | 1.3 / 2.9 | 10.8 / 13.0 | 2.1 / 3.6 | 5.7 |
| ESM detector | H150 | 2.3 [0.0, 6.0] | 6.3 [3.2, 10.0] | 2.5 / 4.4 | 0.8 / 14.4 | 2.5 / 4.3 | 6.7 |
| pilot7 TRIAGE-a (original recording, truncated) | H150 | 1.3 [0.1, 3.7] | 14.5 [10.1, 18.9] | 1.2 / 11.2 | 1.7 / 27.9 | 0.3 / 14.0 | 7.8 |
| ESM detector, 9B judge | H150 | 4.8 [1.2, 9.8] | 15.1 [10.5, 20.1] | 5.3 / 8.9 | 0.8 / 40.7 | 5.2 / 9.8 | 6.8 |

Dev reference: ESM detector 2.6 / 3.8, pilot7 3.5 / 17.1.

* **The held-out detection numbers reproduce the dev picture.** FS falls from 14.5 to 6.3 % on the same 160 facts, while FF
  stays at 1–2 %.
* **Behaviour facts are the weak spot on ALL:** FF 10.8 %, against 2.5 % on dev.
* **Detection ablations on H150:**
  * anchored + truncated deltas: FF 1.2 / FS 5.6;
  * hierarchical deltas without anchoring: FF 1.2 / FS 14.9.

  **Anchoring is what removes the false stales** (14.9 → 5.6–6.3 %); hierarchy vs truncation makes no difference. That
  is the same conclusion as on dev.

## 8. Read schedules and costs

* **Cost per read.** ESM costs 66 tokens per read at every commit (ALL). On H150 the cost per read rises as reads get
  sparser, because the work per read grows while the total spend falls:

  | schedule | served-wrong | tokens per read | tokens per fact |
  |---|---|---|---|
  | every | 6.9 % | 66 | 26.5k |
  | every5 | 7.0 % | 300 | 24.0k |
  | bursty | 4.8 % | 183 | 14.6k |
  | every20 | 7.2 % | 956 | 19.1k |
  | every50 | 7.4 % | 2,077 | 16.6k |

  NEVER on H150 is wrong on 28.8 % of reads at every commit and 32.0 % at every50; ESM − NEVER at every20 is −22.7 pp. The
  @oracle baselines on all schedules for ALL are in `tables.md` T4.
* **RDE unit.** The kept facts' own 27B s0 derivations, mean 8.4k tokens.
* **What one re-derivation costs.** A 27B re-derivation costs 13.5k tokens on average at t > 0, against 8.4k at s0, and the
  9B costs 17.5k. Re-derivations at changed states are harder.
* **Where ESM's 26.5k tokens per fact go:**
  * the judge: 7.8 calls per fact, 10.1k tokens;
  * re-derivations: 1.11 agent runs per fact, 16.5k tokens.
* **Needless spend.** 55 % of ESM's tokens are spent at reads whose stored answer was still right.
* **Re-derivation accuracy of the 27B agent** (`tables.md` T6, `rederivation_accuracy.png`):
  * by commit on the H150 grid: 98 % at t = 50, 99 % at t = 100, 89 % at t = 200, 87 % at t = 300, 86 % at t = 400;
  * 83.6 % over all t > 0;
  * 73.2 % when the truth differs from s0, 97.0 % when it does not;
  * behaviour 72.7 %.
* **The 9B agent on the same grid:** 80.4 % overall, and 64.1 % when the truth changed.

## 9. Error taxonomy of ESM's wrong-served reads (ALL, every commit; 33,139 of 567,600 reads)

| cause | reads | % | facts |
|---|---|---|---|
| a wrong re-derivation that persists, **oracle NONE** (referent gone, path moved, or file broken; the agent gave a value) | 27,909 | 84.2 | 148 |
| a wrong re-derivation that persists, referent present | 2,818 | 8.5 | 17 |
| missed: a memoised still_valid reused on a state whose truth differs, oracle NONE | 1,459 | 4.4 | 13 |
| missed: a memoised still_valid reused on a state whose truth differs, referent present | 522 | 1.6 | 8 |
| the wrong re-derivation read itself (NONE / present) | 327 / 45 | 1.1 | 157 / 17 |
| missed: the judge said still_valid on a changed state | 51 | 0.2 | 19 |
| **change outside the recorded evidence** (evidence state unchanged, truth changed) | **8** | 0.02 | 4 |

* **Wrong re-derivations.** 372 of the 1,569 re-derivations made by the main arm were wrong (76 % right). Of the 372:
  * 309 had oracle NONE and a value from the agent;
  * 34 returned no answer at all: the 12-call limit, or a reply that is not an answer;
  * 29 gave a wrong value while the referent exists.
* **Observation incompleteness, in the strict sense, is negligible.** A change in truth with an unchanged evidence
  state occurred in only 4 boltons facts, all at the single transient commit where `boltons/strutils.py` fails to parse
  (t = 79–80). A weaker form is behaviour facts whose call breaks for a reason the evidence shows only indirectly
  (example 7). Those are counted under "missed: memoised / judge still_valid" (~2k reads).

Concrete examples (from `examples.txt`, produced by `esm.scripts.examples_heldout`, zero LLM):

1. **`jinja:T3:16`: path move counted as NONE.** "In file `jinja2/runtime.py`, what are the parameter names of
   `LoopContext.__init__`?"
   * K = `self, iterable, undefined, recurse, depth0`.
   * At t = 103 jinja moves to `src/jinja2/`, and the oracle becomes NONE because the pinned path no longer exists.
   * The judge says "changed: file no longer exists"; the 27B agent re-derives, finds `src/jinja2/runtime.py` and answers
     the same parameter list. This is semantically reasonable, but wrong by the benchmark's definition, and it persists for
     298 reads.
   * This mechanism covers most of jinja's 13k wrong reads.
2. **`mkdocs:T1:2`: no answer, then a confirmed nothing.** "Which file defines `modified_time`?"
   * At t = 311 the function is removed. The judge correctly says "changed: removed", but the re-derivation returned no
     answer.
   * From then on the stored answer is empty. At t = 330 the judge even calls it still valid ("the original answer 'None'
     remains correct"): 90 wrong reads.
   * A fallback to keep the old answer on an empty re-derivation would not help here; mapping "no answer after a changed
     verdict" to NONE would.
3. **`scrapy:T2:8`: None vs NONE.** The default of `namespace` in `_embed_ipython_shell` is `None`.
   * At t = 300 the function is removed, and the judge says "changed: removed".
   * The agent answers `None`, the Python default, instead of `NONE`, the referent being gone. For T2 the canonicaliser
     keeps these apart (`None` ≠ `NONE`), so 100 reads are wrong.
   * This is a format ambiguity of the benchmark's T2 type.
4. **`pygments:T6:30`: unsure, then an empty re-derivation.** "Which files import `pygments.lexers.python`?"
   * At t = 117 the judge is unsure ("new files added; unknown if they import …").
   * The re-derivation hits the 12-call limit and returns no answer; the empty answer is then judged still valid on later
     states.
5. **`httpx:T5:25`: memoised verdict reused.** "How many test functions in `tests/test_multipart.py`?"
   * The judge correctly repaired 19 → 21 at t = 52.
   * At t = 77 one test was removed and two were added (21 → 22). The judge said "one removed, one added; count unchanged":
     a real miscount on a `list_defs` diff.
   * The memo then carried that verdict for 57 reads, until another change at t = 135 triggered a correct re-derivation.
6. **`networkx:B:maximal_independent_set:c2936c8c`: flipping truth.** The executed value flips between `[1, 3]` and
   `[1, 4]` at many FUTURE commits (t = 3, 6, 7, 9, 11, …). The cause was not investigated.
   * Twice the re-derivation produced prose ("Actually, I just realized …") instead of an answer.
7. **`poetry-core:B:parse_single_constraint:ff1c9dc3`: missed NONE.** At t = 240 the executed call becomes NONE (the
   import fails or the attribute is missing).
   * The judge, looking at the changed parser source, kept saying still_valid. A memoised verdict then served the old value
     for 161 reads.
   * What breaks the call (an import elsewhere in the package) is not visible in the recorded evidence: an
     observation-completeness failure that is specific to behaviour facts.
8. **`boltons:T1:0`: change outside the recorded evidence.** At the transient broken commit (t = 79–80, IndentationError
   in `boltons/strutils.py`), the oracle says NONE for `windowed_iter`, which lives in `iterutils.py`. Why pilot3's T1
   oracle does this was not traced.
   * The recorded evidence was unchanged, so ESM served K: 2 wrong reads.

## 10. What was skipped or approximated

**Real-cost baselines:**

* **FILEHASH, ASTHASH and CITE** were run with real re-derivation only on the shared 50-commit grid (every50, H150). At
  every commit they appear only as @oracle; they would need about 20 re-derivations per fact.
* **REPLAY** at every commit was run on all of H150. It was first restricted to H80R, then extended to the full H150 after
  time allowed.
* **LLMDIFF** at every commit was stopped after 20/160 facts at 2.4 h (one 8 KB diff judgement per file change) and
  restarted. It was completed on all of H150 at every commit in the last hours: 8.1 % at 72k tokens per fact, paired
  ESM − LLMDIFF −1.2 [−2.6, +0.2]. LLMDIFF is also complete at every50.
* **ALWAYS** only at every50, where it equals TTL50's derivations. ALWAYS at every commit would be 400 derivations per
  fact; ALWAYS@oracle is reported for all schedules.

**Arms not run:**

* **ESM on sparse schedules** ran on H150 only, not ALL. Sparse reads move the re-derivation commits, so these runs would
  need new derivations (~8k calls).
* **9B arms** ran on H150 only, as planned.
* **No arm combining no anchoring with truncation** was run on held-out.

**Changes to the benchmark protocol:**

* **CERT-v0h** is pilot3's CERT v0 without the two synthetic perturbations in the sufficiency test. Only the real HISTORY
  counter-example is used, and it covers static facts only. Its construction tokens (about 7 calls per fact) are added to
  its cost; CERT-ZS's extraction call is added likewise.
* **CITE** uses zero-LLM auto-citations located in the trace's read-set files. 20 % of facts fall back to FILEHASH. On dev,
  CITE used LLM-extracted citations.
* **The NONE instruction** added to the agent prompt is a protocol change with respect to the dev stage. It was applied to
  everything in this stage, including the dev calibration.

**How the subsets were drawn:**

* **H150** was drawn from 1,096 of the 1,419 kept facts: a random ~74 %, because s0 ran round-robin in seeded random order.
* H150 over-represents changing facts by design, so its pooled rates are not base rates; it is used for paired comparisons
  only.

**Benchmark semantics:**

* The oracle's NONE covers removal, renaming, **moves of pinned paths** and transient non-parsing commits. Most of ESM's
  residual error lies there; T1-nn removes those reads as a sensitivity check.

**Infrastructure incidents (no results lost):**

* One ledger line was garbled by concurrent appends. Ledger writes are now single `os.write` calls, and derivations and
  certificates go to per-process shards.
* One oracle-baseline process crashed while saving the observation cache (Windows file lock), before its every50 schedule.
  That schedule was re-run.
* The first main-arm runs (batch 1 and batch 2) were stopped and restarted as one run. Every LLM call was served from the
  cache.

## 11. Realised LLM budget

| model | role | calls | prompt tokens | completion tokens |
|---|---|---|---|---|
| qwen3.6:27b | derivation agent (s0, re-derivations, grids) | 21,392 | 51.78M | 1.89M |
| qwen3.6:27b | ESM / DETECT judge (incl. screens; incl. dev calibration) | 20,583 | 26.42M | 0.91M |
| qwen3.6:27b | LLMDIFF judge | 3,992 | 8.51M | 0.17M |
| qwen3.6:27b | certificate construction (CERT-ZS, CERT-v0h) | 1,099 | 0.72M | 0.12M |
| qwen3.6:27b | repair verifier | 201 | 0.21M | 0.01M |
| qwen3.5:9b | derivation agent (s0 on all facts, H150 grid, 9B-deriver arm) | 13,400 | 35.86M | 1.34M |
| qwen3.5:9b | judge (9B detector, 9B-evaluator arm) | 1,818 | 2.09M | 0.07M |

Plan: ~45k 27B calls. Realised: **47,267 27B calls** (87.6M prompt + 3.1M completion tokens), including ~1.3k superseded
calls made before the NONE instruction, and **15,218 9B calls** (38.0M + 1.4M). Throughput was 24–29 27B calls/min on
two GPUs. LLM wall-clock ran from 16:02 on 10-03 to 20:48 on 10-04 (28.8 h); the work as a whole, analysis included, ran
from 15:50 on 10-03 to about 22:00 on 10-04. 5 ledger lines are garbled (concurrent appends before the fix). See PLAN.md
for the timeline. Ollama servers: own ports 11595 / 11596 (local) and 11597 (remote, tunnel), all stopped at the
end; 11434 never touched.

## 12. Files

* `PLAN.md`: the plan written before maintenance, the decision log, and the realised budget.
* `tables.md` / `results.json`: every table (T0–T8), paired differences and curve points.
* `records.parquet`: one row per (policy, schedule, fact, read): stored/served validity, action, verdict, tokens,
  re-derivations, verifier fields, judge reason.
* Curves:
  * `curves_ALL_every.png`, `curves_H150_every.png`, `curves_*_every20.png`: FF–FS and served-wrong vs RDE (log), with the
    Pareto step over real-cost policies;
  * `rederivation_accuracy.png`.
* `examples.txt`: the full traces of the taxonomy examples.
* Raw data in `esm_data_heldout\`:
  * `sim/*.parquet`;
  * `derivations*.jsonl` (27B), `derivations_9b*.jsonl`;
  * `certs*.jsonl`;
  * `obs/*.pkl`;
  * `llm_cache/`, `llm_ledger.jsonl`;
  * `dev27/` (dev calibration);
  * `frozen.json`, `sub_*.json`;
  * the queue files and logs.
* Reproduce (everything is cached):
  * the `heldout_s0`, `heldout_subsets`, `build_states`, `heldout_certs` and `run_sim` commands in `queue_*.txt`;
  * then `python -m esm.scripts.report_heldout`, with `ESM_DATA=esm_data_heldout` and `ESM_STAGE=heldout`.
