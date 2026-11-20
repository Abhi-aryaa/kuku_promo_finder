"""Compare several runs of the tool on the same pack. Usage: python eval_runs.py "A rules-only=dirA" "B Claude=dirB" "C Gemini=dirC" > comparison.md
Reports: top-K overlap for every pair, rank agreement of final scores on shared clips, and a faithfulness check (is the quoted hook really in the transcript?)."""
import json, re, sys, statistics, os
from compare import compare, _ov

def spearman(x, y):
    def rk(v):
        s = sorted(range(len(v)), key=lambda i: v[i]); r = [0] * len(v)
        for k, i in enumerate(s): r[i] = k
        return r
    a, b = rk(x), rk(y); n = len(a); ma, mb = sum(a) / n, sum(b) / n
    return sum((p - ma) * (q - mb) for p, q in zip(a, b)) / ((sum((p - ma) ** 2 for p in a) ** .5) * (sum((q - mb) ** 2 for q in b) ** .5))

def match(p, L):
    b = max(L, key=lambda q: _ov(p, q)); return b if _ov(p, b) >= 0.5 else None

runs = []
for a in sys.argv[1:]:
    name, path = a.split("=", 1); runs.append((name, json.load(open(os.path.join(path, "promos.json"), encoding="utf-8"))))
norm = lambda s: re.sub(r"[^a-z0-9 ]", "", s.lower())
print("# Comparison of runs\n")
print("| run | promos | scored by | median length (s) | trims applied | hook quoted verbatim from transcript |\n|---|---|---|---|---|---|")
for n, P in runs:
    sb = ",".join(sorted({p["scored_by"] for p in P})); hk = sum(1 for p in P if norm(p["hook"])[:35] and norm(p["hook"])[:35] in norm(p["transcript"]))
    print(f"| {n} | {len(P)} | {sb} | {statistics.median(p['duration_s'] for p in P):.0f} | {sum('llm_trimmed' in p['flags'] for p in P)} | {hk}/{len(P)} |")
print("\n## Same clip in both top-10 / top-20 (overlap of at least half of the shorter clip)\n\n| pair | top-10 | top-20 | rank agreement (Spearman) on shared clips |\n|---|---|---|---|")
for i in range(len(runs)):
    for j in range(i + 1, len(runs)):
        (n1, A), (n2, B) = runs[i], runs[j]
        pr = [(match(x, B), x) for x in A]; pr = [(b, a) for b, a in pr if b]
        rho = spearman([a["score"] for b, a in pr], [b["score"] for b, a in pr]) if len(pr) > 5 else float("nan")
        print(f"| {n1} vs {n2} | {compare(A, B, 10)['same_clip_in_both_topk']}/10 | {compare(A, B, 20)['same_clip_in_both_topk']}/20 | {rho:.2f} ({len(pr)} shared clips) |")
if len(runs) >= 3:
    print("\n## Clips that appear in the top-10 of every LLM-judged run (the most trustworthy picks)\n")
    L = [P for n, P in runs[1:]]
    for p in L[0][:10]:
        if all(match(p, q[:10]) for q in L[1:]): print(f"- Ep{p['segments'][0]['episode']} " + " + ".join(f"{s['start'][:5]}-{s['end'][:5]}" for s in p['segments']) + f" ({p['duration_s']} s): {p['hook'][:80]}")
