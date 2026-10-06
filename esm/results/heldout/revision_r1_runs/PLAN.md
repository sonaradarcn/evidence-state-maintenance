# Reviewer round 1: supplementary held-out runs — plan and LLM budget

*Lab notebook, kept as written during the runs: the plan fixed before the first run, followed by the timestamped decision log. Server ports, hardware incidents and deviations are recorded as they happened; the final numbers are in RESULTS.md.*

Written 2026-10-05 12:35, before any LLM call of this stage. Time budget ≈ 14 h (12:30 → ≈ 02:30 on 10-06); the LLM work
gets a hard stop at ≈ 00:30 (no new fact started after that; `run_sim --deadline`), the rest is analysis and writing.

Requests: `reviews/paper_r1_summary.md` major issues 4 (Experiment A) and 3 (Experiment B); analysis-only precursors in
`esm/results/heldout/revision_r1/REVISION_ANALYSES.md` items 6 and 3/2.

## Infrastructure (as in the held-out stage, `../PLAN.md`)

* Own Ollama servers 11595 (GPU0) and 11596 (GPU1), qwen3.6:27b, thinking off, T = 0, ctx 16k; 11434 is never touched;
  both stopped at the end (`esm/scripts/stop_ollama.ps1`).
* `ESM_DATA = esm_data_heldout` (same LLM cache, ledger and derivation store as the held-out stage, so every
  identical call is a cache hit). New simulation outputs go to `esm_data_heldout\sim_r1\` (the frozen held-out
  `sim\` parquets are not touched). Results and scripts: this folder.
* Two persistent job queues (`esm.scripts.jobqueue`): `queue_R1A` (Experiment A) and `queue_R1B` (Experiment B), each
  with 2 request slots per GPU. I poll explicitly from the shell (ledger rate, `.done` files, logs), at most every ~30 min.
* Code change: `esm/maintain.py` gains `ESMConfig.expiry` / `expiry_mode` (defaults off). Regression check before any
  run: the modified `simulate_esm` reproduces the stored `ESM-norepair` every-commit records exactly (25 H150 facts,
  offline, all fields compared: 0 differences).

## Experiment A — ESM + anchor expiry (major issue 4), H150 (160 facts), every commit

* **Base policy** = the frozen `ESM-norepair` (27B judge, 27B deriver, anchored + hierarchical, changed/unsure ⇒
  re-derive).
* **Expiry rule** (`ESM-norepair-exp{N}`, N ∈ {50, 100, 200}): at the first read at which the current anchor is ≥ N
  commits old, the 27B agent re-derives *before* the evidence check (s0 is the anchor at t = 0; every re-derivation,
  forced or ESM-triggered, is a new anchor and resets the age). The forced re-derivation goes through the same
  `DerivStore` (memoised per (fact, t)), so it is the same agent, prompt and T = 0 as every other re-derivation.
* **Forced outcome handling (defined now):**
  * an answer (any non-empty string, *including* `NONE`, which is the benchmark's legitimate "referent gone" answer and
    exactly the answer the item-6 failure needs) is adopted: K := answer, evidence re-recorded from the new trace,
    age reset;
  * **fallback** — the forced re-derivation returns no answer (None / empty: 12-call limit, server parse error) or raises:
    the previous answer **and** its evidence anchor are kept, the answer is marked *unverified* (`verified = 0` on every
    read it is served while unverified), and the age clock restarts at t (next attempt at t + N). Reported: number of
    fallbacks and unverified reads, and how many of them were wrong.
* **Optional variant** (`ESM-norepair-expS{N}`): expiry only for *NONE-suspicious* anchors, a zero-oracle rule: an
  ESM-triggered re-derivation that returned no answer, or returned a value other than `NONE` although the judge verdict
  that triggered it said the referent disappeared (regex on the verdict reason: removed / moved / renamed / no longer /
  not found / missing / does not exist …). A forced answer that is again a non-`NONE` value stays suspicious (retried
  every N); `NONE` clears it. s0 anchors are never suspicious.
* **Reported** (paired vs frozen ESM on the same 160 facts; fact and repo-cluster bootstrap, B = 2000): served-wrong,
  FF / FS (maintenance definitions; forced reads count as acted-on), stored-wrong episodes never acted on, tokens/fact,
  RDE (re-derivation-equivalents), forced re-derivations/fact and how many were right, wrong anchored episodes removed /
  introduced; compared with the item-6 estimates (A / B / C).

## Experiment B — strong baselines on a natural random sample (major issue 3)

* **Sample NAT100** drawn at 12:30, *before* any outcome of it was looked at: `random.Random(20261005).sample` of the
  sorted ids of the 715 kept NATURAL facts, 100 facts (`draw_nat100.py`, `draw_nat100.json`, population hash recorded;
  `esm_data_heldout/sub_NAT100.json`). Composition (not outcomes): 92 static / 8 behaviour; all 16 repos (3–10 facts
  each); 11 facts overlap H150.
* **Arms, every commit, real 27B re-derivations:** ESM-norepair (frozen; its ALL-run records are reused — re-simulated
  offline, all calls cached), NEVER, TTL100, CERT-ZS (incl. extraction tokens), CERT-v0h (static facts only, incl.
  construction tokens), LLMDIFF, REPLAY (only if it fits; otherwise REPLAY on the shared 50-commit grid, with ESM on
  the same grid).
* **Reported:** served-wrong, tokens/fact, paired ESM − B with fact and repo-cluster bootstrap CIs, non-inferiority /
  TOST at 1.5 pp exactly as REVISION_ANALYSES item 2 (one-sided 95 % upper bound < 1.5 pp; 90 % CI inside ±1.5 pp),
  cost ratios B/ESM with cluster CIs, compared with the H150 ratios (2.00 CERT-ZS, 1.09 CERT-v0h, 2.72 LLMDIFF, 6.12
  REPLAY, 1.66 TTL100) and the item-3 re-weighted estimates.

## LLM budget (27B calls; estimates from zero-LLM counts)

| item | basis of the estimate | est. new 27B calls |
|---|---|---|
| A: forced re-derivations, N = 50 / 100 / 200 | item 6: 7.1 / 3.2 / 1.3 forced per fact on H150, 69–80 % already in the derivation store → ≈ 450 new derivations × ≈ 4.5 calls | ≈ 2.0k |
| A: judge calls on the new anchors | ESM: 7.8 judge calls/fact with 1.3 anchors/fact; ≈ 2–3× more anchors (shared across N where forced commits coincide) | ≈ 4–6k |
| A: expS variants | few suspicious anchors (≤ 0.3 per fact) | ≈ 0.3k |
| B: certificates (CERT-ZS 89 new, CERT-v0h ≈ 82 new static facts × ≈ 7) | held-out stage costs | ≈ 0.7k |
| B: TTL100 | 400 grid derivations, 44 already stored → 356 new | ≈ 1.6k |
| B: CERT-ZS / CERT-v0h re-derivations | H150: 4.6 / 2.3 per fact, lower on natural facts | ≈ 1.1k + 0.7k |
| B: LLMDIFF | H150 ≈ 25 judge calls + 2 re-derivations per fact | ≈ 2.5k + 0.9k |
| B: REPLAY at every commit | REPLAY@oracle on NAT100: 754 re-derivations, 113 stored → ≈ 640 new | ≈ 2.9k |
| B: ESM-norepair, NEVER | cached / zero LLM | 0 |
| **total** | | **≈ 17–19k** |

At the measured 24–29 calls/min this is ≈ 11–13 h, i.e. at or slightly over the ≈ 11.5 h of GPU time available.
**Priority (cut from the bottom):** (1) A: exp100, exp200; (2) B: certificates, TTL100, CERT-ZS, CERT-v0h; (3) A:
exp50; (4) B: LLMDIFF; (5) A: expS50/100/200; (6) B: REPLAY at every commit, with REPLAY on the shared every50 grid as
the fallback. Long arms run in a seeded random fact order with `--deadline`, so a cut arm is a random subsample and is
reported as such. Everything skipped or cut is listed in RESULTS.md.

## Changes during execution (logged as they happen)
* **12:33, both queues started** (servers 11595 / 11596 started 12:31). Offline ESM-norepair + NEVER on NAT100 done at
  12:34 (100/100 facts, every call a cache hit).
* **13:17, certificates for NAT100 done** (CERT-ZS 100, CERT-v0h for the 92 static facts; 0 errors; 43 min — slower
  than the 0.7k-call estimate because of CERT-v0h's sufficiency calls).
* **13:40, rebalancing.** Experiment A runs far below its budget (exp200 done in 19 min, exp100 in 23 min: most forced
  re-derivations fall on grid commits already in the derivation store, and judge calls are mostly cache hits), so
  LLMDIFF on NAT100 was moved from queue B to the end of queue A (after the expS variants). Queue B keeps TTL100,
  CERT-ZS, CERT-v0h, then REPLAY at every commit. Nothing else changed.
* **14:00–16:26, Experiment B.** CERT-ZS done 14:51; CERT-v0h 15:08 (8 behaviour facts not applicable, by design);
  LLMDIFF 16:08; REPLAY at every commit 16:26 (it fit, so the every50 fallback was not needed). All arms complete
  (100/100 facts; 92 static for CERT-v0h), 0 errors otherwise; no `--deadline` was reached.
* **≈ 16:40, all GPU work finished.** Job queues and Ollama 11595 / 11596 stopped (`stop_ollama.ps1`); 11434 never
  touched. Realised: 6,044 non-cached 27B calls (11.26M prompt + 0.39M completion tokens), far below the 17–19k
  estimate because most forced re-derivations and judge prompts were cache hits. Results: `RESULTS.md`.
