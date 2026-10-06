"""Turn the catalogue into an ordered event list = snapshot sequence per lake (manifests over the CAS store).

Output: datalake_data/snapshots/<lake>.json  {events:[...], rows:{sha:n}, s0_index, history_start_index, ...}
and a copy of the event list (without the big 'put' maps) in datalake/manifests/<lake>_events.json.

Every event yields one snapshot.  Event kinds:
  bootstrap    initial docs / lookup present before the first data file              (real content)
  arrive       one monthly TLC file / one month of Backblaze daily CSVs arrives     (real content)
  doc          a new real version of a documentation file (Wayback / Last-Modified) (real content)
  lookup       new real version of the taxi zone lookup                             (real content)
  correct      SYNTHETIC: a previously published preliminary file is replaced by the full file
               (the preliminary version = real file minus ~3 % deterministically chosen "late-arriving" rows)
  repartition  SYNTHETIC: a monthly file is replaced by two part files with identical rows
  rename_dir   SYNTHETIC: a directory is renamed (paths change, contents identical)
  late_day     SYNTHETIC: a Backblaze daily file withheld from its month's batch arrives later
"""
import datetime as dt, hashlib, io, json, re
from pathlib import Path
import pyarrow as pa, pyarrow.parquet as pq

from ingest import CAT, STORE, ROOT, put

HERE = Path(__file__).parent
N_HIST = 60
S0_FRAC = 0.40

TLC_DS_ORDER = {"yellow": 0, "green": 1, "fhv": 2, "fhvhv": 3}
# SYNTHETIC events (documented in MANIFEST.md).  (dataset, month) -> correction time
TLC_CORRECTIONS = {("yellow", "2021-03"): "2021-09-01", ("green", "2021-11"): "2022-08-20",
                   ("yellow", "2022-01"): "2022-11-10", ("fhvhv", "2021-06"): "2023-05-05",
                   ("fhv", "2020-12"): "2024-06-12", ("yellow", "2020-05"): "2025-07-01"}
TLC_REPARTITIONS = {("fhvhv", "2020-09"): "2023-09-01", ("yellow", "2024-06"): "2025-10-01"}
TLC_RENAME = ("misc/", "reference/", "2024-09-01")
BB_CORRECTIONS = {"2014-06-10": "2015-01-15", "2017-03-14": "2019-05-15", "2016-08-02": "2021-02-15",
                  "2018-02-07": "2024-04-15"}
BB_LATE_DAYS = {"2017-11-20": "2020-03-15"}


def blob(sha, ext):
    return STORE / sha[:2] / f"{sha}{ext}"


def drop_late_rows(key, n):
    """Deterministic ~3 % of row indices treated as 'late-arriving' (absent from the preliminary file)."""
    return {i for i in range(n) if int(hashlib.md5(f"{key}:{i}".encode()).hexdigest()[:8], 16) % 32 == 0}


def prelim_parquet(sha, key):
    t = pq.read_table(blob(sha, ".parquet"))
    pf = pq.ParquetFile(blob(sha, ".parquet"))
    codec = pf.metadata.row_group(0).column(0).compression.lower() if pf.metadata.num_row_groups else "snappy"
    drop = drop_late_rows(key, t.num_rows)
    keep = [i for i in range(t.num_rows) if i not in drop]
    t2 = t.take(pa.array(keep, pa.int64()))
    buf = io.BytesIO()
    pq.write_table(t2, buf, compression=codec)
    s, _ = put(buf.getvalue(), ".parquet")
    return s, t2.num_rows


def split_parquet(sha):
    t = pq.read_table(blob(sha, ".parquet"))
    pf = pq.ParquetFile(blob(sha, ".parquet"))
    codec = pf.metadata.row_group(0).column(0).compression.lower() if pf.metadata.num_row_groups else "snappy"
    h = t.num_rows // 2
    out = []
    for part in (t.slice(0, h), t.slice(h)):
        buf = io.BytesIO()
        pq.write_table(part, buf, compression=codec)
        out.append((put(buf.getvalue(), ".parquet")[0], part.num_rows))
    return out


def prelim_csv(sha, key):
    raw = blob(sha, ".csv").read_bytes().decode("utf-8")
    nl = "\r\n" if "\r\n" in raw[:5000] else ("\n" if "\n" in raw[:5000] else "\r")
    lines = [l for l in raw.split(nl) if l]
    drop = drop_late_rows(key, len(lines) - 1)
    keep = [lines[0]] + [l for i, l in enumerate(lines[1:]) if i not in drop]
    s, _ = put((nl.join(keep) + nl).encode("utf-8"), ".csv")
    return s, len(keep) - 1


