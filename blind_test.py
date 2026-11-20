"""Blind human test: mix top-N clips from each run with N RANDOM valid windows, hide the source, get ratings, reveal.
  python blind_test.py make    <input folder|zip> <n> <runA/promos.json> [<runB/promos.json> ...]   -> blind_sheet.csv (give to raters) + blind_key.csv (keep secret)
  python blind_test.py analyze blind_sheet_filled.csv blind_key.csv                                -> mean ratings per source
Raters score each clip 1-5 on: hook, cliffhanger, standalone (blank columns in the sheet)."""
import sys, csv, json, random, os, glob, zipfile, tempfile, statistics
from parser import load_pack, fmt
from candidates import singles
import llm

def load(inp):
    if inp.endswith(".zip"):
        t = tempfile.mkdtemp(); zipfile.ZipFile(inp).extractall(t); inp = os.path.dirname(glob.glob(t + "/**/episode-*.txt", recursive=True)[0])
    return {e.num: e for e in load_pack(inp)}

def make(inp, n, runs):
    random.seed(7); eps = load(inp); items = []
    for path in runs:
        P = json.load(open(path)); name = os.path.basename(os.path.dirname(path)) or path
        for p in P[:n]: items.append((name, p["segments"], p["duration_s"]))
    used = {(s["episode"]) for _, segs, _ in items for s in segs}
    for _ in range(n):                                          # random baseline: valid 20-60 s windows on line boundaries
        ep = random.choice(list(eps.values())); c = random.choice(singles(ep)); sg = c.segments[0]
        items.append(("RANDOM", [{"episode": sg.episode, "start_s": sg.start, "end_s": sg.end}], round(c.duration, 1)))
    random.shuffle(items)
    with open("blind_sheet.csv", "w", newline="", encoding="utf-8") as f, open("blind_key.csv", "w", newline="", encoding="utf-8") as k:
        w, wk = csv.writer(f), csv.writer(k); w.writerow(["clip_id", "length_s", "transcript", "hook_1to5", "cliffhanger_1to5", "standalone_1to5"]); wk.writerow(["clip_id", "source", "segments"])
        for i, (src, segs, dur) in enumerate(items, 1):
            txt = "\n".join(llm.render(eps[s["episode"]], [type("S", (), {"start": s["start_s"], "end": s["end_s"]})()]) for s in segs)
            w.writerow([f"C{i:02d}", dur, txt, "", "", ""]); wk.writerow([f"C{i:02d}", src, " + ".join(f"Ep{s['episode']} {fmt(s['start_s'])[:5]}-{fmt(s['end_s'])[:5]}" for s in segs)])
    print(f"wrote blind_sheet.csv ({len(items)} clips) and blind_key.csv")

def analyze(sheet, key):
    src = {r["clip_id"]: r["source"] for r in csv.DictReader(open(key, encoding="utf-8"))}; by = {}
    for r in csv.DictReader(open(sheet, encoding="utf-8")):
        try: v = [float(r[c]) for c in ("hook_1to5", "cliffhanger_1to5", "standalone_1to5")]
        except ValueError: continue
        by.setdefault(src[r["clip_id"]], []).append(v)
    print("source | n clips | hook | cliffhanger | standalone | average")
    for s, vs in sorted(by.items()):
        m = [statistics.mean(x[i] for x in vs) for i in range(3)]; print(f"{s} | {len(vs)} | " + " | ".join(f"{x:.2f}" for x in m) + f" | {statistics.mean(m):.2f}")

if __name__ == "__main__":
    if sys.argv[1] == "make": make(sys.argv[2], int(sys.argv[3]), sys.argv[4:])
    else: analyze(sys.argv[2], sys.argv[3])
