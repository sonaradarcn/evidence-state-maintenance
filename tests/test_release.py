"""Smoke tests that need no GPU, network or rebuilt data: the package imports, and the shipped records reproduce
the headline held-out numbers (python -m pytest tests, or python tests/test_release.py)."""
import importlib, json, os, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ESM_DATA", tempfile.mkdtemp(prefix="esm_test_"))
os.environ["ESM_LLM_OFFLINE"] = "1"


def test_imports():
    for m in ("esm.env", "esm.tools", "esm.evidence", "esm.delta", "esm.judge", "esm.maintain", "esm.baselines",
              "esm.policies", "esm.metrics", "esm.envs.pyrepo", "esm.envs.heldout"):
        importlib.import_module(m)


def test_heldout_headline():
    import pandas as pd
    d = pd.read_parquet(ROOT / "esm/results/heldout/records.parquet", columns=["policy", "iid", "schedule", "served_valid"])
    every = d[d.schedule == "every"]
    wrong = {p: 100 * (1 - every[every.policy == p].served_valid.mean()) for p in ("ESM-norepair", "NEVER")}
    assert every[every.policy == "ESM-norepair"].iid.nunique() == 1419
    assert round(wrong["ESM-norepair"], 1) == 5.8 and round(wrong["NEVER"], 1) == 21.5


def test_benchmark_files():
    n = sum(len(json.loads(p.read_text(encoding="utf-8"))["facts"]) for p in (ROOT / "heldout").glob("facts_*.json")
            if not p.name.endswith(".static.json"))
    assert n == 1478


if __name__ == "__main__":
    for f in (test_imports, test_heldout_headline, test_benchmark_files):
        f(); print("ok", f.__name__)
