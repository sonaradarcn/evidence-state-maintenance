"""Cached LLM client for ESM (OpenAI-compatible Ollama servers).

* Every call is cached on disk keyed by sha256(model, messages, tools, max_tokens, temperature, extra[, nonce]).
  Read-through caches (ESM_LLM_READ_THROUGH) are consulted on a miss; a hit is copied into the own cache.
  The cache is never invalidated.
* A ledger line (tag, model, tokens, latency) is appended for every non-cached call.
* `ESM_PORTS_<model>` (e.g. ESM_PORTS_qwen3.6:27b -> env var ESM_PORTS_Q27) sets the server pool; one request in flight
  per server (qwen3.5/3.6 do not support parallel slots in Ollama).
* `ESM_LLM_OFFLINE=1` makes a cache miss raise `CacheMiss` instead of calling a server (used by analysis scripts so
  that the analysis can never silently spend tokens).
"""
import hashlib, json, os, queue, random, shutil, sys, threading, time
from pathlib import Path

DATA = Path(os.environ.get("ESM_DATA", Path(__file__).resolve().parents[1] / "esm_data"))
CACHE = DATA / "llm_cache"
CACHE.mkdir(parents=True, exist_ok=True)
LEDGER = DATA / "llm_ledger.jsonl"
# Extra read-only caches consulted on a miss (os.pathsep-separated), e.g. the dev-stage cache when running a later
# stage.  During the original runs this held the dev cache and the pilot caches.
READ_THROUGH = [Path(p) for p in os.environ.get("ESM_LLM_READ_THROUGH", "").split(os.pathsep) if p.strip()]
READ_THROUGH = [p for p in READ_THROUGH if p.resolve() != CACHE.resolve()]

# Cross-model stage (esm/results/xmodel): ESM_MAIN_MODEL replaces the main ("27B") model everywhere it is the default
# (deriver, judge, verifier, certificates, LLMDIFF judge); ESM_PORTS_Q27 then configures ITS servers.  ESM_REASONING sets
# the reasoning_effort sent to Ollama (default "none" = Qwen thinking off; gpt-oss cannot switch reasoning off -> "low").
# Unset, both default to the original values, so every earlier cache key is unchanged.
Q27, Q9 = os.environ.get("ESM_MAIN_MODEL", "ollama:qwen3.6:27b"), "ollama:qwen3.5:9b"
REASONING = os.environ.get("ESM_REASONING", "none")
PORTS = {Q27.split(":", 1)[1]: [int(p) for p in os.environ.get("ESM_PORTS_Q27", "11495").strip("\"'").split(",") if p.strip("\"'")],
         "qwen3.5:9b": [int(p) for p in os.environ.get("ESM_PORTS_Q9", "11496,11497").strip("\"'").split(",") if p.strip("\"'")]}
# NVIDIA NIM (OpenAI-compatible) backend, model "nim:<model id>": key / base URL from the environment or the project .env;
# ESM_NIM_CONC requests in flight (pool slots, "port" 0), at most ESM_NIM_RPM request starts per minute per process,
# ESM_NIM_EXTRA = JSON merged into the request body (e.g. reasoning switches); it is part of the cache key.
NIM_EXTRA = json.loads(os.environ.get("ESM_NIM_EXTRA", "{}") or "{}")
_nim_last = [0.0]


def _nim_conf():
    env = {}
    pe = Path(__file__).resolve().parents[1] / ".env"
    if pe.exists():
        for l in pe.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in l and not l.lstrip().startswith("#"):
                k, v = l.split("=", 1)
                if v.strip():
                    env.setdefault(k.strip(), v.strip().strip("\"'"))
    key = os.environ.get("NVIDIA_NIM_API_KEY") or env.get("NVIDIA_NIM_API_KEY")
    base = os.environ.get("NVIDIA_NIM_BASE_URL") or env.get("NVIDIA_NIM_BASE_URL") or "https://integrate.api.nvidia.com/v1"
    return key, base


if Q27.startswith("nim:"):
    PORTS[Q27.split(":", 1)[1]] = [0] * int(os.environ.get("ESM_NIM_CONC", "2"))


class CacheMiss(Exception):
    pass


class ServerParseError(Exception):
    """Ollama could not parse the model's own tool-call output (HTTP 500); deterministic for that prompt."""


_lock = threading.Lock()
_pools, _clients = {}, {}
STATS = {"hits": 0, "readthrough": 0, "calls": 0}


def set_ports(model, ports):
    with _lock:
        PORTS[model] = list(ports)
        _pools.pop(model, None)


def _pool(model):
    with _lock:
        if model not in _pools:
            q = queue.Queue()
            for p in PORTS[model]:
                q.put(p)
            _pools[model] = q
        return _pools[model]


def _client(port, timeout, backend="ollama"):
    from openai import OpenAI
    k = (backend, port, timeout)
    with _lock:
        if k not in _clients:
            if backend == "nim":
                key, base = _nim_conf()
                _clients[k] = OpenAI(api_key=key, base_url=base, timeout=timeout, max_retries=0)
            else:
                _clients[k] = OpenAI(api_key="ollama", base_url=f"http://127.0.0.1:{port}/v1", timeout=timeout, max_retries=0)
        return _clients[k]


