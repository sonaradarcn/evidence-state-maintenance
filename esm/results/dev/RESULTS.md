# ESM v1 on the dev set: results

Date: 2026-10-03. Every number below was produced by `python -m esm.scripts.report` (`tables.md`, `results.json`,
`curves_*.png` in this folder) from the per-(fact, read, policy) records in `records.parquet`, which has one row per
fact × read × policy × schedule. Code: package `esm/` (see `esm/README.md`). Pilot outputs and caches were only read, never written.
All analysis ran under Python 3.14. Every LLM call is cached in `esm_data\llm_cache`, and the ledger is `esm_data/llm_ledger.jsonl`.

**Time budget.** The planned budget was about 10 h. The work took about 19 h wall-clock, including roughly 9.5 h of idle
GPU time between jobs. Several planned arms were skipped (§7).

## 0. Verdict in one paragraph

* **Anchoring plus hierarchical deltas fix pilot7's false-stale problem.** In pilot7's own detection-only framework, on all
  285 facts, the ESM detector scores **FF 2.6 % [0.2, 5.8] / FS 3.8 % [2.3, 5.5]**. Pilot7's TRIAGE-a, recomputed with
  this package, scores FF 3.5 / FS 17.1. Behaviour-fact FS falls from 42.2 % to 6.6 %. FF does not rise; it falls slightly,
  but that drop is within the noise.
* **Re-derivation dominates the end-to-end picture.** In full maintenance (repair or re-derive, every commit, all 285
  facts), ESM serves a wrong answer on **18.0 %** of reads. Blind reuse serves a wrong answer on 28.4 %, and the pilot7-style
  maintainer (no anchoring, truncated deltas) on 21.2 %. ESM costs **3.5 re-derivation-equivalents (RDE) per fact over 400
  commits**. **Two thirds of ESM's wrong reads come from a wrong agent re-derivation that then persists.** The
  qwen3.5-9B agent is right only 61–76 % of the time at later commits.
* **ESM is on the real-cost Pareto frontier, not below the idealised baselines.** With real re-derivations (40-fact
  subset SR), ESM (14.5 % wrong, 2.4 RDE) beats REPLAY + re-derive (20.3 %, 27 RDE) and TTL 50/100/200 (22–23 %, 2.5–9.7 RDE).
  Baselines given an *oracle* re-derivation reach 0–7 % at 2–58 RDE, so ESM is not ahead of them.

## 1. What was run

| item | value |
|---|---|
| facts | 285 dev facts: 241 static (pilot3–5, truth from pilot4's oracle series) and 44 behaviour (pilot6, executed truth). 400 FUTURE commits each. |
| recording | `evidence.record`. **anchored**: `read` windows become `def_block` of the enclosing def/class/method when the visible window lies inside one that is ≤ 1.5×window + 20 lines. Otherwise they become a content-anchored span (distinctive first and last lines, EOF-anchored at end of file; if the anchor is lost, the fixed window is shown and labelled). `grep` is line-number-insensitive, and `ls`/`find` are compared as sorted sets. **original** = pilot7's recording. |
| evidence states | anchored: 3,776 distinct non-s0 states over 285 facts; original: 4,427 (pilot7: 4,549 incl. raw). Anchoring barely reduces the *number* of states. It changes what the delta shows. |
| delta / evaluator | pilot7's capped delta (2.5 KB/call, 8 KB total) when nothing is dropped. If the complete delta is ≤ 12 KB it is shown complete in one call. Otherwise it is evaluated **hierarchically**: groups of ≤ 12 KB (every hunk, hunks nearest the cited evidence first, oversized hunks split), one screening call per group ("could this part affect the answer?"), then one final call on all retained groups. If the retained groups exceed 20 KB the case is "too large" and the fact is re-derived. The judge is qwen3.6:27b (q4, T = 0, no thinking) with pilot7's JSON prompt. |
| actions | still_valid → reuse and memoise per (anchor, state). changed + new_answer → in-place repair (K := new_answer, queries re-anchored at t). unsure / changed without an answer / too large / parse failure → re-derivation by the agent (qwen3.5:9b, the pilot3/pilot6 agent loop, ≤ 12 tool calls), with new evidence recorded from the new trace and zero-LLM citations. |
| re-derivation | Real agent runs (`DerivStore`, 1,519 distinct (fact, commit) derivations in total), memoised per (fact, commit). They are compared with the oracle and can be wrong. |
| baselines | NEVER; TTL k; REPLAY / FILEHASH / ASTHASH (read set of the current trace); CITE; CERT-ZS; CERT v0 (static only); ALWAYS. Each flag ⇒ re-derive and re-baseline the guard at that commit (`baselines.py`). "@oracle" = the re-derivation is replaced by the oracle answer (idealised upper bound, logged s0 derivation cost). |
| subsets | ALL = 285 facts. S1 = pilot7's 86-fact stratified subsample (ablations). SR = 40 facts (pilot7's S3 plus 15 static S1 facts stratified by type; 22 changing) for baselines with real re-derivation. |
| servers | own Ollama servers: 11495 (GPU0, 27B), 11496/11497 (GPU1, 27B or two 9B instances). 11434 never touched. All stopped at the end. |
| LLM volume (non-cached) | 27B: 10,189 calls, 18.8 M prompt + 0.44 M completion tokens. 9B: 7,828 calls, 25.2 M + 0.88 M. Calls identical to pilot7's were served from pilot7's cache. |

