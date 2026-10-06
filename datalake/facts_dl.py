"""Fact types D1..D8, programmatic oracles (DuckDB full scans), question templates, canonicalisers, sampling.

Oracle evaluation = (1) for every file VERSION (sha) the fact depends on, a DuckDB full scan computes an exact
per-file profile (cached by sha); (2) the profiles of all files the fact depends on in the snapshot are combined.
All combined quantities are decomposable (counts, exact DECIMAL sums, group counts, set unions), so the result equals
a single full scan over the snapshot -- `oracle_direct()` re-derives values with ONE DuckDB SQL statement over the
snapshot's files and is used by the smoke test to cross-check.

Run:  python facts_dl.py tlc|bb    -> facts_<lake>.json, oracle_<lake>.parquet, pool stats
"""
import csv, io, json, pickle, random, re, sys, time
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path

import lake as L

NONE = "NONE"
HERE = Path(__file__).parent
CACHE = L.DATA / "cache"
CACHE.mkdir(exist_ok=True)

# ------------------------------------------------------------------ hand-written concept mapping (D2)
# Derived from the official TLC data dictionaries (docs/data_dictionary_trip_records_*.txt in the lake) and, for
# Backblaze, from the Drive Stats documentation page + the SMART attribute numbering it uses.  Matching against file
# column names is case-insensitive; the oracle returns the exact column name present in the file.
TLC_CONCEPTS = {
    "pickup_time": ("pickup date and time", ["tpep_pickup_datetime", "lpep_pickup_datetime", "pickup_datetime"]),
    "dropoff_time": ("drop-off date and time", ["tpep_dropoff_datetime", "lpep_dropoff_datetime", "dropoff_datetime"]),
    "pickup_zone": ("TLC taxi zone ID of the pick-up location", ["PULocationID"]),
    "dropoff_zone": ("TLC taxi zone ID of the drop-off location", ["DOLocationID"]),
    "distance": ("trip distance in miles", ["trip_distance", "trip_miles"]),
    "base_fare": ("base fare (time-and-distance fare, before taxes, tolls, tips and surcharges)", ["fare_amount", "base_passenger_fare"]),
    "tip": ("tip amount", ["tip_amount", "tips"]),
    "tolls": ("tolls paid", ["tolls_amount", "tolls"]),
    "airport_fee": ("airport fee charged for pick-ups at LaGuardia / JFK", ["airport_fee"]),
    "congestion_surcharge": ("NYS congestion surcharge", ["congestion_surcharge"]),
    "cbd_fee": ("MTA Congestion Relief Zone (CBD) congestion fee", ["cbd_congestion_fee"]),
    "total_charged": ("total amount charged to passengers (excluding cash tips)", ["total_amount"]),
    "provider": ("code of the provider / vendor / HVFHS licensee that supplied the record", ["VendorID", "hvfhs_license_num"]),
    "dispatch_base": ("TLC base license number of the dispatching base", ["dispatching_base_num"]),
    "shared_flag": ("flag for a shared / pooled ride request", ["SR_Flag", "shared_request_flag"]),
    "passenger_count": ("number of passengers", ["passenger_count"]),
    "rate_code": ("final rate code in effect at the end of the trip", ["RatecodeID"]),
}
BB_CONCEPTS = {
    "power_on_hours": ("raw SMART power-on-hours counter (SMART 9)", ["smart_9_raw"]),
    "reallocated_sectors": ("raw reallocated sectors count (SMART 5)", ["smart_5_raw"]),
    "reported_uncorrect": ("raw reported uncorrectable errors (SMART 187)", ["smart_187_raw"]),
    "command_timeout": ("raw command timeout count (SMART 188)", ["smart_188_raw"]),
    "pending_sectors": ("raw current pending sector count (SMART 197)", ["smart_197_raw"]),
    "offline_uncorrectable": ("raw offline uncorrectable sector count (SMART 198)", ["smart_198_raw"]),
    "temperature": ("raw drive temperature (SMART 194)", ["smart_194_raw"]),
    "capacity": ("drive capacity in bytes", ["capacity_bytes"]),
    "failure_label": ("0/1 label that is 1 on the drive's last day before failure", ["failure"]),
    "drive_model": ("manufacturer-assigned model number", ["model"]),
    "drive_id": ("manufacturer-assigned serial number", ["serial_number"]),
    "observation_date": ("observation date", ["date"]),
    "datacenter": ("data center in which the drive is installed", ["datacenter"]),
    "vault": ("ID of the storage vault the drive is in", ["vault_id"]),
    "pod": ("ID of the storage pod the drive is in", ["pod_id"]),
    "legacy_flag": ("flag whether the SMART data were collected in the legacy format", ["is_legacy_format"]),
    "spin_retry": ("raw spin retry count (SMART 10)", ["smart_10_raw"]),
    "load_cycles": ("raw load/unload cycle count (SMART 193)", ["smart_193_raw"]),
}

TLC_RX = re.compile(r"(?:^|/)(yellow|green|fhv|fhvhv)_tripdata_(\d{4}-\d{2})(?:\.parquet|/part-\d+\.parquet)$")
BB_RX = re.compile(r"(?:^|/)(\d{4}-\d{2}-\d{2})\.csv$")
TLC_DS = ["yellow", "green", "fhv", "fhvhv"]
NUMERIC = re.compile(r"^(u?int\d+|double|float|halffloat|decimal.*)$")


def q2(x):
    return str(Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN))


def fr(num, den, k=5):
    if den == 0:
        return NONE
    return str((Decimal(num) / Decimal(den)).quantize(Decimal(1).scaleb(-k), rounding=ROUND_HALF_EVEN))


def find_col(names, cands):
    low = {n.lower(): n for n in names}
    for c in cands:
        if c.lower() in low:
            return low[c.lower()]
    return None


# ------------------------------------------------------------------ world indexes
_widx = {}


def tlc_index(w):
    k = (w.commit, tuple(sorted(w.overlay))) if w.overlay else w.commit
    if k in _widx:
        return _widx[k]
    parts = defaultdict(list)       # (ds, month) -> [paths]
    lookup = None
    for p in w.paths():
        m = TLC_RX.search(p)
        if m:
            parts[(m.group(1), m.group(2))].append(p)
        elif p.endswith("taxi_zone_lookup.csv"):
            lookup = p
    for v in parts.values():
        v.sort()
    r = {"parts": parts, "lookup": lookup}
    if len(_widx) > 400:
        _widx.clear()
    _widx[k] = r
    return r


def bb_index(w):
    k = ("bb", w.commit)
    if k in _widx:
        return _widx[k]
    days = {}
    for p in w.paths():
        m = BB_RX.search(p)
        if m:
            days[m.group(1)] = p
    r = {"days": days}
    _widx[k] = r
    return r


# ------------------------------------------------------------------ per-file profiles (exact full scans)
class Profiles:
    def __init__(self, lake):
        self.lake = lake
        self.path = CACHE / f"profiles_{lake}.pkl"
        self.d = pickle.loads(self.path.read_bytes()) if self.path.exists() else {}
        self.dirty = 0

    def save(self):
        if self.dirty:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_bytes(pickle.dumps(self.d))
            tmp.replace(self.path)
            self.dirty = 0

    def get(self, w, p):
        sha = w.sha(p)
        v = self.d.get(sha)
        if v is None:
            v = (tlc_profile if self.lake == "tlc" else bb_profile)(w.local(p).as_posix(), p)
            self.d[sha] = v
            self.dirty += 1
            if self.dirty >= 200:
                self.save()
        return v


