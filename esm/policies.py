"""Registry of the maintenance policies evaluated on the dev set (ESM variants + baselines) and the shared context."""
from pathlib import Path
from . import evidence as E
from . import llm
from .common import DATA, DEV_DATA
from .maintain import ESMConfig, simulate_esm, schedule, DerivStore, NeedModel  # noqa: F401
from .llm import CacheMiss  # noqa: F401
from . import baselines as B

ESM = {
    "ESM":             ESMConfig("ESM"),
    "ESM-noanchor":    ESMConfig("ESM-noanchor", mode="original"),
    "ESM-trunc":       ESMConfig("ESM-trunc", delta="trunc"),
    "ESM-noanchor-trunc": ESMConfig("ESM-noanchor-trunc", mode="original", delta="trunc"),
    "ESM-norepair":    ESMConfig("ESM-norepair", repair=False),
    "ESM-unsurefresh": ESMConfig("ESM-unsurefresh", unsure="fresh"),
    "ESM-chain":       ESMConfig("ESM-chain", chain=True),
    "ESM-9B":          ESMConfig("ESM-9B", model=llm.Q9),
    "ESM-n3":          ESMConfig("ESM-n3", n=3, rule="unanimous"),
    "ESM-n3maj":       ESMConfig("ESM-n3maj", n=3, rule="majority"),
    "ESM-n3-unsurefresh": ESMConfig("ESM-n3-unsurefresh", n=3, rule="unanimous", unsure="fresh"),
    "ESM-noexcerpt":   ESMConfig("ESM-noexcerpt", excerpt=False),
    # held-out stage: repair verification (blind evidence-only answer must agree) and deriver arms
    "ESM-verify":      ESMConfig("ESM-verify", verify="blind"),
    "ESM-verify-unsurefresh": ESMConfig("ESM-verify-unsurefresh", verify="blind", unsure="fresh"),
    "ESM-9Bderiver":   ESMConfig("ESM-9Bderiver", deriver=llm.Q9),
    "ESM-n2":          ESMConfig("ESM-n2", n=2, rule="unanimous"),
    "ESM-verify-n2":   ESMConfig("ESM-verify-n2", n=2, rule="unanimous", verify="blind"),
    "ESM-verify-noanchor": ESMConfig("ESM-verify-noanchor", mode="original", verify="blind"),
    "ESM-verify-trunc": ESMConfig("ESM-verify-trunc", delta="trunc", verify="blind"),
    "ESM-verify-9B":   ESMConfig("ESM-verify-9B", model=llm.Q9, verify="blind"),
    # ablations around the frozen held-out configuration (ESM-norepair, chosen on dev S1; see esm/results/heldout/PLAN.md)
    "ESM-norepair-noanchor": ESMConfig("ESM-norepair-noanchor", mode="original", repair=False),
    "ESM-norepair-trunc": ESMConfig("ESM-norepair-trunc", delta="trunc", repair=False),
    "ESM-norepair-noanchor-trunc": ESMConfig("ESM-norepair-noanchor-trunc", mode="original", delta="trunc", repair=False),
    "ESM-norepair-unsurefresh": ESMConfig("ESM-norepair-unsurefresh", unsure="fresh", repair=False),
    "ESM-norepair-9B": ESMConfig("ESM-norepair-9B", model=llm.Q9, repair=False),
    "ESM-norepair-9Bderiver": ESMConfig("ESM-norepair-9Bderiver", deriver=llm.Q9, repair=False),
    "ESM-norepair-n2": ESMConfig("ESM-norepair-n2", n=2, rule="unanimous", repair=False),
    "ESM-verify-9Bderiver": ESMConfig("ESM-verify-9Bderiver", verify="blind", deriver=llm.Q9),
    # frozen ESM + anchor expiry after N commits (esm/results/heldout/revision_r1_runs)
    **{f"ESM-norepair-exp{n}": ESMConfig(f"ESM-norepair-exp{n}", repair=False, expiry=n) for n in (50, 100, 200)},
    **{f"ESM-norepair-expS{n}": ESMConfig(f"ESM-norepair-expS{n}", repair=False, expiry=n, expiry_mode="suspicious")
       for n in (50, 100, 200)},
}


# detection-only (pilot7 framework: stored answer is always the s0 K; FF/FS per commit)
DETECT = {
    "DETECT-p7a":       ESMConfig("DETECT-p7a", mode="original", delta="trunc"),            # = pilot7 TRIAGE-a
    "DETECT-p7b":       ESMConfig("DETECT-p7b", mode="original", delta="trunc", chain=True),  # = pilot7 TRIAGE-b
    "DETECT-anchor-hier": ESMConfig("DETECT-anchor-hier"),                                    # ESM v1's detector
    "DETECT-anchor-trunc": ESMConfig("DETECT-anchor-trunc", delta="trunc"),
    "DETECT-noanchor-hier": ESMConfig("DETECT-noanchor-hier", mode="original"),
    "DETECT-9B":        ESMConfig("DETECT-9B", model=llm.Q9),
    "DETECT-n3":        ESMConfig("DETECT-n3", n=3),
}


