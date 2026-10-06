# Reproducing the paper

There are three levels, from cheapest to most expensive.

| level | what | needs | time |
|---|---|---|---|
| A | recompute tables, figures and statistics from the shipped records | this repository | minutes, CPU |
| B | rebuild the benchmarks and their ground truth from the public sources | network, git, ~80 GB transient download for the lakes | hours, CPU |
| C | re-run the LLM experiments | B, local GPUs with Ollama (and a NIM key for the second model) | days of GPU time |

What a level-C re-run cannot give is a byte-identical replay of the original LLM calls: every call was cached, but the
caches (several GB per stage) are not in this repository. They are available from the authors on request, and with
them each stage's report can be recomputed offline (`ESM_LLM_OFFLINE=1`). The model builds are pinned by digest in
`MODEL_MANIFEST.json`; a re-run with the same builds and settings should give close but not identical outputs, since
GPU inference is not bit-reproducible.

The development set (285 facts from 9 repositories, Sections 5–6) comes from the preliminary studies and cannot be
rebuilt from this repository; its results and per-read records are in `esm/results/dev/`. Names such as `pilot3` or `pilot7`
in the result notes refer to these preliminary studies (Section 4 of the paper); their code is not included.

## Paper to code

| paper | stage | inputs | code | results |
|---|---|---|---|---|
| 6, Table 2 | benchmarks | `heldout/facts_*.json`, `datalake/facts_*.json` | `heldout/`, `datalake/` | `heldout/MANIFEST.md`, `datalake/MANIFEST.md` |
| 7.1, 7.2, 7.4, 7.5, 7.9 | held-out | `inputs/heldout/` | `esm/scripts/*heldout*`, `run_sim.py` | `esm/results/heldout/` (+ `ANALYSES.md`) |
| 7.3 | second model | `inputs/xmodel/` | `esm/results/xmodel/*.py` | `esm/results/xmodel/` |
| 7.6 | data lakes | `inputs/datalake/` | `esm/scripts/dl_*.py`, `esm/envs/datalake.py` | `esm/results/datalake/` |
| 7.7 | task stream | `data/events_github.parquet`, `esm/results/stream/cache/` | `esm/stream/` | `esm/results/stream/` |
| 7.8 | task studies | `inputs/e2e/`, `inputs/e2e_lake/` | `esm/e2e/`, `esm/e2e_lake/` | `esm/results/e2e/`, `esm/results/e2e_lake/` |
| figures | | `esm/results/*/results.json` | `paper_figures/make_figs.py` | `paper_figures/*.pdf` |

Subset names: S160 in the paper is called `H150` in code, file and column names (it has 160 facts;
`inputs/heldout/sub_S160.json` is a copy of `sub_H150.json`). NAT100 is a uniform sample of 100 natural facts, X30 /
X120 are the second-model subsets, R and S the data-lake subsets.

## Level A

```bash
python -m pytest tests                                  # headline numbers from records.parquet
python paper_figures/make_figs.py                       # every paper figure (ESM_FIG_OUT=<dir> to write elsewhere)
python -B -m esm.stream.arrivals                        # task-stream simulation from the shipped cache
python -B -m esm.stream.validate
python -B -m esm.stream.run
python -B -m esm.stream.report
cd esm/results/heldout/revision_r1 && python -B item1_clustered.py   # also item2..item5
```

## Level B

Working directories default to folders at the repository root and are ignored by git:

| variable | default | content |
|---|---|---|
| `ESM_DATA` | `esm_data/` | working data of one stage: LLM cache and ledger, derivations, observation tables, simulations |
| `ESM_STAGE` | `dev` | `esm/results/` sub-folder written by the reports |
| `ESM_HELDOUT_DATA` | `heldout_data/` | held-out clones, tree caches, oracle tables, dependency folders |
| `ESM_LAKE_DATA` | `datalake_data/` | data-lake store and snapshot manifests |
| `ESM_PYTHON` | current interpreter | interpreter used to execute behaviour facts |

Held-out repositories (16 full-history bare clones, HEAD pinned to the recorded commit; trees take about a minute per
repository):

```bash
python heldout/clone_repos.py          # clones, checks the 701-commit windows, copies data/heldout_oracle_tables
python heldout/setup_deps.py           # fixed dependencies for executing behaviour facts
cd heldout && for r in boltons httpx werkzeug black poetry-core jinja typer marshmallow rich kombu scrapy \
    networkx pyparsing mkdocs isort pygments; do python -B build_trees.py $r; done; cd ..
```

The facts and oracle tables are shipped, so re-running the fact builder is optional
(`build_trees.py` → `static_h.py` → `behav_h.py` → `build_manifest.py` → `validate_h.py`; see `heldout/README.md`).

Data lakes (sources from the NYC TLC CloudFront bucket and Backblaze B2, subsampled deterministically to a 4.8 GB
store; each file is checked against the sha256 catalogue in `data/datalake_catalog`):

```bash
python -m esm.e2e_lake.fetch_lake --workers 6 --tlc-until 2026-08 --bb-until 2026Q2
python -m esm.e2e_lake.fetch_docs_lake
python -m esm.e2e_lake.build_snaps_lake        # rebuilt event lists are compared with datalake/manifests/
export ESM_LAKE_DATA=esm_data_e2e_lake/lake_data
```

## Level C

Start one Ollama server per GPU on its own port and pull the models listed in `MODEL_MANIFEST.json`
(Windows helper: `esm/scripts/start_ollama.ps1 <port> <gpu>`).

