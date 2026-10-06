"""Stage 4 prep (zero LLM, zero GPU): extract everything the task-stream simulation needs from the held-out stage.

Writes esm/results/stream/cache/facts.pkl with, per kept held-out fact:
  repo, slice, type, subset, in_H150, derive_tokens (s0), cert setup tokens,
  truth hashes over t = 0..400 (t = 0 is s0), and for every RECORDED 27B re-derivation (t > 0) of that fact:
  tokens, correct-at-t, and its validity vector against the oracle at every FUTURE commit (canonicalised comparison,
  the same `answer_matches` the held-out stage used).
Also writes cache/commit_times.parquet: committer timestamps of s0 + the 400 FUTURE first-parent commits per repo
(read-only `git show` on the held-out clones).

usage: python -m esm.stream.prep
"""
import json, os, pickle, subprocess, sys
from pathlib import Path

os.environ["ESM_LLM_OFFLINE"] = "1"
os.environ.setdefault("ESM_DATA", str(Path(__file__).resolve().parents[2] / "esm_data_heldout"))
os.environ["ESM_STAGE"] = "stream"
import pandas as pd
from esm import llm
from esm.common import DATA, RESULTS
from esm.maintain import DerivStore, read_shards
from esm.envs import heldout as H
from esm.certs import CertStore

CACHE = RESULTS / "cache"
CACHE.mkdir(parents=True, exist_ok=True)


def commit_times():
    rows = []
    for repo in H.REPOS:
        d = json.loads((H.ROOT / "heldout" / f"facts_{repo}.json").read_text(encoding="utf-8"))
        hs = d["commits"][300:701]          # s0 + 400 FUTURE
        out = subprocess.run(["git", "-C", str(H.HD / "repos" / repo), "show", "-s", "--format=%H %ct %at"] + hs,
                             capture_output=True, text=True, check=True).stdout.split()
        got = {out[i]: (int(out[i + 1]), int(out[i + 2])) for i in range(0, len(out), 3)}
        for t, h in enumerate(hs):
            rows.append({"repo": repo, "t": t, "commit": h, "ct": got[h][0], "at": got[h][1]})
    df = pd.DataFrame(rows)
    df.to_parquet(CACHE / "commit_times.parquet", index=False)
    print("commit times", df.shape)


def facts():
    raw = H.load_heldout_raw()
    env0 = H.make_env(raw)
    d0 = DerivStore(env0, DATA / "derivations.jsonl", model=llm.Q27)
    kept = H.attach_s0(raw, d0, env0)
    CertStore(DATA / "certs.jsonl").attach(kept)
    h150 = set(json.loads((DATA / "sub_H150.json").read_text()))
    ders = {}
    for r in read_shards(DATA / "derivations.jsonl"):
        ders.setdefault((r["iid"], r["t"]), r)
    byf = {}
    for (iid, t), r in ders.items():
        if t > 0:
            byf.setdefault(iid, []).append(r)
    out = {}
    for f in kept:
        truth = f["truth"][300:701]             # index 0 = s0, 1..400 FUTURE
        uniq = {}
        dl = []
        for r in sorted(byf.get(f["iid"], []), key=lambda r: r["t"]):
            a = r["answer"]
            vv = []
            for u in range(1, 401):
                v = truth[u]
                k = (a, v)
                if k not in uniq:
                    uniq[k] = bool(a is not None and env0.answer_matches(f, a, v))
                vv.append(uniq[k])
            dl.append({"t": r["t"], "tok": int(sum(r["tokens"])), "correct": bool(r["correct"]),
                       "none_answer": a is None, "valid": vv})
        ct = f.get("cert_tokens") or {}
        out[f["iid"]] = {"repo": f["repo"], "slice": f["slice"], "type": f["type"], "subset": f["subset"],
                         "H150": f["iid"] in h150, "dtok0": int(sum(f["derive_tokens"])),
                         "setup_certzs": int(ct.get("certzs") or 0), "setup_certv0": int(ct.get("certv0h") or 0),
                         "truth": (lambda m: [m.setdefault(x, len(m)) for x in truth])({}),   # per-fact value codes
                         "valid0": list(f["valid"]), "ders": dl}
    with open(CACHE / "facts.pkl", "wb") as fh:
        pickle.dump(out, fh)
    print("facts", len(out), "H150", sum(v["H150"] for v in out.values()),
          "ders", sum(len(v["ders"]) for v in out.values()))


if __name__ == "__main__":
    commit_times()
    facts()
