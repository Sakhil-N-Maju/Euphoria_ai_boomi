"""B-roll map and generation prompts (B-Roll Prompter skill).

The AI reads the current cut and marks the moments that need a visual. For each one it fills the fixed
formula  Subject + Action + Setting + Camera + Style; this module assembles the prompt itself, so every prompt
follows the formula, shares one style phrase, and ends with the no-music line. The user generates each clip
(OpenArt or any video model: 5 s, 16:9 or 9:16, same model for the whole set) and uploads it; the renderer
trims it to its slot and covers the speaker while the voice keeps running.
"""
from __future__ import annotations

import uuid

from .aiedit import transcript_listing
from .llm import chat_json

NO_MUSIC = "No background music, natural diegetic sound only."
CAMERAS = ("static", "slow push-in", "slow orbit", "tracking", "top-down", "macro", "handheld")
MAX_WORDS_PER_MOMENT = 40

DEFAULT_STYLE_PHRASE = "high-end commercial realism, soft natural light, muted warm palette"
ARCHIVAL_STYLE_PHRASE = ("archival 16mm documentary footage, soft natural light, gentle halation, "
                         "muted tones, fine film grain")

BROLL_SYSTEM = """You are a video editor planning B-ROLL for a talking-head video (Malayalam, Hindi, English or
code-mixed). You get the transcript of the CURRENT CUT as numbered words: [s3 12.4-18.9s] 40:word ... (~x~ = cut).

Mark every moment where the viewer should see something other than the speaker:
- a claim -> show the proof; a story beat -> show the scene; a noun the viewer can picture
  (a product, a place, a process) -> show the thing.
- About one moment every 2 sentences. Each moment covers part of ONE sentence (never two sentences).
  Never two moments covering the same sentence. Skip the first sentence (the speaker hooks the viewer).

For each moment fill the formula Subject + Action + Setting + Camera, in ENGLISH, for a video generator:
- subject: specific, never "a person" (e.g. "a young woman in a mustard cotton kurta", "a steel tiffin box").
- action: ONE action only.
- setting: where it happens; fit the speaker's world (India, Kerala, the topic).
- camera: exactly one of: static, slow push-in, slow orbit, tracking, top-down, macro, handheld.
  Vary the camera across moments, not the look.
- No on-screen text, logos, captions or signs with readable words. No music.
- impact: true only if something drops, hits or lands in the shot.

Reply with JSON only:
{"moments": [{"from": <first word id>, "to": <last word id>, "show": "<what we'll show, a few words>",
  "subject": "...", "action": "...", "setting": "...", "camera": "...", "impact": false}]}"""


def compose_prompt(subject: str, action: str, setting: str, camera: str, style_phrase: str) -> str:
    """Subject + Action + Setting + Camera + Style, then the no-music line (always)."""
    parts = [p.strip().rstrip(".,") for p in (subject, action, setting) if p and p.strip()]
    cam = camera if camera in CAMERAS else "static"
    body = ", ".join(parts + [f"{cam} shot", style_phrase.strip().rstrip(".")])
    return f"{body[:1].upper()}{body[1:]}. {NO_MUSIC}"


def validate_moments(raw: list, words: list[dict], removed: set[int], max_count: int) -> list[dict]:
    n = len(words)
    out: list[dict] = []
    taken: set[int] = set()
    for m in raw if isinstance(raw, list) else []:
        if not isinstance(m, dict):
            continue
        try:
            a, b = int(m.get("from")), int(m.get("to"))
        except (TypeError, ValueError):
            continue
        if not (0 <= a <= b < n) or b - a + 1 > MAX_WORDS_PER_MOMENT:
            continue
        span = set(range(a, b + 1))
        if span & taken or len(span - removed) == 0:
            continue
        subject = str(m.get("subject", "")).strip()
        action = str(m.get("action", "")).strip()
        if not subject or not action:
            continue
        taken |= span
        out.append({"from_word": a, "to_word": b, "show": str(m.get("show", "")).strip()[:80] or subject[:80],
                    "subject": subject[:160], "action": action[:160], "setting": str(m.get("setting", "")).strip()[:160],
                    "camera": m.get("camera") if m.get("camera") in CAMERAS else "static",
                    "impact": bool(m.get("impact") is True)})
        if len(out) >= max_count:
            break
    return sorted(out, key=lambda x: x["from_word"])