def tlc_profile(lp, logical):
    import pyarrow.parquet as pq
    con = L.duck()
    schema = [(f.name, str(f.type)) for f in pq.ParquetFile(lp).schema_arrow]
    names = [n for n, _ in schema]
    src = f"read_parquet('{lp}')"
    sel = ["count(*)"]
    for n, t in schema:
        sel.append(f'count("{n}")')
        if NUMERIC.match(t):
            sel += [f'sum(round("{n}", 2)::DECIMAL(38,2))', f'count_if("{n}" < 0)', f'count_if("{n}" = 0)']
    m = TLC_RX.search(logical)
    month = m.group(2)
    y, mo = int(month[:4]), int(month[5:])
    nxt = f"{y + (mo == 12):04d}-{(mo % 12) + 1:02d}-01"
    pk = find_col(names, TLC_CONCEPTS["pickup_time"][1])
    if pk:
        sel += [f'min("{pk}")::VARCHAR', f'max("{pk}")::VARCHAR',
                f"count_if(\"{pk}\" < TIMESTAMP '{month}-01' OR \"{pk}\" >= TIMESTAMP '{nxt}')"]
    row = con.execute(f"SELECT {', '.join(sel)} FROM {src}").fetchone()
    it = iter(row)
    prof = {"n": next(it), "schema": schema, "cols": {}}
    for n, t in schema:
        c = {"nn": next(it)}
        if NUMERIC.match(t):
            s = next(it)
            c.update({"sum": str(s if s is not None else Decimal("0.00")), "neg": next(it), "zero": next(it)})
        prof["cols"][n] = c
    if pk:
        prof["pk_min"], prof["pk_max"], prof["oom"] = next(it), next(it), next(it)
    for key, concept in (("pu", "pickup_zone"), ("do", "dropoff_zone")):
        c = find_col(names, TLC_CONCEPTS[concept][1])
        prof[key] = {} if not c else {int(a): b for a, b in con.execute(
            f'SELECT "{c}"::BIGINT, count(*) FROM {src} WHERE "{c}" IS NOT NULL GROUP BY 1').fetchall()}
    c = find_col(names, ["hvfhs_license_num"])
    prof["lic"] = {} if not c else dict(con.execute(f'SELECT "{c}", count(*) FROM {src} GROUP BY 1').fetchall())
    c = find_col(names, ["dispatching_base_num"])
    prof["bases"] = sorted(r[0] for r in con.execute(f'SELECT DISTINCT upper(trim("{c}")) FROM {src} WHERE "{c}" IS NOT NULL').fetchall()) if c else []
    return prof


def bb_profile(lp, logical):
    con = L.duck()
    src = f"read_csv('{lp}', all_varchar=true, header=true, sample_size=-1)"
    cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()]
    types = [(r[0], r[1]) for r in con.execute(f"DESCRIBE SELECT * FROM read_csv('{lp}', header=true, sample_size=-1)").fetchall()]
    sel = ["count(*)", "sum(TRY_CAST(failure AS INTEGER))", "count_if(TRY_CAST(capacity_bytes AS BIGINT) < 0)",
           "sum(TRY_CAST(capacity_bytes AS BIGINT)) FILTER (WHERE TRY_CAST(capacity_bytes AS BIGINT) > 0)",
           "count(*) FILTER (WHERE TRY_CAST(capacity_bytes AS BIGINT) > 0)"] + [f'count("{c}")' for c in cols]
    row = con.execute(f"SELECT {', '.join(sel)} FROM {src}").fetchone()
    prof = {"n": row[0], "fail": row[1] or 0, "cap_neg": row[2] or 0, "cap_sum": int(row[3] or 0), "cap_n": row[4] or 0,
            "nn": dict(zip(cols, row[5:])), "schema": types}
    ms = defaultdict(set)
    failed = set()
    mfail = Counter()
    for model, h, f in con.execute(f"SELECT trim(model), hash(serial_number), TRY_CAST(failure AS INTEGER) FROM {src}").fetchall():
        ms[model].add(h)
        if f == 1:
            failed.add(h)
            mfail[model] += 1
    prof["ms"] = {k: frozenset(v) for k, v in ms.items()}
    prof["failed"] = frozenset(failed)
    prof["mfail"] = dict(mfail)
    return prof


# ------------------------------------------------------------------ helpers over a snapshot
def period_parts(idx, ds, period):
    """period: 'YYYY-MM' | 'YYYY' | 'all'  -> list of (month, [paths])"""
    out = []
    for (d, m), ps in sorted(idx["parts"].items()):
        if d != ds:
            continue
        if period == "all" or m == period or (len(period) == 4 and m.startswith(period)):
            out.append((m, ps))
    return out


def latest_paths(idx, ds):
    ms = sorted(m for (d, m) in idx["parts"] if d == ds)
    return idx["parts"][(ds, ms[-1])] if ms else []


def read_lookup(w, p):
    txt = w.text(p)
    rd = csv.DictReader(io.StringIO(txt))
    return {int(r["LocationID"]): (r["Borough"], r["Zone"], r["service_zone"]) for r in rd if r.get("LocationID", "").strip().isdigit()}


def topk(counter, k):
    items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return ", ".join(str(a) for a, _ in items[:k]) if items else NONE


# ------------------------------------------------------------------ oracle: relevant files + combine
def relevant(w, f):
    """(paths the value depends on)."""
    t, a = f["type"], f["args"]
    if f["lake"] == "tlc":
        idx = tlc_index(w)
        ds = a.get("ds")
        if t in ("D1", "D2"):
            return latest_paths(idx, ds)[:1]
        if t == "D8" and a["sub"] == "datasets_with_column":
            return sum((latest_paths(idx, d)[:1] for d in TLC_DS), [])
        if t == "D3":
            return idx["parts"].get((ds, a["month"]), [])
        if t in ("D4", "D8"):
            return sum((ps for _, ps in period_parts(idx, ds, a.get("year", "all"))), [])
        if t in ("D5", "D7"):
            return sum((ps for _, ps in period_parts(idx, ds, a["period"])), [])
        if t == "D6":
            ps = sum((ps for _, ps in period_parts(idx, ds, a["period"])), [])
            return ps + ([idx["lookup"]] if idx["lookup"] else [])
    else:
        days = bb_index(w)["days"]
        keys = sorted(days)
        if t in ("D1", "D2") or (t == "D8" and a["sub"] == "n_columns_latest"):
            return [days[keys[-1]]] if keys else []
        if t in ("D3", "D5", "D7"):
            per = a.get("month") or a.get("period")
            return [days[k] for k in keys if per == "all" or k.startswith(per)]
        if t == "D4":
            per = a.get("year", "all")
            return [days[k] for k in keys if per == "all" or k.startswith(per)]
        if t == "D6":
            coh = [days[k] for k in keys if k.startswith(a["cohort_month"])]
            if a["sub"] == "failed_to_date":
                return coh + [days[k] for k in keys if k > a["cohort_month"]]
            return coh + ([days[keys[-1]]] if keys else [])
        if t == "D8":
            return [days[k] for k in keys]
    raise ValueError(t)


