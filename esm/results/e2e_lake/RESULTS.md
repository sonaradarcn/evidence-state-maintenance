# B3-lake: end-to-end task evaluation on the evolving data lakes (expensive re-derivation)

Date: 2026-10-06. Plan, decision log, cuts and realised budget: `PLAN.md`. Every number below comes from
`python -m esm.e2e_lake.report_lake` (zero LLM), which writes `tables.md`, `results.json`,
`task_outcomes.{parquet,json}`, `task_outcomes_trust.parquet` and three figures. Code: `esm/e2e_lake/`. Data:
`esm_data_e2e_lake/`. Mirrors the code-repository e2e (`esm/results/e2e/`).

## 0. Verdict

* **Setup.** 63 real tasks: 21 kept Stage-3 facts × 3 later snapshots, done by a qwen3.6:27b tool-using agent on the
  rebuilt lakes. Backblaze: 12 facts at +20 / +40 / +80 snapshots. TLC: 9 facts at +25 / +50 / +100 snapshots.
  * Task types:
    * T-sql: write a DuckDB query that must use the right column name; the query is executed.
    * T-report: report a partition / running / join statistic.
    * T-files: choose the daily file to load; checked against the manifest.
    * T-question: answer a schema / coverage question.
  * The memory note is wrong at t for 49 % of NEVER's tasks.
  * No selected referent disappears, so no task has abstention as its correct answer.
* **Main table (main prompt: "the data may have changed since"; CIs bootstrap over tasks).**

  | arm | success % [95 % CI] | wrong action % | failure % | memory right % | tokens/task (task + maint.) | latency s/task (est.) |
  |---|---|---|---|---|---|---|
  | NO-MEMORY | 76.2 [65.1, 85.7] | 7.9 [1.6, 14.3] | 15.9 | – | 43.2k (43.2k + 0) | 51.2 |
  | NEVER (blind reuse) | 74.6 [63.5, 84.1] | 19.0 [9.5, 28.6] | 6.3 | 50.8 | 40.6k (40.6k + 0) | 45.9 |
  | TTL (TLC 25 / BB 20) | 77.8 [66.7, 87.3] | 9.5 [3.2, 17.5] | 12.7 | 79.4 | 76.3k (34.1k + 42.2k) | 88.7 |
  | REPLAY | 77.8 [66.7, 87.3] | 9.5 [3.2, 17.5] | 12.7 | 79.4 | 76.3k (34.1k + 42.2k) | 88.7 |
  | **ESM** (frozen, lazy) | **79.4 [68.3, 88.9]** | 14.3 [6.3, 23.8] | 6.3 | 74.6 | **50.9k (38.2k + 12.6k)** | 58.5 |
  | *TTL-mid (50 / 40)* | *74.6* | *14.3* | *11.1* | *74.6* | *64.6k (36.3k + 28.3k)* | *74.8* |
  | *ESM-eager (replayed)* | *76.2* | *15.9* | *7.9* | *68.3* | *77.8k (39.8k + 38.0k)* | *86.6* |
  | *ORACLE memory (idealised)* | *88.9 [81.0, 96.8]* | *7.9* | *3.2* | *100* | *33.0k* | *39.7* |

  Latency is the measured task latency plus maintenance re-estimated at 1.11 s per 1k tokens on this server
  (`tables.md` T7b). On these reads REPLAY ≡ TTL: every lake append changes a replayed listing, so both re-derive at
  every read. All re-derivations were Stage-3 records; ESM made 3 new judge calls.
* **Reading (main prompt).**
  * **Accuracy.**
    * No maintained policy is significantly more accurate than having no memory. Paired success vs NO-MEMORY:
      ESM +3.2 pp [−9.5, +14.3], TTL +1.6 [−9.5, +11.1].
    * Blind reuse is the one clear harm: NEVER makes +11.1 pp [+4.8, +19.0] more wrong actions than NO-MEMORY.
    * Maintenance removes most of that harm. TTL / REPLAY: −9.5 pp [−19.0, −1.6] wrong actions vs NEVER. ESM:
      −4.8 [−11.1, +1.6], not significant.
  * **Cost.**
    * ESM is the cheapest maintained policy: −25.4k tokens per task vs TTL [−32.3k, −19.2k], at equal accuracy
      (success +1.6 pp [−6.3, +9.5]).
    * It still costs **+7.7k tokens per task [+0.9k, +14.9k] more than NO-MEMORY**.
  * **Why memory does not pay here.** With the main prompt the agent re-checks its memory. Memory cuts its own task
    tokens only from 43.2k to 38.2k, and even perfect memory (ORACLE) only to 33.0k: −10.1k [−15.9k, −5.1k].
