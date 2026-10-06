# `esm` package

`esm.env.Environment` isolates everything environment-specific. `envs/pyrepo.py` (git repositories; `envs/heldout.py`
loads the held-out benchmark on top of it) and `envs/datalake.py` are the implementations used in the paper.

## Layout

| module | role | env-specific? |
|---|---|---|
| `env.py` | `Environment` interface (facts, worlds, truth, tool calls, anchoring, guards, derivation agent) | interface |
| `envs/pyrepo.py` | `PyRepoEnv`: dev-set loader (`load_dev_facts`), git worlds, oracle comparison, 9B derivation agent, read-set / file / AST hashes | yes (git + Python) |
| `envs/pyfacts.py` | Python-repo fact types, programmatic oracles and canonicalisers (copied from pilot3/pilot6) | yes |
| `tools.py` | git VFS (`GitRepo`, `World`) and the deterministic tools `ls find grep grep_count read def_block list_defs toml_get ini_get` (same outputs as pilot3) | yes |
| `evidence.py` | `record()` (drift-robust anchored queries or original calls), `reanchor()`, `Evidence`, `ObsTable` (memoised observation series, persisted), code anchoring (`code_anchor`, `code_observe`, `code_reanchor`) | generic + code anchoring helpers |
| `delta.py` | pilot7-identical capped delta (`build_capped`), hierarchical split (`plan_hierarchical`), prompts | generic |
| `judge.py` | `evaluate()` (single call or hierarchical screen + final call; n samples), `combine()` (n-sample rules), `evaluate_rdiff()` (LLM-on-diff baseline) | generic |
| `maintain.py` | `simulate_esm()` (ESM policy), `detect_only()` (pilot7 framework), `DerivStore` (memoised agent re-derivations), `schedule()`, `Rec` | generic |
| `baselines.py` | NEVER, ALWAYS, TTL<k>, REPLAY, FILEHASH, ASTHASH, CITE, CERT-ZS, CERT-v0, LLMDIFF; `@oracle` suffix = idealised re-derivation | generic (uses env guards) |
| `policies.py` | registry of named policy configurations (`ESM`, ablations, `DETECT-*`) and the shared `Context` | generic |
| `metrics.py` | per-fact aggregation, FF / FS / served-wrong / cost / severity, bootstrap CIs, paired differences | generic |
| `llm.py` | cached OpenAI-compatible client (Ollama), ledger; optional read-through caches (`ESM_LLM_READ_THROUGH`); offline mode | generic |
| `common.py` | data / results paths | – |

## Entry points (run from the repository root)

| command | what it does |
|---|---|
| `esm/scripts/start_ollama.ps1 -port P -gpu G` / `stop_ollama.ps1 [-port P]` | start/stop ESM's own Ollama servers (refuses 11434). Logs + pids in `esm_data/logs`. |
| `python -m esm.scripts.build_states <repo>` | zero-LLM: replay every fact's s0 evidence (anchored + original) at the 400 future commits; persists `esm_data/obs/<repo>.pkl` |
| `python -m esm.scripts.run_sim --policies P1,P2 --schedules every,every5,every20,bursty [--facts ids.json] [--workers N] [--q27 ports] [--q9 ports] [--offline] [--reverse]` | simulate policies; writes `esm_data/sim/<policy>__<schedule>.parquet` (one row per fact × read). A fact that needs a model not configured (`--q27 ""`) is reported incomplete; re-run later (everything is cached). |
| `python -m esm.scripts.derive_grid --facts ids.json --grid 0,100,200` | agent re-derivations at fixed commits (ALWAYS / TTL baselines, re-derivation accuracy) |
| `python -m esm.scripts.report` | zero-LLM analysis → `esm/results/dev/{tables.md, results.json, records.parquet, curves_*.png}` |

Policy names: see `policies.py` (`ESM`, `ESM-noanchor`, `ESM-trunc`, `ESM-noanchor-trunc`, `ESM-norepair`,
`ESM-unsurefresh`, `ESM-chain`, `ESM-9B`, `ESM-n3`, `ESM-n3maj`, `ESM-n3-unsurefresh`, `DETECT-p7a` (= pilot7 TRIAGE-a),
`DETECT-p7b`, `DETECT-anchor-hier`, ...) and `baselines.py`.  Schedules: `every`, `every<k>`, `bursty` (80 reads in
bursts of 10, seed 7).

