"""Create the fixed dependency directories used when behaviour facts are executed (heldout_data/deps/<repo>).

    python heldout/setup_deps.py [--out DIR]

Each directory is put on PYTHONPATH after the checkout, identically for every commit (see README.md, "Fixed
dependencies"). It also holds a stub `<dist>-0+heldout.dist-info/METADATA`, because recent jinja and isort call
importlib.metadata.version() on their own distribution at import time.
"""
import argparse, os, shutil, subprocess, sys, tarfile, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = {"boltons": "boltons", "jinja": "Jinja2", "werkzeug": "Werkzeug", "marshmallow": "marshmallow", "isort": "isort",
        "pygments": "Pygments", "networkx": "networkx", "rich": "rich", "poetry-core": "poetry-core"}
PIP = {"werkzeug": ["markupsafe==3.0.3"], "marshmallow": ["packaging==26.3"], "isort": ["mypy_extensions==1.1.0"],
       "rich": ["Pygments==2.21.0", "markdown-it-py==4.2.0", "mdurl==0.1.2"]}


def pip_target(pkgs, target):
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--no-deps", "--target", str(target), *pkgs], check=True)


def markupsafe_201(target):
    # jinja's s0 (2018) imports markupsafe.soft_unicode, removed in 2.1; only the pure-Python package is used.
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([sys.executable, "-m", "pip", "download", "--quiet", "--no-deps", "--no-binary", ":all:",
                        "-d", tmp, "MarkupSafe==2.0.1"], check=True)
        with tarfile.open(next(Path(tmp).glob("MarkupSafe-2.0.1.tar.gz"))) as tf:
            tf.extractall(tmp, filter="data")
        src = Path(tmp) / "MarkupSafe-2.0.1" / "src" / "markupsafe"
        dst = target / "markupsafe"
        dst.mkdir(parents=True, exist_ok=True)
        for name in ("__init__.py", "_native.py", "_speedups.pyi", "py.typed"):
            shutil.copy2(src / name, dst / name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(os.environ.get("ESM_HELDOUT_DATA", ROOT / "heldout_data")) / "deps"))
    out = Path(ap.parse_args().out)
    for repo, dist in DIST.items():
        d = out / repo
        d.mkdir(parents=True, exist_ok=True)
        if repo in PIP:
            pip_target(PIP[repo], d)
        if repo == "jinja":
            markupsafe_201(d)
        meta = d / f"{dist}-0+heldout.dist-info"
        meta.mkdir(exist_ok=True)
        (meta / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {dist}\nVersion: 0+heldout\n", encoding="utf-8")
        print(repo, sorted(p.name for p in d.iterdir()))


if __name__ == "__main__":
    main()