def oracle(w, f, P):
    return (oracle_tlc if f["lake"] == "tlc" else oracle_bb)(w, f, P)


def oracle_tlc(w, f, P):
    t, a = f["type"], f["args"]
    idx = tlc_index(w)
    ds = a.get("ds")
    if t == "D1":
        ps = latest_paths(idx, ds)
        if not ps:
            return NONE
        sch = P.get(w, ps[0])["schema"]
        c = find_col([n for n, _ in sch], [a["column"]])
        return dict(sch)[c] if c else NONE
    if t == "D2":
        ps = latest_paths(idx, ds)
        if not ps:
            return NONE
        c = find_col([n for n, _ in P.get(w, ps[0])["schema"]], TLC_CONCEPTS[a["concept"]][1])
        return c or NONE
    if t == "D8" and a["sub"] == "datasets_with_column":
        out = [d for d in TLC_DS if latest_paths(idx, d) and a["column"] in dict(P.get(w, latest_paths(idx, d)[0])["schema"])]
        return ", ".join(out) or NONE
    if t == "D8":
        parts = period_parts(idx, ds, "all")
        if a["sub"] == "latest_month":
            return parts[-1][0] if parts else NONE
        has = [m for m, ps in parts if a["column"] in dict(P.get(w, ps[0])["schema"])]
        if a["sub"] == "first_month":
            return has[0] if has else NONE
        if a["sub"] == "n_months_with_column":
            return str(len(has)) if has else NONE
    if t in ("D3", "D4"):
        if t == "D3":
            parts = [(a["month"], idx["parts"].get((ds, a["month"]), []))]
            if not parts[0][1]:
                return NONE
        else:
            parts = period_parts(idx, ds, a.get("year", "all"))
            if not parts:
                return NONE
        profs = [P.get(w, p) for _, ps in parts for p in ps]
        agg = a["agg"]
        if agg == "count":
            return str(sum(p["n"] for p in profs))
        if agg == "n_bases":
            return str(len(set().union(*[set(p["bases"]) for p in profs])))
        if agg == "max_pickup":
            vals = [p.get("pk_max") for p in profs if p.get("pk_max")]
            return max(vals) if vals else NONE
        if agg in ("sum", "mean"):
            s, n = Decimal(0), 0
            for p in profs:
                c = find_col([x for x, _ in p["schema"]], TLC_CONCEPTS[a["concept"]][1])
                if c and "sum" in p["cols"][c]:
                    s += Decimal(p["cols"][c]["sum"])
                    n += p["cols"][c]["nn"]
            if agg == "sum":
                return q2(s) if n else NONE
            return fr(s, n, 4)
    if t in ("D5", "D6", "D7"):
        parts = period_parts(idx, ds, a["period"])
        if not parts:
            return NONE
        profs = [P.get(w, p) for _, ps in parts for p in ps]
        if t == "D5":
            if a["sub"] == "busiest_month":
                return topk(Counter({m: sum(P.get(w, p)["n"] for p in ps) for m, ps in parts}), 1)
            if a["sub"] == "top_provider":
                return topk(sum((Counter(p["lic"]) for p in profs), Counter()), 1)
            return topk(sum((Counter(p[a["side"]]) for p in profs), Counter()), a["k"])
        if t == "D6":
            if not idx["lookup"]:
                return NONE
            lk = read_lookup(w, idx["lookup"])
            cnt = sum((Counter(p["pu"]) for p in profs), Counter())
            if a["sub"] == "top_zone_name":
                z = topk(cnt, 1)
                return NONE if z == NONE else (lk[int(z)][1] if int(z) in lk else "UNMATCHED_ID")
            by = Counter()
            col = 0 if a["sub"] in ("top_borough", "count_borough") else 2
            for z, n in cnt.items():
                by[lk[z][col] if z in lk else "UNMATCHED_ID"] += n
            if a["sub"] in ("top_borough", "top_service_zone"):
                return topk(by, 1)
            return str(by.get(a["value"], 0))
        if t == "D7":
            n = sum(p["n"] for p in profs)
            if a["check"] == "out_of_month":
                if any("oom" not in p for p in profs):
                    return NONE
                return fr(sum(p["oom"] or 0 for p in profs), n)
            num = 0
            for p in profs:
                c = find_col([x for x, _ in p["schema"]], [a["column"]])
                if c is None:
                    if a["check"] == "null_frac":
                        num += p["n"]        # absent column counts as all-null
                    continue
                cc = p["cols"][c]
                if a["check"] == "null_frac":
                    num += p["n"] - (cc["nn"] or 0)
                elif a["check"] == "neg_frac":
                    num += cc.get("neg") or 0
                elif a["check"] == "zero_frac":
                    num += cc.get("zero") or 0
            return fr(num, n)
    raise ValueError((t, a))


def oracle_bb(w, f, P):
    t, a = f["type"], f["args"]
    days = bb_index(w)["days"]
    keys = sorted(days)
    if not keys:
        return NONE
    if t in ("D1", "D2") or (t == "D8" and a["sub"] == "n_columns_latest"):
        sch = P.get(w, days[keys[-1]])["schema"]
        if t == "D8":
            return str(len(sch))
        if t == "D1":
            c = find_col([n for n, _ in sch], [a["column"]])
            return dict(sch)[c] if c else NONE
        return find_col([n for n, _ in sch], BB_CONCEPTS[a["concept"]][1]) or NONE
    if t == "D8":
        if a["sub"] == "latest_date":
            return keys[-1]
        has = [k for k in keys if a["column"] in P.get(w, days[k])["nn"]]
        if a["sub"] == "first_date":
            return has[0] if has else NONE
        if a["sub"] == "n_files_with_column":
            return str(len(has)) if has else NONE
    per = a.get("month") or a.get("period") or a.get("year", "all")
    sel = [days[k] for k in keys if per == "all" or k.startswith(per)]
    if t != "D6" and not sel:
        return NONE
    profs = [P.get(w, p) for p in sel]
    if t in ("D3", "D4"):
        agg = a["agg"]
        if agg == "drive_days":
            return str(sum(p["n"] for p in profs))
        if agg == "failures":
            return str(sum(p["fail"] for p in profs))
        if agg == "n_drives":
            return str(len(frozenset().union(*[frozenset().union(*p["ms"].values()) if p["ms"] else frozenset() for p in profs])))
        if agg == "n_models":
            return str(len(set().union(*[set(p["ms"]) for p in profs])))
        if agg == "mean_capacity_tb":
            n = sum(p["cap_n"] or 0 for p in profs)
            return fr(sum(p["cap_sum"] or 0 for p in profs), n * 10 ** 12, 4) if n else NONE
        if agg == "latest_date_in_year":
            return [k for k in keys if per == "all" or k.startswith(per)][-1]
    if t == "D5":
        if a["sub"] == "top_model_days":
            c = Counter()
            for p in profs:
                for m, s in p["ms"].items():
                    c[m] += len(s)
            return topk(c, a["k"])
        if a["sub"] == "top_model_failures":
            c = sum((Counter(p["mfail"]) for p in profs), Counter())
            return topk(c, a.get("k", 1))
    if t == "D6":
        coh_files = [days[k] for k in keys if k.startswith(a["cohort_month"])]
        if not coh_files:
            return NONE
        coh = frozenset().union(*[P.get(w, p)["ms"].get(a["model"], frozenset()) for p in coh_files])
        if not coh:
            return NONE
        if a["sub"] == "failed_to_date":
            later = [days[k] for k in keys if k >= a["cohort_month"]]
            failed = frozenset().union(*[P.get(w, p)["failed"] for p in later])
            return str(len(coh & failed))
        last = P.get(w, days[keys[-1]])
        return str(len(coh & last["ms"].get(a["model"], frozenset())))
    if t == "D7":
        n = sum(p["n"] for p in profs)
        if a["check"] == "cap_neg_frac":
            return fr(sum(p["cap_neg"] or 0 for p in profs), n)
        if a["check"] == "null_frac":
            return fr(sum(p["n"] - p["nn"].get(a["column"], 0) for p in profs), n)
    raise ValueError((t, a))


