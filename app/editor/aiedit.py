"""AI edits on top of the edit plan: retake detection and chat edits.

The AI never touches video. It sees the transcript with word IDs and answers with JSON that names word
IDs; everything it returns is checked against the transcript before it changes the plan, so it cannot
invent speech or cut words that don't exist.
"""
from __future__ import annotations

import json
import re

from . import style as stylelib
from .llm import LLMError, chat_json

MAX_RETAKE_WORDS = 80          # one retake shouldn't remove more than this many words
MAX_RETAKE_SHARE = 0.5         # all retakes together shouldn't remove more than half the words


# ---------- transcript as the AI sees it ----------

def transcript_listing(transcript: dict, removed: set[int] | None = None) -> str:
    """One line per segment: [s3 12.4-18.9s] 40:word 41:word ~42:word~ ...  (~x~ = currently cut)."""
    removed = removed or set()
    words = transcript["words"]
    lines = []
    segments = transcript.get("segments") or [{"start": 0.0, "end": transcript.get("duration", 0),
                                               "word_ids": [w["i"] for w in words]}]
    for n, seg in enumerate(segments):
        ids = seg.get("word_ids") or []
        if not ids:
            continue
        toks = []
        for i in ids:
            t = f'{i}:{words[i]["text"]}'
            toks.append(f"~{t}~" if i in removed else t)
        lines.append(f'[s{n} {seg["start"]:.1f}-{seg["end"]:.1f}s] ' + " ".join(toks))
    return "\n".join(lines)


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ---------- retakes ----------

RETAKE_SYSTEM = """You help edit talking-head videos (Malayalam, Hindi, English, or code-mixed like Manglish/Hinglish).
You get the transcript as numbered words, grouped in segments: [s3 12.4-18.9s] 40:word 41:word ...

Find RETAKES: places where the speaker starts a sentence or phrase, stumbles, stops or restarts, and says it again.
Also find FALSE STARTS: a sentence abandoned half-way and then restarted.
For each, remove the earlier attempt(s) and keep the LAST complete attempt.

Be conservative:
- Only flag a retake when the later words clearly repeat the meaning of the earlier ones.
- Deliberate repetition (emphasis, lists, a chorus, a question asked twice on purpose) is NOT a retake.
- The removed range must end before the kept range starts.

Reply with JSON only:
{"retakes": [{"remove_from": <word id>, "remove_to": <word id>, "kept_from": <word id>, "kept_to": <word id>,
              "reason": "<a few English words, e.g. 'restarted the intro sentence'>"}]}
Return {"retakes": []} if there are none."""


def validate_retakes(raw: list, n_words: int) -> list[dict]:
    """Keep only retakes that point at real words, in order, without overlaps or huge removals."""
    accepted: list[dict] = []
    taken: set[int] = set()
    budget = int(n_words * MAX_RETAKE_SHARE)
    for r in raw if isinstance(raw, list) else []:
        if not isinstance(r, dict):
            continue
        a, b, ka, kb = (_int(r.get(k)) for k in ("remove_from", "remove_to", "kept_from", "kept_to"))
        if None in (a, b, ka, kb):
            continue
        if not (0 <= a <= b < ka <= kb < n_words):
            continue
        span = set(range(a, b + 1))
        if b - a + 1 > MAX_RETAKE_WORDS or span & taken or len(taken) + len(span) > budget:
            continue
        taken |= span
        accepted.append({"remove_from": a, "remove_to": b, "kept_from": ka, "kept_to": kb,
                         "reason": str(r.get("reason", "retake"))[:120]})
    return sorted(accepted, key=lambda r: r["remove_from"])


def find_retakes(transcript: dict) -> list[dict]:
    words = transcript["words"]
    if len(words) < 6:
        return []
    reply = chat_json(RETAKE_SYSTEM, [{"role": "user", "content": transcript_listing(transcript)}])
    return validate_retakes(reply.get("retakes", []), len(words))


# ---------- chat edits ----------

