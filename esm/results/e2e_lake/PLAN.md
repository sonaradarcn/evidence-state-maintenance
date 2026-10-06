# B3-lake: end-to-end task evaluation on the evolving data lakes (PLAN, written before any task run)

*Lab notebook, kept as written during the runs: the plan fixed before the first run, followed by the timestamped decision log. Server ports, hardware incidents and deviations are recorded as they happened; the final numbers are in RESULTS.md.*

Date: 2026-10-06, 01:20. Mirrors the code-repository end-to-end evaluation (`esm/results/e2e/`, code `esm/e2e/`) on the
Stage-3 data lakes (`esm/results/datalake/`), where re-deriving a fact is expensive (Stage 3: one Backblaze derivation
≈ 12.5 LLM calls / 70k tokens, one TLC re-derivation ≈ 46k tokens; 27B re-derivation accuracy 64 % TLC / 78 % BB).
Code: `esm/e2e_lake/`. Data: `esm_data_e2e_lake/`. Results: `esm/results/e2e_lake/`.

## Budget (fixed before running)

| item | budget |
|---|---|
| wall-clock | ≈ 12 h (01:00 → ≈ 13:00 on 10-06), incl. re-creating the lake store and writing |
| GPU | GPU 1 only, own Ollama on port 11651 (`CUDA_VISIBLE_DEVICES=1`, qwen3.6:27b q4, ctx 16k, 1 slot). 11434 and the other session's server on GPU 0 (11621) are never touched. Stopped at the end. |
| new 27B calls | task agent ≈ 240 unique runs (78 tasks × ≈ 3 distinct memory notes) × ≈ 6 calls ≈ 1,400 calls; maintenance ≤ 100 new judge calls (ESM lazy) + re-derivations only where no Stage-3 record exists (expected: none, see below). Ceiling 3,000 new calls. At ≈ 6–9 s per call ≈ 3–4 h of GPU. |
| network / disk | re-download of the lake sources needed up to the last task snapshot (TLC ≤ 2024-03, Backblaze ≤ 2024 Q4: 59 GB raw, deleted after subsampling; ≈ 4 GB stored under `esm_data_e2e_lake/lake_data`) |
| cut order if over budget | (1) the pre-registered secondary 'trust' prompt variant, (2) TTL-mid arm runs, (3) nothing else (main arms are required) |

## Precondition found at start: the lake store is gone

The bulk lake data (`datalake_data`: content-addressed store, snapshot manifests, Wayback caches) was deleted on
2026-10-05 together with the rest of the original data drive. Only the catalogue survived (`data/datalake_catalog`). It is re-created:

* `fetch_lake.py`: re-downloads each source (CloudFront / Backblaze B2), re-applies `datalake/ingest.py`'s deterministic
  subsampling (same functions), and stores each file under its catalogued sha256. Checks: Backblaze members must reproduce
  the catalogued sha256 byte for byte; TLC sources must reproduce the catalogued raw sha256 and the subsampled row count /
  schema, and the re-written file's sha256 is compared with the catalogue. First checks (green 2019-01, data_2013.zip,
  fhv 2019-02/03): all byte-identical.
* `build_snaps_lake.py`: re-builds the snapshot manifests with `datalake/build_snapshots.py`'s unchanged event logic;
  the rebuilt event lists equal `datalake/manifests/*_events.json` on all 383 / 176 events (snap id, time, kind, synthetic
  flag, put paths). SYNTHETIC preliminary / re-partition blobs are not re-created: the real-only variant used here never
  shows them.
* `fetch_docs_lake.py`: re-fetches the documentation / lookup versions (Wayback) and compares sha256 with the catalogue.
* Files not yet present when a tool needs them are fetched on demand (blocking; wait excluded from measured tool time).

## What is real and what is replayed

| component | status |
|---|---|
| lakes | real-only variant (`esm.envs.datalake.VariantLake('real')`), re-created as above |
| facts (question, s0 answer, s0 trace) | reused: Stage-3 kept s0 27B derivations |
| truth at t | Stage-3 truth series (`truth_<lake>_real.json`, exact DuckDB full-scan profiles); validated here by `facts_dl.oracle_direct` (one independent DuckDB statement) at every (fact, t) |
| maintenance at the task snapshots (lazy: reads only at the 3 task snapshots) | real policy code (`esm` package: NEVER, TTL, REPLAY, frozen `ESM-norepair`). A judge call / re-derivation whose identical request exists from Stage 3 is served from the Stage-3 cache / derivation store (counted at its recorded tokens, marked recorded); everything else is called now on GPU 1 |
| ESM-eager (secondary) | replayed: the Stage-3 every-snapshot frozen ESM run's served answer at t; maintenance tokens = recorded tokens in (t_prev, t] |
| task agent | real, new: qwen3.6:27b tool loop over the lake tools, every call made now |
| success checks | real, deterministic, against the lake snapshot at t (oracle value / executed SQL / manifest) |