# ------------------------------------------------------------------ independent single-statement recomputation
def oracle_direct(w, f):
    """Recompute a fact with ONE DuckDB SQL full scan over the snapshot's files (no profiles); used by the smoke test."""
    con = L.duck()
    t, a = f["type"], f["args"]
    files = relevant(w, f)
    if f["lake"] == "tlc":
        data = [p for p in files if TLC_RX.search(p)]
        if t in ("D1", "D2", "D8"):
            return _direct_schema_tlc(w, f)
        if not data:
            return NONE

        def colexpr(p, cands, cast="DOUBLE"):
            import pyarrow.parquet as pq
            names = pq.ParquetFile(w.local(p)).schema_arrow.names
            c = find_col(names, cands)
            return f'"{c}"' if c else "NULL"

        def union(expr_fn):
            return " UNION ALL ".join(f"SELECT {expr_fn(p)} FROM read_parquet('{w.local(p).as_posix()}')" for p in data)

        if t in ("D3", "D4"):
            agg = a["agg"]
            if agg == "count":
                return str(con.execute(f"SELECT count(*) FROM ({union(lambda p: '1 AS x')})").fetchone()[0])
            if agg == "n_bases":
                return str(con.execute(f"SELECT count(DISTINCT upper(trim(b))) FROM ({union(lambda p: colexpr(p, ['dispatching_base_num']) + ' AS b')})").fetchone()[0])
            if agg == "max_pickup":
                v = con.execute(f"SELECT max(x)::VARCHAR FROM ({union(lambda p: colexpr(p, TLC_CONCEPTS['pickup_time'][1]) + ' AS x')})").fetchone()[0]
                return v or NONE
            cands = TLC_CONCEPTS[a["concept"]][1]
            s, n = con.execute(f"SELECT sum(round(x, 2)::DECIMAL(38,2)), count(x) FROM ({union(lambda p: colexpr(p, cands) + '::DOUBLE AS x')})").fetchone()
            if n == 0:
                return NONE
            return q2(s) if agg == "sum" else fr(s, n, 4)
        if t == "D5":
            if a["sub"] == "busiest_month":
                rows = con.execute(f"SELECT m, count(*) c FROM ({' UNION ALL '.join(f'''SELECT '{TLC_RX.search(p).group(2)}' AS m FROM read_parquet('{w.local(p).as_posix()}')''' for p in data)}) GROUP BY m ORDER BY c DESC, m LIMIT 1").fetchall()
                return rows[0][0] if rows else NONE
            if a["sub"] == "top_provider":
                rows = con.execute(f"SELECT x, count(*) c FROM ({union(lambda p: colexpr(p, ['hvfhs_license_num']) + ' AS x')}) GROUP BY x ORDER BY c DESC, x LIMIT 1").fetchall()
                return rows[0][0] if rows and rows[0][0] is not None else NONE
            cands = TLC_CONCEPTS["pickup_zone" if a["side"] == "pu" else "dropoff_zone"][1]
            rows = con.execute(f"SELECT x::BIGINT, count(*) c FROM ({union(lambda p: colexpr(p, cands) + ' AS x')}) WHERE x IS NOT NULL GROUP BY 1 ORDER BY c DESC, 1 LIMIT {a['k']}").fetchall()
            return ", ".join(str(r[0]) for r in rows) or NONE
        if t == "D6":
            lk = tlc_index(w)["lookup"]
            if not lk:
                return NONE
            lsrc = f"read_csv('{w.local(lk).as_posix()}', header=true, all_varchar=true)"
            trips = f"({union(lambda p: colexpr(p, TLC_CONCEPTS['pickup_zone'][1]) + '::BIGINT AS z')})"
            if a["sub"] == "top_zone_name":
                r = con.execute(f"SELECT z, count(*) c FROM {trips} WHERE z IS NOT NULL GROUP BY z ORDER BY c DESC, z LIMIT 1").fetchall()
                if not r:
                    return NONE
                nm = con.execute(f"SELECT Zone FROM {lsrc} WHERE TRY_CAST(LocationID AS BIGINT) = {r[0][0]}").fetchall()
                return nm[0][0] if nm else "UNMATCHED_ID"
            col = "Borough" if a["sub"] in ("top_borough", "count_borough") else "service_zone"
            q = (f"SELECT coalesce(l.{col}, 'UNMATCHED_ID') g, count(*) c FROM {trips} t LEFT JOIN {lsrc} l "
                 f"ON TRY_CAST(l.LocationID AS BIGINT) = t.z WHERE t.z IS NOT NULL GROUP BY g")
            rows = con.execute(q + " ORDER BY c DESC, g").fetchall()
            if a["sub"] in ("top_borough", "top_service_zone"):
                return rows[0][0] if rows else NONE
            return str(dict(rows).get(a["value"], 0))
        if t == "D7":
            if a["check"] == "out_of_month":
                def e(p):
                    m = TLC_RX.search(p).group(2)
                    y, mo = int(m[:4]), int(m[5:])
                    nxt = f"{y + (mo == 12):04d}-{(mo % 12) + 1:02d}-01"
                    c = colexpr(p, TLC_CONCEPTS["pickup_time"][1])
                    return f"({c} < TIMESTAMP '{m}-01' OR {c} >= TIMESTAMP '{nxt}') AS x"
                num, n = con.execute(f"SELECT count_if(x), count(*) FROM ({union(e)})").fetchone()
                return fr(num, n)
            pred = {"null_frac": "x IS NULL", "neg_frac": "x < 0", "zero_frac": "x = 0"}[a["check"]]
            num, n = con.execute(f"SELECT count_if({pred}), count(*) FROM ({union(lambda p: colexpr(p, [a['column']]) + ' AS x')})").fetchone()
            return fr(num, n)
    else:
        data = [p for p in files if BB_RX.search(p)]
        if t in ("D1", "D2", "D8"):
            return _direct_schema_bb(w, f)
        if not data:
            return NONE
        lst = "[" + ", ".join("'" + w.local(p).as_posix() + "'" for p in data) + "]"
        src = f"read_csv({lst}, union_by_name=true, all_varchar=true, header=true)"
        if t in ("D3", "D4"):
            agg = a["agg"]
            expr = {"drive_days": "count(*)", "failures": "coalesce(sum(TRY_CAST(failure AS INTEGER)), 0)",
                    "n_drives": "count(DISTINCT serial_number)", "n_models": "count(DISTINCT trim(model))",
                    "latest_date_in_year": "max(date)",
                    "mean_capacity_tb": "sum(TRY_CAST(capacity_bytes AS BIGINT)) FILTER (WHERE TRY_CAST(capacity_bytes AS BIGINT) > 0), "
                                        "count(*) FILTER (WHERE TRY_CAST(capacity_bytes AS BIGINT) > 0)"}[agg]
            r = con.execute(f"SELECT {expr} FROM {src}").fetchone()
            if agg == "mean_capacity_tb":
                return fr(r[0], r[1] * 10 ** 12, 4) if r[1] else NONE
            return str(r[0])
        if t == "D5":
            if a["sub"] == "top_model_days":
                rows = con.execute(f"SELECT trim(model) m, count(*) c FROM {src} GROUP BY m ORDER BY c DESC, m LIMIT {a['k']}").fetchall()
                return ", ".join(r[0] for r in rows) or NONE
            rows = con.execute(f"SELECT trim(model) m, count(*) c FROM {src} WHERE TRY_CAST(failure AS INTEGER) = 1 GROUP BY m ORDER BY c DESC, m LIMIT {a.get('k', 1)}").fetchall()
            return ", ".join(r[0] for r in rows) or NONE
        if t == "D6":
            coh = [p for p in data if BB_RX.search(p).group(1).startswith(a["cohort_month"])]
            if not coh:
                return NONE
            rest = [p for p in data if p not in coh] if a["sub"] == "failed_to_date" else [p for p in data if p not in coh]
            cl = "[" + ", ".join("'" + w.local(p).as_posix() + "'" for p in coh) + "]"
            csrc = f"read_csv({cl}, union_by_name=true, all_varchar=true, header=true)"
            n_coh = con.execute(f"SELECT count(DISTINCT serial_number) FROM {csrc} WHERE trim(model) = ?", [a["model"]]).fetchone()[0]
            if n_coh == 0:
                return NONE
            if a["sub"] == "failed_to_date":
                q = (f"SELECT count(DISTINCT c.serial_number) FROM (SELECT DISTINCT serial_number FROM {csrc} WHERE trim(model) = ?) c "
                     f"JOIN (SELECT serial_number FROM {src} WHERE TRY_CAST(failure AS INTEGER) = 1) x USING (serial_number)")
                return str(con.execute(q, [a["model"]]).fetchone()[0])
            lastp = sorted(data, key=lambda p: BB_RX.search(p).group(1))[-1]
            q = (f"SELECT count(DISTINCT c.serial_number) FROM (SELECT DISTINCT serial_number FROM {csrc} WHERE trim(model) = ?) c "
                 f"JOIN (SELECT serial_number FROM read_csv('{w.local(lastp).as_posix()}', all_varchar=true, header=true) WHERE trim(model) = ?) x USING (serial_number)")
            return str(con.execute(q, [a["model"], a["model"]]).fetchone()[0])
        if t == "D7":
            if a["check"] == "cap_neg_frac":
                num, n = con.execute(f"SELECT count_if(TRY_CAST(capacity_bytes AS BIGINT) < 0), count(*) FROM {src}").fetchone()
            else:
                c = a["column"]
                has = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()]
                if c in has:
                    num, n = con.execute(f'SELECT count(*) - count("{c}"), count(*) FROM {src}').fetchone()
                else:
                    num = n = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
            return fr(num, n)
    raise ValueError((t, a))


