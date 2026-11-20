"""LLM judge for shortlisted candidates. Provider-agnostic: swap model with --provider/--model or env vars.
Providers: gemini (free tier: gemini-3.5-flash-lite / gemini-3.1-flash-lite), anthropic, openai, cache, none."""
import json, os, re, urllib.request, urllib.error, time, threading
from parser import fmt

RUBRIC = """You are a senior social-video editor for a vertical microdrama app (ReelShort / DramaBox style).
You judge whether a clip cut from the screenplay would work as a 20-60s PROMO on Instagram/TikTok/YouTube Shorts to pull in NEW viewers who have never seen the show.

A great promo:
1. HOOK: in the first 3 seconds something makes a scrolling viewer stop (slap, reveal, shocking line, threat, public humiliation).
2. CLIFFHANGER: it ends on an unresolved moment so the viewer must know what happens next (not a resolved scene, not a calm closing line).
3. STANDALONE: a stranger understands who is who, and what is at stake, without prior episodes. Penalise clips that need backstory.
4. NO big spoiler: it should not give away the show's central twist or ending.

SHOW CONTEXT (what the show is about, from episode 1-2 loglines):
{context}

Score the clip below. Return ONLY JSON, no markdown:
{{"hook_score":0-10,"cliffhanger_score":0-10,"standalone_score":0-10,"spoiler_risk":0-10,"overall":0-10,
 "hook_line":"the line/action in the first 3s","cliffhanger":"what is left unresolved at the end",
 "why":"ONE sentence on why this works or fails as a promo",
 "problem":"none | needs_context | weak_hook | weak_ending | slow | spoiler | other: ...",
 "trim_start":null or a start time (mm:ss.s) taken from the transcript lines below if a tighter start is better,
 "trim_end":null or an end time (mm:ss.s) taken from the transcript if a better cut exists}}
Be a harsh judge: most clips should score 4-6; reserve 8+ for clips you would genuinely post first.

CLIP (episode {ep}, {s}-{e}, {dur:.0f}s). Episode logline: {logline}
{transcript}
"""

BATCH_RUBRIC = """You are a senior social-video editor for a vertical microdrama app (ReelShort / DramaBox style).
Judge each of the {n} clips below as a 20-60s PROMO on Instagram/TikTok/YouTube Shorts for NEW viewers who have never seen the show.

A great promo:
1. HOOK: in the first 3 seconds something makes a scrolling viewer stop (slap, reveal, shocking line, threat, public humiliation).
2. CLIFFHANGER: ends on an unresolved moment so the viewer must know what happens next.
3. STANDALONE: a stranger understands who is who and what is at stake without prior episodes.
4. NO big spoiler: does not give away the show's central twist or ending.

SHOW CONTEXT:
{context}

Return ONLY a JSON object with a single key "results" mapping each clip_id string to its score object:
{{"results": {{
  "<clip_id>": {{
    "hook_score":0-10,"cliffhanger_score":0-10,"standalone_score":0-10,"spoiler_risk":0-10,"overall":0-10,
    "hook_line":"the line/action in the first 3s","cliffhanger":"what is left unresolved at the end",
    "why":"ONE sentence on why this works or fails as a promo",
    "problem":"none | needs_context | weak_hook | weak_ending | slow | spoiler | other: ...",
    "trim_start":null or "mm:ss.s","trim_end":null or "mm:ss.s"
  }}
}}}}
Be a harsh judge: most clips should score 4-6; reserve 8+ for clips you would genuinely post first.

{clips_block}
"""

# Official active free-tier high-quota models (15 RPM / 500 RPD on Google AI Studio)
DEFAULT_GEMINI_MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
_WORKING_GEMINI_MODEL = None
_GEMINI_LIST = None
_CACHE_LOCK = threading.Lock()
SLEEP = 0.0
STATS = {"live": 0, "cached": 0}