## Held-out stage (16 new repositories; `esm/results/heldout/`)

Set `ESM_DATA=esm_data_heldout` and `ESM_STAGE=heldout` (results folder). Dev-stage data (`ESM_DEV_DATA`) is only read.

| command | what it does |
|---|---|
| `python -m esm.scripts.heldout_s0 [--deriver 27b\|9b]` | s0 derivation of all 1,478 held-out facts (27B agent; 9B secondary arm) |
| `python -m esm.scripts.heldout_subsets` | ALL = kept facts; H150 = stratified 160-fact subset (seeded; frozen once drawn) |
| `python -m esm.scripts.build_states <repo\|all> --kind heldout` | zero-LLM evidence-state tables |
| `python -m esm.scripts.heldout_certs --facts F` | CERT-ZS / CERT-v0h certificates (27B) |
| `python -m esm.scripts.run_sim --kind heldout ...` | policies (as above; `--priority F` puts a subset first) |
| `python -m esm.scripts.run_sim --kind dev27 ...` | dev calibration (dev facts, 27B re-deriver) |
| `python -m esm.scripts.freeze_choice` | applies the pre-registered repair-policy rule -> `<data>/frozen.json` |
| `python -m esm.scripts.jobqueue <queue>` / `status` / `poll` | persistent job queues and explicit polling |
| `python -m esm.scripts.report_heldout` | zero-LLM analysis -> `esm/results/heldout/` |

New in the package for this stage: `envs/heldout.py` (loader, oracle tables, s0 attachment), `certs.py` (CERT-ZS,
CERT-v0h), the repair verifier `judge.verify_answer` (`ESMConfig.verify="blind"`), the deriver choice per policy
(`ESMConfig.deriver`), a NONE instruction in the agent prompt (`PyRepoEnv(none_hint=True)`), per-process shard files for
derivations / certificates, and the `lifetime kept` metric.

## Using it on another environment

1. Implement `esm.env.Environment` (see the docstrings): worlds per version, `run_call`, `anchor_call` (how to make an
   observation drift-robust in that environment, e.g. a column/partition-addressed query instead of a row range),
   `observe`, `reanchor`, `query_label`, `cite_texts`, `auto_cites`, `read_set`, `item_hash`, `readset_diff`, `derive`,
   `truth`, `answer_matches`, plus `domain` / `tool_names` strings used in prompts.
2. Build fact dicts (iid, slice, unit, type, question, K, trace, cite, truth series, valid, derive_tokens).
3. Use `policies.Context(env, ObsTable(env), DerivStore(env, path))` and `simulate_esm` / `baselines.simulate`.

## Caching and data

* LLM cache: `esm_data/llm_cache` (+ any read-through caches in `ESM_LLM_READ_THROUGH`); ledger `esm_data/llm_ledger.jsonl`.
* Re-derivations: `esm_data/derivations.jsonl` (trace, answer, tokens, correctness).
* Observations: `esm_data/obs/*.pkl`; simulations: `esm_data/sim/*.parquet`.

## Data-lake anchoring (`envs/datalake.py`)

How each lake tool's observation is made drift-robust (`lake_anchor` / `lake_observe`; fixed before any maintenance
run, see esm/results/datalake/PLAN.md):

| tool | anchored observation |
|---|---|
| `ls`, `find` | sorted set of output lines |
| `grep` | line numbers stripped, sorted set |
| `file_schema` | {column: type} map in name order (column order ignored); file resolved by key |
| `head` | header + data rows as a set (compared by content, not position) |
| `file_rowcount` | value; file resolved by key (a re-partitioned partition = sum over its part files) |
| `file_stats` | min / max / null count / rows only |
| `sql` | header + rows; rows sorted canonically unless the query has ORDER BY; floats rounded to 10 significant digits; a vanished file literal is re-resolved by key |
| `read_text` | content-anchored span (distinctive first/last lines of the window, as for code reads) |
| `schema_diff` | sorted lines; files resolved by key |

"Resolved by key": the exact logical path if it exists, else the files of the same (dataset, month) partition (TLC
`<ds>_tripdata_<YYYY-MM>` including `/part-*.parquet`), else the unique file with the same basename. `mode="original"`
keeps every call as recorded. Read sets for FILEHASH-style guards include the listings the agent consulted (find
globs, ls directories, sql globs), so a new file matching a consulted glob counts as a manifest change.
