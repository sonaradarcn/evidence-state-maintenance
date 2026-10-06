"""Download, deterministically subsample and store the two real lakes in a content-addressed store.

Usage:  python ingest.py tlc  [workers]     # NYC TLC trip records 2019-01 .. 2026-08
        python ingest.py bb   [workers]     # Backblaze Drive Stats 2013 .. 2026Q2
        python ingest.py head               # HEAD every source URL, record size / Last-Modified / ETag

Per source file a JSON catalogue record is written to datalake_data/catalog/<lake>/<name>.json; the record holds the
logical path(s), the sha256 of the stored (subsampled) file(s), raw and subsampled row counts and the HTTP metadata.
The step is idempotent: a file with a catalogue record is skipped.  Raw downloads are deleted after processing.

Subsampling (documented in MANIFEST.md):
  TLC : keep row r iff md5(concat_ws('|', all columns of r cast to text, NULLs skipped)) as 128-bit int % 64 == 0
        (DuckDB 1.5.6 md5_number); rows are copied with pyarrow so the original Arrow/Parquet schema and the
        original compression codec are kept.  Rate = 1/64 = 1.5625 % of rows.
  BB  : keep row iff int(md5(serial_number).hexdigest()[:16], 16) % 64 == 0  (whole drive histories are kept);
        CSV header and column order are kept byte-for-byte; only data lines are filtered.
"""
import concurrent.futures as cf, hashlib, json, os, subprocess, sys, time, zipfile, io, shutil
from pathlib import Path

ROOT = Path(os.environ.get("ESM_LAKE_DATA", Path(__file__).resolve().parents[1] / "datalake_data"))
RAW, STORE, CAT, LOGS = ROOT / "raw", ROOT / "store", ROOT / "catalog", ROOT / "logs"
TLC_BASE = "https://d37ci6vzurychx.cloudfront.net/trip-data/"
BB_BASE = "https://f001.backblazeb2.com/file/Backblaze-Hard-Drive-Data/"
RATE = 64


def months(a, b):
    y, m = a
    while (y, m) <= b:
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m == 13:
            y, m = y + 1, 1


def tlc_files():
    out = []
    for ds in ("yellow", "green", "fhv", "fhvhv"):
        start = (2019, 2) if ds == "fhvhv" else (2019, 1)
        for ym in months(start, (2026, 8)):
            out.append(f"{ds}_tripdata_{ym}.parquet")
    return out


def bb_files():
    out = ["data_2013.zip", "data_2014.zip", "data_2015.zip"]
    for y in range(2016, 2027):
        for q in (1, 2, 3, 4):
            if (y, q) > (2026, 2):
                break
            out.append(f"data_Q{q}_{y}.zip")
    return out


def head(url):
    r = subprocess.run(["curl", "-sI", "-m", "30", url], capture_output=True, text=True)
    h = {}
    lines = r.stdout.splitlines()
    status = lines[0].split()[1] if lines else "ERR"
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            h[k.strip().lower()] = v.strip()
    return {"status": status, "content_length": int(h["content-length"]) if "content-length" in h else None,
            "last_modified": h.get("last-modified"), "etag": h.get("etag"),
            "bz_upload_ts": h.get("x-bz-upload-timestamp"), "bz_sha1": h.get("x-bz-content-sha1")}


def download(url, dest, size):
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(30):
        if dest.exists() and size and dest.stat().st_size == size:
            return
        subprocess.run(["curl", "-s", "-L", "-C", "-", "--retry", "5", "--retry-delay", "5", "-m", "7200",
                        "--speed-limit", "20000", "--speed-time", "60", "-o", str(dest), url])
        if dest.exists() and size and dest.stat().st_size > size:
            dest.unlink()
        time.sleep(2)
    if not (dest.exists() and dest.stat().st_size == size):
        raise RuntimeError(f"download failed {url}")


def put(path_or_bytes, ext):
    if isinstance(path_or_bytes, (bytes, bytearray)):
        data = bytes(path_or_bytes)
        sha = hashlib.sha256(data).hexdigest()
        dst = STORE / sha[:2] / f"{sha}{ext}"
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_suffix(dst.suffix + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, dst)
        return sha, len(data)
    p = Path(path_or_bytes)
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    sha = h.hexdigest()
    dst = STORE / sha[:2] / f"{sha}{ext}"
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), dst)
    else:
        p.unlink()
    return sha, dst.stat().st_size


# ------------------------------------------------------------------ TLC
def tlc_subsample(raw, tmp_out):
    import duckdb, pyarrow as pa, pyarrow.parquet as pq
    con = duckdb.connect()
    con.execute("SET enable_progress_bar=false; SET threads=8; SET memory_limit='12GB'")
    keep = [r[0] for r in con.execute(
        "SELECT file_row_number FROM read_parquet(?, file_row_number=true) "
        f"WHERE md5_number(concat_ws('|', *COLUMNS(* EXCLUDE (file_row_number)))) % {RATE} = 0 ORDER BY 1",
        [str(raw)]).fetchall()]
    con.close()
    pf = pq.ParquetFile(raw)
    md = pf.metadata
    codec = md.row_group(0).column(0).compression if md.num_row_groups else "SNAPPY"
    codec = {"UNCOMPRESSED": "none"}.get(codec, codec.lower())
    writer = pq.ParquetWriter(tmp_out, pf.schema_arrow, compression=codec)
    off, k = 0, 0
    for i in range(md.num_row_groups):
        n = md.row_group(i).num_rows
        loc = []
        while k < len(keep) and keep[k] < off + n:
            loc.append(keep[k] - off)
            k += 1
        if loc:
            t = pf.read_row_group(i).take(pa.array(loc, pa.int64()))
            writer.write_table(t)
        off += n
    if not keep:
        writer.write_table(pf.schema_arrow.empty_table())
    writer.close()
    sub = pq.ParquetFile(tmp_out)
    return {"n_rows_raw": md.num_rows, "n_rows_sub": sub.metadata.num_rows, "codec": codec,
            "raw_created_by": md.created_by, "raw_row_groups": md.num_row_groups,
            "schema_equal": sub.schema_arrow.equals(pf.schema_arrow, check_metadata=False),
            "schema": [(f.name, str(f.type)) for f in pf.schema_arrow]}