def render(ep, segments, max_action=160):
    out = []
    for i, sg in enumerate(segments):
        if len(segments) > 1:
            out.append(f"--- SEGMENT {i+1}: {fmt(sg.start)}-{fmt(sg.end)} ---")
        for b in ep.beats:
            if b.end > sg.start + 0.05 and b.start < sg.end - 0.05 and b.kind != "CAMERA":
                if b.kind == "DIALOGUE":
                    d = f" ({b.delivery})" if b.delivery else ""
                    out.append(f"[{fmt(b.start)}] {b.speaker}{d}: {b.text}")
                else:
                    out.append(f"[{fmt(b.start)}] ({b.kind}) {b.text[:max_action]}")
    return "\n".join(out)


def build_prompt(context, ep, cand):
    segs = cand.segments
    return RUBRIC.format(
        context=context,
        ep=ep.num,
        s=fmt(segs[0].start),
        e=fmt(segs[-1].end),
        dur=cand.duration,
        logline=ep.logline[:300],
        transcript=render(ep, segs),
    )


def build_batch_prompt(context, items):
    """items: list of (clip_id, ep, cand)"""
    blocks = []
    for cid, ep, cand in items:
        segs = cand.segments
        blocks.append(
            f"=== CLIP {cid} (episode {ep.num}, {fmt(segs[0].start)}-{fmt(segs[-1].end)}, {cand.duration:.0f}s) ===\n"
            f"Episode logline: {ep.logline[:240]}\n"
            f"{render(ep, segs)}"
        )
    return BATCH_RUBRIC.format(context=context, n=len(items), clips_block="\n\n".join(blocks))


def _post(url, headers, body, retries=3):
    data = json.dumps(body).encode()
    for k in range(retries):
        try:
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json", **headers}
            )
            return json.loads(urllib.request.urlopen(req, timeout=60).read())
        except urllib.error.HTTPError as ex:
            err_body = ex.read()[:400].decode("utf-8", errors="replace")
            # Do not retry if quota is 0 / billing limit; only retry transient rate-limit or 5xx
            if ex.code in (429, 500, 503) and k < retries - 1:
                if "limit: 0" in err_body.lower():
                    raise RuntimeError(f"{ex.code}: {err_body}")
                if ex.code == 429 and re.search(r"PerDay|per day|daily", err_body, re.I):
                    raise RuntimeError(f"429 DAILY QUOTA used up for this model: {err_body}")
                time.sleep(5 * (k + 1))
                continue
            raise RuntimeError(f"{ex.code}: {err_body}")


def _gemini_models(key):
    """Models this key can call, Flash-Lite only (largest free quota), newest first. Cached after the first lookup."""
    global _GEMINI_LIST
    if _GEMINI_LIST is None:
        names = []
        try:
            d = json.loads(urllib.request.urlopen(f"https://generativelanguage.googleapis.com/v1beta/models?pageSize=200&key={key}", timeout=30).read())
            names = [m["name"].split("/")[-1] for m in d.get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])]
        except Exception:
            pass
        bad = ("tts", "image", "live", "audio", "transcribe", "embedding", "robotics", "computer", "learnlm", "gemma", "imagen", "veo")
        _GEMINI_LIST = sorted([n for n in names if "flash" in n and "lite" in n and not any(b in n for b in bad)], reverse=True)
    return _GEMINI_LIST


