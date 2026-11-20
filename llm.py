"""LLM judge for shortlisted candidates. Provider-agnostic: swap model with --provider/--model or env vars.
Providers: gemini (free tier), anthropic, openai (also any OpenAI-compatible endpoint via OPENAI_BASE_URL), cache (replay saved judgments), none."""
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

_WORKING_GEMINI_MODEL = None
_CACHE_LOCK = threading.Lock()


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


def _post(url, headers, body, retries=3):
    data = json.dumps(body).encode()
    for k in range(retries):
        try:
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json", **headers}
            )
            return json.loads(urllib.request.urlopen(req, timeout=45).read())
        except urllib.error.HTTPError as ex:
            err_body = ex.read()[:300].decode("utf-8", errors="replace")
            if ex.code in (429, 500, 503) and k < retries - 1:
                wait = 3 * (k + 1)
                time.sleep(wait)
                continue
            raise RuntimeError(f"{ex.code}: {err_body}")


def call_model(provider, model, prompt):
    global _WORKING_GEMINI_MODEL
    if provider == "gemini":
        key = os.environ["GEMINI_API_KEY"]
        # Use cached working model first so we NEVER repeat 404s on every single clip
        if model:
            candidates = [model]
        elif _WORKING_GEMINI_MODEL:
            candidates = [_WORKING_GEMINI_MODEL]
        else:
            candidates = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-flash-latest", "gemini-2.0-flash"]

        last = None
        for m in candidates:
            try:
                gen_cfg = {
                    "temperature": 0.2,
                    "responseMimeType": "application/json",
                }
                # Disable slow thinking tokens on 2.5 models for 5x faster JSON judging
                if "2.5" in m:
                    gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}
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
                if not str(ex).startswith("404"):
                    break
        raise RuntimeError(last)

    if provider == "anthropic":
        key = os.environ["ANTHROPIC_API_KEY"]
        model = model or "claude-haiku-4-5"
        r = _post(
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": key, "anthropic-version": "2023-06-01"},
            {"model": model, "max_tokens": 700, "temperature": 0.2, "messages": [{"role": "user", "content": prompt}]},
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


SLEEP = 0.0


def judge(provider, model, context, ep, cand, cache_path=None):
    """Returns dict judgment or None. Thread-safe caching by candidate key."""
    k = cand_key(cand)
    with _CACHE_LOCK:
        cache = json.load(open(cache_path)) if cache_path and os.path.exists(cache_path) else {}
        if k in cache:
            return cache[k]
    if provider in ("none", "cache"):
        return None
    try:
        j = parse_json(call_model(provider, model, build_prompt(context, ep, cand)))
        if SLEEP:
            time.sleep(SLEEP)
    except Exception as ex:
        return {"error": str(ex)[:200]}
    if cache_path:
        with _CACHE_LOCK:
            cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
            cache[k] = j
            json.dump(cache, open(cache_path, "w"), indent=1)
    return j