def do_tlc(name):
    rec_path = CAT / "tlc" / (name + ".json")
    if rec_path.exists():
        return name, "skip"
    url = TLC_BASE + name
    h = head(url)
    if h["status"] != "200":
        rec_path.write_text(json.dumps({"name": name, "url": url, "http": h, "available": False}, indent=1))
        return name, f"unavailable {h['status']}"
    raw = RAW / "tlc" / name
    download(url, raw, h["content_length"])
    raw_sha = hashlib.sha256(raw.read_bytes()).hexdigest()
    tmp = RAW / "tlc" / (name + ".sub")
    info = tlc_subsample(raw, tmp)
    sha, size = put(tmp, ".parquet")
    raw.unlink()
    rec = {"name": name, "url": url, "http": h, "available": True, "raw_sha256": raw_sha,
           "logical_path": "trip-data/" + name, "sha256": sha, "size": size, **info}
    rec_path.write_text(json.dumps(rec, indent=1))
    return name, f"ok {info['n_rows_raw']}->{info['n_rows_sub']}"


# ------------------------------------------------------------------ Backblaze
_serial_keep = {}


def keep_serial(s):
    v = _serial_keep.get(s)
    if v is None:
        v = int(hashlib.md5(s.encode()).hexdigest()[:16], 16) % RATE == 0
        _serial_keep[s] = v
    return v


def do_bb(name):
    rec_path = CAT / "bb" / (name + ".json")
    if rec_path.exists():
        return name, "skip"
    url = BB_BASE + name
    h = head(url)
    if h["status"] != "200":
        rec_path.write_text(json.dumps({"name": name, "url": url, "http": h, "available": False}, indent=1))
        return name, f"unavailable {h['status']}"
    raw = RAW / "bb" / name
    download(url, raw, h["content_length"])
    stem = name[:-4]
    members, skipped = [], []
    n_raw = n_sub = 0
    with zipfile.ZipFile(raw) as z:
        for zi in z.infolist():
            mn = zi.filename
            if zi.is_dir():
                continue
            if mn.startswith("__MACOSX/") or "/." in mn or mn.startswith("."):
                skipped.append(mn)
                continue
            logical = mn if "/" in mn else f"{stem}/{mn}"
            logical = "drive_stats/" + logical
            data = z.read(zi)
            if mn.lower().endswith(".csv"):
                text = data.decode("utf-8", "replace")
                head5k = text[:5000]
                # real quirk: a few daily files (e.g. 2018-02-25, 2019-06-17) use bare '\r' line endings
                nl = "\r\n" if "\r\n" in head5k else ("\n" if "\n" in head5k else ("\r" if "\r" in head5k else "\n"))
                lines = text.split(nl)
                hdr = lines[0]
                cols = [c.strip() for c in hdr.split(",")]
                si = cols.index("serial_number")
                out = [hdr]
                nr = 0
                for line in lines[1:]:
                    if not line:
                        continue
                    nr += 1
                    parts = line.split(",", si + 1)
                    if len(parts) > si and keep_serial(parts[si]):
                        out.append(line)
                body = nl.join(out) + nl
                sha, size = put(body.encode("utf-8"), ".csv")
                members.append({"member": mn, "logical_path": logical, "sha256": sha, "size": size,
                                "n_rows_raw": nr, "n_rows_sub": len(out) - 1, "n_cols": len(cols)})
                n_raw += nr
                n_sub += len(out) - 1
            else:
                ext = Path(mn).suffix or ".bin"
                sha, size = put(data, ext)
                members.append({"member": mn, "logical_path": logical, "sha256": sha, "size": size, "raw": True})
    raw_size = raw.stat().st_size
    raw.unlink()
    rec = {"name": name, "url": url, "http": h, "available": True, "raw_size": raw_size,
           "n_rows_raw": n_raw, "n_rows_sub": n_sub, "members": members, "skipped_members": skipped}
    rec_path.write_text(json.dumps(rec, indent=1))
    return name, f"ok {len(members)} files {n_raw}->{n_sub}"


def run(kind, workers):
    files = tlc_files() if kind == "tlc" else bb_files()
    fn = do_tlc if kind == "tlc" else do_bb
    (CAT / kind).mkdir(parents=True, exist_ok=True)
    log = open(LOGS / f"ingest_{kind}.log", "a", encoding="utf-8")
    # biggest first for better packing
    with cf.ProcessPoolExecutor(workers) as ex:
        futs = {ex.submit(fn, f): f for f in files}
        for fu in cf.as_completed(futs):
            try:
                n, msg = fu.result()
            except Exception as e:
                n, msg = futs[fu], f"ERROR {type(e).__name__}: {e}"
            print(time.strftime("%H:%M:%S"), n, msg, file=log, flush=True)


if __name__ == "__main__":
    kind = sys.argv[1]
    w = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    if kind == "head":
        out = {}
        for f in tlc_files():
            out[TLC_BASE + f] = head(TLC_BASE + f)
        for f in bb_files():
            out[BB_BASE + f] = head(BB_BASE + f)
        (ROOT / "catalog" / "http_heads.json").write_text(json.dumps(out, indent=1))
        print(sum(1 for v in out.values() if v["status"] == "200"), "of", len(out), "available")
    else:
        run(kind, w)
