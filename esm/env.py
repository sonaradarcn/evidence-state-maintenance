"""The environment interface ESM is written against.

ESM never touches a repository, a file system or a database directly.  Everything environment-specific sits behind
`Environment`; `esm.envs.pyrepo.PyRepoEnv` is the git-repository implementation used on the dev set.  A second
environment (e.g. a data lake with schema/aggregate facts) implements the same methods and gets evidence recording,
deltas, judging, maintenance, baselines and metrics for free.

Conventions
-----------
* A *fact* is a dict with at least: iid, slice, unit (repo / table group), type, question, K (answer at s0), trace
  (list of {tool, args, out} recorded at s0), cite (list of {file, line}), derive_tokens ([prompt, completion]).
* Time is an integer t: 0 = s0 (derivation commit), 1..n_steps() = later environment versions.
* A *query* is a JSON-serialisable dict produced by `anchor_call`; `observe` resolves it in a world and returns the
  normalised observation text.  Two observations are "the same evidence" iff their texts are equal.
"""
from abc import ABC, abstractmethod


class Environment(ABC):
    name = "abstract"
    domain = "an environment"            # used in prompts: "a question about <domain>"
    tool_names = ""                      # used in prompts: "(ls, find, grep, ...)"

    # ---- data
    @abstractmethod
    def facts(self):
        """List of fact dicts (see module docstring)."""

    @abstractmethod
    def n_steps(self):
        """Number of later versions (FUTURE commits)."""

    @abstractmethod
    def world(self, fact, t):
        """World object of the fact's unit at time t (0 = s0)."""

    @abstractmethod
    def truth(self, fact, t):
        """Oracle answer value at time t (string)."""

    @abstractmethod
    def answer_matches(self, fact, answer, value):
        """Canonicalised comparison of an answer string with an oracle value."""

    # ---- tools and evidence
    @abstractmethod
    def run_call(self, world, call):
        """Raw output of a recorded tool call {tool, args}."""

    @abstractmethod
    def anchor_call(self, world0, call, cites, mode):
        """Drift-robust query for a recorded call (mode 'anchored'), or the original call (mode 'original')."""

    @abstractmethod
    def observe(self, world, query):
        """Normalised observation text of a query in a world."""

    @abstractmethod
    def reanchor(self, world, query):
        """A query equivalent to `query` but anchored on `world`'s content (after a repair at a later version)."""

    @abstractmethod
    def query_label(self, query):
        """Short human-readable call string for prompts."""

    # ---- cheap guard ingredients for baselines
    @abstractmethod
    def read_set(self, trace):
        """Units of storage (files / tables) the trace consulted."""

    @abstractmethod
    def item_hash(self, world, item, kind):
        """kind 'file' = content hash; 'ast' = structure hash ignoring comments/formatting."""

    @abstractmethod
    def readset_diff(self, world_a, world_b, items, cap):
        """Unified diff of the read-set items between two worlds (for the LLM-on-diff baseline)."""

    # ---- derivation agent
    @abstractmethod
    def derive(self, fact, t, model):
        """Run the derivation agent at time t.  Returns {trace, answer, tokens: [prompt, completion], n_llm}."""
