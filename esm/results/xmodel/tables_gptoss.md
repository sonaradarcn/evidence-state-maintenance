# Cross-model generalisation: generated tables (analyze.py; second model = ollama:gpt-oss:20b, reasoning_effort=medium, schedule = every)

## T0. s0 derivation on X120 (Qwen-27B solved all 120 by construction: X120 ⊂ Qwen-kept facts; Qwen on all 1,478 held-out facts: 96.0 %)

| split | facts | gpt-oss-20B correct % | wrong | no answer | gpt-oss-20B tokens/derivation | gpt-oss-20B tool calls | Qwen3.6-27B tokens/derivation (same facts) |
|---|---|---|---|---|---|---|---|
| all | 120 | 59.2 | 13 | 36 | 19.6k | 7.3 | 8.4k |
| static | 100 | 63.0 | 11 | 26 | 18.4k | 6.9 | 7.8k |
| behaviour | 20 | 40.0 | 2 | 10 | 25.3k | 9.3 | 11.6k |
| natural half | 60 | 58.3 | 5 | 20 | 19.6k | 7.4 | 6.6k |
| enriched half | 60 | 60.0 | 8 | 16 | 19.5k | 7.2 | 10.3k |
| type B | 20 | 40.0 | 2 | 10 | 25.3k | 9.3 | 11.6k |
| type T1 | 17 | 88.2 | 0 | 2 | 10.1k | 5.9 | 5.3k |
| type T2 | 19 | 42.1 | 2 | 9 | 27.3k | 8.9 | 7.6k |
| type T3 | 18 | 55.6 | 2 | 6 | 21.7k | 8.0 | 5.5k |
| type T4 | 8 | 100.0 | 0 | 0 | 3.8k | 2.2 | 2.5k |
| type T5 | 14 | 85.7 | 1 | 1 | 8.4k | 3.5 | 4.0k |
| type T6 | 7 | 28.6 | 3 | 2 | 34.9k | 9.6 | 39.5k |
| type T7 | 17 | 47.1 | 3 | 6 | 21.8k | 8.5 | 5.5k |

Common fact set for every comparison: **71 facts** (X120 facts the second model got right at s0; natural 35, enriched 36).

**Comparison set (all tables below): 71 facts** on which the second model's ESM, TTL100 and CERT-ZS runs all finished (natural 35, enriched 36). Arms that finished on fewer facts are marked (n=…); their paired comparisons use the facts both arms have.

## T1. Side by side on the same 71 facts (every; served-wrong % [fact CI] {repo-cluster CI}; B = 2000 cluster, 1000 fact)

| policy | Qwen3.6-27B: served-wrong % | Qwen3.6-27B: tokens/fact | Qwen3.6-27B: re-der./fact | gpt-oss-20B: served-wrong % | gpt-oss-20B: tokens/fact | gpt-oss-20B: re-der./fact | gpt-oss-20B: judge calls/fact |
|---|---|---|---|---|---|---|---|
| ESM (frozen) | 4.4 [1.4, 8.2] {1.6, 8.0} | 15.9k | 0.93 | 11.9 [7.1, 17.5] {7.3, 17.4} | 57.4k | 1.80 | 11.5 |
| NEVER | 24.3 [16.4, 32.5] {17.0, 32.8} | 0.0k | 0.00 | 24.3 [16.4, 32.5] {17.0, 32.8} | 0.0k | 0.00 | 0.0 |
| TTL100 + re-derive | 9.7 [6.2, 13.6] {6.8, 13.3} | 32.7k | 4.00 | 22.0 [16.5, 28.1] {16.3, 27.3} | 51.5k | 4.00 | 0.0 |
| CERT-ZS + re-derive (incl. extraction) | 3.9 [1.0, 7.2] {1.3, 7.3} | 29.2k | 3.32 | 14.0 [8.2, 20.3] {7.8, 20.6} | 70.6k | 4.37 | 0.0 |
| LLMDIFF + re-derive | 6.1 [2.6, 10.5] {2.8, 10.4} | 45.2k | 1.35 | 13.4 [7.6, 19.6] {7.3, 20.1} | 219.9k | 3.65 | 39.6 |
| REPLAY + re-derive | 5.1 [2.0, 8.5] {2.0, 8.9} | 89.7k | 6.48 | 20.2 [14.0, 26.4] {14.2, 25.7} | 211.1k | 13.04 | 0.0 |

