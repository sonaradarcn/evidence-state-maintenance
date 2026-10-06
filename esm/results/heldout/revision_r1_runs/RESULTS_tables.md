# Reviewer round 1 — supplementary runs: generated tables (analyze.py)

## A. Frozen ESM + anchor expiry (H150, every commit, real 27B re-derivations)

| policy | facts | served-wrong % [fact CI] {cluster CI} | FF % | FS % | stored-wrong episodes never acted on % | tokens/fact | RDE | re-derivations/fact (forced) | forced right % | fallbacks (unverified reads, of which wrong) | judge calls/fact | judge / re-derivation tokens per fact |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| frozen ESM (no expiry) | 160 | 6.9 [4.1, 9.8] {3.4, 11.2} | 96.3 | 0.1 | 3.4 (5/146) | 26.5k | 2.83 | 1.31 (0.00) |  | 0 (0, 0) | 7.8 | 9.3k / 17.3k |
| + expiry, every anchor, N = 200 | 160 | 6.9 [4.3, 9.8] {3.5, 11.0} | 96.1 | 0.4 | 3.4 (5/148) | 37.1k | 3.96 | 2.54 (1.24) | 94.0 | 2 (43, 0) | 7.7 | 8.4k / 28.7k |
| + expiry, every anchor, N = 100 | 160 | 7.2 [4.6, 10.2] {3.7, 11.4} | 95.9 | 0.9 | 3.9 (6/152) | 58.6k | 6.25 | 4.54 (3.21) | 93.8 | 8 (476, 153) | 7.7 | 7.7k / 50.9k |
| + expiry, every anchor, N = 50 | 160 | 7.3 [4.5, 10.5] {3.9, 11.4} | 94.9 | 1.9 | 2.6 (4/156) | 99.6k | 10.62 | 8.47 (7.16) | 93.2 | 18 (776, 271) | 7.8 | 7.5k / 92.1k |
| + expiry, NONE-suspicious anchors only, N = 200 | 160 | 6.8 [3.9, 9.8] {3.4, 11.0} | 96.3 | 0.1 | 4.1 (6/147) | 27.8k | 2.97 | 1.41 (0.11) | 94.1 | 0 (0, 0) | 7.8 | 9.1k / 18.7k |
| + expiry, NONE-suspicious anchors only, N = 100 | 160 | 6.7 [4.2, 9.7] {3.2, 10.9} | 96.0 | 0.1 | 4.1 (6/147) | 31.8k | 3.39 | 1.62 (0.31) | 81.6 | 3 (153, 153) | 7.8 | 9.0k / 22.8k |
| + expiry, NONE-suspicious anchors only, N = 50 | 160 | 6.5 [4.0, 9.4] {3.2, 10.7} | 95.5 | 0.2 | 4.1 (6/147) | 39.9k | 4.25 | 2.06 (0.74) | 77.1 | 8 (353, 271) | 7.8 | 9.0k / 30.9k |

### A2. Paired against the frozen ESM (same facts; Δ = hybrid − frozen ESM)

| policy | facts | Δ served-wrong pp [fact CI] {cluster CI} | repos better / tie / worse (hybrid lower = better) | Δ tokens/fact [cluster CI] | ESM-wrong reads fixed | ESM-right reads broken | anchored-wrong reads of frozen ESM removed | forced: wrong→right / right→wrong / wrong→wrong | wrong→wrong with the identical answer string |
|---|---|---|---|---|---|---|---|---|---|
| + expiry, every anchor, N = 200 | 160 | -0.02 [-0.88, +0.73] {-0.75, +0.67} | 2 / 11 / 3 | +10.6k [+8.7, +12.2] | 252 | 237 | 52 / 3993 (1.3 %) | 2 / 5 / 7 | 7 |
| + expiry, every anchor, N = 100 | 160 | +0.31 [-0.72, +1.32] {-0.77, +1.28} | 3 / 8 / 5 | +32.0k [+26.5, +37.9] | 352 | 553 | 152 / 3993 (3.8 %) | 7 / 7 / 25 | 22 |
| + expiry, every anchor, N = 50 | 160 | +0.42 [-0.76, +1.63] {-0.63, +1.49} | 4 / 7 / 5 | +73.1k [+60.4, +86.5] | 432 | 698 | 232 / 3993 (5.8 %) | 10 / 10 / 68 | 62 |
| + expiry, NONE-suspicious anchors only, N = 200 | 160 | -0.08 [-0.24, +0.00] {-0.24, +0.00} | 1 / 15 / 0 | +1.3k [+0.6, +2.1] | 52 | 0 | 52 / 3993 (1.3 %) | 1 / 0 / 1 | 1 |
| + expiry, NONE-suspicious anchors only, N = 100 | 160 | -0.24 [-0.63, +0.00] {-0.62, +0.00} | 2 / 14 / 0 | +5.3k [+3.1, +7.7] | 152 | 0 | 152 / 3993 (3.8 %) | 2 / 0 / 9 | 6 |
| + expiry, NONE-suspicious anchors only, N = 50 | 160 | -0.37 [-0.83, +0.00] {-0.77, +0.00} | 3 / 13 / 0 | +13.3k [+8.2, +18.9] | 234 | 0 | 234 / 3993 (5.9 %) | 3 / 0 / 27 | 21 |

