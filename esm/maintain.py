"""ESM v1 maintenance policy + shared simulation machinery (derivation store, read schedules, per-read records).

Per fact, at every read t of a schedule (all reads of one fact are processed in order):
  1. replay the anchor's queries at t (zero LLM) -> evidence state; same as the anchor's state => REUSE
  2. memo hit for (anchor, state) => apply the memoised verdict (still_valid -> REUSE)
  3. else TRANSITION EVALUATION (judge.evaluate, hierarchical or truncated delta) ->
       still_valid               -> reuse, memoise (and, if cfg.chain, move the reference to t)
       changed + new_answer      -> IN-PLACE REPAIR (K := new_answer; re-anchor the queries at t)   [cfg.repair]
       unsure                    -> re-derive (cfg.unsure == 'stale') or reuse+memoise (cfg.unsure == 'fresh')
       changed w/o answer, too_large, parse_fail, or changed with repair off -> RE-DERIVATION by the agent at t
         (K := agent answer; new evidence recorded from the new trace at t; zero-LLM citations from the trace)
Every read yields one record (see `Rec`): stored answer before maintenance, served answer after, their validity vs the
oracle, action, token costs.  `nomemo_calls` counts the evaluator calls a policy without memoisation would make.
"""
import json, threading, time
from dataclasses import dataclass, field, asdict
from . import evidence as E
from . import judge as J
from . import llm


