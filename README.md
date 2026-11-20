# Promo Finder

Finds the best 20-60 second **promo clips** in microdrama screenplays, so an editor does not have to watch every episode.
For every promo it gives: the episode, the start and end time of each segment, the hook, the cliffhanger, a one-line reason, a rank, and a known-issue flag.

Built for the Kuku AI Generalist assignment (Problem 1).

## How it works (in plain words)

1. **Read** the screenplay files (`parser.py`). Every line of dialogue and action has a start and end time.
2. **List every possible clip** (`candidates.py`): every 20-60 s stretch that starts and ends on a line, so no sentence is ever cut in half. About 20,000 clips for 50 episodes.
3. **Score with simple rules** (`scoring.py`): is there a strong first 3 seconds? does it end unresolved? can a stranger follow it? is it fast? is it a big spoiler? Keep the best 2 per episode (99 clips). No AI needed so far.
4. **Ask an AI judge** (`llm.py`) to score those clips, 5 clips per call (about 20 calls). The AI only scores - the code decides all timestamps.
5. **Rank** (`pipeline.py`): combine rule score and AI score, spread the top list across episodes, write the files.
6. **A human editor** picks from the ranked list.

## Quick start

You need Python 3.9+. The core tool uses only the standard library.

```bash
# 1) Free, no AI, no key
python pipeline.py --input "your_screenplays.zip" --out my_run --provider none

# 2) With an AI judge (pick one; set your key first)
set GEMINI_API_KEY=your_key            # Windows   (Mac/Linux: export GEMINI_API_KEY=your_key)
python pipeline.py --input "your_screenplays.zip" --out my_run --provider gemini
#   other judges: --provider anthropic (ANTHROPIC_API_KEY)  |  --provider openai (OPENAI_API_KEY)
#   pick a model:  --model <model name>

# 3) Replay the bundled scores (written by Claude in chat, no key)
python pipeline.py --input "your_screenplays.zip" --out my_run --provider cache --cache llm_cache.json
```

`--input` can be the zip or the folder of `episode-*.txt` files.
Results are in `my_run/`: `promos.csv` (open in Excel), `promos.json`, `promos_report.md` (with transcripts).

The run prints how many clips were scored by the AI and how many API calls were really made, so you always know whether a model was used.

## Web app

```bash
pip install streamlit
streamlit run app.py
```

Upload the zip, choose a judge, paste an API key (used for that run only, never saved), press **Find promos**. Every run stays on screen and can be compared with other runs at the bottom of the page.
Free Gemini keys have small daily limits - the app shows how many calls a run will make and asks you to confirm.

## Check the results

```bash
python validate.py my_run your_screenplays.zip          # length 20-60 s? any cut mid-line? inside the episode?
python compare.py runA/promos.json runB/promos.json 10   # how many of the top 10 are the same clip?
python eval_runs.py "A=runA" "B=runB" "C=runC"            # 3+ runs: overlap, rank agreement, quote check
python blind_test.py make your_screenplays.zip 10 runA/promos.json runB/promos.json   # sheet for human raters (+ random clips)
python blind_test.py analyze blind_sheet_filled.csv blind_key.csv                     # reveal average ratings per source
```

## Files

| File | What it does |
|---|---|
| `parser.py` | reads screenplays |
| `candidates.py` | builds clips, picks the best non-overlapping ones |
| `scoring.py` | rule scores (edit the word lists for other genres / languages) |
| `llm.py` | AI judge: prompt, Gemini / Claude / OpenAI, saved scores |
| `pipeline.py` | the main command |
| `app.py`, `runner.py` | Streamlit web app |
| `compare.py`, `eval_runs.py`, `eval_agreement.py`, `validate.py`, `blind_test.py` | checking tools |
| `export_from_json.py` | rebuilds the CSV/report from a downloaded `promos.json` |
| `llm_cache.json` | bundled scores for 141 clips, written by Claude in chat (see below) |

## What was tested (honest summary)

- Three runs on all 50 episodes: **A** rules only, **B** bundled Claude-in-chat scores, **C** a live Gemini run. All produce 99 promos with no clip outside 20-60 s and no cut mid-line.
- Top-10 overlap between any two runs is 5/10; five clips are in the top 10 of both AI judges.
- Known problems: the rules over-rate loud speeches; Gemini missed a spoiler; the AI's cliffhanger text is a description, not a quote; 5 trimmed clips had stale hook text (fixed in code, not re-run).
- **Not done:** comparison with promos Kuku's editors really posted, and a human blind rating.

## Good to know

- Saved scores are only reused for the **same** judge. A Gemini run never returns Claude's scores, and live results are saved in a separate file (`llm_cache_<provider>.json`).
- The AI sees screenplay text only - no picture, no sound.
- The screenplays are Kuku's confidential content. Do not commit them to a public repository.
