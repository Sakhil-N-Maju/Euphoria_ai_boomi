"""Finishing style for an edit: title, caption style, keyword pops, transitions, look, sound.

Everything here is optional and off by default, so a plain edit renders exactly as before.
The style lives in edit.yaml under "style" (video as code). Every change, from the review page or a chat
edit, goes through clean_style(), so only known keys with sane values ever reach the renderer.
"""
from __future__ import annotations

import re

from .config import load_config

# key: (kind, a, b)  kind = bool | int | float | str | choice | ids | color
SCHEMA: dict[str, tuple] = {
    "title": ("str", 0, 60),
    "title_enabled": ("bool", None, None),
    "caption_style": ("choice", ("plain", "highlight"), None),
    "keyword_pop": ("bool", None, None),
    "pop_scale": ("float", 1.0, 1.6),
    "pop_ms": ("int", 40, 400),
    "keywords": ("ids", None, None),
    "topic_breaks": ("ids", None, None),
    "transitions": ("bool", None, None),
    "transition_zoom": ("float", 1.03, 1.35),
    "transition_ms": ("int", 150, 900),
    "punch_in": ("bool", None, None),
    "punch_zoom": ("float", 1.03, 1.3),
    "look": ("choice", ("clean", "archival", "archival_all", "vhs"), None),
    "sfx": ("bool", None, None),
    "sfx_db": ("float", -24.0, 6.0),
    "whoosh_ms": ("int", 150, 900),
    "whoosh_hz": ("float", 200.0, 3000.0),
    "music": ("bool", None, None),
    "music_db": ("float", -40.0, 0.0),
    "duck_db": ("float", 0.0, 24.0),
    "accent": ("color", None, None),
    # Reel Editor skill: vertical 9:16 reel, Instagram safe zones, comment-keyword call to action
    "format": ("choice", ("original", "reel"), None),
    "face_x": ("float", 0.0, 1.0),
    "face_y": ("float", 0.0, 1.0),
    "cta_keyword": ("str", 0, 24),
    "cta_line": ("str", 0, 60),
    # Colour grade of the presenter footage: reel-editor "cinematic" (any footage) or Look 01 LUT (S-Log3 only)
    "grade": ("choice", ("none", "cinematic", "look01"), None),
    # graphic-overlays skill: lower-third name card
    "lower_name": ("str", 0, 40),
    "lower_role": ("str", 0, 50),
    "lower_at": ("float", 0.0, 600.0),
    # subtitle-generation skill: translated captions ("" = the spoken language)
    "caption_lang": ("choice", ("", "en", "hi", "ml", "ta", "te", "kn", "bn", "mr", "gu", "pa", "ur", "ar", "es", "fr"), None),
    "caption_dual": ("bool", None, None),
    # video-edit (ffmpeg) skill: playback speed of the finished video
    "speed": ("float", 1.0, 1.5),
    # audio-editing / audio-production skills: denoise, de-ess, presence for the voice
    "voice_clean": ("bool", None, None),
}

DEFAULTS = {
    "title": "", "title_enabled": False,
    "caption_style": "plain", "keyword_pop": False, "pop_scale": 1.18, "pop_ms": 150,
    "keywords": [], "topic_breaks": [],
    "transitions": False, "transition_zoom": 1.15, "transition_ms": 350,
    "punch_in": False, "punch_zoom": 1.12,
    "look": "clean",
    "sfx": False, "sfx_db": 0.0, "whoosh_ms": 400, "whoosh_hz": 900.0,
    "music": False, "music_db": -10.0, "duck_db": 8.0,
    "accent": "#FFD23F",
    "format": "original", "face_x": 0.5, "face_y": 0.45, "cta_keyword": "", "cta_line": "",
    "grade": "none",
    "lower_name": "", "lower_role": "", "lower_at": 2.5,
    "caption_lang": "", "caption_dual": False, "speed": 1.0, "voice_clean": False,
}

_HEX = re.compile(r"^#?[0-9a-fA-F]{6}$")


def defaults() -> dict:
    """Built-in defaults, overridden by the 'style' section of config.yaml."""
    cfg = load_config().get("style") or {}
    out = dict(DEFAULTS)
    out.update(clean_style(cfg))
    return out


def effective(plan: dict) -> dict:
    """The style the renderer uses: defaults + whatever this video's plan sets."""
    return {**defaults(), **clean_style(plan.get("style") or {})}


def clean_style(changes: dict | None, n_words: int | None = None) -> dict:
    """Keep only known keys with values of the right type, clamped to their allowed range."""
    out: dict = {}
    for key, value in (changes or {}).items():
        spec = SCHEMA.get(key)
        if spec is None:
            continue
        kind, a, b = spec
        if kind == "bool":
            if isinstance(value, bool):
                out[key] = value
        elif kind in ("int", "float"):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                v = min(b, max(a, float(value)))
                out[key] = int(round(v)) if kind == "int" else round(v, 3)
        elif kind == "str":
            if isinstance(value, str):
                out[key] = " ".join(value.split())[:b]
        elif kind == "choice":
            if value in a:
                out[key] = value
        elif kind == "color":
            if isinstance(value, str) and _HEX.match(value.strip()):
                out[key] = "#" + value.strip().lstrip("#").upper()
        elif kind == "ids":
            if isinstance(value, (list, tuple)):
                ids = set()
                for v in value:
                    try:
                        i = int(v)
                    except (TypeError, ValueError):
                        continue
                    if i >= 0 and (n_words is None or i < n_words):
                        ids.add(i)
                out[key] = sorted(ids)
    return out