* **Pre-registered secondary: "rely on your memory" prompt (T9).** This is the regime where re-derivation cost matters.
  * Memory now cuts task tokens to about half: ORACLE 18.2k vs 43.2k.
  * **ESM is then 7.4k tokens per task cheaper than NO-MEMORY** [−16.9k, +2.0k], at total 35.8k, with success
    76.2 % vs 76.2 %.
  * **Blind reuse becomes very harmful:** NEVER makes 42.9 % wrong actions, paired +34.9 pp [+22.2, +47.6] vs NO-MEMORY.
  * ESM removes half of NEVER's excess wrong actions: −22.2 pp [−31.7, −12.7]. TTL / REPLAY remove more: −30.2 pp,
    at 64.7k tokens per task.
  * ESM still makes +12.7 pp [+4.8, +22.2] more wrong actions than NO-MEMORY. These come from facts whose staleness it
    does not detect (§3).
* **Bottom line: the cheap-vs-expensive contrast (T10).**

  | | code repos (cheap re-derivation) | data lakes (expensive) | TLC | Backblaze |
  |---|---|---|---|---|
  | fact derivation cost (s0) | ≈ 8–19k | ≈ 34k / 70k | ≈ 34k | ≈ 70k |
  | NO-MEMORY task tokens / success | 11.2k / 93.3 % | **43.2k / 76.2 %** | 31.8k / 85.2 % | 51.7k / 69.4 % |
  | task tokens saved by ESM memory, main prompt | −0.3k | 4.9k | 5.6k | 4.4k |
  | ESM maintenance tokens / read | 5.8k | 12.6k | 12.3k | 12.9k |
  | ESM − NO-MEMORY total tokens, main prompt | +6.0k [+4.0, +8.3] | +7.7k [+0.9, +14.9] | +6.7k [−2.2, +15.4] | +8.4k [−1.6, +19.8] |
  | ESM − NO-MEMORY total tokens, trust prompt | (code e2e: +4.5k) | **−7.4k [−16.9, +2.0]** | −0.2k (31.6k vs 31.8k) | −12.8k (38.9k vs 51.7k) |
  | ESM − NO-MEMORY success, main / trust | +1.7 / – | +3.2 / 0.0 | 0.0 / +3.7 | +5.6 / −2.8 |
  | NEVER wrong actions, main / trust | 7.5 / 12.5 % | 19.0 / 42.9 % | 7.4 / 33.3 % | 27.8 / 50.0 % |

  When the agent relies on what it remembers, expensive re-derivation turns maintained memory from a net cost into a
  net saving. On the lakes, ESM's 12.6k tokens per read are less than the ≈ 20k task tokens that relying on memory
  saves. In code repositories, by contrast, the whole task costs ≈ 11k.

  Two things limit the claim:
  1. With a re-verifying agent, memory saves little even here. The agent re-checks and still pays most of the
     derivation cost.
  2. Saving tokens is not the same as being correct. ESM's undetected stale facts (Backblaze D8 counts) produce
     wrong actions that a memoryless agent avoids.

## 1. What is real and what is replayed

