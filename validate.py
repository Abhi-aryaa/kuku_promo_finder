"""Sanity checks + quality report on a run's promos.json. Usage: python validate.py <outputs_dir> <input_folder>"""
import json, sys, statistics, re
import os, glob, zipfile, tempfile
from parser import load_pack
out, inp = sys.argv[1], sys.argv[2]
if inp.lower().endswith(".zip"):
    t = tempfile.mkdtemp(); zipfile.ZipFile(inp).extractall(t); inp = os.path.dirname(glob.glob(t + "/**/episode-*.txt", recursive=True)[0])
P = json.load(open(f"{out}/promos.json")); eps = {e.num: e for e in load_pack(inp)}
bad = []; starts_speech = ends_ep_end = 0; durs = []
for p in P:
    tot = 0
    for s in p["segments"]:
        ep = eps[s["episode"]]; a, b = s["start_s"], s["end_s"]; tot += b - a
        if not (0 <= a < b <= ep.duration + 0.01): bad.append((p["rank"], "out of range"))
        for x in ep.beats:
            if x.kind == "DIALOGUE" and (x.start < a - 0.01 < x.end - 0.3 or x.start + 0.3 < b < x.end - 0.01): bad.append((p["rank"], "cuts a line", x.text[:30]))
        if any(x.kind == "DIALOGUE" and x.start <= a + 1.5 and x.end > a for x in ep.beats): starts_speech += 1
        if ep.duration - b <= 1.6: ends_ep_end += 1
    if not (20 <= tot <= 60.05): bad.append((p["rank"], "duration", round(tot, 1)))
    durs.append(tot)
n = len(P); eps_cov = len({s["episode"] for p in P for s in p["segments"]})
cnt = lambda f: sum(1 for p in P if f(p))
lines = [f"# Automatic validation of {out}/promos.json",
 f"- promos: {n} across {eps_cov}/50 episodes; joined cuts: {cnt(lambda p: p['type']=='joined')}",
 f"- hard-rule violations (duration outside 20-60s, cut mid-line, out of range): {len(bad)} {bad[:5]}",
 f"- duration: median {statistics.median(durs):.0f}s, min {min(durs):.0f}s, max {max(durs):.0f}s",
 f"- segments that open on speech within 1.5s: {starts_speech}/{sum(len(p['segments']) for p in P)}",
 f"- segments ending within 1.6s of the episode's end (natural cliffhanger): {ends_ep_end}",
 f"- flagged known_issue != none: {cnt(lambda p: p['known_issue'] not in ('none',''))}  (spoiler: {cnt(lambda p: 'spoiler' in p['known_issue'])}, needs_context: {cnt(lambda p: 'needs_context' in p['known_issue'])})",
 f"- tier A/B/C: {cnt(lambda p: p['tier'][0]=='A')}/{cnt(lambda p: p['tier'][0]=='B')}/{cnt(lambda p: p['tier'][0]=='C')}"]
open(f"{out}/validation.md", "w").write("\n".join(lines) + "\n"); print("\n".join(lines))
