"""The edited timeline: where each kept word lands, and where transitions, b-roll and sound effects go.

All times returned here are in the EDITED video (after cuts). Everything is derived from the transcript and
the plan, so it is recomputed whenever the plan changes and never goes stale.
"""
from __future__ import annotations

from .plan import keep_segments, remap_time


def map_time(t: float, segs: list[tuple[float, float]], prefer_next: bool) -> float | None:
    """Source time -> edited time. A time inside a cut snaps to the nearest kept edge."""
    mapped = remap_time(t, segs)
    if mapped is not None:
        return mapped
    offset = 0.0
    for start, end in segs:
        if t < start:
            return offset if prefer_next else max(0.0, offset - 0.001)
        offset += end - start
    return offset if not prefer_next else None


def edited_words(transcript: dict, plan: dict) -> list[dict]:
    """Kept words with their times on the edited timeline: [{"i", "text", "start", "end"}]."""
    segs = keep_segments(plan["cuts"], float(plan["duration"]))
    removed = set(plan.get("removed_words", []))
    out = []
    for w in transcript["words"]:
        if w["i"] in removed:
            continue
        s = map_time(w["start"], segs, prefer_next=True)
        e = map_time(w["end"], segs, prefer_next=False)
        if s is None or e is None:
            continue
        out.append({"i": w["i"], "text": w["text"], "start": s, "end": max(e, s + 0.05)})
    return out


def joins(plan: dict) -> list[float]:
    """Edited times of every cut (where two kept segments meet)."""
    segs = keep_segments(plan["cuts"], float(plan["duration"]))
    t, out = 0.0, []
    for s, e in segs[:-1]:
        t += e - s
        out.append(round(t, 3))
    return out


def edited_duration(plan: dict) -> float:
    return sum(e - s for s, e in keep_segments(plan["cuts"], float(plan["duration"])))


def transition_times(ew: list[dict], plan: dict, style: dict) -> list[float]:
    """One transition per topic break, snapped back onto the cut just before it when there is one."""
    if not style.get("transitions"):
        return []
    by_id = {w["i"]: w for w in ew}
    cut_times = joins(plan)
    out = []
    for i in style.get("topic_breaks", []):
        w = by_id.get(i)
        if w is None:
            continue
        t = w["start"]
        near = [c for c in cut_times if t - 0.6 <= c <= t + 0.02]
        if near:
            t = max(near)
        if t >= 0.5 and all(abs(t - o) > 1.0 for o in out):
            out.append(round(t, 3))
    return sorted(out)


def broll_slots(ew: list[dict], plan: dict, cfg: dict) -> dict[str, dict]:
    """Where each b-roll moment plays: {id: {"start", "end", "status"}} in edited time.

    Default placement (B-Roll Prompter): cover the speaker fully for 2-4 s, speech continues underneath.
    A slot never overlaps the previous one and never runs past the end of the video or of its clip.
    """
    bcfg = cfg.get("broll") or {}
    lo, hi = float(bcfg.get("min_seconds", 2.0)), float(bcfg.get("max_seconds", 4.0))
    skip = float(bcfg.get("skip_start", 0.4))
    total = edited_duration(plan)
    by_id = {w["i"]: w for w in ew}
    rows = []
    for item in plan.get("broll") or []:
        kept = [by_id[i] for i in range(int(item["from_word"]), int(item["to_word"]) + 1) if i in by_id]
        if not kept:
            rows.append((None, item, None))
            continue
        start, end = kept[0]["start"], kept[-1]["end"]
        dur = min(hi, max(lo, end - start))
        rows.append((start, item, dur))

    out: dict[str, dict] = {}
    last_end = 0.0
    for start, item, dur in sorted(rows, key=lambda r: (r[0] is None, r[0] or 0)):
        if start is None:
            out[item["id"]] = {"start": None, "end": None, "status": "its words are cut from the edit"}
            continue
        start = max(start, last_end + 0.05) if last_end else start
        clip_len = item.get("clip_duration")
        if clip_len:
            trim = item.get("trim_start")
            trim = skip if trim is None else float(trim)
            dur = min(dur, max(0.5, float(clip_len) - trim))
        end = min(start + dur, total)
        if end - start < 0.5:
            out[item["id"]] = {"start": None, "end": None, "status": "no room (overlaps the previous b-roll)"}
            continue
        status = "placed" if item.get("clip") else "waiting for clip"
        out[item["id"]] = {"start": round(start, 3), "end": round(end, 3), "status": status}
        last_end = end
    return out


def speech_intervals(ew: list[dict], merge_gap: float = 0.35, pad: float = 0.08) -> list[tuple[float, float]]:
    """Edited-time ranges where someone is talking (for ducking the music)."""
    out: list[list[float]] = []
    for w in ew:
        s, e = max(0.0, w["start"] - pad), w["end"] + pad
        if out and s - out[-1][1] <= merge_gap:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(a, b) for a, b in out]


def sound_map(ew: list[dict], plan: dict, style: dict, slots: dict[str, dict], trans: list[float],
              duration: float | None = None) -> list[dict]:
    """Every moment that gets a sound effect (Sound Design skill): one row per moment.

    title lands -> pop · transition -> whoosh · keyword pop -> soft tick · b-roll in -> soft whoosh
    (split screens get a full whoosh) · b-roll marked as an impact -> hit. Caption lines get no tick
    (that would sound like a typewriter).
    """
    rows: list[dict] = []
    if style.get("title_enabled") and style.get("title"):
        rows.append({"t": 0.25, "kind": "pop", "what": f'title "{style["title"]}" lands'})
    for t in trans:
        rows.append({"t": t, "kind": "whoosh", "what": "transition (topic change)"})
    if style.get("keyword_pop") and (plan.get("captions") or {}).get("enabled", True):
        kw = set(style.get("keywords", []))
        for w in ew:
            if w["i"] in kw:
                rows.append({"t": round(w["start"], 3), "kind": "tick", "what": f'keyword "{w["text"]}" pops'})
    items = {b["id"]: b for b in plan.get("broll") or []}
    for bid, slot in slots.items():
        item = items.get(bid)
        if not item or slot["start"] is None or not item.get("clip"):
            continue
        split = item.get("layout") == "split"
        rows.append({"t": slot["start"], "kind": "whoosh" if split else "whoosh_soft",
                     "what": f'b-roll in: {item.get("show", "")[:40]}'})
        if item.get("impact"):
            rows.append({"t": round(slot["start"] + 0.04, 3), "kind": "hit", "what": "b-roll impact"})
    keyword = (style.get("cta_keyword") or "").strip()
    if keyword and duration:
        from .captions import cta_times
        start, _, letters = cta_times(duration, keyword)
        rows.append({"t": round(start, 3), "kind": "pop", "what": "call to action appears"})
        for k, t in enumerate(letters):
            rows.append({"t": t, "kind": "key", "what": f'types "{keyword[:k + 1]}"'})
    rows.sort(key=lambda r: r["t"])
    return rows


def describe(transcript: dict, plan: dict, cfg: dict, style: dict) -> dict:
    """Everything the review page and the renderer need to know about the edited timeline."""
    ew = edited_words(transcript, plan)
    trans = transition_times(ew, plan, style)
    slots = broll_slots(ew, plan, cfg)
    return {"words": ew, "transitions": trans, "broll": slots,
            "sound_map": sound_map(ew, plan, style, slots, trans, edited_duration(plan)),
            "duration": round(edited_duration(plan), 3)}