def new_item(m: dict, style_phrase: str) -> dict:
    return {"id": uuid.uuid4().hex[:8], **m,
            "prompt": compose_prompt(m["subject"], m["action"], m["setting"], m["camera"], style_phrase),
            "layout": "full", "clip": None, "clip_duration": None, "clip_has_audio": False, "trim_start": None}


def plan_broll(transcript: dict, plan: dict, look: str = "clean") -> tuple[list[dict], str]:
    """Ask the AI for the b-roll map. Returns (new items, style phrase)."""
    removed = set(plan.get("removed_words", []))
    edited = float(plan.get("edited_duration") or plan.get("duration") or 60)
    max_count = max(1, min(12, round(edited / 7)))
    reply = chat_json(BROLL_SYSTEM, [{"role": "user", "content":
                      f"Edited length {edited:.0f}s: plan at most {max_count} moments.\n\n"
                      + transcript_listing(transcript, removed)}])
    style_phrase = ARCHIVAL_STYLE_PHRASE if look in ("archival", "archival_all") else DEFAULT_STYLE_PHRASE
    moments = validate_moments(reply.get("moments", []), transcript["words"], removed, max_count)
    return [new_item(m, style_phrase) for m in moments], style_phrase


def merge(existing: list[dict], new: list[dict]) -> list[dict]:
    """New map replaces moments without a clip; moments that already have a clip are kept."""
    keep = [b for b in existing if b.get("clip")]
    taken = {i for b in keep for i in range(b["from_word"], b["to_word"] + 1)}
    for b in new:
        if not taken & set(range(b["from_word"], b["to_word"] + 1)):
            keep.append(b)
    return sorted(keep, key=lambda b: b["from_word"])


def clean_item_update(changes: dict) -> dict:
    """Fields the review page may change on a b-roll moment."""
    out: dict = {}
    if isinstance(changes.get("prompt"), str):
        out["prompt"] = changes["prompt"].strip()[:1200]
    if isinstance(changes.get("show"), str):
        out["show"] = changes["show"].strip()[:80]
    if changes.get("layout") in ("full", "split"):
        out["layout"] = changes["layout"]
    if isinstance(changes.get("impact"), bool):
        out["impact"] = changes["impact"]
    t = changes.get("trim_start")
    if isinstance(t, (int, float)) and not isinstance(t, bool):
        out["trim_start"] = round(min(30.0, max(0.0, float(t))), 2)
    return out


def notes_markdown(name: str, items: list[dict], slots: dict, words: list[dict]) -> str:
    """A notes file for the generation session: every prompt, its slot, and room for the clip link."""
    text = {w["i"]: w["text"] for w in words}
    lines = [f"# B-roll prompts: {name}", "",
             "Generate every clip at 5 s, the video's aspect ratio, with the SAME model and settings for all of them.",
             "Generate the shot with a person in it first: people are where AI video fails most.",
             "The editor trims each clip to its best 2-4 s. Save each clip's link below as you go.", ""]
    for n, b in enumerate(items, 1):
        slot = slots.get(b["id"], {})
        when = f'{slot["start"]:.1f}s-{slot["end"]:.1f}s' if slot.get("start") is not None else "not placed"
        line = " ".join(text.get(i, "") for i in range(b["from_word"], b["to_word"] + 1))
        lines += [f"## {n}. {b.get('show', '')} ({when})", f'Covers: "{line}"', "", "```", b["prompt"], "```",
                  f"Clip: {b.get('clip') or '(not uploaded yet)'}", "Link: ", ""]
    return "\n".join(lines)
