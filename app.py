"""Streamlit UI: upload a screenplay zip, pick a judge model, get ranked promo cuts. Run: streamlit run app.py"""
import streamlit as st, subprocess, tempfile, os, json, sys
HERE = os.path.dirname(os.path.abspath(__file__))
st.set_page_config(page_title="Promo Finder", layout="wide")
st.title("Promo Finder - ranked 20-60s promo cuts from microdrama screenplays")
up = st.file_uploader("Screenplay pack (.zip of episode-*.txt)", type="zip")
prov = st.selectbox("Judge", ["none (free, heuristics only)", "gemini", "anthropic", "openai", "cache (replay saved judgments)"])
model = st.text_input("Model override (optional)", "")
key = st.text_input("API key (kept in memory only)", type="password")
keep = st.slider("Max promos per episode", 1, 4, 2)
if st.button("Find promos") and up:
    d = tempfile.mkdtemp(); zp = os.path.join(d, "pack.zip"); open(zp, "wb").write(up.read())
    p = prov.split()[0]; env = dict(os.environ)
    if key: env[{"gemini": "GEMINI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}.get(p, "X")] = key
    cmd = [sys.executable, os.path.join(HERE, "pipeline.py"), "--input", zp, "--out", os.path.join(d, "out"), "--provider", p, "--keep", str(keep), "--cache", os.path.join(d, "c.json") if p != "cache" else os.path.join(HERE, "llm_cache.json")]
    if model: cmd += ["--model", model]
    with st.spinner("Parsing, generating candidates, judging..."):
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, cwd=HERE)
    if r.returncode: st.error(r.stderr[-1500:])
    else:
        P = json.load(open(os.path.join(d, "out", "promos.json")))
        st.success(f"{len(P)} promos")
        st.dataframe([{"rank": x["rank"], "tier": x["tier"], "cut": " + ".join(f"Ep{s['episode']} {s['start']}-{s['end']}" for s in x["segments"]),
                       "sec": x["duration_s"], "hook": x["hook"][:80], "cliffhanger": x["cliffhanger"][:80], "why": x["why_it_works"], "issue": x["known_issue"]} for x in P], use_container_width=True)
        for x in P[:10]:
            with st.expander(f"#{x['rank']} " + " + ".join(f"Ep{s['episode']} {s['start']}-{s['end']}" for s in x["segments"])): st.code(x["transcript"])
        st.download_button("Download promos.json", json.dumps(P, indent=1), "promos.json")

st.divider()
st.header("Compare two runs (e.g. two different judge models)")
a_up = st.file_uploader("promos.json from run 1", type="json", key="a"); b_up = st.file_uploader("promos.json from run 2", type="json", key="b")
k = st.slider("Compare top-K", 5, 30, 10)
if a_up and b_up:
    from compare import report
    st.markdown(report(json.load(a_up), json.load(b_up), k, "Run 1", "Run 2"))