# ---------- automatic picks (no AI needed) ----------

# Claim words pop best (HyperFrames notes): numbers, brand names, "double", "gone", "free"...
CLAIM_WORDS = {
    "free", "double", "triple", "half", "gone", "never", "always", "best", "worst", "only", "secret", "mistake",
    "mistakes", "faster", "fastest", "zero", "biggest", "easiest", "huge", "instantly", "guaranteed", "save",
    "saves", "money", "profit", "viral", "million", "billion", "lakh", "lakhs", "crore", "crores", "percent",
    "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "twenty", "thirty", "forty", "fifty",
    "hundred", "thousand", "seconds", "minutes", "hours",
}
_SENTENCE_END = (".", "?", "!", "।", "॥")


def _bare(text: str) -> str:
    return re.sub(r"[^\w₹$%]", "", text.lower())


def auto_keywords(words: list[dict], removed: set[int], per_words: int = 7) -> list[int]:
    """Numbers, money and claim words, at most about one per `per_words` kept words, never two in a row."""
    kept = [w for w in words if w["i"] not in removed]
    picks: list[tuple[int, int]] = []
    budget = max(1, len(kept) // per_words)
    scored = []
    for pos, w in enumerate(kept):
        bare = _bare(w["text"])
        if not bare:
            continue
        score = 0
        if re.search(r"\d", bare) or any(c in w["text"] for c in "₹$%"):
            score = 3
        elif bare in CLAIM_WORDS:
            score = 2
        elif w["text"][:1].isupper() and pos > 0 and not kept[pos - 1]["text"].endswith(_SENTENCE_END) and len(bare) > 3:
            score = 1   # a capitalised word mid-sentence is often a name or brand
        if score:
            scored.append((score, pos, w["i"]))
    for score, pos, i in sorted(scored, key=lambda x: (-x[0], x[1])):
        if len(picks) >= budget:
            break
        if all(abs(pos - p) > 1 for p, _ in picks):
            picks.append((pos, i))
    return sorted(i for _, i in picks)


def auto_topic_breaks(words: list[dict], removed: set[int], edited_duration: float,
                      min_gap: float = 0.9, spacing: float = 8.0) -> list[int]:
    """Where a new thought starts: the first word after a finished sentence and a long pause.

    The biggest pauses win; at most one break per ~15 s of edited video and none closer than `spacing` s.
    """
    kept = [w for w in words if w["i"] not in removed]
    cands = []
    for a, b in zip(kept, kept[1:]):
        gap = b["start"] - a["end"]
        if gap >= min_gap and a["text"].endswith(_SENTENCE_END):
            cands.append((gap, b))
    limit = max(1, min(6, int(edited_duration // 15)))
    chosen: list[dict] = []
    for gap, w in sorted(cands, key=lambda x: -x[0]):
        if len(chosen) >= limit:
            break
        if w["start"] < 2.0:
            continue
        if all(abs(w["start"] - c["start"]) >= spacing for c in chosen):
            chosen.append(w)
    return sorted(w["i"] for w in chosen)


# ---------- AI picks ----------

STYLE_SYSTEM = """You are a video editor finishing a talking-head video (Malayalam, Hindi, English or code-mixed).
You get the transcript of the CURRENT CUT as numbered words: [s3 12.4-18.9s] 40:word 41:word ...  (~x~ = cut).

Return JSON only:
{"title": "<3-5 word title for the video's subject, in the language the speaker uses>",
 "keywords": [<word ids>],
 "topic_breaks": [<word ids>]}

- keywords: words that should POP in the captions: numbers, money, names, brands, and claim words
  ("double", "free", "gone", "never"). About one per 6-8 words at most, never two words in a row. Only words not cut.
- topic_breaks: the FIRST word of each new topic or section (not the first word of the video). Only real topic
  changes, usually 2-5 in a 1-minute video. Never between every sentence.
- Use only word ids that exist. Do not invent words."""


def ai_style(transcript: dict, plan: dict) -> dict:
    """Ask the AI for a title, keywords and topic breaks; everything is validated against the transcript."""
    from .aiedit import transcript_listing
    from .llm import chat_json

    removed = set(plan.get("removed_words", []))
    reply = chat_json(STYLE_SYSTEM, [{"role": "user", "content": transcript_listing(transcript, removed)}])
    n = len(transcript["words"])
    picked = clean_style({"title": reply.get("title", ""), "keywords": reply.get("keywords", []),
                          "topic_breaks": reply.get("topic_breaks", [])}, n_words=n)
    picked["keywords"] = [i for i in picked.get("keywords", []) if i not in removed]
    picked["topic_breaks"] = [i for i in picked.get("topic_breaks", []) if i not in removed and i > 0]
    # Two keywords in a row read as shouting: keep the first of each pair.
    kw: list[int] = []
    for i in picked["keywords"]:
        if not kw or i - kw[-1] > 1:
            kw.append(i)
    picked["keywords"] = kw
    return picked