CHAT_SYSTEM = """You are the editing assistant inside a talking-head video editor for Indian-language creators.
The video is edited by cutting words from its transcript. You get the transcript as numbered words in segments:
[s3 12.4-18.9s] 40:word 41:word ~42:word~ ...   Words written ~like this~ are currently cut.
Segment times are in the ORIGINAL video. Long pauses are also tightened automatically when that setting is on.

Turn the user's request into edit actions. Reply with JSON only:
{"reply": "<one or two short sentences to the user, in the language they wrote in>",
 "actions": [
   {"type": "cut", "from": <word id>, "to": <word id>},
   {"type": "restore", "from": <word id>, "to": <word id>},
   {"type": "keep_only", "ranges": [[<from id>, <to id>], ...]},
   {"type": "restore_all"},
   {"type": "settings", "remove_silences": <true|false>, "min_silence": <seconds 0.3-2.0>},
   {"type": "captions", "enabled": <true|false>},
   {"type": "style", <only the style keys to change>},
   {"type": "keywords", "add": [<word ids>], "remove": [<word ids>]}
 ]}

Style keys (finishing; the current values are given to you):
 title (3-5 words), title_enabled (bool), caption_style ("plain" | "highlight" = word-synced, spoken word tinted),
 keyword_pop (bool: keywords scale up and stay tinted), pop_scale (1.0-1.6; "bigger" -> raise it by ~0.1),
 pop_ms (40-400 ms; "snappier" -> lower it), transitions (bool: zoom transition at each topic change),
 transition_zoom (1.03-1.35), punch_in (bool: alternate zoom on jump cuts), look ("clean" | "archival" = black-and-white
 film look with bloom and grain on the b-roll | "archival_all" = on the whole video), sfx (bool: sound effects),
 sfx_db (-24..6, overall effects level), whoosh_ms (150-900; "shorter" -> lower), whoosh_hz (200-3000; "deeper" -> lower),
 music (bool), music_db (-40..0, music level between phrases), duck_db (0-24, how much more the music dips under the
 voice; "duck the music another 6dB" -> add 6). Keywords are word IDs that pop in the captions: numbers, names, claims.

Rules:
- Use only word IDs that appear in the transcript. Ranges are inclusive.
- "keep_only" cuts everything outside the ranges (words inside keep their current state). Use it for requests like
  "make a 30-second reel of the best part": pick complete sentences, start on a strong hook, and make the chosen
  segments' durations add up close to the target.
- To remove a topic, cut the full sentences about it, not half sentences.
- B-roll clips and the music file are added in the B-roll and Sound panels of the review page; if asked to add
  them, say so in "reply". Dubbing, voice changes and new speech are not possible: say so and return no actions.
  Never invent words.
- If the request is unclear, ask a short question in "reply" and return no actions."""

_TARGET_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-|\s)?\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes)\b", re.I)


def target_seconds(message: str) -> float | None:
    m = _TARGET_RE.search(message)
    if not m:
        return None
    value = float(m.group(1))
    return value * 60 if m.group(2).lower().startswith("m") else value


def apply_actions(actions: list, removed: set[int], n_words: int) -> tuple[set[int], dict, dict, list[str]]:
    """Apply validated actions. Returns (removed, settings changes, caption changes, notes on skipped actions)."""
    removed = set(removed)
    settings: dict = {}
    captions: dict = {}
    notes: list[str] = []

    def rng(a, b) -> range | None:
        a, b = _int(a), _int(b)
        if a is None or b is None or not (0 <= a <= b < n_words):
            return None
        return range(a, b + 1)

    for act in actions if isinstance(actions, list) else []:
        if not isinstance(act, dict):
            continue
        kind = act.get("type")
        if kind in ("cut", "restore"):
            r = rng(act.get("from"), act.get("to"))
            if r is None:
                notes.append(f"skipped a {kind} with invalid word IDs")
                continue
            if kind == "cut":
                removed |= set(r)
            else:
                removed -= set(r)
        elif kind == "keep_only":
            keep: set[int] = set()
            for pair in act.get("ranges") or []:
                r = rng(*pair) if isinstance(pair, (list, tuple)) and len(pair) == 2 else None
                if r is None:
                    notes.append("skipped an invalid keep range")
                    continue
                keep |= set(r)
            if not keep:
                notes.append("skipped keep_only with no valid ranges")
                continue
            removed = (removed & keep) | (set(range(n_words)) - keep)
        elif kind == "restore_all":
            removed = set()
        elif kind == "settings":
            if isinstance(act.get("remove_silences"), bool):
                settings["remove_silences"] = act["remove_silences"]
            ms = act.get("min_silence")
            if isinstance(ms, (int, float)) and not isinstance(ms, bool):
                settings["min_silence"] = round(min(2.0, max(0.3, float(ms))), 2)
        elif kind == "captions":
            if isinstance(act.get("enabled"), bool):
                captions["enabled"] = act["enabled"]
        else:
            notes.append(f"skipped unknown action '{kind}'")
    if len(removed) >= n_words:
        notes.append("refused to cut every word")
        return set(), settings, captions, notes
    return removed, settings, captions, notes


