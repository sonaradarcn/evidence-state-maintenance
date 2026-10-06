"""Transition representation: focused evidence deltas and evaluator prompts (no LLM calls here).

* `build_capped` is the capped delta of the preliminary study (2 context lines, hunks ranked by distance to the cited lines,
  2.5 KB per call, 8 KB total, calls containing cited lines first, dropped hunks/calls announced).  When nothing had to be
  dropped (`info["trunc"] is False`) the delta is complete and ESM uses it as is.
* If the complete delta is larger than the 8 KB cap but at most SINGLE (12 KB) chars it is shown complete in one call.
* `plan_hierarchical` is used instead of truncation when the complete delta does not fit: the complete set of hunks is
  split into groups of <= GROUP chars (by changed observation, hunks nearest the cited evidence first; an oversized hunk
  is split into line chunks - nothing is dropped).  Each group gets a screening prompt ("could this part affect the
  answer?"); the final prompt shows every retained group in full (<= FINAL chars, otherwise the transition is declared
  too large and the fact is re-derived).
* For the single-call case the prompts are byte-identical to the preliminary study's, so its cached responses are
  reused where states coincide.
"""
import difflib, re

PER_CALL, TOTAL, EXCERPT = 2500, 8000, 1500
SINGLE, GROUP, FINAL = 12000, 12000, 20000
_HH = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def line_hits(lines, cites):
    pos = []
    for i, l in enumerate(lines):
        s = l.strip()
        for q in cites:
            if q == s or (len(q) >= 8 and q in l):
                pos.append(i)
                break
    return pos


def excerpt(env, fact, ev):
    """Cited lines +-2 lines from the anchor's reference observations (<= 1.5 KB); else head of the last non-error output."""
    cites = env.cite_texts(fact, ev.cites)
    parts, used = [], set()
    for q, k in zip(ev.queries, ev.keys):
        lines = ev.ref[k].split("\n")
        hits = line_hits(lines, cites)
        if not hits:
            continue
        keep = sorted({j for i in hits for j in range(max(0, i - 2), min(len(lines), i + 3))})
        seg, prev = [], None
        for j in keep:
            if prev is not None and j != prev + 1:
                seg.append("...")
            seg.append(lines[j])
            prev = j
        txt = "\n".join(seg)
        if txt in used:
            continue
        used.add(txt)
        parts.append(f"from {env.query_label(q)}:\n{txt}")
    s = "\n\n".join(parts)
    if not s:
        for q, k in zip(reversed(ev.queries), reversed(ev.keys)):
            o = ev.ref[k]
            if not o.startswith("error") and o.strip():
                s = f"from {env.query_label(q)}:\n{o[:1200]}"
                break
    if len(s) > EXCERPT:
        s = s[:EXCERPT] + "\n[...]"
    return s


def hunks(a, b):
    d = list(difflib.unified_diff(a.split("\n"), b.split("\n"), n=2, lineterm=""))
    hs, cur = [], None
    for l in d[2:]:
        m = _HH.match(l)
        if m:
            cur = {"s": int(m.group(1)) - 1, "l": int(m.group(2) or 1), "lines": ["@@"]}
            hs.append(cur)
        elif cur is not None:
            cur["lines"].append(l)
    for x in hs:
        x["text"] = "\n".join(x["lines"])
    return hs


def _blocks(env, fact, ev, cur):
    cites = env.cite_texts(fact, ev.cites)
    blocks = []
    for order, (q, k) in enumerate(zip(ev.queries, ev.keys)):
        a, b = ev.ref[k], cur[k]
        if a == b:
            continue
        hs = hunks(a, b)
        anchors = line_hits(a.split("\n"), cites)
        for i, x in enumerate(hs):
            if anchors:
                lo, hi = x["s"], x["s"] + max(x["l"], 1) - 1
                x["dist"] = min(0 if lo <= p <= hi else min(abs(p - lo), abs(p - hi)) for p in anchors)
            else:
                x["dist"] = 10 ** 6 + i
        blocks.append({"k": k, "order": order, "hdr": f"### {env.query_label(q)}", "hs": hs,
                       "mind": min([x["dist"] for x in hs] or [10 ** 7]), "anchored": bool(anchors)})
    blocks.sort(key=lambda b: (b["mind"] >= 10 ** 6, b["mind"] if b["mind"] < 10 ** 6 else 0, b["order"]))
    return blocks


