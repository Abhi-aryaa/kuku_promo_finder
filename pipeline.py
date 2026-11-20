#!/usr/bin/env python3
"""Promo finder: screenplay folder -> ranked promo cuts (episode, start/end of every segment, hook, cliffhanger, why).
Usage:
  python pipeline.py --input "<folder or .zip>" --out outputs --provider none
  GEMINI_API_KEY=... python pipeline.py --input "<folder or .zip>" --provider gemini --batch-size 5 --sleep 4.2
"""
import argparse, json, csv, os, re, sys
from parser import load_pack, fmt
from candidates import singles, joins, select
import llm


def build_context(eps, n=3):
    return " ".join(e.logline for e in eps[:n])[:900]


def ts_to_sec(t):
    if t is None:
        return None
    m = re.match(r"^(\d+):(\d+(?:\.\d+)?)$", str(t).strip())
    return int(m.group(1)) * 60 + float(m.group(2)) if m else None


def apply_trim(ep, cand, j):
    """Apply LLM-suggested trim only if it stays inside the candidate, keeps 20-60s, and doesn't split a line."""
    if not j or len(cand.segments) != 1:
        return
    sg = cand.segments[0]
    s = ts_to_sec(j.get("trim_start"))
    e = ts_to_sec(j.get("trim_end"))
    ns = s if s is not None and sg.start <= s < sg.end else sg.start
    ne = e if e is not None and sg.start < e <= sg.end else sg.end
    if 20 <= ne - ns <= 60 and (ns, ne) != (sg.start, sg.end):
        for b in ep.beats:
            if b.kind == "DIALOGUE":
                if b.start < ns < b.end:
                    ns = b.start
                if b.start < ne < b.end:
                    ne = b.end
        if 20 <= ne - ns <= 60:
            sg.start, sg.end = round(ns, 2), round(ne, 2)
            cand.flags.append("llm_trimmed")


