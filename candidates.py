"""Candidate generation: single continuous windows + 'joined' cuts (two moments of one episode, skipping a lull)."""
from dataclasses import dataclass, field
from typing import List
from parser import Episode, Beat, fmt
import scoring as S

MIN_D, MAX_D = 20.0, 60.0

@dataclass
class Segment:
    episode: int
    start: float
    end: float
    def dur(self): return self.end - self.start

@dataclass
class Candidate:
    segments: List[Segment]
    scores: dict = field(default_factory=dict)
    total: float = 0.0
    flags: list = field(default_factory=list)
    hook_beat: Beat = None
    cliff_beat: Beat = None
    kind: str = "single"
    @property
    def duration(self): return sum(s.dur() for s in self.segments)

def _snap(ep: Episode, s, e):
    """Never cut a spoken line in half; add tiny pads so cuts land on breaths."""
    for b in ep.beats:
        if b.kind == "DIALOGUE":
            if b.start < s < b.end: s = b.start
            if b.start < e < b.end: e = b.end
    return max(0.0, round(s, 2)), min(ep.duration, round(e, 2))

def _beats_in(ep, s, e): return [b for b in ep.beats if b.end > s + 0.05 and b.start < e - 0.05]

def _starts_ends(ep):
    cb = [b for b in ep.beats if b.kind in ("DIALOGUE", "ACTION")]
    starts = sorted({max(0.0, round(b.start - (0.25 if b.kind == "DIALOGUE" else 0.0), 2)) for b in cb})
    ends = sorted({round(min(ep.duration, b.end + 0.3), 2) for b in cb} | {round(ep.duration, 2)})
    return starts, ends

def _score(ep: Episode, segs, kind="single"):
    scene_starts = [sc[2] for sc in ep.scenes]
    allb = []
    for sg in segs: allb += _beats_in(ep, sg.start, sg.end)
    first, last = segs[0], segs[-1]
    h, hb = S.hook_score(_beats_in(ep, first.start, first.end), first.start)
    c, cb = S.cliff_score(_beats_in(ep, last.start, last.end), last.end, ep.duration, ep.duration)
    st = S.standalone_score(allb, first.start, last.end, ep.num, scene_starts, bool(ep.continuity))
    pc = sum(sg.dur() for sg in segs)
    pace = S.pace_score(allb, first.start, first.start + pc)
    spoil = S.spoiler_flag(allb)
    total = 0.32 * h + 0.34 * c + 0.20 * st + 0.14 * pace
    flags = []
    if spoil: total -= 0.8; flags.append("spoiler_risk")
    if kind == "joined": total -= 0.5; flags.append("joined_cut")
    if st < 5.5: flags.append("needs_context")
    return dict(hook=round(h, 2), cliff=round(c, 2), standalone=round(st, 2), pace=round(pace, 2)), round(total, 3), flags, hb, cb

def singles(ep: Episode) -> List[Candidate]:
    starts, ends = _starts_ends(ep)
    out = []
    for s in starts:
        for e in ends:
            d = e - s
            if d < MIN_D: continue
            if d > MAX_D: break
            s2, e2 = _snap(ep, s, e)
            if not (MIN_D <= e2 - s2 <= MAX_D): continue
            sc, tot, fl, hb, cb = _score(ep, [Segment(ep.num, s2, e2)])
            out.append(Candidate([Segment(ep.num, s2, e2)], sc, tot, fl, hb, cb))
    return out

def joins(ep: Episode, top=14) -> List[Candidate]:
    starts, ends = _starts_ends(ep)
    A, B = [], []
    for s in starts:
        for e in ends:
            d = e - s
            if 8 <= d <= 28:
                s2, e2 = _snap(ep, s, e)
                h, _ = S.hook_score(_beats_in(ep, s2, e2), s2)
                A.append((h, s2, e2))
            if 12 <= d <= 45:
                s2, e2 = _snap(ep, s, e)
                c, _ = S.cliff_score(_beats_in(ep, s2, e2), e2, ep.duration, ep.duration)
                B.append((c, s2, e2))
    A = sorted(A, reverse=True)[:top]; B = sorted(B, reverse=True)[:top]
    out = []
    for _, a0, a1 in A:
        for _, b0, b1 in B:
            if b0 - a1 < 8: continue                      # must actually skip something
            d = (a1 - a0) + (b1 - b0)
            if not (MIN_D + 2 <= d <= MAX_D): continue
            skipped = [x for x in _beats_in(ep, a1, b0) if x.kind != "CAMERA"]
            avg = sum(S.beat_intensity(x) for x in skipped) / max(1, len(skipped))
            segs = [Segment(ep.num, a0, a1), Segment(ep.num, b0, b1)]
            sc, tot, fl, hb, cb = _score(ep, segs, "joined")
            if avg > 4.0: tot -= 1.0; fl.append("skips_key_beat")
            out.append(Candidate(segs, sc, tot, fl, hb, cb, "joined"))
    return out

def overlap(c1: Candidate, c2: Candidate) -> float:
    ov = 0.0
    for a in c1.segments:
        for b in c2.segments:
            if a.episode == b.episode: ov += max(0.0, min(a.end, b.end) - max(a.start, b.start))
    return ov / max(1e-6, min(c1.duration, c2.duration))

def select(cands: List[Candidate], per_ep=3, max_overlap=0.2):
    chosen = []
    for c in sorted(cands, key=lambda x: -x.total):
        if sum(1 for k in chosen if k.segments[0].episode == c.segments[0].episode) >= per_ep: continue
        if any(overlap(c, k) > max_overlap for k in chosen): continue
        chosen.append(c)
    return chosen
