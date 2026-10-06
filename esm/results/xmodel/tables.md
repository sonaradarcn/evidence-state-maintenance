# Cross-model generalisation: generated tables (analyze.py; second model = nim:nvidia/nemotron-3-super-120b-a12b, reasoning_effort=default (NIM; reasoning on, not switched off), schedule = every)

## T0. s0 derivation on X120 (Qwen-27B solved all 120 by construction: X120 ⊂ Qwen-kept facts; Qwen on all 1,478 held-out facts: 96.0 %)

| split | facts | Nemotron-3-Super-120B correct % | wrong | no answer | Nemotron-3-Super-120B tokens/derivation | Nemotron-3-Super-120B tool calls | Qwen3.6-27B tokens/derivation (same facts) |
|---|---|---|---|---|---|---|---|
| all | 120 | 95.8 | 1 | 4 | 15.9k | 5.2 | 8.4k |
| static | 100 | 97.0 | 0 | 3 | 14.8k | 5.0 | 7.8k |
| behaviour | 20 | 90.0 | 1 | 1 | 21.7k | 6.5 | 11.6k |
| natural half | 60 | 98.3 | 1 | 0 | 14.2k | 5.1 | 6.6k |
| enriched half | 60 | 93.3 | 0 | 4 | 17.7k | 5.3 | 10.3k |
| type B | 20 | 90.0 | 1 | 1 | 21.7k | 6.5 | 11.6k |
| type T1 | 17 | 100.0 | 0 | 0 | 15.4k | 6.5 | 5.3k |
| type T2 | 19 | 100.0 | 0 | 0 | 14.1k | 4.7 | 7.6k |
| type T3 | 18 | 100.0 | 0 | 0 | 10.6k | 3.9 | 5.5k |
| type T4 | 8 | 100.0 | 0 | 0 | 6.8k | 2.6 | 2.5k |
| type T5 | 14 | 100.0 | 0 | 0 | 10.9k | 4.4 | 4.0k |
| type T6 | 7 | 71.4 | 0 | 2 | 44.5k | 9.9 | 39.5k |
| type T7 | 17 | 94.1 | 0 | 1 | 14.1k | 4.4 | 5.5k |

Common fact set for every comparison: **115 facts** (X120 facts the second model got right at s0; natural 59, enriched 56).

**Comparison set (all tables below): 30 facts** on which the second model's ESM, TTL100 and CERT-ZS runs all finished (natural 15, enriched 15). Arms that finished on fewer facts are marked (n=…); their paired comparisons use the facts both arms have.

## T1. Side by side on the same 30 facts (every; served-wrong % [fact CI] {repo-cluster CI}; B = 2000 cluster, 1000 fact)

| policy | Qwen3.6-27B: served-wrong % | Qwen3.6-27B: tokens/fact | Qwen3.6-27B: re-der./fact | Nemotron-3-Super-120B: served-wrong % | Nemotron-3-Super-120B: tokens/fact | Nemotron-3-Super-120B: re-der./fact | Nemotron-3-Super-120B: judge calls/fact |
|---|---|---|---|---|---|---|---|
| ESM (frozen) | 6.7 [0.0, 15.1] {0.0, 15.2} | 20.2k | 1.40 | 7.3 [1.2, 15.5] {1.0, 15.3} | 56.7k | 1.90 | 12.5 |
| NEVER | 29.2 [17.1, 41.9] {17.1, 42.6} | 0.0k | 0.00 | 29.2 [17.1, 41.9] {17.1, 42.6} | 0.0k | 0.00 | 0.0 |
| TTL100 + re-derive | 13.7 [6.9, 21.6] {6.6, 22.0} | 33.7k | 4.00 | 15.4 [8.5, 22.9] {8.5, 23.8} | 63.9k | 4.00 | 0.0 |
| CERT-ZS + re-derive (incl. extraction) | 5.4 [0.0, 13.0] {0.0, 13.4} | 34.7k | 3.97 | 8.8 [1.8, 17.3] {0.1, 20.0} | 67.7k | 3.67 | 0.0 |
| LLMDIFF + re-derive | 6.2 [0.3, 13.7] {0.7, 13.8} | 67.5k | 1.57 | 10.2 [2.8, 19.9] {3.3, 20.1} | 126.9k | 2.63 | 24.4 |
| REPLAY + re-derive | 6.2 [0.4, 13.6] {0.7, 14.1} | 118.3k | 9.00 | not run | not run | not run | not run |