# independent schema / coverage recomputation: reads Parquet footers / CSV header lines directly (no profiles)
def _pq_names_types(w, p):
    import pyarrow.parquet as pq
    return [(x.name, str(x.type)) for x in pq.ParquetFile(w.local(p)).schema_arrow]


def _direct_schema_tlc(w, f):
    t, a = f["type"], f["args"]
    files = {}
    for p in w.paths():
        m = TLC_RX.search(p)
        if m:
            files.setdefault(m.group(1), {}).setdefault(m.group(2), []).append(p)

    def latest(ds):
        if ds not in files:
            return None
        m = max(files[ds])
        return sorted(files[ds][m])[0]
    if t == "D8" and a["sub"] == "datasets_with_column":
        out = [d for d in TLC_DS if latest(d) and a["column"] in [n for n, _ in _pq_names_types(w, latest(d))]]
        return ", ".join(out) or NONE
    ds = a["ds"]
    if ds not in files:
        return NONE
    if t == "D8":
        months = sorted(files[ds])
        if a["sub"] == "latest_month":
            return months[-1]
        has = [m for m in months if a["column"] in [n for n, _ in _pq_names_types(w, sorted(files[ds][m])[0])]]
        if not has:
            return NONE
        return has[0] if a["sub"] == "first_month" else str(len(has))
    sch = _pq_names_types(w, latest(ds))
    names = [n for n, _ in sch]
    if t == "D1":
        c = next((n for n in names if n.lower() == a["column"].lower()), None)
        return dict(sch)[c] if c else NONE
    cands = [x.lower() for x in TLC_CONCEPTS[a["concept"]][1]]
    for c in TLC_CONCEPTS[a["concept"]][1]:
        hit = next((n for n in names if n.lower() == c.lower()), None)
        if hit:
            return hit
    return NONE


def _csv_header(w, p):
    with open(w.local(p), "rb") as fh:
        h = fh.read(65536).replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n")[0].decode()
    return [c.strip() for c in h.split(",")]


def _direct_schema_bb(w, f):
    t, a = f["type"], f["args"]
    days = sorted((m.group(1), p) for p in w.paths() for m in [BB_RX.search(p)] if m)
    if not days:
        return NONE
    if t == "D8":
        if a["sub"] == "latest_date":
            return days[-1][0]
        if a["sub"] == "n_columns_latest":
            return str(len(_csv_header(w, days[-1][1])))
        has = [d for d, p in days if a["column"] in _csv_header(w, p)]
        if not has:
            return NONE
        return has[0] if a["sub"] == "first_date" else str(len(has))
    lp = w.local(days[-1][1]).as_posix()
    sch = [(r[0], r[1]) for r in L.duck().execute(f"DESCRIBE SELECT * FROM read_csv('{lp}', header=true, sample_size=-1)").fetchall()]
    names = [n for n, _ in sch]
    if t == "D1":
        c = next((n for n in names if n.lower() == a["column"].lower()), None)
        return dict(sch)[c] if c else NONE
    for c in BB_CONCEPTS[a["concept"]][1]:
        hit = next((n for n in names if n.lower() == c.lower()), None)
        if hit:
            return hit
    return NONE


class _NoCacheProfiles(Profiles):
    def __init__(self, lake):
        self.lake, self.d, self.dirty, self.path = lake, {}, 0, None

    def save(self):
        pass


# ------------------------------------------------------------------ questions
PERIOD_TXT = lambda p: "all data in the lake so far" if p == "all" else (f"calendar year {p} (all monthly files of {p} present so far)" if len(p) == 4 else f"the {p} monthly file")


