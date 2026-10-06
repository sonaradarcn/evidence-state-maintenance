"""Re-subsample Backblaze daily files that the first ingest pass mis-split (bare '\r' line endings: the whole file was
read as one header line, so the stored blob is the FULL original file).  Applies the same 1/64 serial rule."""
import json
from ingest import CAT, STORE, put, keep_serial

for f in sorted((CAT / "bb").glob("*.json")):
    r = json.loads(f.read_text())
    changed = False
    for m in r.get("members", []):
        if m.get("n_cols", 0) > 1000:
            src = STORE / m["sha256"][:2] / (m["sha256"] + ".csv")
            text = src.read_bytes().decode("utf-8", "replace")
            lines = [l for l in text.split("\r") if l]
            cols = [c.strip() for c in lines[0].split(",")]
            si = cols.index("serial_number")
            out = [lines[0]] + [l for l in lines[1:] if keep_serial(l.split(",", si + 1)[si])]
            sha, size = put(("\r".join(out) + "\r").encode("utf-8"), ".csv")
            print(m["logical_path"], "rows", len(lines) - 1, "->", len(out) - 1, "cols", len(cols))
            m.update({"sha256": sha, "size": size, "n_rows_raw": len(lines) - 1, "n_rows_sub": len(out) - 1,
                      "n_cols": len(cols), "note": "bare CR line endings in the original; re-subsampled by fix_cr_files.py"})
            r["n_rows_raw"] += len(lines) - 1
            r["n_rows_sub"] += len(out) - 1
            src.unlink()
            changed = True
    if changed:
        f.write_text(json.dumps(r, indent=1))
