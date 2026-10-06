# B3: real end-to-end task evaluation of a persistent coding agent

Date: 2026-10-06. Plan, decision log and realised budget: `PLAN.md`. Every number below comes from
`python -m esm.e2e.report_e2e` (zero LLM), which writes `tables.md`, `results.json`, `task_outcomes.{parquet,json}`,
`task_outcomes_trust.parquet` and the two figures. Code: `esm/e2e/`. Data: `esm_data_e2e/`.

## 0. Verdict

* **Setup.** 120 real tasks (40 held-out facts x commits t = 100, 250, 400 after s0) across 16 repositories, done by
  a qwen3.6:27b tool-using agent. Five task types: locate (import), API call, code modification (edit), regression test
  (executed), and repository question. Each outcome is checked against the repository at commit t. 18 of the 120 tasks
  refer to code that is gone at t; for those, the correct action is to abstain.
* **Main result (main prompt; the memory note says the code may have changed since):**

  | arm | success % [95 % CI] | wrong action % | failure % | memory right % | tokens/task (task + maint.) | latency s/task, est.* |
  |---|---|---|---|---|---|---|
  | NO-MEMORY | 93.3 [88.3, 97.5] | 3.3 [0.8, 6.7] | 3.3 | – | 11.2k (11.2k + 0) | 18.6 |
  | NEVER (blind reuse) | 92.5 [87.5, 96.7] | 7.5 [3.3, 12.5] | 0.0 | 60.0 | 11.1k (11.1k + 0) | 18.5 |
  | TTL100 | 95.0 [90.8, 98.3] | 5.0 [1.7, 9.2] | 0.0 | 91.7 | 24.4k (11.5k + 12.9k) | 39.1 |
  | REPLAY | 95.0 [90.8, 98.3] | 5.0 [1.7, 9.2] | 0.0 | 91.7 | 22.7k (11.5k + 11.2k) | 36.2 |
  | **ESM** (frozen) | **95.0 [90.8, 98.3]** | **5.0 [1.7, 10.0]** | 0.0 | 94.2 | **17.2k (11.4k + 5.8k)** | **27.4** |
  | *ESM-eager (replayed)* | *95.0* | *5.0* | *0.0* | *92.5* | *21.8k (11.3k + 10.5k)* | *35.0* |
  | *ORACLE memory (idealised)* | *94.2* | *5.8* | *0.0* | *100* | *11.6k* | *17.8* |

  \* task latency is measured. Maintenance latency is re-estimated on this server from tokens (1.64 s per 1k tokens).
  The recorded Stage-2 latencies, taken with 2–4 requests in flight, are 2–4x higher (`tables.md` T1, T7b).
* **Reading of the main result.**
  * **Accuracy: the maintained policies are tied.** ESM, TTL100 and REPLAY reach the same task outcomes on every one of
    the 120 tasks: paired difference 0.0 pp. The memory each one serves differs in only a few places, and on those tasks
    the agent re-checked the code anyway.
  * **Against NEVER:** ESM succeeds +2.5 pp [0.0, +5.8] more often and takes −2.5 pp [−5.8, 0.0] fewer wrong actions.
    Both CIs touch 0.
  * **Against NO-MEMORY:** no maintained policy is better or worse. Success +1.7 [−3.3, +6.7]; wrong actions +1.7
    [−1.7, +5.0].
  * **Cost:** ESM is the cheapest maintained policy:
    * −7.2k tokens per task vs TTL100 [−9.3k, −5.3k];
    * −5.4k vs REPLAY [−7.7k, −3.5k].
  * **But maintained memory costs more than having no memory.** ESM spends +6.0k tokens per task [+4.1k, +8.2k] over
    NO-MEMORY. The agent's own task tokens hardly change with memory: 11.1k–11.6k in every arm, ORACLE included.
* **Why NEVER is nearly harmless here.** The agent, told that the code may have changed, re-checks what it remembers.
  * Stale memory (NEVER: 40 % of its notes are wrong at t) leads to wrong actions mainly on tasks whose referent is gone
    (T5): NEVER is wrong on 22.2 % of them; NO-MEMORY, TTL100, REPLAY and ESM are wrong on 0–5.6 %.
  * It also shows on repository questions: NEVER 16.7 % wrong vs 0 % for NO-MEMORY.
