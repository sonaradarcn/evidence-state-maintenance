"""Generate the statistics part of MANIFEST.md (written to manifests/stats.md and spliced into MANIFEST.md between
the markers <!-- STATS:BEGIN --> / <!-- STATS:END -->).  Every number here is computed from the catalogue, the
snapshot files and the facts files -- nothing is typed by hand."""
import json, re
from collections import Counter, defaultdict
from pathlib import Path

from ingest import CAT, ROOT, STORE

HERE = Path(__file__).parent


def human(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"


def dir_size(p):
    return sum(f.stat().st_size for f in Path(p).rglob("*") if f.is_file())


def tlc_tables(out):
    recs = [json.loads(f.read_text()) for f in sorted((CAT / "tlc").glob("*.json"))]
    by = defaultdict(list)
    for r in recs:
        by[r["name"].split("_tripdata_")[0]].append(r)
    out.append("### TLC source files\n")
    out.append("| dataset | months requested | available | not available | raw bytes | raw rows | kept rows (1/64) | stored bytes | schema identical after subsampling |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    tot = Counter()
    for ds in ("yellow", "green", "fhv", "fhvhv"):
        rs = sorted(by[ds], key=lambda r: r["name"])
        av = [r for r in rs if r.get("available")]
        na = [r["name"] for r in rs if not r.get("available")]
        rb = sum(r["http"]["content_length"] for r in av)
        rr = sum(r["n_rows_raw"] for r in av)
        kr = sum(r["n_rows_sub"] for r in av)
        sb = sum(r["size"] for r in av)
        eq = sum(1 for r in av if r["schema_equal"])
        tot.update({"raw": rb, "rows": rr, "kept": kr, "stored": sb})
        out.append(f"| {ds} | {rs[0]['name'][-15:-8]} .. {rs[-1]['name'][-15:-8]} ({len(rs)}) | {len(av)} | {', '.join(n[-15:-8] for n in na) or '-'} | {human(rb)} | {rr:,} | {kr:,} ({kr / max(rr, 1):.3%}) | {human(sb)} | {eq}/{len(av)} |")
    out.append(f"| **total** | | | | {human(tot['raw'])} | {tot['rows']:,} | {tot['kept']:,} | {human(tot['stored'])} | |\n")
    # republish evidence from Last-Modified
    out.append("**Real republication evidence (HTTP Last-Modified of the current originals).** A file whose Last-Modified is "
               "later than ~3 months after the end of its data month has been (re)published after the nominal release; "
               "the earlier versions are not obtainable, so only the current version is in the lake.\n")
    lm = Counter()
    for r in recs:
        if r.get("available"):
            lm[r["http"]["last_modified"][5:16]] += 1
    out.append("| Last-Modified date | # files |\n|---|---|")
    for d, n in sorted(lm.items(), key=lambda x: -x[1])[:12]:
        out.append(f"| {d} | {n} |")
    out.append("")
    # schema timeline
    out.append("### TLC schema-change timeline (real, from the Parquet footers of consecutive monthly files)\n")
    out.append("| dataset | first month with the change | added | removed | type changes |\n|---|---|---|---|---|")
    for ds in ("yellow", "green", "fhv", "fhvhv"):
        prev = None
        for r in sorted([r for r in by[ds] if r.get("available")], key=lambda r: r["name"]):
            s = r["schema"]
            if prev is not None:
                pn, cn = dict(prev), dict(s)
                add = [c for c in cn if c not in pn]
                rem = [c for c in pn if c not in cn]
                ty = [f"{c}: {pn[c]}→{cn[c]}" for c in cn if c in pn and pn[c] != cn[c]]
                if add or rem or ty:
                    out.append(f"| {ds} | {r['name'][-15:-8]} | {', '.join(add) or '-'} | {', '.join(rem) or '-'} | {'; '.join(ty) or '-'} |")
            prev = s
    out.append("")


def bb_tables(out):
    recs = [json.loads(f.read_text()) for f in sorted((CAT / "bb").glob("*.json"))]
    av = [r for r in recs if r.get("available")]
    na = [r["name"] for r in recs if not r.get("available")]
    out.append("### Backblaze source files\n")
    rb = sum(r["http"]["content_length"] for r in av)
    rr = sum(r["n_rows_raw"] for r in av)
    kr = sum(r["n_rows_sub"] for r in av)
    nfiles = sum(1 for r in av for m in r["members"] if m["logical_path"].endswith(".csv"))
    sb = sum(m["size"] for r in av for m in r["members"])
    skipped = sum(len(r["skipped_members"]) for r in av)
    empty = [m["logical_path"] for r in av for m in r["members"] if m.get("n_rows_raw") == 0]
    out.append(f"| zips requested | available | not available | raw zip bytes | daily CSVs | raw rows (drive-days) | kept rows (1/64 of drives) | stored bytes |")
    out.append("|---|---|---|---|---|---|---|---|")
    out.append(f"| {len(recs)} ({recs[0]['name']} .. ) | {len(av)} | {', '.join(na) or '-'} | {human(rb)} | {nfiles} | {rr:,} | {kr:,} ({kr / max(rr, 1):.3%}) | {human(sb)} |\n")
    out.append(f"Skipped zip members (macOS resource forks `__MACOSX/`, dot-files): {skipped}. "
               f"Real header-only daily files (0 data rows in the original): {len(empty)} ({', '.join(Path(e).stem for e in empty[:8])}{' …' if len(empty) > 8 else ''}).\n")
    # header timeline
    out.append("### Backblaze schema-change timeline (real, from the CSV headers of consecutive daily files)\n")
    out.append("| first day | #columns | added | removed |\n|---|---|---|---|")
    days = []
    for r in av:
        for m in r["members"]:
            if m["logical_path"].endswith(".csv") and re.search(r"\d{4}-\d{2}-\d{2}\.csv$", m["logical_path"]):
                days.append((Path(m["logical_path"]).stem, m))
    days.sort(key=lambda x: x[0])
    prev = None
    layouts = Counter()
    for d, m in days:
        layouts[str(Path(m["logical_path"]).parent)] += 0
        p = STORE / m["sha256"][:2] / (m["sha256"] + ".csv")
        with open(p, "rb") as fh:
            hdr = fh.read(30000).replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n")[0].decode()
        cols = [c.strip() for c in hdr.split(",")]
        if prev is None:
            out.append(f"| {d} | {len(cols)} | (initial) | |")
        elif cols != prev:
            add = [c for c in cols if c not in prev]
            rem = [c for c in prev if c not in cols]
            if add or rem:
                out.append(f"| {d} | {len(cols)} | {', '.join(add)} | {', '.join(rem) or '-'} |")
            else:
                out.append(f"| {d} | {len(cols)} | (column order changed) | |")
        prev = cols
    dirs = sorted({str(Path(m['logical_path']).parent).replace(chr(92), '/') for _, m in days})
    out.append(f"\nReal directory layouts inside the zips (kept as-is under `drive_stats/`): {len(dirs)} distinct directories, e.g. "
               f"{', '.join(dirs[:3])} … {', '.join(dirs[-2:])}.\n")


def events_tables(out, lake):
    d = json.loads((ROOT / "snapshots" / f"{lake}.json").read_text())
    ev = d["events"]
    out.append(f"### Snapshot sequence: {lake}\n")
    out.append(f"* snapshots (events): **{d['n_snapshots']}**; s0 = `{d['s0_snap']}` (index {d['s0_index']}, {d['s0_time']}); "
               f"HISTORY = {d['n_history']} snapshots (from index {d['history_start_index']}, {ev[d['history_start_index']]['time']}); "
               f"FUTURE = {d['n_future']} snapshots (to {ev[-1]['time']}).")
    kinds = Counter((e["kind"], bool(e.get("synthetic"))) for e in ev)
    out.append("* events by kind: " + ", ".join(f"{k}{' (SYNTHETIC)' if s else ''}: {n}" for (k, s), n in sorted(kinds.items())))
    nsyn = sum(1 for e in ev if e.get("synthetic"))
    out.append(f"* synthetic events: {nsyn} of {len(ev)} ({nsyn / len(ev):.1%}); every one is flagged `synthetic: true` in the event list.\n")
    out.append("| idx | time | kind | real/synthetic | phase | files | note |\n|---|---|---|---|---|---|---|")
    for e in ev:
        if e["kind"] == "arrive" and not e.get("synthetic") and not e.get("synthetic_part"):
            continue
        ph = "HISTORY" if d["history_start_index"] <= e["idx"] < d["s0_index"] else ("s0" if e["idx"] == d["s0_index"] else (
            "FUTURE" if e["idx"] > d["s0_index"] else "pre-window"))
        files = sorted(e.get("put", {}))
        fs = ", ".join(files[:2]) + (f" (+{len(files) - 2})" if len(files) > 2 else "")
        if e.get("remove"):
            fs += f"; removed {len(e['remove'])}"
        out.append(f"| {e['idx']} | {e['time'][:10]} | {e['kind']} | {'SYNTHETIC' if e.get('synthetic') or e.get('synthetic_part') else 'real'} | {ph} | {fs} | {e.get('note', '')[:120]} |")
    out.append("")


def facts_tables(out, lake):
    p = HERE / f"facts_{lake}.json"
    if not p.exists():
        out.append(f"(facts_{lake}.json not built)\n")
        return
    d = json.loads(p.read_text())
    fs = d["facts"]
    out.append(f"### Facts: {lake} ({len(fs)} facts; s0 = {d['s0']}, FUTURE = {d['n_future']} snapshots)\n")
    out.append("Base rate = fraction of facts whose oracle value differs from K (the s0 value) in at least one FUTURE snapshot; "
               "pair rate = fraction of (fact, FUTURE snapshot) pairs in which the value differs from K.\n")
    out.append("| type | candidates at s0 | pool evaluated | **pool base rate** | pool pair rate | natural n | natural base rate | natural pair rate | enriched n (of which unchanged fill-ins) | enriched base rate |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    nf = d["n_future"]
    for t, s in d["stats"].items():
        nat = [f for f in fs if f["type"] == t and f["subset"] == "natural"]
        pr = sum(f["n_future_changed"] for f in nat) / max(1, len(nat) * nf)
        out.append(f"| {t} | {s['n_candidates']} | {s['pool']} | {s['pool_frac_changing']:.3f} | {s['pool_frac_invalid_pairs']:.3f} | "
                   f"{s['natural_n']} | {s['natural_frac_changing']:.3f} | {pr:.3f} | {s['enriched_n']} ({s.get('enriched_fill_n', 0)}) | {s['enriched_frac_changing']:.3f} |")
    nat = [f for f in fs if f["subset"] == "natural"]
    out.append(f"| **all** | | | | | {len(nat)} | {sum(1 for f in nat if f['n_future_changed'] > 0) / max(1, len(nat)):.3f} | "
               f"{sum(f['n_future_changed'] for f in nat) / max(1, len(nat) * nf):.3f} | {len(fs) - len(nat)} | "
               f"{sum(1 for f in fs if f['subset'] != 'natural' and f['n_future_changed'] > 0) / max(1, len(fs) - len(nat)):.3f} |\n")


def main():
    out = ["<!-- generated by make_manifest.py -->\n", "## Generated statistics\n"]
    tlc_tables(out)
    bb_tables(out)
    for lake in ("tlc", "bb"):
        events_tables(out, lake)
    for lake in ("tlc", "bb"):
        facts_tables(out, lake)
    st = dir_size(STORE)
    out.append(f"### Storage\n\n* content-addressed store: {human(st)} ({sum(1 for _ in STORE.rglob('*.*'))} blobs)")
    out.append(f"* whole `datalake_data` directory: {human(dir_size(ROOT))}\n")
    txt = "\n".join(out)
    (HERE / "manifests").mkdir(exist_ok=True)
    (HERE / "manifests" / "stats.md").write_text(txt, encoding="utf-8")
    m = HERE / "MANIFEST.md"
    if m.exists():
        s = m.read_text(encoding="utf-8")
        s = re.sub(r"<!-- STATS:BEGIN -->.*<!-- STATS:END -->", lambda _: "<!-- STATS:BEGIN -->\n" + txt + "\n<!-- STATS:END -->", s, flags=re.S)
        m.write_text(s, encoding="utf-8")
    print(txt[:3000])


if __name__ == "__main__":
    main()