## Design (fixed before running)

* **Facts.** The Stage-3 blind stratified subset S (drawn right after s0, before any maintenance run; ≈ 60 % changing in
  FUTURE), restricted to the fact types this evaluation targets: D1, D2, D3, D4, D6, D8 (D5 top-k and D7 data-quality are
  left out; optional extension only if budget remains, reported separately). 14 TLC + 12 Backblaze = **26 facts**.
  Reason for S: it is the only set with recorded 27B re-derivations at every grid snapshot, so TTL / REPLAY / ESM
  maintenance at the task snapshots needs no new (expensive) re-derivation. S over-represents changing facts; pooled rates
  are not base rates.
* **Task snapshots.** TLC t = 25, 50, 100 snapshots after s0 (2022-10, 2023-04, 2024-04); Backblaze t = 20, 40, 80
  (2020-03, 2021-08, 2024-08). These are the Stage-3 shared re-derivation grid points (TLC every 25, BB every 20); the
  request's example offsets (+20/+50/+100, +15/+40/+80) were moved to the nearest grid points for that reason.
  **78 tasks** (26 facts × 3) planned; 63 run (21 facts × 3) after 5 TLC fhvhv facts were cut, see the decision log.
* **Task types** (the memory note can supply exactly what the task needs):

  | task type | fact types (n facts) | task | success check |
  |---|---|---|---|
  | T-sql | D2 field mapping (TLC 2, BB 2) | write one DuckDB `SELECT` over the most recent file of the dataset returning one row, one column: the number of distinct non-null values of the column that holds concept X, aliased with that column's exact (case-sensitive) name, as used by downstream code | the query is **executed** with the lake's sql tool on the snapshot at t: it must read the most recent file, its single output column must be named exactly as the true column at t, and its value must equal the reference (same aggregate over the true column) |
  | T-report | D3 partition aggregates (TLC 3, BB 2), D4 running aggregates (TLC 2), D6 joins (TLC 2, BB 1) | report the statistic for a report (the fact's question) | canonicalised value equals the oracle value at t |
  | T-files | D4 latest-date facts (BB 2) | decide which daily file to load to analyse the most recent day of data (of 2018 / of all data) | the submitted logical path equals the manifest's latest daily file (of that year) at t |
  | T-question | D1 schema types (TLC 3, BB 3), D8 coverage counts (TLC 2, BB 2) | answer the schema / coverage question | canonicalised answer equals the oracle value at t |

  If the referent is gone at t (oracle NONE), the correct action is `abstain` (or answer NONE).
* **Arms** (same task prompt; memory = one note: the fact's question + the policy's served answer at t):
  NO-MEMORY (derive from scratch within the same tool budget), NEVER (blind reuse of the s0 answer),
  **TTL** (lake TTL: TLC 25, BB 20 snapshots, lazy: re-derive if the answer is ≥ TTL old; at these reads this equals
  re-deriving at every read), TTL-mid (TLC 50, BB 40; secondary), REPLAY (lazy: replay the current trace as recorded, any
  change ⇒ re-derive), **ESM** (frozen `ESM-norepair`, lazy), ESM-eager (replayed, secondary), ORACLE memory (truth at t;
  idealised, labelled).
* **Agent.** qwen3.6:27b, T = 0, thinking off, the Stage-3 lake tools (ls, find, file_schema, head, file_rowcount,
  file_stats, sql with the same scan budget, read_text, grep, schema_diff), **≤ 12 tool calls** (the derivation budget),
  then `submit` or `abstain`. Identical prompts are cached, so arms whose notes are identical share literally one run.
* **Prompts.** Main: the note is introduced as "notes you recorded earlier while working with this lake; the data may have
  changed since" (as in the code-repo e2e main prompt). **Pre-registered secondary** (decided now, before any run here,
  because the code-repo e2e showed the prompt decides how much memory matters): the 'trust' variant ("verified facts …
  rely on them instead of re-checking") for the memory arms; NO-MEMORY row shared.
* **Outcomes.** success; wrong action (submitted something that fails the check); failure (abstained although possible,
  or nothing submitted); abstention rate reported separately.
* **Metrics.** success / wrong / failure / abstention rates with bootstrap CIs over tasks (B = 2000; fact-clustered CI as a
  check); tokens per task = task tokens + maintenance tokens at that read; latency per task = measured task latency +
  maintenance latency (measured for new calls; recorded Stage-3 latency for reused ones, and re-estimated from tokens on
  this server, labelled); per lake, per fact type / task type, per snapshot offset; paired differences vs NO-MEMORY and vs
  NEVER. Contrast table: code-repo e2e (cheap re-derivation) vs lake e2e (expensive re-derivation): NO-MEMORY task tokens,
  memory-arm task tokens, maintenance tokens, success / wrong.

## Decision log

* 00:58 start. the original data drive lake store found deleted; catalogue in `data`. Re-creation started 01:00 (59 GB, 4 workers ×
  6 range segments); docs re-fetch started; snapshot manifests rebuilt and verified (01:05). Ollama 11651 / GPU 1 started
  01:12 (other session's 11621 on GPU 0 untouched).
* (correction of the times above: Ollama 11651 started 01:05; the plan text was written ≈ 01:08, before any task run.)
* 01:06 bulk fetcher switched from threads to processes (Backblaze subsampling is GIL-bound). 01:13 docs re-fetch done:
  all 33 documentation / lookup versions byte-identical to the catalogue (sha256).
* 01:34 Backblaze sources complete (39 zips; every member byte-identical to the catalogue). TLC: 104 sources done (all
  raw-sha / sub-sha / rows / schema identical), then **CloudFront answered HTTP 403 to every request** (rate block after
  ≈ 8 parallel range streams). The fetcher was stopped; partial TLC downloads were deleted (curl wrote the 403 body into
  part files: no corrupted blob reached the store because none finished; `-f` added to curl).
* **01:45 → 09:45: the supervising session was suspended for ≈ 8 h** (no work ran; the machine/session paused). At 09:55
  CloudFront answered again. Remaining wall-clock budget ≈ 3 h (to ≈ 13:00), so the design is cut as follows
  (decided now, before any task-agent or maintenance run):
  1. **TLC is restricted to the 9 selected facts that do not need the High Volume FHV (fhvhv) dataset** (the 26-GB part of
     the TLC download that is still missing): tlc:D1:12, D2:33, D3:45, D3:56, D3:65, D4:87, D6:112, D6:123, D8:155.
     The 5 fhvhv facts (D1:6, D1:13, D2:28, D4:73, D8:167) are dropped. fhvhv files stay fetchable on demand (an agent
     that opens one waits; the wait is excluded from tool time).
  2. Backblaze keeps all 12 facts. Total **21 facts, 63 tasks**.
  3. The pre-registered 'trust' variant is run only if time remains after the main run (cut order item 1).
  4. Remaining TLC non-fhvhv files (≤ 2024-03) re-fetched with 2 workers.
* 10:00–10:21 setup (validation: Stage-3 truth = `oracle_direct` on 60/63 (fact, t); the 3 mismatches are bb:D4:72, where
  `oracle_direct`'s string max over the date column picks a real file's `6/17/19`-formatted date; the truth series and
  the manifest agree), maintenance (BB 2 new judge calls, TLC 1; every re-derivation recorded in Stage 3), BB agent run
  started 10:02; TLC agent run chained after it (a premature concurrent TLC start at 10:21 was killed after < 30 s; one
  BB run overlapped it).
* 10:25 (decided after seeing 7 BB tasks of the main run; the variant itself was pre-registered): the trust variant is
  run after the main runs (memory-arm runs are expected to be short), instead of being cut.
* 11:33 BB main done (105 unique runs); 12:20 TLC main done (79); 13:10 trust variant done (109); Ollama 11651 stopped
  13:12. Report generated (zero LLM).

## Realised budget (2026-10-06 13:15)

| item | plan | realised |
|---|---|---|
| wall-clock | ≈ 12 h (to ≈ 13:00) | 00:58 → 13:20 ≈ 12.4 h, of which ≈ 8 h (01:45 → 09:45) the session was suspended; ≈ 4.4 h of work |
| lake re-creation | 59 GB | Backblaze 39 zips (≤ 2024 Q4) + TLC 189 non-fhvhv files (≤ 2024-03) + 33 docs, all byte-identical; 2.8 GB stored; fhvhv not fetched (blocked, then cut) |
| new 27B calls (GPU 1, port 11651) | ≈ 1,400 task + ≤ 100 maintenance; ceiling 3,000 | **2,001**: 1,998 task-agent calls (9.45M prompt + 0.30M completion tokens, 3.1 h LLM time) + 3 ESM judge calls |
| maintenance reused from Stage 3 | – | 24 judge calls + every re-derivation at the task snapshots |
| agent runs | ≈ 240 unique | 184 unique runs for 504 main (arm, task) pairs + 109 for 378 trust pairs |
| tasks | 78 | 63 (5 TLC fhvhv facts cut) |
| servers | own Ollama 11651 / GPU 1 | started 01:05, stopped 13:12; 11434 and the other session's 11621 / GPU 0 never touched |
