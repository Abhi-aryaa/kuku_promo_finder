"""Streamlit UI: upload a screenplay zip, pick a judge, get ranked promo cuts, compare runs. Run: streamlit run app.py"""
import streamlit as st, os, json, tempfile, time, zipfile, re, math
from runner import build_cmd, stream

HERE = os.path.dirname(os.path.abspath(__file__))
st.set_page_config(page_title="Promo Finder", layout="wide")
ss = st.session_state
for k, v in (("runs", {}), ("csv", {}), ("summary", {}), ("last", None)): ss.setdefault(k, v)

st.title("Promo Finder - ranked 20-60s promo cuts from microdrama screenplays")
st.caption("Screenplays -> every 20-60 s cut -> rule scores (hook / cliffhanger / stand-alone) -> an LLM judge re-scores the shortlist -> ranked promos with exact timestamps. A human editor makes the final call.")

up = st.file_uploader("Screenplay pack (.zip of episode-*.txt)", type="zip")
n_eps = 0
if up:
    try: n_eps = sum(1 for n in zipfile.ZipFile(up).namelist() if re.search(r"episode-\d+.*\.txt$", n)); up.seek(0)
    except Exception: pass

prov = st.selectbox("Judge", ["none (free: rules only, no API)", "gemini", "anthropic", "openai", "cache (replay the bundled Claude-in-chat scores)"])
p = prov.split()[0]; live = p in ("gemini", "anthropic", "openai")
model = st.text_input("Model override (optional)", "", placeholder="blank = default (Gemini: gemini-3.5-flash-lite, then any Flash-Lite your key can use)")
key = st.text_input("API key (used for this run only, never saved)", type="password") if live else ""

c1, c2, c3, c4 = st.columns(4)
keep = c1.slider("Max promos per episode", 1, 4, 2)
per_ep = c2.slider("Clips judged per episode", 1, 3, 2)
batch = c3.slider("Clips per API call", 1, 8, 5, help="5 clips per call = ~20 calls for 50 episodes")
gap = c4.number_input("Seconds between calls", 0.0, 30.0, 4.2 if p == "gemini" else 0.0, 0.2, help="Free Gemini Flash-Lite allows 15 calls/min: 4.2 s is safe")

ok = True
if live:
    calls = math.ceil(n_eps * per_ep / batch) if n_eps else None
    st.info(f"About **{calls if calls else 'N'} live API calls**" + (f" (~{calls * (gap + 6) / 60:.0f} min)." if calls else ".") + " Free-tier quotas are small: run once, then compare the saved result below.")
    ok = st.checkbox("I understand this uses my API quota")

if st.button("Find promos", type="primary", disabled=not (up and ok)):
    d = tempfile.mkdtemp(); zp = os.path.join(d, "pack.zip"); open(zp, "wb").write(up.read()); out = os.path.join(d, "out")
    env = dict(os.environ)
    if key: env[{"gemini": "GEMINI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}[p]] = key
    status = st.empty(); bar = st.progress(0.0); t0 = time.time(); logs = []; rc = None
    status.info("Starting: parsing episodes and building candidate cuts (about 40 s before the judge starts)...")
    for kind, val in stream(build_cmd(zp, out, p, keep, per_ep, batch, gap, os.path.join(HERE, "llm_cache.json"), model.strip()), env):
        if kind == "done": rc = val; break
        logs.append(val)
        m = re.match(r"PROGRESS: Judging batch (\d+)/(\d+)", val)
        if m: a, b = int(m.group(1)), int(m.group(2)); bar.progress(a / b); status.info(f"Judge '{p}': batch {a}/{b}  |  {time.time() - t0:.0f}s elapsed")
        elif val.startswith("STATUS:"): status.info(val[7:].strip())
    bar.empty(); status.empty()
    if rc:
        st.error("Run failed. Last messages:\n\n" + "\n".join(logs[-10:]))
    else:
        P = json.load(open(os.path.join(out, "promos.json"), encoding="utf-8"))
        label = f"{p}{':' + model.strip() if model.strip() else ''} #{len(ss['runs']) + 1}"
        ss["runs"][label] = P; ss["last"] = label
        ss["summary"][label] = [l for l in logs if l.startswith(("Judge ", "WARNING"))]
        ss["csv"][label] = open(os.path.join(out, "promos.csv"), encoding="utf-8").read()

if ss["last"]:                                   # results live in session state, so downloads / sliders never wipe them
    lab = ss["last"]; P = ss["runs"][lab]; fn = re.sub(r"[^A-Za-z0-9_.-]", "_", lab)
    st.success(f"Run '{lab}': {len(P)} promos")
    for l in ss["summary"].get(lab, []): st.info(l)
    st.dataframe([{"rank": x["rank"], "tier": x["tier"], "cut": " + ".join(f"Ep{s['episode']} {s['start']}-{s['end']}" for s in x["segments"]), "sec": x["duration_s"],
                   "hook": x["hook"][:80], "cliffhanger": x["cliffhanger"][:80], "why": x["why_it_works"], "issue": x["known_issue"], "scored_by": x["scored_by"]} for x in P], use_container_width=True)
    for x in P[:10]:
        with st.expander(f"#{x['rank']} " + " + ".join(f"Ep{s['episode']} {s['start']}-{s['end']}" for s in x["segments"])): st.code(x["transcript"])
    d1, d2 = st.columns(2)
    d1.download_button("Download promos.json", json.dumps(P, indent=1, ensure_ascii=False), f"promos_{fn}.json")
    d2.download_button("Download promos.csv", ss["csv"][lab], f"promos_{fn}.csv")

st.divider()
st.header("Compare runs (e.g. rules-only vs two different judge models)")
st.caption("Runs from this session appear here automatically. You can also add promos.json files from earlier runs.")
names = st.multiselect("Runs from this session", list(ss["runs"]), default=list(ss["runs"]))
ups = st.file_uploader("Extra promos.json files", type="json", accept_multiple_files=True, key="cmp")
k = st.slider("Compare top-K", 5, 30, 10)
runs = [(n, ss["runs"][n]) for n in names] + [(u.name, json.load(u)) for u in ups]
if len(runs) >= 2:
    from compare import report, matrix
    st.markdown(report(runs[0][1], runs[1][1], k, runs[0][0], runs[1][0]) if len(runs) == 2 else matrix(runs, k))
    st.caption("'Same clip' = two promos overlapping by at least half of the shorter one. For a fair comparison use the same 'clips per episode' and 'max promos' settings in every run.")
else:
    st.caption("Make at least two runs (e.g. 'none' and 'gemini') or upload two promos.json files to compare.")