def why_template(c, ep):
    hb, cb = c.hook_beat, c.cliff_beat
    h = (
        f'opens on {hb.speaker.title()}: "{hb.text[:70]}"'
        if hb and hb.kind == "DIALOGUE"
        else (f"opens on action: {hb.text[:80]}" if hb else "weak open")
    )
    e = (
        f'ends on "{cb.text[:70]}"'
        if cb and cb.kind == "DIALOGUE"
        else (f"ends on: {cb.text[:80]}" if cb else "")
    )
    return f"{h}; {e}."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--provider", default="none", choices=["none", "gemini", "anthropic", "openai", "cache"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--cache", default="llm_cache.json")
    ap.add_argument("--per-ep", type=int, default=2, help="shortlist size per episode (default 2)")
    ap.add_argument("--keep", type=int, default=2, help="max promos kept per episode in final list")
    ap.add_argument("--min-score", type=float, default=0.0)
    ap.add_argument("--batch-size", type=int, default=5, help="clips judged per API call (default 5 -> ~20 calls for 50 eps)")
    ap.add_argument("--sleep", type=float, default=None, help="seconds between live API calls (default 4.2 for Gemini 15 RPM)")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    print("STATUS: Parsing screenplay pack...", flush=True)
    if a.input.lower().endswith(".zip"):
        import zipfile, tempfile, glob
        tmp = tempfile.mkdtemp()
        zipfile.ZipFile(a.input).extractall(tmp)
        hit = glob.glob(os.path.join(tmp, "**", "episode-*.txt"), recursive=True)
        a.input = os.path.dirname(hit[0]) if hit else tmp

    eps = load_pack(a.input)
    byn = {e.num: e for e in eps}
    ctx = build_context(eps)
    print(f"STATUS: Generating candidate cuts across {len(eps)} episodes...", flush=True)

    pool = []
    for ep in eps:
        pool += select(singles(ep) + joins(ep), per_ep=a.per_ep)
    hmax = max(c.total for c in pool)
    use_llm = a.provider != "none"
    llm.SLEEP = a.sleep if a.sleep is not None else (4.2 if a.provider == "gemini" else 0.0)

    judgments = [None] * len(pool)
    if use_llm and pool:
        bs = max(1, a.batch_size if a.provider != "cache" else len(pool))
        total_batches = (len(pool) + bs - 1) // bs
        for b_idx in range(total_batches):
            start = b_idx * bs
            end = min(len(pool), start + bs)
            batch_items = [(byn[pool[i].segments[0].episode], pool[i]) for i in range(start, end)]
            print(f"PROGRESS: Judging batch {b_idx + 1}/{total_batches} (clips {start + 1}-{end}/{len(pool)})...", flush=True)
            res = llm.judge_batch(a.provider, a.model, ctx, batch_items, a.cache)
            for offset, j in enumerate(res):
                judgments[start + offset] = j

            # Fail fast on batch 1 if EVERY clip errored (wrong key, 0 quota, bad model name)
            if b_idx == 0 and a.provider != "cache" and all(j and "error" in j for j in res):
                first_err = res[0]["error"]
                sys.exit(
                    f"Stopped immediately on batch 1 to protect your quota. Error: {first_err}\n"
                    "Tip: Use model 'gemini-3.5-flash-lite' or 'gemini-3.1-flash-lite' (500 RPD free tier)."
                )

    rows = []
    n_ok = n_err = n_missing = 0
    first_err = None
    for c, j in zip(pool, judgments):
        ep = byn[c.segments[0].episode]
        if j and "error" in j:
            n_err += 1
            first_err = first_err or j["error"]
        elif use_llm and not j:
            n_missing += 1
        if j and "error" not in j:
            n_ok += 1
            apply_trim(ep, c, j)
            ov = float(j.get("overall", 0))
            sp = float(j.get("spoiler_risk", 0))
            final = 0.20 * (c.total / hmax * 10) + 0.65 * ov + 0.15 * float(j.get("standalone_score", 5)) - 0.15 * max(0, sp - 5)
            hook = j.get("hook_line") or (c.hook_beat.text if c.hook_beat else "")
            cliff = j.get("cliffhanger") or (c.cliff_beat.text if c.cliff_beat else "")
            why = j.get("why") or why_template(c, ep)
            prob = j.get("problem", "none")
            src = "llm+heuristic"
        else:
            final = c.total / hmax * 10
            hook = c.hook_beat.text if c.hook_beat else ""
            cliff = c.cliff_beat.text if c.cliff_beat else ""
            why = why_template(c, ep)
            prob = ",".join(c.flags) or "none"
            src = "heuristic"
            j = j or {}
        rows.append(dict(c=c, ep=ep, final=round(final, 2), hook=hook, cliff=cliff, why=why, problem=prob, src=src, j=j))

    print(
        f"Judge '{a.provider}': {n_ok}/{len(pool)} clips scored ({llm.STATS['live']} live, {llm.STATS['cached']} cached), "
        f"{n_err} failed, {n_missing} not in cache.",
        flush=True,
    )
    if use_llm and a.provider != "cache" and n_ok == 0:
        sys.exit(f"ALL model calls failed. First error: {first_err}")
    if n_err:
        print(f"WARNING: {n_err} clips fell back to heuristic. First error: {first_err}", flush=True)

    rows.sort(key=lambda r: -r["final"])
    capped = []
    cnt = {}
    for r in rows:
        n = r["c"].segments[0].episode
        if cnt.get(n, 0) >= a.keep or r["final"] < a.min_score:
            continue
        cnt[n] = cnt.get(n, 0) + 1
        capped.append(r)

    kept = []
    used = {}
    rem = capped[:]
    while rem:
        best = max(rem, key=lambda r: r["final"] - 1.0 * used.get(r["c"].segments[0].episode, 0))
        rem.remove(best)
        kept.append(best)
        n = best["c"].segments[0].episode
        used[n] = used.get(n, 0) + 1

    out = []
    for i, r in enumerate(kept, 1):
        c = r["c"]
        tier = "A (post first)" if i <= 10 else ("B (post next)" if i <= 30 else "C (backlog)")
        out.append(
            {
                "rank": i,
                "tier": tier,
                "type": c.kind,
                "score": r["final"],
                "duration_s": round(c.duration, 1),
                "segments": [{"episode": s.episode, "start": fmt(s.start), "end": fmt(s.end), "start_s": s.start, "end_s": s.end} for s in c.segments],
                "hook": r["hook"],
                "cliffhanger": r["cliff"],
                "why_it_works": r["why"],
                "known_issue": r["problem"],
                "flags": c.flags,
                "sub_scores": c.scores,
                "scored_by": r["src"],
                "transcript": llm.render(r["ep"], c.segments),
            }
        )

    json.dump(out, open(os.path.join(a.out, "promos.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    with open(os.path.join(a.out, "promos.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "tier", "type", "score", "duration_s", "segments (episode start-end)", "hook", "cliffhanger", "why_it_works", "known_issue"])
        for p in out:
            w.writerow(
                [
                    p["rank"],
                    p["tier"],
                    p["type"],
                    p["score"],
                    p["duration_s"],
                    " + ".join(f"Ep{s['episode']} {s['start']}-{s['end']}" for s in p["segments"]),
                    p["hook"],
                    p["cliffhanger"],
                    p["why_it_works"],
                    p["known_issue"],
                ]
            )
    with open(os.path.join(a.out, "promos_report.md"), "w", encoding="utf-8") as f:
        f.write(
            f"# Promo finder report\n\n{len(out)} promos across {len(eps)} episodes. "
            f"Scored by: {('LLM judge on ' + str(n_ok) + '/' + str(len(pool)) + ' shortlisted clips (rest: heuristics)') if use_llm else 'heuristics only'}.\n\n"
        )
        for p in out:
            segs = " + ".join(f"**Ep {s['episode']}  {s['start']} -> {s['end']}**" for s in p["segments"])
            f.write(f"## #{p['rank']}  [{p['tier']}]  {segs}  ({p['duration_s']}s, {p['type']}, score {p['score']})\n")
            f.write(f"- **Hook:** {p['hook']}\n- **Cliffhanger:** {p['cliffhanger']}\n- **Why it works:** {p['why_it_works']}\n- **Known issue:** {p['known_issue']}\n\n```\n{p['transcript']}\n```\n\n")
    print(f"wrote {len(out)} promos to {a.out}/", flush=True)


if __name__ == "__main__":
    main()