Ranking by served-wrong (best first): Qwen3.6-27B: CERT-ZS < ESM-norepair < REPLAY < LLMDIFF < TTL100 < NEVER; gpt-oss-20B: ESM-norepair < LLMDIFF < CERT-ZS < REPLAY < TTL100 < NEVER.
Ranking by tokens/fact (cheapest first): Qwen3.6-27B: NEVER < ESM-norepair < CERT-ZS < TTL100 < LLMDIFF < REPLAY; gpt-oss-20B: NEVER < TTL100 < ESM-norepair < CERT-ZS < REPLAY < LLMDIFF.
Kendall τ between the two served-wrong rankings (6 policies): 0.60.

## T2. Paired ESM − baseline on the same facts (pp; positive = ESM worse), non-inferiority, cost ratio B / ESM

NI at m: the one-sided 95 % upper bound of ESM − B (95th bootstrap percentile) is below m (fact / cluster bootstrap).

| model | baseline | facts | ESM % / B % | Δ pp [fact 95 %] {cluster 95 %} | one-sided 95 % upper bound fact / cluster | NI 0.5 / 1.0 / 1.5 / 2.0 pp (fact; cluster) | repos ESM better / tie / worse | tokens ESM / B | ratio B/ESM [fact] {cluster} |
|---|---|---|---|---|---|---|---|---|---|
| Qwen3.6-27B | NEVER | 71 | 4.4 / 24.3 | -19.91 [-26.75, -12.82] {-28.32, -12.88} | -13.88 / -13.89 | y/y · y/y · y/y · y/y | 14 / 2 / 0 | 15.9k / 0.0k | – |
| Qwen3.6-27B | TTL100 + re-derive | 71 | 4.4 / 9.7 | -5.30 [-7.74, -2.94] {-8.39, -2.77} | -3.26 / -3.09 | y/y · y/y · y/y · y/y | 13 / 2 / 1 | 15.9k / 32.7k | 2.06 [1.68, 2.66] {1.55, 2.77} |
| Qwen3.6-27B | CERT-ZS + re-derive (incl. extraction) | 71 | 4.4 / 3.9 | +0.55 [+0.00, +1.64] {+0.00, +1.74} | +1.64 / +1.64 | n/n · n/n · n/n · y/y | 0 / 15 / 1 | 15.9k / 29.2k | 1.83 [1.26, 2.54] {1.22, 2.52} |
| Qwen3.6-27B | LLMDIFF + re-derive | 71 | 4.4 / 6.1 | -1.69 [-5.20, +1.08] {-5.00, +1.42} | +0.58 / +0.86 | n/n · y/y · y/y · y/y | 5 / 9 / 2 | 15.9k / 45.2k | 2.84 [2.14, 3.76] {2.08, 4.01} |
| Qwen3.6-27B | REPLAY + re-derive | 71 | 4.4 / 5.1 | -0.65 [-2.21, +0.74] {-2.02, +0.51} | +0.52 / +0.37 | n/y · y/y · y/y · y/y | 3 / 11 / 2 | 15.9k / 89.7k | 5.64 [3.85, 7.84] {4.23, 7.24} |
| gpt-oss-20B | NEVER | 71 | 11.9 / 24.3 | -12.43 [-19.65, -5.59] {-19.74, -5.47} | -6.46 / -6.60 | y/y · y/y · y/y · y/y | 13 / 1 / 2 | 57.4k / 0.0k | – |
| gpt-oss-20B | TTL100 + re-derive | 71 | 11.9 / 22.0 | -10.11 [-14.53, -5.72] {-14.42, -5.53} | -6.26 / -6.31 | y/y · y/y · y/y · y/y | 13 / 1 / 2 | 57.4k / 51.5k | 0.90 [0.70, 1.23] {0.65, 1.24} |
| gpt-oss-20B | CERT-ZS + re-derive (incl. extraction) | 71 | 11.9 / 14.0 | -2.06 [-6.11, +1.93] {-6.84, +2.36} | +1.32 / +1.88 | n/n · n/n · y/n · y/y | 6 / 3 / 7 | 57.4k / 70.6k | 1.23 [0.72, 1.95] {0.88, 1.71} |
| gpt-oss-20B | LLMDIFF + re-derive | 71 | 11.9 / 13.4 | -1.54 [-5.18, +1.57] {-5.07, +1.79} | +1.06 / +1.25 | n/n · n/n · y/y · y/y | 6 / 5 / 5 | 57.4k / 219.9k | 3.83 [2.17, 6.34] {2.06, 6.38} |
| gpt-oss-20B | REPLAY + re-derive | 71 | 11.9 / 20.2 | -8.33 [-12.95, -3.44] {-12.92, -3.32} | -4.21 / -4.17 | y/y · y/y · y/y · y/y | 13 / 1 / 2 | 57.4k / 211.1k | 3.68 [2.99, 4.65] {2.93, 4.80} |

