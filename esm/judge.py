"""Transition evaluator: one LLM call (or a hierarchical screen + final call) on an evidence delta.

`evaluate(env, fact, ev, cur, ...)` -> {verdict, new_answer, reason, tokens:[prompt, completion], n_calls, info, samples}
verdict in {still_valid, changed, unsure, parse_fail, too_large}.  With n > 1 the final prompt is sampled n times at
temperature `temp` (nonces 0..n-1); `samples` keeps every sample so combination rules can be applied afterwards
(`combine`).  Everything goes through esm.llm (disk cache).
"""
import json, os
from . import delta as D
from . import llm

# cross-model stage: a reasoning model spends part of max_tokens on hidden reasoning; ESM_JUDGE_MAXTOK raises the cap
# (default 900 = every earlier stage, cache keys unchanged)
MAX_TOK = int(os.environ.get("ESM_JUDGE_MAXTOK", "900"))


def parse(content):
    j = llm.json_from(content)
    v, na, rs = None, None, None
    if isinstance(j, dict):
        v = str(j.get("verdict", "")).strip().lower().replace(" ", "_")
        na = j.get("new_answer")
        rs = j.get("reason")
    if v not in ("still_valid", "changed", "unsure"):
        low = (content or "").lower()
        v = "still_valid" if '"still_valid"' in low and '"changed"' not in low else "parse_fail"
    na = None if na in (None, "", "null") else (json.dumps(na) if not isinstance(na, str) else na)
    return v, na, (rs if isinstance(rs, str) else (None if rs is None else str(rs)))


def _call(model, prompt, temp, nonce, tag):
    r = llm.chat(model, [{"role": "user", "content": prompt}], max_tokens=MAX_TOK, temperature=temp, tag=tag, nonce=nonce)
    return r


def _final(model, prompt, n, temp, tag):
    samples, tok = [], [0, 0]
    for k in range(n):
        r = _call(model, prompt, temp if n > 1 else 0.0, (k if n > 1 else None), tag)
        v, na, rs = parse(r["content"])
        samples.append({"verdict": v, "new_answer": na, "reason": (rs or "")[:300], "cached": r.get("cached", False)})
        tok[0] += r["usage"]["prompt"]; tok[1] += r["usage"]["completion"]
    return samples, tok


def combine(samples, rule="unanimous"):
    """n-sample combination.  unanimous: still_valid only if every sample says so; otherwise the majority non-valid verdict
    (changed+answer if a strict majority agrees on the same answer).  majority: plain majority over verdicts."""
    if len(samples) == 1:
        return samples[0]["verdict"], samples[0]["new_answer"]
    vs = [s["verdict"] for s in samples]
    ch = [s["new_answer"] for s in samples if s["verdict"] == "changed" and s["new_answer"]]
    best = max(set(ch), key=ch.count) if ch else None
    if rule == "unanimous":
        if all(v == "still_valid" for v in vs):
            return "still_valid", None
    else:
        if vs.count("still_valid") * 2 > len(vs):
            return "still_valid", None
    if best is not None and ch.count(best) * 2 > len(samples):
        return "changed", best
    if vs.count("changed") * 2 > len(vs):
        return "changed", None
    return "unsure", None


def evaluate(env, fact, ev, cur, mode="hier", model=llm.Q27, n=1, temp=0.7, with_excerpt=True,
             ref_label="the earlier commit", tag="esm_judge"):
    """Judge the transition ev.ref -> cur (dicts qkey -> observation).  mode: 'hier' (no truncation) or 'trunc' (pilot7)."""
    text, info = D.build_capped(env, fact, ev, cur)
    info = dict(info, mode=mode)
    tok, ncalls = [0, 0], 0
    if mode != "trunc" and info["trunc"]:
        t2, i2 = D.build_capped(env, fact, ev, cur, per_call=D.SINGLE, total=D.SINGLE)
        if not i2["trunc"]:
            text, info = t2, dict(i2, mode=mode, single_uncapped=True, trunc_8k=True)
    if mode == "trunc" or not info["trunc"]:
        prompt = D.prompt_delta(env, fact, ev, text, with_excerpt, ref_label)
        samples, t = _final(model, prompt, n, temp, tag)
        tok = t
        ncalls = n
    else:
        groups, labels, ginfo = D.plan_hierarchical(env, fact, ev, cur)
        info.update(ginfo)
        keep, screens = [], []
        for i, g in enumerate(groups, 1):
            r = _call(model, D.prompt_screen(env, fact, ev, g, i, len(groups)), 0.0, None, tag + "_screen")
            tok[0] += r["usage"]["prompt"]; tok[1] += r["usage"]["completion"]; ncalls += 1
            j = llm.json_from(r["content"])
            ca = j.get("could_affect") if isinstance(j, dict) else None
            if isinstance(ca, str):
                ca = ca.strip().lower() not in ("false", "no")
            ca = True if ca is None else bool(ca)       # unparseable screen -> keep the group
            screens.append(ca)
            if ca:
                keep.append(i - 1)
        info["retained"] = len(keep)
        info["screens"] = screens
        if not keep:
            samples = [{"verdict": "still_valid", "new_answer": None, "reason": "all changed parts screened as irrelevant", "cached": True}]
        else:
            body = "\n\n".join(groups[i] for i in keep)
            dropped = [lab for i, lab in enumerate(labels) if i not in keep]
            if dropped:
                calls = sorted({x for lab in dropped for x in lab})
                body += (f"\n\n[{len(dropped)} other part(s) of the change (in: {'; '.join(c[:80] for c in calls[:6])}) were "
                         "screened as unable to affect the answer and are not shown]")
            info["final_chars"] = len(body)
            if len(body) > D.FINAL:
                samples = [{"verdict": "too_large", "new_answer": None, "reason": "retained delta exceeds the final budget", "cached": True}]
            else:
                prompt = D.prompt_delta(env, fact, ev, body, with_excerpt, ref_label)
                samples, t = _final(model, prompt, n, temp, tag)
                tok[0] += t[0]; tok[1] += t[1]; ncalls += n
    v, na = combine(samples)
    return {"verdict": v, "new_answer": na, "reason": samples[0].get("reason"), "tokens": tok, "n_calls": ncalls,
            "info": info, "samples": samples}


