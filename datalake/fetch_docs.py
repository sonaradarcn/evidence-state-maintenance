"""Fetch REAL historical versions of lake documentation and lookup tables (Wayback Machine + current originals).

Each version becomes a file version in the content-addressed store; its arrival time is the earliest Wayback capture
of that content (or HTTP Last-Modified for the current original).  Output: catalog/docs/docs.json
PDF dictionaries are converted to text with pypdf (the text file is what read_text() serves; the PDF itself is not kept).
"""
import gzip, html, json, re, subprocess, time
from html.parser import HTMLParser
from pathlib import Path
import io

from ingest import put, CAT


def head(url):
    r = subprocess.run(["curl", "-sI", "-m", "30", "-A", UA, url], capture_output=True, text=True)
    h = {}
    for line in r.stdout.splitlines()[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            h[k.strip().lower()] = v.strip()
    return {"last_modified": h.get("last-modified")}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


BLOCK_MARK = b"flagged it as suspected abusive bot traffic"


_CACHE_DIR = CAT.parent / "raw" / "docs"


def curl(url, binary=True, valid=None):
    """Polite fetch: >= 8 s between Wayback requests, exponential back-off when blocked or invalid.
    Successful Wayback responses are cached on disk (raw/docs) so re-runs do not hit the archive again."""
    import hashlib as _h
    wb = "web.archive.org" in url
    cp = _CACHE_DIR / _h.sha1(url.encode()).hexdigest()
    if wb and cp.exists():
        return cp.read_bytes()
    delay = 120
    for _ in range(4):
        if wb:
            time.sleep(10)
        # NB: the Wayback Machine flags the truncated browser UA string as a bot; curl's default UA is accepted there,
        # while nyc.gov needs a browser-like UA.
        ua = [] if wb else ["-A", UA]
        r = subprocess.run(["curl", "-s", "-L", "-m", "120", *ua, url], capture_output=True)
        b = r.stdout
        if r.returncode == 0 and b and BLOCK_MARK not in b[:3000]:
            bb = maybe_gunzip(b)
            if valid is None or valid(bb):
                if wb:
                    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    cp.write_bytes(b)
                return b
        print("  retry", url[:100], "blocked" if BLOCK_MARK in (b or b"")[:3000] else "invalid", flush=True)
        time.sleep(delay)
        delay *= 2
    raise RuntimeError(url)


def cdx(url):
    q = f"https://web.archive.org/cdx/search/cdx?url={url}&output=json&fl=timestamp,digest,statuscode,original&collapse=digest&filter=statuscode:200"
    rows = json.loads(curl(q, valid=lambda x: x.strip().startswith(b"[")))
    return rows[1:]


def maybe_gunzip(b):
    return gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b


def pdf_text(b):
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(b))
    return "\n".join((p.extract_text() or "") for p in r.pages)


class _TextHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg", "head"):
            self.skip += 1
        if tag in ("p", "br", "li", "tr", "h1", "h2", "h3", "h4", "div", "td", "th"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg", "head") and self.skip:
            self.skip -= 1

    def handle_data(self, d):
        if not self.skip:
            self.out.append(d)


def html_text(b):
    p = _TextHTML()
    p.feed(b.decode("utf-8", "replace"))
    t = "".join(p.out)
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n\n", t)
    return t.strip() + "\n"


def wb_ts_iso(ts):
    return f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}T{ts[8:10]}:{ts[10:12]}:{ts[12:14]}Z"


