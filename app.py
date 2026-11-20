"""Streamlit UI: upload a screenplay zip, pick a judge model, get ranked promo cuts. Run: streamlit run app.py"""
import streamlit as st, subprocess, tempfile, os, json, sys

HERE = os.path.dirname(os.path.abspath(__file__))
st.set_page_config(page_title="Promo Finder", layout="wide")
st.title("Promo Finder - ranked 20-60s promo cuts from microdrama screenplays")

up = st.file_uploader("Screenplay pack (.zip of episode-*.txt)", type="zip")
prov = st.selectbox(
    "Judge",
    ["none (free, heuristics only)", "gemini", "anthropic", "openai", "cache (replay saved judgments)"],
)

default_model = "gemini-3.5-flash-lite" if prov == "gemini" else ""
model = st.text_input(
    "Model override (for Gemini free tier, keep 'gemini-3.5-flash-lite' or 'gemini-3.1-flash-lite' — 500 req/day)",
    value=default_model,
)
key = st.text_input("API key (kept in memory only)", type="password")

c1, c2, c3 = st.columns(3)
with c1:
    keep = st.slider("Max promos per episode", 1, 4, 2)
with c2:
    per_ep = st.slider("Candidates judged / episode", 1, 3, 2)
with c3:
    batch_size = st.slider("Clips per API call (5 = ~20 calls total)", 1, 8, 5)

if st.button("Find promos", type="primary") and up:
    d = tempfile.mkdtemp()
    zp = os.path.join(d, "pack.zip")
    open(zp, "wb").write(up.read())
    p = prov.split()[0]
    env = dict(os.environ)
    if key:
        env[{"gemini": "GEMINI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}.get(p, "X")] = key

    cache_file = os.path.join(HERE, "llm_cache.json")
    cmd = [
        sys.executable,
        "-u",
        os.path.join(HERE, "pipeline.py"),
        "--input", zp,
        "--out", os.path.join(d, "out"),
        "--provider", p,
        "--keep", str(keep),
        "--per-ep", str(per_ep),
        "--batch-size", str(batch_size),
        "--sleep", "4.2" if p == "gemini" else "0.0",
        "--cache", cache_file,
    ]
    if model.strip():
        cmd += ["--model", model.strip()]

    logs = []
    with st.status("Starting Promo Finder...", expanded=True) as status:
        progress_line = st.empty()
        progress_line.write("Parsing screenplay zip and generating candidate cuts...")
        proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=HERE)
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            logs.append(line)
            if line.startswith("STATUS:") or line.startswith("PROGRESS:"):
                progress_line.write(line.split(":", 1)[1].strip())
        stderr = proc.stderr.read()
        proc.wait()

        if proc.returncode:
            status.update(label="Run failed", state="error", expanded=True)
        else:
            status.update(label="Done! Promos ranked.", state="complete", expanded=False)

    if proc.returncode:
        st.error(stderr[-1500:] if stderr else "\n".join(logs[-10:]))
    else:
        P = json.load(open(os.path.join(d, "out", "promos.json"), encoding="utf-8"))
        st.success(f"{len(P)} promos ready")
        st.info("\n".join(logs[-4:]))
        if any(x["scored_by"] == "heuristic" for x in P) and p != "none":
            st.warning("Some or all clips were NOT scored by the model (scored_by = heuristic). See the message above.")
        st.dataframe(
            [
                {
                    "rank": x["rank"],
                    "tier": x["tier"],
                    "cut": " + ".join(f"Ep{s['episode']} {s['start']}-{s['end']}" for s in x["segments"]),
                    "sec": x["duration_s"],
                    "hook": x["hook"][:80],
                    "cliffhanger": x["cliffhanger"][:80],
                    "why": x["why_it_works"],
                    "issue": x["known_issue"],
                }
                for x in P
            ],
            use_container_width=True,
        )
        for x in P[:10]:
            with st.expander(f"#{x['rank']} " + " + ".join(f"Ep{s['episode']} {s['start']}-{s['end']}" for s in x["segments"])):
                st.code(x["transcript"])
        st.download_button("Download promos.json", json.dumps(P, indent=1), "promos.json")

st.divider()
st.header("Compare two runs (e.g. two different judge models)")
ups = st.file_uploader("promos.json files (2 or more)", type="json", accept_multiple_files=True, key="cmp")
k = st.slider("Compare top-K", 5, 30, 10)
if len(ups) >= 2:
    from compare import report, matrix
    runs = [(u.name, json.load(u)) for u in ups]
    if len(runs) == 2:
        st.markdown(report(runs[0][1], runs[1][1], k, runs[0][0], runs[1][0]))
    else:
        st.markdown(matrix(runs, k))