def docs_for(lake):
    p = CAT / "docs" / "docs.json"
    if not p.exists():
        print("WARNING: docs.json missing -- building without documentation versions")
        return []
    d = json.loads(p.read_text())
    return [r for r in d if r["lake"] == lake]


def iso(s):
    return s if "T" in s else s + "T00:00:00Z"


def finalize(lake, events, rows, extra):
    events.sort(key=lambda e: (e["time"], e.get("order", 0)))
    for i, e in enumerate(events):
        e["idx"] = i
        e["snap"] = f"{lake}-{i:04d}"
        e.pop("order", None)
    n = len(events)
    s0 = round(S0_FRAC * n)
    h0 = s0 - N_HIST
    assert h0 >= 0 and n - s0 - 1 >= 80, (n, s0)
    out = {"lake": lake, "n_snapshots": n, "s0_index": s0, "history_start_index": h0,
           "n_history": N_HIST, "n_future": n - s0 - 1, "s0_snap": events[s0]["snap"], "s0_time": events[s0]["time"],
           "events": events, "rows": rows, **extra}
    (ROOT / "snapshots").mkdir(exist_ok=True)
    (ROOT / "snapshots" / f"{lake}.json").write_text(json.dumps(out))
    (HERE / "manifests").mkdir(exist_ok=True)
    slim = [{k: v for k, v in e.items() if k != "put"} | {"put_paths": sorted(e.get("put", {}))[:5] +
             ([f"... (+{len(e.get('put', {})) - 5})"] if len(e.get("put", {})) > 5 else [])} for e in events]
    (HERE / "manifests" / f"{lake}_events.json").write_text(json.dumps(
        {k: v for k, v in out.items() if k not in ("events", "rows")} | {"events": slim}, indent=0))
    print(lake, "snapshots", n, "s0", s0, events[s0]["time"], "history from", h0, events[h0]["time"], "future", n - s0 - 1,
          "synthetic events", sum(1 for e in events if e.get("synthetic")))


# ------------------------------------------------------------------ TLC
def build_tlc():
    rows, events = {}, []
    recs = []
    for f in sorted((CAT / "tlc").glob("*.json")):
        r = json.loads(f.read_text())
        if r.get("available"):
            recs.append(r)
            rows[r["sha256"]] = r["n_rows_sub"]
    unavailable = sorted(json.loads(f.read_text())["name"] for f in (CAT / "tlc").glob("*.json")
                         if not json.loads(f.read_text()).get("available"))
    start = "2019-03-15T00:00:00Z"
    boot = {"time": "2019-03-01T00:00:00Z", "kind": "bootstrap", "synthetic": False, "put": {},
            "note": "per doc/lookup path: latest version available before the lake start, else the earliest available version"}
    vers = {}
    for d in docs_for("tlc"):
        vers.setdefault(d["logical_path"], []).append(d)
    for p, vs in vers.items():
        vs.sort(key=lambda d: iso(d["arrival"]))
        before = [d for d in vs if iso(d["arrival"]) <= start]
        first = before[-1] if before else vs[0]
        boot["put"][p] = first["sha256"]
        for d in vs[vs.index(first) + 1:]:
            kind = "lookup" if "lookup" in p else "doc"
            events.append({"time": iso(d["arrival"]), "kind": kind, "synthetic": False, "put": {p: d["sha256"]},
                           "note": d["source"]})
    events.append(boot)
    for r in recs:
        m = re.match(r"(\w+?)_tripdata_(\d{4})-(\d{2})\.parquet", r["name"])
        ds, y, mo = m.group(1), int(m.group(2)), int(m.group(3))
        ym = f"{y:04d}-{mo:02d}"
        ry, rm = (y, mo + 2) if mo <= 10 else (y + 1, mo - 10)
        t = f"{ry:04d}-{rm:02d}-15T12:{TLC_DS_ORDER[ds]:02d}:00Z"
        path = r["logical_path"]
        ev = {"time": t, "kind": "arrive", "synthetic": False, "put": {path: r["sha256"]}, "dataset": ds, "month": ym,
              "note": f"nominal release (month+2, 15th); origin Last-Modified {r['http']['last_modified']}"}
        if (ds, ym) in TLC_CORRECTIONS:
            ps, pn = prelim_parquet(r["sha256"], r["name"])
            rows[ps] = pn
            ev["put"] = {path: ps}
            ev["synthetic"] = True
            ev["note"] = f"SYNTHETIC preliminary version: {r['n_rows_sub'] - pn} of {r['n_rows_sub']} rows held back as late-arriving"
            events.append({"time": TLC_CORRECTIONS[(ds, ym)] + "T09:00:00Z", "kind": "correct", "synthetic": True,
                           "put": {path: r["sha256"]}, "dataset": ds, "month": ym,
                           "note": "SYNTHETIC late-arriving correction: full file republished"})
        events.append(ev)
        if (ds, ym) in TLC_REPARTITIONS:
            parts = split_parquet(r["sha256"])
            put_ = {}
            for i, (s, n) in enumerate(parts):
                put_[f"trip-data/{ds}_tripdata_{ym}/part-{i:04d}.parquet"] = s
                rows[s] = n
            events.append({"time": TLC_REPARTITIONS[(ds, ym)] + "T09:00:00Z", "kind": "repartition", "synthetic": True,
                           "put": put_, "remove": [path], "dataset": ds, "month": ym,
                           "note": "SYNTHETIC re-partition into two part files (identical rows)"})
    # synthetic directory rename: needs the manifest at that time -> computed after sorting
    events.sort(key=lambda e: e["time"])
    old, new, when = TLC_RENAME
    cur = {}
    t_ren = when + "T09:00:00Z"
    for e in events:
        if e["time"] > t_ren:
            break
        for p in e.get("remove", []):
            cur.pop(p, None)
        cur.update(e.get("put", {}))
    moved = {p: s for p, s in cur.items() if p.startswith(old)}
    events.append({"time": t_ren, "kind": "rename_dir", "synthetic": True,
                   "put": {new + p[len(old):]: s for p, s in moved.items()}, "remove": sorted(moved),
                   "note": f"SYNTHETIC directory rename {old} -> {new}"})
    for e in events:   # later lookup versions must follow the rename
        if e["time"] > t_ren:
            e["put"] = {(new + p[len(old):] if p.startswith(old) else p): s for p, s in e.get("put", {}).items()}
    finalize("tlc", events, rows, {"unavailable_files": unavailable, "subsample_rate": "1/64 rows (md5 of row text)"})


