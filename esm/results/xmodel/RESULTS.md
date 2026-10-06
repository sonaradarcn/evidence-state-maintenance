# Cross-model generalisation of ESM (ESWA revision, B-level item 1)

Date: 2026-10-06.

* **Sources.** Every number comes from `analyze.py`. Primary output: `tables.md`, `results.json`, `records.parquet`,
  `fig_xmodel_tradeoff.png`, `fig_xmodel_paired.png`. Secondary arm: the same files with suffix `_gptoss`.
* **Plan and log.** `PLAN.md` holds the plan, written before any cross-model LLM call, every decision with its
  reason, and the realised budget.
* **Comparison data.** The Qwen3.6-27B numbers are recomputed from the Stage-2 / revision-r1 records, restricted to
  the **same facts**.

## 0. Verdict

**Second model: NVIDIA Nemotron-3-Super-120B-A12B (NIM).** It is an independent family: NVIDIA's hybrid
Mamba-Transformer MoE. It replaced Qwen in every LLM role of the pipeline:

* s0 deriver and re-deriver;
* ESM transition judge;
* CERT-ZS certificate extraction;
* LLMDIFF judge.

Everything else is frozen: `ESM-norepair`, the prompts, the 12-call tool loop, the oracle and the metrics.

**Coverage.**

* s0 on 120 stratified facts: **115/120 correct (95.8 %)**, against Qwen-27B's 96.0 % on the full held-out set.
* NIM throttled the key to ~4.3 calls/min, so maintenance ran on **X30**: 15 natural + 15 change-enriched facts, all
  16 repos.
* Every commit (400 reads): ESM, NEVER, TTL100, CERT-ZS, LLMDIFF.
* REPLAY on the shared every50 grid.

**Accuracy direction: holds.** On the same 30 facts:

| | Nemotron | Qwen |
|---|---|---|
| ESM served-wrong | 7.3 % | 6.7 % |
| ESM − TTL100 | **−8.1 pp** | −7.0 pp |
| ESM − NEVER | **−22.0 pp** | −22.5 pp |

* No baseline is significantly better than ESM under either model; there is no opposite-sign significant effect.
* Under Nemotron, ESM is also significantly better than LLMDIFF: −2.9 pp, cluster CI [−8.2, −0.0].
* Under Nemotron, ESM is non-inferior to CERT-ZS at 1.5 / 2.0 pp.
* On the grid, ESM − REPLAY is −4.2 pp under Nemotron and −1.3 pp under Qwen; both CIs touch 0.

**Cost direction: same sign, much smaller margin.** Token ratios baseline / ESM:

| baseline | Qwen | Nemotron |
|---|---|---|
| TTL100 | 1.67 | 1.13 |
| CERT-ZS | 1.71 | 1.19 |
| LLMDIFF | 3.34 | 2.24 |
| REPLAY (grid) | 2.64 | 2.63 |

* In LLM calls, Nemotron's ESM is **no cheaper than TTL100 or CERT-ZS** (1.00×, 0.97×). It stays cheaper than LLMDIFF
  (1.77×) and REPLAY.
* Why: Nemotron explores more (5.2 tool calls per s0 trace against ~3.3), so ESM records more evidence and its judge
  runs 12.5 times per fact (Qwen: 6.0).

**The anchoring phenomenon appears in both families.**

| | Qwen | Nemotron |
|---|---|---|
| a wrong re-derivation followed by another wrong one (consecutive pairs) | 84 % | 84 % (36/43) |
| … of which the identical answer string | | 35/36 |
| share of ESM's wrong reads that come from anchored wrong re-derivations | 100 % | 65 % |

Under Nemotron the rest of ESM's wrong reads are judge misses.

**Judge detection:**

| | Qwen | Nemotron |
|---|---|---|
| FF | 0.0 % | 5.4 % (behaviour 18.4 %) |
| FS | 2.6 % | 3.2 % |