def build_capped(env, fact, ev, cur, per_call=PER_CALL, total=TOTAL):
    """pilot7's capped delta.  Returns (text, info) with info['trunc'] True iff any hunk or call was dropped/cut."""
    blocks = _blocks(env, fact, ev, cur)
    for bl in blocks:
        hs = bl["hs"]
        kept, size = [], 0
        for x in sorted(hs, key=lambda x: x["dist"]):
            if size + len(x["text"]) <= per_call or not kept:
                kept.append(x if len(x["text"]) <= per_call else dict(x, text=x["text"][:per_call] + "\n[... hunk truncated]"))
                size += min(len(x["text"]), per_call)
        n_omit = len(hs) - len(kept)
        body = "\n".join(x["text"] for x in sorted(kept, key=lambda x: x["s"]))
        if n_omit:
            body += f"\n[... {n_omit} more changed hunk(s) of this output omitted]"
        bl.update(body=body, n_h=len(hs), n_kept=len(kept), trunc=bool(n_omit) or any(len(x["text"]) > per_call for x in hs))
    out, tot, omitted = [], 0, 0
    for bl in sorted(blocks, key=lambda b: (b["mind"] >= 10 ** 6, b["mind"] if b["mind"] < 10 ** 6 else 0, b["order"])):
        s = bl["hdr"] + "\n" + bl["body"]
        if tot + len(s) <= total:
            out.append((bl["order"], s))
            tot += len(s)
        else:
            out.append((bl["order"], bl["hdr"] + "\n[output changed; diff omitted for space]"))
            omitted += 1
            bl["trunc"] = True
            bl["omitted"] = True
    text = "\n\n".join(s for _, s in sorted(out))
    full = sum(len(bl["hdr"]) + 1 + sum(len(x["text"]) + 1 for x in bl["hs"]) for bl in blocks)
    info = {"n_changed": len(blocks), "omitted_calls": omitted, "trunc": any(b["trunc"] for b in blocks),
            "hunks": sum(b["n_h"] for b in blocks), "hunks_kept": sum(b["n_kept"] for b in blocks if not b.get("omitted")),
            "chars": len(text), "full_chars": full}
    return text, info


def plan_hierarchical(env, fact, ev, cur, group=GROUP):
    """Complete delta split into groups (list of texts, each <= group chars, nothing dropped) + per-group call labels."""
    blocks = _blocks(env, fact, ev, cur)
    items = []   # (block index, header, text piece)
    for bi, bl in enumerate(blocks):
        hs = sorted(bl["hs"], key=lambda x: (x["dist"], x["s"]))
        for x in hs:
            t = x["text"]
            if len(t) + len(bl["hdr"]) + 2 <= group:
                items.append((bi, t))
                continue
            lines, cur_, n = t.split("\n"), [], 0
            pieces = []
            for l in lines:
                if n + len(l) + 1 > group - len(bl["hdr"]) - 60 and cur_:
                    pieces.append("\n".join(cur_)); cur_, n = [], 0
                cur_.append(l[: group - len(bl["hdr"]) - 80]); n += len(cur_[-1]) + 1
            if cur_:
                pieces.append("\n".join(cur_))
            for j, p in enumerate(pieces, 1):
                items.append((bi, f"[hunk piece {j}/{len(pieces)}]\n{p}" if j > 1 else p))
    groups, cur_g, size = [], [], 0
    for bi, t in items:
        add = len(t) + 1 + (len(blocks[bi]["hdr"]) + 2 if not cur_g or cur_g[-1][0] != bi else 0)
        if cur_g and size + add > group:
            groups.append(cur_g); cur_g, size = [], 0
            add = len(t) + 1 + len(blocks[bi]["hdr"]) + 2
        cur_g.append((bi, t)); size += add
    if cur_g:
        groups.append(cur_g)
    texts, labels = [], []
    for g in groups:
        parts, last = [], None
        for bi, t in g:
            if bi != last:
                parts.append(blocks[bi]["hdr"])
                last = bi
            parts.append(t)
        texts.append("\n".join(parts))
        labels.append(sorted({blocks[bi]["hdr"][4:] for bi, _ in g}))
    return texts, labels, {"n_changed": len(blocks), "hunks": sum(len(b["hs"]) for b in blocks), "groups": len(texts)}


