# Stage 4: end-to-end task stream with real arrival patterns (SIMULATION from recorded decisions)

Date: 2026-10-04.

* **No LLM or GPU was used in this stage.**
* **This is a simulation.**
  * Task arrival times are real GitHub issue timestamps.
  * Which facts each task reads is synthetic.
  * Every served answer and every token count replays a decision recorded in Stage 2 (`esm/results/heldout/records.parquet`
    and the recorded 27B re-derivations).
  * Assumptions and limitations are listed in `esm/stream/README.md`; read it before quoting any number.
* **Where the numbers come from.** `tables.md` and `results.json` are produced by `python -m esm.stream.report`, and
  `validation.md` by `python -m esm.stream.validate`.

## 0. Verdict

* **The stream.** 16 held-out repositories, each with 400 FUTURE commits:
  * 8,771 tasks per run;
  * one task per real issue, reading k ∈ {1, 2, 3} stored facts with Zipf(1) popularity;
  * 10 seeds;
  * lazy, on-read maintenance.
* **Main result, H150 (160 facts, every real-cost policy, same 27B re-derivation agent).**
  * **ESM (frozen) serves a wrong answer to 10.6 % of tasks at 370 tokens per task.**
  * NEVER (blind reuse) serves 38.6 % at 0 tokens; paired −28.0 pp [−34.4, −20.6].
  * ESM matches the best baselines on wrong-served tasks and is cheaper than every baseline except TTL200: 1.5× cheaper than TTL100, 1.8× than CERT-ZS / LLMDIFF, and up to 27× than ALWAYS*:

    | baseline | wrong-served tasks % | paired ESM − baseline, pp [CI] | tokens per task |
    |---|---|---|---|
    | CERT-ZS | 10.1 | +0.5 [−2.5, +3.8] | 662 |
    | LLMDIFF | 9.2 | +1.3 [−1.4, +5.4] | 689 |
    | REPLAY + re-derive | 13.4 | −2.8 [−7.1, +1.1] | 1,778 |
    | FILEHASH (composed) | 13.5 | | 2,349 |
    | ALWAYS (composed) | 14.5 | | 10,047 |

  * ESM is significantly better than TTL50 (−7.1 pp at −851 tokens per task) and TTL100 (−11.6 pp at −190 tokens per task).
  * ESM-verify (verified repair) is tied with ESM at 22 % lower cost.
* **What the real arrival pattern adds over a rate-matched Poisson stream: very little.**
  * Every policy moves by ≤ 1.2 pp, except the no-/slow-maintenance ones: NEVER −2.9 pp, TTL200 −1.8 pp.
  * The policy ranking is essentially unchanged: Kendall τ = 0.985 by wrong-served tasks and 1.000 by cost on H150, and
    1.000 / 1.000 on ALL.
  * The real streams place tasks slightly earlier in the commit sequence: mean commit index 176 vs 194. That accounts for
    most of NEVER's difference.
  * This matches the earlier trace study: reads and writes share activity bursts but are only mildly clustered.
* **Total cost follows change, not read volume.** From ×0.3 to ×3 read volume (10× more tasks):
  * ESM's total tokens grow 2.65M → 3.57M (×1.35), and the wrong-served rate stays flat (10.3–10.6 %).
  * Per-task cost falls 1,011 → 136.
  * TTL, REPLAY, CERT-ZS and LLMDIFF behave the same way.
  * ALWAYS is the exception: it scales with reads, 37M → 145M.
* **Wrong answers that survive stay in service a long time.** ESM's residual wrong answers sit in long episodes:
  * median 474 days from the first wrong read to the next right read;
  * 81 % never corrected within the window;
  * about 42 wrong reads per episode.
  * These are mostly the persistent wrong re-derivations found in Stage 2 (a referent removed or moved, but the agent
    answered a value).
  * Policies that re-derive on a timer have shorter episodes but more of them (TTL50: 98 episodes per run, median 81 days).
* **What bounds accuracy is still the answer source, not detection.**
  * With oracle re-derivations, ESM@oracle serves 0.8 % wrong tasks at 278 tokens per task.
  * REPLAY@oracle serves 0.3 % at 1,332, and ALWAYS@oracle 0 % at 9,003.

## 1. What was simulated