### A3. Real run vs the item-6 first-order estimates (H150, every anchor expires)

| N | frozen ESM % | real hybrid % (facts run) | estimate A / B / C % | real forced re-der./fact | estimated forced/fact | real extra tokens/fact | estimated extra (re-derivation only) |
|---|---|---|---|---|---|---|---|
| 50 | 6.9 | 7.3 (160) | 8.0 / 8.1 / 8.7 | 7.16 | 7.13 | +73.1k | +100k |
| 100 | 6.9 | 7.2 (160) | 7.9 / 7.8 / 8.1 | 3.21 | 3.21 | +32.0k | +45k |
| 200 | 6.9 | 6.9 (160) | 7.2 / 7.2 / 7.3 | 1.24 | 1.26 | +10.6k | +18k |

Suspicious-only variant vs item-6 'expiry of re-derived anchors only' (closest analogue; expS restricts further to NONE-suspicious re-derived anchors):

| N | real expS hybrid % | frozen % | estimate (re-derived anchors only) A / B / C % |
|---|---|---|---|
| 50 | 6.5 (160 facts) | 6.9 | 7.1 / 7.2 / 7.8 |
| 100 | 6.7 (160 facts) | 6.9 | 7.4 / 7.3 / 7.6 |
| 200 | 6.8 (160 facts) | 6.9 | 7.2 / 7.2 / 7.2 |

### A4. The NONE-suspicious rule on the frozen arm's 27B re-derivations (H150, every commit)

* re-derivations: 209; wrong: 48 (oracle NONE at 41 of them).
* flagged suspicious: 61 — 25 of the 48 wrong ones (52.1 % recall) and 36 of the 161 right ones (precision 41.0 %).
* wrong re-derivations with oracle NONE that the rule flags: 21 of 41.

## B. Strong baselines on NAT100 (100 natural facts, seeded uniform draw; every commit, real 27B re-derivations)

| policy | facts | served-wrong % [fact CI] {cluster CI} | FF % | FS % | episodes never acted on % | tokens/fact | re-derivations/fact | LLM judge calls/fact |
|---|---|---|---|---|---|---|---|---|
| ESM (frozen) | 100 | 5.5 [2.3, 9.3] {1.7, 10.9} | 98.2 | 0.1 | 5.7 | 15.4k | 0.65 | 6.1 |
| NEVER | 100 | 14.4 [8.9, 20.4] {6.7, 23.0} | 100.0 | 0.0 | 100.0 | 0.0k | 0.00 | 0.0 |
| TTL100 | 100 | 7.7 [4.2, 11.6] {3.7, 13.1} | 98.6 | 1.0 | 6.9 | 29.5k | 4.00 | 0.0 |
| CERT-ZS (incl. extraction) | 100 | 5.5 [2.2, 9.4] {1.7, 10.9} | 97.9 | 1.0 | 5.6 | 34.9k | 4.42 | 0.0 |
| CERT-v0h (static only, incl. construction) | 92 | 5.9 [2.6, 10.0] {1.6, 12.6} | 97.0 | 0.3 | 3.0 | 17.0k | 1.73 | 0.0 |
| LLMDIFF | 100 | 6.4 [2.8, 10.3] {2.4, 11.9} | 98.3 | 0.3 | 11.8 | 57.3k | 1.48 | 20.3 |
| REPLAY | 100 | 5.6 [2.5, 9.6] {1.8, 11.1} | 93.1 | 1.9 | 0.0 | 92.6k | 8.90 | 0.0 |

