"""Progress snapshot (zero LLM): ledger call rates by model/tag over the last 10 / 60 min, derivation counts, queue states.
usage: python -m esm.scripts.status"""
import json, time, collections
from pathlib import Path
from esm.common import DATA

now = time.time()
c10, c60, tot = collections.Counter(), collections.Counter(), collections.Counter()
ptok = collections.Counter()
led = DATA / "llm_ledger.jsonl"
last = {}
if led.exists():
    for l in open(led, encoding="utf-8", errors="replace"):
        try:
            r = json.loads(l)
        except Exception:
            continue
        k = (r["model"].split(":", 1)[1], r["tag"])
        tot[k] += 1
        ptok[r["model"]] += r["prompt"] + r["completion"]
        last[r["model"]] = r["t"]
        if now - r["t"] < 600:
            c10[k] += 1
        if now - r["t"] < 3600:
            c60[k] += 1
print(time.strftime("%Y-%m-%d %H:%M:%S"))
for m in sorted({k[0] for k in tot}):
    a10 = sum(v for k, v in c10.items() if k[0] == m)
    a60 = sum(v for k, v in c60.items() if k[0] == m)
    print(f"{m}: last10min {a10 / 10:.1f}/min  last60min {a60 / 60:.1f}/min  total {sum(v for k, v in tot.items() if k[0] == m)} calls "
          f"{ptok['ollama:' + m] / 1e6:.2f}M tok  idle {now - last.get('ollama:' + m, now):.0f}s")
print("last 60 min by tag:", dict(c60.most_common(12)))
from esm.maintain import read_shards
for p in [DATA / "derivations.jsonl", DATA / "derivations_9b.jsonl", DATA / "dev27" / "derivations.jsonl", DATA / "certs.jsonl"]:
    n = len(read_shards(p))
    if n:
        print(f"{p.relative_to(DATA)} (+shards): {n}")
for q in sorted(DATA.glob("queue_*.txt")):
    jobs = [l for l in q.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    d = q.with_suffix(".done")
    nd = len(d.read_text(encoding="utf-8").splitlines()) if d.exists() else 0
    print(f"{q.name}: {nd}/{len(jobs)} done; running: {jobs[nd][:150] if nd < len(jobs) else '-'}")
sim = DATA / "sim"
if sim.exists():
    print("sim:", sorted(p.stem for p in sim.glob("*.parquet")))
