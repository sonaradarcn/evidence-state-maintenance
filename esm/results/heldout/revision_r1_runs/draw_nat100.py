"""Draw NAT100: 100 facts uniformly at random (without replacement) from the held-out NATURAL subset of kept facts
(subset == 'natural', s0 answer correct; 715 facts), seed fixed BEFORE any outcome of the sample was looked at.
Only fact ids and the 'subset' label are read here (no validity / truth / results).
Writes esm_data_heldout/sub_NAT100.json and draw_nat100.json (seed, population size, population hash)."""
import hashlib, json, os, random, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
os.environ.setdefault("ESM_DATA", str(ROOT / "esm_data_heldout")); os.environ["ESM_LLM_OFFLINE"] = "1"
sys.path.insert(0, str(ROOT))
from esm.envs import heldout as H
from esm.maintain import DerivStore
from esm import llm
from esm.common import DATA
SEED = 20261005
raw = H.load_heldout_raw()
env0 = H.make_env(raw)
kept = H.attach_s0(raw, DerivStore(env0, DATA / "derivations.jsonl", model=llm.Q27), env0)
allk = set(json.loads((DATA / "sub_ALL.json").read_text()))
pop = sorted(f["iid"] for f in kept if f["subset"] == "natural" and f["iid"] in allk)
assert len(pop) == 715, len(pop)
sample = sorted(random.Random(SEED).sample(pop, 100))
out = DATA / "sub_NAT100.json"
assert not out.exists(), "already drawn; never redraw"
out.write_text(json.dumps(sample))
info = {"seed": SEED, "method": "random.Random(seed).sample(sorted(natural kept iids), 100)", "population": len(pop),
        "population_sha256": hashlib.sha256(json.dumps(pop).encode()).hexdigest(), "sample": sample}
(Path(__file__).parent / "draw_nat100.json").write_text(json.dumps(info, indent=1))
print("drawn", len(sample), "from", len(pop))