| item | value |
|---|---|
| repos / commits | 16 held-out repos × 400 FUTURE first-parent commits (Stage 2 layout) |
| arrivals: own | httpx, jinja, black, networkx: their own issues (traces/events_github.parquet) in their FUTURE window, on their own commit clock |
| arrivals: proxy | the other 12: the 400-commit window of the trace repo with the closest commit rate (each proxy used once; the 4 own repos excluded). The held-out commit i is identified with proxy window commit i, and every time is the proxy's real time (`arrivals_meta.json`; rate match within 1.4× for 9 of 12, worst 1.85× boltons ← pallets/flask) |
| tasks | 1 issue = 1 task (8,771 per run; 19 for scrapy up to 1,255 for kombu); k ~ U{1,2,3} distinct facts of that repo, Zipf(1) over a random per-seed popularity order; t = last commit at or before the task time |
| control | Poisson: same task count, uniform times over the same window and commit clock |
| sensitivity | volume ×0.3 / ×3; k = 1 / 3; uniform popularity / Zipf 1.5 (one factor at a time) |
| fact sets | **H150** (160 facts; all real-cost policies recorded at every commit), **H150s** (its 133 static facts, for static-only CERT-v0h), **ALL** (1,419 facts; ESM, NEVER and @oracle baselines only) |
| deployment | lazy: maintain a fact only when read; several reads of a fact at one commit share one maintenance; the served answer is the recorded every-commit run's answer at that commit; cost = one judgement + one re-derivation at most per read interval, at recorded tokens ("coalesced"). The EAGER commit-hook cost (exact) and the "sum" upper bound are also reported (§5) |
| composed policies | ALWAYS* and FILEHASH* re-derivations are imputed from recorded 27B re-derivations of the same fact at the nearest commit with the same oracle value (exact commit or same value: 99.8 % of imputations; leave-one-out agreement 96.9 %) |
| seeds, CIs | 10 seeds; bootstrap B = 2,000 over the 16 repos (task metrics) and over facts (read metrics); paired where stated. Seed variation is summed, not resampled |

## 2. Validation of the replay approximation (`validation.md`)

The engine was run on the every-commit records with reads placed on schedules that Stage 2 actually executed lazily, and
its output compared with those recorded runs.

**ESM (frozen), H150:**

| schedule | served-wrong %, engine / recorded | tokens per fact, engine / recorded | per-read agreement % |
|---|---|---|---|
| every5 | 7.0 / 7.0 | 24.2k / 24.0k | 100.0 |
| every20 | 7.3 / 7.2 | 20.1k / 19.1k | 99.4 |
| every50 | 7.7 / 7.4 | 17.6k / 16.6k | 98.5 |
| bursty | 4.7 / 4.8 | 15.2k / 14.6k | 99.7 |

So the coalesced accounting over-charges ESM by 1–6 %.

**Other policies at every50:**

* REPLAY, CERT-ZS, CERT-v0h and LLMDIFF: served-wrong within 0.6 pp, tokens within 2 %.
* FILEHASH*: 9.1 vs 9.3 %, 60.7k vs 65.9k tokens.
* ALWAYS*: identical, as expected.

**TTL** is exact when the stream's epoch expiry and Stage 2's age expiry coincide. When they differ (every20, bursty), the
engine charges up to +33 % (TTL@oracle).

**Not validated:** most facts in the stream are read more sparsely than every 50 commits, which is outside the
validated range.

## 3. Main table: H150, real arrivals, default configuration (`tables.md` T1, T2)

