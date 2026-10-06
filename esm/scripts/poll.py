"""Blocking poll (no LLM): wait up to --max seconds, checking every --every seconds, until a condition holds; then print
a status snapshot.  Conditions: --file-exists P, --lines P N (file has >= N lines), --log-has P TEXT.
usage: python -m esm.scripts.poll --max 580 [--file-exists P] [--lines P N] [--log-has P TEXT]"""
import argparse, os, subprocess, sys, time

ap = argparse.ArgumentParser()
ap.add_argument("--max", type=int, default=580)
ap.add_argument("--every", type=int, default=20)
ap.add_argument("--file-exists", default=None)
ap.add_argument("--lines", nargs=2, default=None)
ap.add_argument("--log-has", nargs=2, default=None)
a = ap.parse_args()


def ok():
    if a.file_exists and os.path.exists(a.file_exists):
        return f"exists {a.file_exists}"
    if a.lines and os.path.exists(a.lines[0]):
        n = sum(1 for _ in open(a.lines[0], encoding="utf-8", errors="replace"))
        if n >= int(a.lines[1]):
            return f"{a.lines[0]} has {n} lines"
    if a.log_has and os.path.exists(a.log_has[0]):
        if a.log_has[1] in open(a.log_has[0], encoding="utf-8", errors="replace").read():
            return f"{a.log_has[0]} contains {a.log_has[1]!r}"
    return None


t0 = time.time()
r = None
while time.time() - t0 < a.max:
    r = ok()
    if r:
        break
    time.sleep(a.every)
print(f"[poll] {'condition met: ' + r if r else 'timeout'} after {time.time() - t0:.0f}s", flush=True)
subprocess.call([sys.executable, "-B", "-m", "esm.scripts.status"])