**Secondary arm, gpt-oss-20B** (OpenAI family, local; 71 kept facts, every arm at every commit). This model is
**unreliable with the tool loop**:

* 59 % s0;
* 18 % of its tool calls go to non-existent tools.

Even so:

* ESM has the lowest served-wrong of all six policies: 11.9 % against 13.4–24.3 %.
* It is significantly better than TTL100 and REPLAY.
* Its cost advantage disappears against TTL100: ratio 0.90.

## 1. Model choice: the probe results

The order came from the brief: (a) local gpt-oss:20b, (b) NIM Nemotron-3-Super or GLM-5.3-flash, (c) NIM gpt-oss-20b.
The pass criteria were fixed in PLAN.md beforehand:

* ≥ 7/10 s0 correct;
* healthy tool loop;
* 0 judge parse failures;
* parseable CERT-ZS.

The probe used the same 10 X120 facts (2 behaviour + 8 static, seed 7) for every model.

| model / setting | s0 answered | s0 correct | judge parse_fail | CERT-ZS parseable | notes |
|---|---|---|---|---|---|
| gpt-oss:20b, reasoning low, judge max_tokens 900 | 10/10 | 3/10 | 0/2 | 2/3 | format slips (`**Answer:** \`NONE\``, `none` for `(none)`) |
| gpt-oss:20b, reasoning medium, max_tokens 900 | 9/10 | 8/10 | **4/8** | 2/4 | the 900-token cap was spent inside hidden reasoning |
| gpt-oss:20b, reasoning medium, judge max_tokens **4000** | 9/10 | 8/10 | 0/8 | 2/4 | **passed the probe** |
| *gpt-oss:20b at scale, all 120 X120 facts* | *86/120* | ***71/120 (59.2 %)*** | – | – | **fails at scale**: see below |
| **Nemotron-3-Super (NIM)**, reasoning at NIM default, judge max_tokens 4000 | 9/10 | **9/10** | 0/9 | 4/4 | **passed**; at scale 115/120 |
| mistral-small3.2:24b (not in the brief; insurance while NIM was throttled) | 9/10 | 0/10 | – | – | stops after one tool call and answers in prose; dropped |

**gpt-oss:20b failed at scale. It passed the 10-fact probe by luck.** On the full s0 traces:

* 155 of 879 tool calls (18 %) went to tools that do not exist: `search`, `open_file`, `open`. These are gpt-oss's
  built-in browser tools.
* `read` was called with `line_start` / `line_end` instead of `start` / `end`, so it re-read from line 1 and looped.
* 6 answers were leaked tool-call JSON.
* 33 derivations exhausted the 12-call budget.
* Ollama returned HTTP 500 "error parsing tool call" for malformed calls. These are now treated like Qwen's
  deterministic parse errors.

I therefore moved to option (b) and kept gpt-oss as a clearly labelled secondary arm. It ran free on the local GPU 0.
GLM-5.3-flash timed out on a single test call. Option (c) was not needed.

## 2. Subsets (all drawn by seed, before any maintenance outcome existed)

* **X120** (`draw_x120.py`): 60 natural facts from NAT100 and 60 change-enriched facts from H150.
  * Behaviour facts were drawn first (8 natural + 12 enriched), then static facts.
  * Repos were visited round-robin; each visit took the least-represented type.
  * Every compared policy has complete Qwen records at every commit on these facts.
* **X60 → X30** (`draw_x60.py`): the same procedure applied to the 115 facts Nemotron kept, after NIM throttled the key.
  * X30 = 15 natural (2 behaviour) + 15 enriched (3 behaviour); 13 / 12 repos; 6 / 9 changing.
  * Pooled X30 rates are therefore not base rates. X30 is for paired and cross-model comparison.
* **gpt-oss:** its 71 kept X120 facts.

## 3. Main side-by-side table (X30, the same 30 facts for every row)

Reads at every commit (400 per fact), real re-derivations by each model. Fact bootstrap CIs are in [ ], repository
cluster bootstrap CIs in { } (B = 2000).