| component | status |
|---|---|
| lakes | **re-created** this session. The the original data drive store was deleted on 10-05. Every Backblaze member file (39 zips) and every TLC non-fhvhv file (≤ 2024-03) was re-downloaded, re-subsampled with `datalake/ingest.py`'s functions and **byte-identical** to the catalogued sha256. All 33 doc / lookup versions are identical. The rebuilt snapshot manifests equal `datalake/manifests` on all 383 / 176 events. 0 on-demand fetches were needed during task runs. |
| facts, s0 answer, s0 trace | reused: Stage-3 kept 27B derivations |
| truth at t | Stage-3 truth series. Validated against `facts_dl.oracle_direct` on 60/63 (fact, t). The 3 misses are bb:D4:72: `oracle_direct`'s string max over the date column picks a real file's `6/17/19` date; the truth and the manifest agree. |
| maintenance (lazy: reads only at the 3 task snapshots) | real policy code (`esm` package: NEVER, TTL, TTL-mid, REPLAY, frozen ESM-norepair). **All 186 re-derivation reads (NEVER/TTL/TTL-mid/REPLAY/ESM; distinct (fact, t) ≤ 63) and 24 of 27 ESM judge calls were identical Stage-3 requests** (task snapshots = the Stage-3 grid): served from the record at recorded tokens. **3 judge calls are new.** |
| ESM-eager | replayed: Stage-3 every-snapshot ESM served answer at t; maintenance = recorded tokens in (t_prev, t] |
| task agent | **real, new**: 1,998 qwen3.6:27b calls on GPU 1 (9.45M prompt + 0.30M completion tokens, 3.1 h LLM time). Arms with identical notes share one run: 184 unique runs for 504 main (arm, task) pairs, 109 for the trust variant |
| checks | deterministic, at snapshot t: canonical value vs oracle (T-report / T-question), **executed** SQL vs a reference query on the true column, plus a must-read-the-latest-file check (T-sql), manifest path (T-files) |

## 2. Design (pre-registered in `PLAN.md`; cuts logged there)

* **Facts.** The Stage-3 blind stratified subset S, restricted to D1/D2/D3/D4/D6/D8. S is the only set with recorded
  re-derivations at every grid snapshot.
  * S over-represents changing facts, so absolute rates are not base rates.
  * **Cut at 09:55, logged before any task or maintenance run:** the 5 TLC facts on the High-Volume FHV dataset were
    dropped. Its 26-GB re-download was rate-blocked by CloudFront (HTTP 403), and the session was then suspended for
    ≈ 8 h. D5 / D7 were excluded by design.
  * Final set: TLC 9 facts (D1 1, D2 1, D3 3, D4 1, D6 2, D8 1); Backblaze 12 facts (D1 3, D2 2, D3 2, D4 2, D6 1, D8 2).
* **Task types and checks.**
  * T-sql (D2): the query must alias its output with the exact case-sensitive column name, read the newest file, and
    return the reference value.
  * T-report (D3 / TLC D4 / D6).
  * T-files (Backblaze D4 latest-date facts).
  * T-question (D1 / D8).
* **Arms.** NO-MEMORY, NEVER, TTL (TLC 25, BB 20), TTL-mid (50 / 40), REPLAY, ESM (frozen, lazy), ESM-eager (replayed),
  ORACLE.
* **Agent.** At most 12 lake tool calls, the same scan budget as the derivation agent, then submit / abstain.
* **CIs.** Bootstrap over tasks (B = 2000); fact-clustered CIs as a check. Clustering widens most CIs: `tables.md`
  T1c and T2.

## 3. Further results (`tables.md`)

* **By task type (T3, main prompt).**
  * **T-question (D1 schema types, D8 coverage counts)** is where stale memory hurts:
    * NEVER: 28.6 % wrong (its note is right on only 14 % of these tasks).
    * TTL / REPLAY: 4.8 %. NO-MEMORY: 4.8 %.
    * ESM: 19.0 %, from bb:D8:147, explained under "Errors".
  * **T-report (D3 / D4 / D6)** is where memory helps. NO-MEMORY fails 29.6 % of these tasks: it abstains or runs out
    of the 12-call budget on multi-file aggregates. That is the expensive-derivation regime.
    * ESM success 85.2 % vs NO-MEMORY 70.4 %. NEVER 81.5 %, TTL 70.4 %.
    * TTL re-derives at every read, and its re-derivations are sometimes empty. The agent then has no usable note.
  * **T-files:** TTL / REPLAY / ESM 100 %, TTL-mid / NEVER / NO-MEMORY 83 %.
  * **T-sql:** all arms fail equally often on the same tasks, ORACLE included (2 of 3 BB D2 tasks at +20 / +40). The
    agent picks the wrong "most recent" daily file: `data_Q4_2019/…` sorts after `data_Q1_2020/…`. The column name it
    remembers is right.