Representativeness: frozen ESM on all 715 natural facts = 5.6 % at 23.0k tokens/fact; on NAT100 = 5.5 % at 15.4k (fact-bootstrap 95 % CI of the sample's tokens/fact [11.2, 19.7]k). Changing facts: 24/100 in NAT100 vs 198/715 = 28 % in the population.

### B2. Paired ESM − baseline (pp; positive = ESM worse), non-inferiority / TOST, cost ratio

| comparison | facts | ESM % / B % | Δ [95 % fact CI] | 95 % cluster CI | 90 % CI fact / cluster | one-sided 95 % upper bound fact / cluster | NI at 1.5 pp (fact / cluster) | EQ ±1.5 pp (fact / cluster) | ESM / B tokens per fact | ratio B/ESM [fact CI] {cluster CI} | repos ESM better / tie / worse |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ESM − NEVER | 100 | 5.5 / 14.4 | -8.89 [-14.22, -4.33] | [-17.07, -2.50] | [-13.17, -5.01] / [-15.41, -3.08] | -5.01 / -3.08 | yes / yes | no / no | 15.4k / 0.0k | 0.00 [0.00, 0.00] {0.00, 0.00} | 8 / 8 / 0 |
| ESM − TTL100 | 100 | 5.5 / 7.7 | -2.22 [-3.62, -0.99] | [-3.65, -0.93] | [-3.39, -1.16] / [-3.41, -1.11] | -1.16 / -1.11 | yes / yes | no / no | 15.4k / 29.5k | 1.91 [1.55, 2.50] {1.37, 2.89} | 8 / 8 / 0 |
| ESM − CERT-ZS (incl. extraction) | 100 | 5.5 / 5.5 | -0.03 [-0.10, +0.00] | [-0.09, +0.00] | [-0.10, +0.00] / [-0.09, +0.00] | +0.00 / +0.00 | yes / yes | yes / yes | 15.4k / 34.9k | 2.26 [1.51, 3.40] {1.31, 3.40} | 1 / 15 / 0 |
| ESM − CERT-v0h (static only, incl. construction) | 92 | 5.9 / 5.9 | +0.00 [+0.00, +0.00] | [+0.00, +0.00] | [+0.00, +0.00] / [+0.00, +0.00] | +0.00 / +0.00 | yes / yes | yes / yes | 14.7k / 17.0k | 1.15 [0.73, 1.87] {0.79, 1.79} | 0 / 16 / 0 |
| ESM − LLMDIFF | 100 | 5.5 / 6.4 | -0.91 [-2.65, +0.00] | [-2.86, +0.00] | [-2.57, +0.00] / [-2.60, +0.00] | +0.00 / +0.00 | yes / yes | no / no | 15.4k / 57.3k | 3.72 [3.04, 4.59] {2.72, 4.96} | 2 / 14 / 0 |
| ESM − REPLAY | 100 | 5.5 / 5.6 | -0.13 [-0.32, +0.00] | [-0.32, +0.00] | [-0.28, -0.03] / [-0.28, +0.00] | -0.03 / +0.00 | yes / yes | yes / yes | 15.4k / 92.6k | 6.01 [4.56, 7.68] {3.79, 8.53} | 2 / 14 / 0 |

### B3. Cost ratio B / ESM: natural sample vs the change-enriched H150 subset

| baseline | NAT100 ratio [cluster CI] | H150 ratio (measured, every commit) | item-3 re-weighted estimate (type × changing / churn × jinja) | Δ served-wrong pp NAT100 | Δ served-wrong pp H150 |
|---|---|---|---|---|---|
| TTL100 | 1.91 {1.37, 2.89} | 1.66 (160 facts) | 2.06 / 2.02 | -2.2 | -7.7 |
| CERT-ZS | 2.26 {1.31, 3.40} | 2.00 (160 facts) | 2.85 / 2.01 | -0.0 | -0.2 |
| CERT-v0h | 1.15 {0.79, 1.79} | 1.09 (133 facts) | 1.45 / – | +0.0 | -0.3 |
| LLMDIFF | 3.72 {2.72, 4.96} | 2.72 (160 facts) | 3.63 / 2.96 | -0.9 | -1.2 |
| REPLAY | 6.01 {3.79, 8.53} | 6.12 (160 facts) | 6.28 / 6.98 | -0.1 | -1.6 |

### B4. Tokens per fact within NAT100, changing vs non-changing facts

| policy | changing facts: n, tokens/fact, served-wrong % | non-changing facts: n, tokens/fact, served-wrong % |
|---|---|---|
| ESM (frozen) | 24, 33.9k, 22.8 | 76, 9.6k, 0.0 |
| NEVER | 24, 0.0k, 59.9 | 76, 0.0k, 0.0 |
| TTL100 | 24, 37.7k, 32.1 | 76, 26.9k, 0.0 |
| CERT-ZS (incl. extraction) | 24, 33.4k, 22.8 | 76, 35.4k, 0.0 |
| CERT-v0h (static only, incl. construction) | 22, 40.0k, 24.8 | 70, 9.7k, 0.0 |
| LLMDIFF | 24, 93.7k, 26.6 | 76, 45.8k, 0.0 |
| REPLAY | 24, 162.2k, 23.0 | 76, 70.6k, 0.1 |

### B5. Sensitivity: NAT100 post-stratified to the natural population's churn mix

Churn bin = number of FUTURE commits at which the s0 answer is invalid (0 / 1–100 / 101–200 / 201–400). Population shares (715 natural facts): 72 % / 5 % / 5 % / 18 %; NAT100 counts: 76 / 4 / 4 / 16.

Validation on ESM: re-weighted NAT100 = 6.2 % at 16.4k tokens/fact vs the actual population 5.6 % at 23.0k.

| baseline | ratio B/ESM unweighted | ratio re-weighted to the population churn mix | Δ served-wrong pp re-weighted |
|---|---|---|---|
| TTL100 | 1.91 | 1.82 | -2.56 |
| CERT-ZS (incl. extraction) | 2.26 | 2.12 | -0.03 |
| CERT-v0h (static only, incl. construction) | 1.15 | 1.16 | +0.00 |
| LLMDIFF | 3.72 | 3.61 | -1.03 |
| REPLAY | 6.01 | 5.88 | -0.14 |