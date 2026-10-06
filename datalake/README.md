# Evolving data-lake environment (non-code evaluation environment)

Two **real** evolving data lakes — NYC TLC trip records and Backblaze Drive Stats — turned into ordered
snapshot sequences (the analogue of commits), with deterministic, size-capped observation tools and facts whose
ground truth is computed **programmatically by DuckDB full scans at every snapshot**. No LLM and no GPU are used
anywhere in this directory. Sources, subsampling, the event timeline (real vs synthetic) and base rates are in
[MANIFEST.md](MANIFEST.md).

The interface mirrors `heldout/vfs.py` + `heldout/facts.py` (the code-repository environment), so a maintenance method written against the
code-repo environment (`Repo` / `World` / `run_tool` / `oracle`) can be pointed at a lake with minimal changes.

## Layout

| path | content |
|---|---|
| `lake.py` | `Lake` (snapshot list, HISTORY / s0 / FUTURE), `World` (one snapshot), the tools, `run_tool`, `normalise`, `files_touched`, `openai_tools` |
| `facts_dl.py` | fact types D1–D8, `relevant()`, `oracle()`, `oracle_direct()`, `question()`, `canon()/matches()`, candidate enumeration and sampling |
| `facts_tlc.json`, `facts_bb.json` | sampled facts with `K_oracle` (value at s0), change statistics, question text, subset label |
| `oracle/oracle_<lake>.parquet` | oracle value of every sampled fact at every window snapshot (HISTORY, s0, FUTURE) |
| `manifests/<lake>_events.json` | the event list (one event = one snapshot) without the full file maps |
| `ingest.py`, `fetch_docs.py`, `build_snapshots.py` | how the lakes were built (download → subsample → content-addressed store → events) |
| `smoke_test.py`, `smoke_test_report_tlc_bb.txt` | tool run on 3 snapshots per lake + 30 oracle values per lake recomputed independently |
| `make_manifest.py` | regenerates the statistics tables in MANIFEST.md |

Bulk data (content-addressed store, snapshot manifests, profile cache) lives in `$ESM_LAKE_DATA`
(default `datalake_data/` at the repository root: `store/`, `snapshots/`, `catalog/`, `cache/`).

## Plugging the environment into a maintenance method

```python
import sys; sys.path.insert(0, "datalake")   # from the repository root
import json, lake as L, facts_dl as F

lk = L.Lake("tlc")                         # or "bb"
snaps = lk.list_snapshots()                # window = HISTORY (60) + s0 + FUTURE   (lk.commits is the same list)
lk.s0, lk.history, lk.future               # like vfs.Repo
w = lk.world(lk.s0)                        # World: w.tree = {logical_path: (sha256, is_text)}

# tools (deterministic; every output is text, capped at 4,000 chars)
L.run_tool(w, "find", {"glob": "yellow_*2022-0*"})
L.run_tool(w, "sql", {"query": "SELECT count(*) FROM 'trip-data/yellow_tripdata_2022-01.parquet'"})
T = L.tools(w); T["file_schema"](file="trip-data/fhvhv_tripdata_2022-01.parquet")
L.openai_tools()                           # function-calling schemas for an agent

# facts and oracle
facts = json.load(open("facts_tlc.json"))["facts"]
P = F.Profiles("tlc")                      # per-file-version DuckDB full-scan profiles (cached on disk)
f = facts[0]
F.oracle(lk.world(lk.future[10]), f, P)    # ground truth at any snapshot; "NONE" if the referent disappeared
F.oracle_direct(lk.world(lk.future[10]), f)  # same value via one independent DuckDB statement (slower)
F.matches(f, agent_answer, value)          # canonicalised comparison of an agent answer with an oracle value

# precomputed series
import pandas as pd
tab = pd.read_parquet("oracle/oracle_tlc.parquet")   # lake, fact_id, snap_idx, window_idx, snapshot, phase, value, valid
```

