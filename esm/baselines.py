"""Baseline maintenance policies.  Every baseline that only flags staleness re-derives on a flag (agent run at that
commit via the shared DerivStore, so a re-derivation can itself be wrong) and re-baselines its guard at that commit.

  NEVER                 blind reuse of the s0 answer
  ALWAYS                re-derive at every read
  TTL<k>                re-derive when >= k commits have passed since the last derivation
  REPLAY                replay the current trace (line numbers normalised); any change -> re-derive;
                        after a re-derivation the NEW trace is replayed
  FILEHASH              content hash of the current trace's read set; any change -> re-derive (new trace's read set)
  ASTHASH               like FILEHASH with AST hashes (comments / formatting ignored) of python files
  CITE                  presence of the s0 citations' lines (FILEHASH fallback without valid citations);
                        flag when the presence pattern changes w.r.t. the last derivation
  CERT-ZS               LLM-written certificate of <= 3 tool calls (REPLAY fallback); outputs vs last derivation
  CERT-v0               CERT v0 certificate of the preliminary study (static facts only; REPLAY when v0 picked the replay)
  LLMDIFF               27B judge on the read-set repository diff since the last derivation (ESM's judge prompt applied to the diff,
                        memoised per read-set state); still_valid -> reuse, otherwise re-derive
Suffix "@oracle" (e.g. "REPLAY@oracle") replaces the agent re-derivation by the oracle answer at that commit (an
idealised upper bound with the logged derivation's token cost); it is reported separately and never mixed with real runs.
"""
from . import evidence as E
from . import judge as J
from . import llm
from .maintain import Rec, NeedModel, judge_ok
from .tools import norm_path


class NotApplicable(Exception):
    pass


class OracleDerivs:
    def __init__(self, env):
        self.env = env

    def get(self, fact, t):
        return {"answer": self.env.truth(fact, t), "tokens": fact["derive_tokens"], "trace": fact["trace"], "oracle": True}


def _cite_valid(env, fact):
    w0 = env.world(fact, 0)
    ok = []
    for c in fact["cite"] or []:
        f, q = norm_path(str(c.get("file", ""))), str(c.get("line", "")).strip()
        txt = w0.text(f)
        if not q or txt is None:
            continue
        if any(q == l.strip() or (len(q) >= 8 and q in l) for l in txt.split("\n")):
            ok.append((f, q))
    return ok


def _cite_from_trace(env, fact):
    """(file, line) citation pairs when the fact's citations carry no file (held-out: zero-LLM auto-citations from the
    trace).  A grep-style text 'path:text' is split at the path; any other text is located in the trace's read-set files at
    s0.  Lines that cannot be located are dropped."""
    w0 = env.world(fact, 0)
    files = env.read_set(fact["trace"])
    ok, seen = [], set()
    for q in env.cite_texts(fact, fact["cite"]):
        pairs = []
        if ":" in q and w0.text(q.split(":", 1)[0]) is not None:
            f, rest = q.split(":", 1)
            pairs = [(f, rest.strip())]
        else:
            for f in files:
                txt = w0.text(f)
                if txt is not None and any(q == l.strip() or (len(q) >= 8 and q in l) for l in txt.split("\n")):
                    pairs.append((f, q))
        for f, x in pairs:
            txt = w0.text(f)
            if x and txt is not None and (f, x) not in seen and any(x == l.strip() or (len(x) >= 8 and x in l) for l in txt.split("\n")):
                seen.add((f, x))
                ok.append((f, x))
    return ok[:8]


def _cite_obs(w, cites):
    out = []
    for f, q in cites:
        txt = w.text(f)
        out.append(bool(txt is not None and any(q == l.strip() or (len(q) >= 8 and q in l) for l in txt.split("\n"))))
    return tuple(out)


