"""Compare two runs (e.g. Gemini-judged vs Claude-judged): how much do their top-K promos agree?
Usage: python compare.py runA/promos.json runB/promos.json [K=10]"""
import json, sys

def _ov(p, q):
    ov = 0.0
    for a in p["segments"]:
        for b in q["segments"]:
            if a["episode"] == b["episode"]: ov += max(0.0, min(a["end_s"], b["end_s"]) - max(a["start_s"], b["start_s"]))
    return ov / max(1e-6, min(p["duration_s"], q["duration_s"]))

def match(p, others, thr=0.5):
    best = max(others, key=lambda q: _ov(p, q), default=None)
    return best if best and _ov(p, best) >= thr else None

def compare(A, B, k=10):
    topA, topB = A[:k], B[:k]
    rows, same = [], 0
    for p in topA:
        q = match(p, topB)
        if q: same += 1
        rows.append((p["rank"], p["segments"][0]["episode"], p["segments"][0]["start"][:5], q["rank"] if q else None))
    anyB = sum(1 for p in topA if match(p, B)); eps = len({p["segments"][0]["episode"] for p in topA} & {p["segments"][0]["episode"] for p in topB})
    return dict(k=k, same_clip_in_both_topk=same, topA_found_anywhere_in_B=anyB, shared_episodes=eps, rows=rows)

def report(A, B, k, nameA="A", nameB="B"):
    r = compare(A, B, k)
    L = [f"# {nameA} vs {nameB} (top-{k})", f"- same clip (>=50% time overlap) in both top-{k}: **{r['same_clip_in_both_topk']}/{k}**",
         f"- {nameA}'s top-{k} found anywhere in {nameB}'s list: {r['topA_found_anywhere_in_B']}/{k}", f"- episodes shared by both top-{k}s: {r['shared_episodes']}", "",
         f"| {nameA} rank | episode | start | rank in {nameB} top-{k} |", "|---|---|---|---|"]
    L += [f"| {a} | {b} | {c} | {d if d else '-'} |" for a, b, c, d in r["rows"]]
    return "\n".join(L)

if __name__ == "__main__":
    A = json.load(open(sys.argv[1])); B = json.load(open(sys.argv[2])); k = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    print(report(A, B, k))
