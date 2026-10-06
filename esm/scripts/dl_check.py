"""Zero-LLM sanity checks of the data-lake environment: real-variant truth series, synth-variant oracle reproduction,
anchored observations.  usage: python -m esm.scripts.dl_check <lake>"""
import sys, time, json, random
from esm.common import DATA
from esm.envs import datalake as DLE
lake = sys.argv[1]
t0 = time.time()
real, lkr = DLE.load_facts(lake, "real", DATA)
print("real truth", len(real), f"{time.time()-t0:.0f}s", flush=True)
syn, lks = DLE.load_facts(lake, "synth", DATA)
# 1) recompute 12 synth series with facts_dl.oracle on VariantLake('synth') and compare with the stored table
rng = random.Random(1)
P = DLE.F.Profiles(lake); P.save = lambda: None
ws = [lks.world(s) for s in [lks.s0] + lks.future]
bad = 0
for f in rng.sample(syn, 12):
    ser = DLE.F.series(lks, {"lake": lake, "type": f["type"], "args": f["args"]}, P, ws, {})
    bad += ser != f["truth"]
print("synth recomputation mismatches:", bad, "/ 12", flush=True)
# 2) real vs synth differences
S = {f["iid"]: f for f in syn}
nd = sum(f["truth"] != S[f["iid"]]["truth"] for f in real)
nk = sum(f["truth"][0] != S[f["iid"]]["truth"][0] for f in real)
chg_r = sum(any(not v for v in f["valid0"]) for f in real); chg_s = sum(any(not v for v in f["valid0"]) for f in syn)
print(f"facts whose series differ real vs synth: {nd}; s0 value differs: {nk}; changing facts real {chg_r} synth {chg_s}")
for f in real:
    if f["truth"][0] != S[f["iid"]]["truth"][0]:
        print("  s0 differs", f["iid"], f["args"], S[f["iid"]]["truth"][0], "->", f["truth"][0])
