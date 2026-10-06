"""Re-create the subsampled lake store from the public sources.

The catalogue (data/datalake_catalog) holds, per source file, the raw sha256 / size and the sha256 of every
stored (subsampled) file.  This script re-downloads the sources, re-applies datalake/ingest.py's deterministic
subsampling (the same functions) and stores each file under its catalogued sha256 in esm_data_e2e_lake/lake_data/store.
Verification per file: Backblaze members must reproduce the catalogued sha256 byte for byte; TLC files must reproduce the
catalogued raw sha256 (same source bytes) and the catalogued subsampled row count / schema, and the sha256 of the
re-written Parquet file is compared with the catalogue (recorded in fetch_log.jsonl).

usage: python -m esm.e2e_lake.fetch_lake [--tlc-until 2024-03] [--bb-until 2024Q4] [--workers 6]
       ensure(sha) can also be imported to fetch a single missing blob on demand.
"""
import argparse, concurrent.futures as cf, hashlib, json, os, re, shutil, subprocess, sys, threading, time, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAT_SRC = ROOT / "data" / "datalake_catalog"
LD = ROOT / "esm_data_e2e_lake" / "lake_data"
STORE, RAW, CATD = LD / "store", LD / "raw", LD / "catalog"
LOG = LD / "fetch_log.jsonl"
sys.path.insert(0, str(ROOT / "datalake"))
import ingest as I  # noqa: E402

I.ROOT, I.RAW, I.STORE, I.CAT, I.LOGS = LD, RAW, STORE, CATD, LD / "logs"
_lock = threading.Lock()


def log(rec):
    with _lock:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": time.strftime("%H:%M:%S"), **rec}) + "\n")
    print(time.strftime("%H:%M:%S"), json.dumps(rec)[:240], flush=True)


def catalogue():
    tlc = [json.loads(p.read_text()) for p in sorted((CAT_SRC / "tlc").glob("*.json"))]
    bb = [json.loads(p.read_text()) for p in sorted((CAT_SRC / "bb").glob("*.json"))]
    return [r for r in tlc if r.get("available")], [r for r in bb if r.get("available")]


def blob(sha, ext):
    return STORE / sha[:2] / f"{sha}{ext}"