| policy | Qwen3.6-27B served-wrong % | Qwen tokens/fact | Qwen LLM calls/fact | **Nemotron served-wrong %** | **Nemotron tokens/fact** | Nemotron LLM calls/fact |
|---|---|---|---|---|---|---|
| **ESM (frozen)** | **6.7** [0.0, 15.1] {0.0, 15.2} | **20.2k** | 13.5 | **7.3** [1.2, 15.5] {1.0, 15.3} | **56.7k** | 26.7 |
| NEVER | 29.2 {17.1, 42.6} | 0 | 0 | 29.2 {17.1, 42.6} | 0 | 0 |
| TTL100 + re-derive | 13.7 {6.6, 22.0} | 33.7k | 17.9 | 15.4 {8.5, 23.8} | 63.9k | 26.8 |
| CERT-ZS + re-derive (incl. extraction) | 5.4 {0.0, 13.4} | 34.7k | 18.9 | 8.8 {0.1, 20.0} | 67.7k | 25.8 |
| LLMDIFF + re-derive | 6.2 {0.7, 13.8} | 67.5k | 30.1 | 10.2 {3.3, 20.1} | 126.9k | 47.3 |
| REPLAY + re-derive, every commit | 6.2 {0.7, 14.1} | 118.3k | – | not run (rate limit) | – | – |
| *every50 grid:* ESM | 5.4 | 14.8k | | 8.8 | 33.0k | |
| *every50 grid:* REPLAY | 6.7 | 39.0k | | 12.9 | 87.0k | |

**Paired ESM − baseline** (pp; negative = ESM better; NI = non-inferiority, one-sided 95 % upper bound < margin):

| baseline | Qwen Δ {cluster CI} | Qwen NI 0.5/1/1.5/2 pp | Qwen token / call ratio B/ESM | **Nemotron Δ {cluster CI}** | Nemotron NI 0.5/1/1.5/2 pp | **Nemotron token / call ratio B/ESM {cluster CI}** |
|---|---|---|---|---|---|---|
| NEVER | −22.5 {−33.5, −12.9} | y y y y | – | −22.0 {−31.3, −12.8} | y y y y | – |
| TTL100 | −7.0 {−12.3, −2.0} | y y y y | 1.67 / 1.32 | **−8.1 {−11.7, −5.0}** | y y y y | 1.13 {0.83, 1.66} / 1.00 |
| CERT-ZS | +1.3 {−0.0, +4.7} | n n n n | 1.71 / 1.40 | −1.6 {−6.4, +1.7} | n n y y | 1.19 {0.42, 2.06} / 0.97 |
| LLMDIFF | +0.5 {−2.7, +5.2} | n n n n | 3.34 / 2.23 | **−2.9 {−8.2, −0.0}** | y y y y | 2.24 {1.37, 3.65} / 1.77 |
| REPLAY, every50 grid | −1.3 {−3.5, +0.0} | – | 2.64 (tokens) | −4.2 {−9.2, +0.0} | – | 2.63 (tokens) |

**Rankings.**

* By served-wrong: Nemotron ESM < CERT-ZS < LLMDIFF < TTL100 < NEVER; Qwen CERT-ZS < LLMDIFF = REPLAY < ESM < TTL100 <
  NEVER.
* Kendall τ = 0.60 over the 5 shared policies. Qwen's top four lie within 1.3 pp of each other, none significant, so
  their order is noise.
* By tokens: the same order for both models: NEVER < ESM < TTL100 < CERT-ZS < LLMDIFF (< REPLAY).

**X30 caveat for Qwen.** On these 30 facts Qwen's ESM is not non-inferior to CERT-ZS even at 2 pp: +1.3 pp, one-sided
upper bound 4.0. On the larger Stage-2 samples it was a tie (H150 −0.2 pp; NAT100 0.0 pp). X30 is small and has few
changing facts (15), so all CIs are wide.

## 4. Why Nemotron's cost advantage is smaller

