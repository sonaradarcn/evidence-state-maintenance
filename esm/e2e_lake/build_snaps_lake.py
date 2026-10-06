"""Re-create the snapshot manifests (datalake/build_snapshots.py, unchanged event logic) from the archived catalogue into
esm_data_e2e_lake/lake_data/snapshots.  The SYNTHETIC preliminary / re-partition blobs are not re-created (placeholder
shas): the headline real-only variant (esm/envs/datalake.VariantLake 'real') replaces every one of them by the final real
file or a no-op, so they are never visible.  The rebuilt event lists are compared with datalake/manifests/<lake>_events.json.
usage: python -m esm.e2e_lake.build_snaps_lake"""
import hashlib, json, sys
from esm.e2e_lake import fetch_lake as FL
sys.path.insert(0, str(FL.ROOT / "datalake"))
import build_snapshots as BS  # noqa: E402

BS.CAT, BS.ROOT, BS.HERE = FL.CAT_SRC, FL.LD, FL.LD
BS.STORE = FL.STORE


def _ph(kind, sha, key):
    return "synthetic-" + hashlib.sha256(f"{kind}:{sha}:{key}".encode()).hexdigest()[10:]


BS.prelim_parquet = lambda sha, key: (_ph("prelim", sha, key), -1)
BS.prelim_csv = lambda sha, key: (_ph("prelimcsv", sha, key), -1)
BS.split_parquet = lambda sha: [(_ph("part0", sha, ""), -1), (_ph("part1", sha, ""), -1)]
for lake in ("tlc", "bb"):
    {"tlc": BS.build_tlc, "bb": BS.build_bb}[lake]()
    new = json.loads((FL.LD / "manifests" / f"{lake}_events.json").read_text())
    old = json.loads((FL.ROOT / "datalake" / "manifests" / f"{lake}_events.json").read_text())
    keys = ("snap", "time", "kind", "synthetic")
    same = [all(a.get(k) == b.get(k) for k in keys) and a.get("put_paths") == b.get("put_paths")
            for a, b in zip(new["events"], old["events"])]
    print(lake, "events", len(new["events"]), len(old["events"]), "identical (snap/time/kind/synthetic/put paths):",
          sum(same), "s0", new["s0_index"], old["s0_index"], "h0", new["history_start_index"], old["history_start_index"])
    assert len(new["events"]) == len(old["events"]) and all(same)
