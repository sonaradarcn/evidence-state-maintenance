# Stage 3 — ESM on the evolving data lake: plan and LLM budget

*Lab notebook, kept as written during the runs: the plan fixed before the first run, followed by the timestamped decision log. Server ports, hardware incidents and deviations are recorded as they happened; the final numbers are in RESULTS.md.*

Written 2026-10-04 ≈ 21:45, after the environment code and before any maintenance run. Only the s0 derivations had
started (21:23; they do not depend on any policy or anchoring choice). Time budget ≈ 18 h wall-clock (21:10 on 10-04 →
≈ 15:00 on 10-05); the last ≈ 3 h are kept for analysis and writing. Decisions taken during the run are appended to the
log at the end (also `esm_data_datalake/decisions.log`, timestamped).

## Environment

* **Lakes** (`datalake/`, read only; bulk data on D:): NYC TLC (383 snapshots; s0 = index 153; FUTURE = 229) and
  Backblaze Drive Stats (176 snapshots; s0 = index 70; FUTURE = 105). Facts: TLC 176, Backblaze 168 (types D1–D8,
  natural / enriched subsets). Tools: ls, find, file_schema, head, file_rowcount, file_stats, sql (budgeted), read_text,
  grep, schema_diff. Plugged into the package as `esm/envs/datalake.py` (`DataLakeEnv`, kinds `dl_tlc`, `dl_bb`,
  `dlsyn_tlc`, `dlsyn_bb`). Package changes are generic and keep Stage 1/2 behaviour byte-identical: an optional
  trace-aware anchoring hook (`env.anchor_calls`), read sets that may depend on the version (`read_set(trace, world)`),
  CERT-ZS prompt subject / tool API supplied by the environment, `bursty` = 20 % read density for horizons ≠ 400.
* **Headline variant = REAL-ONLY lakes** (`dl_*`). Every synthetic maintenance event is removed: a preliminary file
  version is replaced by its final real version from its arrival on; synthetic corrections, re-partitions and the
  directory rename become no-op snapshots (indices are kept, so FUTURE is still 229 / 105 snapshots); the withheld
  Backblaze day arrives with its own month. Truth is recomputed with `facts_dl.oracle` (exact full-scan profiles); the same
  code reproduces 24/24 stored oracle series of the synthetic lake exactly (`esm/scripts/dl_check.py`). Effect: 41 TLC and
  31 Backblaze facts get a different series (38 / 31 a different s0 value); changing facts: TLC 79 (synthetic lake 101),
  Backblaze 74 (86).
* **Synthetic variant** (`dlsyn_*`, the lake exactly as built) is used only for the separately reported synthetic-event
  analysis, on the facts whose truth series or s0 evidence the synthetic events touch.

## Drift-robust observations (anchoring), fixed before any maintenance run

Mode `anchored` (ESM). Each recorded call becomes a query whose normalised output is the evidence:

| tool | anchored observation |
|---|---|
| sql | header + rows; rows sorted canonically unless the query has ORDER BY; floats rounded to 10 significant digits; a quoted file literal that no longer exists is re-resolved by key (below) |
| file_schema | {column: type} printed in name order (column order ignored) |
| head | header + data rows as a sorted set (compared by content, not position) |
| file_rowcount | the value (a re-partitioned partition = sum over its part files) |
| file_stats | rows / min / max / null_count values only (no provenance wording) |
| read_text | content-anchored span (distinctive first/last visible lines), exactly as for code reads |
| grep | line numbers stripped, sorted set |
| schema_diff | sorted lines |
| ls / find | **listing anchored on use**: presence of the entries that later calls used (path / dir in their arguments, matched by a glob literal there, or containing the stored answer); for a used entry that was the newest / oldest member of its file series (digit runs → `#`) within the listing, that series' newest / oldest entry; if the stored answer is an integer equal to the number of a series' entries in the listing, that count. A listing nothing was taken from contributes an empty observation. |

* **Key resolution** (file_* calls, head, sql literals, read_text): the exact logical path if it exists, else the files of
  the same (dataset, month) partition, else the unique file with the same basename. Only the synthetic variant ever needs
  it (re-partition, directory rename).