def question(f):
    t, a = f["type"], f["args"]
    if f["lake"] == "tlc":
        ds = a.get("ds")
        DS = {"yellow": "Yellow taxi", "green": "Green taxi", "fhv": "FHV", "fhvhv": "High Volume FHV (fhvhv)"}.get(ds, ds)
        if t == "D1":
            return f"In the most recent {DS} trip file in the lake, what is the Arrow/Parquet data type of column `{a['column']}` (matched case-insensitively)? Answer with the type name, e.g. int64, double, string, large_string, timestamp[us], null."
        if t == "D2":
            return f"In the most recent {DS} trip file, what is the exact (case-sensitive) name of the column that holds the {TLC_CONCEPTS[a['concept']][0]}? Answer NONE if no column holds it."
        if t == "D3":
            if a["agg"] == "count":
                return f"How many rows does the {DS} partition for month {a['month']} contain (all files of that month)?"
            if a["agg"] == "n_bases":
                return f"How many distinct dispatching base numbers (upper-cased, trimmed) occur in the {DS} partition for month {a['month']}?"
            c = TLC_CONCEPTS[a["concept"]][0]
            return (f"In the {DS} partition for month {a['month']}, what is the {'sum' if a['agg'] == 'sum' else 'mean over non-null rows'} of the {c} "
                    f"(each value rounded to cents first){'; answer with 2 decimals' if a['agg'] == 'sum' else '; answer with 4 decimals'}?")
        if t == "D4":
            scope = "all monthly files present so far" if a.get("year", "all") == "all" else f"all monthly files of {a['year']} present so far"
            if a["agg"] == "count":
                return f"How many {DS} trip rows are there in total over {scope}?"
            if a["agg"] == "max_pickup":
                return f"What is the latest pickup timestamp over {scope} of {DS} data (YYYY-MM-DD HH:MM:SS)?"
            return f"What is the total {TLC_CONCEPTS[a['concept']][0]} summed over {scope} of {DS} data (values rounded to cents first; 2 decimals)?"
        if t == "D5":
            if a["sub"] == "busiest_month":
                return f"Which monthly {DS} partition present so far has the most rows (YYYY-MM)?"
            if a["sub"] == "top_provider":
                return f"Which hvfhs_license_num has the most trips in {PERIOD_TXT(a['period'])} of {DS} data?"
            side = "pick-up" if a["side"] == "pu" else "drop-off"
            return (f"Which {a['k']} {side} zone ID(s) have the most {DS} trips in {PERIOD_TXT(a['period'])}? Ignore NULL zone IDs; "
                    f"order by count descending, ties by ID ascending; answer comma-separated.")
        if t == "D6":
            base = f"Join the {DS} trips of {PERIOD_TXT(a['period'])} on their pick-up zone ID with the taxi zone lookup table currently in the lake."
            if a["sub"] == "top_zone_name":
                return base + " What is the Zone name of the pick-up zone with the most trips?"
            if a["sub"] == "top_borough":
                return base + " Which Borough value has the most trips?"
            if a["sub"] == "top_service_zone":
                return base + " Which service_zone value has the most trips?"
            what = "Borough" if a["sub"] == "count_borough" else "service_zone"
            return base + f" How many trips have {what} = '{a['value']}'?"
        if t == "D7":
            if a["check"] == "out_of_month":
                return f"What fraction of {DS} rows in {PERIOD_TXT(a['period'])} have a pickup timestamp outside the month of the file they are stored in? (5 decimals)"
            what = {"null_frac": "NULL (a missing column counts as NULL)", "neg_frac": "negative", "zero_frac": "exactly zero"}[a["check"]]
            return f"What fraction of {DS} rows in {PERIOD_TXT(a['period'])} have a {what} value in column `{a['column']}` (matched case-insensitively)? (5 decimals)"
        if t == "D8":
            if a["sub"] == "datasets_with_column":
                return f"Which of the datasets yellow, green, fhv, fhvhv have a column named exactly `{a['column']}` (case-sensitive) in their most recent file? Answer in the order yellow, green, fhv, fhvhv, comma-separated."
            if a["sub"] == "latest_month":
                return f"What is the most recent month (YYYY-MM) for which a {DS} trip file is in the lake?"
            if a["sub"] == "first_month":
                return f"What is the earliest month (YYYY-MM) whose {DS} file has a column named exactly `{a['column']}` (case-sensitive)?"
            return f"How many monthly {DS} partitions have a column named exactly `{a['column']}` (case-sensitive)?"
    else:
        if t == "D1":
            return f"In the most recent daily Drive Stats CSV in the lake, what data type does DuckDB infer for column `{a['column']}` (read_csv with sample_size=-1)? Answer e.g. BIGINT, DOUBLE, VARCHAR."
        if t == "D2":
            return f"In the most recent daily Drive Stats CSV, what is the exact name of the column holding the {BB_CONCEPTS[a['concept']][0]}? Answer NONE if absent."
        per = a.get("month") or a.get("period") or a.get("year", "all")
        scope = "all daily files present so far" if per == "all" else f"all daily files of {per} present so far"
        if t in ("D3", "D4"):
            return {"drive_days": f"How many drive-day rows are there in {scope}?",
                    "failures": f"How many failure records (failure = 1) are there in {scope}?",
                    "n_drives": f"How many distinct serial numbers appear in {scope}?",
                    "n_models": f"How many distinct (trimmed) model names appear in {scope}?",
                    "mean_capacity_tb": f"What is the mean capacity_bytes in TB (10^12 bytes; rows with capacity_bytes <= 0 excluded) over {scope}? (4 decimals)",
                    "latest_date_in_year": f"What is the latest date covered by {scope}?"}[a["agg"]]
        if t == "D5":
            if a["sub"] == "top_model_days":
                return f"Which {a['k']} model(s) have the most drive-day rows in {scope}? Order by count descending, ties by name; comma-separated."
            return (f"Which {a.get('k', 1)} model(s) have the most failure records in {scope}? Order by count descending, "
                    f"ties by name; comma-separated.")
        if t == "D6":
            if a["sub"] == "failed_to_date":
                return (f"Consider the drives (serial numbers) of model `{a['model']}` that appear in the daily files of {a['cohort_month']}. "
                        f"How many of them have a failure = 1 record in any daily file from {a['cohort_month']} onwards present so far?")
            return (f"Consider the drives of model `{a['model']}` that appear in the daily files of {a['cohort_month']}. "
                    f"How many of them appear (with that model) in the most recent daily file in the lake?")
        if t == "D7":
            if a["check"] == "cap_neg_frac":
                return f"What fraction of rows in {scope} have a negative capacity_bytes? (5 decimals)"
            return f"What fraction of rows in {scope} have an empty value in column `{a['column']}` (a missing column counts as empty)? (5 decimals)"
        if t == "D8":
            if a["sub"] == "latest_date":
                return "What is the most recent date for which a daily Drive Stats file is in the lake?"
            if a["sub"] == "n_columns_latest":
                return "How many columns does the most recent daily Drive Stats file have?"
            if a["sub"] == "first_date":
                return f"What is the earliest date whose daily file has a column named `{a['column']}`?"
            return f"How many daily files present so far have a column named `{a['column']}`?"
    raise ValueError((t, a))


