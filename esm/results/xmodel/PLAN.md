# Cross-model generalisation (ESWA revision, B-level item 1): plan and LLM budget

*Lab notebook, kept as written during the runs: the plan fixed before the first run, followed by the timestamped decision log. Server ports, hardware incidents and deviations are recorded as they happened; the final numbers are in RESULTS.md.*

Written 2026-10-05, about 22:25, before any cross-model LLM call (the model pull had started; nothing else). Time budget:
about 20 h wall-clock, to about 18:30 on 10-06; the last ~3 h are kept for analysis and writing.

## Question

Does ESM's cost/error trade-off direction hold when the **entire** LLM part of the pipeline — s0 deriver, re-deriver,
transition judge, CERT-ZS certificate extraction and the LLMDIFF judge — is a second, independent model family instead
of Qwen? Everything else is unchanged: the frozen ESM configuration (`ESM-norepair`: anchored evidence, hierarchical
deltas, changed / unsure / too-large / parse-fail ⇒ re-derivation), the prompts (incl. the NONE instruction), the tool
loop (≤ 12 tool calls), the oracle tables, the metrics and the bootstrap code.

## Infrastructure

| item | value |
|---|---|
| GPU | **GPU 0 only** (GPU 1 belongs to another experiment). |
| server | my own Ollama, `127.0.0.1:11621`, `CUDA_VISIBLE_DEVICES=0`, `OLLAMA_NUM_PARALLEL=4`, ctx 16k, local model directory; started with `esm/scripts/start_ollama.ps1 -port 11621 -gpu 0 -par 4` (pid file in `esm_data_xmodel/logs`). Port 11434 is never touched. Stopped at the end with `stop_ollama.ps1 -port 11621`. |
| data | `esm_data_xmodel\` (LLM cache, ledger, derivations, certificates, obs, sim, queues, logs). `obs/` is seeded with a copy of the held-out observation pickles (deterministic tool outputs; a pure cache). The held-out data are only read. |
| code | `esm/llm.py`: `ESM_MAIN_MODEL` replaces the main model wherever it is the default (deriver, judge, verifier, certificates, LLMDIFF); `ESM_REASONING` sets `reasoning_effort` (default `none`, so every earlier cache key is unchanged). No other code change. |
| jobs | `esm/scripts/jobqueue.py` queue `X` in `esm_data_xmodel`; explicit polling with `esm/scripts/poll.py` / `status.py` (no monitors), at least every 30 min. |

## Model choice (probe, ≤ 1 h total, in this order; the first that works reliably is taken)

1. **local `gpt-oss:20b`** (OpenAI family, MoE ~21B / 3.6B active, MXFP4, ~13 GB, fits GPU 0). gpt-oss cannot switch its
   reasoning off; I use `reasoning_effort=low` (closest to Qwen's thinking-off). Probe: 10 s0 derivations on X120 facts
   (2 behaviour + 8 static, seeded), then one transition judgement per correct derivation and 4 CERT-ZS extractions.
   **Pass criteria (fixed now):** ≥ 8/10 derivations end with an `answer` tool call (no server parse errors, no prose
   answers on more than 1), ≥ 7/10 correct at s0, 0 judge `parse_fail` in the probe judgements, CERT-ZS returns
   parseable calls, and ≥ 15 calls/min sustained.
2. if (1) fails: NVIDIA NIM `nvidia/nemotron-3-super-120b-a12b`, then `z-ai/glm-5.3-flash` (≈ 7 calls/min ⇒ the subset
   and schedule would shrink, see below).
3. fallback: `openai/gpt-oss-20b` via NIM.

Should `max_tokens` (judge 900, agent 3000) truncate gpt-oss's answers because reasoning tokens count against it, I will
raise them for the cross-model run only and say so; the probe decides.

## Subset X120 (drawn 22:20, before any LLM call; `draw_x120.py`, `draw_x120.json`, `esm_data_xmodel/sub_X120.json`)

* **Pools** — both have complete Qwen-27B records at every commit for every compared policy, so Qwen can be recomputed on
  exactly these facts:
  * natural: **NAT100** (seeded uniform sample of the 715 natural kept facts);
  * change-enriched: the 89 enriched facts of **H150**.
* **Quota:** 60 + 60. Behaviour facts first (natural: all 8; enriched: 12 of 18), then static facts. Repositories are
  visited round-robin in a seeded random order; each visit adds the fact whose type is least represented so far
  (seed 20261006).
* **Result:** natural 60 = 8 B + 52 static (T1 11, T2 11, T3 12, T4 1, T5 6, T6 1, T7 10), 18 changing; enriched 60 =
  12 B + 48 static (T1 6, T2 8, T3 6, T4 7, T5 8, T6 6, T7 7), 35 changing; all 16 repos in both halves (3–5 facts each).
  Subset hash `b85c7cd6c69436cb`.
* Pooled X120 rates are therefore **not base rates**; the subset is for paired and cross-model comparisons.

## Protocol

1. **s0** with the new model on all 120 facts (`heldout_s0`-equivalent restricted to X120). A fact is kept iff the
   canonicalised answer matches the oracle at s0 (as in Stage 2). Report s0 accuracy vs Qwen-27B (96.0 % on all 1,478;
   recomputed on X120: Qwen was 100 % here by construction, since X120 ⊂ Qwen-kept facts — so the honest comparison is
   the new model's rate on facts Qwen solved, plus the Qwen rate on all held-out facts).
2. **Common fact set** for every comparison = X120 facts kept by the new model (call it X-kept). Qwen's numbers are
   recomputed on X-kept (primary) and on all 120 (reference).
3. **Maintenance over the 400 FUTURE commits, read at every commit**, real re-derivations by the new model:
   ESM (frozen), NEVER, TTL100 + re-derive, CERT-ZS (+ extraction by the new model), LLMDIFF, REPLAY + re-derive.
   Shared derivation store keyed (fact, commit), exactly as in Stage 2.
4. **Fallbacks if the budget forces it (decided from measured throughput, logged below):** REPLAY on the shared every50
   grid (with ESM every50 for the paired comparison); if ESM / TTL / CERT-ZS / LLMDIFF at every commit do not fit, the
   every5 schedule for all arms (and Qwen recomputed at every5 is NOT available from records — Qwen's every-commit
   records would then be compared at the matching reads, i.e. records with t % 5 == 0, which is an approximation and
   will be said so).
5. **Metrics** exactly as Stage 2 / revision r1: served-wrong with fact and repo-cluster bootstrap CIs (B = 2000), FF / FS
   (maintenance definitions) and pilot7 detection FF / FS for the judge (`DETECT-anchor-hier` on X-kept, cheap: shares
   the ESM judge cache), tokens per fact, RDE (unit: the fact's own s0 derivation tokens of the same model),
   re-derivations per fact, paired differences ESM − B, non-inferiority at 0.5 / 1.0 / 1.5 / 2.0 pp (one-sided 95 %
   upper bound < m), cost ratios B / ESM with CIs.
6. **Side-by-side vs Qwen-27B on the same facts:** served-wrong, tokens/fact, ranking, cost-ratio direction; the
   "wrong re-derivation gets anchored" phenomenon: share of ESM's wrong-served reads in episodes that start at a wrong
   re-derivation, and the **repeat-error rate on consecutive re-derivation pairs** (for every pair of consecutive
   re-derivations of the same fact by REPLAY / TTL100 / CERT-ZS / LLMDIFF / ESM, given the first was wrong, how often
   is the second wrong, and with the identical answer string); judge FF / FS (detection-only) for both models.

## Budget (calls of the new model; Qwen-27B per-fact rates from H150 / NAT100 used as the estimate)

| arm | per fact (est.) | X120 total |
|---|---|---|
| s0 derivation (≈ 4.3 LLM calls) | 4.3 | 0.5k |
| ESM (7.8 judge + 1.2 re-derivations × 4.5) | 13 | 1.6k |
| DETECT-anchor-hier (mostly cache hits of ESM's a0 transitions) | 2 | 0.2k |
| TTL100 (4 re-derivations) | 18 | 2.2k |
| CERT-ZS (1 extraction + 4.5 re-derivations) | 21 | 2.5k |
| LLMDIFF (20 judge + 1.8 re-derivations) | 28 | 3.4k |
| REPLAY (≈ 9.5 re-derivations) | 43 | 5.1k |
| **total** (before sharing of (fact, t) re-derivations) | | **≈ 15.5k** |

At an assumed 30–60 calls/min for gpt-oss:20b on one 3080 with 4 parallel slots this is ≈ 4–9 h of GPU time, inside the
budget. Priority (cut from the bottom): s0 → ESM → NEVER → TTL100 → CERT-ZS → LLMDIFF → DETECT → REPLAY (→ every50 if
REPLAY at every commit would end after ~14:30 on 10-06).

## Decision log

* **22:10–23:53, model pull.** `ollama pull gpt-oss:20b` through my own server took 1 h 40 min: the registry CDN stalled
  three times (TLS handshake timeouts), each fixed by restarting the client. This is infrastructure time, not probe time.
* **23:55, the original data drive data gone.** The held-out repositories / tree caches / oracle tables on the original data drive were deleted on 10-05 (see
  PROGRESS.md). The parallel end-to-end experiment had re-cloned the 16 repositories (HEAD pinned to the manifest),
  rebuilt the tree caches and restored the archived oracle tables under `esm_data_e2e/` (its validation reproduced 83 of
  90 Stage-2 judge prompts byte-identically). I copied `repos/`, `trees/`, `oracle_tables/` to `esm_data_xmodel/hd/` and
  added one env override, `ESM_HELDOUT_DATA`, to `esm/envs/heldout.py` (default unchanged). Check: 336 anchored evidence
  states (8 gpt-oss + 40 Qwen s0 traces × 7 commits) recomputed from the rebuilt repos vs the copied observation cache:
  **0 mismatches**.
* **23:55–00:01, probe of gpt-oss:20b (option a), 10 X120 facts (2 behaviour + 8 static, seed 7).**

  | setting | s0 answered | s0 correct | server parse errors | judge parse_fail | CERT-ZS parseable | wall time |
  |---|---|---|---|---|---|---|
  | `reasoning_effort=low`, judge max_tokens 900 | 10/10 | **3/10** | 0 | 0/2 | 2/3 | 39 s for 10 derivations |
  | `reasoning_effort=medium`, judge max_tokens 900 | 9/10 | **8/10** | 0 | **4/8** (all: the 900-token cap was spent inside the hidden reasoning, `finish=length`, empty content) | 2/4 | ~2 min |
  | `reasoning_effort=medium`, judge max_tokens **4000** | (cached) | 8/10 | 0 | **0/8** (8/8 correct still_valid) | 2/4 | – |

  * At `low`, the tool loop is healthy but the answers are poor: format slips (`'**Answer:** \`NONE\`'`, `none` for
    `(none)`, `<NO DEFAULT>`), both behaviour facts wrong. Fails the ≥ 7/10 criterion.
  * At `medium` the pass criteria hold once the judge's `max_tokens` is raised (anticipated above). The 4000 cap is
    applied to every judge-type call of the cross-model run (ESM judge, screens, LLMDIFF judge) via a new env var
    `ESM_JUDGE_MAXTOK` in `esm/judge.py` (default 900, so earlier stages are unchanged). Agent turns keep 3000 and
    CERT-ZS keeps 3000 (largest probe completion 1,264).
  * **gpt-oss trait:** on tool-less prompts it sometimes emits a hallucinated tool call (`repo_browser.search`,
    `repo_browser.open_file`) instead of JSON. 2 of 4 probe CERT-ZS extractions came back empty this way. The protocol is
    kept as is: an empty certificate falls back to REPLAY (the same rule as for Qwen); the empty rate is reported. A judge
    reply of that kind is a `parse_fail` ⇒ re-derivation (frozen rule).
  * **Decision (00:02): gpt-oss:20b (OpenAI family), `reasoning_effort=medium`, judge max_tokens 4000.** Options (b)/(c)
    (NIM) were not needed and not probed. Probe LLM time: ~8 min; probe calls are in `esm_data_xmodel/probe*/` ledgers
    and are not reused by the main run (separate stores).
  * Throughput seen in the probe: ~30–35 calls/min with 4 requests in flight; derivations at medium cost 4–53k tokens
    (Qwen-27B on the same facts: 8.4k mean on all kept facts).
* **00:05, queues.** Queue XA: s0 on X120 → NEVER → ESM → DETECT-anchor-hier → LLMDIFF. Queue XB (started when s0 is
  done): CERT-ZS extraction → TTL100 → CERT-ZS → REPLAY. Both use the same server (4 slots, 4 requests in flight per
  process).
* **00:10, Ollama HTTP 500 "error parsing tool call".** gpt-oss sometimes emits a malformed tool call that Ollama
  cannot parse. `esm/llm.py` only treated Qwen's "XML syntax error" as deterministic; the gpt-oss message is now handled
  the same way (3 attempts, then `ServerParseError` ⇒ the derivation ends without an answer, exactly the Qwen rule). The
  2 s0 derivations that had failed with the old code were re-run (both: no answer).
* **00:18, gpt-oss:20b fails at scale — the probe passed by luck.** s0 on all 120 X120 facts: **71/120 correct
  (59.2 %)**, 15 wrong, 34 no answer (Qwen-27B: 96.0 % on all held-out facts; 120/120 here by construction). Causes,
  read from the traces:
  * 155 of 879 tool calls (18 %) go to tools that do not exist (`search` 90, `open_file` 25, `open` 9 — gpt-oss's
    built-in browser tool names), and `read` is called with `line_start` / `line_end` instead of the schema's `start` /
    `end` (the tool then re-reads from line 1, so the agent loops);
  * 6 answers are a tool-call JSON leaked into the message content (e.g. `{"path":"boltons/cacheutils.py","pattern":...}`);
  * 33 of 120 derivations exhaust the 12-call budget (Qwen: 1.8 % no-answer).
  By the brief's criterion ("works reliably with the tool loop") gpt-oss:20b fails; I move to option (b).
  **It is kept as a secondary, clearly labelled arm** ("a weak tool user"): it runs on the otherwise idle local GPU 0 at
  no extra cost, on its 71 kept facts, with the same arms. It is not the primary cross-model result.
* **00:20–00:27, probe of option (b) `nvidia/nemotron-3-super-120b-a12b` on NIM** (same 10 facts, same code; NIM
  backend added to `esm/llm.py`: `nim:<model>`, key / base URL from `.env`, per-process request-start rate limit
  `ESM_NIM_RPM`, `ESM_NIM_CONC` requests in flight; reasoning left at the NIM default = on, short):
  s0 answered 9/10, **correct 9/10**; judge 9/9 parsed (8 still_valid, 1 changed — a false alarm on kombu:T3:n33);
  CERT-ZS 4/4 parseable; 0 retries, 0 HTTP 429 at 4 in flight / ≤ 30 RPM; 93 calls in 6 min (~15/min, latency-bound).
  Nemotron needs ~7–10 LLM turns per derivation (Qwen ~4.3) and 8–63k tokens. **Decision (00:28): Nemotron-3-Super
  (NVIDIA family; hybrid Mamba-Transformer MoE, independent of Qwen) is the primary second model.** Data in
  `esm_data_xmodel/nemotron/`; the gpt-oss secondary arm stays in `esm_data_xmodel/`. Probe time used: ~25 min of the
  1 h (plus the 15-min gpt-oss s0 that exposed the failure).
* **00:30, Nemotron queue NA started** with s0 on X120 at 8 in flight / ≤ 40 RPM (to measure the sustainable rate
  before fixing the schedule / subset; the brief's "≈ 7 calls/min" would force a large shrink). gpt-oss queue XB
  started (CERT-ZS extraction → TTL100 → CERT-ZS → REPLAY).
* **00:50, Nemotron s0 done: 115/120 correct (95.8 %)** — on par with Qwen-27B (96.0 % on all held-out facts). 752
  calls in 22 min (~33/min, 6.3 LLM turns per derivation).
* **00:52–01:05, NIM throttling.** After ~790 calls at ~35/min the key was throttled to ~3 calls/min (HTTP 429 on most
  requests; it looks like a rolling request quota, not a fixed RPM). The back-off of `llm.chat` (8 attempts) would make
  facts fail. Changes: for the NIM backend, 429s are retried patiently (≥ 60 attempts, back-off cap 180 s); the queue
  was restarted at **≤ 12 request starts/min, 4 in flight**. The killed ESM job had not saved any fact (all its calls
  are cached and reused).
* **01:10, Nemotron re-plan (the brief's "shrink the subset accordingly").** At ≤ 12 calls/min (~8.6k calls in the
  ~12 h left) the full protocol on 115 facts (~150–200 calls per fact at every commit) does not fit. **X60** = a seeded
  stratified half of the 115 Nemotron-kept X120 facts (`draw_x60.py`, `draw_x60.json`; 30 natural incl. 4 behaviour,
  30 enriched incl. 6 behaviour; all 16 repos in each half; 11 + 18 changing), drawn after s0 and before any
  maintenance outcome existed. Order (queue NA): phase 1 on X60 at **every commit**: ESM → TTL100 → CERT-ZS extraction →
  CERT-ZS → LLMDIFF → ESM + REPLAY on the shared every50 grid → DETECT; phase 2: ESM on the other 55 kept facts
  (deadline 13:00); then **REPLAY at every commit on X60** (deadline 14:45; facts not started by then are reported
  missing and REPLAY's every-commit comparison is restricted to the finished facts). NEVER already covers all 115.
  The gpt-oss secondary arm keeps its full protocol on its 71 kept facts (local GPU, no quota).
* **01:45, re-plan 2.** Even at ≤ 12 RPM the key delivers only **~4–5 calls/min** (01:00–01:40, steady; HTTP 429 on
  most requests) — i.e. the brief's "≈ 7 calls/min sustained"; the first ~800 calls were an initial allowance. After
  35 min no X60 fact had finished ESM. At ~4.5/min (~3.4k calls left) and ~120 Nemotron calls per fact for all arms,
  **X30** = the same stratified procedure applied to X60 (15 natural incl. 2 behaviour, 15 enriched incl. 3 behaviour;
  `draw_x30.json`; drawn before any maintenance outcome existed). Queue NA: phase 1 on X30 — ESM, TTL100, CERT-ZS
  extraction, CERT-ZS, LLMDIFF at every commit; ESM + REPLAY on the shared every50 grid; DETECT. Phase 2 extends ESM,
  TTL100, CERT-ZS, LLMDIFF to the other 30 facts of X60 with deadlines (12:00 / 13:00 / 14:00 / 14:45). REPLAY at every
  commit is dropped for Nemotron (would be ~60 calls per fact); REPLAY is compared on the every50 grid. All calls of
  the two killed runs are cached and reused.
* **01:40, insurance.** Started pulling `mistral-small3.2:24b` (Mistral AI, a third family) on my server, bandwidth
  only. It would be used only if NIM stops delivering; any use will be logged here.
* **01:50–02:03, Mistral probe (outside the brief's list; would have been an additional full-size family on GPU 0).**
  The gpt-oss queues were paused for it (Ollama does not swap models while the loaded one is busy). Same 10-fact
  probe: **0/10 correct** — after one tool call Mistral answers in prose ("I will now search for files that import …")
  instead of calling the next tool, which the frozen loop takes as the final answer. Dropped; nothing else was run with
  it. gpt-oss queues restarted at 02:03 (the two interrupted jobs, DETECT and REPLAY, rerun from cache). Added the
  every50 grid (ESM + REPLAY) to the gpt-oss arm.
* **02:50, Nemotron order of the remaining phase-1 jobs.** At the measured 4.2 calls/min, phase 1 on X30 needs ≈ 4k
  calls against ≈ 3.1k that fit before ~15:00. New order after ESM: TTL100 → CERT-ZS extraction → CERT-ZS → ESM + REPLAY
  on the every50 grid → DETECT → **LLMDIFF at every commit in seeded random fact order with a 14:40 deadline** (facts
  not started by then are missing; LLMDIFF's comparisons use the finished facts, an unbiased random subset of X30).
  Phase 2 (the other 30 facts of X60) will most likely not run.
* **04:05, Nemotron order changed again** (ESM on X30 finished at 03:55, 2 h 20 min; TTL100 running): DETECT
  (mostly ESM's cached a0 judgements; answers the judge FF/FS question) → CERT-ZS extraction → CERT-ZS → LLMDIFF
  (random order, deadline 12:30) → ESM + REPLAY on the every50 grid (random order, deadline 14:40). Rationale: REPLAY
  already has a fallback form (grid) and the detector is cheap.
* **05:25 / 06:10 / 07:03:** Nemotron TTL100, DETECT and CERT-ZS (30/30 certificates parseable) finished on X30;
  CERT-ZS was fast because most of its re-derivations fall on commits ESM / TTL100 had already derived (shared store).
* **07:10, phase 2 replaced.** Extending single arms to more facts would not help paired comparisons, so after the REPLAY
  grid the other 30 X60 facts run in seeded-random chunks of 5 (`sub_X60rest_c*.json`, seed 2026100630), each chunk
  ESM + TTL100 + CERT-ZS together, deadline 15:20. LLMDIFF and the REPLAY grid stay X30-only.
* **04:55–05:05, Qwen every50 completion run** (qwen3.6:27b on my server, GPU 0, after the gpt-oss arm finished): only
  24 new 27B judge calls; every derivation it needed was already in the Stage-2 LLM cache. **My Ollama server 11621 was
  stopped at 05:05** (nothing else needs GPU 0; Nemotron runs on NIM).
* **02:50, Qwen every50 completion.** Stage 2 ran the every50 grid only on H150; 52 X120 facts lack Qwen every50
  records. `qwen_every50.py` re-simulates NEVER / ESM / REPLAY at every50 for them from the Stage-2 cache and
  derivations (read-only copies in `esm_data_xmodel/qwen50/`); offline, 12 (ESM) and 36 (REPLAY) facts need new 27B
  calls. These will be made with qwen3.6:27b on my server (GPU 0) after the gpt-oss arm is finished.
* **10:15 / 11:07:** Nemotron LLMDIFF (all 30 X30 facts) and the every50 grid (ESM + REPLAY, all 30) finished.
* **11:10, stop.** The coordinator asked for the deliverables. Phase 2 (extending ESM + TTL100 + CERT-ZS to the other 30
  X60 facts) would add facts for only three arms, so it was cancelled after a few minutes of chunk 0. Any partial
  phase-2 rows in `nemotron/sim/` are excluded from the analysis (`XM_CORE_IDS` = X30). The Nemotron queue and the
  two idle gpt-oss queue loops were stopped. My Ollama server had already been stopped at 05:05. **Port 11434 was never
  touched.** GPU 1 was never used.
* Clock note: the decision-log times between 00:30 and 01:45 above were written from estimates and run up to ~10 min
  ahead of the real clock; the ledgers' timestamps are authoritative.

## Realised budget (from the ledgers; non-cached calls only)

| model | where | role | calls | prompt tokens | completion tokens |
|---|---|---|---|---|---|
| nemotron-3-super-120b-a12b (NIM) | primary arm, `esm_data_xmodel/nemotron/` 00:27–11:08 | derivation agent (s0, re-derivations) | 2,024 | 5.16M | 0.64M |
| | | ESM / DETECT judge | 677 | 0.83M | 0.38M |
| | | LLMDIFF judge | 717 | 1.47M | 0.37M |
| | | CERT-ZS extraction | 39 | 0.05M | 0.02M |
| | | **total** | **3,457** | **7.52M** | **1.41M** |
| gpt-oss:20b (own Ollama, GPU 0) | secondary arm, `esm_data_xmodel/` 00:03–04:54 | derivation agent | 6,209 | 14.78M | 0.53M |
| | | ESM / DETECT judge | 1,292 | 1.84M | 0.84M |
| | | LLMDIFF judge | 2,805 | 6.35M | 1.52M |
| | | CERT-ZS extraction | 71 | 0.10M | 0.02M |
| | | **total** | **10,377** | **23.07M** | **2.92M** |
| qwen3.6:27b (own Ollama, GPU 0) | every50 completion, `qwen50/` 04:56–04:57 | judge 20, agent 4 | 24 | 0.03M | 0.00M |
| probes | `probe*` dirs | gpt-oss low 69, gpt-oss medium 107, Nemotron 95, Mistral 24 | 295 | 0.56M | 0.08M |

**Planned against realised.** The plan assumed one model at 30–60 calls/min, ≈ 15.5k calls on X120. In reality the
reliable model (Nemotron) was rate-limited to ~4.3 calls/min after an initial ~800-call burst. It made 3.5k calls and
covered X30 with every arm (REPLAY on the every50 grid only). The fast local model (gpt-oss) made 10.4k calls and
covered its 71 kept facts with every arm, including REPLAY at every commit.

**Wall-clock.** 22:10 (10-05) to ~11:10 (10-06) for the runs. 1 h 40 min of that went to the model download. Analysis
and writing took until ~12:00. This is inside the 20 h budget.

**Ledger integrity.** 1 unparseable line in the gpt-oss ledger (a concurrent append).