| ESM, X30 | Qwen | Nemotron |
|---|---|---|
| tool calls per s0 trace | ~3.3 | 5.2 |
| judge calls per fact | 6.0 | 12.5 |
| re-derivations per fact | 1.40 | 1.90 |
| tokens per re-derivation | 11.5k | 19.1k |
| completion share of judge tokens (reasoning) | 3 % | 31 % |
| ESM judge / re-derivation tokens per fact | 6.6k / 13.6k | 20.0k / 36.7k |
| lifetime kept | 95.4 % | 83.6 % |

* The baselines get more expensive too, but less so.
* TTL100's cost is fixed at 4 re-derivations.
* CERT-ZS's re-derivations mostly fall on commits that ESM / TTL100 had already derived, so in this shared store they
  cost little.
* ESM's own cost scales with the evidence volume and with the judge's verbosity. Both are properties of the model.
* **The cost advantage is not model-invariant.** It is large when the model records compact evidence and judges
  tersely (Qwen with thinking off). Against fixed-schedule or certificate baselines it shrinks to about parity for a
  verbose, exploratory reasoning model. Against LLMDIFF and REPLAY it persists (≥ 1.8× in calls, ≥ 2.2× in tokens).

## 5. The "wrong re-derivation gets anchored" phenomenon, and the judge

| quantity (X30) | Qwen | Nemotron |
|---|---|---|
| re-derivations at t > 0 by the compared arms, correct % | 86.1 (n = 403) | 82.5 (n = 280) |
| … when the truth changed / unchanged | 71.4 / 99.5 | 73.6 / 89.7 |
| … when the oracle is NONE | 61.0 | 60.0 |
| no-answer re-derivations | 2.0 % | 7.1 % |
| P(2nd re-derivation wrong \| 1st wrong), consecutive pairs, all arms pooled | 84.1 % (53/63; 75 % = 12/16 without REPLAY) | **83.7 % (36/43)**, 35 with the identical answer string |
| P(2nd wrong \| 1st right) | 3.8 % | 5.9 % |
| ESM wrong-served reads in episodes that start at a wrong re-derivation | 100 % (805/805) | 65 % (568/874) |
| detector only (pilot7 definitions): FF / FS | 0.0 / 2.6 % | 5.4 [0, 16.1] / 3.2 % (behaviour FF 18.4 %) |

**Anchoring.**

* The wrong re-derivation is a stable property of the answer source in both families: it repeats about 84 % of the
  time and is almost always the same string. Periodic refresh does not fix it.
* Under Nemotron, about a third of ESM's wrong reads come instead from judge misses (FF). These are concentrated in
  behaviour facts.
* The NONE-referent difficulty is model-independent: both models are right on about 60 % of re-derivations whose
  oracle value is NONE.

## 6. Secondary arm: gpt-oss-20B (an unreliable tool user; `tables_gptoss.md`)

71 facts kept at s0 (59.2 %). Every arm at every commit, REPLAY included. The same 71 facts for Qwen.

| policy | Qwen % | Qwen tokens/fact | gpt-oss % | gpt-oss tokens/fact | gpt-oss Δ ESM − B {cluster} | token ratio B/ESM (Qwen / gpt-oss) |
|---|---|---|---|---|---|---|
| ESM | 4.4 | 15.9k | **11.9** | 57.4k | – | – |
| NEVER | 24.3 | 0 | 24.3 | 0 | −12.4 {−19.7, −5.5} | – |
| TTL100 | 9.7 | 32.7k | 22.0 | 51.5k | −10.1 {−14.4, −5.5} | 2.06 / **0.90** |
| CERT-ZS | 3.9 | 29.2k | 14.0 | 70.6k | −2.1 {−6.8, +2.4} | 1.83 / 1.23 |
| LLMDIFF | 6.1 | 45.2k | 13.4 | 219.9k | −1.5 {−5.1, +1.8} | 2.84 / 3.83 |
| REPLAY | 5.1 | 89.7k | 20.2 | 211.1k | −8.3 {−12.9, −3.3} | 5.64 / 3.68 |