def evaluate_rdiff(env, fact, ev, rdiff, model=llm.Q27, tag="esm_rdiff"):
    """LLM-on-repository-diff judge (baseline)."""
    if not rdiff.strip():
        return {"verdict": "still_valid", "new_answer": None, "reason": "empty diff", "tokens": [0, 0], "n_calls": 0, "info": {}}
    r = _call(model, D.prompt_rdiff(env, fact, ev, rdiff), 0.0, None, tag)
    v, na, rs = parse(r["content"])
    return {"verdict": v, "new_answer": na, "reason": rs, "tokens": [r["usage"]["prompt"], r["usage"]["completion"]], "n_calls": 1,
            "info": {"trunc": "[... diff truncated" in rdiff}}


# ---------------------------------------------------------------- repair verification (held-out stage)
VERIFY_CAP_PER, VERIFY_CAP = 4000, 24000


def evidence_text(env, ev, cur, per=VERIFY_CAP_PER, cap=VERIFY_CAP):
    """Current observations of the evidence's queries, labelled, each <= per chars, total <= cap chars."""
    parts, tot, omitted = [], 0, 0
    for q, k in zip(ev.queries, ev.keys):
        o = cur[k]
        if len(o) > per:
            o = o[:per] + "\n[... output truncated]"
        s = f"### {env.query_label(q)}\n{o}"
        if tot + len(s) > cap:
            omitted += 1
            continue
        parts.append(s)
        tot += len(s)
    if omitted:
        parts.append(f"[{omitted} further tool output(s) omitted for space]")
    return "\n\n".join(parts)


def prompt_verify(env, fact, evtext):
    return (f"You are given the outputs of deterministic, read-only tool calls ({env.tool_names}) made on {env.domain} at "
            "its current commit. Answer the question using ONLY this evidence.\n\n"
            f"Question: {fact['question']}\n\nTool outputs at the current commit:\n\n{evtext}\n\n"
            "If the evidence shows that what the question refers to does not exist any more, the answer is NONE. "
            'Reply with JSON only: {"answer": <the answer in the format the question asks, or null if the evidence shown '
            'does not determine it>, "reason": "<at most 20 words>"}.')


def verify_answer(env, fact, ev, cur, proposed, model=llm.Q27, tag="esm_verify"):
    """Blind independent confirmation of a proposed answer: the verifier answers the question from the current
    (re-anchored) evidence WITHOUT seeing the proposal; the proposal is accepted iff the two answers agree after the
    environment's answer canonicalisation.  Returns {ok, answer, tokens, n_calls}."""
    p = prompt_verify(env, fact, evidence_text(env, ev, cur))
    r = llm.chat(model, [{"role": "user", "content": p}], max_tokens=MAX_TOK, temperature=0.0, tag=tag)
    j = llm.json_from(r["content"])
    ans = None
    if isinstance(j, dict):
        ans = j.get("answer")
        if ans is not None and not isinstance(ans, str):
            ans = json.dumps(ans) if isinstance(ans, (list, dict)) else str(ans)
        if isinstance(ans, str) and ans.strip().lower() in ("", "null"):
            ans = None
    ok = ans is not None and env.answers_agree(fact, ans, proposed)
    return {"ok": bool(ok), "answer": ans, "tokens": [r["usage"]["prompt"], r["usage"]["completion"]], "n_calls": 1}
