"""Stage 4 arrival model: real GitHub issue arrivals mapped onto the 400 FUTURE commits of each held-out repository.

* Commit times: committer timestamps of s0 and the 400 FUTURE first-parent commits (cache/commit_times.parquet, from the
  held-out clones). A running maximum makes them monotone (one non-monotone pair, isort).
* OWN repos (encode/httpx, pallets/jinja, psf/black, networkx/networkx are among the 58 trace repos): every issue opened
  in (T_s0, T_400] in traces/events_github.parquet becomes a task at its real time; it reads the knowledge as of the
  last FUTURE commit at or before that time (t = 0 means "still at s0").
* PROXY repos (the other 12): a trace repo with a similar commit rate supplies BOTH the commit clock and the issue
  stream.  Proxy window = its 400 first-parent commits following its last commit at or before the held-out repo's
  T_s0 (calendar-aligned; if fewer than 400 follow, its last 401 commits).  Candidates = the 54 trace repos that are
  not one of the four OWN repos; similarity = |log(commit rate of that window / held-out FUTURE commit rate)|; each
  proxy is used once (greedy, held-out repos in increasing commit-rate order, best unused candidate).  The held-out
  repo's FUTURE commit i is identified with the proxy's i-th window commit; every proxy issue keeps its real time, so
  the timing and the interleaving are entirely the proxy's real ones and real-time statistics (stale windows) are
  measured on the proxy clock.  (An earlier variant that warped proxy issues onto the held-out commit clock was
  dropped: it assigns issues to gaps by the proxy's gap lengths, decoupling issue counts from the held-out gap
  lengths.)
* POISSON control: the same number of tasks, arrival times i.i.d. uniform on (T_s0, T_400] (a homogeneous Poisson
  process conditioned on its count), redrawn per seed.

usage: python -m esm.stream.arrivals  -> results/stream/arrivals.parquet, arrivals_meta.json
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "esm" / "results" / "stream"
CACHE = OUT / "cache"
USED, CLOCK = set(), {}
OWN = {"httpx": "encode/httpx", "jinja": "pallets/jinja", "black": "psf/black", "networkx": "networkx/networkx"}


def held_times():
    c = pd.read_parquet(CACHE / "commit_times.parquet")
    out = {}
    for r, g in c.groupby("repo"):
        ct = g.sort_values("t").ct.to_numpy(np.int64)
        out[r] = np.maximum.accumulate(ct).astype(float)      # seconds, index 0 = s0
    return out


def trace_events():
    ev = pd.read_parquet(ROOT / "data" / "events_github.parquet")
    ev["ts"] = ev.timestamp.astype("int64") // 10**9 if str(ev.timestamp.dtype).endswith("[ns, UTC]") else ev.timestamp.astype("int64")
    # pandas may store [ns]; normalise to seconds
    if ev.ts.max() > 1e12:
        ev["ts"] = ev.ts // 10**9
    W = {a: np.sort(g.ts.to_numpy(float)) for a, g in ev[ev.type == "W"].groupby("asset")}
    R = {a: np.sort(g.ts.to_numpy(float)) for a, g in ev[ev.type == "R"].groupby("asset")}
    return W, R


def proxy_window(Wp, T0):
    i0 = np.searchsorted(Wp, T0, side="right") - 1          # last proxy commit <= T0
    if i0 < 0 or i0 + 400 >= len(Wp):
        i0 = len(Wp) - 401
        aligned = False
    else:
        aligned = True
    return Wp[i0:i0 + 401], aligned


def build():
    T = held_times()
    W, R = trace_events()
    rows, meta = [], {}
    order = sorted(T, key=lambda r: 400 / (T[r][-1] - T[r][0]))
    for repo in order:
        Th = T[repo]
        CLOCK[repo] = Th
        rate_h = 400 / ((Th[-1] - Th[0]) / 86400)
        if repo in OWN:
            a = OWN[repo]
            iss = R[a][(R[a] > Th[0]) & (R[a] <= Th[-1])]
            t_idx = np.searchsorted(Th, iss, side="right") - 1
            times = iss
            meta[repo] = {"source": "own", "trace_asset": a, "rate_heldout_per_day": rate_h,
                          "trace_issue_last": float(R[a].max()), "window_end": float(Th[-1]),
                          "note": "issues after the trace fetch (2026-10-01) are missing" if R[a].max() < Th[-1] - 86400 else ""}
        else:
            best = None
            for a, Wp in W.items():
                if a in OWN.values() or a in USED or len(Wp) < 401:
                    continue
                win, aligned = proxy_window(Wp, Th[0])
                rp = 400 / max((win[-1] - win[0]) / 86400, 1e-9)
                d = abs(np.log(rp / rate_h))
                if best is None or d < best[0]:
                    best = (d, a, win, aligned, rp)
            d, a, win, aligned, rp = best
            USED.add(a)
            iss = R[a][(R[a] > win[0]) & (R[a] <= win[-1])]
            Th = np.maximum.accumulate(win)
            CLOCK[repo] = Th
            times = iss
            t_idx = np.searchsorted(Th, times, side="right") - 1
            meta[repo] = {"source": "proxy", "trace_asset": a, "rate_heldout_per_day": rate_h, "rate_proxy_per_day": rp,
                          "abs_log_rate_ratio": float(d), "calendar_aligned": bool(aligned),
                          "proxy_window": [str(pd.to_datetime(win[0], unit="s").date()), str(pd.to_datetime(win[-1], unit="s").date())]}
        t_idx = np.clip(t_idx, 0, 400)
        meta[repo].update({"n_issues": int(len(times)), "issues_per_commit": len(times) / 400,
                           "window": [str(pd.to_datetime(Th[0], unit="s").date()), str(pd.to_datetime(Th[-1], unit="s").date())],
                           "days": (Th[-1] - Th[0]) / 86400})
        for x, t in zip(times, t_idx):
            rows.append({"repo": repo, "time": float(x), "t": int(t)})
        # interleaving statistics of the real (mapped) stream
        s = np.sort(times)
        gaps = np.diff(s)
        cum = Th
        # fraction of tasks that arrive within 24 h after a commit; Poisson expectation by the same window
        last_commit = cum[np.clip(np.searchsorted(cum, s, side="right") - 1, 0, 400)]
        within = np.mean((s - last_commit) < 86400) if len(s) else np.nan
        meta[repo].update({"cv_interarrival": float(gaps.std() / gaps.mean()) if len(gaps) > 1 and gaps.mean() > 0 else None,
                           "frac_within_24h_after_commit": float(within),
                           "commits_with_task_before_next_commit": float(len(np.unique(t_idx)) / 401)})
    df = pd.DataFrame(rows)
    df.to_parquet(OUT / "arrivals.parquet", index=False)
    pd.DataFrame([{"repo": r, "t": i, "time": float(x)} for r, c in CLOCK.items() for i, x in enumerate(c)]).to_parquet(
        OUT / "clock.parquet", index=False)
    (OUT / "arrivals_meta.json").write_text(json.dumps(meta, indent=1))
    return df, meta


def poisson_times(repo_T, n, rng):
    return np.sort(rng.uniform(repo_T[0], repo_T[-1], n))


if __name__ == "__main__":
    df, meta = build()
    for r, m in meta.items():
        print(r, m["source"], m["trace_asset"], m["n_issues"], f"{m['rate_heldout_per_day']:.2f}", m.get("rate_proxy_per_day"),
              m.get("calendar_aligned"), m["frac_within_24h_after_commit"], m["cv_interarrival"])