def main():
    out = []
    # ---- TLC data dictionaries
    for kind in ("yellow", "green", "fhv", "hvfhs"):
        orig = f"https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_{kind}.pdf"
        logical = f"docs/data_dictionary_trip_records_{kind}.txt"
        seen = set()
        vers = []
        for ts, dg, st, o in cdx(f"nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_{kind}.pdf"):
            try:
                b = maybe_gunzip(curl(f"https://web.archive.org/web/{ts}id_/{o}", valid=lambda x: x.startswith(b"%PDF")))
            except RuntimeError:
                print("  SKIP (not obtainable)", kind, ts)
                continue
            txt = pdf_text(b)
            vers.append((wb_ts_iso(ts), txt, f"wayback:{ts}"))
        h = head(orig)
        b = curl(orig, valid=lambda x: x.startswith(b"%PDF"))
        txt = pdf_text(b)
        lm = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.strptime(h["last_modified"], "%a, %d %b %Y %H:%M:%S GMT"))
        vers.append((lm, txt, "origin:last-modified"))
        for when, txt, src in sorted(vers):
            norm = re.sub(r"\s+", " ", txt).strip()
            if norm in seen:
                continue
            seen.add(norm)
            sha, size = put(txt.encode("utf-8"), ".txt")
            out.append({"lake": "tlc", "logical_path": logical, "sha256": sha, "size": size, "arrival": when,
                        "source": src, "url": orig, "real": True})
    # ---- TLC taxi zone lookup (two real versions)
    zl = "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv"
    old = maybe_gunzip(curl("https://web.archive.org/web/20200904194253id_/https://s3.amazonaws.com/nyc-tlc/misc/taxi+_zone_lookup.csv", valid=lambda x: x.count(b"\n") > 200 and x.startswith(b'"LocationID"')))
    sha, size = put(old, ".csv")
    out.append({"lake": "tlc", "logical_path": "misc/taxi_zone_lookup.csv", "sha256": sha, "size": size,
                "arrival": "2018-01-01T00:00:00Z", "source": "wayback:20200904194253 (s3 nyc-tlc misc/taxi+_zone_lookup.csv)",
                "url": zl, "real": True, "note": "earliest available version; present before the lake window starts"})
    h = head(zl)
    new = curl(zl)
    lm = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.strptime(h["last_modified"], "%a, %d %b %Y %H:%M:%S GMT"))
    sha, size = put(new, ".csv")
    out.append({"lake": "tlc", "logical_path": "misc/taxi_zone_lookup.csv", "sha256": sha, "size": size,
                "arrival": lm, "source": "origin:last-modified", "url": zl, "real": True})
    # ---- Backblaze Drive Stats documentation page: first capture of each year (old + new URL)
    caps = []
    for u in ("backblaze.com/b2/hard-drive-test-data.html", "backblaze.com/cloud-storage/resources/hard-drive-test-data"):
        try:
            caps += cdx(u)
        except Exception as e:
            print("cdx fail", u, e)
    caps.sort()
    by_year = {}
    for ts, dg, st, o in caps:
        by_year.setdefault(ts[:4], (ts, o))     # first capture of each year
    seen = set()
    for y, (ts, o) in sorted(by_year.items()):
        try:
            b = maybe_gunzip(curl(f"https://web.archive.org/web/{ts}id_/{o}", valid=lambda x: b"<html" in x[:5000].lower() or b"<!doctype" in x[:500].lower()))
        except Exception as e:
            print("fail", ts, e)
            continue
        txt = html_text(b)
        if len(txt) < 500 or txt in seen:
            continue
        seen.add(txt)
        sha, size = put(txt.encode("utf-8"), ".txt")
        out.append({"lake": "bb", "logical_path": "docs/hard-drive-test-data.txt", "sha256": sha, "size": size,
                    "arrival": wb_ts_iso(ts), "source": f"wayback:{ts}", "url": "https://" + o.split("://", 1)[-1],
                    "real": True, "note": "visible text of the Backblaze 'Hard Drive Data and Stats' page"})
    (CAT / "docs").mkdir(parents=True, exist_ok=True)
    (CAT / "docs" / "docs.json").write_text(json.dumps(out, indent=1))
    for r in out:
        print(r["lake"], r["logical_path"], r["arrival"], r["size"], r["source"])


if __name__ == "__main__":
    main()
