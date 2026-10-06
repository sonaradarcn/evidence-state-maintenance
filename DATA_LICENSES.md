# Third-party data

The MIT license in `LICENSE` covers the code and documentation written for this project. The files below are derived
from third-party sources and remain under the terms of those sources.

| files | derived from | terms |
|---|---|---|
| `heldout/facts_*.json`, `data/heldout_oracle_tables/` | 16 public GitHub repositories (list and URLs in `heldout/MANIFEST.md`): questions about their source code, commit hashes, values computed from it | the license of each repository (all are OSI-approved open-source licenses) |
| `datalake/facts_tlc.json`, `datalake/oracle/oracle_tlc.parquet`, `data/datalake_catalog/tlc/` | NYC Taxi & Limousine Commission trip record data | NYC Open Data terms of use |
| `datalake/facts_bb.json`, `datalake/oracle/oracle_bb.parquet`, `data/datalake_catalog/bb/` | Backblaze Drive Stats | Backblaze's terms for the Drive Stats data (attribution to Backblaze required) |
| `data/datalake_catalog/docs/` | data dictionaries and lookup tables published by NYC TLC and Backblaze (hashes and metadata only) | as above |
| `data/events_github.parquet` | timestamps of issues and commits of 58 public GitHub repositories (no issue text) | GitHub Terms of Service |

The data lakes themselves are not redistributed; `esm/e2e_lake/fetch_lake.py` downloads them from the publishers.