class Context:
    """env + observation table + derivation stores (one per deriver model; `ders` = the default deriver's store)."""

    def __init__(self, env, tab, ders, extra_ders=None, obs_dir=None):
        self.env, self.tab, self.ders = env, tab, ders
        self.dstores = {ders.model: ders, **(extra_ders or {})}
        self.facts = env.facts()
        self.n_states = {}
        self.obs_dir = obs_dir or (DATA / "obs")

    def ders_for(self, model):
        if model is None:
            return self.ders
        if model not in self.dstores:
            raise NeedModel(model)
        return self.dstores[model]

    def count_states(self):
        for f in self.facts:
            ev = E.record(self.env, f, f["trace"], 0, "anchored", f["cite"], f["K"], "s0")
            r0 = self.tab.ref_state(ev)
            self.n_states[f["iid"]] = len({self.tab.state(f, ev, t)[0] for t in range(1, self.env.n_steps() + 1)} - {r0})

    @classmethod
    def load(cls, kind=None):
        """kind 'dev' (default; dev facts, 9B deriver as in the dev stage), 'dev27' (dev facts, 27B deriver, new data under
        <ESM_DATA>/dev27) or 'heldout' (kept held-out facts, 27B deriver; 9B deriver store for the 9B-deriver arm)."""
        import os
        kind = kind or os.environ.get("ESM_KIND", "dev")
        if kind.startswith("dl_") or kind.startswith("dlsyn_"):
            # data-lake stage: kind dl_<lake> (real-only snapshot sequence, headline) or dlsyn_<lake> (synthetic events kept)
            from .envs import datalake as DLE
            from .certs import CertStore
            variant = "synth" if kind.startswith("dlsyn_") else "real"
            lake = kind.split("_", 1)[1]
            sub = DATA / kind
            raw, lk = DLE.load_facts(lake, variant, DATA)
            env0 = DLE.DataLakeEnv(lake, variant, facts=raw, lk=lk)
            kept = DLE.attach_s0(raw, DerivStore(env0, sub / "derivations.jsonl", model=llm.Q27), env0)
            CertStore(sub / "certs.jsonl").attach(kept)
            env = DLE.DataLakeEnv(lake, variant, facts=kept, lk=lk)
            env._ocache = env0._ocache
            tab = E.ObsTable(env)
            obs_dir = sub / "obs"
            for p in sorted(obs_dir.glob("*.pkl")):
                tab.load(p)
            ctx = cls(env, tab, DerivStore(env, sub / "derivations.jsonl", model=llm.Q27),
                      {llm.Q9: DerivStore(env, sub / "derivations_9b.jsonl", model=llm.Q9)}, obs_dir)
            ctx.raw, ctx.kind, ctx.sub = raw, kind, sub
            return ctx
        if kind == "heldout":
            from .envs import heldout as H
            raw = H.load_heldout_raw()
            env0 = H.make_env(raw)
            d0 = DerivStore(env0, DATA / "derivations.jsonl", model=llm.Q27)
            kept = H.attach_s0(raw, d0, env0)
            from .certs import CertStore
            CertStore(DATA / "certs.jsonl").attach(kept)
            env = H.make_env(kept, repos=env0._repos)
            tab = E.ObsTable(env)
            obs_dir = DATA / "obs"
            for p in sorted(obs_dir.glob("*.pkl")):
                tab.load(p)
            ctx = cls(env, tab, DerivStore(env, DATA / "derivations.jsonl", model=llm.Q27),
                      {llm.Q9: DerivStore(env, DATA / "derivations_9b.jsonl", model=llm.Q9)}, obs_dir)
            ctx.raw = raw
            return ctx
        from .envs.pyrepo import PyRepoEnv
        env = PyRepoEnv(none_hint=(kind == "dev27"))
        tab = E.ObsTable(env)
        dev_obs = DEV_DATA / "obs"
        if kind == "dev27":
            obs_dir = DATA / "dev27" / "obs"
            for p in sorted(dev_obs.glob("*.pkl")) + sorted(obs_dir.glob("*.pkl")):
                tab.load(p)
            ctx = cls(env, tab, DerivStore(env, DATA / "dev27" / "derivations.jsonl", model=llm.Q27), None, obs_dir)
        else:
            for p in sorted((DATA / "obs").glob("*.pkl")):
                tab.load(p)
            ctx = cls(env, tab, DerivStore(env, DATA / "derivations.jsonl"))
        ctx.count_states()
        return ctx

    def save_obs(self):
        units = {f["unit"] for f in self.facts}
        for u in units:
            self.tab.save(self.obs_dir / f"{u}.pkl", u)


def run(ctx, policy, fact, sched):
    reads = schedule(sched, ctx.env.n_steps())
    if policy in ESM:
        cfg = ESM[policy]
        return simulate_esm(ctx.env, ctx.tab, fact, reads, cfg, ctx.ders_for(cfg.deriver))
    if policy.endswith("@oracle") and policy[:-7] in ESM:
        from .baselines import OracleDerivs
        return simulate_esm(ctx.env, ctx.tab, fact, reads, ESM[policy[:-7]], OracleDerivs(ctx.env))
    if policy in DETECT:
        from .maintain import detect_only
        return detect_only(ctx.env, ctx.tab, fact, reads, DETECT[policy])
    return B.simulate(ctx, policy, fact, reads)
