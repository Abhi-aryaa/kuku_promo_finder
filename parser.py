"""Parse Kuku screenplay .txt files into structured beats with episode-relative timestamps."""
import re, glob, os
from dataclasses import dataclass, field
from typing import List, Optional

TS = r"(\d+):(\d+\.\d+)"
HDR = re.compile(r"^\*\*(.+?)(?:\s*\((.*?)\))?:\*\*\s*$")
TIME = re.compile(rf"^Start:\s*\({TS}\)\s*\|\s*End:\s*\({TS}\)")

def to_sec(m, s): return int(m) * 60 + float(s)

@dataclass
class Beat:
    kind: str            # DIALOGUE | ACTION | CAMERA | SOUND
    start: float
    end: float
    text: str
    speaker: Optional[str] = None
    delivery: Optional[str] = None
    scene: int = 1

@dataclass
class Episode:
    num: int
    logline: str
    continuity: str
    duration: float
    beats: List[Beat] = field(default_factory=list)
    scenes: list = field(default_factory=list)   # (scene_no, heading, start, end)

def parse_episode(path) -> Episode:
    lines = open(path, encoding="utf-8").read().splitlines()
    num = int(re.search(r"Episode (\d+)", lines[0]).group(1))
    logline = next((l.split(":", 1)[1].strip() for l in lines if l.startswith("EPISODE LOGLINE")), "")
    cont = next((l.split(":", 1)[1].strip() for l in lines if l.startswith("CONTINUITY NOTES")), "")
    ep = Episode(num, logline, cont, 0.0)
    scene = 0; i = 0
    while i < len(lines):
        l = lines[i]
        sm = re.match(r"^SCENE\s+(\d+)\s*$", l.strip(), re.I)
        if sm:
            scene = int(sm.group(1)); heading = ""; s = e = 0.0
            for j in range(i + 1, min(i + 5, len(lines))):
                if re.match(r"^scene heading:", lines[j], re.I): heading = lines[j].split(":", 1)[1].strip()
                m = re.match(rf"Scene start:\s*{TS}", lines[j], re.I)
                if m: s = to_sec(*m.groups())
                m = re.match(rf"Scene end:\s*{TS}", lines[j], re.I)
                if m: e = to_sec(*m.groups())
            ep.scenes.append((scene, heading, s, e))
        m = HDR.match(l)
        if m and i + 2 < len(lines):
            name, delivery = m.group(1).strip(), m.group(2)
            t = TIME.match(lines[i + 1])
            if t:
                st, en = to_sec(*t.groups()[:2]), to_sec(*t.groups()[2:])
                body = []
                k = i + 2
                while k < len(lines) and lines[k].strip() and not lines[k].startswith("**") and not lines[k].startswith("---"):
                    body.append(lines[k].strip()); k += 1
                text = " ".join(body).strip()
                if name in ("CAMERA", "ACTION", "SOUND FX"):
                    kind = {"CAMERA": "CAMERA", "ACTION": "ACTION", "SOUND FX": "SOUND"}[name]
                    ep.beats.append(Beat(kind, st, en, text, scene=scene))
                else:
                    ep.beats.append(Beat("DIALOGUE", st, en, text.strip('"'), speaker=name, delivery=delivery, scene=scene))
                i = k; continue
        i += 1
    ep.beats.sort(key=lambda b: (b.start, b.end))
    ep.duration = max([b.end for b in ep.beats] + [s[3] for s in ep.scenes] + [0])
    return ep

def load_pack(folder):
    files = sorted(glob.glob(os.path.join(folder, "episode-*.txt")))
    return [parse_episode(f) for f in files]

def fmt(t):
    m = int(t // 60); s = t - 60 * m
    return f"{m:02d}:{s:05.2f}"

if __name__ == "__main__":
    import sys
    eps = load_pack(sys.argv[1])
    tot = 0
    for e in eps:
        d = sum(b.kind == "DIALOGUE" for b in e.beats)
        tot += e.duration
        print(e.num, fmt(e.duration), len(e.scenes), "scenes", len(e.beats), "beats", d, "dialogue")
    print("total min", tot / 60)