Ranking by served-wrong (best first): Qwen3.6-27B: CERT-ZS < LLMDIFF < REPLAY < ESM-norepair < TTL100 < NEVER; Nemotron-3-Super-120B: ESM-norepair < CERT-ZS < LLMDIFF < TTL100 < NEVER.
Ranking by tokens/fact (cheapest first): Qwen3.6-27B: NEVER < ESM-norepair < TTL100 < CERT-ZS < LLMDIFF < REPLAY; Nemotron-3-Super-120B: NEVER < ESM-norepair < TTL100 < CERT-ZS < LLMDIFF.
Kendall τ between the two served-wrong rankings (5 policies): 0.60.


### T1c. LLM calls per fact (judge calls + agent turns of every re-derivation; CERT-ZS + 1 extraction) and the completion share of tokens

| policy | Qwen3.6-27B: calls/fact | Nemotron-3-Super-120B: calls/fact | facts |
|---|---|---|---|
| TTL100 + re-derive | 17.9 | 26.8 | 30 |
| CERT-ZS + re-derive (incl. extraction) | 18.9 | 25.8 | 30 |
| LLMDIFF + re-derive | 30.1 | 47.3 | 30 |
| ESM (frozen) | 13.5 | 26.7 | 30 |
## T2. Paired ESM − baseline on the same facts (pp; positive = ESM worse), non-inferiority, cost ratio B / ESM

NI at m: the one-sided 95 % upper bound of ESM − B (95th bootstrap percentile) is below m (fact / cluster bootstrap).

| model | baseline | facts | ESM % / B % | Δ pp [fact 95 %] {cluster 95 %} | one-sided 95 % upper bound fact / cluster | NI 0.5 / 1.0 / 1.5 / 2.0 pp (fact; cluster) | repos ESM better / tie / worse | tokens ESM / B | token ratio B/ESM [fact] {cluster} | LLM-call ratio B/ESM {cluster} |
|---|---|---|---|---|---|---|---|---|---|---|
| Qwen3.6-27B | NEVER | 30 | 6.7 / 29.2 | -22.54 [-34.44, -12.15] {-33.52, -12.89} | -13.51 / -14.36 | y/y · y/y · y/y · y/y | 10 / 4 / 0 | 20.2k / 0.0k | – | – |
| Qwen3.6-27B | TTL100 + re-derive | 30 | 6.7 / 13.7 | -6.97 [-11.99, -2.39] {-12.32, -2.02} | -3.12 / -2.87 | y/y · y/y · y/y · y/y | 9 / 4 / 1 | 20.2k / 33.7k | 1.67 [1.28, 2.49] {1.18, 2.75} | 1.32 {0.95, 2.02} |
| Qwen3.6-27B | CERT-ZS + re-derive (incl. extraction) | 30 | 6.7 / 5.4 | +1.27 [-0.05, +3.88] {-0.04, +4.65} | +3.86 / +3.99 | n/n · n/n · n/n · n/n | 1 / 12 / 1 | 20.2k / 34.7k | 1.71 [0.97, 2.68] {0.94, 2.47} | 1.40 {0.79, 2.10} |
| Qwen3.6-27B | LLMDIFF + re-derive | 30 | 6.7 / 6.2 | +0.50 [-2.67, +5.00] {-2.72, +5.20} | +4.08 / +3.89 | n/n · n/n · n/n · n/n | 3 / 10 / 1 | 20.2k / 67.5k | 3.34 [2.08, 5.00] {1.90, 5.21} | 2.23 {1.50, 3.21} |
| Qwen3.6-27B | REPLAY + re-derive | 30 | 6.7 / 6.2 | +0.47 [-0.93, +2.55] {-0.96, +2.90} | +2.31 / +2.34 | n/n · n/n · n/n · n/n | 2 / 11 / 1 | 20.2k / 118.3k | 5.85 [3.57, 8.39] {3.76, 7.52} | 4.47 {2.80, 5.83} |
| Nemotron-3-Super-120B | NEVER | 30 | 7.3 / 29.2 | -21.97 [-33.93, -11.39] {-31.34, -12.84} | -12.88 / -14.20 | y/y · y/y · y/y · y/y | 10 / 4 / 0 | 56.7k / 0.0k | – | – |
| Nemotron-3-Super-120B | TTL100 + re-derive | 30 | 7.3 / 15.4 | -8.09 [-12.06, -4.49] {-11.73, -5.00} | -5.10 / -5.45 | y/y · y/y · y/y · y/y | 11 / 3 / 0 | 56.7k / 63.9k | 1.13 [0.86, 1.67] {0.83, 1.66} | 1.00 {0.73, 1.49} |
| Nemotron-3-Super-120B | CERT-ZS + re-derive (incl. extraction) | 30 | 7.3 / 8.8 | -1.56 [-6.40, +1.62] {-6.37, +1.69} | +1.12 / +1.24 | n/n · n/n · y/y · y/y | 1 / 11 / 2 | 56.7k / 67.7k | 1.19 [0.48, 2.10] {0.42, 2.06} | 0.97 {0.34, 1.69} |
| Nemotron-3-Super-120B | LLMDIFF + re-derive | 30 | 7.3 / 10.2 | -2.93 [-7.43, -0.10] {-8.18, -0.02} | -0.18 / -0.09 | y/y · y/y · y/y · y/y | 4 / 10 / 0 | 56.7k / 126.9k | 2.24 [1.33, 3.75] {1.37, 3.65} | 1.77 {1.22, 2.60} |