| policy | wrong-served tasks % [repo CI] | wrong reads % [fact CI] | tokens / task [repo CI] | total tokens / run | judge : re-derivation | wrong tasks avoided vs NEVER per 1M tokens | stale episodes / run, median days, % censored |
|---|---|---|---|---|---|---|---|
| **ESM (frozen)** | **10.6 [4.1, 19.7]** | 5.9 [3.0, 9.2] | **370** [254, 576] | 3.25M | 30 : 70 | 757 | 24, 474, 81 % |
| ESM-verify | 10.1 [3.9, 18.7] | 5.6 [2.8, 8.9] | 287 [199, 433] | 2.52M | 42 : 58 | 992 | 26, 386, 83 % |
| NEVER | 38.6 [30.4, 46.9] | 24.3 [18.2, 30.5] | 0 | 0 | – | – | 87, 455, 91 % |
| ALWAYS (composed) | 14.5 [8.1, 22.7] | 7.9 [4.6, 11.7] | 10,047 | 88.1M | 0 : 100 | 24 | 58, 126, 39 % |
| TTL50 | 17.7 [11.6, 25.0] | 10.0 [7.0, 13.4] | 1,221 | 10.7M | 0 : 100 | 171 | 98, 81, 34 % |
| TTL100 | 22.2 [15.7, 29.3] | 13.1 [9.5, 16.6] | 561 | 4.9M | 0 : 100 | 293 | 98, 134, 35 % |
| TTL200 | 30.6 [21.9, 40.3] | 18.6 [13.5, 23.9] | 182 | 1.6M | 0 : 100 | 437 | 90, 218, 61 % |
| REPLAY + re-derive | 13.4 [7.2, 21.8] | 7.3 [4.0, 11.0] | 1,778 | 15.6M | 0 : 100 | 142 | 48, 162, 47 % |
| FILEHASH (composed) | 13.5 [7.3, 22.0] | 7.3 [4.0, 11.1] | 2,349 | 20.6M | 0 : 100 | 107 | 49, 159, 48 % |
| CERT-ZS (incl. construction) | 10.1 [4.3, 19.4] | 5.7 [3.1, 8.6] | 662 | 5.8M | 0 : 97 (+3 setup) | 430 | 32, 274, 66 % |
| LLMDIFF | 9.2 [3.5, 19.0] | 5.3 [2.9, 8.0] | 689 | 6.0M | 57 : 43 | 426 | 35, 147, 73 % |
| *ESM@oracle (idealised)* | *0.8 [0.0, 2.6]* | *0.4* | *278* | *2.4M* | *33 : 67* | *1,360* | *5, 385, 59 %* |
| *ALWAYS@oracle* | *0.0* | *0.0* | *9,003* | *79.0M* | *0 : 100* | *43* | *0* |
| *TTL50@oracle* | *7.5* | *4.1* | *1,086* | *9.5M* | | *286* | *80, 55, 14 %* |
| *TTL100@oracle* | *14.3* | *8.2* | *499* | *4.4M* | | *487* | |
| *REPLAY@oracle* | *0.3* | *0.1* | *1,332* | *11.7M* | | *288* | *3, 104, 0 %* |
| *FILEHASH@oracle* | *0.2* | *0.1* | *2,247* | *19.7M* | | *171* | |

Wrong-served tasks per 1k tokens is also in `tables.md`. It is dominated by the denominator: ESM 0.285, TTL200 1.684,
REPLAY 0.075.

**Paired, ESM − baseline** (repo bootstrap; the fact bootstrap on wrong reads agrees in sign and significance):

| baseline | Δ wrong-served tasks, pp | Δ tokens per task |
|---|---|---|
| NEVER | −28.0 [−34.4, −20.6] | +370 |
| TTL50 | −7.1 [−12.0, −2.6] | −851 |
| TTL100 | −11.6 [−17.1, −6.1] | −190 |
| TTL200 | −20.1 [−27.3, −11.9] | +188 |
| REPLAY | −2.8 [−7.1, +1.1] | −1,408 [−2,197, −834] |
| FILEHASH* | −2.9 [−7.8, +1.8] | −1,979 |
| ALWAYS* | −4.0 [−9.6, +1.1] | −9,677 |
| CERT-ZS | +0.5 [−2.5, +3.8] | −292 [−540, −115] |
| LLMDIFF | +1.3 [−1.4, +5.4] | −319 [−496, −210] |
| ESM-verify | +0.5 [−0.8, +2.4] | +83 [+38, +158] |

**Static subset (H150s, 133 facts; T1s, T2s):**

| policy | wrong-served tasks % | tokens per task |
|---|---|---|
| ESM | 10.6 | 291 |
| CERT-v0h (incl. construction) | 11.6 | 332 |
| CERT-ZS | 9.6 | 443 |
| REPLAY | 11.8 | 1,232 |

* ESM − CERT-v0h: −1.0 [−8.0, +5.5] pp, −41 [−122, +17] tokens per task. A tie.
* ESM − CERT-ZS: +1.0 [−1.7, +4.1] pp, −151 [−365, −17] tokens per task.

**Reading of the main table:**

* The repo CIs are wide (±7–8 pp) because one repo, jinja, dominates the wrong tasks. On ALL, ESM's wrong-served tasks in
  jinja are 56 %, from the `src/` move.
* Under real arrivals, ESM, CERT-ZS, LLMDIFF and ESM-verify are statistically indistinguishable in accuracy. ESM and
  ESM-verify are the cheapest of the four.
* Policies that re-derive more often (ALWAYS*, FILEHASH*, REPLAY, TTL50) are not more accurate, because each 27B
  re-derivation can itself be wrong. Stage 2 found the same.

## 4. ALL facts (1,419; ESM vs NEVER vs idealised @oracle baselines; T3, T4)

