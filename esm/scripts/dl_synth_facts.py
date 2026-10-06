"""Zero-LLM: facts affected by the SYNTHETIC events of a lake (for the separately reported synthetic-event analysis).
A fact is affected iff its truth series differs between the real-only and the as-built lake, or a FUTURE synthetic event
touches (puts / removes) a file the fact's oracle depends on (facts_dl.relevant) just before or at that event.
Writes <data>/dlsyn_<lake>/sub_SYN.json and a per-event table <data>/dlsyn_<lake>/synth_events.json.
usage: python -m esm.scripts.dl_synth_facts <lake>"""
import json, sys
from esm.common import DATA
from esm.envs import datalake as DLE

lake = sys.argv[1]
real, _ = DLE.load_facts(lake, "real", DATA)
syn, lk = DLE.load_facts(lake, "synth", DATA)
R = {f["iid"]: f for f in real}
F = DLE.F
fut = lk.future
ev_t = [(t, lk.event_of[s]) for t, s in enumerate(fut, 1) if lk.event_of[s].get("synthetic")]
out, events = set(), []
for t, e in ev_t:
    touched = set(e.get("put", {})) | set(e.get("remove", []))
    w0, w1 = lk.world(lk.s0 if t == 1 else fut[t - 2]), lk.world(fut[t - 1])
    hit = []
    for f in syn:
        g = {"lake": lake, "type": f["type"], "args": f["args"]}
        rel = set(F.relevant(w0, g)) | set(F.relevant(w1, g))
        if rel & touched:
            hit.append(f["iid"])
    events.append({"t": t, "kind": e["kind"], "snap": e["snap"], "files": sorted(touched)[:4], "facts_touched": len(hit),
                   "truth_changed": sum(1 for i in hit if [x for x in syn if x["iid"] == i][0]["truth"][t] !=
                                        [x for x in syn if x["iid"] == i][0]["truth"][t - 1])})
    out |= set(hit)
diff = {f["iid"] for f in syn if f["truth"] != R[f["iid"]]["truth"]}
out |= diff
sub = DATA / f"dlsyn_{lake}"
sub.mkdir(parents=True, exist_ok=True)
(sub / "sub_SYN.json").write_text(json.dumps(sorted(out)))
(sub / "synth_events.json").write_text(json.dumps(events, indent=1))
print(f"{lake}: synthetic FUTURE events {len(ev_t)}; affected facts {len(out)} (series differ real vs synth: {len(diff)})")
for e in events:
    print(" ", e)
