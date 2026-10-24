"""Grow: account set-up, scripts and take notes (Growth Starter + Viral Script skills).

The AI writes markdown; nothing here touches Instagram. Research on Instagram is done by the creator in their
own app or browser (the "explore page hack"), and they bring back links, view counts, screenshots or a screen
recording of a reference reel. Every number in the output must come from the creator or from what they pasted;
estimates are labelled "est.".

data/grow/
    starter-kit_<time>.md   account set-up (topic + TAM, study list, bio, highlights, warm-up, week 1, practice)
    script_<time>.md        a script modelled on a reference reel
    style.md                the creator's voice (updated with each script that has voice samples)
    style_<time>.md         earlier versions of style.md
"""
from __future__ import annotations

import base64
import re
import time
from pathlib import Path

from .config import DATA_DIR
from .llm import chat_text

GROW_DIR = DATA_DIR / "grow"
SAFE = re.compile(r"^[A-Za-z0-9_.-]+\.md$")
STYLE_MARK = "=====STYLE.MD====="

RULES = """Rules (always):
- Never invent numbers, results, views, followers, money or credentials. Use only what the creator gave you or what
  appears in what they pasted. Anything estimated is labelled "est.". If something needed is missing, say what to
  check and where, instead of guessing.
- Don't promise followers or views; this raises the odds, the algorithm decides.
- Never suggest buying followers, engagement groups, follow/unfollow, or any automation that acts on Instagram.
- Creators are studied for the pattern (hook, structure, CTA), never copied: no reusing their words, names, branding
  or characters. Credit them by handle.
- Skip harmful trends (scams, gambling, hacking accounts, anything that hurts people), even viral ones.
- Write for Indian creators when relevant: keep the creator's language, keep English tech words in English."""

STARTER_SYSTEM = f"""You are the "Growth Starter" auditor. You get a creator ready to post, so the first reels land on a
topic people already care about, from an account that tells a visitor in 3 seconds why to follow.
Framework (hadibuilds.com/grow): 1) pick a topic with a big audience first (check the TAM), niche down later;
2) find reels that already work and copy the pattern (hook, structure, CTA), never the video; 3) practise the
presentation (or the voiceover if faceless); 4) fresh account, warmed up for 2 days, bio done before the first reel.

You get the creator's interview answers, maybe their current profile, maybe research they did (Instagram keyword
search results, reels with view counts, screenshots). You cannot browse. Where the research is missing, give the
exact searches to run: https://www.instagram.com/explore/search/keyword/?q=<phrase> (3-5 phrasings, in English
and in their language), plus YouTube/Google, and mark the TAM scores "est." until they check.

Write ONE markdown file called starter-kit.md with exactly these sections:
# Starter kit: <name>
## 1. Starting topic
- A table scoring each topic idea 1-5 on Mass (would a normal person stop?), Proof (are reels about it getting big
  views now, including small accounts?), Room (crowded in their language or open?), Fit (can they make 100 videos?).
- ONE wide starting topic (the big circle) and the niche for later (the small circle), in two lines,
  e.g. "start: AI tools for everyone -> later: AI for clinics".
## 2. Study list
| Reel (link) | Creator | Views (real or est.) | Hook (first 3 s) | Structure | CTA |  -- only reels the creator
gave you; if none, the searches to run and what to note. Then the 3 FORMATS to copy first (structure, not words).
## 3. Profile
- If a current profile was given: a yes/no checklist audit first (name field searchable, who it's for, what they
  get, proof, free resource + link reason, clear picture, highlights), then the rewrite.
- Name field (searchable): `Name | topic`. Bio version A and B, 4 short lines each: who it's for / what they get /
  proof (only what they gave) / the free resource + a reason to tap the link.
- Profile picture brief (clear face, looking at camera, plain one-colour background, high contrast, readable as a
  tiny circle). Highlights (3): "Start here", a proof one, "Community" or "Free". First 3 reels to pin (the 3 formats).
## 4. Account plan
- Fresh account recommendation (experience, not a guarantee). 2-day warm-up checklist (20-30 min a day: search
  the topic, watch reels to the end, like and save good ones, follow 10-20 niche accounts, no posting; finish bio,
  picture, highlights). Week 1: one reel a day from the 3 formats; post 2-3 hook variations of the best idea as
  trial reels and keep the winner.
## 5. Practice plan
- Record the same hook 3 times, a little different each time; keep the one that sounds like talking to a friend.
  Faceless: the voiceover is the face, record 3 times, keep the clearest and most energetic. Ask for notes on a take
  (this app's "Coach this take" button does that on any uploaded video).

{RULES}
Reply with the markdown only."""