| variable | meaning |
|---|---|
| `ESM_PORTS_Q27`, `ESM_PORTS_Q9` | comma-separated Ollama ports for the 27B and the 9B model (one request in flight per port) |
| `ESM_MAIN_MODEL` | model used in every main role, e.g. `nim:nvidia/nemotron-3-super-120b-a12b` or `ollama:gpt-oss:20b` |
| `ESM_REASONING` | `reasoning_effort` sent with each request (default `none`) |
| `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_BASE_URL` | NIM access (environment, or an untracked `.env` at the repository root) |
| `ESM_NIM_CONC`, `ESM_NIM_RPM` | NIM concurrency and requests per minute |
| `ESM_LLM_OFFLINE=1` | a cache miss raises instead of calling a model |
| `ESM_LLM_READ_THROUGH` | additional read-only caches (`os.pathsep`-separated), e.g. the original caches |

Each stage writes to its own `ESM_DATA` directory; copy the stage's frozen inputs there first. Simulations are
resumable. The original command sequences, with their ports, worker counts and deadlines, are in
`provenance/job_logs/`; they record what was run, not a script to run as is.

**Held-out (7.1, 7.2, 7.4, 7.5).** About 47k 27B calls and 15k 9B calls (28.8 h of LLM time on two RTX 3080).

```bash
export ESM_DATA=esm_data_heldout ESM_STAGE=heldout ESM_PORTS_Q27=11595,11596 ESM_PORTS_Q9=11597
mkdir -p $ESM_DATA && cp inputs/heldout/*.json $ESM_DATA/
python -m esm.scripts.heldout_s0                                    # s0 derivation of the 1,478 facts
python -m esm.scripts.build_states all --kind heldout                # zero-LLM evidence-state tables
python -m esm.scripts.heldout_certs --facts $ESM_DATA/sub_H150.json  # CERT-ZS / CERT-v0h
python -m esm.scripts.run_sim --kind heldout --policies ESM-norepair --schedules every --facts $ESM_DATA/sub_ALL.json
python -m esm.scripts.run_sim --kind heldout --policies NEVER,TTL50,TTL100,REPLAY,LLMDIFF,CERT-ZS \
       --schedules every --facts $ESM_DATA/sub_H150.json
python -m esm.scripts.run_sim --kind heldout --policies ESM-norepair --schedules every5,every20,bursty \
       --facts $ESM_DATA/sub_H150.json
python -m esm.scripts.report_heldout                                # -> esm/results/heldout/
```

`frozen.json` holds the repair policy chosen on the development set before any held-out run
(`esm.scripts.freeze_choice`). Ablations and the 9B arms are further `run_sim` policies (`esm/policies.py`); the anchor-expiry and
NAT100 runs are in `provenance/job_logs/heldout/queue_R1*.txt`, analysed by `esm/results/heldout/revision_r1_runs/analyze.py`.

**Second model (7.3).**

```bash
export ESM_DATA=esm_data_xmodel/nemotron ESM_MAIN_MODEL=nim:nvidia/nemotron-3-super-120b-a12b
mkdir -p $ESM_DATA && cp inputs/xmodel/nemotron/*.json $ESM_DATA/
python -m esm.scripts.heldout_s0 --facts $ESM_DATA/sub_X120.json
python -m esm.scripts.build_states all --kind heldout
python -m esm.scripts.heldout_certs --facts $ESM_DATA/sub_X30.json --kinds certzs
python -m esm.scripts.run_sim --kind heldout --policies ESM-norepair,NEVER,TTL100,CERT-ZS,LLMDIFF --schedules every \
       --facts $ESM_DATA/sub_X30.json
python esm/results/xmodel/analyze.py
```

The gpt-oss arm uses `ESM_DATA=esm_data_xmodel`, `ESM_MAIN_MODEL=ollama:gpt-oss:20b`, `ESM_REASONING=medium`
(`inputs/xmodel/model.json`).

**Data lakes (7.6).** About 17k 27B calls.

```bash
export ESM_DATA=esm_data_datalake ESM_STAGE=datalake
mkdir -p $ESM_DATA && cp -r inputs/datalake/* $ESM_DATA/
python -m esm.scripts.dl_s0 --kind dl_tlc --q27 11595             # and --kind dl_bb
python -m esm.scripts.dl_states --kind dl_tlc
python -m esm.scripts.run_sim --kind dl_tlc --policies ESM-norepair --schedules every --order random:7
python -m esm.scripts.report_datalake                              # -> esm/results/datalake/
```

**Task stream (7.7).** `python -B -m esm.stream.prep` rebuilds `esm/results/stream/cache/` from `esm_data_heldout`;
the remaining steps are those of level A. Assumptions are listed in `esm/stream/README.md`.

**Task studies (7.8).** These replay the maintenance decisions of the held-out and data-lake stages, so they need
those stages' working data.

```bash
python -m esm.e2e.setup_e2e && python -m esm.e2e.maint_e2e && python -m esm.e2e.agent_e2e && python -m esm.e2e.report_e2e
python -m esm.e2e_lake.setup_lake && python -m esm.e2e_lake.maint_lake
python -m esm.e2e_lake.agent_lake --variant main && python -m esm.e2e_lake.agent_lake --variant trust
python -m esm.e2e_lake.report_lake
```

## Environment of the original runs

Windows 10, Python 3.14, two RTX 3080 (10 GB) for the 27B model plus a second machine for the 9B arms, Ollama with
the builds in `MODEL_MANIFEST.json`, NVIDIA NIM for Nemotron (2026-10-06). Package versions: `requirements.txt`.
Repository HEADs and commit windows: `heldout/facts_<repo>.json`. Random seeds are fixed in the scripts and recorded in
each stage's `PLAN.md` and `RESULTS.md`.