def style_actions(actions: list, current: dict, n_words: int) -> tuple[dict, list[str]]:
    """Collect validated style changes from 'style' and 'keywords' actions. Returns (changes, notes)."""
    changes: dict = {}
    notes: list[str] = []
    keywords = set(current.get("keywords", []))
    touched_kw = False
    for act in actions if isinstance(actions, list) else []:
        if not isinstance(act, dict):
            continue
        if act.get("type") == "style":
            raw = {k: v for k, v in act.items() if k != "type"}
            clean = stylelib.clean_style(raw, n_words)
            clean.pop("keywords", None)
            clean.pop("topic_breaks", None)
            if len(clean) < len([k for k in raw if k not in ("keywords", "topic_breaks")]):
                notes.append("skipped unknown or invalid style values")
            changes.update(clean)
        elif act.get("type") == "keywords":
            add = stylelib.clean_style({"keywords": act.get("add") or []}, n_words).get("keywords", [])
            rem = stylelib.clean_style({"keywords": act.get("remove") or []}, n_words).get("keywords", [])
            keywords = (keywords | set(add)) - set(rem)
            touched_kw = True
    if touched_kw:
        changes["keywords"] = sorted(keywords)
    return changes, notes


def chat_edit(transcript: dict, plan: dict, message: str, history: list[dict],
              rebuild) -> tuple[dict, str, list[str]]:
    """Run one chat request. `rebuild(removed, settings, captions)` returns a new plan.

    If the user asked for a target length and the first result misses it, the AI gets one chance to adjust.
    Returns (new plan, reply text, notes).
    """
    n = len(transcript["words"])
    msgs = []
    for h in history[-6:]:
        if h.get("role") in ("user", "assistant") and h.get("text"):
            msgs.append({"role": h["role"], "content": h["text"]})

    def ask(current: dict, extra: str = "") -> dict:
        state = (f"Original length {current['duration']:.1f}s, current edited length {current['edited_duration']:.1f}s. "
                 f"Pause tightening: {'on' if current['settings'].get('remove_silences', True) else 'off'} "
                 f"(pauses over {current['settings'].get('min_silence', 0.6)}s). "
                 f"Captions: {'on' if current.get('captions', {}).get('enabled', True) else 'off'}.\n"
                 f"Style: {json.dumps(stylelib.effective(current), ensure_ascii=False)}\n\n"
                 f"TRANSCRIPT:\n{transcript_listing(transcript, set(current['removed_words']))}")
        return chat_json(CHAT_SYSTEM, [{"role": "user", "content": state}, *msgs,
                                        {"role": "user", "content": message + extra}])

    reply = ask(plan)
    removed, settings, captions, notes = apply_actions(
        [a for a in reply.get("actions", []) or [] if not (isinstance(a, dict) and a.get("type") in ("style", "keywords"))],
        set(plan["removed_words"]), n)
    style, style_notes = style_actions(reply.get("actions", []), stylelib.effective(plan), n)
    notes += style_notes
    if style.get("keyword_pop") and not style.get("keywords") and not stylelib.effective(plan).get("keywords"):
        style["keywords"] = stylelib.auto_keywords(transcript["words"], removed)
    new_plan = rebuild(removed, settings, captions, style) if style else rebuild(removed, settings, captions)
    text = str(reply.get("reply", "")).strip() or "Done."

    target = target_seconds(message)
    if target and reply.get("actions") and abs(new_plan["edited_duration"] - target) > max(4.0, 0.2 * target):
        try:
            fix = ask(new_plan, f"\n\n(Your edit gave {new_plan['edited_duration']:.1f}s but the target is "
                                f"{target:.0f}s. Adjust the current state with more actions to get close to the target.)")
            removed2, s2, c2, notes2 = apply_actions(fix.get("actions", []), set(new_plan["removed_words"]), n)
            candidate = (rebuild(removed2, {**settings, **s2}, {**captions, **c2}, style) if style
                         else rebuild(removed2, {**settings, **s2}, {**captions, **c2}))
            if abs(candidate["edited_duration"] - target) < abs(new_plan["edited_duration"] - target):
                new_plan, notes = candidate, notes + notes2
                text = str(fix.get("reply", "")).strip() or text
        except LLMError:
            pass
    return new_plan, text, notes


def summarize(old: dict, new: dict) -> str:
    before, after = set(old["removed_words"]), set(new["removed_words"])
    parts = []
    if after - before:
        parts.append(f"cut {len(after - before)} words")
    if before - after:
        parts.append(f"restored {len(before - after)} words")
    if old.get("settings") != new.get("settings"):
        parts.append("changed pause settings")
    if old.get("captions") != new.get("captions"):
        parts.append("changed captions")
    so, sn = old.get("style") or {}, new.get("style") or {}
    changed_keys = sorted(k for k in set(so) | set(sn) if so.get(k) != sn.get(k))
    if changed_keys:
        parts.append("changed style: " + ", ".join(changed_keys))
    parts.append(f"length {old['edited_duration']:.1f}s → {new['edited_duration']:.1f}s")
    return ", ".join(parts)