| policy | wrong-served tasks % [repo CI] | wrong reads % [fact CI] | tokens / task |
|---|---|---|---|
| **ESM (frozen)** | **8.2 [2.7, 17.5]** | 5.0 [3.9, 6.2] | **1,540** |
| NEVER | 29.1 [20.0, 40.3] | 18.9 [16.9, 21.0] | 0 |
| *TTL100@oracle* | *10.5* | *6.1* | *2,415* |
| *TTL50@oracle* | *5.5* | *3.1* | *3,978* |
| *CITE@oracle* | *6.8* | *3.5* | *1,369* |
| *REPLAY@oracle* | *0.3* | *0.2* | *3,610* |
| *FILEHASH@oracle* | *1.2* | *0.6* | *4,762* |
| *ALWAYS@oracle* | *0.0* | *0.0* | *11,811* |

* **Against NEVER:** ESM − NEVER −20.9 [−27.5, −14.9] pp.
* **Against the idealised baselines:** ESM ties TTL100@oracle (−2.3 [−6.8, +4.9]) at 875 fewer tokens per task.
  Baselines that are handed a perfect answer and pay 1.3–7.7× more tokens are more accurate.
* **Per-task cost by fact set.** ESM's per-task cost is higher on ALL (1,540) than on H150 (370). With ~90 facts per repo
  instead of 10, each fact is read rarely, so each read carries more of the maintenance for the commits since its last read.
* **Per repo** (`tables.md`): ESM's wrong-served tasks range from 0.0 % (rich, typer) to 56.4 % (jinja) and 22.8 %
  (werkzeug). NEVER ranges from 9.2 % to 75.0 %.

## 5. Cost accounting variants (H150, tokens per task; T7)

| policy | lazy, coalesced (main) | lazy, sum over skipped commits (upper bound) | eager commit hook (exact replay) |
|---|---|---|---|
| ESM | 370 | 457 | 484 |
| ESM-verify | 287 | 362 | 381 |
| TTL50 / TTL100 | 1,221 / 561 | 1,307 / 570 | 1,575 / 803 |
| REPLAY | 1,778 | 2,785 | 2,963 |
| CERT-ZS | 662 | 910 | 969 |
| LLMDIFF | 689 | 1,234 | 1,319 |
| FILEHASH* | 2,349 | 5,345 | 5,698 |
| ALWAYS* | 10,047 | 72,822 | 77,569 |

* ESM's advantage does not depend on the accounting. Even its exact eager cost (484) is below every lazy baseline except
  TTL100 (561) and TTL200 (182).
* Lazy evaluation saves ESM only ~24 %. Its work is already amortised per evidence state, not per commit.
* Lazy evaluation saves guards that act on every file change much more: FILEHASH ~59 %, LLMDIFF ~48 %.

## 6. Real arrivals vs Poisson control (T5)

| policy (H150) | wrong-served tasks %, real / Poisson | Δ pp [CI] | tokens per task, real / Poisson |
|---|---|---|---|
| ESM | 10.6 / 11.2 | −0.6 [−1.2, −0.1] | 370 / 359 |
| NEVER | 38.6 / 41.5 | −2.9 [−4.0, −1.4] | 0 / 0 |
| TTL200 | 30.6 / 32.5 | −1.8 [−3.1, −0.6] | 182 / 182 |
| REPLAY | 13.4 / 13.9 | −0.5 [−1.3, +0.1] | 1,778 / 1,684 |
| CERT-ZS | 10.1 / 10.7 | −0.6 [−1.3, −0.1] | 662 / 637 |
| LLMDIFF | 9.2 / 9.8 | −0.6 [−1.1, −0.2] | 689 / 670 |

All other policies are within ±1.2 pp (`tables.md`).

**Rankings:**

* H150: Kendall τ(real, Poisson) = 0.985 by wrong-served tasks. Only adjacent swaps occur: ESM-verify ↔ CERT-ZS and
  ALWAYS* ↔ TTL100@oracle. τ = 1.000 by tokens.
* ALL: τ = 1.000 for both.

**Why real arrivals look slightly better:**

* Real tasks sit earlier in the commit sequence: mean commit index 176 vs 194 under Poisson.
* Staleness grows with commit index, so policies that leave staleness in place gain from this. NEVER gains most.
* Real arrivals cost slightly more for policies that act on every change (REPLAY +94 tokens per task), because real tasks
  are somewhat more spread over distinct commits.

**Stale-window medians are nearly unchanged** (ESM 474 vs 478 days).

**Conclusion:** on these data the real interleaving does not change which policy to choose. It shifts absolute numbers
by ≤ 3 pp.

## 7. Sensitivity (T6; `sensitivity.png`)

