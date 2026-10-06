"""Subprocess runner for held-out behaviour facts (python -S -B, PYTHONPATH = materialised package state [+ fixed deps]).

Value semantics are IDENTICAL to pilot6/runner_exec.py: value = canonical repr | 'raises <Type>' | 'NONE' (module import fails or
the called attribute is missing) | 'TIMEOUT'.  Jobs: JSON list [{id, module, func, expr, timeout?}] on stdin; JSON {id: value} out.

Probe mode (argv[1] == 'probe', used only when generating candidates at s0): each expression is evaluated TWICE in this process;
the output per job is {v, v2, iter, literal, t} (iter: result has __next__ / is a generator; literal: repr is ast.literal_eval-able;
t: seconds for the first evaluation)."""
import ast, importlib, io, json, sys, threading, os, time


def canon_repr(v):
    if isinstance(v, (set, frozenset)):
        try:
            return "{" + ", ".join(canon_repr(x) for x in sorted(v, key=repr)) + "}" if v else ("set()" if isinstance(v, set) else "frozenset()")
        except Exception:
            return repr(v)
    return repr(v)


def _eval(job, res, probe):
    mod = job["module"]
    try:
        m = importlib.import_module(mod)
    except BaseException as e:
        res["v"] = "NONE"
        res["why"] = f"import {type(e).__name__}"
        return
    ns = {}
    try:
        exec(f"import {mod}", ns)
    except BaseException:
        res["v"] = "NONE"
        return
    if job.get("func"):
        if not hasattr(m, job["func"]):
            res["v"] = "NONE"
            res["why"] = "attr missing"
            return
    t = time.perf_counter()
    try:
        v = eval(job["expr"], ns)
        res["v"] = canon_repr(v)[:2000]
        if probe:
            res["iter"] = hasattr(v, "__next__") or type(v).__name__ in ("generator", "map", "filter", "zip")
            try:
                ast.literal_eval(res["v"])
                res["literal"] = True
            except Exception:
                res["literal"] = False
    except AttributeError:
        res["v"] = "raises AttributeError"
    except Exception as e:
        res["v"] = f"raises {type(e).__name__}"
    res["t"] = time.perf_counter() - t
    if probe:
        try:
            v2 = eval(job["expr"], ns)
            res["v2"] = canon_repr(v2)[:2000]
        except AttributeError:
            res["v2"] = "raises AttributeError"
        except Exception as e:
            res["v2"] = f"raises {type(e).__name__}"


def main():
    probe = len(sys.argv) > 1 and sys.argv[1] == "probe"
    jobs = json.loads(sys.stdin.read())
    real_out = sys.stdout
    sys.stdout = io.StringIO()          # anything the evaluated code prints must not corrupt the JSON channel
    out = {}
    for job in jobs:
        res = {}
        t = threading.Thread(target=_eval, args=(job, res, probe), daemon=True)
        t.start()
        t.join(float(job.get("timeout", 5)))
        if t.is_alive():
            out[job["id"]] = {"v": "TIMEOUT"} if probe else "TIMEOUT"
            # a runaway thread may keep running; stop processing further jobs in this process to keep timing honest
            for j in jobs[jobs.index(job) + 1:]:
                out[j["id"]] = {"v": "RUNNER_ABORT"} if probe else "RUNNER_ABORT"
            break
        out[job["id"]] = res if probe else res.get("v", "TIMEOUT")
    real_out.write(json.dumps(out))
    real_out.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