* **Role anchoring**: a file-addressed call (file_schema / head / file_rowcount / file_stats) on the newest member of its
  file series is anchored as "the newest file of that series" — the replay follows each newly arrived file — unless the
  file was picked through a period-restricted glob in the trace (e.g. `yellow_tripdata_2022-*`) or its period token
  (YYYY / YYYY-MM / YYYY-MM-DD) appears in the question. A listing entry covered by a role-anchored call contributes no
  separate observation.
* Why: in a lake almost every snapshot appends files, so plain sorted listings (and fixed file references for "most
  recent file" questions) give a new evidence state at nearly every snapshot. On the first 7 TLC traces the original
  recording had 184 distinct non-s0 states per fact (every snapshot), the anchored one 10 before the last two rules.
* Mode `original` (ablation "no anchoring", pilot7 recording): every call as recorded; only the lake's own line-number
  normalisation of grep / read_text.

## Agent and models

* Deriver: qwen3.6:27b, lake tool loop (≤ 12 tool calls, thinking off, T = 0), system prompt with the lake description,
  the sql budget, and the Stage-2 NONE sentence ("If what the question refers to does not exist in this snapshot …,
  call answer(value='NONE')"). A fact is kept iff its s0 answer matches the oracle (canonicalised). Success is reported per
  lake × type × subset. Stored K = the agent's answer; evidence = its trace; citations = zero-LLM auto-citations.
* Evaluator (frozen, Stage 2): `ESM-norepair` = anchored evidence + hierarchical deltas + 27B judge (pilot7 prompt);
  "changed" / "unsure" / too-large / parse-fail ⇒ re-derivation by the 27B agent; memoised per (anchor, state).
* Servers: own Ollama 11595 (GPU0) and 11596 (GPU1), qwen3.6:27b q4, ctx 16k; a second machine's Ollama
  (qwen3.5:9b) via ssh tunnel 11597 for the 9B evaluator arm. Port 11434 is never touched. All stopped at the end.
* Measured throughput (s0, first 15 min): generation-bound at ≈ 30 tok/s per GPU; ≈ 13 calls/min total for multi-turn
  derivations (one conversation in flight per server keeps the KV cache warm); judge calls (single short prompts) can be
  pipelined. Planning figure: **≈ 13–18 27B calls/min ⇒ ≈ 11–13k 27B calls** in the GPU window.

## Subsets, schedules, arms

* **ALL** = kept facts of each lake. **S** = stratified subset per lake drawn by seed right after s0 (before any
  maintenance run, blind to outcomes): types round-robin, alternating natural / enriched, changing facts
  preferred (~60 %) where available → 20 TLC + 16 Backblaze facts. Rates on S are not base rates; S is for paired
  comparisons and ablations.
* **Schedules**: `every` (229 / 105 reads), `every5`, `every20`, `bursty` (20 % density in bursts of 10, seed 7).
  **Shared re-derivation grid**: TLC every 25 snapshots (t = 25 … 225, 9 points), Backblaze every 20 (t = 20 … 100,
  5 points; first planned as every 10, see the log); ALWAYS = re-derive at every grid read.
* **TTL** (snapshot units, matched to cadence: TLC has ≈ 4 snapshots per month, Backblaze 1): TLC TTL25 / 50 / 100
  (≈ 6 / 12 / 24 months), Backblaze TTL20 / 40 / 100 (≈ 20 / 40 / 100 months). All their re-derivations fall on the grid.

| priority | arm | facts | schedules | est. 27B calls |
|---|---|---|---|---|
| 1 | s0 derivation | 344 | – | ≈ 1.9k (5.5 calls / derivation) |
| 2 | ESM (frozen) | ALL | every | judge ≈ 2k + re-derivation ≈ 2.5k |
| 3 | grid derivations (ALWAYS, TTL×3 at every read; REPLAY / FILEHASH(manifest) / CERT-ZS / LLMDIFF(manifest diff) / ESM / NEVER on the grid schedule, real re-derivations shared) | S | grid, every (TTL) | ≈ 2.6k + ≈ 0.4k LLMDIFF judge + 50 CERT-ZS |
| 4 | detection only, pilot7 definitions (`DETECT-anchor-hier`) | ALL | every | ≈ 0.8k (shares ESM's a0 transitions) |
| 5 | synthetic-event analysis (`dlsyn_*`): ESM, NEVER, TTL, @oracle baselines | affected facts | every | ≈ 1.5k |
| 6 | ablations: truncation, unsure-as-fresh, verified repair (every); no anchoring (grid; its every-read cost estimated zero-LLM from state counts) | S | every / grid | ≈ 1.2k |
| 7 | 9B evaluator (`ESM-norepair-9B`, remote 9B judge, 27B re-derivations) | S | every | 27B ≈ 0.3k |
| 8 | ESM on sparse schedules (every5, every20, bursty) | S | sparse | ≈ 1k |
| 9 | REPLAY / CERT-ZS + real re-derivation at every read | S | every | only if time remains |
| – | NEVER, ALWAYS@oracle, TTL*@oracle, REPLAY@oracle, FILEHASH@oracle, CERT-ZS@oracle, ESM@oracle (idealised, labelled) | ALL (CERT-ZS: S) | all | 0 |

Total ≈ 13–14k 27B calls: at the upper end of the window. Lower items are cut first; whatever is cut is listed in
RESULTS.md.

## Metrics (as Stage 2)

Served-wrong (primary) with bootstrap CIs over facts (B = 1000); paired differences vs baselines (B = 2000) on the same
facts and schedule at matched cost; tokens per fact and per read; RDE (unit: the fact's own s0 derivation tokens);
FF / FS (maintenance and pilot7 detection definitions); stored-wrong episodes never acted on; re-derivation accuracy over
time; per lake / type / subset. Special analyses: (a) real schema events (TLC 2023-02 rename + type changes, 2025-01
cbd_congestion_fee, 2026-06 request_source; Backblaze SMART growth incl. 2023 metadata columns; the 2024-02 zone-lookup
revision); (b) synthetic events, separately; (c) D3 partition aggregates vs D4 running aggregates; (d) error taxonomy with
6–10 concrete examples, including changes outside the recorded evidence. Headline numbers = real-only lakes, natural and
pooled, per lake.

## Decision log

(appended during the run; the machine-readable copy with timestamps is `esm_data_datalake/decisions.log`)

* **21:23–21:40, s0 scheduling.** s0 started with 3 interleaved agent conversations per server (10 calls/min); restarted
  with one conversation per server (TLC → GPU0, Backblaze → GPU1) so that the single-slot server keeps the conversation's
  KV cache. `OLLAMA_NUM_PARALLEL=2` was tested and is ignored for this model (21.8 vs 21.1 tok/s). Backblaze derivations
  average 12–14 LLM calls (many hit the 12-tool limit); TLC 5–8. Nothing was lost (all calls cached).
* **22:00, FILEHASH vs MANIFEST.** FILEHASH = content hash of the files the trace read (sql literals/globs resolved at
  derivation), as specified ("manifest hash of files touched"). The variant that also hashes the listings the trace
  consulted (find globs, ls directories, sql globs) is reported as `MANIFEST` (zero-LLM @oracle and on the grid); it flags
  at almost every append. The LLM-judge-on-manifest-diff baseline (`LLMDIFF`) sees that listing-inclusive manifest diff
  (added / removed / replaced files with row counts and schema changes; unified diffs for docs and the lookup table).
* **22:19, anchoring refinements (before any maintenance run)** from zero-LLM replays of the first 51 TLC / 12 Backblaze
  kept traces: (1) listing roles use the file series restricted to the period the question names ("the 2022-02 monthly
  file" → no newest-role; "2022 so far" → the newest 2022 file); (2) sql scan-budget error texts are normalised (their file /
  row counts grow with every append); (3) the "entry contains the stored answer" listing rule applies only when no entry
  is referenced by later calls; (4) a role-anchored `head` on the newest file observes only its header; (5) series order:
  4-digit (year-like) digit runs first (`data_Q3_2018` → (2018, 3)). Effect on 51 TLC facts: 515 distinct anchored
  non-s0 states against 305 truth transitions (original recording: ≈ 214 states per fact, i.e. every snapshot).
* **22:19, cost finding and run order.** Truth transitions concentrate in running aggregates / coverage facts that change
  at nearly every append (over all 344 facts: TLC D8 815, D4 466; Backblaze D8 1,581, D4 517 transitions). Any policy
  that keeps them fresh must re-derive at each change. The frozen ESM with real re-derivation on every kept fact may
  therefore exceed the budget. The main ESM run processes S first (complete), then every other kept fact in a seeded
  random order (`--order random:7`, incremental saves). If it cannot finish, the "ALL" numbers are reported on the
  longest completed prefix of that random order (an unbiased random subsample), with NEVER / @oracle on the same facts and
  on all facts.
* **Grid.** TLC every 25 (TTL25/50/100); Backblaze coarsened to every 20 (t = 20 … 100; TTL20/40/100) because one
  Backblaze derivation costs ≈ 12 LLM calls.
* **23:35, CPU baselines parallelised.** The zero-LLM @oracle baselines were split over six CPU queues (profiling: 6–19 s
  per Backblaze fact × policy × schedule, GIL-bound in one process). Backblaze REPLAY@oracle / CERT-ZS@oracle remained
  slow (sql replays over daily CSVs at every snapshot); CERT-ZS@oracle was moved off the GPU queue at 07:15 so that GPU1
  was not blocked.
* **≈ 23:30, supervision interrupted** by a model quota limit for a few minutes; the detached queues kept running.
* **23:41, TLC s0 done (138/176 kept).** The queued ESM main job failed at start (a `\r` in a sed-edited path split the
  queue line). Queue files were rewritten with Python; the grid-derivation job that had started instead was stopped (its
  derivations kept) and re-queued after ESM main, which started ≈ 23:50 with deadline 05:00.
* **01:17, observation:** "all data so far" facts get a new anchored state at each append of their dataset and the judge
  cannot know the new aggregate ⇒ one re-derivation per append (≈ 13 LLM calls, ≈ 40 % hit the 12-tool limit).
* **02:10–02:30, synthetic variant.** TLC: as-built s0 for the 85 affected facts (49 kept; mostly cache hits). Backblaze:
  restricted to affected facts kept on the real lake (18 → 12 kept on the as-built lake), run after the real BB s0.
  Only the ESM detector + zero-LLM baselines were run on the as-built lakes (budget).
* **02:28, BB s0 done (57/168 kept); BB ESM main complete on all 57 at 03:56.**
* **03:38–09:51, load balancing** between the two GPUs: TLC grid points t = 225 … 125 derived on GPU1 (queue F) while
  queue A worked upward; TLC ablations (queue H) and the TLC synthetic detector + every20 (queue J) on GPU1.
* **06:28, TLC ESM main stopped at its deadline (81/138 facts).** 10:38–12:06: two extension workers (queues K, L) ran
  the same frozen policy on the next facts of the same seeded permutation (deadline 11:45 for new facts); L's output was
  merged. Final: 119/138 TLC facts, completed prefix R = 115.
* **12:08, all GPU work finished;** Ollama 11595 / 11596 / remote 11597 and the tunnel stopped. 11434 never touched.

## Realised budget (from `esm_data_datalake/llm_ledger.jsonl`; non-cached calls only)

| model | role | calls | prompt tokens | completion tokens |
|---|---|---|---|---|
| qwen3.6:27b | derivation agent (s0 both variants, re-derivations, grids) | 12,157 | 58.48M | 1.93M |
| qwen3.6:27b | ESM / detector judge (incl. screens) | 4,262 | 5.09M | 0.20M |
| qwen3.6:27b | LLMDIFF judge | 230 | 0.76M | 0.01M |
| qwen3.6:27b | repair verifier | 98 | 0.38M | 0.005M |
| qwen3.6:27b | CERT-ZS extraction | 36 | 0.12M | 0.01M |
| **qwen3.6:27b total** | | **16,783** | **64.8M** | **2.16M** |
| qwen3.5:9b | 9B evaluator arm (judge) | 306 | 0.37M | 0.01M |

Planned ≈ 13–14k 27B calls; realised 16.8k (Backblaze derivations averaged 12.5 calls, the plan assumed 5.5). LLM
wall-clock 10-04 21:21 → 10-05 12:05 (14.7 h). One ledger line is garbled (concurrent appends).
