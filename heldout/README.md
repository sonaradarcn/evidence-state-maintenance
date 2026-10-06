# Held-out benchmark: code facts with programmatic ground truth over real commit histories

Built without any LLM call and without GPUs. Summary numbers are in `MANIFEST.md`, and the independent oracle check is in `VALIDATION.md`.

## Files

| path | content |
|---|---|
| `heldout/facts_<repo>.json` | **the benchmark**: all facts of one repo (static + behaviour, both subsets), commit list, stats |
| `heldout/facts_<repo>.static.json` | intermediate static-only output of `static_h.py` (superseded by `facts_<repo>.json`) |
| `heldout/MANIFEST.md`, `heldout/VALIDATION.md` | summary / validation reports |
| `heldout_data/repos/<repo>` | full clones (with blobs) from github.com (direct; no mirror was needed) |
| `heldout_data/trees/<repo>.pkl` | 701-commit tree cache (same format as pilot3/pilot6) |
| `heldout_data/oracle_tables/oracle_<repo>.parquet` | compact oracle table: `fact_id, commit_idx, value_hash, changed, is_none` (701 rows per fact) |
| `heldout_data/oracle_tables/oracle_values_<repo>.parquet` | `fact_id, value_hash, value`: join this to recover full values |
| `heldout_data/oracle_tables/commits_<repo>.parquet` | `commit_idx, commit, segment` (HISTORY / s0 / FUTURE) |
| `heldout_data/oracle_tables/oracle_all.parquet` | all repos concatenated, with `repo, subset, type` |
| `heldout_data/oracle_tables/static_<repo>.values.parquet`, `.reference.parquet` | full static value series of the facts / of the reference samples |
| `heldout_data/behav/<repo>.cands.json`, `.truth.json`, `behav_facts.json`, `behav_truth_selected.json` | behaviour candidates (with both s0 probes), full truth series of every valid candidate, selected facts |
| `heldout_data/deps/<repo>` | fixed dependency directory added to `PYTHONPATH` for behaviour execution (identical for all commits) |

Pipeline (Python 3.14, `python -B -W ignore`):
`build_trees.py <repo>` → `static_h.py <repo>` → `behav_h.py cands <repo>` → `behav_h.py truth <repo>` → `behav_h.py select` →
`build_manifest.py` → `validate_h.py`.

## Protocol (same as the dev set)

* First-parent history of the default branch at clone time (2026-10-02). `s0` = HEAD − 400 first-parent commits. HISTORY = the 300
  commits before s0. FUTURE = the 400 commits after s0, ending at HEAD. `commits[0..700]`, index 300 = s0. This is pilot3's `vfs.Repo` layout.
* Static oracles: `facts.py` (`enumerate_candidates`, `oracle`, `question`, `fact_file`) and `vfs.py` in this folder, the
  development-set modules copied unchanged (`esm/envs/pyfacts.py` and `esm/tools.py` are package copies with the same semantics).
* Behaviour truth: pilot6 semantics. `python -S -B`, `PYTHONPATH` = that commit's package files materialised from git blobs, 5 s timeout per call.
  The value is the canonical repr, `raises <Type>`, or `NONE` (module import fails or called attribute missing).
  `runner_h.py` produces values identical to `pilot6/runner_exec.py`.

## Fact schema (superset of pilot3 / pilot6)

`facts_<repo>.json` = `{repo, url, s0, head, first_history, n_first_parent, commits[701], layout, stats{static, behaviour}, facts[...],
behaviour_runtime?}`. pilot3 had `{repo, s0, head, stats, facts}`. Those keys are present with the same meaning; `stats` is now nested.

Static fact (pilot3 fields unchanged: `id, repo, type, args, K_oracle, n_future_changed, question`), plus:

* `subset`: `"enriched"` | `"natural"`
* `same_fact_as`: id of the identical fact in the other subset, or null
* `n_history_changed`: HISTORY commits whose value ≠ s0 value
* `file_hot_history`: HISTORY modification count of the fact's file
* `none_at_future_end`: value at HEAD is NONE
* `future_invalid_frac`: fraction of FUTURE commits with value ≠ K
* `first_future_change`: 1-based FUTURE offset of the first change, or null
* `n_distinct_future_values`
* `change_only_by_disappearance`: every differing FUTURE value is NONE
* `changes_to_other_value`
* `transient_none_only`: only NONE blips, and the value at HEAD equals K again

