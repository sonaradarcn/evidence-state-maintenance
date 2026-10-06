# MANIFEST — evolving data-lake environment

Built 2026-10-02 on this machine; no LLM calls, no GPU. All numbers in the "Generated statistics" section are produced
by `make_manifest.py` from the catalogue / snapshot / facts files.

## 1. Sources (what worked from mainland China)

| lake | source | URL | access that worked | licence / terms |
|---|---|---|---|---|
| NYC TLC trip records | monthly Parquet files, yellow / green / fhv / fhvhv | `https://d37ci6vzurychx.cloudfront.net/trip-data/<ds>_tripdata_<YYYY-MM>.parquet` | **direct CloudFront** (no proxy): ~0.5–2.5 MB/s per stream, ~6 MB/s with 6 parallel streams | NYC Open Data terms |
| NYC TLC taxi zone lookup | CSV | current: `https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv` (Last-Modified 2024-02-22); older version: Wayback capture 2020-09-04 of `https://s3.amazonaws.com/nyc-tlc/misc/taxi+_zone_lookup.csv` | direct + Wayback Machine | |
| NYC TLC data dictionaries | PDF (converted to text with pypdf) | `https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_{yellow,green,fhv,hvfhs}.pdf` and their Wayback captures | direct (needs a browser User-Agent) + Wayback | |
| Backblaze Drive Stats | quarterly (2013–2015: yearly) zips of daily CSVs | `https://f001.backblazeb2.com/file/Backblaze-Hard-Drive-Data/data_Q<q>_<yyyy>.zip`, `data_<yyyy>.zip` | **direct Backblaze B2** (no proxy): ~0.5–0.9 MB/s per stream, ~3 MB/s with 5 streams | Backblaze: free use with citation, no resale |
| Backblaze documentation | "Hard Drive Data and Stats" web page | Wayback captures of `backblaze.com/b2/hard-drive-test-data.html` and `backblaze.com/cloud-storage/resources/hard-drive-test-data` | Wayback Machine | |

What did **not** work / was not used:
* `hf-mirror.com` for `backblaze/Drive_Stats`: the API endpoint answers with a 308 redirect to huggingface.co (not mirrored),
  so the official B2 bucket was used instead (reachable directly).
* Citi Bike S3 (`s3.amazonaws.com/tripdata/...`): 404 for the probed key; not needed because Backblaze was obtainable.
* The Wayback Machine answered with a "suspected abusive bot traffic" page. The cause turned out to be the truncated
  browser User-Agent string the fetcher sent (`Mozilla/5.0 (Windows NT 10.0; Win64; x64)`); with curl's default UA the
  same captures download fine. The final fetcher uses the default UA for the archive (browser UA only for nyc.gov),
  paces requests ≥ 10 s apart, validates every response (a block page stored by the first run was found and deleted)
  and caches captures on disk. **All** listed dictionary / lookup / Backblaze-page versions were eventually obtained.
* Earlier versions of republished TLC files (see "Real republication evidence") are not downloadable: only the
  current version of each file exists at the origin.
* TLC `fhv_tripdata_2026-08.parquet` was not yet published (HTTP 403) on 2026-10-02; other missing months are listed in the tables.

## 2. Subsampling (deterministic; original schemas and file layout kept)