def call_model(provider, model, prompt):
    global _WORKING_GEMINI_MODEL
    if provider == "gemini":
        key = os.environ["GEMINI_API_KEY"]
        if model:
            candidates = [model]
        elif _WORKING_GEMINI_MODEL:
            candidates = [_WORKING_GEMINI_MODEL]
        else:
            candidates = list(DEFAULT_GEMINI_MODELS)

        last = None
        tried = set()
        while candidates:
            m = candidates.pop(0)
            if m in tried: continue
            tried.add(m)
            try:
                gen_cfg = {
                    "temperature": 0.2,
                    "responseMimeType": "application/json",
                }
                r = _post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}",
                    {},
                    {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": gen_cfg},
                )
                if not model:
                    _WORKING_GEMINI_MODEL = m
                return r["candidates"][0]["content"]["parts"][0]["text"]
            except RuntimeError as ex:
                last = f"[{m}] {ex}"
                if "DAILY QUOTA" in str(ex):
                    _WORKING_GEMINI_MODEL = None          # this model is finished for today: try another
                elif not str(ex).startswith("404"):
                    break
                if not candidates and not model:          # defaults exhausted: try what this key can actually use
                    candidates = [x for x in _gemini_models(key)[:3] + ["gemini-2.5-flash-lite"] if x not in tried]
        raise RuntimeError(last)

    if provider == "anthropic":
        key = os.environ["ANTHROPIC_API_KEY"]
        model = model or "claude-haiku-4-5"
        r = _post(
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": key, "anthropic-version": "2023-06-01"},
            {"model": model, "max_tokens": 2000, "temperature": 0.2, "messages": [{"role": "user", "content": prompt}]},
        )
        return r["content"][0]["text"]

    if provider == "openai":
        key = os.environ["OPENAI_API_KEY"]
        model = model or "gpt-4o-mini"
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        r = _post(
            f"{base}/chat/completions",
            {"Authorization": f"Bearer {key}"},
            {
                "model": model,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        return r["choices"][0]["message"]["content"]

    raise ValueError(provider)


def parse_json(txt):
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", txt, re.S)
    return json.loads(m.group(0))


def cand_key(cand):
    return "|".join(f"{s.episode}:{s.start:.2f}-{s.end:.2f}" for s in cand.segments)


def _load_cache(cache_path):
    if cache_path and os.path.exists(cache_path):
        try:
            return json.load(open(cache_path, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache_path, updates):
    if not cache_path or not updates:
        return
    with _CACHE_LOCK:
        cache = _load_cache(cache_path)
        cache.update(updates)
        json.dump(cache, open(cache_path, "w", encoding="utf-8"), indent=1)


def judge(provider, model, context, ep, cand, cache_path=None):
    """Single-clip judge (kept for backwards compatibility)."""
    return judge_batch(provider, model, context, [(ep, cand)], cache_path=cache_path)[0]


def judge_batch(provider, model, context, ep_cands, cache_path=None):
    """Judges a batch of (ep, cand) tuples in ONE API call (saves 5x quota & time)."""
    results = [None] * len(ep_cands)
    to_call = []  # (idx, clip_id, cand_key, ep, cand)
    live = provider not in ("none", "cache")
    read_path = cache_path
    if live and cache_path:                       # live judgments go to llm_cache_<provider>.json, never into the bundled file
        cache_path = cache_path[:-5] + f"_{provider}.json" if cache_path.endswith(".json") else cache_path + f".{provider}"

    with _CACHE_LOCK:
        cache = _load_cache(read_path)
        if live: cache.update(_load_cache(cache_path))
        for i, (ep, cand) in enumerate(ep_cands):
            k = cand_key(cand)
            entry = cache.get(k)
            if entry and (provider == "cache" or str(entry.get("judge", "")).startswith(provider)):
                STATS["cached"] += 1
                results[i] = entry
            elif provider not in ("none", "cache"):
                to_call.append((i, f"C{i+1}", k, ep, cand))

    if not to_call:
        return results

    try:
        if len(to_call) == 1:
            idx, _, k, ep, cand = to_call[0]
            j = parse_json(call_model(provider, model, build_prompt(context, ep, cand)))
            j["judge"] = provider + (":" + model if model else "")
            results[idx] = j
            STATS["live"] += 1
            _save_cache(cache_path, {k: j})
        else:
            prompt = build_batch_prompt(context, [(cid, ep, cand) for _, cid, _, ep, cand in to_call])
            raw = parse_json(call_model(provider, model, prompt))
            res_map = raw.get("results", raw)
            updates = {}
            for idx, cid, k, _, _ in to_call:
                j = res_map.get(cid)
                if isinstance(j, dict):
                    j["judge"] = provider + (":" + model if model else "")
                    results[idx] = j
                    updates[k] = j
                    STATS["live"] += 1
                else:
                    results[idx] = {"error": f"Missing {cid} in batch response"}
            _save_cache(cache_path, updates)
        if SLEEP:
            time.sleep(SLEEP)
    except Exception as ex:
        err = {"error": str(ex)[:250]}
        for idx, _, _, _, _ in to_call:
            results[idx] = err

    return results