# ---------------------------------------------------------------- schedules
def schedule(name, n=400):
    if name == "every":
        return list(range(1, n + 1))
    if name.startswith("every") and name[5:].isdigit():
        k = int(name[5:])
        return list(range(k, n + 1, k))
    if name == "bursty":
        # 80 reads in bursts of 10 over 400 commits (Stage 1/2); for other horizons the same 20 % read density
        import random
        rng = random.Random(7)
        m = 80 if n == 400 else max(10, n // 5)
        reads = set()
        while len(reads) < m:
            s = rng.randint(1, n)
            reads.update(range(s, min(n, s + 9) + 1))
        return sorted(reads)[:m]
    raise ValueError(name)


# ---------------------------------------------------------------- derivation store
def read_shards(path):
    """Records of <path> plus every per-process shard <stem>.<pid>.jsonl next to it (unparseable lines skipped)."""
    out = []
    for p in [path] + sorted(path.parent.glob(f"{path.stem}.*.jsonl")):
        if not p.exists():
            continue
        for l in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if l.strip():
                try:
                    out.append(json.loads(l))
                except Exception:
                    pass
    return out


class NeedModel(Exception):
    """Raised when a computation needs an LLM whose servers are not configured in this run."""


class DerivStore:
    """Memoised agent re-derivations keyed by (iid, t); persisted to <data>/derivations.jsonl."""

    def __init__(self, env, path, model=llm.Q9):
        self.env, self.path, self.model = env, path, model
        self.d, self._locks, self._lock = {}, {}, threading.Lock()
        for r in read_shards(path):
            self.d.setdefault((r["iid"], r["t"]), r)
        # each process appends to its own shard <stem>.<pid>.jsonl (no interleaving of long lines between processes)
        import os
        self.wpath = path.with_name(f"{path.stem}.{os.getpid()}.jsonl")

    def get(self, fact, t):
        k = (fact["iid"], t)
        r = self.d.get(k)
        if r is not None:
            return r
        with self._lock:
            lk = self._locks.setdefault(k, threading.Lock())
        with lk:
            r = self.d.get(k)
            if r is not None:
                return r
            if not llm.PORTS.get(self.model.split(":", 1)[1]) or __import__("os").environ.get("ESM_LLM_OFFLINE") == "1":
                raise NeedModel(self.model)
            t0 = time.time()
            der = self.env.derive(fact, t, self.model)
            r = {"iid": fact["iid"], "t": t, "answer": der["answer"], "tokens": der["tokens"], "n_llm": der["n_llm"],
                 "n_new": der["n_new"], "trace": der["trace"], "secs": round(time.time() - t0, 1),
                 "correct": bool(self.env.answer_matches(fact, der["answer"], self.env.truth(fact, t)))}
            with self._lock:
                self.d[k] = r
                with open(self.wpath, "a", encoding="utf-8") as f:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            return r


# ---------------------------------------------------------------- per-read record
@dataclass
class Rec:
    policy: str
    iid: str
    t: int
    stored_valid: bool
    served_valid: bool
    flagged: bool                 # policy acted (judged stale / re-derived / repaired)
    action: str                   # same | memo | valid | repair | rederive | unsure_fresh | none
    eval_tok: int = 0
    eval_calls: int = 0
    der_tok: int = 0
    n_der: int = 0
    nomemo_calls: int = 0
    nomemo_tok: int = 0
    guard_io: int = 0             # observations replayed
    verdict: str = ""
    repair_ok: int = -1           # 1/0 for repairs
    served: str = ""
    verified: int = -1            # repair verification: 1 accepted, 0 rejected (-> re-derivation), -1 not run
    proposed_ok: int = -1         # was the judge's proposed new answer right (whether or not it was accepted)
    reason: str = ""              # judge's reason (first 200 chars) / verifier answer, for the error taxonomy


def judge_ok(model):
    return bool(llm.PORTS.get(model.split(":", 1)[1]))


@dataclass
class ESMConfig:
    name: str = "ESM"
    mode: str = "anchored"        # anchored | original   (evidence recording)
    delta: str = "hier"           # hier | trunc
    repair: bool = True
    unsure: str = "stale"         # stale | fresh
    n: int = 1
    temp: float = 0.7
    rule: str = "unanimous"
    model: str = llm.Q27
    chain: bool = False
    excerpt: bool = True
    verify: str = "none"          # none | blind  (repair accepted only if a blind evidence-only answer agrees)
    deriver: str = None           # re-derivation agent model (None = the context's default deriver)
    # Anchor expiry (revision_r1_runs): expiry = N > 0 forces a re-derivation at the first read at which
    # the current anchor is >= N commits old (s0 = an anchor at t = 0).  expiry_mode 'all' = every anchor expires;
    # 'suspicious' = only anchors whose answer is NONE-suspicious (see _none_suspicious).  Fallback when the forced
    # re-derivation returns no answer (None / empty) or raises: keep the previous answer AND the previous evidence anchor,
    # mark the answer 'unverified', and restart the age clock at t (next forced attempt at t + N).
    expiry: int = 0
    expiry_mode: str = "all"


import re as _re
_GONE = _re.compile(r"no longer|removed|deleted|delet|does ?n[o']?t exist|not exist|missing|moved|renamed|not found|"
                    r"no such|absent|gone|disappear|cannot be found|can't be found|non-?existent|not present|not defined",
                    _re.I)


def _none_suspicious(answer, verdict_reason):
    """Zero-oracle rule for the optional expiry variant: a re-derived answer is NONE-suspicious if the
    re-derivation returned no answer, or if it returned a value other than 'NONE' although the judge verdict that
    triggered it said the referent disappeared (removed / moved / renamed / not found ...).  That is the situation of
    90 % of ESM's anchored wrong re-derivations (oracle NONE, agent gives a value)."""
    a = "" if answer is None else str(answer).strip()
    if not a:
        return True
    return a.upper() != "NONE" and bool(_GONE.search(verdict_reason or ""))


def detect_only(env, tab, fact, reads, cfg):
    """pilot7-style detection: the s0 evidence is never moved (unless cfg.chain: reference moves to the last state judged
    still_valid, pilot7 variant b); a read is STALE iff its state differs and the verdict is not still_valid.
    The stored answer is always K, so FF/FS are pilot7's per-commit definitions.  Returns list[Rec]."""
    ev = E.record(env, fact, fact["trace"], 0, cfg.mode, fact["cite"], fact["K"], "a0", origin="s0")
    ref_state = tab.ref_state(ev)
    memo, recs, n = {}, [], 0
    for t in reads:
        sv = env.answer_matches(fact, fact["K"], env.truth(fact, t))
        st, _ = tab.state(fact, ev, t)
        r = Rec(cfg.name, fact["iid"], t, sv, sv, False, "same", guard_io=len(ev.keys))
        if st != ref_state:
            mk = (ev.aid, st)
            if mk not in memo:
                res = J.evaluate(env, fact, ev, tab.outputs(fact, ev, t), mode=cfg.delta, model=cfg.model, n=cfg.n,
                                 temp=cfg.temp, with_excerpt=cfg.excerpt, tag=f"esm_{cfg.name}",
                                 ref_label="the earlier commit" if ev.aid == "a0" else
                                 "the last commit at which the answer was confirmed still valid")
                v, na = (J.combine(res["samples"], cfg.rule) if cfg.n > 1 else (res["verdict"], res["new_answer"]))
                memo[mk] = (v, na, sum(res["tokens"]), res["n_calls"], res["info"].get("trunc"), res["info"].get("groups", 0))
                r.eval_tok, r.eval_calls = sum(res["tokens"]), res["n_calls"]
                r.action = "eval"
            else:
                r.action = "memo"
            v, na, tok, nc, tr, ng = memo[mk]
            r.verdict = v
            r.nomemo_calls, r.nomemo_tok = nc, tok
            ok = v == "still_valid" or (v == "unsure" and cfg.unsure == "fresh")
            r.flagged = not ok
            r.served = "" if na is None else str(na)          # the judge's proposed new answer (repair candidate)
            if r.flagged and na:
                r.repair_ok = int(env.answer_matches(fact, na, env.truth(fact, t)))
            if ok and cfg.chain:
                n += 1
                ev = E.reanchor(env, fact, ev, t, fact["K"], f"c{n}", origin="chain")
                ref_state = tab.ref_state(ev)
        recs.append(r)
    return recs


def simulate_esm(env, tab, fact, reads, cfg, ders, judge_cache=None):
    """Returns list[Rec].  Raises NeedModel if an LLM that is not available is needed."""
    if not judge_ok(cfg.model):
        pass   # judge availability is checked lazily (only when a call is actually needed)
    n_anchor = [0]

    def new_aid():
        n_anchor[0] += 1
        return f"a{n_anchor[0]}"

    ev = E.record(env, fact, fact["trace"], 0, cfg.mode, fact["cite"], fact["K"], "a0", origin="s0")
    ref_state = tab.ref_state(ev)
    memo, nomemo_cost = {}, {}
    K = fact["K"]
    recs = []
    anchor_t, susp, unverified = 0, False, False       # anchor expiry state (cfg.expiry > 0 only)
    for t in reads:
        truth = env.truth(fact, t)
        stored_valid = env.answer_matches(fact, K, truth)
        if cfg.expiry and t - anchor_t >= cfg.expiry and (cfg.expiry_mode == "all" or susp):
            r = Rec(cfg.name, fact["iid"], t, stored_valid, stored_valid, True, "forced", guard_io=len(ev.keys))
            try:
                d = ders.get(fact, t)
            except (NeedModel, llm.CacheMiss):
                raise
            except Exception as e:            # a failed forced re-derivation -> fallback (keep previous answer)
                d = {"answer": None, "tokens": [0, 0], "trace": [], "error": repr(e)[:200]}
            r.der_tok, r.n_der = sum(d["tokens"]), 1
            anchor_t = t
            a = d["answer"]
            if a is None or not str(a).strip():
                r.action, unverified = "forced_keep", True           # fallback: K and its anchor kept, now unverified
                r.reason = "forced re-derivation returned no answer; previous answer kept (unverified)"
            else:
                K = a
                unverified = False
                susp = cfg.expiry_mode == "suspicious" and susp and str(a).strip().upper() != "NONE"
                cites = env.auto_cites(fact, d["trace"], a)
                ev = E.record(env, fact, d["trace"], t, cfg.mode, cites, K, new_aid(), origin="forced")
                ref_state = tab.ref_state(ev)
            r.served = "" if K is None else str(K)
            r.served_valid = env.answer_matches(fact, K, truth)
            r.verified = 0 if unverified else -1
            recs.append(r)
            continue
        st, _ = tab.state(fact, ev, t)
        r = Rec(cfg.name, fact["iid"], t, stored_valid, stored_valid, False, "same", guard_io=len(ev.keys))
        if unverified:
            r.verified = 0                                           # served answer is a kept, unverified one
        if st == ref_state:
            r.served = K
            recs.append(r)
            continue
        mk = (ev.aid, st)
        if mk in memo:
            v = memo[mk]
            r.action, r.verdict = "memo", v
            c = nomemo_cost[mk]
            r.nomemo_calls, r.nomemo_tok = c
            r.served = K
            recs.append(r)
            continue
        cur = tab.outputs(fact, ev, t)
        if judge_cache is not None and (fact["iid"], ev.aid, st) in judge_cache:
            res = judge_cache[(fact["iid"], ev.aid, st)]
        else:
            res = J.evaluate(env, fact, ev, cur, mode=cfg.delta, model=cfg.model, n=cfg.n, temp=cfg.temp,
                             with_excerpt=cfg.excerpt, tag=f"esm_{cfg.name}")
            if cfg.n > 1:
                res = dict(res)
                res["verdict"], res["new_answer"] = J.combine(res["samples"], cfg.rule)
        tok = sum(res["tokens"])
        r.eval_tok, r.eval_calls = tok, res["n_calls"]
        r.nomemo_calls, r.nomemo_tok = res["n_calls"], tok
        v, na = res["verdict"], res["new_answer"]
        r.verdict = v
        r.reason = (res.get("reason") or "")[:200] + (f" | proposed={na}"[:120] if na else "")
        if v == "still_valid" or (v == "unsure" and cfg.unsure == "fresh"):
            memo[mk] = v
            nomemo_cost[mk] = (res["n_calls"], tok)
            r.action = "valid" if v == "still_valid" else "unsure_fresh"
            if cfg.chain:
                ev = E.reanchor(env, fact, ev, t, ev.K, new_aid(), origin="chain")
                ref_state = tab.ref_state(ev)
            r.served = K
            recs.append(r)
            continue
        r.flagged = True
        accept = False
        if v == "changed" and na and cfg.repair:
            r.proposed_ok = int(env.answer_matches(fact, na, truth))
            ev2 = E.reanchor(env, fact, ev, t, na, new_aid(), origin="repair")
            accept = True
            if cfg.verify != "none":
                vr = J.verify_answer(env, fact, ev2, ev2.ref, na, model=cfg.model, tag=f"esm_{cfg.name}_verify")
                r.eval_tok += sum(vr["tokens"]); r.eval_calls += vr["n_calls"]
                r.nomemo_tok += sum(vr["tokens"]); r.nomemo_calls += vr["n_calls"]
                r.verified = int(vr["ok"])
                r.reason += f" | verifier={vr['answer']}"[:120]
                accept = vr["ok"]
        if accept:
            K = na
            r.action = "repair"
            r.repair_ok = int(env.answer_matches(fact, K, truth))
            ev = ev2
            ref_state = tab.ref_state(ev)
            anchor_t, susp, unverified = t, False, False
        else:
            d = ders.get(fact, t)
            K = d["answer"]
            r.action = "rederive"
            r.der_tok, r.n_der = sum(d["tokens"]), 1
            cites = env.auto_cites(fact, d["trace"], d["answer"])
            ev = E.record(env, fact, d["trace"], t, cfg.mode, cites, K, new_aid(), origin="rederive")
            ref_state = tab.ref_state(ev)
            anchor_t, unverified = t, False
            susp = _none_suspicious(K, res.get("reason") or "")
            if cfg.expiry:
                r.verified = -1
        r.served = "" if K is None else str(K)
        r.served_valid = env.answer_matches(fact, K, truth)
        recs.append(r)
    return recs
