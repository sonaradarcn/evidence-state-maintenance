# Validation of the lazy-replay approximation

Engine = this stage's replay of the EVERY-commit record with reads placed at the schedule's commits; recorded = the held-out run actually executed on that schedule (its own lazy decisions and LLM calls).

| set | policy | schedule | facts | served-wrong % recorded | engine | per-read agreement % | tokens/fact recorded | engine coalesced | engine sum | re-derivations/fact recorded | engine |
|---|---|---|---|---|---|---|---|---|---|---|---|
| H150 | ESM (frozen) | every5 | 160 | 7.0 | 7.0 | 100.0 | 24.0k | 24.2k | 26.5k | 1.19 | 1.23 |
| H150 | ESM (frozen) | every20 | 160 | 7.2 | 7.3 | 99.4 | 19.1k | 20.1k | 26.5k | 0.99 | 1.09 |
| H150 | ESM (frozen) | every50 | 160 | 7.4 | 7.7 | 98.5 | 16.6k | 17.6k | 26.5k | 0.93 | 1.01 |
| H150 | ESM (frozen) | bursty | 160 | 4.8 | 4.7 | 99.7 | 14.6k | 15.2k | 21.5k | 0.79 | 0.84 |
| H150 | NEVER | every50 | 160 | 32.0 | 32.0 | 100.0 | 0.0k | 0.0k | 0.0k | 0.00 | 0.00 |
| H150 | TTL50 | every50 | 160 | 8.9 | 8.9 | 100.0 | 86.3k | 86.3k | 86.3k | 8.00 | 8.00 |
| H150 | TTL100 | every50 | 160 | 12.0 | 12.0 | 100.0 | 44.0k | 44.0k | 44.0k | 4.00 | 4.00 |
| H150 | TTL200 | every50 | 160 | 19.0 | 19.0 | 100.0 | 22.5k | 22.5k | 22.5k | 2.00 | 2.00 |
| H150 | REPLAY | every50 | 160 | 8.9 | 8.8 | 99.8 | 55.6k | 56.0k | 162.4k | 3.92 | 3.97 |
| H150 | CERT-ZS | every50 | 160 | 8.2 | 7.6 | 97.5 | 28.2k | 28.5k | 52.0k | 2.36 | 2.41 |
| H150 | CERT-v0h | every50 | 133 | 7.1 | 7.0 | 98.7 | 14.1k | 14.3k | 21.6k | 1.41 | 1.44 |
| H150 | LLMDIFF | every50 | 160 | 9.4 | 8.9 | 98.1 | 25.4k | 25.1k | 72.3k | 1.29 | 1.38 |
| H150 | ALWAYS (composed) | every50 | 160 | 8.9 | 8.9 | 100.0 | 86.3k | 86.3k | 4252.3k | 8.00 | 8.00 |
| H150 | FILEHASH (composed) | every50 | 160 | 9.3 | 9.1 | 99.3 | 65.9k | 60.7k | 312.3k | 5.46 | 5.14 |
| ALL | TTL50@oracle | every5 | 1419 | 3.1 | 3.1 | 100.0 | 67.1k | 67.1k | 67.1k | 8.00 | 8.00 |
| ALL | TTL50@oracle | every20 | 1419 | 2.5 | 2.7 | 97.5 | 50.4k | 67.1k | 67.1k | 6.00 | 8.00 |
| ALL | TTL50@oracle | every50 | 1419 | 0.0 | 0.0 | 100.0 | 67.1k | 67.1k | 67.1k | 8.00 | 8.00 |
| ALL | TTL50@oracle | bursty | 1419 | 2.6 | 2.8 | 98.8 | 33.6k | 42.0k | 50.4k | 4.00 | 5.00 |
| ALL | TTL100@oracle | every5 | 1419 | 6.2 | 6.2 | 100.0 | 33.6k | 33.6k | 33.6k | 4.00 | 4.00 |
| ALL | TTL100@oracle | every20 | 1419 | 5.2 | 5.2 | 100.0 | 33.6k | 33.6k | 33.6k | 4.00 | 4.00 |
| ALL | TTL100@oracle | every50 | 1419 | 3.3 | 3.3 | 100.0 | 33.6k | 33.6k | 33.6k | 4.00 | 4.00 |
| ALL | TTL100@oracle | bursty | 1419 | 4.0 | 5.9 | 96.8 | 16.8k | 25.2k | 25.2k | 2.00 | 3.00 |
| ALL | TTL200@oracle | every5 | 1419 | 11.2 | 11.2 | 100.0 | 16.8k | 16.8k | 16.8k | 2.00 | 2.00 |
| ALL | TTL200@oracle | every20 | 1419 | 10.3 | 10.3 | 100.0 | 16.8k | 16.8k | 16.8k | 2.00 | 2.00 |
| ALL | TTL200@oracle | every50 | 1419 | 8.7 | 8.7 | 100.0 | 16.8k | 16.8k | 16.8k | 2.00 | 2.00 |
| ALL | TTL200@oracle | bursty | 1419 | 7.9 | 8.4 | 99.5 | 8.4k | 8.4k | 8.4k | 1.00 | 1.00 |
| ALL | REPLAY@oracle | every5 | 1419 | 0.1 | 0.1 | 100.0 | 84.6k | 85.5k | 103.3k | 6.13 | 6.18 |
| ALL | REPLAY@oracle | every20 | 1419 | 0.1 | 0.1 | 99.9 | 58.0k | 58.3k | 103.3k | 4.52 | 4.55 |
| ALL | REPLAY@oracle | every50 | 1419 | 0.0 | 0.1 | 100.0 | 37.1k | 37.3k | 103.3k | 3.19 | 3.21 |
| ALL | REPLAY@oracle | bursty | 1419 | 0.1 | 0.1 | 100.0 | 45.2k | 45.3k | 88.4k | 3.55 | 3.56 |
| ALL | FILEHASH@oracle | every5 | 1419 | 2.2 | 0.7 | 98.4 | 158.1k | 158.2k | 235.1k | 14.22 | 14.23 |
| ALL | FILEHASH@oracle | every20 | 1419 | 0.7 | 0.7 | 100.0 | 83.0k | 83.1k | 235.1k | 8.27 | 8.28 |
| ALL | FILEHASH@oracle | every50 | 1419 | 0.6 | 0.7 | 99.9 | 46.1k | 46.1k | 235.1k | 4.91 | 4.92 |
| ALL | FILEHASH@oracle | bursty | 1419 | 0.5 | 0.6 | 99.9 | 77.7k | 77.7k | 199.6k | 7.25 | 7.25 |
| ALL | CITE@oracle | every5 | 1419 | 5.3 | 3.8 | 98.3 | 30.9k | 31.0k | 39.3k | 2.82 | 2.82 |
| ALL | CITE@oracle | every20 | 1419 | 3.6 | 3.9 | 99.7 | 19.3k | 19.4k | 39.3k | 1.89 | 1.89 |
| ALL | CITE@oracle | every50 | 1419 | 3.7 | 4.1 | 99.6 | 12.7k | 12.7k | 39.3k | 1.32 | 1.33 |
| ALL | CITE@oracle | bursty | 1419 | 2.6 | 2.9 | 99.7 | 16.2k | 16.2k | 33.1k | 1.65 | 1.65 |
| ALL | NEVER | every5 | 1419 | 21.7 | 21.7 | 100.0 | 0.0k | 0.0k | 0.0k | 0.00 | 0.00 |
| ALL | NEVER | every20 | 1419 | 22.2 | 22.2 | 100.0 | 0.0k | 0.0k | 0.0k | 0.00 | 0.00 |
| ALL | NEVER | every50 | 1419 | 23.4 | 23.4 | 100.0 | 0.0k | 0.0k | 0.0k | 0.00 | 0.00 |
| ALL | NEVER | bursty | 1419 | 16.0 | 16.0 | 100.0 | 0.0k | 0.0k | 0.0k | 0.00 | 0.00 |

Note on TTL rows: the recorded sparse TTL runs expire by AGE since the last re-derivation (the clock restarts at the read that re-derived); the stream uses EPOCH expiry (the answer expires at commits k, 2k, ...; the first read after an expiry re-derives), which is what the replay of the every-commit record gives. The two coincide on every5 / every50 and differ on every20 / bursty (the engine then charges more re-derivations than the age-based run).

Re-derivation imputation (composed policies), share of imputed re-derivations by kind: {"ALWAYS*": {"same_truth": 0.945, "exact": 0.052, "other_truth": 0.002}, "FILEHASH*": {"same_truth": 0.619, "exact": 0.38, "other_truth": 0.001}}

Leave-one-out: a recorded re-derivation's correctness predicted from the nearest other recorded re-derivation of the same fact (same oracle value when available): exact_t_excluded_same_truth: 4029/4159 = 96.9 %; fallback_other_truth: 35/324 = 10.8 %
