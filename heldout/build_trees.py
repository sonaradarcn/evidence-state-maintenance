"""Build the 701-commit tree cache for one held-out repo (python build_trees.py <name>)."""
import sys, time
import common_h as C
t = time.time()
r = C.get_repo(sys.argv[1])
print(sys.argv[1], "n_first_parent", r.n_first_parent, "s0", r.s0[:12], "head", r.commits[-1][:12], f"{time.time()-t:.0f}s", flush=True)