* **Read volume ×0.3 → ×1 → ×3** (2,624 → 8,771 → 26,313 tasks per run).
  * Wrong-served rates are flat for every policy, within 0.6 pp.
  * Tokens per task fall roughly in proportion to 1/volume; total tokens grow sub-linearly:

    | policy | total tokens, ×0.3 → ×1 → ×3 |
    |---|---|
    | ESM | 2.65M → 3.25M → 3.57M |
    | TTL50 | 8.7M → 10.7M → 11.4M |
    | REPLAY | 10.6M → 15.6M → 18.6M |
    | CERT-ZS | 4.5M → 5.8M → 6.6M |
    | ALWAYS* | 37M → 88M → 145M |

* **k.** k = 1 vs 3 changes every wrong-served task rate by ×2–2.5 (ESM 5.9 % vs 14.8 %, NEVER 24.2 % vs 51.2 %),
  because a task is wrong if any read is wrong. Rankings are unchanged (τ ≥ 0.99).
* **Popularity.** Uniform popularity and Zipf 1.5 change rates by ≤ 0.7 pp and tokens by ≤ 10 %; τ ≥ 0.99.
* **Robustness of the ranking.** On ALL, the ranking is identical (τ = 1.00) under every variation.

## 8. Stale windows (reader's view)

An episode starts at a wrong read whose previous read of that fact was right, and ends at the next right read. It is
measured in real days on the stream's clock and censored at the end of the window.

| policy (H150, real) | episodes per run | median days (p90) | % censored | wrong reads per episode | median days, corrected episodes only |
|---|---|---|---|---|---|
| ESM | 24 | 474 (1,963) | 81 % | 42 | 14 |
| NEVER | 87 | 455 (1,482) | 91 % | 49 | 25 |
| REPLAY | 48 | 162 (1,175) | 47 % | 26 | 33 |
| TTL50 | 98 | 81 (501) | 34 % | 18 | 52 |
| CERT-ZS | 32 | 274 (1,955) | 66 % | 32 | 21 |
| LLMDIFF | 35 | 147 (1,952) | 73 % | 26 | 50 |

* **ESM has the fewest episodes**, about 1/4 of NEVER's.
* **Its episodes are long.** When ESM's stored answer is wrong, it is usually because a re-derivation produced a wrong
  value and was then treated as the new anchor. No later state change exposes it.
  * Stage 2 traced 84 % of ESM's wrong reads to this mechanism (oracle NONE: the referent was removed, its file moved, or
    the file does not parse).
  * Episodes that do get corrected are corrected quickly: median 14 days.
* **Timer-based policies** (TTL) cap the episode length at the cost of many more episodes.
* **Example.** `timeline_networkx.png` shows one stream (networkx, own issue arrivals, seed 0):
  * commits, tasks, ESM judge calls and re-derivations, right and wrong reads, and the ESM vs NEVER episodes;
  * three ESM episodes start at a re-derivation or at a judgement that kept the answer, and none is corrected before the window ends.

## 9. Figures

* `pareto.png`: tokens per task (log) vs wrong-served task %.
  * Filled markers are real arrivals, hollow markers Poisson; circles are real-cost policies, squares @oracle.
  * Left panel H150, right panel ALL. The red step marks the real-cost Pareto front.
  * On H150 the front is NEVER → TTL200 → ESM-verify → LLMDIFF. ESM sits on it within its CI; ESM-verify dominates it
    slightly.
* `timeline_networkx.png`: the per-repo timeline described in §8.
* `sensitivity.png`: wrong-served tasks and tokens per task vs read volume.

## 10. Limitations

* **Replayed, not re-run.**
  * At sparse reads, a real lazy policy would judge different transitions and re-derive at different commits. The
    approximation is validated to ≤ 0.6 pp and ≤ 6 % tokens down to every-50-commit reads; most stream reads are sparser
    still.
  * ALWAYS* and FILEHASH* are composed from re-derivations recorded at other commits. No real ALWAYS or FILEHASH was ever
    run at every commit.
* **Borrowed arrivals.**
  * 12 of the 16 repos use a proxy repo's commit and issue stream, so the commit ↔ code-change pairing is arbitrary for
    those repos.
  * Issues are only a proxy for knowledge-reading tasks.
  * The task-to-fact mapping (k, Zipf, popularity independent of churn) is assumed.
* **Unrepresentative fact sets.**
  * H150 over-represents changing facts, so its absolute rates are not base rates.
  * ALL has real costs only for ESM and NEVER.
* **CIs omit some variation.** Repo-level CIs are wide and dominated by jinja (its `src/` move). Seed variation is
  summed, not included in the CIs.
* **Unmeasured costs.** Initial s0 derivation cost is not counted for any policy. Certificate construction is counted for
  CERT-ZS and CERT-v0h.
