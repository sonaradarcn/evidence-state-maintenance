# B3: real end-to-end task evaluation of a persistent coding agent (PLAN, written before any task run)

*Lab notebook, kept as written during the runs: the plan fixed before the first run, followed by the timestamped decision log. Server ports, hardware incidents and deviations are recorded as they happened; the final numbers are in RESULTS.md.*

Date: 2026-10-05, 22:30. Assessment item: `reviews/eswa_assessment.md` B3.

## Question

When a persistent coding agent reuses a remembered repository fact to do a real task at a later commit, does the memory
policy (none / blind reuse / TTL / replay / ESM) change task success, wrong actions, tokens and latency?

## What is real and what is replayed

| component | status |
|---|---|
| repositories | re-cloned (bare, full history) from GitHub; HEAD pinned to the manifest HEAD; first-parent window checked against `heldout/facts_<repo>.json` |
| s0 facts (question, K, trace) | **reused**: the held-out s0 27B derivations (kept facts only) |
| maintenance at the task commits (lazy, on read) | **real policy run** (esm package, reads at t = 100, 250, 400 only). A judge call or re-derivation whose exact request was already made in Stage 2 is served from the Stage-2 cache / derivation store (identical request => identical output; counted at its recorded tokens and marked "recorded"); every other call is made now on GPU 1 |
| ESM-eager (secondary) | **replayed**: the Stage-2 every-commit ESM run's served answer at t; maintenance tokens = recorded tokens in (t_prev, t] |
| task agent | **real**: qwen3.6:27b, new tool loop, every call made now |
| success check | **real**: deterministic checks against the repository at commit t (AST / import resolution / signature binding / patch application / executing the agent's test in a materialised package with fixed deps) |

## Design (fixed before running)

* Facts: 40 facts from H150 (the 160-fact subset with recorded real-cost baselines), seeded (seed 20261005), stratified by
  task type, at most one fact per repo per type where possible, about 70 % of each quota from facts whose value changes
  in FUTURE (H150 itself over-represents changing facts; pooled rates are therefore not base rates).
* Tasks: each fact gives one task at each of t = 100, 250, 400 commits after s0 (120 tasks).

  | task type | from fact type | n facts | task | success |
  |---|---|---|---|---|
  | T-locate | T1 (file defining X) | 8 | write a one-line `from M import X` importing X from its defining module | M resolves at t to a source file that defines X at top level (import also executed where the package is importable) |
  | T-api | T3 (parameters of f) | 7 | write a call of f passing every named parameter (not self/cls, not *args/**kwargs) by keyword with value None | keyword set equals the signature at t and the call binds |
  | T-modify | T3 | 7 | edit (exact old -> new text replacement) adding parameter `e2e_flag=False` to f | edit applies uniquely, file parses, f's parameters = parameters at t + e2e_flag, body unchanged; module imports (executed) where the package is importable |
  | T-test | B (value of a call) | 8 | write a pytest regression test asserting the current value of expression e (literal `==`, or `pytest.raises`) | the test passes when executed at t (materialised package + fixed deps) and is non-trivial |
  | T-question | T2 / T6 / T7 | 4 / 3 / 3 | answer the fact's question (asked by module / symbol, not by pinned path) | canonicalised answer equals the truth at t |

  If what the task refers to is gone at t, the correct action is `abstain` (or answer NONE for questions).
* Ground truth at t is computed from the checkout at t. Unlike the benchmark oracle, a file that moved only by a
  `src/` layout change (jinja at t = 103) is the same module: tasks name modules and symbols, not pinned paths. The strict
  benchmark oracle is reported as a secondary scoring of the remembered answers.
* Arms (same task prompt; memory = the fact's question and the policy's served answer, one note):
  NO-MEMORY, NEVER, TTL100 (lazy: re-derive if the answer is >= 100 commits old), REPLAY (lazy: replay the current
  trace, any change => re-derive), ESM (frozen `ESM-norepair`, lazy), secondary ESM-eager (replayed), reference
  ORACLE-MEMORY (memory = truth at t; idealised, labelled).
* Agent: qwen3.6:27b, T = 0, thinking off, <= 8 read-only tool calls (ls, find, grep, read, def_block, list_defs,
  toml_get, ini_get), then `submit` or `abstain`. Identical prompts are cached, so arms whose memory notes are identical
  get literally the same run (fair pairing).
* Outcome per task: success / wrong action (submitted something that fails the check) / failure (abstained when the task
  was possible, or no submission).
* Metrics: success, wrong-action and failure rates; tokens per task = task tokens + maintenance tokens at that read;
  latency = measured task wall-clock + maintenance latency (measured for new calls, recorded Stage-2 latency for reused
  calls); bootstrap CIs over tasks (B = 2000) and over facts (cluster) as a check; per task type and per t; paired
  differences vs NEVER and vs NO-MEMORY.

## Budget

* GPU: GPU 1 only, own Ollama on port 11641 (CUDA_VISIBLE_DEVICES=1); 11434 never touched; stopped at the end.
* LLM: maintenance <= 600 new 27B calls; task agent ~ 7 arms x 120 tasks, ~ 350 unique runs x ~ 5 calls = ~ 1,800 calls.
  At ~ 8-12 s per call on one GPU: ~ 6 h. Ceiling 4,000 new calls.
* Wall-clock: <= 20 h total. Data: `esm_data_e2e/`; results: `esm/results/e2e/`.

## Decision log

* 22:10 the original data drive data is gone (deleted 10-05); clones, trees and exec deps are re-created under `esm_data_e2e/` (oracle tables
  from `data/`). Ollama 11641/GPU 1 started 22:25. Another session runs Ollama on 11621 (GPU 0): not touched.
* 22:41 maintenance done in 61 s: lazy reads at t=100/250/400 hit Stage-2 records almost everywhere (all re-derivations at these t exist from the Stage-2 50-commit grid; 83 of 90 ESM judge calls identical to Stage-2 requests, 7 new). Smoke test of the agent OK (4 runs). Full agent run queued (302 unique runs for 840 arm-task pairs).
* 23:35 (post hoc, decided after ~200 of 298 main runs) partial counts showed the agent re-verifying remembered facts (NEVER ~ NO-MEMORY in success). Added a secondary prompt variant 'trust' (memory presented as verified facts to rely on) for the four memory policies + ORACLE; reported separately as a post hoc sensitivity (T9).
* 00:20 BUG in ground truth found while reading failures: kombu/transport/SQS.py became the package kombu/transport/SQS/__init__.py (same module kombu.transport.SQS); resolve_file only handled src/ moves, so the function was wrongly 'gone'. Fixed: fall back to the unique file with the same module name (consistent with the pre-declared 'tasks name modules, not paths'). Queued: setup (truth recomputed; tasks.pre_fix.json kept), zero-LLM recheck of every recorded run (runs.pre_recheck.jsonl kept), agent runs for the ORACLE memories that changed, report.

## Realised budget (2026-10-06 00:55)

| item | plan | realised |
|---|---|---|
| wall-clock | <= 20 h | ~2.9 h (22:05 -> 00:55), incl. re-cloning 16 repos (~25 min) and tree caches |
| new 27B calls (GPU 1, port 11641) | ~1,800 task + <= 600 maintenance; ceiling 4,000 | **1,894**: 1,887 task-agent calls (4.34M prompt + 0.18M completion tokens, 2.0 h of LLM time) + 7 ESM judge calls |
| maintenance reused from Stage 2 | – | 83 ESM judge calls (identical requests) + all 245 re-derivations at t = 100/250/400 (TTL100 120, REPLAY 91, ESM 34; Stage-2 50-commit grid) |
| agent runs | ~350 unique | 302 unique runs for 840 (arm, task) pairs (main) + 179 for 600 pairs (post hoc 'trust' variant) |
| servers | own Ollama 11641 / GPU 1 | started 22:25, stopped 00:52; 11434 and the other session's 11621 (GPU 0) never touched |

Deviations: (1) maintenance turned out almost entirely replayable from Stage-2 records (the plan expected some new
re-derivations at t = 250); (2) ground-truth fix for module -> package moves at 00:20 (one fact, kombu:T3:13; zero-LLM
re-check of all runs; 10 recorded outcomes changed, all wrong -> success); (3) post hoc 'trust' prompt variant.
