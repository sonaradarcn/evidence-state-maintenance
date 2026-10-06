"""Zero-LLM: evidence-state fingerprint of every kept fact's s0 anchored evidence at every FUTURE commit (the reference
state of the detection-only runs), from the cached observation tables.  -> cache/states_s0.pkl {iid: [state at t=0..400]}"""
import pickle, time
from r1_common import *
from esm.policies import Context
from esm import evidence as E

ctx = Context.load("heldout")
env, tab = ctx.env, ctx.tab
out = {}
t0 = time.time()
for k, f in enumerate(ctx.facts):
    ev = E.record(env, f, f["trace"], 0, "anchored", f["cite"], f["K"], "a0", origin="s0")
    out[f["iid"]] = [tab.ref_state(ev)] + [tab.state(f, ev, t)[0] for t in range(1, 401)]
    if k % 200 == 0:
        print(k, round(time.time() - t0), flush=True)
(CACHE / "states_s0.pkl").write_bytes(pickle.dumps(out))
print("done", len(out))