Read-set / evidence-state helpers (same role as in `vfs.py`):
`L.files_touched(name, args, out, w)` returns the logical files an observation depends on (for `sql`, the files the
query resolves to); `L.normalise(name, out)` strips line numbers from `grep` / `read_text` output so that an
evidence state is stable under pure line shifts. The fingerprint of a file is `w.sha(path)` (sha256 of the stored
version), so FILEHASH-style guards work unchanged. Overlay worlds are supported: `lk.world(s, overlay={path: sha or None})`.

### Tools

| tool | args | returns |
|---|---|---|
| `ls` | path | entries of a directory (sub-directories with file counts) |
| `find` | glob | matching logical paths (max 150) |
| `file_schema` | file | column names + types (Parquet: Arrow types from the footer; CSV: DuckDB inference over the whole file) |
| `head` | file, n ≤ 20 | first rows as CSV |
| `file_rowcount` | file | row count from Parquet metadata / catalogue (no scan) |
| `file_stats` | file, column | min / max / null count — from Parquet row-group statistics; for CSV a scan of that single file |
| `sql` | query | one read-only DuckDB `SELECT`; files are referenced as quoted logical paths, globs allowed (`read_parquet('trip-data/yellow_*2023-0[12]*.parquet')`); max 50 result rows |
| `read_text` | file, start, end | numbered lines (max 200) of docs / data dictionaries / lookup CSV |
| `grep` | pattern, path | regex hits in documentation text files and lookup tables |
| `schema_diff` | file_a, file_b | added / removed / case-renamed / type-changed columns, order change |

**`sql` scan budget** (so that one cheap call cannot recompute a whole-lake aggregate):
TLC ≤ 3 files and ≤ 1.2 M catalogue rows per call; Backblaze ≤ 10 daily files and ≤ 120 k rows per call; 30 s timeout.
Statements other than `SELECT`, multiple statements, `COPY`/`ATTACH`/`INSTALL`/`SET`/`PRAGMA`/…, URLs and file
literals that are not files of the current snapshot are refused. A month of TLC data or a week of Backblaze data
fits one call; a year or the full history needs many calls (or reasoning from `file_rowcount` / `file_stats`).

## Fact types (both lakes)

| type | meaning (TLC) | meaning (Backblaze) | typical drift |
|---|---|---|---|
| D1 schema | Arrow type of column *c* in the latest file of dataset *d* | DuckDB-inferred type of column *c* in the latest daily CSV | type changes / column dropped |
| D2 field mapping | exact column holding concept *X* in the latest file of *d* (hand-written mapping table from the official data dictionaries, `TLC_CONCEPTS`) | same for SMART / metadata concepts (`BB_CONCEPTS`) | renames (e.g. `airport_fee`→`Airport_fee`) |
| D3 partition aggregate | count / exact sum / mean of a concept column in month *m* of *d* | drive-days, failures, distinct drives / models, mean capacity in month *m* | only corrections / re-partitions |
| D4 running aggregate | count / sum / max pickup over all data (or a year) to date | drive-days, failures, distinct drives … to date or per year | every append (all) / until the year closes |
| D5 top-k / argmax | top-k pick-up or drop-off zones, busiest month, top HVFHS licensee | top-k models by drive-days, model with most failures | incomplete periods, corrections |
| D6 join | trips joined with the zone lookup: top zone name / borough / service zone, count in a borough | cross-partition join: of the drives of model *M* seen in month *m0*, how many failed later / are present on the latest day | lookup revisions (real), appends |
| D7 data quality | null / negative / zero fraction of a column, fraction of pickups outside the file's month, per month / year / all | negative-capacity fraction, empty-SMART fraction per period | appends, corrections, schema additions |
| D8 existence / coverage | datasets whose latest file has column *c*; first month with *c*; #months with *c*; latest month | first date with *c*; #files with *c*; #columns of latest file; latest date | additions, renames, appends |

Numeric answers are canonical strings (integers; sums with 2 decimals from exact DECIMAL arithmetic; fractions with
5 and means with 4 decimals, half-even). `NONE` means the referent does not exist in that snapshot.
Each fact has a `subset` label: `natural` (uniform sample from the candidate pool at s0) or `enriched`
(sampled among pool facts whose value changes in FUTURE). Report base rates on `natural` only; the per-type pool
statistics (`stats` in the facts file) are the larger-sample natural base rates.