### T2b. Direction check: does each paired effect and cost ratio have the same sign under both models?

| baseline | Δ pp Qwen3.6-27B | Δ pp gpt-oss-20B | same sign (or both n.s.) | ratio Qwen3.6-27B | ratio gpt-oss-20B | both ratios > 1 |
|---|---|---|---|---|---|---|
| TTL100 + re-derive | -5.30 | -10.11 | yes | 2.06 | 0.90 | no |
| CERT-ZS + re-derive (incl. extraction) | +0.55 | -2.06 | yes | 1.83 | 1.23 | yes |
| LLMDIFF + re-derive | -1.69 | -1.54 | yes | 2.84 | 3.83 | yes |
| REPLAY + re-derive | -0.65 | -8.33 | same point sign | 5.64 | 3.68 | yes |

## T3. By half (natural / change-enriched): served-wrong % and tokens/fact

| policy | half | facts | Qwen3.6-27B % | Qwen3.6-27B tok/fact | gpt-oss-20B % | gpt-oss-20B tok/fact |
|---|---|---|---|---|---|---|
| ESM (frozen) | natural | 35 | 3.6 | 10.9k | 8.9 | 40.8k |
| ESM (frozen) | enriched | 36 | 5.2 | 20.8k | 14.8 | 73.5k |
| NEVER | natural | 35 | 19.6 | 0.0k | 19.6 | 0.0k |
| NEVER | enriched | 36 | 28.9 | 0.0k | 28.9 | 0.0k |
| TTL100 + re-derive | natural | 35 | 7.1 | 26.1k | 22.0 | 49.9k |
| TTL100 + re-derive | enriched | 36 | 12.2 | 39.2k | 22.0 | 53.0k |
| CERT-ZS + re-derive (incl. extraction) | natural | 35 | 3.6 | 19.6k | 16.7 | 68.8k |
| CERT-ZS + re-derive (incl. extraction) | enriched | 36 | 4.1 | 38.5k | 11.2 | 72.4k |
| LLMDIFF + re-derive | natural | 35 | 6.2 | 37.8k | 12.1 | 204.9k |
| LLMDIFF + re-derive | enriched | 36 | 6.0 | 52.4k | 14.7 | 234.4k |
| REPLAY + re-derive | natural | 35 | 3.6 | 38.1k | 20.4 | 148.7k |
| REPLAY + re-derive | enriched | 36 | 6.5 | 139.9k | 20.1 | 271.8k |

## T4. The 'wrong re-derivation gets anchored' phenomenon

| quantity | Qwen3.6-27B | gpt-oss-20B |
|---|---|---|
| ESM: wrong-served reads in episodes that start at a wrong re-derivation | 83.7 % (1050/1254) | 96.3 % (3256/3380) |
| re-derivations at t > 0 made by the compared arms (one per fact × commit), n | 810 | 1357 |
|   correct % | 92.1 | 68.6 |
|   correct % when the truth differs from s0 | 81.2 (n=292) | 55.5 (n=434) |
|   correct % when the truth equals s0 | 98.3 (n=518) | 74.8 (n=923) |
|   correct % when the oracle is NONE | 69.8 (n=182) | 39.4 (n=289) |
|   no answer % | 2.0 | 25.6 |
|   tokens per re-derivation | 11.0k | 17.6k |