## 2. Metric definitions (maintenance framework)

At read t, the *stored* answer is the one held before maintenance and the *served* answer is the one after it.

* **FF**: stored answer wrong, and the policy did not act. Denominator: reads with the stored answer wrong.
* **FS**: stored answer right, but the policy acted (repair or re-derivation). Denominator: reads with the stored answer right.
* **served-wrong**: served answer ≠ oracle, over all reads.
* **needless spend**: evaluator plus re-derivation tokens spent on reads whose stored answer was still right.
* **RDE**: total tokens ÷ the fact's logged s0 derivation tokens (mean 14.7k), Σ/Σ.

**Caveat on per-read FF.** In this framework FF is dominated by *persistence*. A wrong repair or re-derivation stays wrong
on every later read whose evidence did not change, so every maintaining policy shows FF of 80–99 %. That number is not
comparable to pilot7's FF. For detection quality use instead:

* **episodes never acted on**: stored-wrong episodes with no action at all;
* the **detection-only table T5**, which uses pilot7's definitions exactly.

## 3. Main tables

**T5 – detection only, pilot7 framework** (the stored answer is always K; per-commit FF/FS as in pilot7):

| detector | facts | FF % [CI] | FS % [CI] | static FF / FS | behaviour FF / FS | judge calls/fact |
|---|---|---|---|---|---|---|
| pilot7 TRIAGE-a (recomputed, `DETECT-p7a`) | 285 | 3.5 [0.9, 6.6] | 17.1 [13.6, 21.0] | 3.5 / 11.7 | 3.6 / 42.2 | 16.0 |
| **ESM detector (anchored + hierarchical)** | 285 | **2.6 [0.2, 5.8]** | **3.8 [2.3, 5.5]** | 2.7 / 3.2 | 2.5 / 6.6 | 17.4 |
| pilot7 TRIAGE-a on S1 | 86 | 2.1 | 15.0 | 2.2 / 9.9 | 0.0 / 36.5 | 15.7 |
| ESM detector on S1 | 86 | 1.7 | 1.9 | 1.8 / 1.9 | 0.0 / 2.2 | 14.8 |

The ESM detector costs 37.2k evaluator tokens per fact (2.5 RDE). TRIAGE-a costs 26.9k (1.8 RDE): hierarchical
screening and complete deltas cost about 38 % more tokens.

**T1a – maintenance, all 285 facts, read at every commit:**

