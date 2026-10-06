"""Tiny persistent job queue: runs the commands listed in <queue>.txt one after another (one line = one shell command,
'#' comments ignored).  Lines can be appended while the queue runs.  Finished lines are recorded in <queue>.done
(exit code, duration); each job's output goes to <queue>.<n>.log.  The queue exits when it has run every line and no
new line appeared for --idle seconds.
usage: python -m esm.scripts.jobqueue <queue-file-without-ext> [--idle 60]"""
import subprocess, sys, time, json
from pathlib import Path

q = Path(sys.argv[1])
idle = int(sys.argv[sys.argv.index("--idle") + 1]) if "--idle" in sys.argv else 60
txt, done = q.with_suffix(".txt"), q.with_suffix(".done")
last_new = time.time()
while True:
    lines = [l.strip() for l in txt.read_text(encoding="utf-8").splitlines()] if txt.exists() else []
    jobs = [l for l in lines if l and not l.startswith("#")]
    fin = [json.loads(l) for l in done.read_text(encoding="utf-8").splitlines() if l.strip()] if done.exists() else []
    n = len(fin)
    if n < len(jobs):
        cmd = jobs[n]
        log = q.parent / f"{q.name}.{n}.log"
        t0 = time.time()
        print(f"[{time.strftime('%H:%M:%S')}] start #{n}: {cmd}", flush=True)
        with open(log, "w", encoding="utf-8") as fh:
            rc = subprocess.call(cmd, shell=True, stdout=fh, stderr=subprocess.STDOUT)
        rec = {"n": n, "cmd": cmd, "rc": rc, "secs": round(time.time() - t0), "end": time.strftime("%Y-%m-%d %H:%M:%S")}
        with open(done, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        print(f"[{time.strftime('%H:%M:%S')}] done #{n} rc={rc} {rec['secs']}s", flush=True)
        last_new = time.time()
        continue
    if time.time() - last_new > idle:
        print("queue empty, exiting", flush=True)
        break
    time.sleep(10)
