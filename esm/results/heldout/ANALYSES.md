# Additional held-out analyses

The sub-folders hold analyses added after the main held-out run, most of them during the review of the paper. Each
script lists its inputs in its docstring and writes a `.md` and a `.json` with the same stem next to itself.

| folder / script | content |
|---|---|
| `revision_r1/item1_clustered.py` | repository-cluster bootstrap, leave-one-repository-out, sign tests |
| `revision_r1/item2_noninferiority.py` | non-inferiority / equivalence (TOST) against CERT-ZS, CERT-v0h, LLMDIFF |
| `revision_r1/item3_reweight.py` | real-cost baselines re-weighted to the natural fact distribution |
| `revision_r1/item4_memo.py` | ablation of evidence-state memoisation |
| `revision_r1/item5_observation.py` | misses whose cause lies outside the recorded evidence (observation completeness) |
| `revision_r1/item6_anchoring.py` | anchored wrong re-derivations; first-order estimate of anchor expiry |
| `revision_r1/item7_minor.py` | small factual checks of numbers quoted in the paper |
| `revision_r1/cache/` | fact metadata and per-policy read tables extracted from the run data (inputs of the scripts above) |
| `revision_r1_runs/` | real runs of anchor expiry (S160) and of the strong baselines on NAT100; `analyze.py` |
| `revision_r2/` | construction cost of certificates; repeat-error statistic of Fig. 4d |
| `revision_r3/estimate_c.py` | estimate C of the anchor-expiry analysis |
| `revision_eswa/` | margin sensitivity and the analyses added for the journal revision |

`H150` in file and column names is the 160-fact subset called S160 in the paper.

Which scripts run from this repository alone: `revision_r1/item1`–`item5` and `revision_eswa/eswa_r2_analyses.py`
(they read `records.parquet` and `revision_r1/cache/`). The others also read the stage's working data
(`esm_data_heldout/`: derivation logs, observation tables, LLM cache), which is not in the repository, and
`item7_minor.py` checks numbers against the manuscript source. The pickles in `revision_r1/cache/` were written by
these scripts with pandas 3.0 under Python 3.14.
