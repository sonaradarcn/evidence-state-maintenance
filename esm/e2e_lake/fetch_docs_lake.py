"""Re-fetch the lake documentation / lookup versions (datalake/fetch_docs.py, unchanged logic) into the e2e store and
compare their sha256 with the archived catalogue.  usage: python -m esm.e2e_lake.fetch_docs_lake"""
import json, sys
from esm.e2e_lake import fetch_lake as FL
sys.path.insert(0, str(FL.ROOT / "datalake"))
import fetch_docs as FD  # noqa: E402
FD.CAT = FL.CATD
FD._CACHE_DIR = FL.RAW / "docs"
FD.main()
new = json.loads((FL.CATD / "docs" / "docs.json").read_text())
old = json.loads((FL.CAT_SRC / "docs" / "docs.json").read_text())
ns = {r["sha256"] for r in new}
for r in old:
    print("OK " if r["sha256"] in ns else "MISSING", r["logical_path"], r["arrival"], r["source"])
