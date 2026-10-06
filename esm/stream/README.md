# Stage 4: end-to-end task-stream SIMULATION (zero LLM, zero GPU)

This stage simulates one persistent agent over a project's lifetime: a stream of tasks that read stored knowledge, mixed
with repository commits, at realistic times. It asks what each maintenance policy costs in total and how many tasks it
answers correctly.

**It is a simulation.** No model was called in this stage.

* Every served answer and every token comes from **decisions already recorded** in the held-out stage (Stage 2):
  * `esm/results/heldout/records.parquet`, schedule `every`;
  * the recorded 27B re-derivations in `esm_data_heldout/derivations*.jsonl`.
* Task arrival times come from **real GitHub issue streams** (`data/events_github.parquet`).
* The tasks themselves are **synthetic**. Which facts a task reads, and how many, are random draws.

## Files

| file | role |
|---|---|
| `prep.py` | Extracts the kept facts, their oracle series, the recorded re-derivations (with each answer's validity at every FUTURE commit) and certificate set-up tokens → `results/stream/cache/facts.pkl`. Also reads the commit timestamps from the held-out clones (read-only `git show`). |
| `arrivals.py` | Arrival model: real issues, proxy selection, commit clock → `arrivals.parquet`, `clock.parquet`, `arrivals_meta.json`. |
| `sim.py` | Replay engine: policy matrices, task generation, lazy cost accounting, composed policies, stale windows. |
| `validate.py` | Checks the replay approximation against held-out runs that were actually executed on sparse schedules → `validation.md`. |
| `run.py` | Runs every fact set × configuration × arrival model × 10 seeds → `agg.parquet`, `perfact.parquet`, `stale.parquet`. |
| `report.py` | Tables and figures → `tables.md`, `results.json`, `pareto.png`, `timeline_networkx.png`, `sensitivity.png`. |

Run order, from the project root with `python -B`:

1. `-m esm.stream.prep`
2. `-m esm.stream.arrivals`
3. `-m esm.stream.validate`
4. `-m esm.stream.run`
5. `-m esm.stream.report`

Everything runs on CPU in about 15 minutes.

## Assumptions (all of them)

### 1. Arrivals

**READ = an issue opened; WRITE = a first-parent commit.** These definitions come from the trace study.

**Own streams.** Four held-out repos are among the 58 trace repos: httpx, jinja, black and networkx.

* They use their own issues inside their own FUTURE window, (T_s0, T_400], on their own commit clock.
* networkx's last ~3 days have no issues, because the issue fetch ended on 2026-10-01.

**Proxy streams.** The other 12 repos have no recorded issue stream, so each one borrows a proxy:

* **How the proxy is chosen.** It is the trace repo whose commit rate is closest to the held-out repo's FUTURE commit rate.
  * The rate is measured over a 400-commit window that starts at the held-out repo's s0 date where possible (otherwise the
    proxy's last 400 commits).
  * The four own repos are excluded as proxies.
  * Each proxy is used once.
  * The closest available match differs by up to 1.9× in commit rate (boltons ← pallets/flask, |log ratio| 0.62).
    Nine of the 12 matches are within 1.4×.
* **What the proxy supplies.** The held-out repo's i-th FUTURE commit is identified with the proxy's i-th window commit.
  Commit times, issue times and their interleaving are then all the proxy's real ones.
* **What this implies.** For those 12 repos, timing is real but borrowed. It is not the repo's own history, and the
  pairing of a proxy commit with a held-out code change is arbitrary.
* **Dropped variant.** An earlier variant warped proxy issues onto the held-out commit clock. It was dropped because it
  decouples issue counts from gap lengths (see `arrivals.py`).

**Poisson control.**

* The same number of tasks, with i.i.d. uniform times over the same window and the same commit clock.
* The times are redrawn for each seed.

**Volume.** One issue is one task, so read volume = issues × E[k].

* ×0.3 keeps each issue with probability 0.3.
* ×3 turns every issue into 3 tasks at the same time.

### 2. Tasks

* **Facts per task.** Each task reads k distinct facts of its repo:
  * k ~ U{1, 2, 3} by default;
  * sensitivity runs use k = 1 and k = 3.
* **Which facts.** Facts are drawn with Zipf(1) popularity over a random per-seed ranking.
  * Sensitivity runs use uniform popularity and Zipf 1.5.
  * Popularity is independent of whether a fact changes. Real popularity might correlate with code churn; that
    correlation is not modelled.
* **When a task is wrong.** A task is "served a wrong answer" if any of its k reads gets an answer that differs from the
  programmatic oracle at that commit.

### 3. Deployment and cost model (lazy, on read)

**Maintenance runs only when a fact is read.** Reads of the same fact at the same commit share one maintenance.

**The answer served at commit t** is the answer the recorded every-commit run held at t.

**The cost charged at a read** at commit r covers the interval (p, r], where p is the previous read of that fact
(p = 0 for the first read):

* one judgement, at the tokens of the last recorded judgement in the interval;
* one re-derivation, at the tokens of the last recorded re-derivation in the interval.

This is the "coalesced" accounting.

**Why this is an approximation.** A truly lazy run would judge the transition anchor → state(r) once. It would also
re-derive at r, not at the commit where the every-commit run re-derived. The validation below bounds the error.

**Two other cost accountings are reported:**

* **"sum".** Pay every skipped commit's recorded cost. This is an upper bound.
* **EAGER.** A commit hook maintains every fact at every commit. Its cost is an exact replay, and it does not depend on reads.

**TTL in the stream is epoch-based.** The answer expires at commits k, 2k, …, and the first read after an expiry
re-derives. The recorded sparse TTL runs were age-based instead.

**Reads at t = 0** (before the first FUTURE commit) serve the verified s0 answer at zero cost.

**One-off certificate construction tokens** (CERT-ZS, CERT-v0h) are added once per fact in the set, whether or not the
fact is read.

### 4. Policies and fact sets

**H150** (160 facts) has every real-cost policy recorded at every commit:

* ESM (frozen), ESM-verify, NEVER;
* TTL50 / 100 / 200, REPLAY, CERT-ZS, LLMDIFF;
* @oracle versions.

So the main comparison runs on H150, for all policies.

* **H150 over-represents changing facts by design**, so its absolute rates are not base rates.
* **CERT-v0h** is static-only. It runs on the 133 static H150 facts, next to ESM / CERT-ZS / REPLAY / NEVER on the same facts.
* **ALL** (1,419 facts) has only ESM, NEVER and the @oracle baselines recorded at every commit.

**Composed policies** (marked `*` / "composed"):

* **ALWAYS\*** re-derives at every read.
  * Each re-derivation is imputed from the recorded 27B re-derivation of that fact at the nearest commit with the same
    oracle value: exact commit 5 %, same value 94.5 %, other value 0.2 % on H150.
  * The imputed answer is scored against the oracle at the read's commit.
  * A leave-one-out check of this imputation agrees with the recorded correctness 96.9 % of the time.
* **FILEHASH\*** re-derives when the s0 read-set file hashes change.
  * The triggers come from the recorded FILEHASH@oracle run.
  * Each re-derivation is imputed in the same way.
  * Real FILEHASH would re-baseline on the new trace's read set; that is not modelled.
* **No real ALWAYS or FILEHASH was ever run at every commit**, so these two policies exist only as composed runs.

**@oracle policies** replace re-derivation with the oracle answer. They are idealised references and are always labelled.

### 5. Metrics

* tokens per task and total tokens per run;
* wrong-served tasks (% and count), wrong reads;
* wrong tasks per 1k tokens, and wrong tasks avoided relative to NEVER per 1M tokens;
* the split between judge and re-derivation tokens;
* **stale window.** Seen from the reader's side: an episode starts at a wrong read whose previous read of that fact was
  right, and ends at the next right read. It is measured in real (clock) days, and censored at the end of the window.

**Bootstrap (B = 2,000):**

* over the 16 repositories, for task-level metrics;
* over facts, for read-level metrics.

Paired differences use the same resamples. Seeds (10) are summed before bootstrapping, so the CIs do not include
seed-to-seed variation.

## Validation of the approximation (`results/stream/validation.md`)

The engine was applied to every-commit records with reads placed on schedules that **were** actually run in Stage 2:
every5, every20, every50 and bursty.

* **ESM (frozen), H150.**
  * Served-wrong is within 0.3 pp of the recorded sparse runs: 7.0/7.0, 7.2/7.3, 7.4/7.7, 4.8/4.7.
  * Per-read agreement is 98.5–100 %.
  * Tokens per fact are 1–6 % higher than recorded: 24.2k vs 24.0k, 20.1k vs 19.1k, 17.6k vs 16.6k, 15.2k vs 14.6k.
    The coalesced accounting is therefore slightly conservative for ESM.
* **REPLAY, CERT-ZS, CERT-v0h and LLMDIFF at every50.** Served-wrong is within 0.6 pp and tokens are within 2 %.
* **TTL.** Exact where the two expiry rules coincide. On every20 and bursty the engine charges up to 33 % more tokens,
  because of the epoch vs age expiry difference.
* **FILEHASH\* at every50.** Served-wrong 9.1 vs 9.3 %; tokens 60.7k vs 65.9k.
* **The "sum" accounting** over-states lazy cost by 1.0–49× (ALWAYS is the extreme). It is reported only as an upper bound.

## Limitations (plain)

* **No new LLM decisions were made.**
  * When reads are sparse, the real lazy policy would judge different transitions and re-derive at different commits
    than the recorded every-commit run. The approximation error measured above is small for ESM and for the guard
    policies.
  * Reads in the stream are sparser than every50 for most facts, which is outside the validated range. Any error there
    is unmeasured.
* **ALWAYS\* and FILEHASH\* are composed from re-derivations recorded at other commits.**
* **12 of 16 repos use a proxy repository's issue/commit stream.** Issues are a proxy for "tasks that read stored
  knowledge". There is no evidence that an issue would read these particular facts.
* **Facts per task (k), popularity (Zipf) and the independence of popularity from churn are assumptions.** Sensitivity
  runs vary k and popularity, not the independence.
* **H150 over-represents changing facts.** ALL has real costs only for ESM and NEVER.
* **Stale windows are measured from reads.** A wrong answer that nobody reads is not counted as in service.