### T2b. Direction check: does each paired effect and cost ratio have the same sign under both models?

| baseline | ESM − B, Qwen3.6-27B | ESM − B, Nemotron-3-Super-120B | direction (no significant opposite effects) | token ratio Qwen3.6-27B | token ratio Nemotron-3-Super-120B | both token ratios > 1 | LLM-call ratio Qwen3.6-27B / Nemotron-3-Super-120B |
|---|---|---|---|---|---|---|---|
| TTL100 + re-derive | ESM better* (-6.97) | ESM better* (-8.09) | consistent | 1.67 | 1.13 | yes | 1.32 / 1.00 |
| CERT-ZS + re-derive (incl. extraction) | n.s. (+1.27) | n.s. (-1.56) | consistent | 1.71 | 1.19 | yes | 1.40 / 0.97 |
| LLMDIFF + re-derive | n.s. (+0.50) | ESM better* (-2.93) | consistent | 3.34 | 2.24 | yes | 2.23 / 1.77 |

## T3. By half (natural / change-enriched): served-wrong % and tokens/fact

| policy | half | facts | Qwen3.6-27B % | Qwen3.6-27B tok/fact | Nemotron-3-Super-120B % | Nemotron-3-Super-120B tok/fact |
|---|---|---|---|---|---|---|
| ESM (frozen) | natural | 15 | 10.1 | 21.3k | 10.1 | 58.7k |
| ESM (frozen) | enriched | 15 | 3.4 | 19.2k | 4.5 | 54.6k |
| NEVER | natural | 15 | 28.9 | 0.0k | 28.9 | 0.0k |
| NEVER | enriched | 15 | 29.5 | 0.0k | 29.5 | 0.0k |
| TTL100 + re-derive | natural | 15 | 16.3 | 36.2k | 18.0 | 63.4k |
| TTL100 + re-derive | enriched | 15 | 11.1 | 31.2k | 12.8 | 64.4k |
| CERT-ZS + re-derive (incl. extraction) | natural | 15 | 10.1 | 20.0k | 14.3 | 37.5k |
| CERT-ZS + re-derive (incl. extraction) | enriched | 15 | 0.8 | 49.4k | 3.4 | 97.8k |
| LLMDIFF + re-derive | natural | 15 | 10.1 | 75.3k | 10.4 | 170.7k |
| LLMDIFF + re-derive | enriched | 15 | 2.4 | 59.7k | 10.1 | 83.0k |
| REPLAY + re-derive | natural | 15 | 10.5 | 117.2k | – | – |
| REPLAY + re-derive | enriched | 15 | 2.0 | 119.4k | – | – |

## T4. The 'wrong re-derivation gets anchored' phenomenon

| quantity | Qwen3.6-27B | Nemotron-3-Super-120B |
|---|---|---|
| ESM: wrong-served reads in episodes that start at a wrong re-derivation | 100.0 % (805/805) | 65.0 % (568/874) |
| re-derivations at t > 0 made by the compared arms (one per fact × commit), n | 403 | 280 |
|   correct % | 86.1 | 82.5 |
|   correct % when the truth differs from s0 | 71.4 (n=192) | 73.6 (n=125) |
|   correct % when the truth equals s0 | 99.5 (n=211) | 89.7 (n=155) |
|   correct % when the oracle is NONE | 61.0 (n=141) | 60.0 (n=75) |
|   no answer % | 2.0 | 7.1 |
|   tokens per re-derivation | 11.5k | 19.1k |

