"""How good is the cheap heuristic ranker vs the LLM judge? Writes raw_outputs/eval/agreement.md. Usage: python eval_agreement.py <input_folder_or_zip>"""
import json, sys, os, statistics, glob, zipfile, tempfile
from parser import load_pack, fmt
from candidates import singles, joins, select
import llm
inp = sys.argv[1]
if inp.endswith(".zip"):
    t = tempfile.mkdtemp(); zipfile.ZipFile(inp).extractall(t); inp = os.path.dirname(glob.glob(t + "/**/episode-*.txt", recursive=True)[0])
eps = load_pack(inp); pool = []
for ep in eps: pool += select(singles(ep) + joins(ep), per_ep=3)
cache = json.load(open("llm_cache.json"))
H = [c.total for c in pool]; L = [cache[llm.cand_key(c)]["overall"] for c in pool]; n = len(pool)
def rank(x):
    s = sorted(range(len(x)), key=lambda i: x[i]); r = [0] * len(x)
    for k, i in enumerate(s): r[i] = k
    return r
rh, rl = rank(H), rank(L); mh, ml = sum(rh) / n, sum(rl) / n
rho = sum((a - mh) * (b - ml) for a, b in zip(rh, rl)) / ((sum((a - mh) ** 2 for a in rh) ** .5) * (sum((b - ml) ** 2 for b in rl) ** .5))
order_h = sorted(range(n), key=lambda i: -H[i]); order_l = sorted(range(n), key=lambda i: -L[i])
top = lambda o, k: set(o[:k])
lab = lambda i: f"Ep{pool[i].segments[0].episode} {fmt(pool[i].segments[0].start)[:5]}-{fmt(pool[i].segments[-1].end)[:5]}"
out = ["# Heuristic ranker vs LLM judge (141-candidate shortlist)", "",
 f"- Spearman rank correlation: **{rho:.2f}**",
 f"- Overlap of top-10 / top-20 / top-30: **{len(top(order_h,10)&top(order_l,10))} / {len(top(order_h,20)&top(order_l,20))} / {len(top(order_h,30)&top(order_l,30))}**",
 f"- Mean judge score: heuristic top-20 = {statistics.mean(L[i] for i in order_h[:20]):.2f} vs shortlist average {statistics.mean(L):.2f}; {sum(L[i]>=6 for i in order_h[:20])}/20 of the heuristic top-20 scored >= 6",
 "", "## Heuristic false positives (high heuristic rank, judge <= 5.0)"]
for i in order_h[:25]:
    if L[i] <= 5.0: out.append(f"- {lab(i)}: heuristic rank {order_h.index(i)+1}, judge {L[i]} ({cache[llm.cand_key(pool[i])]['problem']})")
out += ["", "## Heuristic misses (judge >= 7.0, heuristic rank > 30)"]
for i in order_l[:25]:
    if L[i] >= 7.0 and order_h.index(i) >= 30: out.append(f"- {lab(i)}: heuristic rank {order_h.index(i)+1}, judge {L[i]}")
os.makedirs("../raw_outputs/eval", exist_ok=True); open("../raw_outputs/eval/agreement.md", "w").write("\n".join(out) + "\n"); print("\n".join(out))