class Guard:
    """Guard instrument re-baselined at every (re-)derivation."""

    def __init__(self, ctx, policy, fact):
        self.ctx, self.env, self.tab, self.p, self.f = ctx, ctx.env, ctx.tab, policy, fact
        self.kind = policy
        self.cites = None
        if policy == "CITE":
            self.cites = _cite_valid(self.env, fact)
            if not self.cites and fact.get("cite") and not any(c.get("file") for c in fact["cite"]):
                self.cites = _cite_from_trace(self.env, fact)
            if not self.cites:
                self.kind = "FILEHASH"
        self.listings = False
        if policy == "MANIFEST":           # FILEHASH over files + the listings the trace consulted (data-lake environment)
            self.kind, self.listings = "FILEHASH", True
        if policy == "LLMDIFF":            # the LLM sees the manifest diff incl. consulted listings where the env has them
            self.listings = bool(getattr(self.env, "llmdiff_listings", False))
        if policy == "CERT-ZS":
            self.calls = fact.get("certzs") or []
            if not self.calls:
                self.kind = "REPLAY"
        if policy == "CERT-v0":
            if fact["slice"] != "static":
                raise NotApplicable
            self.calls = fact.get("certv0")
            if not self.calls:
                self.kind = "REPLAY"
        self.io = 0

    def rebase(self, trace, t):
        """Re-baseline at time t on the (new) trace."""
        self.t_last = t
        if self.kind in ("REPLAY", "LLMDIFF"):
            self.ev = E.record(self.env, self.f, trace, t, "original", self.f["cite"], None, f"g{t}")
            self.ref = self.tab.ref_state(self.ev)
            self.io = len(self.ev.keys)
        if self.kind in ("FILEHASH", "ASTHASH", "LLMDIFF"):
            w = self.env.world(self.f, t)
            try:                                                # environments whose read set depends on the version
                self.items = (self.env.read_set(trace, world=w, listings=True) if self.listings else
                              self.env.read_set(trace, world=w))
            except TypeError:
                self.items = self.env.read_set(trace)
            self.href = tuple(self.env.item_hash(w, p, "ast" if self.kind == "ASTHASH" else "file") for p in self.items)
            self.io = len(self.items)
        if self.kind in ("CERT-ZS", "CERT-v0"):
            self.ev = E.record(self.env, self.f, self.calls, t, "original", self.f["cite"], None, f"g{t}")
            self.ref = self.tab.ref_state(self.ev)
            self.io = len(self.ev.keys)
        if self.kind == "CITE":
            self.ref = _cite_obs(self.env.world(self.f, t), self.cites)
            self.io = len(self.cites)

    def changed(self, t):
        if self.kind in ("REPLAY", "CERT-ZS", "CERT-v0"):
            return self.tab.state(self.f, self.ev, t)[0] != self.ref
        if self.kind in ("FILEHASH", "ASTHASH", "LLMDIFF"):
            w = self.env.world(self.f, t)
            return tuple(self.env.item_hash(w, p, "ast" if self.kind == "ASTHASH" else "file") for p in self.items) != self.href
        if self.kind == "CITE":
            return _cite_obs(self.env.world(self.f, t), self.cites) != self.ref
        raise ValueError(self.kind)


def simulate(ctx, policy, fact, reads):
    env = ctx.env
    oracle = policy.endswith("@oracle")
    base = policy[:-7] if oracle else policy
    ders = OracleDerivs(env) if oracle else ctx.ders
    K = fact["K"]
    recs = []
    ttl = int(base[3:]) if base.startswith("TTL") else None
    g = None
    if base not in ("NEVER", "ALWAYS") and ttl is None:
        g = Guard(ctx, base, fact)
        g.rebase(fact["trace"], 0)
    t_last = 0
    memo = {}
    K_ev = K
    for t in reads:
        truth = env.truth(fact, t)
        sv = env.answer_matches(fact, K, truth)
        r = Rec(policy, fact["iid"], t, sv, sv, False, "same", guard_io=(g.io if g else 0))
        flag = False
        if base == "ALWAYS":
            flag = True
        elif ttl is not None:
            flag = t - t_last >= ttl
        elif base != "NEVER":
            if g.changed(t):
                if g.kind == "LLMDIFF":
                    w = env.world(fact, t)
                    key = (g.t_last, tuple(env.item_hash(w, p, "file") for p in g.items))
                    if key in memo:
                        v = memo[key]
                        r.action, r.verdict = "memo", v
                    else:
                        rd, _ = env.readset_diff(env.world(fact, g.t_last), w, g.items, 8000)
                        ev = g.ev
                        ev.K = K_ev
                        res = J.evaluate_rdiff(env, fact, ev, rd)
                        v = res["verdict"]
                        memo[key] = v
                        r.eval_tok, r.eval_calls, r.verdict = sum(res["tokens"]), res["n_calls"], v
                        r.nomemo_calls, r.nomemo_tok = res["n_calls"], sum(res["tokens"])
                        r.action = "valid"
                    flag = v != "still_valid"
                else:
                    flag = True
        if flag:
            d = ders.get(fact, t)
            K = d["answer"]
            K_ev = K
            r.flagged, r.action = True, "rederive"
            r.der_tok, r.n_der = sum(d["tokens"]), 1
            t_last = t
            if g is not None:
                g.rebase(d["trace"], t)
            r.served_valid = env.answer_matches(fact, K, truth)
        r.served = "" if K is None else str(K)
        recs.append(r)
    return recs