# ------------------------------------------------------------------ canonicaliser for agent answers
def canon(f, s):
    if s is None:
        return None
    s = str(s).strip().strip("`").strip().strip("'\"")
    if s.upper() in ("NONE", "N/A_NONE", ""):
        return NONE
    v = f.get("K_oracle", "")
    if re.fullmatch(r"-?\d+\.\d+", v or ""):
        try:
            k = len(v.split(".")[1])
            return str(Decimal(s.replace(",", "")).quantize(Decimal(1).scaleb(-k), rounding=ROUND_HALF_EVEN))
        except Exception:
            return s
    if re.fullmatch(r"-?\d+", v or ""):
        m = re.search(r"-?[\d,]+", s)
        return m.group(0).replace(",", "") if m else s
    if f["type"] in ("D5",) or (f["type"] == "D8" and f["args"].get("sub") == "datasets_with_column"):
        return ", ".join(x.strip().strip("'\"") for x in re.split(r"[,\n]", s) if x.strip())
    if f["type"] == "D1" and f["lake"] == "bb":
        return s.upper()
    return s


def matches(f, answer, value):
    return canon(f, answer) == value


# ------------------------------------------------------------------ candidate enumeration at s0
def enumerate_tlc(w, P):
    idx = tlc_index(w)
    C = defaultdict(list)
    months = {ds: [m for m, _ in period_parts(idx, ds, "all")] for ds in TLC_DS}
    years = {ds: sorted({m[:4] for m in months[ds]}) for ds in TLC_DS}
    for ds in TLC_DS:
        lp = latest_paths(idx, ds)
        if not lp:
            continue
        names = [n for n, _ in P.get(w, lp[0])["schema"]]
        for n in names:
            C["D1"].append({"ds": ds, "column": n})
        for c, (_, cands) in TLC_CONCEPTS.items():
            if find_col(names, cands):
                C["D2"].append({"ds": ds, "concept": c})
        money = [c for c in ("base_fare", "tip", "tolls", "total_charged", "congestion_surcharge", "airport_fee", "distance")
                 if find_col(names, TLC_CONCEPTS[c][1])]
        for m in months[ds]:
            C["D3"].append({"ds": ds, "month": m, "agg": "count"})
            for c in money:
                C["D3"].append({"ds": ds, "month": m, "agg": "sum", "concept": c})
                C["D3"].append({"ds": ds, "month": m, "agg": "mean", "concept": c})
            if ds in ("fhv", "fhvhv"):
                C["D3"].append({"ds": ds, "month": m, "agg": "n_bases"})
        for y in years[ds] + ["all"]:
            C["D4"].append({"ds": ds, "year": y, "agg": "count"})
            C["D4"].append({"ds": ds, "year": y, "agg": "max_pickup"})
            for c in money:
                C["D4"].append({"ds": ds, "year": y, "agg": "sum", "concept": c})
        periods = years[ds] + ["all"] + months[ds][-6:]
        for p in periods:
            for side in ("pu", "do"):
                for k in (1, 3):
                    C["D5"].append({"ds": ds, "period": p, "sub": "topk", "side": side, "k": k})
            if ds == "fhvhv":
                C["D5"].append({"ds": ds, "period": p, "sub": "top_provider"})
            for sub in ("top_zone_name", "top_borough", "top_service_zone"):
                C["D6"].append({"ds": ds, "period": p, "sub": sub})
            for b in ("Unknown", "Manhattan", "Queens", "EWR", "N/A"):
                C["D6"].append({"ds": ds, "period": p, "sub": "count_borough", "value": b})
            for sz in ("N/A", "Yellow Zone", "Boro Zone", "Airports", "EWR"):
                C["D6"].append({"ds": ds, "period": p, "sub": "count_service_zone", "value": sz})
            C["D7"].append({"ds": ds, "period": p, "check": "out_of_month"})
            for n in names:
                C["D7"].append({"ds": ds, "period": p, "check": "null_frac", "column": n})
            for c in money + ["passenger_count"]:
                col = find_col(names, TLC_CONCEPTS[c][1]) if c in TLC_CONCEPTS else None
                if col:
                    C["D7"].append({"ds": ds, "period": p, "check": "neg_frac", "column": col})
                    C["D7"].append({"ds": ds, "period": p, "check": "zero_frac", "column": col})
        C["D5"].append({"ds": ds, "period": "all", "sub": "busiest_month"})
        C["D8"].append({"ds": ds, "sub": "latest_month"})
        for n in names:
            C["D8"].append({"ds": ds, "sub": "first_month", "column": n})
            C["D8"].append({"ds": ds, "sub": "n_months_with_column", "column": n})
    allcols = sorted({n for ds in TLC_DS for n in ([x for x, _ in P.get(w, latest_paths(idx, ds)[0])["schema"]] if latest_paths(idx, ds) else [])})
    for n in allcols:
        C["D8"].append({"sub": "datasets_with_column", "column": n})
    return C


def enumerate_bb(w, P):
    days = bb_index(w)["days"]
    keys = sorted(days)
    C = defaultdict(list)
    last = P.get(w, days[keys[-1]])
    cols = [n for n, _ in last["schema"]]
    for c in cols:
        C["D1"].append({"column": c})
    for c, (_, cands) in BB_CONCEPTS.items():
        if find_col(cols, cands):
            C["D2"].append({"concept": c})
    months = sorted({k[:7] for k in keys})
    years = sorted({k[:4] for k in keys})
    for m in months:
        for agg in ("drive_days", "failures", "n_drives", "n_models", "mean_capacity_tb"):
            C["D3"].append({"month": m, "agg": agg})
    for y in years + ["all"]:
        for agg in ("drive_days", "failures", "n_drives", "n_models", "mean_capacity_tb", "latest_date_in_year"):
            C["D4"].append({"year": y, "agg": agg})
    periods = years + ["all"] + months[-6:]
    for p in periods:
        for k in (1, 3, 5):
            C["D5"].append({"period": p, "sub": "top_model_days", "k": k})
        for k in (1, 3):
            C["D5"].append({"period": p, "sub": "top_model_failures", "k": k})
        C["D7"].append({"period": p, "check": "cap_neg_frac"})
        for c in ("smart_9_raw", "smart_5_raw", "smart_187_raw", "smart_188_raw", "smart_197_raw", "smart_194_raw",
                  "smart_10_raw", "smart_193_raw", "smart_240_raw", "smart_241_raw", "smart_242_raw", "smart_1_normalized"):
            C["D7"].append({"period": p, "check": "null_frac", "column": c})
    # cohorts: models with >= 20 drives in a cohort month (one month per quarter to keep the pool tractable)
    for m in months[::3]:
        coh = defaultdict(set)
        for k in keys:
            if k.startswith(m):
                for model, s in P.get(w, days[k])["ms"].items():
                    coh[model] |= s
        for model, s in coh.items():
            if len(s) >= 20:
                C["D6"].append({"model": model, "cohort_month": m, "sub": "failed_to_date"})
                C["D6"].append({"model": model, "cohort_month": m, "sub": "present_latest_day"})
    C["D8"].append({"sub": "latest_date"})
    C["D8"].append({"sub": "n_columns_latest"})
    for c in cols:
        C["D8"].append({"sub": "first_date", "column": c})
        C["D8"].append({"sub": "n_files_with_column", "column": c})
    return C


# ------------------------------------------------------------------ series + sampling
def series(lk, f, P, worlds, memo):
    out = []
    for w in worlds:
        rel = relevant(w, f)
        # the value is a function of the versions of exactly these files (relevant() includes the lookup table)
        key = (f["type"], json.dumps(f["args"], sort_keys=True), tuple((p, w.sha(p)) for p in rel))
        v = memo.get(key)
        if v is None:
            v = oracle(w, f, P)
            memo[key] = v
        out.append(v)
    return out