* **TLC**: keep a row iff `md5_number(concat_ws('|', <all columns as text, NULLs skipped>)) % 64 == 0` (DuckDB 1.5.6),
  i.e. 1/64 = 1.5625 % of rows. Selected rows are copied with pyarrow from the original row groups, so the Arrow schema
  (incl. `null`-typed columns, `large_string`, timestamp units) and the original compression codec are preserved;
  `schema_identical` is checked for every file. Logical path = `trip-data/<original file name>` (TLC's flat layout).
* **Backblaze**: keep a row iff `int(md5(serial_number).hexdigest()[:16], 16) % 64 == 0` — whole drive histories
  are kept (needed for failure/cohort facts). CSV header lines and data lines are copied byte-for-byte; the original
  line terminator is kept (two real daily files, 2018-02-25 and 2019-06-17, use bare `\r` line endings). Logical
  path = `drive_stats/<path inside the zip>`; the real directory layout varies by year (e.g. `2013/…`, `data_Q1_2016/…`, …)
  and is kept as-is; `__MACOSX/` resource-fork members are dropped.
* Raw downloads were deleted after subsampling; the content-addressed store keeps only subsampled files, docs and
  synthetic variants (store paths `store/<sha[:2]>/<sha256><ext>`).

## 3. Snapshot construction

A snapshot is the manifest `{logical_path: sha256}` after one event; consecutive snapshots share blobs (no copying).
Events (see `manifests/<lake>_events.json`):

* **TLC**: one snapshot per monthly file arrival, at a nominal release time (15th of month+2; within a day yellow,
  green, fhv, fhvhv). The bootstrap snapshot holds the zone lookup (2020 Wayback version) and the earliest available
  version of each data dictionary. Later real versions of the dictionaries (Wayback capture time = upper bound of their
  publication) and the current zone lookup (Last-Modified 2024-02-22, which relabels zones 264/265:
  `264 Unknown/NV` → `264 Unknown/N/A`, `265 Unknown/NA` → `265 N/A/Outside of NYC`) arrive as their own events.
* **Backblaze**: one snapshot per calendar month = that month's daily CSVs (real cadence is a quarterly zip; monthly
  batches are a documented refinement), plus documentation versions.