Behaviour fact (pilot6 layout: `type: "B"`, `args: {module, func, expr, file}`, `question` with pilot6's exact wording, `K`), plus:

* `K_oracle` (= `K`) and `n_future_changed`, as for static facts
* `source`: `"doctest"` | `"synth"`
* `doctest_want`: the docstring's expected output, for information only. The truth is execution, not this.
* `wrapped`: the expression was wrapped in `list(...)` / `repr(...)`
* `cid`, plus the same diagnostic fields as static facts

**Schema differences to note**

1. **Fact ids.**
   * Enriched static ids are pilot3-style `<repo>:<type>:<n>`. Natural static ids are `<repo>:<type>:n<j>`.
   * Behaviour ids are `<repo>:B:<func>:<sha1(expr)[:8]>`. Natural behaviour ids are `<repo>:B:<func>:n-<hash>`. pilot6 used `<repo>:B:<func>:<k>`.
   * The `<repo>` part can contain a hyphen (`poetry-core`), never a colon.
2. **Truth series are not embedded** in the fact JSON. pilot6's `behav_facts.json` embedded them; pilot4 kept static truth in
   `sig_<repo>.pkl`. Here, read `oracle_<repo>.parquet` joined with `oracle_values_<repo>.parquet`, ordered by `commit_idx`. This gives the same
   701-value list that pilot7's `load_facts()` expects in `truth`, and `valid[i] = truth[301 + i] == K`.
3. **No derivation fields.** The trace, model, cite and certzs fields are absent. No agent has derived these facts yet; that is the job of
   the evaluation run.

## Decisions and deviations, with reasons

* **Extra non-source directories.** At runtime they are added to pilot3's `EXCL_DIRS`, which affects T1/T6 enumeration and oracles and
  `is_source`. The directories are `docs_src, benchmark, requirements, news, stubs, sample_project, tutorial, examples_src, extras, misc,
  devtools, playground, test_data, testdata` (`common_h.EXTRA_EXCL`). Example: typer's `docs_src/` holds about 500 tutorial `.py` files. These
  are not package source, and the T1/T6 question text already excludes docs/examples.
* **T5/dir fast path.** Inside `static_h.py`, T5/dir uses the per-commit `dircount` index. It has the same definition as
  `facts.oracle`'s path loop. `validate_h.py` uses the unmodified loop.
* **Enriched static subset.** This is pilot3's `sample_facts` logic with `PER_TYPE = 6`, so at most 42 facts per repo.
  * Pool: ≤ 250 candidates per type, half of the sort keys HISTORY-hot.
  * Picks: ≥ half changing in FUTURE where possible.
  * A type with fewer candidates contributes fewer facts and is not back-filled. Example: boltons has no T6 candidates and only 5 T4.
  * The RNG call order differs from pilot3 because pool evaluation is commit-outer, so this is not bit-identical to pilot3's sampling.
    It is the same procedure.
* **Natural static subset.** 40 facts drawn uniformly from all eligible candidates, all types pooled. Eligible = enumerated at s0 and
  oracle(s0) ≠ NONE. Selection uses no HISTORY or FUTURE information, so the type mix follows each repo's candidate mix, which is dominated
  by T1–T3.
  * Per-type natural base rates also come from a larger uniform reference sample: up to 120 per type per repo, kept as stats only.
* **Behaviour candidates (no LLM).**
  * **Doctests.** Examples are parsed with `doctest.DocTestParser` from the module, function, class and method docstrings of the s0
    package. Each expression example is rewritten to fully qualified names:
    * doctest-local imports
    * module-level definitions, and the module's own imports, resolved to absolute package paths
    * the `nx` alias that networkx's `conftest.py` injects into every doctest
    * simple doctest assignments, which are inlined
    * `print(x)` → `str(x)`

    A doctest variable is poisoned, i.e. not inlined any more, after any statement that rebinds or may mutate it (`x[..] = `, `x.a = `,
    `x += `, `x.method(...)`). Expressions referencing anything outside the package plus builtins are dropped. So are those matching
    an impurity regex: time, random, os, sys, I/O, gc/traceback/inspect, boltons' env/gc/tb/socket/file utils.
  * **Synthesised calls.** These cover public, undecorated top-level functions of public modules that pass pilot6's body purity regex
    and are 3–80 lines long. Up to 3 calls each. Argument literals come from a fixed pool keyed by annotation, else default type, else
    parameter-name heuristics.
  * **Probe at s0.** Every expression is evaluated twice in one process (`PYTHONHASHSEED=0`) and again, twice, in a second process
    (`PYTHONHASHSEED=1`). It is kept iff:
    * all 4 values are identical
    * the first evaluation took < 1 s
    * the value has no `at 0x`, is ≤ 300 chars and is `ast.literal_eval`-able (or is `raises X`)
    * the value is not `None` (mutator calls)
    * the value is not one of the artefact exceptions: Name/Import/ModuleNotFound/Attribute/Syntax/Recursion/Memory error

    Non-literal results are retried wrapped: `list(...)` if the result is an iterator, else `repr(...)`. At selection, I/O-error values
    (`raises FileNotFoundError` etc.) are dropped.
  * **Truth run and selection.** The truth run re-executes s0. Any candidate whose s0 value differs from the probe is dropped; there were
    none.
    * Enriched: pilot6's `cmd_select` rule. Changing candidates come first, up to ≥ half; ≤ 4 per function if changing, ≤ 2 if stable.
    * Natural: uniform random order, ≤ 2 per function. It does not look at FUTURE.
    * Both subsets: `raises` values capped at 20 %, 10 facts per repo.
* **Behaviour runner hardening, values unaffected.**
  * The evaluated code's stdout is captured so prints cannot corrupt the JSON channel.
  * After a TIMEOUT the runner stops, and the remaining calls are re-run in a fresh process. pilot6 kept going with a runaway thread.
  * If a process dies without output, its calls are re-run one per process.
* **Fixed dependencies** (`heldout_data/deps/<repo>`, identical for every commit; the checkout comes first on `PYTHONPATH`).
  * jinja: MarkupSafe 2.0.1, the pure-Python part of the sdist. s0 (2018) imports `soft_unicode`, which was removed in 2.1; Jinja 3.x accepts ≥ 2.0.
  * werkzeug: MarkupSafe 3.0.3.
  * marshmallow: packaging 26.3.
  * isort: mypy_extensions 1.1.0.
  * rich: Pygments 2.21.0, markdown-it-py 4.2.0, mdurl 0.1.2.
  * **Stub `<dist>-0+heldout.dist-info/METADATA`** in every deps dir. Recent jinja and isort call
    `importlib.metadata.version("<own dist>")` at import time; a not-installed checkout would otherwise fail to import. Any value derived
    from the package's own installed version would read `0+heldout`.

## Known limitations

* **Everything executes and parses under Python 3.14,** as in pilots 3/6. Old code that 3.14 rejects counts as "gone" (NONE). This is
  not the same as a semantic change. Repos whose s0 is old:
  * boltons s0 is 2017-03: e.g. `boltons.dictutils` fails on `from collections import KeysView`, so its doctests are not candidates.
  * jinja s0 is 2018-08.
  * marshmallow's earliest HISTORY needs `distutils`.
  * jinja's 2013 HISTORY start fails with a regex `PatternError`.

  These mostly affect HISTORY and candidate yield, not FUTURE truth. The manifest therefore reports changes "to a non-NONE value"
  separately.
* **Transient breakages in real history are real NONE values.** Examples:
  * boltons FUTURE commit c8c442b9 has an IndentationError in `strutils.py`; it is fixed in the next commit.
  * jinja renamed `jinja2` → `jinja` on 2020-01-10 and reverted it two commits later.

  These count as truth changes, which matches the protocol. The `transient_none_only` / `changes_to_other_value` fields separate them.
* **Windows span years in slow repos.** boltons, jinja, arrow (dropped) and mkdocs run from 2017–2018 to 2025–2026. Fast repos (typer,
  scrapy, networkx, black) cover about 1–1.5 years. That is a property of the commit-count protocol.
* **pyparsing has no behaviour facts.** Its examples are `Example::` blocks rather than `>>>` doctests, and its functions take parser
  objects. The programmatic generator produced 3 candidates, all in a module needing an uninstalled dependency. It stays in the static set.
* **Behaviour runs execute in the materialised package directory, not a full checkout.** Package data files other than `.py`, `.pyi`
  and `py.typed` are not materialised. A call that needs such data at runtime would `raise`. The validation runs against a full
  checkout instead, which tests this.
* **Synthesised calls are partly trivial.** Examples: `slugify('abc')`, and `raises TypeError` for an ill-typed argument (capped at 20 %).
  Doctest-derived calls are the higher-quality share; see `source`.
