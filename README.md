# Promo Finder (Kuku AI Generalist - Problem 1)

Reads microdrama screenplays (`episode-*.txt`) and outputs ranked 20-60 s promo cuts: episode, start/end of every segment, hook, cliffhanger, why it works, known issue.

## Run (Python 3.9+, no installs needed for the core pipeline)
```bash
# 1) free, offline, heuristics only (this is what raw_outputs/run_A used)
python pipeline.py --input "<folder or .zip of episode-*.txt>" --out outputs --provider none

# 2) with an LLM judge - swap the model with --provider / --model
GEMINI_API_KEY=...    python pipeline.py --input pack.zip --out outputs --provider gemini    # free tier: gemini-2.0-flash
ANTHROPIC_API_KEY=... python pipeline.py --input pack.zip --out outputs --provider anthropic --model claude-haiku-4-5
OPENAI_API_KEY=...    python pipeline.py --input pack.zip --out outputs --provider openai    # OPENAI_BASE_URL for any compatible endpoint

# 3) replay saved judgments (run_B used the bundled llm_cache.json)
python pipeline.py --input pack.zip --out outputs --provider cache --cache llm_cache.json

python compare.py runA/promos.json runB/promos.json 10   # how much do two judge models agree?
python blind_test.py make pack.zip 10 runA/promos.json runB/promos.json   # blind human test sheet (+ random baseline)
python blind_test.py analyze blind_sheet_filled.csv blind_key.csv          # reveal mean ratings per source
python validate.py outputs <folder>        # hard-rule checks + stats
python eval_agreement.py pack.zip          # heuristic vs judge agreement (needs llm_cache.json)
streamlit run app.py                       # small UI
```
Options: `--keep N` promos per episode (default 2), `--per-ep N` shortlist per episode (default 3).

## Files
`parser.py` screenplay -> beats | `scoring.py` hook/cliffhanger/standalone/pace/spoiler rules (edit the lexicons per genre/language) | `candidates.py` windows + joined cuts + selection | `llm.py` rubric prompt, providers, caching | `pipeline.py` CLI | `judgments/make_cache.py` how the bundled judgments were recorded.

## Known limits
Screenplay text only (no picture/audio); English lexicons; shortlist capped at 3 per episode; judge scores in `llm_cache.json` were made by Claude in chat, not a live API call - re-run with `--provider gemini` to regenerate (cache is keyed by clip, delete it to force fresh calls).
The screenplays are Kuku's confidential content: keep the repo private and do not commit the input pack.
