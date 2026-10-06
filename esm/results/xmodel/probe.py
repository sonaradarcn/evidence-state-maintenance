"""Cross-model stage, model probe: does the candidate model work with ESM's tool loop and JSON verdicts?

On N facts of X120 (seeded pick, incl. behaviour facts): s0 derivation with the pilot3/pilot6 tool loop (+ NONE
instruction), then for every correct derivation one transition judgement (first anchored evidence state that differs
from s0, the frozen ESM judge prompt, hierarchical deltas) and one CERT-ZS extraction.  Reports tool-loop health
(answered / correct / tool calls / server parse errors / prose answers) and JSON health (verdict parse failures).
usage (env: ESM_MAIN_MODEL, ESM_REASONING, ESM_PORTS_Q27, ESM_DATA=<probe dir>):
    python esm/results/xmodel/probe.py --n 10 --workers 4
"""
import argparse, collections, json, random, sys, time
from pathlib import Path
import concurrent.futures as cf

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
ap = argparse.ArgumentParser()
ap.add_argument("--n", type=int, default=10)
ap.add_argument("--workers", type=int, default=4)
a = ap.parse_args()
from esm import llm, evidence as E, judge as J
from esm.common import DATA
from esm.envs import heldout as H
from esm.maintain import DerivStore
from esm.certs import cert_zs

ids = json.loads((ROOT / "esm_data_xmodel" / "sub_X120.json").read_text())
rng = random.Random(7)
raw = H.load_heldout_raw()
F = {f["iid"]: f for f in raw}
beh = [i for i in ids if F[i]["slice"] == "behav"]
sta = [i for i in ids if F[i]["slice"] != "behav"]
rng.shuffle(beh); rng.shuffle(sta)
pick = beh[:2] + sta[:a.n - 2]
facts = [F[i] for i in pick]
env = H.make_env(raw)
ders = DerivStore(env, DATA / "derivations.jsonl", model=llm.Q27)
t0 = time.time()
with cf.ThreadPoolExecutor(a.workers) as ex:
    dres = list(ex.map(lambda f: ders.get(f, 0), facts))
el = time.time() - t0
print(f"model={llm.Q27} reasoning={llm.REASONING} derivations={len(dres)} in {el:.0f}s")
for f, r in zip(facts, dres):
    print(f"  {f['iid'][:48]:48s} {f['type']:3s} calls={len(r['trace']):2d} llm={r['n_llm']:2d} tok={sum(r['tokens']):6d} "
          f"correct={r['correct']} answer={str(r['answer'])[:50]!r} oracle={F[f['iid']]['truth'][300][:40]!r}")
kept = H.attach_s0(raw, ders, env)
kept = [g for g in kept if g["iid"] in set(pick)]
env2 = H.make_env(kept, repos=env._repos)
tab = E.ObsTable(env2)
for p in sorted((DATA / "obs").glob("*.pkl")):
    tab.load(p)
verd = collections.Counter()
jt = []
for f in kept:
    ev = E.record(env2, f, f["trace"], 0, "anchored", f["cite"], f["K"], "a0", origin="s0")
    r0 = tab.ref_state(ev)
    tt = next((t for t in range(1, 401) if tab.state(f, ev, t)[0] != r0), None)
    if tt is None:
        print(f"  {f['iid'][:48]:48s} no anchored state change in FUTURE")
        continue
    t1 = time.time()
    res = J.evaluate(env2, f, ev, tab.outputs(f, ev, tt), mode="hier", model=llm.Q27, tag="probe_judge")
    verd[res["verdict"]] += 1
    jt.append(time.time() - t1)
    print(f"  judge {f['iid'][:40]:40s} t={tt:3d} verdict={res['verdict']:11s} new={str(res['new_answer'])[:30]!r} "
          f"truth_changed={not env2.answer_matches(f, f['K'], env2.truth(f, tt))} calls={res['n_calls']} tok={res['tokens']} "
          f"reason={(res['reason'] or '')[:80]!r}")
cz = collections.Counter()
for f in kept[:4]:
    c = cert_zs(env2, f)
    cz["ok" if c["calls"] else "empty"] += 1
print(f"s0: answered {sum(r['answer'] is not None for r in dres)}/{len(dres)}; correct (kept) {len(kept)}/{len(facts)}")
print("judge verdicts:", dict(verd), "mean secs/judgement", round(sum(jt) / max(len(jt), 1), 1))
print("CERT-ZS extraction:", dict(cz))
print("llm stats", llm.STATS)