| policy | served-wrong % [CI] | FF % | FS % | tokens/fact | RDE | judge calls/fact | re-derivations/fact | episodes never acted on % | repairs (correct) |
|---|---|---|---|---|---|---|---|---|---|
| **ESM** | **18.0 [15.0, 21.3]** | 98.5 | 0.1 | 51.8k | 3.52 | 16.6 | 0.78 | 6.8 | 177 (64.4 %) |
| ESM without anchoring, truncated deltas (≈ pilot7 maintainer) | 21.2 [18.2, 24.6] | 98.1 | 0.3 | 70.1k | 4.76 | 18.0 | 1.65 | 6.2 | 277 (45.8 %) |
| NEVER | 28.4 [24.6, 32.4] | 100 | 0 | 0 | 0 | 0 | 0 | 100 | – |
| TTL200 @oracle | 13.1 | 98.9 | 0.4 | 29.4k | 2.00 | 0 | 2.0 | 3.6 | – |
| TTL100 @oracle | 6.6 | 97.8 | 0.9 | 58.9k | 4.00 | 0 | 4.0 | 2.9 | – |
| TTL50 @oracle | 3.5 | 95.6 | 1.9 | 117.8k | 8.00 | 0 | 8.0 | 1.1 | – |
| CERT v0 @oracle (241 static) | 0.9 | 81.6 | 0.7 | 54.1k | 4.18 | 0 | 3.45 | 2.6 | – |
| CERT-ZS @oracle | 1.0 | 85.3 | 1.8 | 182.0k | 12.4 | 0 | 7.8 | 2.0 | – |
| CITE @oracle | 7.0 | 98.1 | 3.1 | 242.5k | 16.5 | 0 | 12.0 | 20.8 | – |
| REPLAY @oracle | 0.0 | 4.0 | 3.9 | 358.1k | 24.3 | 0 | 16.2 | 0.0 | – |
| ASTHASH @oracle | 1.7 | 90.2 | 8.9 | 811.8k | 55.1 | 0 | 35.6 | 3.3 | – |
| FILEHASH @oracle | 1.7 | 90.2 | 9.3 | 850.2k | 57.8 | 0 | 37.4 | 3.3 | – |

**T1c – baselines with REAL re-derivations on SR (40 facts), every commit:**

| policy | served-wrong % [CI] | tokens/fact | RDE | re-derivations/fact | episodes never acted on % |
|---|---|---|---|---|---|
| **ESM** | **14.5 [7.9, 22.3]** | 36.6k | 2.43 | 0.55 | 11.5 |
| ESM-noanchor-trunc | 17.5 [9.4, 26.2] | 66.5k | 4.42 | 1.55 | 13.8 |
| REPLAY + re-derive | 20.3 [11.5, 29.6] | 410.0k | 27.2 | 16.25 | 0.0 |
| TTL50 | 22.2 [12.8, 31.9] | 145.9k | 9.69 | 8 | 0.0 |
| TTL100 | 22.8 [14.9, 30.9] | 74.5k | 4.95 | 4 | 0.0 |
| TTL200 | 23.4 [16.2, 31.3] | 38.0k | 2.52 | 2 | 0.0 |
| ALWAYS (reads every 50 commits) | 23.8 | 145.9k | 9.7 | 8 | 0.0 |
| NEVER | 29.7 [20.4, 39.7] | 0 | 0 | 0 | 100 |
| REPLAY @oracle (same facts) | 0.1 | 369.9k | 24.6 | 16.0 | 0.0 |

Paired on SR (ESM − B, served-wrong pp):

| B | Δ served-wrong [95 % CI] | Δ tokens/fact |
|---|---|---|
| REPLAY | −5.8 [−12.5, +0.2] | −373k |
| TTL50 | −7.7 [−15.0, −1.6] | |
| TTL100 | −8.3 [−14.8, −2.8] | |
| TTL200 | −8.9 [−14.6, −3.8] | at equal cost (−1.4k [−14.7, +14.8]) |
| NEVER | −15.2 [−24.4, −7.3] | |

Against the @oracle baselines on all facts, ESM is worse on served-wrong by 4.9 (TTL200) to 18 (REPLAY) pp. It is
cheaper than all of them except TTL200 and is about tied on cost with CERT v0 (−7k [−26, +10]).

## 4. Ablations (all ESM variants are full maintenance, every commit)

