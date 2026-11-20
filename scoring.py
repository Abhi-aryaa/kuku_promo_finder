"""Rule-based scoring of a screenplay window: hook, cliffhanger, standalone-ness, pace.
Deterministic, free, offline. Used (a) to shortlist candidates for the LLM and (b) as the fallback ranker."""
import re
from parser import Beat

# ---- lexicons (tuned for English melodrama / microdrama; edit for other genres/languages) ----
DANGER  = r"slap|strike|struck|whip|crop|blood|bleed|dagger|sword|knife|blade|gun|hang|gallows|execut|kill|murder|poison|arsenic|burn|fire|ablaze|explosion|torch|iron|chain|dungeon|noose|die|dead|death|dying|attack|thug"
REVEAL  = r"secret|truth|reveal|expos|prove|proof|confess|identity|lost son|true duke|duke|crest|imposter|witch|traitor|treason|conspir|forged|framed|fabricat|witness|saw you"
BETRAY  = r"betray|liar|lies|lie\b|worthless|nothing|disown|banish|abandon|humiliat|shame|disgrace|beg|mud|plainness|low value|pathetic|cruel|how dare|you will pay|regret|mercy"
POWER   = r"marry|married|husband|wife|bride|kneel|proposal|vow|swear|promise|love|mine|mother|brother|child|son\b|heir|inherit|title|throne|crown|sanctuary|invalid"
SHOCK_A = r"gasp|slap|strike|shatter|burst|slam|stagger|freeze|frozen|stunned|collapse|lunge|seize|grab|drag|throw|hurl|draw[s]? a|point[s]? a|kneel|rip|tear|smash|explod|appears|steps? (?:out|in|forward)|enters|door"
HOT_DELIV = r"shout|scream|furious|rage|enrag|menac|threat|cold|icy|sneer|cruel|gloat|smug|gasp|horrif|shock|stunned|trembling|desperate|pleading|defiant|fierce|vicious|snarl|bark|command"
RESOLVE = r"thank you|thanks|goodbye|farewell|good night|rest now|sleep well|peace|forgive|together|safe now|it is over|it's over|all is well|i love you"
CONTEXT = r"as i said|remember|last night|earlier|the other day|again\b|you promised|yesterday|before\b|back then|that night|as we planned|our plan|the plan|as you know"
PRON_OPEN = re.compile(r"^(he|she|they|him|her|it|that|this|them)\b", re.I)
CLIFF_ACT = r"door|burst|appears|enters|steps? (?:out|in|forward)|stands? in the doorway|witness|watching|unseen|gasp|freez|frozen|stunned|horror|realiz|dread|ominous|cliffhanger|sting|drone|swell|cut to black|smash cut|looms?|reveal"
# plot-twist reveals that spoil the show if used as top-of-funnel promo (specific to this show; auto-extendable by LLM mode)
SPOILER = r"true duke|rightful duke|duke of|regalia|alive|lost son|ashbourne crest|ashbourne\b|ashburn"

def _c(rx, s): return len(re.findall(rx, s, re.I))

def beat_intensity(b: Beat) -> float:
    """0..10 'how loud is this beat' for hook/lull detection."""
    if b.kind == "CAMERA": return 0.0
    t = b.text
    x = 1.0
    x += 1.6 * min(_c(DANGER, t), 2) + 1.4 * min(_c(REVEAL, t), 2) + 1.2 * min(_c(BETRAY, t), 2) + 0.6 * min(_c(POWER, t), 2)
    x += 1.5 * min(t.count("!"), 2) + 0.7 * t.count("?")
    if b.kind == "DIALOGUE":
        if b.delivery: x += 1.3 * min(_c(HOT_DELIV, b.delivery), 2)
        n = len(t.split())
        if n <= 9: x += 0.8            # punchy line
        if n >= 30: x -= 1.0           # speechy / expository
        if re.search(r"\b(you|your)\b", t, re.I) and (_c(BETRAY, t) or _c(DANGER, t)): x += 0.8  # direct accusation/threat
    elif b.kind == "ACTION":
        x += 1.4 * min(_c(SHOCK_A, t), 2)
    elif b.kind == "SOUND":
        x += 0.8 * min(_c(CLIFF_ACT, t), 2)
    return max(0.0, min(10.0, x))

def content_beats(beats): return [b for b in beats if b.kind in ("DIALOGUE", "ACTION", "SOUND")]