Repeat-error rate on consecutive re-derivation pairs (same fact, same policy): P(2nd wrong | 1st wrong) [identical answer string among wrong→wrong], and P(2nd wrong | 1st right) for contrast.

| policy | Qwen3.6-27B: pairs, P(w→w) [identical] | Qwen3.6-27B: P(r→w) | gpt-oss-20B: pairs, P(w→w) [identical] | gpt-oss-20B: P(r→w) |
|---|---|---|---|---|
| ESM (frozen) | 29, 100.0 % of 2 [2] | 3.7 % of 27 | 86, 78.3 % of 46 [25] | 20.0 % of 40 |
| TTL100 + re-derive | 213, 77.8 % of 9 [7] | 3.9 % of 204 | 213, 70.8 % of 48 [28] | 12.7 % of 165 |
| CERT-ZS + re-derive (incl. extraction) | 184, 71.4 % of 7 [5] | 2.3 % of 177 | 260, 74.2 % of 62 [28] | 10.1 % of 198 |
| LLMDIFF + re-derive | 60, 60.0 % of 5 [3] | 5.5 % of 55 | 223, 92.0 % of 150 [135] | 17.8 % of 73 |
| REPLAY + re-derive | 403, 70.5 % of 44 [31] | 5.0 % of 359 | 866, 68.7 % of 214 [111] | 12.0 % of 652 |
| **pooled** | 889, **71.6 %** of 67 [48] | 4.1 % | 1648, **77.1 %** of 520 [327] | 12.4 % |

## T5. Transition judge, detection only (pilot7 definitions: stored answer = s0 K; per-commit FF / FS) on the same facts

| model | facts | FF % [CI] | FS % [CI] | static FF / FS | behaviour FF / FS | judge calls/fact |
|---|---|---|---|---|---|---|
| Qwen3.6-27B | 71 | 3.0 [0.0, 10.7] | 4.1 [0.9, 8.7] | 3.1 / 4.7 | 0.0 / 0.0 | 4.5 |
| gpt-oss-20B | 71 | 6.6 [1.0, 14.8] | 7.2 [3.2, 12.7] | 5.5 / 6.2 | 24.7 / 13.8 | 12.0 |

## T6. Where ESM's tokens go

| quantity | Qwen3.6-27B | gpt-oss-20B |
|---|---|---|
| judge tokens/fact | 5.8k | 20.4k |
| re-derivation tokens/fact | 10.1k | 37.0k |
| judge calls/fact | 5.18 | 11.48 |
| re-derivations/fact | 0.93 | 1.80 |
| RDE (unit: the fact's own s0 derivation of the same model) | 2.34 | 5.19 |
| needless-spend share | 53.7 % | 43.4 % |
| lifetime kept | 93.8 % | 80.5 % |
| FS (maintenance) | 0.1 % | 0.2 % |
| stored-wrong episodes never acted on | 2.3 % | 3.8 % |

## T7. Shared 50-commit grid (reads and re-derivations only at t = 50, 100, ..., 400)

Qwen every50 records: Stage 2 (H150 part of X120) + qwen_every50.py (the other X120 facts, Stage-2 cache + 24 new 27B judge calls). Rows are on the facts both models have.

| model | policy | facts | served-wrong % | tokens/fact | re-der./fact | Δ ESM − policy pp [fact] {cluster} | ratio policy/ESM |
|---|---|---|---|---|---|---|---|
| Qwen3.6-27B | ESM-norepair | 71 | 4.0 | 10.8k | 0.70 |  | 1.00 |
| Qwen3.6-27B | REPLAY | 71 | 5.3 | 35.1k | 2.94 | -1.23 [-2.46, -0.18] {-2.57, -0.18} | 3.25 |
| Qwen3.6-27B | NEVER | 71 | 26.8 | 0.0k | 0.00 | -22.71 [-30.46, -14.96] {-31.17, -15.25} | 0.00 |
| gpt-oss-20B | ESM-norepair | 71 | 12.0 | 24.6k | 0.89 |  | 1.00 |
| gpt-oss-20B | REPLAY | 71 | 22.7 | 68.3k | 4.39 | -10.74 [-15.67, -5.81] {-15.92, -4.88} | 2.78 |