* **By fact type (T3b, T11).** Net token saving of ESM over NO-MEMORY (main prompt):
  * Positive for partition aggregates (TLC D3 +7.0k; BB D3 +1.5k, 0 maintenance tokens).
  * Positive for the BB join (D6 +40.9k: NO-MEMORY needs 126k tokens and fails 2 of 3).
  * Negative for coverage counts and running aggregates (BB D8 −31.5k; TLC D8 −39.3k; TLC D4 −12.4k): they change at
    every append, and maintenance costs a re-derivation each time.
  * This is the Stage-3 D3-vs-D4 boundary seen again in the task loop.
* **By snapshot offset (T4).** NEVER's memory is right on 66.7 / 47.6 / 38.1 % of tasks at offsets 1 / 2 / 3; ESM's on
  81 / 67 / 76 %.
* **Memory correctness vs outcome (T6, main prompt, memory arms pooled).**
  * A right note: 87.2 % success at 29.9k task tokens. On the same tasks NO-MEMORY gets 77.9 % at 37.4k.
  * A wrong note: 50.6 % success, against 71.9 % for NO-MEMORY on the same tasks.
* **Errors that the maintenance policy does not catch.**
  * **bb:D8:147** ("number of daily files with column smart_223_raw"): ESM served the s0 value 2000 at every read. The
    true count moves with every append (2517 / 3035 / 4131), and this change lies outside the recorded evidence, as
    documented in Stage 3. All three ESM tasks are wrong actions, in both prompts.
  * **tlc:D6:123**: every re-derivation returned the wrong value (the 27B agent cannot compute a 2022 FHV join under the
    scan budget). This affects every maintained arm.
* **Maintenance work (T7).**
  * Memory right at the read: ESM 69 % (BB) / 81 % (TLC); TTL / REPLAY 78 / 81 %; NEVER 47 / 56 %.
  * Tokens per read: ESM 12.9k / 12.3k vs TTL 51.3k / 30.2k.
  * Lazy ESM uses 50 % (BB) / 23 % (TLC) of the tokens of its eager every-snapshot replay (25.6k / 54.5k per read),
    with the same or better memory accuracy.

## 4. Figures

* `fig_outcomes.png`: success / wrong / failure per arm (main prompt).
* `fig_cost_contrast.png`: tokens per task (task agent + maintenance) and success, code repositories vs data lakes.
* `fig_wrong_actions.png`: wrong-action rate with 95 % CIs, main vs "rely on memory" prompt.

## 5. Limitations

* **Smaller than planned.** 21 facts / 63 tasks instead of 26 / 78. The 5 TLC High-Volume-FHV facts were dropped after
  the CloudFront block and an ≈ 8-h suspension of the session (`PLAN.md`). CIs are ±10 pp. Most pairwise differences
  between maintained policies are not significant. Fact-clustered CIs (21 clusters) are wider.
* **Maintenance is replayed.** Real policy code ran, but every re-derivation and 24 of 27 judge calls were identical
  Stage-3 requests served from records; only 3 calls were new. Recorded maintenance latency is Stage-3 wall-clock, so
  latency is also re-estimated from tokens (labelled).
* **S is a changing-enriched subset** (≈ 60 % of facts change in FUTURE), so the rates are not base rates.
* **No gone referents** among the selected tasks, so abstention is never the correct answer. Abstention rates measure
  give-ups only.
* **The prompt decides the result.** The main prompt makes the agent re-verify, and memory then saves little. The trust
  prompt was pre-registered here (PLAN.md 01:08). The decision to run it rather than cut it was taken at 10:25, after
  7 BB tasks of the main run had been seen.
* **REPLAY ≡ TTL on these reads**: both re-derive at every read. It is not a distinct data point here.
* **T-sql tests the file choice more than the column name.** DuckDB resolves identifiers case-insensitively, so the
  case-sensitive alias requirement is what makes the stale TLC name (`airport_fee` vs `Airport_fee`) wrong. Most T-sql
  failures are wrong-newest-file picks, in all arms alike.
* **Retrieval is assumed perfect** (one relevant note per task). There is one model and one harness. The s0 derivation
  cost is not charged to any arm.
* **Latency.** Task latency is measured with one request in flight. The TLC process overlapped one BB run for less
  than 30 s at 10:21.
