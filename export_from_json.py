"""Rebuild promos.csv and promos_report.md from a promos.json (e.g. one downloaded from the Streamlit app). Usage: python export_from_json.py <dir containing promos.json>"""
import json, csv, sys, os
d = sys.argv[1]; P = json.load(open(os.path.join(d, "promos.json"), encoding="utf-8"))
with open(os.path.join(d, "promos.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["rank", "tier", "type", "score", "duration_s", "segments (episode start-end)", "hook", "cliffhanger", "why_it_works", "known_issue"])
    for p in P: w.writerow([p["rank"], p["tier"], p["type"], p["score"], p["duration_s"], " + ".join(f"Ep{s['episode']} {s['start']}-{s['end']}" for s in p["segments"]), p["hook"], p["cliffhanger"], p["why_it_works"], p["known_issue"]])
with open(os.path.join(d, "promos_report.md"), "w", encoding="utf-8") as f:
    f.write(f"# Promo finder report\n\n{len(P)} promos. Scored by: {', '.join(sorted({p['scored_by'] for p in P}))}.\n\n")
    for p in P:
        segs = " + ".join(f"**Ep {s['episode']}  {s['start']} -> {s['end']}**" for s in p["segments"])
        f.write(f"## #{p['rank']}  [{p['tier']}]  {segs}  ({p['duration_s']}s, {p['type']}, score {p['score']})\n- **Hook:** {p['hook']}\n- **Cliffhanger:** {p['cliffhanger']}\n- **Why it works:** {p['why_it_works']}\n- **Known issue:** {p['known_issue']}\n\n```\n{p['transcript']}\n```\n\n")
print("wrote promos.csv and promos_report.md in", d)
