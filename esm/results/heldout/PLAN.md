# Held-out evaluation of ESM: plan and LLM budget

*Lab notebook, kept as written during the runs: the plan fixed before the first run, followed by the timestamped decision log. Server ports, hardware incidents and deviations are recorded as they happened; the final numbers are in RESULTS.md.*

Written 2026-10-03, about 16:40, before any held-out *maintenance* run. Two things had already started 50 minutes earlier
because neither depends on a policy choice:

* the s0 derivations (step 1);
* the dev calibration runs (step 0).

Time budget: about 36 h wall-clock, from 15:50 on 10-03 to about 03:50 on 10-05. The last about 5 h are kept for analysis and
writing.

## Infrastructure

| item | value |
|---|---|
| local LLM servers | two own Ollama servers: 11595 (GPU0) and 11596 (GPU1). Both run qwen3.6:27b (q4), thinking off (`reasoning_effort=none`), T = 0, ctx 16k. Port 11434 is never touched. Stopped at the end. |
| remote LLM server | a second machine (RTX 3080 10 GB). A dedicated Ollama there serves qwen3.5:9b through an ssh tunnel. Used only for the 9B arms. Stopped at the end. |
| measured throughput (27B) | One request in flight per server: about 14 calls/min in total. With 2–3 in flight per server: about 20–25 calls/min in total for ~2k-token prompts. Ollama ignores `NUM_PARALLEL` for this model, so the gain comes from pipelining. |
| data | All new data goes to `esm_data_heldout\`: `llm_cache`, `llm_ledger.jsonl`, `derivations.jsonl`, `obs/`, `sim/`, `certs.jsonl`, `dev27/`, `logs/`, and the job queues. D: is read only: heldout_data, the dev esm_data, and the pilot caches through read-through. |
| job control | `esm/scripts/jobqueue.py`: persistent queues A (main) and B (auxiliary). Each job is a `run_sim` / `derive_grid` / … command. I poll at least every 30 min from the shell (ledger rate, queue `.done`, logs), with no monitors. |

## Step 0 — dev calibration of the repair policy (frozen before held-out maintenance)

* **Facts and model.** The S1 subset of the dev set (86 facts, pilot7's stratified subsample). The re-deriver is qwen3.6:27b
  (`ESM_KIND=dev27`). The judge is the frozen ESM judge: 27B, anchored evidence, hierarchical deltas, unsure ⇒ re-derive.
* **Policies, read at every commit:**
  * `ESM` (plain repair);
  * `ESM-verify`: a repair is accepted only if a *blind* verifier agrees. The verifier is one 27B call that sees only the
    question and the re-anchored evidence outputs at the current commit, and must answer from them alone. Agreement is
    canonicalised answer equality. Otherwise the fact is re-derived.
  * `ESM-norepair` (changed ⇒ re-derive).
* **Choice rule, fixed now.** Take the policy with the lowest served-wrong % on S1. If another policy is within 0.5 pp of it,
  take the cheaper of the two (tokens per fact). The choice is frozen and used for every held-out "ESM" arm.
* **Answer check after re-derivation (option c).** On the dev 9B re-derivations, a static answer with no supporting line in
  the trace outputs is wrong 79 % of the time (144/183), against 38 % when a line supports it. For behaviour facts the
  signal is useless. I will measure the same statistic on the 27B re-derivations, at zero LLM cost. It becomes an arm only
  if it is still strongly predictive *and* the remedy is cheap. Otherwise it is reported as analysis only.
* **Budget:** about 2k 27B calls.

## Step 1 — s0 derivation (all 1,478 held-out facts)

* **Agent.** The 27B agent with the pilot3/pilot6 tool loop (≤ 12 tool calls), cached. A fact is kept iff its answer
  matches the oracle at s0 (canonicalised). The stored K is the agent's own answer string. The evidence is recorded from
  the agent's trace, and the citations are the zero-LLM `auto_cites` lines from that trace (no LLM citation step; this
  differs from the dev set).
* **Reported:** the success rate per type, slice, repo and subset.
* **Budget:** about 4.2 calls per fact, so about 6.2k calls (measured on the first 70 facts: 96 % correct, about 6k tokens
  per derivation).

## Step 2 — maintenance over the 400 FUTURE commits

* **Evidence state counts.** These are zero-LLM. On the first 77 kept facts, the anchored s0 evidence has 2.3 queries and
  5.2 distinct non-s0 states per fact (dev: about 13). The judge-call estimates below are therefore about 6–7 calls per
  fact, including screens.

**Subsets.**

* **ALL** = all kept facts (about 1.4k).
* **H150** = a stratified subset of about 160 kept facts, fixed by seed before any maintenance run:
  * 10 per repo;
  * in the 9 behaviour repos, 3 behaviour + 7 static;
  * about half enriched and half natural;
  * changing facts over-represented (about 60 %) wherever available, so that the subset contains real change episodes.

  Pooled rates on H150 are therefore not base rates. H150 is used for paired comparisons only.

**Read schedules.** `every` (400 reads), `every5` (80), `every20` (20), `bursty` (80 reads in bursts of 10, seed 7). Cost is
reported per fact and **per read**, as total evaluator plus re-derivation tokens divided by the number of reads.

**Arms and estimated 27B calls.**

| arm | facts | schedules | est. 27B calls |
|---|---|---|---|
| ESM (frozen) | ALL | every | ~7k judge + ~3k re-derivation + ~0.5k verify |
| ESM detection-only, pilot7 definitions (`DETECT-anchor-hier`) | ALL | every | ~2k extra (shares the a0 transitions with ESM) |
| ESM (frozen) | ALL | every5, every20, bursty | ~3k extra (mostly cache hits after detection-only) |
| pilot7 TRIAGE-a detector (`DETECT-p7a`) | H150 | every | ~1k |
| ablations: no anchoring, truncation, no repair / plain repair (whichever is not frozen), unsure-as-fresh | H150 | every | ~3k |
| 9B evaluator (`ESM-9B`), 9B deriver (`ESM-9Bderiver`) | H150 | every | remote 9B; 27B only for their re-derivations or judge calls |
| NEVER | ALL | all | 0 |
| ALWAYS (reads every 50), TTL50/100/200 + re-derive (every) | H150 | – | derivation grid t ∈ {50,…,400}: ≤ 1,280 derivations, ~5k |
| REPLAY / FILEHASH / ASTHASH / CITE / CERT-ZS / CERT-v0h + real 27B re-derivation | H150 | every, or every20 if the derivation count is too large (decided from the zero-LLM @oracle request counts) | ~5–8k |
| CERT-ZS extraction / CERT-v0h construction | H150 (v0h static only) | – | ~0.2k / ~1.3k |
| LLM-on-read-set-diff judge (`LLMDIFF`) + real re-derivation | H150 | every | ~1.5k |
| all flag baselines `@oracle` (oracle re-derivation, idealised, clearly labelled) | ALL | all | 0 (LLMDIFF@oracle: H150 only) |

**Totals.** The total is about 45k 27B calls. At about 22 calls/min that is about 34 h of GPU time, which is over budget once
analysis time is subtracted.

**Priority order** (lower items are cut first if time runs short; anything cut is listed in RESULTS.md):

1. s0
2. dev calibration
3. ESM every on ALL
4. H150 real-cost baselines (TTL/ALWAYS grid, REPLAY, FILEHASH, ASTHASH, CITE)
5. DETECT-anchor-hier on ALL
6. H150 ablations
7. ESM on sparse schedules
8. CERT-ZS, LLMDIFF
9. DETECT-p7a
10. CERT-v0h
11. 9B arms (remote, parallel; they do not compete for local GPUs except for 27B re-derivations)

## Step 3 — metrics and statistics

**Primary metric.** Served-wrong rate.

**Other metrics:**

* FF / FS, in two forms: maintenance definitions, and pilot7 detection-only definitions;
* stored-wrong episodes never acted on;
* lifetime kept, meaning the fraction of reads served without any action;
* repair correctness (proposed vs accepted);
* re-derivation accuracy over time;
* tokens per fact and per read;
* RDE, whose unit is the fact's own 27B s0 derivation tokens;
* cost–accuracy curves;
* per-fact severity.

**Splits:**

* pooled;
* per repo;
* without jinja;
* repo-weighted (each repo weight 1/16);
* subset (enriched / natural);
* slice (static / behaviour);
* type.

**Statistics.**

* Bootstrap 95 % CIs over facts (B = 1000).
* Paired differences (B = 2000) against the strongest baselines at matched cost. "Matched" means the closest real-cost
  baseline in tokens per fact, or a TTL interpolated in cost.

## Step 4 — error taxonomy

ESM's wrong-served reads are classified by cause, as in dev T7, plus a case for a change outside the recorded evidence. I
read 6–10 concrete examples by hand.

## Realised budget

This section is filled in at the end from `llm_ledger.jsonl`.

## Changes during execution (logged as they happen)

* **16:50, NONE instruction in the agent and verifier prompts.** The first 190 s0 derivations, plus 9 dev-calibration
  re-derivations, showed the 27B agent answering "the referent no longer exists" in prose (e.g. "_ViolinPlotter is not
  defined in …"), which the benchmark scores as wrong. On the held-out set, disappearance is the main kind of change: 138 of
  the 203 changing natural facts.
  * **Fix:** one sentence was added to the derivation agent's system prompt: "If what the question refers to does not exist
    at this commit …, call answer(value='NONE')". The same instruction was added to the blind verifier's prompt. The judge
    prompt is frozen and unchanged.
  * **Restart:** both the s0 run and the calibration were restarted from scratch with the new prompt. The superseded
    derivations are in `esm_data_heldout/superseded/`; their LLM calls (~1.3k) still count in the realised budget.
* **19:45, dev calibration finished; the frozen choice is `ESM-norepair`.** The rule was applied mechanically by
  `esm/scripts/freeze_choice.py`, and the full output is in `esm_data_heldout/frozen.json`. Served-wrong on dev S1 (86 facts,
  27B judge, 27B re-deriver):

  | policy | served-wrong | tokens per fact |
  |---|---|---|
  | `ESM-norepair` | 8.2 % [4.1, 12.8] | 42.5k |
  | `ESM-verify` | 8.9 % [4.9, 13.6] | 39.6k |
  | plain `ESM` | 12.4 % [7.6, 17.5] | 32.5k |

  `ESM-verify` is 0.74 pp above `ESM-norepair`, which is more than the 0.5 pp tie margin, so the lowest served-wrong wins.
  Every held-out "ESM" row therefore means **anchored evidence + hierarchical deltas + a "changed" or "unsure" verdict ⇒
  re-derivation by the 27B agent**.
  * **Ablations around it:** no anchoring, truncation, unsure-as-fresh, the 9B evaluator, the 9B deriver, n = 2
    self-consistency, plain repair (`ESM`) and verified repair (`ESM-verify`).
  * **Main run started early:** it started on the 820 facts already derived, and the remaining facts are merged when s0
    completes.
* **20:55, H150 drawn early.** H150 was drawn when 1,096 facts had been kept: s0 derivations proceed round-robin over
  repos in seeded random order, so these are a random ~74 % of the eventual kept set. Stratified by repo × slice × subset
  as planned, the draw is 160 facts:
  * 133 static and 27 behaviour;
  * 89 enriched and 71 natural;
  * 94 changing.

  It is frozen in `esm_data_heldout/sub_H150.json`.
* **Real-cost schedules for the baselines, decided from the zero-LLM @oracle request counts (batch 1, 801 facts).** At
  every commit the flag baselines ask for these re-derivations per fact:

  | baseline | re-derivations per fact |
  |---|---|
  | FILEHASH | 19.7 |
  | ASTHASH | 18.6 |
  | REPLAY | 7.1 |
  | TTL50 | 8 |

  On H150 the union would be about 4k derivations, too many. Decision:
  * **Shared 50-commit grid.** All flag baselines AND ESM are run with real 27B re-derivations on H150 at schedule
    `every50` (reads at t = 50, …, 400). Every re-derivation then falls on the shared grid of ≤ 8 points per fact, and
    ALWAYS = TTL50 = the grid.
  * **Every commit.** TTL50/100/200 (exactly the grid points), REPLAY, CERT-ZS and LLMDIFF also run with real
    re-derivations on H150 at every commit; REPLAY only if time permits.
  * **@oracle for the rest.** FILEHASH, ASTHASH and CITE at every commit appear only as @oracle (all facts).
* **CITE fix.** The held-out citations are zero-LLM `auto_cites` with no file, which made CITE silently fall back to
  FILEHASH. CITE now locates the cited lines in the trace's read-set files at s0. 80 % of facts get line citations; the
  rest fall back to FILEHASH. CITE@oracle was rerun.
* **22:50, s0 finished.** 1,419 of 1,478 facts are kept (96.0 %).
  * **Evidence.** 3.06 queries per fact. Distinct non-s0 evidence states per fact: 5.45 anchored, 6.99 original. In total
    there are 7,667 anchored transitions to judge at most.
  * **Main run, batch 2.** The main ESM run for the remaining 618 facts (batch 2) is queued in queue A and writes to
    `sim_b2/`, to be merged.
  * **9B secondary arm.** The 9B agent's s0 run on all 1,478 facts is done on the remote GPU. Its 9B grid derivations on H150
    are running.
* **23:55, re-prioritisation (no results lost; all LLM calls cached, derivations persisted).** The main arm was getting
  only about 1/3 of the GPU next to the 27B grid, the certificates and the 9B-deriver arm: 40/801 facts after 3.4 h. Measured
  rate: ~1.4k judge calls done out of an estimated ~9k, plus ~6k re-derivation calls.
  * **Main run restarted** as a single run on ALL with 8 request slots, H150 facts first.
  * **Queue B** (H150 baselines, ablations) runs alongside with 2 slots.
  * **27B grid:** stopped; queue B's every50 job derives its points on demand.
  * **9B arms (queue C):** postponed until the main arm has covered H150, so that they reuse its cached judge calls instead
    of duplicating them.
  * **Sparse schedules (every5 / every20 / bursty) for ESM are now H150 only.** At sparse reads ESM re-derives at different
    commits, which would cost about 8k extra calls on ALL. The @oracle baselines and NEVER cover ALL on all schedules.
  * **REPLAY with real re-derivation:** every50 and every20 on H150. It is not run at every commit (≈ 7 re-derivations per
    fact).
* **01:40 (10-04), budget re-plan.**
  * **Capacity.** At ~26 calls/min, about 33k 27B calls remain until ~23:00. The main arm, DETECT on ALL and the sparse
    H150 runs need ~15k; queue B gets the rest.
  * **Queue B, in priority order:**
    1. TTL100/200, CERT-ZS, LLMDIFF and CERT-v0h at every commit;
    2. the ablations: no anchoring, truncation, unsure-as-fresh, plain repair, verified repair;
    3. REPLAY at every commit;
    4. TTL50;
    5. the every50 sweep;
    6. DETECT-p7a and n = 2 self-consistency.
  * **Dropped:** FILEHASH / ASTHASH / CITE with real re-derivation at every20, and the no-anchor+truncation combination.
    Whatever does not finish is listed as skipped in RESULTS.md.
* **05:55, REPLAY with real re-derivation at every commit moved to the end of queue B** (it runs only if time remains).
  REPLAY, FILEHASH, ASTHASH, CITE, CERT-ZS, CERT-v0h, LLMDIFF, ALWAYS, TTL* and ESM are all compared with real 27B
  re-derivations in the every50 sweep on H150. That sweep is nearly free once the TTL50/TTL100 grid derivations exist.
* **12:45, main arm complete on all 1,419 facts at every commit.** It ran 45.5k s after the restart.
* **13:10, LLMDIFF at every commit stopped.** It had finished 20 of 160 facts in 2.4 h: it judges an ~8 KB read-set diff at
  every file change.
  * LLMDIFF with real re-derivation is now compared only in the every50 sweep.
  * TTL100/200 and CERT-ZS at every commit were finished and saved before the stop.
  * CERT-v0h at every commit was moved after TTL50.
* **15:20, DETECT-anchor-hier on ALL done.** ESM every20 / every5 / bursty on H150 were done by 15:45.
* **15:45, more parallel queues once the GPUs freed up.**
  * TTL50 and the every50 sweep moved to a parallel queue D.
  * REPLAY with real re-derivation at every commit on H150 is back in queue A, which is otherwise idle. Queue B keeps the
    ablations, CERT-v0h at every commit, and DETECT-p7a + n = 2.
* **18:35, REPLAY with real re-derivation at every commit restricted to H80R.** After 1 h 40 min the H150 run had finished
  20 of 160 facts (238 re-derivations), against about 1.3k needed. It was restarted on **H80R**: a seeded random half of
  H150 (`random.Random(80).sample`, chosen without looking at outcomes, stored in `sub_H80R.json`). All 238 re-derivations
  are reused from the cache. ESM is compared with it on exactly those 80 facts.
* **19:40, REPLAY at every commit extended to all of H150.** The H80R run finished in 40 min, so there was time for the
  other half; its 80 facts are reused from the cache. The H80R-only parquet is kept as
  `sim_REPLAY_every_H80R.parquet.bak`. LLMDIFF every50 and CERT-v0h at every commit finished. ESM n = 2 runs in parallel in
  queue D.
* **20:15, LLMDIFF at every commit restarted on H80R only** (it was too slow on H150); queue A, with a 23:00 cut-off.
* **18:45 (actual clock), queue A extended:** LLMDIFF at every commit on the full H150, then ESM-norepair@oracle (an idealised deriver) and the detection ablations DETECT-anchor-trunc and DETECT-noanchor-hier on H150. Earlier entries in this log after ~16:00 used estimated clock times that ran ahead by up to 2 h; ledger timestamps are authoritative.
* **20:48, all GPU work finished.** Stopped: the local Ollama servers 11595 and 11596 (`stop_ollama.ps1`), the remote
  Ollama (port 11597, killed by pid), the ssh tunnel and the job queues. Port 11434 was never touched.

## Realised budget (from `esm_data_heldout/llm_ledger.jsonl`; non-cached calls only)

| model | role | calls | prompt tokens | completion tokens |
|---|---|---|---|---|
| qwen3.6:27b | derivation agent (s0, re-derivations, grids) | 21,392 | 51.78M | 1.89M |
| qwen3.6:27b | ESM / DETECT judge (incl. screens; dev calibration included) | 20,583 | 26.42M | 0.91M |
| qwen3.6:27b | LLMDIFF judge | 3,992 | 8.51M | 0.17M |
| qwen3.6:27b | certificate construction (CERT-ZS, CERT-v0h) | 1,099 | 0.72M | 0.12M |
| qwen3.6:27b | repair verifier | 201 | 0.21M | 0.01M |
| **qwen3.6:27b total** | | **47,267** | **87.6M** | **3.11M** |
| qwen3.5:9b | derivation agent (s0 on all facts, H150 grid, 9B-deriver arm) | 13,400 | 35.86M | 1.34M |
| qwen3.5:9b | judge (9B detector, 9B-evaluator arm) | 1,818 | 2.09M | 0.07M |
| **qwen3.5:9b total** | | **15,218** | **38.0M** | **1.41M** |

**Planned vs realised.** The plan budgeted about 45k 27B calls; 47.3k were used, including about 1.3k superseded
s0/calibration calls made before the NONE instruction was added.

**Throughput.** 27B throughput was 24–29 calls per minute over two GPUs; the "≈ 30 calls/min" assumption held only for
short judge prompts.

**Wall-clock.** First call 10-03 16:02, last call 10-04 20:48: 28.8 h of LLM time inside the 36 h budget.

**Ledger integrity.** 5 ledger lines are unparseable: concurrent appends before the single-write fix at about 20:00 on 10-03.
