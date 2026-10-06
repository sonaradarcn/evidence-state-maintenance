"""Smoke test: every tool on 3 snapshots per lake, sql budget enforcement, and 30 random stored oracle values per lake
recomputed with ONE independent DuckDB full-scan statement (facts_dl.oracle_direct) and compared with the oracle table.

    python smoke_test.py            # both lakes
    python smoke_test.py tlc
Writes datalake/smoke_test_report_<lakes>.txt; exit code 1 on any mismatch or tool error.
"""
import json, random, sys, time
from pathlib import Path
import pandas as pd

import lake as L
import facts_dl as F

HERE = Path(__file__).parent


def tool_calls(lk, w):
    if lk.name == "tlc":
        idx = F.tlc_index(w)
        ys = F.latest_paths(idx, "yellow")[0]
        months = [m for m, _ in F.period_parts(idx, "yellow", "all")]
        ya = idx["parts"][("yellow", months[0])][0]
        doc = next(p for p in sorted(w.paths()) if p.endswith(".txt"))
        lookup = idx["lookup"]
        return [("ls", {"path": "."}), ("ls", {"path": "trip-data"}), ("find", {"glob": "fhvhv_*"}),
                ("file_schema", {"file": ys}), ("head", {"file": ys, "n": 3}), ("file_rowcount", {"file": ys}),
                ("file_stats", {"file": ys, "column": "fare_amount"}), ("file_stats", {"file": lookup, "column": "LocationID"}),
                ("sql", {"query": f"SELECT PULocationID, count(*) n FROM '{ys}' GROUP BY 1 ORDER BY n DESC LIMIT 3"}),
                ("sql", {"query": "SELECT count(*) FROM read_parquet('trip-data/yellow_tripdata_*.parquet')"}),   # must hit the budget
                ("sql", {"query": f"COPY (SELECT 1) TO 'x.csv'"}),                                                  # must be refused
                ("read_text", {"file": doc, "start": 1, "end": 15}), ("read_text", {"file": lookup, "start": 260, "end": 266}),
                ("grep", {"pattern": "(?i)airport", "path": "."}), ("schema_diff", {"file_a": ya, "file_b": ys})]
    days = F.bb_index(w)["days"]
    ks = sorted(days)
    last, first = days[ks[-1]], days[ks[0]]
    docs = [p for p in sorted(w.paths()) if p.endswith(".txt")]
    calls = [("ls", {"path": "."}), ("ls", {"path": "drive_stats"}), ("find", {"glob": f"{ks[-1][:7]}-*.csv"}),
             ("file_schema", {"file": last}), ("head", {"file": last, "n": 2}), ("file_rowcount", {"file": last}),
             ("file_stats", {"file": last, "column": "capacity_bytes"}),
             ("sql", {"query": f"SELECT model, count(*) n FROM '{last}' GROUP BY 1 ORDER BY n DESC LIMIT 3"}),
             ("sql", {"query": "SELECT count(*) FROM read_csv('drive_stats/*/*.csv')"}),                         # must hit the budget
             ("schema_diff", {"file_a": first, "file_b": last}), ("grep", {"pattern": r"(?i)s.?m.?a.?r.?t", "path": "."})]
    if docs:
        calls.append(("read_text", {"file": docs[0], "start": 1, "end": 10}))
    return calls


EXPECT_ERROR = {"budget", "COPY"}


def main(lakes):
    L.duck().execute("SET threads=48")
    rep, bad = [], 0
    for name in lakes:
        lk = L.Lake(name)
        snaps = [lk.history[0], lk.s0, lk.future[-1]]
        rep.append(f"=== lake {name}: {len(lk.commits)} window snapshots (HISTORY {len(lk.history)}, FUTURE {len(lk.future)}), s0={lk.s0}")
        for s in snaps:
            w = lk.world(s)
            rep.append(f"--- snapshot {s} ({lk.event_of[s]['time']}, {lk.event_of[s]['kind']}): {len(w.tree)} files")
            for tname, args in tool_calls(lk, w):
                t0 = time.time()
                out = L.run_tool(w, tname, args)
                dt = time.time() - t0
                expect_err = ("read_parquet('trip-data/yellow_tripdata_*" in str(args) or "drive_stats/*/*.csv" in str(args)
                              or "COPY" in str(args))
                is_err = out.startswith("error")
                ok = is_err == expect_err and len(out) <= L.MAX_OUT + 60
                bad += not ok
                touched = sorted(L.files_touched(tname, args, out, w))[:3]
                rep.append(f"[{'ok' if ok else 'FAIL'}] {tname}({json.dumps(args)[:110]}) {dt * 1000:.0f}ms {len(out)}ch touched={touched}")
                rep.append("    " + out[:300].replace("\n", "\n    "))
        # ---- oracle recomputation
        facts = {f["id"]: f for f in json.loads((HERE / f"facts_{name}.json").read_text())["facts"]}
        tab = pd.read_parquet(HERE / "oracle" / f"oracle_{name}.parquet")
        rng = random.Random(1)
        sample = tab.sample(n=30, random_state=rng.randint(0, 10 ** 6))
        rep.append(f"--- 30 random oracle values recomputed by a single DuckDB full-scan statement (lake {name})")
        for _, r in sample.iterrows():
            f = facts[r["fact_id"]]
            w = lk.world(r["snapshot"])
            t0 = time.time()
            v = F.oracle_direct(w, f)
            ok = v == r["value"]
            bad += not ok
            print(f"[{'ok' if ok else 'MISMATCH'}] {f['id']} {time.time() - t0:.1f}s", flush=True)
            rep.append(f"[{'ok' if ok else 'MISMATCH'}] {f['id']} {f['type']} {json.dumps(f['args'])[:90]} @ {r['snapshot']} "
                       f"stored={r['value']!r} direct={v!r} ({time.time() - t0:.1f}s)")
    rep.append(f"TOTAL FAILURES: {bad}")
    (HERE / f"smoke_test_report_{'_'.join(lakes)}.txt").write_text("\n".join(rep), encoding="utf-8")
    print("\n".join(l for l in rep if not l.startswith("    ")))
    return bad


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1:] or ["tlc", "bb"]) else 0)