* With a weak re-deriver (68.6 % correct at t > 0; 25.6 % no answer), every policy that re-derives often is hurt the
  most. ESM, which re-derives least, comes out best on accuracy.
* Repeat-error on consecutive pairs: 77.1 %. Anchored share of ESM's wrong reads: 96 %.
* Detector: FF 6.6 / FS 7.2 %.
* ESM's cost advantage survives only against LLMDIFF, REPLAY and, marginally, CERT-ZS.

## 7. Deviations

* **Subset size and schedule.**
  * Nemotron is on 30 facts, not 120. NIM throttled after ~800 calls; the sustained rate was ~4.3 calls/min (~3.5k
    calls in total).
  * Nemotron REPLAY ran only on the shared every50 grid. It was compared against Qwen on the same grid, completed for
    the non-H150 facts by `qwen_every50.py`: 24 new 27B calls, the rest from the Stage-2 cache.
  * A planned extension of ESM / TTL100 / CERT-ZS to 30 more facts was cancelled when the deliverables were requested.
* **Model adaptations** (env vars; defaults unchanged, so earlier stages are bit-identical):
  * judge `max_tokens` 4000, because reasoning models spend tokens on hidden reasoning;
  * gpt-oss `reasoning_effort=medium`;
  * Nemotron's reasoning left at the NIM default;
  * a NIM backend with patient 429 retries;
  * gpt-oss's "error parsing tool call" is treated as a deterministic parse failure.
* **Tokens are not comparable across models one to one.** Reasoning tokens count as cost. LLM calls per fact are given
  as a second, model-agnostic cost measure.
* **the original data drive data was deleted on 10-05.** The held-out repos / trees / oracle tables come from the copy rebuilt by the e2e
  stage (`esm_data_xmodel/hd`, via `ESM_HELDOUT_DATA`). 336/336 checked evidence states match the old observation
  cache.
* **Power.** X30 has 15 changing facts. The CIs are wide, and the accuracy statements are about direction, not size.
* **No GPU 1, no port 11434.** My Ollama server (11621, GPU 0) was stopped at 05:05.

## 8. Files

* `PLAN.md`: the plan, the decision log and the realised budget.
* `draw_x120.py` / `.json`, `draw_x60.py`, `draw_x60.json`, `draw_x30.json`: the subset draws.
* `probe.py`: the model probe.
* `qwen_every50.py`: the Qwen grid completion.
* `analyze.py`: the analysis.
* Generated outputs:
  * `tables.md`, `results.json`, `records.parquet` (Nemotron + Qwen on X30; column `model`);
  * `fig_xmodel_tradeoff.png`, `fig_xmodel_paired.png`;
  * the `_gptoss` variants of each.
* Raw data:
  * `esm_data_xmodel/nemotron/` (primary): sim, derivations, certs, ledger, cache, queue logs;
  * `esm_data_xmodel/` (gpt-oss);
  * `esm_data_xmodel/qwen50/`;
  * `esm_data_xmodel/probe*/`.
* Reproduce, offline:

  ```
  XM_CORE_IDS=esm_data_xmodel/nemotron/sub_X30.json ESM_HELDOUT_DATA=esm_data_xmodel/hd python esm/results/xmodel/analyze.py
  ```

  and `XM_DATA=esm_data_xmodel XM_SUFFIX=_gptoss … analyze.py` for the secondary arm.
* Code changes in the package, all opt-in through env vars:
  * `esm/llm.py`: `ESM_MAIN_MODEL`, `ESM_REASONING`, the NIM backend, the gpt-oss parse-error rule;
  * `esm/judge.py`: `ESM_JUDGE_MAXTOK`;
  * `esm/envs/heldout.py`: `ESM_HELDOUT_DATA`;
  * `esm/scripts/heldout_s0.py`: `--facts`.