* s0 = round(0.40 × #snapshots); HISTORY = the 60 snapshots before s0; FUTURE = every later snapshot.

### Synthetic maintenance events (clearly labelled; a small minority)

All are `synthetic: true` in the event list; their content is derived from real files only.

| kind | what | TLC | Backblaze |
|---|---|---|---|
| preliminary + `correct` | the first published version of a partition lacks ~3 % deterministically chosen "late-arriving" rows (`md5(f"{key}:{row}") % 32 == 0`); a later correction event republishes the full real file | yellow 2021-03 (corrected in HISTORY), green 2021-11, yellow 2022-01, fhvhv 2021-06, fhv 2020-12, yellow 2020-05 (corrected in FUTURE) | daily files 2014-06-10 (HISTORY), 2017-03-14, 2016-08-02, 2018-02-07 (FUTURE) |
| `repartition` | a monthly file is replaced by `…_tripdata_<YYYY-MM>/part-0000.parquet` + `part-0001.parquet` (identical rows) | fhvhv 2020-09, yellow 2024-06 | – |
| `rename_dir` | directory rename, contents identical | `misc/` → `reference/` (zone lookup) | – |
| `late_day` | a daily file withheld from its month's batch arrives years later | – | 2017-11-20 |

Real non-append drift (no synthesis): TLC column renames / additions / type changes and the zone-lookup revision;
TLC data-dictionary revisions; Backblaze SMART column growth (85 → 179 columns before 2023, more afterwards), header-only
daily files, `\r` line endings, varying directory layout, documentation revisions.

## 4. Facts, oracles and base rates (summary; full tables below)

* Fact types D1–D8 are defined in `README.md` / `facts_dl.py`. For each type, the candidates that exist at s0 are
  enumerated, shuffled (seed 0), and up to 150 are evaluated at every window snapshot (the **pool**). From the pool,
  11 facts are drawn uniformly (**natural**), and 11 more among the facts whose value changes in FUTURE (**enriched**;
  if the pool has too few, extra candidates beyond the pool are scanned, and if there are still too few, the remainder
  is filled with unchanged pool facts labelled `enriched_fill`).
* Oracle values: an exact DuckDB full scan of every file version (per-file profile: counts, exact DECIMAL sums,
  group counts, serial-number sets, schemas), combined over the files the fact depends on in that snapshot.
  Each value is cached by the exact set of (path, sha256) it depends on. `oracle_direct()` recomputes a value with
  a single independent DuckDB statement over the snapshot's files (or file headers / Parquet footers for schema facts).
  `smoke_test_report_tlc_bb.txt`: 30 random stored values per lake recomputed this way.
* Counts: **TLC 176 facts** (88 natural + 88 enriched, 10 of them unchanged fill-ins in D2), 51,040 oracle rows;
  **Backblaze 168 facts** (88 natural + 80 enriched, 17 fill-ins in D2/D3/D5), 27,888 oracle rows.
* Natural base rate of a truth change within FUTURE (pool of up to 150 per type → natural sample of 11):

| type | TLC pool | TLC natural | BB pool | BB natural |
|---|---|---|---|---|
| D1 schema type | 0.43 | 0.45 | 0.18 | 0.45 |
| D2 field mapping | 0.02 | 0.00 | 0.00 | 0.00 |
| D3 partition aggregate | 0.05 | 0.00 | 0.02 | 0.00 |
| D4 running aggregate | 0.56 | 0.55 | 0.36 | 0.36 |
| D5 top-k / argmax | 0.09 | 0.00 | 0.05 | 0.18 |
| D6 join | 0.29 | 0.36 | 0.53 | 0.36 |
| D7 data quality | 0.11 | 0.18 | 0.19 | 0.18 |
| D8 existence / coverage | 0.42 | 0.55 | 0.47 | 0.55 |
| all natural facts | | 0.26 | | 0.26 |

## 5. Known gaps and caveats

* TLC window is 2019-01 … 2026-08 (fhvhv starts 2019-02, when HVFHS licensing began). Earlier years (2009–2018,
  including the 2009–2010 yellow schema with different column names) were not included to keep the download (~45 GB of
  2019+ originals) manageable; the 2019+ window already contains the airport_fee→Airport_fee rename, the 2023-02
  type changes, cbd_congestion_fee (2025-01) and request_source (2026-06).
* Arrival times of monthly files are **nominal** (release lag model), not the true historical publication times;
  most current TLC originals were (re)written on 2022-06-30 / 2022-07-18 (the CSV→Parquet conversion), and several
  later files have Last-Modified dates months after their nominal release, i.e. they were republished — but the
  earlier versions are not obtainable, so real republications could not be replayed (hence the labelled synthetic
  correction events).
* The bootstrap snapshot of the TLC lake contains the earliest available dictionary versions (Wayback 2019-08 / 2019-10)
  although the lake starts at 2019-03; the Wayback timestamp of each later version is an upper bound on its publication date.
* Backblaze monthly batches are finer than the real quarterly release; the documentation page versions are one capture
  per year (first capture of each year), not every revision.
* D1 for Backblaze uses DuckDB's type inference on the 1/64-subsampled file; all-empty SMART columns infer as VARCHAR, so
  some type "changes" reflect which drives are present rather than a declared schema change. This is real behaviour of
  the subsampled lake and of CSV type inference, but it is not a Backblaze schema event.
* D2 has (almost) no natural drift in either lake: in TLC only yellow `airport_fee`→`Airport_fee` (2023-02) changes;
  in Backblaze SMART column names are stable and the 2023 additions (`datacenter`, `vault_id`, …) do not exist at s0, so
  they cannot be facts (K would be NONE). D3 changes only through the labelled synthetic corrections / late day.
  Backblaze D5 is nearly static (one model dominates every period). All of this is reported, not hidden.
* Base rates depend on the fact distribution chosen here (periods, columns); pool base rates are the more reliable
  natural numbers; the natural samples (n = 11 per type) are small.
* Synthetic-event shares: TLC 15 of 383 snapshots are flagged (6 preliminary arrivals of real files with ~3 % rows held
  back + 9 extra events); Backblaze 5 of 176 events (+ 4 arrival batches containing one preliminary daily file each).

<!-- STATS:BEGIN -->
<!-- generated by make_manifest.py -->

## Generated statistics

### TLC source files

| dataset | months requested | available | not available | raw bytes | raw rows | kept rows (1/64) | stored bytes | schema identical after subsampling |
|---|---|---|---|---|---|---|---|---|
| yellow | 2019-01 .. 2026-08 (92) | 92 | - | 5.0 GB | 337,713,845 | 5,276,755 (1.562%) | 112.0 MB | 92/92 |
| green | 2019-01 .. 2026-08 (92) | 92 | - | 219.6 MB | 12,320,085 | 192,650 (1.564%) | 5.1 MB | 92/92 |
| fhv | 2019-01 .. 2026-08 (92) | 91 | 2026-08 | 1.5 GB | 160,889,469 | 2,512,702 (1.562%) | 40.3 MB | 91/91 |
| fhvhv | 2019-02 .. 2026-08 (91) | 91 | - | 38.5 GB | 1,648,689,733 | 25,757,616 (1.562%) | 929.0 MB | 91/91 |
| **total** | | | | 45.3 GB | 2,159,613,132 | 33,739,723 | 1.1 GB | |

**Real republication evidence (HTTP Last-Modified of the current originals).** A file whose Last-Modified is later than ~3 months after the end of its data month has been (re)published after the nominal release; the earlier versions are not obtainable, so only the current version is in the lake.

| Last-Modified date | # files |
|---|---|
| 30 Jun 2022 | 124 |
| 18 Jul 2022 | 31 |
| 30 Aug 2022 | 12 |
| 14 Nov 2022 | 8 |
| 20 Mar 2023 | 8 |
| 23 Apr 2025 | 8 |
| 25 Mar 2026 | 8 |
| 17 Sep 2026 | 8 |
| 25 Jun 2025 | 7 |
| 02 Nov 2023 | 5 |
| 30 Nov 2022 | 4 |
| 19 Dec 2022 | 4 |

### TLC schema-change timeline (real, from the Parquet footers of consecutive monthly files)

| dataset | first month with the change | added | removed | type changes |
|---|---|---|---|---|
| yellow | 2020-08 | - | - | airport_fee: null→double |
| yellow | 2020-10 | - | - | airport_fee: double→null |
| yellow | 2020-11 | - | - | airport_fee: null→double |
| yellow | 2023-02 | Airport_fee | airport_fee | VendorID: int64→int32; passenger_count: double→int64; RatecodeID: double→int64; store_and_fwd_flag: string→large_string; PULocationID: int64→int32; DOLocationID: int64→int32 |
| yellow | 2025-01 | cbd_congestion_fee | - | - |
| yellow | 2026-06 | request_source | - | - |
| green | 2019-09 | - | - | ehail_fee: double→null |
| green | 2023-02 | - | - | VendorID: int64→int32; store_and_fwd_flag: string→large_string; RatecodeID: double→int64; PULocationID: int64→int32; DOLocationID: int64→int32; passenger_count: double→int64; ehail_fee: null→double; payment_type: double→int64; trip_type: double→int64 |
| green | 2025-01 | cbd_congestion_fee | - | - |
| green | 2026-06 | request_source | - | - |
| fhv | 2019-03 | - | - | SR_Flag: double→null |
| fhv | 2019-05 | - | - | PUlocationID: double→int64; DOlocationID: double→int64 |
| fhv | 2019-07 | - | - | PUlocationID: int64→double; DOlocationID: int64→double |
| fhv | 2020-07 | - | - | DOlocationID: double→int64 |
| fhv | 2020-08 | - | - | DOlocationID: int64→double |
| fhv | 2023-02 | - | - | dispatching_base_num: string→large_string; PUlocationID: double→int64; DOlocationID: double→int64; SR_Flag: null→int64; Affiliated_base_number: string→large_string |
| fhvhv | 2019-04 | - | - | wav_match_flag: null→string |
| fhvhv | 2019-07 | - | - | airport_fee: null→double |
| fhvhv | 2020-04 | - | - | airport_fee: double→null |
| fhvhv | 2020-05 | - | - | airport_fee: null→double |
| fhvhv | 2020-10 | - | - | airport_fee: double→null |
| fhvhv | 2020-11 | - | - | airport_fee: null→double |
| fhvhv | 2023-02 | - | - | hvfhs_license_num: string→large_string; dispatching_base_num: string→large_string; originating_base_num: string→large_string; PULocationID: int64→int32; DOLocationID: int64→int32; shared_request_flag: string→large_string; shared_match_flag: string→large_string; access_a_ride_flag: string→large_string; wav_request_flag: string→large_string; wav_match_flag: string→large_string |
| fhvhv | 2025-01 | cbd_congestion_fee | - | - |

### Backblaze source files

| zips requested | available | not available | raw zip bytes | daily CSVs | raw rows (drive-days) | kept rows (1/64 of drives) | stored bytes |
|---|---|---|---|---|---|---|---|
| 45 (data_2013.zip .. ) | 45 | - | 32.7 GB | 4830 | 744,525,690 | 11,401,095 (1.531%) | 3.7 GB |

Skipped zip members (macOS resource forks `__MACOSX/`, dot-files): 4246. Real header-only daily files (0 data rows in the original): 3 (2014-11-02, 2015-11-01, 2017-01-30).

### Backblaze schema-change timeline (real, from the CSV headers of consecutive daily files)

| first day | #columns | added | removed |
|---|---|---|---|
| 2013-04-10 | 85 | (initial) | |
| 2015-01-01 | 95 | smart_22_normalized, smart_22_raw, smart_220_normalized, smart_220_raw, smart_222_normalized, smart_222_raw, smart_224_normalized, smart_224_raw, smart_226_normalized, smart_226_raw | - |
| 2018-01-01 | 105 | smart_177_normalized, smart_177_raw, smart_179_normalized, smart_179_raw, smart_181_normalized, smart_181_raw, smart_182_normalized, smart_182_raw, smart_235_normalized, smart_235_raw | - |
| 2018-04-01 | 109 | smart_23_normalized, smart_23_raw, smart_24_normalized, smart_24_raw | - |
| 2018-10-01 | 129 | smart_16_normalized, smart_16_raw, smart_17_normalized, smart_17_raw, smart_168_normalized, smart_168_raw, smart_170_normalized, smart_170_raw, smart_173_normalized, smart_173_raw, smart_174_normalized, smart_174_raw, smart_218_normalized, smart_218_raw, smart_231_normalized, smart_231_raw, smart_232_normalized, smart_232_raw, smart_233_normalized, smart_233_raw | - |
| 2019-10-01 | 131 | smart_18_normalized, smart_18_raw | - |
| 2020-10-01 | 149 | smart_175_normalized, smart_175_raw, smart_180_normalized, smart_180_raw, smart_202_normalized, smart_202_raw, smart_206_normalized, smart_206_raw, smart_210_normalized, smart_210_raw, smart_234_normalized, smart_234_raw, smart_245_normalized, smart_245_raw, smart_247_normalized, smart_247_raw, smart_248_normalized, smart_248_raw | - |
| 2021-07-01 | 169 | smart_160_normalized, smart_160_raw, smart_161_normalized, smart_161_raw, smart_163_normalized, smart_163_raw, smart_164_normalized, smart_164_raw, smart_165_normalized, smart_165_raw, smart_166_normalized, smart_166_raw, smart_167_normalized, smart_167_raw, smart_169_normalized, smart_169_raw, smart_176_normalized, smart_176_raw, smart_178_normalized, smart_178_raw | - |
| 2021-10-01 | 179 | smart_171_normalized, smart_171_raw, smart_172_normalized, smart_172_raw, smart_230_normalized, smart_230_raw, smart_244_normalized, smart_244_raw, smart_246_normalized, smart_246_raw | - |
| 2023-04-01 | 186 | vault_id, pod_id, is_legacy_format, smart_71_normalized, smart_71_raw, smart_90_normalized, smart_90_raw | - |
| 2023-07-01 | 193 | datacenter, cluster_id, pod_slot_num, smart_27_normalized, smart_27_raw, smart_82_normalized, smart_82_raw | - |
| 2024-04-01 | 197 | smart_211_normalized, smart_211_raw, smart_212_normalized, smart_212_raw | - |

Real directory layouts inside the zips (kept as-is under `drive_stats/`): 45 distinct directories, e.g. drive_stats/2013, drive_stats/2014, drive_stats/2015 … drive_stats/data_Q4_2024, drive_stats/data_Q4_2025.

### Snapshot sequence: tlc

* snapshots (events): **383**; s0 = `tlc-0153` (index 153, 2022-05-15T12:00:00Z); HISTORY = 60 snapshots (from index 93, 2021-02-15T12:01:00Z); FUTURE = 229 snapshots (to 2026-10-15T12:03:00Z).
* events by kind: arrive: 360, arrive (SYNTHETIC): 6, bootstrap: 1, correct (SYNTHETIC): 6, doc: 6, lookup: 1, rename_dir (SYNTHETIC): 1, repartition (SYNTHETIC): 2
* synthetic events: 15 of 383 (3.9%); every one is flagged `synthetic: true` in the event list.

| idx | time | kind | real/synthetic | phase | files | note |
|---|---|---|---|---|---|---|
| 0 | 2019-03-01 | bootstrap | real | pre-window | docs/data_dictionary_trip_records_fhv.txt, docs/data_dictionary_trip_records_green.txt (+3) | per doc/lookup path: latest version available before the lake start, else the earliest available version |
| 64 | 2020-07-15 | arrive | SYNTHETIC | pre-window | trip-data/yellow_tripdata_2020-05.parquet | SYNTHETIC preliminary version: 191 of 5497 rows held back as late-arriving |
| 94 | 2021-02-15 | arrive | SYNTHETIC | HISTORY | trip-data/fhv_tripdata_2020-12.parquet | SYNTHETIC preliminary version: 563 of 18459 rows held back as late-arriving |
| 104 | 2021-05-15 | arrive | SYNTHETIC | HISTORY | trip-data/yellow_tripdata_2021-03.parquet | SYNTHETIC preliminary version: 969 of 30199 rows held back as late-arriving |
| 119 | 2021-08-15 | arrive | SYNTHETIC | HISTORY | trip-data/fhvhv_tripdata_2021-06.parquet | SYNTHETIC preliminary version: 7353 of 233287 rows held back as late-arriving |
| 120 | 2021-09-01 | correct | SYNTHETIC | HISTORY | trip-data/yellow_tripdata_2021-03.parquet | SYNTHETIC late-arriving correction: full file republished |
| 138 | 2022-01-15 | arrive | SYNTHETIC | HISTORY | trip-data/green_tripdata_2021-11.parquet | SYNTHETIC preliminary version: 42 of 1612 rows held back as late-arriving |
| 145 | 2022-03-15 | arrive | SYNTHETIC | HISTORY | trip-data/yellow_tripdata_2022-01.parquet | SYNTHETIC preliminary version: 1223 of 38504 rows held back as late-arriving |
| 161 | 2022-07-07 | doc | real | FUTURE | docs/data_dictionary_trip_records_yellow.txt | wayback:20220707150454 |
| 170 | 2022-08-20 | correct | SYNTHETIC | FUTURE | trip-data/green_tripdata_2021-11.parquet | SYNTHETIC late-arriving correction: full file republished |
| 179 | 2022-11-10 | correct | SYNTHETIC | FUTURE | trip-data/yellow_tripdata_2022-01.parquet | SYNTHETIC late-arriving correction: full file republished |
| 184 | 2022-12-06 | doc | real | FUTURE | docs/data_dictionary_trip_records_hvfhs.txt | wayback:20221206172552 |
| 205 | 2023-05-05 | correct | SYNTHETIC | FUTURE | trip-data/fhvhv_tripdata_2021-06.parquet | SYNTHETIC late-arriving correction: full file republished |
| 222 | 2023-09-01 | repartition | SYNTHETIC | FUTURE | trip-data/fhvhv_tripdata_2020-09/part-0000.parquet, trip-data/fhvhv_tripdata_2020-09/part-0001.parquet; removed 1 | SYNTHETIC re-partition into two part files (identical rows) |
| 247 | 2024-02-22 | lookup | real | FUTURE | misc/taxi_zone_lookup.csv | origin:last-modified |
| 260 | 2024-06-12 | correct | SYNTHETIC | FUTURE | trip-data/fhv_tripdata_2020-12.parquet | SYNTHETIC late-arriving correction: full file republished |
| 273 | 2024-09-01 | rename_dir | SYNTHETIC | FUTURE | reference/taxi_zone_lookup.csv; removed 1 | SYNTHETIC directory rename misc/ -> reference/ |
| 302 | 2025-04-02 | doc | real | FUTURE | docs/data_dictionary_trip_records_yellow.txt | wayback:20250402075938 |
| 311 | 2025-05-16 | doc | real | FUTURE | docs/data_dictionary_trip_records_hvfhs.txt | wayback:20250516185515 |
| 312 | 2025-05-21 | doc | real | FUTURE | docs/data_dictionary_trip_records_green.txt | wayback:20250521025955 |
| 313 | 2025-05-21 | doc | real | FUTURE | docs/data_dictionary_trip_records_fhv.txt | wayback:20250521025955 |
| 318 | 2025-07-01 | correct | SYNTHETIC | FUTURE | trip-data/yellow_tripdata_2020-05.parquet | SYNTHETIC late-arriving correction: full file republished |
| 331 | 2025-10-01 | repartition | SYNTHETIC | FUTURE | trip-data/yellow_tripdata_2024-06/part-0000.parquet, trip-data/yellow_tripdata_2024-06/part-0001.parquet; removed 1 | SYNTHETIC re-partition into two part files (identical rows) |

### Snapshot sequence: bb

* snapshots (events): **176**; s0 = `bb-0070` (index 70, 2018-10-01T00:00:00Z); HISTORY = 60 snapshots (from index 10, 2014-02-01T00:00:00Z); FUTURE = 105 snapshots (to 2026-07-01T00:00:00Z).
* events by kind: arrive: 159, bootstrap: 1, correct (SYNTHETIC): 4, doc: 11, late_day (SYNTHETIC): 1
* synthetic events: 5 of 176 (2.8%); every one is flagged `synthetic: true` in the event list.

| idx | time | kind | real/synthetic | phase | files | note |
|---|---|---|---|---|---|---|
| 0 | 2013-04-01 | bootstrap | real | pre-window |  | empty lake (docs arrive later) |
| 15 | 2014-07-01 | arrive | SYNTHETIC | HISTORY | drive_stats/2014/2014-06-01.csv, drive_stats/2014/2014-06-02.csv (+28) | 30 daily files of 2014-06 (real cadence: quarterly zip; monthly batches here); contains SYNTHETIC preliminary file(s) |
| 22 | 2015-01-15 | correct | SYNTHETIC | HISTORY | drive_stats/2014/2014-06-10.csv | SYNTHETIC late-arriving correction of 2014-06-10: full file republished (13 rows were missing from the preliminary file) |
| 38 | 2016-04-23 | doc | real | HISTORY | docs/hard-drive-test-data.txt | wayback:20160423165839 |
| 43 | 2016-09-01 | arrive | SYNTHETIC | HISTORY | drive_stats/data_Q3_2016/2016-08-01.csv, drive_stats/data_Q3_2016/2016-08-02.csv (+29) | 31 daily files of 2016-08 (real cadence: quarterly zip; monthly batches here); contains SYNTHETIC preliminary file(s) |
| 50 | 2017-04-01 | arrive | SYNTHETIC | HISTORY | drive_stats/data_Q1_2017/2017-03-01.csv, drive_stats/data_Q1_2017/2017-03-02.csv (+29) | 31 daily files of 2017-03 (real cadence: quarterly zip; monthly batches here); contains SYNTHETIC preliminary file(s) |
| 53 | 2017-06-30 | doc | real | HISTORY | docs/hard-drive-test-data.txt | wayback:20170630073637 |
| 62 | 2018-02-02 | doc | real | HISTORY | docs/hard-drive-test-data.txt | wayback:20180202094312 |
| 63 | 2018-03-01 | arrive | SYNTHETIC | HISTORY | drive_stats/data_Q1_2018/2018-02-01.csv, drive_stats/data_Q1_2018/2018-02-02.csv (+26) | 28 daily files of 2018-02 (real cadence: quarterly zip; monthly batches here); contains SYNTHETIC preliminary file(s) |
| 74 | 2019-01-23 | doc | real | FUTURE | docs/hard-drive-test-data.txt | wayback:20190123174149 |
| 79 | 2019-05-15 | correct | SYNTHETIC | FUTURE | drive_stats/data_Q1_2017/2017-03-14.csv | SYNTHETIC late-arriving correction of 2017-03-14: full file republished (43 rows were missing from the preliminary file) |
| 88 | 2020-01-04 | doc | real | FUTURE | docs/hard-drive-test-data.txt | wayback:20200104165344 |
| 91 | 2020-03-15 | late_day | SYNTHETIC | FUTURE | drive_stats/data_Q4_2017/2017-11-20.csv | SYNTHETIC: daily file 2017-11-20 withheld from its month batch, arrives late |
| 102 | 2021-01-03 | doc | real | FUTURE | docs/hard-drive-test-data.txt | wayback:20210103071250 |
| 104 | 2021-02-15 | correct | SYNTHETIC | FUTURE | drive_stats/data_Q3_2016/2016-08-02.csv | SYNTHETIC late-arriving correction of 2016-08-02: full file republished (27 rows were missing from the preliminary file) |
| 116 | 2022-01-12 | doc | real | FUTURE | docs/hard-drive-test-data.txt | wayback:20220112023648 |
| 129 | 2023-01-30 | doc | real | FUTURE | docs/hard-drive-test-data.txt | wayback:20230130001203 |
| 142 | 2024-01-07 | doc | real | FUTURE | docs/hard-drive-test-data.txt | wayback:20240107054135 |
| 146 | 2024-04-15 | correct | SYNTHETIC | FUTURE | drive_stats/data_Q1_2018/2018-02-07.csv | SYNTHETIC late-arriving correction of 2018-02-07: full file republished (40 rows were missing from the preliminary file) |
| 156 | 2025-01-07 | doc | real | FUTURE | docs/hard-drive-test-data.txt | wayback:20250107181021 |
| 169 | 2026-01-01 | doc | real | FUTURE | docs/hard-drive-test-data.txt | wayback:20260101134321 |

### Facts: tlc (176 facts; s0 = tlc-0153, FUTURE = 229 snapshots)

Base rate = fraction of facts whose oracle value differs from K (the s0 value) in at least one FUTURE snapshot; pair rate = fraction of (fact, FUTURE snapshot) pairs in which the value differs from K.

| type | candidates at s0 | pool evaluated | **pool base rate** | pool pair rate | natural n | natural base rate | natural pair rate | enriched n (of which unchanged fill-ins) | enriched base rate |
|---|---|---|---|---|---|---|---|---|---|
| D1 | 70 | 70 | 0.429 | 0.338 | 11 | 0.455 | 0.358 | 11 (0) | 1.000 |
| D2 | 46 | 46 | 0.022 | 0.017 | 11 | 0.000 | 0.000 | 11 (10) | 0.091 |
| D3 | 1673 | 150 | 0.047 | 0.030 | 11 | 0.000 | 0.000 | 11 (0) | 1.000 |
| D4 | 135 | 133 | 0.564 | 0.504 | 11 | 0.545 | 0.503 | 11 (0) | 1.000 |
| D5 | 191 | 150 | 0.087 | 0.076 | 11 | 0.000 | 0.000 | 11 (0) | 1.000 |
| D6 | 572 | 150 | 0.293 | 0.224 | 11 | 0.364 | 0.319 | 11 (0) | 1.000 |
| D7 | 1276 | 150 | 0.107 | 0.103 | 11 | 0.182 | 0.175 | 11 (0) | 1.000 |
| D8 | 192 | 150 | 0.420 | 0.416 | 11 | 0.545 | 0.541 | 11 (0) | 1.000 |
| **all** | | | | | 88 | 0.261 | 0.237 | 88 | 0.886 |

### Facts: bb (168 facts; s0 = bb-0070, FUTURE = 105 snapshots)

Base rate = fraction of facts whose oracle value differs from K (the s0 value) in at least one FUTURE snapshot; pair rate = fraction of (fact, FUTURE snapshot) pairs in which the value differs from K.

| type | candidates at s0 | pool evaluated | **pool base rate** | pool pair rate | natural n | natural base rate | natural pair rate | enriched n (of which unchanged fill-ins) | enriched base rate |
|---|---|---|---|---|---|---|---|---|---|
| D1 | 109 | 109 | 0.183 | 0.153 | 11 | 0.455 | 0.351 | 11 (0) | 1.000 |
| D2 | 14 | 14 | 0.000 | 0.000 | 11 | 0.000 | 0.000 | 3 (3) | 0.000 |
| D3 | 330 | 150 | 0.020 | 0.016 | 11 | 0.000 | 0.000 | 11 (4) | 0.636 |
| D4 | 42 | 42 | 0.357 | 0.343 | 11 | 0.364 | 0.318 | 11 (0) | 1.000 |
| D5 | 65 | 59 | 0.051 | 0.050 | 11 | 0.182 | 0.180 | 11 (10) | 0.091 |
| D6 | 314 | 150 | 0.527 | 0.461 | 11 | 0.364 | 0.281 | 11 (0) | 1.000 |
| D7 | 169 | 150 | 0.193 | 0.181 | 11 | 0.182 | 0.175 | 11 (0) | 1.000 |
| D8 | 220 | 150 | 0.467 | 0.467 | 11 | 0.545 | 0.545 | 11 (0) | 1.000 |
| **all** | | | | | 88 | 0.261 | 0.231 | 80 | 0.787 |

### Storage

* content-addressed store: 4.8 GB (5230 blobs)
* whole `datalake_data` directory: 4.9 GB

<!-- STATS:END -->