SCRIPT_SYSTEM = f"""You are "Viral Script". You take the skeleton of a reel that is already working (hook -> structure ->
CTA) and write the creator's version, in their language, sounding like them.

You get: the creator's topic, audience, language (and what stays in English), samples of their voice, their CTA
(comment keyword + giveaway), maybe their starter kit, and a REFERENCE reel: its transcript with times (from a
screen recording) and/or notes and view counts the creator pasted.

Write markdown with these sections:
## Reference: why it works
- Beat map table | Time | Words | On screen | Beat |  with beats labelled hook / context / proof / payload / CTA.
- Why it worked in 3 lines. Name the pattern if one fits ("X just killed Y", "Secret / feels illegal",
  "It can now...", "Proof number + transformation", "Life moment") and the hook psychology (a specific number feels
  real; a before -> after; a gap: short time or a secret -> "wait, how?").
## Script
| Time | On screen | VO (their language) |  -- keep the order of beats and the rhythm, change the words, examples and
topic to theirs. Spoken, not written: short sentences, the way they talk; English tech words stay English.
Roughly the reference's length (25-45 s is the sweet spot). Cut words, not beats. Their real numbers only.
## 3 hooks (0:00-0:03) to post as trial reels
1. like the reference  2. bolder (a big proof number or "X just killed Y", only if true)  3. personal
## Caption
2-4 short lines + the keyword CTA + 3-4 hashtags. Then the DM line (what they send to people who comment).
## Before recording
The 2-4 things they must check (numbers, names, claims). Fact-check every claim: if the reference says something
false or unprovable ("100% safe", "runs on autopilot"), don't put it in their mouth: flag it and give a true line.

Then, ONLY if voice samples were given, a line with exactly {STYLE_MARK} followed by a short style.md: sentence
length, words they use and never use, how they open and close, English words they keep.

{RULES}
Reply with the markdown only."""

COACH_SYSTEM = """You are a presentation coach for short talking-head videos (reels). You get the transcript of one
practice take with timing measurements (you cannot hear or see the video). Give exactly 3 notes:
1. Energy (judge from pace changes, sentence length, pauses and word choice; say plainly that energy is inferred from
   the words and timing, not heard), 2. Pace (words per minute, long pauses, fillers), 3. The first 3 seconds (is
   there a hook a stranger would stop for? quote it and offer one sharper version in the same language).
Each note: what you noticed with the numbers given, and one concrete thing to do on the next take.
Keep it short, kind and specific. Same language as the transcript if it isn't English, with English terms kept.
Never invent numbers."""


def _save(prefix: str, text: str) -> str:
    GROW_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{prefix}_{time.strftime('%Y%m%d-%H%M%S')}.md"
    (GROW_DIR / name).write_text(text, encoding="utf-8")
    return name


def list_files() -> list[dict]:
    if not GROW_DIR.exists():
        return []
    out = []
    for p in GROW_DIR.glob("*.md"):
        kind = "style" if p.name.startswith("style") else p.name.split("_")[0]
        out.append({"name": p.name, "kind": kind, "time": p.stat().st_mtime, "size": p.stat().st_size})
    return sorted(out, key=lambda f: f["time"], reverse=True)


def read_file(name: str) -> str:
    if not SAFE.match(name) or not (GROW_DIR / name).is_file():
        raise KeyError(name)
    return (GROW_DIR / name).read_text(encoding="utf-8")


def latest(kind: str) -> str | None:
    if kind == "style":
        p = GROW_DIR / "style.md"
        return p.read_text(encoding="utf-8") if p.exists() else None
    files = [f for f in list_files() if f["kind"] == kind]
    return read_file(files[0]["name"]) if files else None


def _block(title: str, text: str | None) -> str:
    text = (text or "").strip()
    return f"### {title}\n{text if text else '(not given)'}\n\n"