def payload_of(model, messages, tools=None, max_tokens=900, temperature=0.0, extra=None, nonce=None):
    backend = model.split(":", 1)[0]
    if backend == "ollama":
        extra = dict(extra or {}, reasoning_effort=REASONING)
    elif backend == "nim" and NIM_EXTRA:
        extra = dict(extra or {}, nim_extra=NIM_EXTRA)
    p = {"model": model, "messages": messages, "tools": tools, "max_tokens": max_tokens, "temperature": temperature, "extra": extra}
    if nonce is not None:
        p["nonce"] = nonce
    return p


def key_of(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def lookup(payload):
    """Cached response or None (checks ESM's cache, then the pilots' caches)."""
    k = key_of(payload)
    p = CACHE / k[:2] / (k + ".json")
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    for rt in READ_THROUGH:
        q = rt / k[:2] / (k + ".json")
        if q.exists():
            p.parent.mkdir(exist_ok=True)
            shutil.copyfile(q, p)
            STATS["readthrough"] += 1
            return json.loads(p.read_text(encoding="utf-8"))
    return None


def chat(model, messages, tools=None, max_tokens=900, temperature=0.0, tag="", extra=None, nonce=None, attempts=8, timeout=600):
    """Returns {content, tool_calls, usage{prompt, completion}, latency, finish, cached}."""
    payload = payload_of(model, messages, tools, max_tokens, temperature, extra, nonce)
    d = lookup(payload)
    if d is not None:
        STATS["hits"] += 1
        d["cached"] = True
        return d
    backend, mname = model.split(":", 1)
    if os.environ.get("ESM_LLM_OFFLINE") == "1" or not PORTS.get(mname):
        raise CacheMiss(f"{tag} {model}")
    assert backend in ("ollama", "nim"), model
    kw = dict(model=mname, messages=messages, max_tokens=max_tokens, temperature=temperature)
    if backend == "ollama":
        kw["reasoning_effort"] = REASONING
    elif NIM_EXTRA:
        kw["extra_body"] = NIM_EXTRA
    if tools:
        kw["tools"] = tools
        kw["tool_choice"] = "auto"
    k = key_of(payload)
    path = CACHE / k[:2] / (k + ".json")
    delay, last = 5.0, None
    if backend == "nim":                               # HTTP 429 (rate limit) is transient: be patient
        attempts = max(attempts, 60)
    for attempt in range(attempts):
        port = _pool(mname).get()
        try:
            if backend == "nim":                       # request-start rate limit (per process)
                gap = 60.0 / float(os.environ.get("ESM_NIM_RPM", "7"))
                with _lock:
                    wait = _nim_last[0] + gap - time.time()
                    _nim_last[0] = max(time.time(), _nim_last[0] + gap)
                if wait > 0:
                    time.sleep(wait)
            t0 = time.time()
            r = _client(port, timeout, backend).chat.completions.create(**kw)
            lat = time.time() - t0
            m = r.choices[0].message
            tcs = [{"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments} for tc in (m.tool_calls or [])]
            u = r.usage
            d = {"content": m.content or "", "tool_calls": tcs,
                 **({"reasoning_chars": len(getattr(m, "reasoning", None) or getattr(m, "reasoning_content", None) or
                                            (getattr(m, "model_extra", None) or {}).get("reasoning") or
                                            (getattr(m, "model_extra", None) or {}).get("reasoning_content") or "")}
                    if (REASONING != "none" or backend == "nim") else {}),
                 "usage": {"prompt": getattr(u, "prompt_tokens", 0) or 0, "completion": getattr(u, "completion_tokens", 0) or 0},
                 "latency": lat, "model": model, "finish": r.choices[0].finish_reason}
            path.parent.mkdir(exist_ok=True)
            tmp = path.with_suffix(".tmp%d" % threading.get_ident())
            tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
            with _lock:
                STATS["calls"] += 1
                line = (json.dumps({"t": time.time(), "tag": tag, "model": model, **d["usage"], "lat": round(lat, 2),
                                    "port": port}) + "\n").encode()
                fd = os.open(LEDGER, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0))
                try:
                    os.write(fd, line)          # one write call per line: no interleaving between processes
                finally:
                    os.close(fd)
            d["cached"] = False
            return d
        except Exception as e:
            last = e
            # Ollama cannot parse the model's own tool call (Qwen: "XML syntax error"; gpt-oss: "error parsing tool
            # call"): deterministic at T = 0, so after 3 attempts the call fails as a ServerParseError
            if ("XML syntax error" in str(e) or "error parsing tool call" in str(e)) and attempt >= 2:
                raise ServerParseError(str(e)[:200])
            print(f"[esm.llm retry {attempt} {model}@{port}] {type(e).__name__}: {str(e)[:160]}", file=sys.stderr, flush=True)
            time.sleep(delay + random.random() * 3)
            delay = min(delay * 1.7, 90 if backend != "nim" else 180)
        finally:
            _pool(mname).put(port)
    raise RuntimeError(f"LLM failed after retries: {last}")


def json_from(text):
    import re
    text = text or ""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    cand = [m.group(1)] if m else []
    if "{" in text and "}" in text:
        cand.append(text[text.index("{"): text.rindex("}") + 1])
    for c in cand:
        try:
            return json.loads(c, strict=False)
        except Exception:
            pass
    return None