Repeat-error rate on consecutive re-derivation pairs (same fact, same policy): P(2nd wrong | 1st wrong) [identical answer string among wrong→wrong], and P(2nd wrong | 1st right) for contrast.

| policy | Qwen3.6-27B: pairs, P(w→w) [identical] | Qwen3.6-27B: P(r→w) | Nemotron-3-Super-120B: pairs, P(w→w) [identical] | Nemotron-3-Super-120B: P(r→w) |
|---|---|---|---|---|
| ESM (frozen) | 26, 100.0 % of 3 [3] | 4.3 % of 23 | 40, 100.0 % of 6 [5] | 5.9 % of 34 |
| TTL100 + re-derive | 90, 71.4 % of 7 [5] | 3.6 % of 83 | 90, 66.7 % of 9 [6] | 6.2 % of 81 |
| CERT-ZS + re-derive (incl. extraction) | 96, 0.0 % of 2 [0] | 3.2 % of 94 | 90, 80.0 % of 10 [8] | 5.0 % of 80 |
| LLMDIFF + re-derive | 29, 100.0 % of 4 [4] | 4.0 % of 25 | 61, 88.9 % of 18 [16] | 7.0 % of 43 |
| REPLAY + re-derive | 245, 87.2 % of 47 [41] | 4.0 % of 198 | 0, 0.0 % of 0 [0] | 0.0 % of 0 |
| **pooled** | 486, **84.1 %** of 63 [53] | 3.8 % | 281, **83.7 %** of 43 [35] | 5.9 % |

## T5. Transition judge, detection only (pilot7 definitions: stored answer = s0 K; per-commit FF / FS) on the same facts

| model | facts | FF % [CI] | FS % [CI] | static FF / FS | behaviour FF / FS | judge calls/fact |
|---|---|---|---|---|---|---|
| Qwen3.6-27B | 30 | 0.0 [0.0, 0.0] | 2.6 [0.0, 8.1] | 0.0 / 3.4 | 0.0 / 0.0 | 4.6 |
| Nemotron-3-Super-120B | 30 | 5.4 [0.0, 16.1] | 3.2 [0.7, 6.6] | 5.3 / 3.9 | 18.4 / 0.8 | 11.2 |

## T6. Where ESM's tokens go

| quantity | Qwen3.6-27B | Nemotron-3-Super-120B |
|---|---|---|
| judge tokens/fact | 6.6k | 20.0k |
| re-derivation tokens/fact | 13.6k | 36.7k |
| judge calls/fact | 6.00 | 12.47 |
| re-derivations/fact | 1.40 | 1.90 |
| RDE (unit: the fact's own s0 derivation of the same model) | 2.95 | 4.15 |
| needless-spend share | 56.5 % | 61.6 % |
| lifetime kept | 95.4 % | 83.6 % |
| FS (maintenance) | 0.1 % | 0.2 % |
| stored-wrong episodes never acted on | 0.0 % | 3.6 % |

## T7. Shared 50-commit grid (reads and re-derivations only at t = 50, 100, ..., 400)

Qwen every50 records: Stage 2 (H150 part of X120) + qwen_every50.py (the other X120 facts, Stage-2 cache + 24 new 27B judge calls). Rows are on the facts both models have.

| model | policy | facts | served-wrong % | tokens/fact | re-der./fact | Δ ESM − policy pp [fact] {cluster} | ratio policy/ESM |
|---|---|---|---|---|---|---|---|
| Qwen3.6-27B | ESM-norepair | 30 | 5.4 | 14.8k | 0.97 |  | 1.00 |
| Qwen3.6-27B | REPLAY | 30 | 6.7 | 39.0k | 3.37 | -1.25 [-3.33, +0.00] {-3.45, +0.00} | 2.64 |
| Qwen3.6-27B | NEVER | 30 | 32.5 | 0.0k | 0.00 | -27.08 [-40.42, -15.42] {-39.59, -15.81} | 0.00 |
| Nemotron-3-Super-120B | ESM-norepair | 30 | 8.8 | 33.0k | 1.17 |  | 1.00 |
| Nemotron-3-Super-120B | REPLAY | 30 | 12.9 | 87.0k | 5.03 | -4.17 [-9.58, +0.00] {-9.17, +0.00} | 2.63 |
| Nemotron-3-Super-120B | NEVER | 30 | 32.5 | 0.0k | 0.00 | -23.75 [-36.67, -12.91] {-34.26, -14.17} | 0.00 |