INSTR = ('Reply with JSON only: {"verdict": "still_valid" | "changed" | "unsure", "new_answer": <the answer at the later commit in the '
         'same format as the question asks, or null if you cannot determine it>, "reason": "<at most 20 words>"}.\n'
         '"still_valid": the changes cannot affect the recorded answer. "changed": the recorded answer is no longer correct '
         '(including when what it refers to was removed, renamed or moved). "unsure": the changes might affect the answer but '
         'the evidence shown is not enough to tell.')


def _head(env, fact, ev, with_excerpt):
    ex = excerpt(env, fact, ev) if with_excerpt else ""
    p = (f"An assistant answered a question about {env.domain} at an earlier commit by calling deterministic, read-only "
         f"tools ({env.tool_names}). At a later commit the same tool calls were "
         "re-run. Some of their outputs changed. Decide whether the recorded answer is still correct at the later commit.\n\n"
         f"Question: {fact['question']}\n\nRecorded answer: {ev.K}\n\n")
    if ex:
        p += f"Excerpt of the original supporting evidence (tool outputs at the earlier commit):\n{ex}\n\n"
    return p


def prompt_delta(env, fact, ev, delta_text, with_excerpt=True, ref_label="the earlier commit"):
    """pilot7's judge prompt (byte-identical for env=PyRepoEnv)."""
    return _head(env, fact, ev, with_excerpt) + (
        f"Changed tool outputs: unified diff per call, '-' = output at {ref_label}, '+' = output now (line-number prefixes "
        "removed). Calls not listed returned exactly the same output as before.\n\n"
        f"{delta_text}\n\n{INSTR}")


def prompt_screen(env, fact, ev, part_text, i, n):
    return (f"An assistant answered a question about {env.domain} at an earlier commit by calling deterministic, read-only "
            f"tools ({env.tool_names}). At a later commit the same tool calls were re-run and some outputs changed. The change "
            "is too large to show at once, so it is split into parts.\n\n"
            f"Question: {fact['question']}\n\nRecorded answer: {ev.K}\n\n"
            + (f"Excerpt of the original supporting evidence (tool outputs at the earlier commit):\n{excerpt(env, fact, ev)}\n\n")
            + f"Part {i} of {n} of the changed tool outputs: unified diff per call, '-' = output at the earlier commit, '+' = output now "
            "(line-number prefixes removed).\n\n"
            f"{part_text}\n\n"
            'Could the changes in THIS PART affect whether the recorded answer is still correct (including removing, renaming or '
            'moving what it refers to)? Reply with JSON only: {"could_affect": true | false, "reason": "<at most 15 words>"}. '
            'Answer false only if these changes clearly cannot affect the answer.')


def prompt_rdiff(env, fact, ev, rdiff, with_excerpt=True):
    """pilot7 variant (c) / pilot3 G-LLMDIFF-style prompt: read-set repository diff instead of the evidence delta."""
    ex = excerpt(env, fact, ev) if with_excerpt else ""
    p = (f"An assistant answered a question about {env.domain} at an earlier commit by reading some files with "
         "deterministic, read-only tools. Decide whether the recorded answer is still correct at a later commit.\n\n"
         f"Question: {fact['question']}\n\nRecorded answer: {ev.K}\n\n")
    if ex:
        p += f"Excerpt of the original supporting evidence (tool outputs at the earlier commit):\n{ex}\n\n"
    p += ("Below is the unified diff, between the earlier commit and the later commit, of the files that were consulted when "
          f"the answer was derived (other files are not shown):\n\n{rdiff}\n\n{INSTR}")
    return p