def image_parts(images: list[tuple[str, bytes]]) -> list[dict]:
    parts = []
    for mime, data in images[:4]:
        parts.append({"type": "image_url",
                      "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}})
    return parts


def starter_kit(answers: dict, images: list[tuple[str, bytes]] | None = None) -> tuple[str, str]:
    """Returns (file name, markdown)."""
    questions = [("about", "1. Who are you and what do you know well?"),
                 ("topics", "2. 2-3 topics you'd like to make videos about"),
                 ("audience", "3. Who should watch? (mass, or a specific group)"),
                 ("language", "4. Language of the videos"),
                 ("face", "5. Face on camera or faceless?"),
                 ("goal", "6. What do you want from it?"),
                 ("proof", "7. Proof you can show, and one free thing you can give away"),
                 ("profile", "Current profile (name field, bio, highlights), if any"),
                 ("research", "Research they did (search results, reels with views, links)")]
    text = "".join(_block(q, answers.get(k)) for k, q in questions)
    if images:
        text += f"### Screenshots\n{len(images[:4])} screenshot(s) attached (profile or search results). Read them.\n"
    content = [{"type": "text", "text": text}, *image_parts(images or [])] if images else text
    md = chat_text(STARTER_SYSTEM, [{"role": "user", "content": content}])
    return _save("starter-kit", md), md


def script(fields: dict, reference_transcript: str = "") -> tuple[str, str, str | None]:
    """Returns (file name, script markdown, style.md or None)."""
    text = (_block("Topic", fields.get("topic")) + _block("Audience", fields.get("audience"))
            + _block("Language of the script, and what stays in English", fields.get("language"))
            + _block("Their voice: samples of their captions or scripts", fields.get("voice"))
            + _block("Existing style.md", latest("style"))
            + _block("CTA: comment keyword and what they give away", fields.get("cta"))
            + _block("Reference reel transcript with times", reference_transcript or fields.get("reference"))
            + _block("Reference notes (creator handle, link, views; est. if estimated)", fields.get("notes"))
            + _block("Starter kit", latest("starter-kit")))
    md = chat_text(SCRIPT_SYSTEM, [{"role": "user", "content": text}])
    style = None
    if STYLE_MARK in md:
        md, style = md.split(STYLE_MARK, 1)
        md, style = md.strip(), style.strip()
        if style:
            GROW_DIR.mkdir(parents=True, exist_ok=True)
            cur = GROW_DIR / "style.md"
            if cur.exists():
                cur.replace(GROW_DIR / f"style_{time.strftime('%Y%m%d-%H%M%S')}.md")
            cur.write_text(style, encoding="utf-8")
    return _save("script", md), md, style


def transcript_with_times(transcript: dict) -> str:
    """'[0.0s] words ...' lines, one per segment, for a reference reel."""
    words = transcript.get("words", [])
    lines = []
    for seg in transcript.get("segments") or []:
        ids = seg.get("word_ids") or []
        if ids:
            lines.append(f'[{seg["start"]:.1f}s] ' + " ".join(words[i]["text"] for i in ids))
    return "\n".join(lines) or " ".join(w["text"] for w in words)


def take_metrics(transcript: dict, plan: dict | None = None) -> dict:
    words = transcript.get("words", [])
    if not words:
        return {"words": 0}
    dur = max(0.1, words[-1]["end"] - words[0]["start"])
    gaps = [b["start"] - a["end"] for a, b in zip(words, words[1:])]
    first3 = [w["text"] for w in words if w["start"] < words[0]["start"] + 3.0]
    lengths, cur = [], 0
    for w in words:
        cur += 1
        if w["text"].endswith((".", "?", "!", "।")):
            lengths.append(cur)
            cur = 0
    return {"words": len(words), "speaking_seconds": round(dur, 1), "words_per_minute": round(len(words) / dur * 60),
            "pauses_over_0_6s": sum(g > 0.6 for g in gaps), "pauses_over_1_5s": sum(g > 1.5 for g in gaps),
            "longest_pause_s": round(max(gaps), 2) if gaps else 0, "first_3_seconds": " ".join(first3),
            "filler_words": len((plan or {}).get("filler_words", [])),
            "retakes_found": len((plan or {}).get("retakes", [])),
            "average_sentence_words": round(sum(lengths) / len(lengths), 1) if lengths else None}


def coach(transcript: dict, plan: dict | None = None) -> str:
    m = take_metrics(transcript, plan)
    text = ("Measurements:\n" + "\n".join(f"- {k}: {v}" for k, v in m.items())
            + "\n\nTranscript with times:\n" + transcript_with_times(transcript))
    return chat_text(COACH_SYSTEM, [{"role": "user", "content": text}])