| comparison (set) | Δ served-wrong pp [CI] | ΔFS pp [CI] | Δ tokens/fact [CI] | other |
|---|---|---|---|---|
| ESM − no anchoring & truncated (ALL, 285) | **−3.2 [−5.0, −1.4]** | −0.2 [−0.3, −0.2] | **−18.3k [−27.2, −10.5]** | re-derivations 0.78 vs 1.65 per fact; repair correctness 64 % vs 46 %; mean detection delay 3.9 vs 10.9 reads |
| ESM − no anchoring (hierarchical kept) (S1) | −3.0 [−6.1, −0.6] | −0.2 [−0.3, −0.1] | −29.6k [−48.0, −13.4] | anchoring is the effective ingredient |
| ESM − truncated deltas (anchoring kept) (S1) | +0.0 [−0.1, +0.2] | +0.0 | −0.4k [−9.4, +6.5] | **hierarchical vs truncation: no measurable difference** once anchored |
| ESM − no repair (changed ⇒ re-derive) (S1) | +1.3 [−0.9, +3.5] | 0.0 | −16.5k [−26.7, −8.1] | repair saves about 1 re-derivation per fact; accuracy n.s. (no-repair 14.6 % vs 15.8 %) |
| ESM − unsure-as-fresh (S1) | −0.2 [−0.9, +0.2] | +0.0 | +9.4k [−1.5, +24.9] | unsure=fresh: 0.22 vs 0.66 re-derivations per fact at the same accuracy; FF of episodes 6.2 vs 6.0 % |
| memoisation (cost only, ALL) | – | – | ESM 51.8k vs **432k** without memo (290 vs 16.6 judge calls per fact) | memoisation is an 8× saving |

In the detection-only framework (T5), anchoring + hierarchy cut FS from 17.1 % to 3.8 % (behaviour 42.2 → 6.6 %) at
equal or lower FF.

## 5. Costs

* **ESM, all 285 facts, 400 commits:** 51.8k tokens per fact = **3.52 RDE**. That is 28.4k for the evaluator (16.6 calls,
  including screens) plus 23.4k for re-derivation (0.78 agent runs at about 23.6k tokens each with the 9B agent). This is
  130 tokens per read. 47.5 % of the spend falls on reads whose stored answer was still right (needless).
* Behaviour facts: 79.1k per fact (3.2 RDE). Static facts: 46.8k (3.6 RDE; T4 config facts are the costliest at 12.5 RDE
  because of repeated failed re-derivations).
* pilot7-style maintainer: 70.1k (4.76 RDE). REPLAY + re-derive with real re-derivations: 410k (27 RDE). TTL50: 146k.
  ALWAYS: one derivation (about 18k tokens) per read.
* One 9B re-derivation costs 23.6k tokens on average (s0: 15.0k). The logged s0 derivations, which are the RDE unit,
  average 14.7k.
* Sparse schedules were only run for the @oracle baselines (`tables.md` T4). For example, REPLAY@oracle costs 895 tokens
  per read at every commit, 3.4k per read every 5 commits and 7.8k per read every 20 commits. ESM was **not** run on
  sparse or bursty schedules (§7).

## 6. Error taxonomy of ESM's wrong-served reads (ALL, every commit; 20,492 of 114,000 reads)

| cause | reads | % | facts |
|---|---|---|---|
| a wrong re-derivation, persisting on later reads (the evidence then confirms the wrong answer) | 13,818 | 67.4 | 78 |
| a wrong in-place repair, persisting | 5,669 | 27.7 | 38 |
| missed change: memoised still_valid reused on a state whose truth differs (`click:T5:28/31`, "count remains 2", the same slip pilot7 saw) | 770 | 3.8 | 3 |
| the wrong re-derivation read itself | 162 | 0.8 | 79 |
| the wrong repair read itself | 63 | 0.3 | 39 |
| missed: judge said still_valid on a changed state | 10 | 0.05 | 4 |
| change outside the recorded evidence (state unchanged) | 0 | 0 | 0 |

**Detection is no longer the problem; the answer source is.**

* 95 % of wrong reads trace back to a *wrong new answer*, from the 9B agent or from the judge's new_answer, which the
  maintenance loop then faithfully protects.