* **Post hoc sensitivity: the prompt tells the agent to rely on its memory** (the "trust" variant, decided after seeing
  the main run; `tables.md` T9).
  * NEVER becomes clearly harmful: 12.5 % wrong actions [7.5, 19.2] vs NO-MEMORY 3.3 %, paired +9.2 pp [+4.2, +15.0].
  * Any maintained policy removes most of that: ESM / TTL100 / REPLAY 6.7 %, paired vs NEVER −5.8 pp [−10.8, −0.8].
  * Their remaining excess over NO-MEMORY, +3.3 pp [0.0, +7.5], is not significant.
  * ESM again matches TTL100 and REPLAY in outcomes at 15.7k vs 22.8k / 21.0k tokens per task.
  * The memory arms themselves get cheaper by about 1.2k task tokens (9.9k vs 11.2k).
* **Bottom line for the paper.** In a real task loop, maintaining memory matters when the agent relies on it. Blind
  reuse then roughly quadruples wrong actions relative to no memory. ESM gives the same task accuracy as TTL and replay
  maintenance at 30 % / 24 % fewer total tokens per task, and 55 % / 48 % less maintenance work.
  For facts that are this cheap to re-derive (about 11k tokens of exploration per task), however, a memoryless agent is
  as accurate and cheaper than any maintained memory. The case for maintained memory therefore rests on expensive
  derivations or agents that rely on memory, not on this regime.

## 1. What is real and what is replayed

| component | status |
|---|---|
| repositories | **re-cloned** from GitHub (bare, full history, HEAD pinned to the manifest); all 16 first-parent windows identical to `heldout/facts_*.json` |
| facts (question, s0 answer, s0 trace) | **reused**: the Stage-2 s0 27B derivations of 40 H150 facts |
| maintenance (lazy: reads only at t = 100, 250, 400) | **real policy code** (`esm` package; NEVER / TTL100 / REPLAY / frozen ESM-norepair). Each judge call or re-derivation whose *identical request* was made in Stage 2 is **replayed** from the Stage-2 cache or derivation store: 83 of 90 ESM judge calls, and all 245 re-derivations at these t, because Stage 2 ran a 50-commit derivation grid. **7 judge calls are new.** |
| ESM-eager | **replayed**: the Stage-2 every-commit ESM run's served answer at t; maintenance tokens = recorded tokens in (t_prev, t] |
| task agent | **real, new**: 1,887 qwen3.6:27b calls on GPU 1. Arms whose memory notes are identical share one run, so pairing is literal: 302 unique runs for 840 (arm, task) pairs, plus 179 for the trust variant |
| success checks | **real, deterministic**, against the repository at commit t. Task types:<ul><li>import: module resolution, and the import was also *executed* for all 84 runs where the package is importable, all of which succeeded;</li><li>API call: keyword set equals the signature at t;</li><li>edit: applies uniquely, AST equals the original plus `e2e_flag=False`, and the module still imports (executed where importable);</li><li>regression test: executed in the materialised package with fixed dependencies;</li><li>question: canonicalised answer equals the truth.</li></ul> |
| ground-truth validation | the oracle machinery recomputed with paths not remapped equals the benchmark oracle on 96/96 static (fact, t) pairs. Executing each behaviour expression at t equals the recorded truth on 24/24 (`validation.json`) |

## 2. Design (pre-registered in `PLAN.md`)

* **Facts.** 40 facts drawn by seed from H150, stratified by task type, about 70 % of them changing in FUTURE.
  * Task types, by number of facts: T-locate 8, T-api 7, T-modify 7, T-test 8, T-question 10 (T2 4, T6 3, T7 3).
  * 120 tasks in total; for 18 of them the referent is gone at t.
  * H150 over-represents changing facts, so absolute rates are not base rates.
* **Tasks.** Tasks name modules and symbols, not pinned paths, so truth uses module identity. The benchmark oracle
  instead counts jinja's `src/` move as NONE.
  * The memory note shows the fact's original question, including its pinned path, and the arm's served answer.
* **Agent.** At most 8 read-only tool calls (the Stage-2 tools), then `submit` or `abstain`.
* **Outcomes.**
  * success;
  * wrong action: something was submitted and it fails the check;
  * failure: the agent abstained although the task was possible, or submitted nothing.
* **CIs.** Bootstrap over tasks (B = 2000). Clustering by fact widens them by 1–3 pp. No point estimate changes,
  but a few task-level CIs that touch 0 then cross it (`tables.md` T1c, T2).

## 3. Further results (`tables.md`)

