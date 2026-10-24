"""Edit plans: the "video as code" layer.

A plan says which words are removed and which time ranges are cut. Cuts are derived from the
transcript plus settings, so the review page only has to send back a list of removed words.
The plan is saved as edit.yaml next to the video, so it can also be read or edited by hand.
"""
from __future__ import annotations

import unicodedata
from pathlib import Path

import yaml

PLAN_VERSION = 1


def normalize_word(text: str) -> str:
    """Lower-case and drop punctuation/symbols, keeping Indic vowel signs (combining marks)."""
    kept = [ch for ch in text if not unicodedata.category(ch).startswith(("P", "S", "Z"))]
    return "".join(kept).lower()


def detect_fillers(words: list[dict], fillers: list[str]) -> list[int]:
    filler_set = {normalize_word(f) for f in fillers}
    return [w["i"] for w in words if normalize_word(w["text"]) in filler_set]


def compute_cuts(words: list[dict], duration: float, removed: set[int], settings: dict) -> list[dict]:
    """Turn removed words + long pauses into a sorted, merged list of {"start", "end", "reason"} cuts."""
    remove_silences = settings.get("remove_silences", True)
    min_silence = float(settings.get("min_silence", 0.6))
    pad = float(settings.get("pad", 0.12))
    min_cut = float(settings.get("min_cut", 0.25))
    tight = 0.02  # padding used when the gap contains a removed word: cut right up to it

    kept = [w for w in words if w["i"] not in removed]
    cuts: list[dict] = []

    def add(start: float, end: float, reason: str) -> None:
        start, end = max(0.0, start), min(duration, end)
        if end - start >= min_cut:
            cuts.append({"start": round(start, 3), "end": round(end, 3), "reason": reason})

    if not kept:
        # Nothing to keep is almost certainly a mistake; refuse to cut the whole video.
        return []

    # Lead-in and tail: dead air before the first kept word and after the last one.
    first, last = kept[0], kept[-1]
    removed_before = any(w["i"] in removed for w in words if w["end"] <= first["start"])
    removed_after = any(w["i"] in removed for w in words if w["start"] >= last["end"])
    if remove_silences or removed_before:
        add(0.0, first["start"] - (tight if removed_before and not remove_silences else pad),
            "removed words" if removed_before else "silence")
    if remove_silences or removed_after:
        add(last["end"] + pad, duration, "removed words" if removed_after else "silence")

    # Gaps between consecutive kept words.
    removed_words = [w for w in words if w["i"] in removed]
    for a, b in zip(kept, kept[1:]):
        inside = [w for w in removed_words if w["start"] >= a["end"] - 0.05 and w["end"] <= b["start"] + 0.05]
        gap = b["start"] - a["end"]
        if inside:
            if all(w.get("_filler") for w in inside):
                reason = "filler"
            elif all(w.get("_retake") for w in inside):
                reason = "retake"
            else:
                reason = "removed words"
            add(a["end"] + tight, b["start"] - tight, reason)
        elif remove_silences and gap > min_silence:
            add(a["end"] + pad, b["start"] - pad, "silence")

    return merge_cuts(cuts)


def merge_cuts(cuts: list[dict], join_gap: float = 0.08) -> list[dict]:
    """Merge overlapping cuts and cuts separated by slivers too short to be worth keeping."""
    merged: list[dict] = []
    for c in sorted(cuts, key=lambda c: c["start"]):
        if merged and c["start"] <= merged[-1]["end"] + join_gap:
            prev = merged[-1]
            prev["end"] = max(prev["end"], c["end"])
            if c["reason"] not in prev["reason"].split(" + "):
                prev["reason"] = f'{prev["reason"]} + {c["reason"]}'
        else:
            merged.append(dict(c))
    return merged


def keep_segments(cuts: list[dict], duration: float, min_len: float = 0.05) -> list[tuple[float, float]]:
    """The complement of the cuts: the (start, end) ranges that end up in the final video."""
    segs, t = [], 0.0
    for c in sorted(cuts, key=lambda c: c["start"]):
        if c["start"] - t >= min_len:
            segs.append((round(t, 3), round(c["start"], 3)))
        t = max(t, c["end"])
    if duration - t >= min_len:
        segs.append((round(t, 3), round(duration, 3)))
    return segs


def remap_time(t: float, segments: list[tuple[float, float]]) -> float | None:
    """Map a time in the source video to the edited timeline. None if t falls inside a cut."""
    offset = 0.0
    for start, end in segments:
        if t < start:
            return None
        if t <= end:
            return offset + (t - start)
        offset += end - start
    return None


def build_plan(transcript: dict, settings: dict, fillers: list[str],
               removed_words: list[int] | None = None, captions: dict | None = None,
               source: str = "", retakes: list[dict] | None = None, style: dict | None = None,
               broll: list[dict] | None = None) -> dict:
    """Build a full plan. If removed_words is None, start from the automatic suggestions."""
    words = transcript["words"]
    duration = float(transcript["duration"])
    filler_ids = set(detect_fillers(words, fillers))
    if removed_words is None:
        removed = set(filler_ids) if settings.get("remove_fillers", True) else set()
    else:
        removed = {int(i) for i in removed_words}

    retakes = retakes or []
    retake_ids = {i for r in retakes for i in range(r["remove_from"], r["remove_to"] + 1)}
    marked = [dict(w, _filler=w["i"] in filler_ids, _retake=w["i"] in retake_ids) for w in words]
    cuts = compute_cuts(marked, duration, removed, settings)
    segs = keep_segments(cuts, duration)
    kept_duration = round(sum(e - s for s, e in segs), 3)

    return {
        "version": PLAN_VERSION,
        "source": source,
        "duration": duration,
        "edited_duration": kept_duration,
        "settings": settings,
        "captions": captions or {},
        "filler_words": sorted(filler_ids),
        "retakes": retakes,
        "retake_words": sorted(retake_ids),
        "removed_words": sorted(removed),
        "cuts": cuts,
        # Finishing (title, caption style, transitions, look, sound) and b-roll moments. Optional; see style.py.
        "style": style or {},
        "broll": broll or [],
    }


def save_plan(plan: dict, path: Path) -> None:
    header = (
        "# Edit plan (video as code). Cuts are in seconds of the original video.\n"
        "# You can edit 'cuts' by hand and re-render; changing words on the review page regenerates them.\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump(plan, f, allow_unicode=True, sort_keys=False, default_flow_style=None, width=120)


def load_plan(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
