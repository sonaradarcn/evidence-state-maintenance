"""Shared paths and the Stage-3 data-lake context rebuilt on the re-created lake store.

Nothing in the esm package, datalake/ or esm_data_datalake/ is modified.  The lake's data path is redirected (module attributes, before esm.envs.datalake is imported) to esm_data_e2e_lake/lake_data,
re-created by fetch_lake.py (sha256-verified against the archived catalogue).  A blob that is not yet in the store is
fetched on demand (blocking; the wait is measured and excluded from tool time).  Stage-3 LLM responses are read through
(identical request => identical response); Stage-3 derivations, truth series and observation tables are copied once
into esm_data_e2e_lake (read-only sources).
"""
import json, os, shutil, sys, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
E2E = ROOT / "esm_data_e2e_lake"
S3 = ROOT / "esm_data_datalake"
RES = ROOT / "esm" / "results" / "e2e_lake"
os.environ.setdefault("ESM_DATA", str(E2E))
os.environ.setdefault("ESM_STAGE", "e2e_lake")
os.environ.setdefault("ESM_PORTS_Q27", "11651")
assert Path(os.environ["ESM_DATA"]).resolve() == E2E.resolve(), "ESM_DATA must point at esm_data_e2e_lake"
SEED = 20261006
TS = {"tlc": [25, 50, 100], "bb": [20, 40, 80]}       # task snapshots (offsets after s0) = Stage-3 grid points
TTL_SHORT = {"tlc": 25, "bb": 20}
TTL_MID = {"tlc": 50, "bb": 40}

# ---- lake paths (must happen before facts_dl / esm.envs.datalake are imported)
sys.path.insert(0, str(ROOT / "datalake"))
import lake as L  # noqa: E402
from esm.e2e_lake import fetch_lake as FL  # noqa: E402

L.DATA = FL.LD
FL.RAW = FL.LD / "raw_ondemand"            # on-demand fetches never share partial files with the bulk fetcher
(FL.RAW / "tlc").mkdir(parents=True, exist_ok=True)
(FL.RAW / "bb").mkdir(parents=True, exist_ok=True)
L.STORE = FL.STORE
L.SNAPS = FL.LD / "snapshots"
(FL.LD / "cache").mkdir(parents=True, exist_ok=True)

FETCH_WAIT = threading.local()
_orig_blob_path = L.blob_path


def _blob_path(sha, logical):
    p = _orig_blob_path(sha, logical)
    if not p.exists():
        t0 = time.time()
        FL.ensure(sha)
        FETCH_WAIT.s = getattr(FETCH_WAIT, "s", 0.0) + (time.time() - t0)
    return p


L.blob_path = _blob_path

import facts_dl as F  # noqa: E402
from esm import llm  # noqa: E402

llm.READ_THROUGH[:] = [S3 / "llm_cache"]
assert 11434 not in llm.PORTS["qwen3.6:27b"]
from esm.envs import datalake as DLE  # noqa: E402


def import_stage3():
    """Copy Stage-3 derivation shards, certificates, truth series and observation tables (read-only sources) once."""
    flag = E2E / ".s3_imported"
    if flag.exists():
        return
    for lake in ("tlc", "bb"):
        src, dst = S3 / f"dl_{lake}", E2E / f"dl_{lake}"
        (dst / "obs").mkdir(parents=True, exist_ok=True)
        for i, p in enumerate(sorted(src.glob("derivations*.jsonl"))):
            shutil.copyfile(p, dst / f"derivations.s3_{i:03d}.jsonl")
        for i, p in enumerate(sorted(src.glob("certs*.jsonl"))):
            shutil.copyfile(p, dst / f"certs.s3_{i:03d}.jsonl")
        for p in (src / "obs").glob("*.pkl"):
            shutil.copyfile(p, dst / "obs" / p.name)
        for n in ("sub_S.json", "sub_ALL.json"):
            shutil.copyfile(src / n, dst / n)
        shutil.copyfile(S3 / f"truth_{lake}_real.json", E2E / f"truth_{lake}_real.json")
    flag.write_text(time.strftime("%Y-%m-%d %H:%M:%S"))


_CTX = {}


def load_context(lake):
    """policies.Context for dl_<lake> on esm_data_e2e_lake (kept facts, real-only lake)."""
    if lake in _CTX:
        return _CTX[lake]
    import_stage3()
    from esm.policies import Context
    ctx = Context.load(f"dl_{lake}")
    _CTX[lake] = ctx
    return ctx


def s3_derivation_keys(lake):
    from esm.maintain import read_shards
    keys = set()
    for p in sorted((S3 / f"dl_{lake}").glob("derivations*.jsonl")):
        for r in read_shards(p):
            keys.add((r["iid"], r["t"]))
    return keys


def jdump(path, obj):
    Path(path).write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