def build(lake_name, pool_per_type=150, n_natural=11, n_enriched=11, seed=0):
    rng = random.Random(seed)
    lk = L.Lake(lake_name)
    P = Profiles(lake_name)
    worlds = [lk.world(s) for s in lk.commits]          # HISTORY + s0 + FUTURE
    w0 = worlds[lk.s0_idx]
    t0 = time.time()
    C = (enumerate_tlc if lake_name == "tlc" else enumerate_bb)(w0, P)
    print("candidates", {k: len(v) for k, v in C.items()}, f"{time.time() - t0:.0f}s", flush=True)
    memo = {}
    facts, stats, oracle_rows = [], {}, []
    for t in ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"]:
        cands = list(C.get(t, []))
        rng.shuffle(cands)
        pool = []
        scan_pos = 0
        for a in cands:
            if len(pool) >= pool_per_type:
                break
            scan_pos += 1
            f = {"lake": lake_name, "type": t, "args": a}
            ser = series(lk, f, P, worlds, memo)
            k = ser[lk.s0_idx]
            if k == NONE:
                continue
            fut = ser[lk.s0_idx + 1:]
            hist = ser[:lk.s0_idx]
            pool.append({"args": a, "K": k, "ser": ser, "nchg": sum(1 for v in fut if v != k),
                         "hist_changes": sum(1 for x, y in zip(hist, hist[1:] + [k]) if x != y)})
        P.save()
        chg = [e for e in pool if e["nchg"] > 0]
        stats[t] = {"n_candidates": len(C.get(t, [])), "pool": len(pool),
                    "pool_frac_changing": round(len(chg) / max(1, len(pool)), 3),
                    "pool_frac_invalid_pairs": round(sum(e["nchg"] for e in pool) / max(1, len(pool) * len(lk.future)), 3)}
        natural = rng.sample(pool, min(n_natural, len(pool)))
        rest_chg = [e for e in chg if e not in natural]
        # change enrichment may look beyond the pool (these extra candidates do NOT enter the pool base rates)
        extra_scanned = 0
        for a in cands[scan_pos:]:
            if len(rest_chg) >= 3 * n_enriched or extra_scanned >= 600:
                break
            f = {"lake": lake_name, "type": t, "args": a}
            ser = series(lk, f, P, worlds, memo)
            extra_scanned += 1
            k = ser[lk.s0_idx]
            if k == NONE:
                continue
            nchg = sum(1 for v in ser[lk.s0_idx + 1:] if v != k)
            if nchg:
                hist = ser[:lk.s0_idx]
                rest_chg.append({"args": a, "K": k, "ser": ser, "nchg": nchg,
                                 "hist_changes": sum(1 for x, y in zip(hist, hist[1:] + [k]) if x != y)})
        stats[t]["enrichment_extra_scanned"] = extra_scanned
        enriched = rng.sample(rest_chg, min(n_enriched, len(rest_chg)))
        if len(enriched) < n_enriched:     # not enough changing facts: fill with more natural draws
            rest = [e for e in pool if e not in natural and e not in enriched]
            fill = rng.sample(rest, min(n_enriched - len(enriched), len(rest)))
            for e in fill:
                e["_fill"] = True
            enriched += fill
        nat_chg = sum(1 for e in natural if e["nchg"] > 0)
        stats[t].update({"natural_n": len(natural), "natural_frac_changing": round(nat_chg / max(1, len(natural)), 3),
                         "enriched_n": len(enriched), "enriched_frac_changing": round(sum(1 for e in enriched if e["nchg"] > 0) / max(1, len(enriched)), 3),
                         "enriched_fill_n": sum(1 for e in enriched if e.get("_fill"))})
        for subset, group in (("natural", natural), ("enriched", enriched)):
            for e in group:
                fid = f"{lake_name}:{t}:{len(facts)}"
                f = {"id": fid, "lake": lake_name, "type": t, "subset": "enriched_fill" if e.get("_fill") else subset, "args": e["args"], "K_oracle": e["K"],
                     "n_future_changed": e["nchg"], "first_change_future_idx": next((i for i, v in enumerate(e["ser"][lk.s0_idx + 1:]) if v != e["K"]), None),
                     "n_distinct_future_values": len(set(e["ser"][lk.s0_idx + 1:])), "history_value_changes": e["hist_changes"]}
                f["question"] = question(f)
                f["depends_on_s0"] = relevant(w0, f)[:20] + (["..."] if len(relevant(w0, f)) > 20 else [])
                facts.append(f)
                for i, (snap, v) in enumerate(zip(lk.commits, e["ser"])):
                    oracle_rows.append({"lake": lake_name, "fact_id": fid, "snap_idx": lk.s0_idx_all - lk.s0_idx + i,
                                        "window_idx": i, "snapshot": snap,
                                        "phase": "history" if i < lk.s0_idx else ("s0" if i == lk.s0_idx else "future"),
                                        "value": v, "valid": v == e["K"]})
        print(t, stats[t], f"{time.time() - t0:.0f}s", flush=True)
    import pandas as pd
    out = {"lake": lake_name, "s0": lk.s0, "s0_time": lk.event_of[lk.s0]["time"], "head": lk.commits[-1],
           "n_history": len(lk.history), "n_future": len(lk.future), "stats": stats, "facts": facts}
    (HERE / f"facts_{lake_name}.json").write_text(json.dumps(out, indent=1))
    (HERE / "oracle").mkdir(exist_ok=True)
    pd.DataFrame(oracle_rows).to_parquet(HERE / "oracle" / f"oracle_{lake_name}.parquet", index=False)
    print("facts", len(facts), "oracle rows", len(oracle_rows), f"{time.time() - t0:.0f}s")


def _profile_job(args):
    lake_name, sha, lp, logical = args
    L.duck().execute("SET threads=2")
    return sha, (tlc_profile if lake_name == "tlc" else bb_profile)(lp, logical)


def precompute(lake_name, workers=24):
    """Compute the per-file profiles of every file version in the snapshot window, in parallel."""
    import concurrent.futures as cf
    lk = L.Lake(lake_name)
    P = Profiles(lake_name)
    rx = TLC_RX if lake_name == "tlc" else BB_RX
    jobs = {}
    for s in lk.commits:
        for p, (sha, _) in lk.trees[s].items():
            if rx.search(p) and sha not in P.d and sha not in jobs:
                jobs[sha] = (lake_name, sha, L.blob_path(sha, p).as_posix(), p)
    print("profiles to compute:", len(jobs), flush=True)
    t0 = time.time()
    with cf.ProcessPoolExecutor(workers) as ex:
        for i, (sha, prof) in enumerate(ex.map(_profile_job, jobs.values(), chunksize=4)):
            P.d[sha] = prof
            P.dirty += 1
            if (i + 1) % 500 == 0:
                P.save()
                print(i + 1, f"{time.time() - t0:.0f}s", flush=True)
    P.save()
    print("done", f"{time.time() - t0:.0f}s")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[2] == "precompute":
        precompute(sys.argv[1])
    else:
        build(sys.argv[1])