def hook_score(beats, s):
    """Strength of the first ~3s. Needs *something* to happen/be said immediately."""
    first = [b for b in content_beats(beats) if b.start < s + 3.2 and b.kind != "SOUND"]
    if not first: return 0.0, None
    best = max(first, key=lambda b: beat_intensity(b) - 0.6 * max(0, b.start - s))
    sc = beat_intensity(best) - 0.6 * max(0, best.start - s)
    if best.kind == "DIALOGUE" and best.start - s <= 1.2: sc += 0.8            # speech starts at once
    if PRON_OPEN.match(best.text) and best.kind == "DIALOGUE": sc -= 0.8         # opens on an unresolved pronoun
    if re.match(r"^(are you|is everything|good morning|good evening|hello|welcome)\b", best.text, re.I): sc -= 1.5  # pleasantry
    return max(0.0, min(10.0, sc * 1.05)), best

def cliff_score(beats, e, ep_end, ep_duration):
    tail = [b for b in content_beats(beats) if b.end > e - 7.0 and b.start < e]
    if not tail: return 0.0, None
    last_c = [b for b in tail if b.kind in ("DIALOGUE", "ACTION")]
    last = last_c[-1] if last_c else tail[-1]
    sc = 2.0
    at_end = (ep_duration - e) <= 1.6
    if at_end: sc += 2.2
    sounds = " ".join(b.text for b in tail if b.kind == "SOUND")
    if at_end and _c(CLIFF_ACT, sounds): sc += 1.6
    t = last.text
    if last.kind == "DIALOGUE":
        if t.rstrip().endswith("?"): sc += 1.6
        if t.rstrip().endswith(("...", "—", "-")): sc += 1.0
        if _c(DANGER, t) or _c(REVEAL, t): sc += 1.6
        if _c(BETRAY, t): sc += 0.8
        if last.delivery and _c(HOT_DELIV, last.delivery): sc += 0.8
        if len(t.split()) <= 10: sc += 0.5
    else:
        sc += 1.4 * min(_c(CLIFF_ACT, t) + _c(SHOCK_A, t), 2)
    tail_txt = " ".join(b.text for b in tail)
    sc += 0.8 * min(_c(CLIFF_ACT, tail_txt), 2)
    sc += 0.4 * min(sum(beat_intensity(b) for b in tail if b.kind != "SOUND") / max(1, len(tail)) / 3, 3)
    if _c(RESOLVE, t): sc -= 2.5                                               # reads like a closure
    if last.kind == "DIALOGUE" and last.delivery and re.search(r"calm|gentle|soft|warm|tender|relie", last.delivery, re.I): sc -= 1.2
    return max(0.0, min(10.0, sc)), last

def standalone_score(beats, s, e, ep_num, scene_starts, has_continuity):
    d = [b for b in beats if b.kind == "DIALOGUE"]
    names = {b.speaker for b in d}
    sc = 9.0
    sc -= 0.9 * max(0, len(names) - 3)
    txt = " ".join(b.text for b in d)
    sc -= 0.8 * min(_c(CONTEXT, txt), 3)
    if not any(abs(s - ss) < 4.0 for ss in scene_starts): sc -= 0.7              # starts mid-scene
    sc -= min(2.5, 0.06 * (ep_num - 1))                                          # deeper in plot = more backstory needed
    if has_continuity and ep_num > 1 and any(abs(s - ss) < 0.5 for ss in scene_starts[:1]): sc -= 0.4
    if len(d) < 3: sc -= 2.0                                                    # too little speech to explain itself
    return max(0.0, min(10.0, sc))

def pace_score(beats, s, e):
    dur = max(1e-6, e - s)
    d = [b for b in beats if b.kind == "DIALOGUE"]
    speech = sum(min(b.end, e) - max(b.start, s) for b in d)
    ratio = speech / dur
    inten = [beat_intensity(b) for b in content_beats(beats) if b.kind != "SOUND"]
    avg = sum(inten) / max(1, len(inten))
    sc = 3.0 * min(1.0, ratio / 0.45) + 0.9 * min(avg, 5)
    # penalise long dead stretches
    cb = sorted(content_beats(beats), key=lambda b: b.start)
    gap = max([cb[i + 1].start - cb[i].end for i in range(len(cb) - 1)] + [0])
    if gap > 5: sc -= 1.5
    # sweet spot 25-45 s
    if 25 <= dur <= 48: sc += 1.0
    return max(0.0, min(10.0, sc))

def spoiler_flag(beats): return _c(SPOILER, " ".join(b.text for b in beats)) >= 1
