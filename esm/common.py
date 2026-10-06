"""Paths shared by ESM scripts."""
import os
from pathlib import Path

PKG = Path(__file__).resolve().parent
ROOT = PKG.parent
DATA = Path(os.environ.get("ESM_DATA", ROOT / "esm_data"))
# Dev-stage data (observation tables, simulations, subsets); read by the held-out calibration and reports.
DEV_DATA = Path(os.environ.get("ESM_DEV_DATA", ROOT / "esm_data"))
RESULTS = PKG / "results" / os.environ.get("ESM_STAGE", "dev")
for p in (DATA, RESULTS, DATA / "obs", DATA / "logs"):
    p.mkdir(parents=True, exist_ok=True)