def seg_download(url, dest, size, nseg=6):
    """Parallel HTTP range download (curl per segment), resumable; verifies the total size."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size == size:
        return
    step = -(-size // nseg)
    parts = []

    def one(i):
        a, b = i * step, min(size, (i + 1) * step) - 1
        p = dest.with_name(dest.name + f".part{i}")
        for attempt in range(40):
            have = p.stat().st_size if p.exists() else 0
            if have == b - a + 1:
                return p
            if have > b - a + 1:
                p.unlink(); have = 0
            subprocess.run(["curl", "-s", "-f", "-L", "-r", f"{a + have}-{b}", "--retry", "5", "--retry-delay", "5", "-m", "3600",
                            "--speed-limit", "20000", "--speed-time", "60", "-o", str(p) + ".cur", url])
            cur = Path(str(p) + ".cur")
            if cur.exists():
                with open(p, "ab") as fo, open(cur, "rb") as fi:
                    shutil.copyfileobj(fi, fo)
                cur.unlink()
            time.sleep(1)
        raise RuntimeError(f"segment {i} failed {url}")

    with cf.ThreadPoolExecutor(nseg) as ex:
        parts = list(ex.map(one, range(nseg)))
    with open(dest, "wb") as fo:
        for p in parts:
            with open(p, "rb") as fi:
                shutil.copyfileobj(fi, fo)
    for p in parts:
        p.unlink()
    if dest.stat().st_size != size:
        dest.unlink()
        raise RuntimeError(f"size mismatch {url}")


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def do_tlc(r, nseg=6):
    dst = blob(r["sha256"], ".parquet")
    if dst.exists():
        return "have"
    raw = RAW / "tlc" / r["name"]
    t0 = time.time()
    seg_download(r["url"], raw, r["http"]["content_length"], nseg)
    t_dl = time.time() - t0
    raw_sha = sha_file(raw)
    tmp = RAW / "tlc" / (r["name"] + ".sub")
    info = I.tlc_subsample(raw, tmp)
    new_sha = sha_file(tmp)
    ok_rows = info["n_rows_sub"] == r["n_rows_sub"]
    ok_schema = [tuple(x) for x in info["schema"]] == [tuple(x) for x in r["schema"]]
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():                              # fetched meanwhile by another process
        tmp.unlink()
    else:
        os.replace(tmp, dst)                      # stored under the CATALOGUED sha (content-equal re-encoding if it differs)
    raw.unlink()
    log({"lake": "tlc", "file": r["name"], "raw_sha_ok": raw_sha == r["raw_sha256"], "sub_sha_ok": new_sha == r["sha256"],
         "rows_ok": ok_rows, "schema_ok": ok_schema, "n_rows_sub": info["n_rows_sub"], "dl_s": round(t_dl),
         "mb": round(r["http"]["content_length"] / 1e6)})
    return "ok"


def do_bb(r, nseg=6):
    need = [m for m in r["members"] if not blob(m["sha256"], Path(m["logical_path"]).suffix or ".bin").exists()]
    if not need:
        return "have"
    raw = RAW / "bb" / r["name"]
    t0 = time.time()
    seg_download(r["url"], raw, r["raw_size"], nseg)
    t_dl = time.time() - t0
    want = {m["logical_path"]: m for m in r["members"]}
    stem = r["name"][:-4]
    n_ok = n_bad = 0
    bad = []
    with zipfile.ZipFile(raw) as z:
        for zi in z.infolist():
            mn = zi.filename
            if zi.is_dir() or mn.startswith("__MACOSX/") or "/." in mn or mn.startswith("."):
                continue
            logical = "drive_stats/" + (mn if "/" in mn else f"{stem}/{mn}")
            m = want.get(logical)
            if m is None:
                continue
            data = z.read(zi)
            if mn.lower().endswith(".csv"):
                text = data.decode("utf-8", "replace")
                head5k = text[:5000]
                nl = "\r\n" if "\r\n" in head5k else ("\n" if "\n" in head5k else ("\r" if "\r" in head5k else "\n"))
                lines = text.split(nl)
                hdr = lines[0]
                cols = [c.strip() for c in hdr.split(",")]
                si = cols.index("serial_number")
                out = [hdr]
                for line in lines[1:]:
                    if not line:
                        continue
                    parts = line.split(",", si + 1)
                    if len(parts) > si and I.keep_serial(parts[si]):
                        out.append(line)
                body = (nl.join(out) + nl).encode("utf-8")
            else:
                body = data
            s = hashlib.sha256(body).hexdigest()
            if s == m["sha256"]:
                n_ok += 1
            else:
                n_bad += 1
                bad.append(logical)
            dst = blob(m["sha256"], Path(logical).suffix or ".bin")
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_suffix(dst.suffix + ".tmp")
            tmp.write_bytes(body)
            os.replace(tmp, dst)
    raw.unlink()
    log({"lake": "bb", "file": r["name"], "members_sha_ok": n_ok, "members_sha_bad": n_bad, "bad": bad[:5],
         "dl_s": round(t_dl), "mb": round(r["raw_size"] / 1e6)})
    return "ok"


def tlc_month(r):
    return re.search(r"(\d{4}-\d{2})", r["name"]).group(1)


def bb_key(r):
    m = re.match(r"data_(?:Q(\d)_)?(\d{4})\.zip", r["name"])
    return (int(m.group(2)), int(m.group(1) or 4))


# ---------------------------------------------------------------- on-demand
_SHA_SRC = None
_ensure_lock = threading.Lock()


def _index():
    global _SHA_SRC
    if _SHA_SRC is None:
        tlc, bb = catalogue()
        d = {}
        for r in tlc:
            d[r["sha256"]] = ("tlc", r)
        for r in bb:
            for m in r["members"]:
                d[m["sha256"]] = ("bb", r)
        _SHA_SRC = d
    return _SHA_SRC


def ensure(sha):
    """Fetch the source holding blob `sha` if it is missing (blocking).  Returns True if it was fetched now."""
    src = _index().get(sha)
    if src is None:
        return False
    with _ensure_lock:
        kind, r = src
        log({"on_demand": sha[:12], "src": r["name"]})
        (do_tlc if kind == "tlc" else do_bb)(r, nseg=8)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tlc-until", default="2024-03")
    ap.add_argument("--bb-until", default="2024Q4")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--only", default="tlc,bb")
    ap.add_argument("--skip-fhvhv", action="store_true")
    a = ap.parse_args()
    (RAW / "tlc").mkdir(parents=True, exist_ok=True)
    (RAW / "bb").mkdir(parents=True, exist_ok=True)
    tlc, bb = catalogue()
    by, bq = int(a.bb_until[:4]), int(a.bb_until[-1])
    jobs = []
    if "tlc" in a.only:
        sel = [r for r in tlc if tlc_month(r) <= a.tlc_until and not (a.skip_fhvhv and r["name"].startswith("fhvhv"))]
        # small datasets first, then fhvhv newest first (latest files are what agents look at most)
        sel.sort(key=lambda r: (r["name"].startswith("fhvhv"), "" if not r["name"].startswith("fhvhv") else
                                "".join(chr(255 - ord(c)) for c in tlc_month(r))))
        jobs += [("tlc", r) for r in sel]
    if "bb" in a.only:
        sel = sorted([r for r in bb if bb_key(r) <= (by, bq)], key=bb_key, reverse=True)
        jobs += [("bb", r) for r in sel]
    print(len(jobs), "sources;", sum((r["http"]["content_length"] if k == "tlc" else r["raw_size"]) for k, r in jobs) / 1e9,
          "GB", flush=True)
    # interleave lakes (different hosts) so both links are busy
    tl = [j for j in jobs if j[0] == "tlc"]
    bl = [j for j in jobs if j[0] == "bb"]
    order = []
    while tl or bl:
        if tl:
            order.append(tl.pop(0))
        if bl:
            order.append(bl.pop(0))
    with cf.ProcessPoolExecutor(a.workers) as ex:     # BB subsampling is pure Python (GIL-bound): processes
        futs = {ex.submit(do_tlc if k == "tlc" else do_bb, r): r["name"] for k, r in order}
        for fu in cf.as_completed(futs):
            try:
                fu.result()
            except Exception as e:
                log({"error": futs[fu], "msg": repr(e)[:300]})
    log({"done": True})


if __name__ == "__main__":
    main()