# ------------------------------------------------------------------ Backblaze
def build_bb():
    rows, events, days = {}, [], {}
    fixed = {}
    for f in sorted((CAT / "bb").glob("*.json")):
        r = json.loads(f.read_text())
        if not r.get("available"):
            continue
        for m in r["members"]:
            if not m["logical_path"].endswith(".csv"):
                continue
            day = Path(m["logical_path"]).stem
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                continue
            days[day] = m
            rows[m["sha256"]] = m["n_rows_sub"]
    boot = {"time": "2013-04-01T00:00:00Z", "kind": "bootstrap", "synthetic": False, "put": {}, "note": "empty lake (docs arrive later)"}
    events.append(boot)
    for d in docs_for("bb"):
        events.append({"time": iso(d["arrival"]), "kind": "doc", "synthetic": False,
                       "put": {d["logical_path"]: d["sha256"]}, "note": d["source"]})
    by_month = {}
    for day, m in days.items():
        by_month.setdefault(day[:7], {})[day] = m
    for ym, dd in sorted(by_month.items()):
        y, mo = int(ym[:4]), int(ym[5:])
        ny, nm = (y, mo + 1) if mo < 12 else (y + 1, 1)
        put_ = {}
        for day, m in sorted(dd.items()):
            if day in BB_LATE_DAYS:
                events.append({"time": BB_LATE_DAYS[day] + "T06:00:00Z", "kind": "late_day", "synthetic": True,
                               "put": {m["logical_path"]: m["sha256"]}, "month": ym,
                               "note": f"SYNTHETIC: daily file {day} withheld from its month batch, arrives late"})
                continue
            if day in BB_CORRECTIONS:
                ps, pn = prelim_csv(m["sha256"], day)
                rows[ps] = pn
                put_[m["logical_path"]] = ps
                events.append({"time": BB_CORRECTIONS[day] + "T06:00:00Z", "kind": "correct", "synthetic": True,
                               "put": {m["logical_path"]: m["sha256"]}, "month": ym,
                               "note": f"SYNTHETIC late-arriving correction of {day}: full file republished "
                                       f"({m['n_rows_sub'] - pn} rows were missing from the preliminary file)"})
                continue
            put_[m["logical_path"]] = m["sha256"]
        events.append({"time": f"{ny:04d}-{nm:02d}-01T00:00:00Z", "kind": "arrive", "synthetic": False, "put": put_,
                       "month": ym, "order": 1,
                       "note": f"{len(put_)} daily files of {ym} (real cadence: quarterly zip; monthly batches here)"
                               + ("; contains SYNTHETIC preliminary file(s)" if any(d in BB_CORRECTIONS for d in dd) else "")})
        if any(d in BB_CORRECTIONS for d in dd):
            events[-1]["synthetic_part"] = True
    finalize("bb", events, rows, {"subsample_rate": "1/64 of drives (md5 of serial_number)"})


if __name__ == "__main__":
    import sys
    for k in (sys.argv[1:] or ["tlc", "bb"]):
        {"tlc": build_tlc, "bb": build_bb}[k]()
