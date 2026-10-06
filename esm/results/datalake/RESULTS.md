# Stage 3 — ESM on the evolving data lake (NYC TLC, Backblaze Drive Stats)

Date: 2026-10-05. Every number comes from `python -m esm.scripts.report_datalake` (→ `tables.md`, `results.json`,
`records.parquet`, `curves_*.png`, `rederivation_accuracy.png`, `examples.txt`) or from the ledger / logs in
`esm_data_datalake\`. `PLAN.md` holds the plan (written before any maintenance run), the anchoring design and the
timestamped decision log. All LLM calls are cached (`esm_data_datalake/llm_cache`), ledger `llm_ledger.jsonl`.

## 0. Verdict

* **Headline lakes are real-only** (all synthetic events removed; §1). Frozen ESM = Stage 2's `ESM-norepair` (anchored
  evidence + hierarchical deltas; changed / unsure ⇒ re-derivation by the 27B agent), every snapshot, real
  re-derivations.
* **Backblaze (all 57 kept facts, 105 snapshots):** ESM serves a wrong answer on **8.2 % [1.9, 15.4]** of reads vs
  **20.4 %** for blind reuse (paired −12.1 pp [−20.6, −4.5]); natural subset 2.8 % vs 9.0 % (−6.2 [−14.5, +0.2]).
  Cost **53.7k tokens/fact = 1.05 RDE, 511 tokens/read**. The idealised TTL20@oracle reaches the same 8.4 % at
  5 RDE (paired −0.1 pp, −203k tokens/fact). On S, real TTL20/40/100 serve 40–41 % wrong vs ESM 22.7 % (−17 to −19 pp).
* **TLC (R = 115 of 138 kept facts, 229 snapshots; R is the completed prefix of a seeded random order, an unbiased
  random subsample — the frozen ESM could not be run on every kept fact in the budget, §1):** **21.1 % [14.1, 28.4]**
  vs NEVER **33.5 %** (−12.4 pp [−18.0, −7.0]); natural 11.8 % vs 16.3 % (−4.5 [−10.3, +0.1], not significant).
  Cost **167k tokens/fact = 6.5 RDE, 728 tokens/read**. Here ESM is clearly *worse* than the idealised TTL25@oracle
  (11.5 %, +9.6 pp [4.7, 14.9]) at similar cost, and only ties the real TTL25/50/100 on S (−1.4 to −2.8 pp, CIs ±10 pp).
* **Why TLC is hard:** detection works (pilot7 definitions on all 138 TLC facts: FF 1.3 % / FS 2.9 %), but the answer
  source does not. The 27B agent re-derives correctly only **64 %** of the time on TLC (78 % on Backblaze) — running
  aggregates over many files cannot be recomputed under the sql scan budget (D4 53 %, D5 59 %, D6/D7 ≈ 33 % correct).
  93 % of ESM's TLC wrong reads are a **wrong or empty re-derivation that then persists**. On "all data so far" facts
  every append changes the evidence, so the frozen policy re-derives at every append even when the answer does not
  change (TLC D5: 9.9 re-derivations/fact, 98 of them at reads whose stored answer was still right).
* **(c) D3 vs D4 answered as hoped:** D3 partition aggregates were never served wrong on either lake, with 99.8 % (TLC)
  / 96.8 % (BB) of reads served with zero LLM and 0 re-derivations; D4 running aggregates were re-derived when the
  evidence moved (TLC 4.0/fact) — but a third of those reads were then wrong because the re-derivation failed.
* **(a) Real schema events:** at the TLC 2023-02 yellow change (airport_fee→Airport_fee + 6 type changes) ESM acted on
  7/8 affected facts at the event snapshot and served 25 % wrong over the next 10 snapshots (NEVER 100 %,
  TTL25@oracle 32.5 %); similar on green 2023-02 (44 % vs 100 %), the zone-lookup revision (20 % vs 100 %) and the 2025-01
  cbd_congestion_fee additions. Backblaze's SMART-column growth changed no kept fact's answer by itself (§6).

## 1. What was run

| item | value |
|---|---|
| lakes | `datalake/` (read only). TLC: 383 snapshots, s0 = 153, FUTURE = 229. Backblaze: 176 snapshots, s0 = 70, FUTURE = 105. 176 + 168 facts (D1–D8; natural / enriched). |
| environment | `esm/envs/datalake.py` (`DataLakeEnv`, kinds `dl_tlc`, `dl_bb`, `dlsyn_tlc`, `dlsyn_bb`). Package changes are generic and leave Stage 1/2 byte-identical (PLAN.md). |
| variants | **real-only** (headline): synthetic preliminary versions replaced by their final real version, synthetic corrections / re-partitions / directory rename are no-op snapshots (indices kept), the withheld Backblaze day arrives with its month; truth recomputed with `facts_dl.oracle` (reproduces 24/24 stored synthetic series exactly). **as-built** (`dlsyn_*`): only for §7. |
| anchoring | PLAN.md table: sql canonical rows / normalised budget errors; schema as name→type map; head as row set; file_stats values; read_text content-anchored spans; listings anchored on the entries later calls used (+ newest/oldest role, + count role); file calls on the newest file of a series anchored by role. Fixed at 22:19, before any maintenance run, from zero-LLM replays of the first 51 TLC / 12 BB traces. |
| models | qwen3.6:27b (q4) on own Ollama 11595 / 11596 (two RTX 3080), thinking off, T = 0; qwen3.5:9b on the remote 3080 (own Ollama 11597 via ssh tunnel) for the 9B evaluator arm. 11434 never touched. All stopped at 12:08 on 10-05. |
| s0 | 27B agent, ≤ 12 tool calls, NONE sentence. Kept iff answer = oracle: **TLC 138/176 (78.4 %)**, **Backblaze 57/168 (33.9 %)**. |
| sets | ALL = kept facts. **S** = blind stratified subset drawn right after s0 (TLC 20, BB 16; ~60 % changing). **R** = longest completed prefix of the main run's seeded random order (TLC 115 facts; BB = all 57). |
| schedules | every snapshot; every5; every20; bursty (20 % density, bursts of 10); shared re-derivation grid TLC every25 (9 points) / BB every20 (5 points). |
| TTLs | TLC TTL25/50/100 (≈ 6/12/24 months), BB TTL20/40/100 (≈ 20/40/100 months); all re-derivations on the grid. |

Arms with **real** 27B re-derivation: ESM (frozen) every snapshot on R/ALL; on S: TTL×3 (every), ablations
(truncation, unsure-as-fresh, verified repair, 9B evaluator) every; ESM sparse schedules; grid sweep (ESM, ALWAYS, REPLAY,
FILEHASH, MANIFEST, CERT-ZS, LLMDIFF, TTL×3, ESM-noanchor, NEVER). Detection-only `DETECT-anchor-hier` on ALL (both lakes).
**@oracle** (idealised, labelled): NEVER, ALWAYS, TTL×3, REPLAY, FILEHASH, MANIFEST on ALL × all schedules; CERT-ZS on S.

## 2. s0 derivation (`tables.md` T0)

| lake | correct % | wrong % | no answer % | tokens/derivation | LLM calls | kept (changing) |
|---|---|---|---|---|---|---|
| TLC | 78.4 | 7.4 | 14.2 | 33.9k | 8.5 | 138 (54) |
| TLC natural / enriched | 83.0 / 73.9 | | | | | 73 / 65 |
| Backblaze | 33.9 | 15.5 | 50.6 | 70.2k | 12.5 | 57 (13) |
| Backblaze natural / enriched | 43.2 / 23.8 | | | | | 38 / 19 |

By type, single-file facts are easy (TLC D1/D2 100 %, D3 95 %; BB D2 93 %), multi-file aggregates that the sql budget
forbids recomputing are not (TLC D4 45 %, D6 55 %, D7 68 %; BB D3 41 %, D4/D5 23 %, D6 5 %, D7 9 %). Backblaze
facts over "all daily files" are mostly unanswerable within 12 tool calls (no-answer 51 %). The kept set is therefore
biased towards facts the agent can re-check — this applies to every policy equally.

## 3. Main table, every snapshot (`tables.md` T1; CI = bootstrap over facts)

| lake / set | facts | **ESM** served-wrong | NEVER | TTL short@oracle | TTL mid@oracle | TTL long@oracle | FILEHASH@oracle | ESM tokens/fact | ESM tok/read | ESM RDE |
|---|---|---|---|---|---|---|---|---|---|---|
| TLC R (pooled) | 115 | **21.1 [14.1, 28.4]** | 33.5 | 11.5 (9 RDE) | 12.9 (4) | 17.9 (2) | 30.6 | 166.7k | 728 | 6.46 |
| TLC R natural | 62 | **11.8 [4.8, 20.8]** | 16.3 | 8.0 | 8.7 | 10.6 | 15.4 | 167.7k | 732 | 6.55 |
| Backblaze ALL (pooled) | 57 | **8.2 [1.9, 15.4]** | 20.4 | 8.4 (5 RDE) | 10.3 (2) | 19.4 (1) | 20.2 | 53.7k | 511 | 1.05 |
| Backblaze natural | 38 | **2.8 [0.0, 8.2]** | 9.0 | 3.4 | 4.0 | 8.5 | 9.0 | 39.5k | 376 | 0.78 |
| both lakes pooled, R | 172 | **18.7 [13.1, 25.3]** | 31.1 | | | | | 129.2k | 688 | |
| both lakes pooled, R natural | 100 | **9.8 [4.3, 16.8]** | 14.7 | | | | | 119.0k | 654 | |

(TTL short/mid/long = TLC 25/50/100, BB 20/40/100 snapshots.) REPLAY@oracle, MANIFEST@oracle and ALWAYS@oracle are 0 %
by construction at 96–229 RDE (they re-derive at almost every append). Over all 138 TLC kept facts NEVER is 34.3 %, i.e. R
is representative (33.5 %).

Other ESM metrics: stored-wrong episodes never acted on TLC 2.7 %, BB 25.0 %; judge calls/fact 5.3 / 14.1;
re-derivations/fact 3.25 / 0.81; FS (maintenance definition) 0.5 / 0.5 %.

## 4. Paired differences (`tables.md` T2; ESM − B, bootstrap over common facts)

| lake | B | set | schedule | Δ served-wrong pp [CI] | Δ tokens/fact |
|---|---|---|---|---|---|
| TLC | NEVER | R (115) | every | **−12.4 [−18.0, −7.0]** | +167k |
| TLC | NEVER | R natural (62) | every | −4.5 [−10.3, +0.1] | +168k |
| TLC | TTL25@oracle *(idealised)* | R | every | **+9.6 [+4.7, +14.9]** | −66k [−143, +40] |
| TLC | TTL50@oracle / TTL100@oracle | R | every | +8.2 [+3.4, +13.2] / +3.2 [−1.1, +7.5] | +63k / +115k |
| TLC | FILEHASH@oracle | R | every | −9.5 [−15.3, −4.1] | +153k |
| TLC | TTL25 / TTL50 / TTL100 (real) | S (20) | every | −2.8 [−14.1, +8.4] / −2.2 [−12.1, +8.0] / −1.4 [−8.8, +7.3] | +12k / +201k / +271k |
| TLC | ALWAYS = TTL25 = REPLAY = MANIFEST (real, grid) | S | every25 | −6.1 [−16.7, 0.0] | −235k |
| TLC | CERT-ZS / LLMDIFF / FILEHASH (real, grid) | S | every25 | −2.2 [−6.7, 0.0] / −10.0 [−22.2, 0.0] / −20.6 [−37.8, −5.0] | −58k / −49k / +74k |
| Backblaze | NEVER | ALL (57) | every | **−12.1 [−20.6, −4.5]** | +54k |
| Backblaze | NEVER | natural (38) | every | −6.2 [−14.5, +0.2] | +40k |
| Backblaze | TTL20@oracle / TTL40@oracle *(idealised)* | ALL | every | −0.1 [−2.3, +2.7] / −2.1 [−5.4, +1.3] | **−203k** / −49k |
| Backblaze | TTL100@oracle | ALL | every | −11.2 [−19.0, −4.1] | +2k |
| Backblaze | TTL20 / TTL40 / TTL100 (real) | S (16) | every | −18.8 [−38.2, +0.1] / **−17.3 [−33.6, −0.4]** / **−17.1 [−35.2, −2.3]** | −212k / −48k / +10k |
| Backblaze | ALWAYS = REPLAY = MANIFEST (real, grid) | S | every20 | −2.5 [−32.5, +27.5] | −233k |
| Backblaze | CERT-ZS / LLMDIFF / FILEHASH (real, grid) | S | every20 | −2.5 [−25, +21] / **+15.0 [−6.2, +37.5]** / −12.5 [−30, 0] | −22k / −109k / +30k |

* On the shared grid ESM is at least as accurate as every re-deriving guard at 1/3–1/5 of their cost on TLC; on
  Backblaze the grid comparison is too noisy (16 facts × 5 reads), and LLMDIFF (judge on the manifest diff) is nominally
  better (12.5 vs 27.5 %) at 3.4× the cost.
* Real re-derivation makes every frequently re-deriving baseline inherit the agent's errors: real ALWAYS on the grid
  serves 26.7 % (TLC) / 30.0 % (BB) wrong although ALWAYS@oracle is 0 %.

## 5. Ablations, schedules, detection

**Ablations on S, every snapshot** (Δ = ESM − variant):

| variant | TLC served-wrong (Δ) | TLC tokens/fact | BB served-wrong (Δ) | BB tokens/fact |
|---|---|---|---|---|
| ESM (frozen) | 30.5 | 344k | 22.7 | 66k |
| truncation instead of hierarchy | 30.5 (0.0) | 344k | 22.7 (0.0) | 96k |
| unsure ⇒ fresh | 27.8 (+2.7 [−1.4, +8.1]) | **76k** | 33.4 (**−10.7** [−27.7, 0.0]) | 37k |
| verified repair (`ESM-verify`) | 30.5 (0.0); 6 repairs accepted, 6 correct | 338k | **17.1** (+5.5 [0.0, +16.6]); 90 repairs accepted, 90 correct; 0.62 vs 1.06 re-derivations/fact | 85k |
| 9B evaluator (27B deriver) | 30.2 (+0.3) | 283k | 27.5 (−4.8 [−18.7, +4.1]) | 143k |
| no anchoring (grid only) | 25.6 at every25 (ESM 20.6; −5.0 [−13.9, 0.0]) | 157k vs 97k | 18.8 at every20 (ESM 27.5; +8.8 [−11.2, +27.5]) | 139k vs 45k |

Hierarchy vs truncation is irrelevant here (lake observations are short). Anchoring buys cost (no-anchor: 1.6–3.1×
tokens, grid FS 30–33 vs 6 %); without anchoring the replayed listings change at every append (≈ 214 distinct states per
TLC fact in the zero-LLM replay vs ≈ 10 anchored), so no-anchor at every snapshot would mean a judge call per snapshot
(not run; §8). Verified repair is the cheapest way to keep running counts fresh on Backblaze (all 90 accepted repairs
correct).

**Schedules** (S; `tables.md` T4): ESM − NEVER = TLC −17.0 (every5), −23.2 (every20), −17.9 (bursty) pp; BB −10.7,
−13.7, −12.2 pp. Tokens/read rise as reads get sparser (TLC 1.5k every → 3–11k sparse).

**Detection only, pilot7 definitions** (stored answer = s0 K; `tables.md` T5): **TLC ALL (138) FF 1.3 % [0.0, 4.4] /
FS 2.9 % [0.3, 6.8]**; Backblaze ALL (57) FF 25.0 % [2.5, 48.3] / FS 16.1 %. Backblaze FF comes from D4/D8 running
counts (FF 48 / 41 %) whose recorded evidence does not move with the count (stale-file or fixed-directory evidence, §6),
and its FS from D1 type facts whose DuckDB-inferred types flip with the drive population (D1 FS 62 %).

**Re-derivation accuracy** (`tables.md` T6, `rederivation_accuracy.png`): TLC 64.1 % (671 derivations; 72 % answered;
D1/D2/D3 100 %, D4 53 %, D5 59 %, D6 33 %, D7 33 %, D8 77 %); Backblaze 77.8 % (185), falling from 84 % in the first
quarter of FUTURE to 68 % in the last. One TLC re-derivation costs 46.5k tokens (1.8× the s0 average).

## 6. Error taxonomy (`tables.md` T7, `examples.txt`) and concrete examples

TLC (5,589 wrong of 27,251 reads, 119 facts): persisting wrong re-derivation 93.2 % (empty answer 50.8 %, wrong value
42.4 %); change outside the recorded evidence 2.2 % (1 fact); memoised still_valid on a changed state 1.7 %; the wrong
re-derivation read itself 2.7 %. Backblaze (493 of 5,985): persisting wrong/empty re-derivation 42.6 %; **change outside
the recorded evidence 37.1 %** (3 facts); judge still_valid on a changed state 16.6 % + memo 2.8 % (1 fact).

1. **`tlc:D1:12` — schema event caught.** "Type of `store_and_fwd_flag` in the most recent Yellow file" (string). Role
   anchoring follows the newest yellow file; at the 2023-02 file the schema map changes, the judge says "changed:
   string→large_string", the re-derivation answers large_string (correct). Later column additions (2025-01, 2026-06) are
   judged still_valid and memoised: 0 wrong reads, 3 judge calls, 1 re-derivation over 229 snapshots.
2. **`tlc:D5:95` — churn on a stable aggregate.** "Top pick-up zone over all FHV data so far" (264, never changes in
   FUTURE). Every FHV append moves the newest-file evidence; the judge cannot know the new top zone ("full re-aggregation
   needed") → 53 re-derivations at 10–14 LLM calls each; 18 of them returned no answer (12-tool limit), which ESM then
   served until the next append.
3. **`tlc:D4:73` / `tlc:D4:82` — empty re-derivation persists.** "Total base fare / distance over 2022 so far": once 2022
   has more than 3 files, the agent cannot sum under the 3-file budget, returns no answer, and the failed trace becomes the
   new evidence; after 2022 closes nothing moves again, so the empty answer is served for ~200 snapshots.
4. **`tlc:D4:69` — change outside the recorded evidence.** "Latest pickup over all fhvhv data so far": the agent took
   max(pickup) of the three newest files by literal path. New months never touch those files, so the evidence state stays
   at s0 while the truth moves monthly (125 reads); at the 2023-02 type change the judge saw only a type change and said
   still_valid.
5. **`bb:D1:13` — agent picked a stale "latest" file.** After trying a non-existent `data_Q4_2018/`, the agent treated
   `data_Q4_2017/2017-12-31.csv` as the most recent file (the real one was 2018-09-30); its answer happened to be right at
   s0. The evidence is that old file, so later type flips in the actual newest file are invisible (served stale).
6. **`bb:D8:147` — count over all daily files.** "How many daily files have column smart_223_raw" (2000 at s0): the
   agent estimated the count from a truncated `find` listing (150 of ≈ 2,000 files) and a handful of schemas; nothing it
   observed moves when new files arrive → never acted on, wrong from t = 1.
7. **`bb:D4:72` — judge accepts a stale answer.** "Latest date covered so far": after a correct re-derivation
   (2019-04-30) the judge called later changed states still_valid (82 wrong reads) and memoised verdicts covered
   14 more.
8. **`tlc:D3:*` — the good case.** 19 partition-aggregate facts: 99.8 % of reads served with zero LLM, 0.4 judge calls
   per fact, 0 re-derivations, 0 wrong reads, while their months' neighbours kept arriving.

Changes outside the recorded evidence are therefore not rare on lakes (TLC 1 fact, BB 3 facts, 37 % of BB wrong reads):
they come from the agent generalising from partial observations (newest three files, one quarter directory, a stale
file) — exactly the "reason from partial observations" situation the scan budget creates.

## 7. Synthetic events (as-built lake; flagged; not in any headline number; `tables.md` T10)

Affected facts (truth or relevant files touched by a synthetic event) kept at s0 on the as-built lake: TLC 49 (of 85),
Backblaze 12 (of the 18 affected facts kept on the real lake). Only the ESM **detector** (27B judge, anchored evidence) and
zero-LLM baselines were run here (the frozen ESM with real re-derivation was not, §8). The detector flagged **100 %** of
the facts whose truth a synthetic correction / late day changed, at the event snapshot (TLC 5 corrections, BB 2
corrections + the late day); spurious flags at the event: TLC 1–6 facts (the directory rename and re-partitions — which
change no truth — produced 6 / 1 / 6 spurious flags), BB 0. NEVER serves 71.5 % (TLC) / 36.8 % (BB) of these facts'
reads wrong; TTL25@oracle 26.7 %, TTL20@oracle 12.2 %.
## 8. Skipped, approximated, deviations

* **Frozen ESM on every kept TLC fact:** not affordable. 119 of 138 TLC facts were run (S first, then a seeded random
  order, then two extension workers over the same permutation until 11:45); the headline TLC set is the 115-fact completed
  prefix R. 19 TLC facts never got an ESM run. Backblaze: all 57.
* **Real-cost REPLAY / FILEHASH / MANIFEST / CERT-ZS / LLMDIFF / ALWAYS** only on the shared grid on S (TLC every25,
  BB every20), not at every snapshot (REPLAY/MANIFEST would re-derive at almost every append: 96–229 per fact).
  At every snapshot they exist only as @oracle (CERT-ZS@oracle on S only).
* **Ablations, 9B evaluator, sparse schedules: S only** (20 + 16 facts; CIs wide). **No-anchoring** only on the grid; its
  every-snapshot cost was not estimated by a separate zero-LLM run beyond the 51-fact replay quoted in §5.
* **Backblaze grid / TTLs** coarsened from every10 / TTL10–50 to every20 / TTL20/40/100 (12-call derivations).
* **Synthetic analysis:** detector + zero-LLM baselines only; Backblaze restricted to SYN facts kept on the real lake;
  the as-built Backblaze MANIFEST@oracle run (CPU only, ≈ 2.5 h left) was stopped and is not in T10.
* **Anchoring rules** were refined at 22:19 on the basis of zero-LLM replays of the first kept s0 traces (PLAN.md);
  no maintenance run had started. Their value is still tested only by the no-anchor grid ablation.
* **ESM-verify** is the Stage-2 blind-verifier arm; on TLC it accepted only 6 repairs (all correct) and is identical to
  the frozen arm in served-wrong.
* **Infrastructure:** the first ESM main TLC job failed to start (a `\r` in an edited queue line) and the grid job that
  ran instead was stopped and re-queued (no work lost); one ledger line garbled by concurrent appends; the supervising
  session was interrupted by a quota limit around 23:30 (queues kept running).
* **Base rates:** natural subsets are small (TLC R natural 62, BB 38); Backblaze facts are mostly the answerable ones
  (34 % kept).

## 9. Realised LLM budget (`esm_data_datalake/llm_ledger.jsonl`, non-cached calls)

| model | role | calls | prompt tokens | completion tokens |
|---|---|---|---|---|
| qwen3.6:27b | derivation agent (s0 both variants, re-derivations, grids) | 12,157 | 58.48M | 1.93M |
| qwen3.6:27b | ESM / detector judge (incl. screens) | 4,262 | 5.09M | 0.20M |
| qwen3.6:27b | LLMDIFF judge | 230 | 0.76M | 0.01M |
| qwen3.6:27b | repair verifier | 98 | 0.38M | 0.005M |
| qwen3.6:27b | CERT-ZS extraction | 36 | 0.12M | 0.01M |
| **qwen3.6:27b total** | | **16,783** | **64.8M** | **2.16M** |
| qwen3.5:9b | 9B evaluator arm (judge) | 306 | 0.37M | 0.01M |

Plan: ≈ 13–14k 27B calls; realised 16.8k (derivations dominate: Backblaze derivations average 12.5 calls). First call
10-04 21:21, last 10-05 12:05 (14.7 h). Throughput was decode-bound at ≈ 22–30 tok/s per GPU; Ollama ignores
`NUM_PARALLEL` for this model.

## 10. Files

`PLAN.md` (plan, anchoring, decisions, budget), `tables.md` / `results.json` (all tables T0–T10), `records.parquet`
(one row per lake × policy × schedule × fact × read), `curves_dl_{tlc,bb}_{ALL,S}_*.png`, `rederivation_accuracy.png`,
`examples.txt`. Raw data: `esm_data_datalake/{dl_tlc,dl_bb,dlsyn_tlc,dlsyn_bb}/{derivations*.jsonl, sim/, obs/,
sub_*.json}`, `truth_*.json`, `llm_cache/`, `llm_ledger.jsonl`, `queue_*.txt/.done/.log`, `decisions.log`.
Reproduce (all cached): the commands in `queue_*.txt`, then
`ESM_DATA=...\esm_data_datalake ESM_STAGE=datalake python -m esm.scripts.report_datalake`.