* **By task type (T3, main prompt).** Memory hurts or helps mostly in two places:
  * Repository questions: NEVER 83.3 % success vs 93.3 % for ESM / TTL / REPLAY and 100 % for NO-MEMORY.
  * Regression tests: every memory arm reaches 100 %, against 79.2 % for NO-MEMORY.
    * Without memory, the agent abstained or ran out of budget on 16.7 % of these tests: the value of a call cannot be
      worked out by reading code alone.
    * A remembered value, even a stale one, gives it a value to assert. NEVER also passes all 24 tests, despite 8
      stale notes.
  * Locate, API and modify tasks are insensitive to memory. The modify failures are the same 3 tasks in every arm:
    an ambiguous `old` snippet (httpx `AsyncClient.__init__`, at all three commits).
* **By commit (T4).** NEVER's memory is right on 82.5 % / 57.5 % / 40.0 % of tasks at t = 100 / 250 / 400. Its
  wrong-action rate rises from 5.0 to 10.0 %, while ESM's stays at 2.5–7.5 %.
* **Memory correctness vs outcome (T6, memory arms pooled).**
  * Main prompt: a right note gives 95.8 % success and a wrong note 86.7 %. Without memory, the same tasks succeed
    95 % / 85 % of the time, so wrong notes fall on tasks that are harder anyway.
  * Trust prompt: a wrong note gives 32 % wrong actions, against 3.7 % for a right note.
* **A failure mode that the answer's correctness does not capture.** On `jinja:T7:41` at t = 250 / 400, every memory
  arm, ORACLE included, answered "the class no longer exists": the remembered question pins `jinja2/nodes.py`, and that
  path moved to `src/` at t = 103.
  * NO-MEMORY found the class.
  * A remembered fact can mislead through its *context* (the path), even when the stored answer is right.
* **Maintenance work (T7).**
  * Memory right at the read (benchmark oracle): ESM 90.8 %, TTL100 88.3 %, REPLAY 88.3 %, NEVER 56.7 %.
  * Tokens per read: ESM 5.8k, TTL100 12.9k, REPLAY 11.2k.
  * Lazy reads at three commits cost ESM 45 % less than its eager every-commit replay (10.5k).

## 4. Figures

* `fig_outcomes.png`: success / wrong action / failure per arm (main prompt).
* `fig_cost_vs_outcome.png`:
  * left panel: tokens per task, split into task-agent and maintenance tokens;
  * right panel: wrong-action % with 95 % CIs, for the main prompt and the post hoc "rely on memory" prompt.

## 5. Limitations

* **Small sample.** 40 facts, 120 tasks; the CIs are ±4–6 pp. Most pairwise differences between memory policies are
  not significant. The ties between ESM, TTL100 and REPLAY are exact on these tasks; that does not prove they are
  equivalent in general.
* **Maintenance is mostly replayed.** Lazy maintenance ran the real policy code. However, almost every judge call and
  re-derivation it needed was an identical request already made in Stage 2, and was served from that record: 7 new
  calls in total. That is real output, not imputed output, but it was not re-executed. Recorded maintenance latencies
  come from Stage-2 hardware load, so latency is re-estimated from tokens (labelled). ESM-eager is a pure replay.
* **The prompt decides how much memory matters.** The main prompt warns that the code may have changed, which makes the
  agent re-verify. The trust prompt is post hoc, chosen after seeing the main run (`PLAN.md`). Both are reported; neither
  is "the" deployment.
* **Retrieval is assumed perfect.** Each task sees exactly one relevant note. Real memories hold many notes, and
  retrieving the wrong one is a separate failure source that was not modelled.
* **Cheap facts.** Re-deriving these facts by exploration costs about the same as doing the task (around 11k tokens).
  That favours NO-MEMORY. Facts that are expensive to derive (behaviour facts, data-lake aggregates) were not turned
  into tasks here, except the T-test tasks. There, memory did help: 100 % vs 79 % success.
* **Fixed s0 cost.** The s0 derivation cost (about 8–19k tokens per fact) is not charged to any arm. It is a one-off
  cost, amortised over all later tasks on that fact.
* **Ground truth.** Module identity is our definition: src-layout and module -> package moves count as the same module.
  The module -> package rule was added after the main run exposed it (one fact; 10 recorded outcomes changed, all from
  wrong to success, in all arms alike; `PLAN.md` 00:20). Tasks on facts with changing values are over-represented.
* **One model, one agent harness, Python repositories only.**