* Re-derivation accuracy (T6): 90 % at s0, but 85 % at t = 100 and 65–68 % at t ≥ 300 (SR grid). Answers of "NONE"
  (definition removed or merged) are a frequent failure, e.g. `click:T1:1` keeps answering `src/click/core.py` after the
  class was removed.
* In-place repairs are right 64 % of the time: 70 % for static facts, but only 31 % for behaviour facts, where the judge
  guesses execution results.

## 7. What was skipped or approximated

* **Skipped:**
  * qwen3.5-9B as evaluator (`ESM-9B`);
  * n = 3 self-consistency (`ESM-n3*`);
  * the confidence-threshold knob (the prompt has no confidence field);
  * chained-vs-anchored *maintenance* (`ESM-chain`; only pilot7's TRIAGE-a detection-only result was recomputed);
  * the LLM-on-repository-diff baseline (`LLMDIFF`);
  * ESM on sparse and bursty schedules (every 5 / every 20 / bursty);
  * real-re-derivation runs of FILEHASH / ASTHASH / CITE / CERT-ZS / CERT v0. These are reported only with oracle
    re-derivation (all facts), which flatters them.
* **Consequence:** the FF–FS–cost operating curves contain only these knobs:
  * unsure = stale / fresh;
  * repair on / off;
  * anchoring / truncation ablations;
  * baselines (`curves_ALL.png`, `curves_S1.png`, `curves_SR.png`).
* **Subsets:**
  * Real-re-derivation baselines use SR (40 facts, 22 changing): wide CIs. ESM vs REPLAY is borderline (−5.8 [−12.5, +0.2]).
  * The ablations other than "no anchoring & truncated" use S1 (86 facts).
* **Re-baselining of the instruments after a re-derivation:**
  * CITE keeps its s0 citations; CERT-ZS and CERT v0 keep their calls. All three re-baseline only their reference outputs.
  * REPLAY / FILEHASH / ASTHASH use the new trace's calls and read set (the real runs); the @oracle runs reuse the logged trace.
* **Failures:** 4 facts hit an Ollama HTTP 500 when qwen3.5-9B emitted a malformed tool call during a re-derivation. After a
  fix (the derivation is counted as failed, with no answer) they were rerun and merged.
  * One fact (attrs) crashed the parser on a judge reply containing "{" but no "}". This is fixed: the reply now counts as a
    parse failure, which leads to re-derivation.
* **Unit approximation:** the RDE unit is the logged s0 derivation (mixed models). The real 9B re-derivations cost about 1.6× that.
* **Post-hoc design choices:** the 12 KB single-call tier and the 12 KB group size were set after seeing early screening
  costs. The def-anchor size rule (≤ 1.5×window + 20 lines) was set a priori.

## 8. Continuity with pilot7

| quantity | pilot7 | recomputed with `esm` |
|---|---|---|
| FF / FS, pooled | 3.5 / 17.1 | 3.51 / 17.13 |
| FF / FS, static | 3.5 / 11.7 | 3.5 / 11.7 |
| FF / FS, behaviour | 3.6 / 42.2 | 3.6 / 42.2 |
| judge decisions | 4,549 | 4,549 (16.0 per fact) |

The `DETECT-p7a` run (original recording, capped delta, anchor fixed at s0) made zero new LLM calls: every prompt was
byte-identical to pilot7's and was served from pilot7's cache.

## 9. Files

* `records.parquet`: per (policy, schedule, fact, read) records, with columns stored_valid, served_valid, flagged, action,
  verdict, eval_tok, der_tok, repair_ok, served, …
* `tables.md`, `results.json`: all tables and numbers.
* `curves_{ALL,S1,SR}.png`: FF–FS and served-wrong vs RDE (Pareto step line over non-oracle policies).
* Raw data:
  * `esm_data\sim\*.parquet`
  * `derivations.jsonl`
  * `obs\*.pkl`
  * `llm_cache`
* Reproduce:
  * `python -m esm.scripts.build_states <repo>` (×9)
  * `python -m esm.scripts.run_sim --policies … --schedules …` (served from the cache)
  * `python -m esm.scripts.report`
