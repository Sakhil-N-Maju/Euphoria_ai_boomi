"""More skills from the video-editing marketplace, built into the editor:

  subtitle-correction   fix_words()        AI fixes misheard words (names, English inside Malayalam) without
                                           touching timings; the original transcript is kept for "restore"
  subtitle-generation   translate_lines()  translated captions, cached per job (translations_<lang>.json)
  subtitle-packager     subtitles()        SRT / VTT of the edited video's captions
  caption-writer +      post_kit()         Instagram caption, YouTube titles, description with chapters at
  content-repurposer                       real edited-video times, hashtags, thumbnail text
  byted-las-video-edit  find_shorts()      2-3 self-contained highlight clips -> new videos in the list
  video-edit / ffmpeg   export()           WhatsApp-size, square / landscape / vertical with blurred fill,
                                           MP3, thumbnail

The AI only ever sees text and answers with word ids or text; every id is checked against the transcript.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from .aiedit import transcript_listing
from .config import find_tool
from .llm import chat_json
from .media import probe, run_ffmpeg
from .timeline import edited_words

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LANG_NAMES = {"en": "English", "hi": "Hindi", "ml": "Malayalam", "ta": "Tamil", "te": "Telugu", "kn": "Kannada",
              "bn": "Bengali", "mr": "Marathi", "gu": "Gujarati", "pa": "Punjabi", "ur": "Urdu", "ar": "Arabic",
              "es": "Spanish", "fr": "French"}


# ---------- subtitle-correction ----------

FIX_SYSTEM = """You correct speech-to-text mistakes in a talking-head transcript (Malayalam, Hindi, English or
code-mixed). You get numbered words: [s3 12.4-18.9s] 40:word 41:word ...

Fix only clear recognition errors: misheard names, brands and technical terms, English words written wrongly inside
Malayalam/Hindi speech (keep them in English letters), wrong numbers when context makes the right one certain, and
obvious misspellings. Do NOT rephrase, translate, add or remove words, fix grammar, or change meaning. One output
word per input word (a fix may contain a short phrase only if the recogniser split or merged words).
When unsure, leave the word alone.

Reply with JSON only: {"fixes": [{"id": <word id>, "text": "<corrected word>", "why": "<few words>"}]}"""


def fix_words(transcript: dict) -> list[dict]:
    """Ask the AI for corrections. Returns validated [{"id", "text", "old", "why"}] (not applied)."""
    words = transcript["words"]
    reply = chat_json(FIX_SYSTEM, [{"role": "user", "content": transcript_listing(transcript)}])
    out, seen = [], set()
    for f in reply.get("fixes", []) if isinstance(reply.get("fixes"), list) else []:
        try:
            i = int(f.get("id"))
        except (TypeError, ValueError, AttributeError):
            continue
        text = " ".join(str(f.get("text", "")).split())
        if not (0 <= i < len(words)) or i in seen or not text or len(text) > 40 or text == words[i]["text"]:
            continue
        seen.add(i)
        out.append({"id": i, "text": text, "old": words[i]["text"], "why": str(f.get("why", ""))[:60]})
    if len(out) > max(5, len(words) // 3):        # rewriting a third of the words isn't a correction
        out = out[: max(5, len(words) // 3)]
    return out


def apply_fixes(job_dir: Path, transcript: dict, fixes: list[dict]) -> dict:
    """Write the fixes into transcript.json; the first time, keep the original as transcript.orig.json."""
    orig = job_dir / "transcript.orig.json"
    if not orig.exists():
        orig.write_text(json.dumps(transcript, ensure_ascii=False, indent=1), encoding="utf-8")
    for f in fixes:
        w = transcript["words"][f["id"]]
        w.setdefault("orig_text", w["text"])
        w["text"] = f["text"]
    (job_dir / "transcript.json").write_text(json.dumps(transcript, ensure_ascii=False, indent=1), encoding="utf-8")
    return transcript


def restore_words(job_dir: Path) -> dict | None:
    orig = job_dir / "transcript.orig.json"
    if not orig.exists():
        return None
    shutil.copyfile(orig, job_dir / "transcript.json")
    data = json.loads(orig.read_text(encoding="utf-8"))
    orig.unlink()
    return data


# ---------- subtitle-generation: translation ----------

TRANSLATE_SYSTEM = """You translate short caption lines of a talking-head video into {lang}. Keep each line short and
natural for on-screen captions, keep names, brands and English tech words as they are, keep numbers exact.
Reply with JSON only: {{"lines": ["<translation of line 1>", "<translation of line 2>", ...]}} in the same order,
exactly one output per input line."""


def translate_lines(job_dir: Path, texts: list[str], lang: str) -> dict[str, str]:
    """Translate caption lines, reusing earlier translations. Returns {original line: translation}."""
    cache_path = job_dir / f"translations_{lang}.json"
    cache: dict[str, str] = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    todo = [t for t in dict.fromkeys(texts) if t not in cache]
    for k in range(0, len(todo), 40):
        chunk = todo[k:k + 40]
        reply = chat_json(TRANSLATE_SYSTEM.format(lang=LANG_NAMES.get(lang, lang)),
                          [{"role": "user", "content": json.dumps({"lines": chunk}, ensure_ascii=False)}])
        got = reply.get("lines") if isinstance(reply.get("lines"), list) else []
        if len(got) == len(chunk):
            for src, dst in zip(chunk, got):
                if isinstance(dst, str) and dst.strip():
                    cache[src] = " ".join(dst.split())[:120]
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return {t: cache[t] for t in texts if t in cache}


def cached_translations(job_dir: Path, lang: str) -> dict[str, str]:
    p = job_dir / f"translations_{lang}.json"
    return json.loads(p.read_text(encoding="utf-8")) if (lang and p.exists()) else {}


# ---------- subtitle-packager ----------

def _ts(t: float, sep: str) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def subtitles(lines: list[dict], fmt: str, speed: float = 1.0, translations: dict[str, str] | None = None,
              dual: bool = False) -> str:
    """SRT or VTT for the edited (and sped-up) video."""
    out = ["WEBVTT", ""] if fmt == "vtt" else []
    sep = "." if fmt == "vtt" else ","
    for n, line in enumerate(lines, 1):
        text = line["text"]
        if translations and translations.get(text):
            text = f"{text}\n{translations[text]}" if dual else translations[text]
        if fmt == "srt":
            out.append(str(n))
        out.append(f"{_ts(line['start'] / speed, sep)} --> {_ts(line['end'] / speed, sep)}")
        out += [text, ""]
    return "\n".join(out)


# ---------- caption-writer + content-repurposer: post kit ----------

POST_SYSTEM = """You write the posting copy for a finished talking-head video, in the language the creator speaks
(keep English tech words in English). You get the edited video's transcript as numbered words and its length.

Reply with JSON only:
{"instagram_caption": "<2-4 short lines that make people watch, then the CTA line>",
 "hashtags": ["#...", ...],                       (4-6, specific to the topic, no generic spam)
 "youtube_titles": ["...", "...", "..."],          (3 options, under 60 characters, no clickbait lies)
 "youtube_description": "<2-3 sentences>",
 "chapters": [{"word_id": <id of the first word of the chapter>, "title": "..."}],   (first chapter starts at the
                                                                                       first word; 3-8 chapters;
                                                                                       empty if under 60 s)
 "thumbnail_text": ["...", "...", "..."],          (2-4 words each)
 "linkedin_post": "<short post, 3-5 lines>",
 "dm_reply": "<what to send people who comment the keyword, if there is one>"}

Only claims the speaker makes. Never invent numbers, results or quotes."""


def post_kit(transcript: dict, plan: dict, style: dict, name: str) -> str:
    ew = edited_words(transcript, plan)
    by_id = {w["i"]: w for w in ew}
    dur = ew[-1]["end"] if ew else 0.0
    removed = set(plan.get("removed_words", []))
    extra = []
    if style.get("cta_keyword"):
        extra.append(f'Comment keyword (CTA): {style["cta_keyword"]} {style.get("cta_line", "")}')
    if style.get("title"):
        extra.append(f'On-screen title: {style["title"]}')
    reply = chat_json(POST_SYSTEM, [{"role": "user", "content":
                      f"Edited length {dur:.0f}s. " + " ".join(extra) + "\n\n" + transcript_listing(transcript, removed)}])
    s = lambda k: str(reply.get(k, "") or "").strip()  # noqa: E731
    chapters = []
    for c in reply.get("chapters") or []:
        try:
            w = by_id.get(int(c.get("word_id")))
        except (TypeError, ValueError, AttributeError):
            continue
        if w is not None and str(c.get("title", "")).strip():
            chapters.append((w["start"], str(c["title"]).strip()[:80]))
    chapters.sort()
    if chapters:
        chapters[0] = (0.0, chapters[0][1])            # YouTube needs the first chapter at 0:00
    if dur < 60 or len(chapters) < 3:
        chapters = []
    speed = float(style.get("speed", 1.0) or 1.0)

    def mmss(t: float) -> str:
        t = t / speed
        return f"{int(t // 60)}:{int(t % 60):02d}"

    tags = [t if str(t).startswith("#") else "#" + str(t) for t in (reply.get("hashtags") or [])][:6]
    md = [f"# Post kit: {name}", "", "## Instagram / Reels caption", "", s("instagram_caption"), "",
          " ".join(tags), "", "## YouTube", "", "**Title options**", ""]
    md += [f"{k}. {t}" for k, t in enumerate(reply.get("youtube_titles") or [], 1)]
    md += ["", "**Description**", "", s("youtube_description")]
    if chapters:
        md += [""] + [f"{mmss(t)} {title}" for t, title in chapters]
    md += ["", "## Thumbnail text", ""] + [f"- {t}" for t in reply.get("thumbnail_text") or []]
    md += ["", "## LinkedIn", "", s("linkedin_post")]
    if s("dm_reply"):
        md += ["", "## DM reply to commenters", "", s("dm_reply")]
    return "\n".join(md) + "\n"


# ---------- byted-las-video-edit: find shorts ----------

SHORTS_SYSTEM = """You find the best SHORT clips (reels/shorts) inside a longer talking-head video. You get the
transcript as numbered words in segments with times: [s3 12.4-18.9s] 40:word ...  (~x~ = already cut).

Pick up to {n} clips. Each clip: one complete, self-contained idea that makes sense without the rest of the video,
starting on a strong hook sentence and ending on a complete sentence, {lo}-{hi} seconds long. Clips may not overlap.
Reply with JSON only:
{{"clips": [{{"title": "<3-6 words>", "from": <first word id>, "to": <last word id>, "hook": "<why it hooks, few words>"}}]}}"""


def find_shorts(transcript: dict, plan: dict, n: int = 3, lo: float = 15, hi: float = 60) -> list[dict]:
    words = transcript["words"]
    removed = set(plan.get("removed_words", []))
    reply = chat_json(SHORTS_SYSTEM.format(n=n, lo=int(lo), hi=int(hi)),
                      [{"role": "user", "content": transcript_listing(transcript, removed)}])
    out, taken = [], set()
    for c in reply.get("clips") or []:
        try:
            a, b = int(c.get("from")), int(c.get("to"))
        except (TypeError, ValueError, AttributeError):
            continue
        if not (0 <= a <= b < len(words)):
            continue
        dur = words[b]["end"] - words[a]["start"]
        span = set(range(a, b + 1))
        if dur < lo * 0.7 or dur > hi * 1.3 or span & taken:
            continue
        taken |= span
        out.append({"title": str(c.get("title", "Short"))[:60], "from": a, "to": b, "seconds": round(dur, 1),
                    "hook": str(c.get("hook", ""))[:80]})
        if len(out) >= n:
            break
    return out


# ---------- video-edit / ffmpeg: export presets ----------

EXPORTS = {
    "whatsapp": "WhatsApp size (under 15 MB)",
    "square": "Square 1:1 (blurred fill)",
    "landscape": "Landscape 16:9 for YouTube (blurred fill)",
    "vertical": "Vertical 9:16 (blurred fill)",
    "mp3": "Audio only (MP3)",
    "thumbnail": "Thumbnail (JPG)",
}


def _blur_fill(w: int, h: int) -> str:
    return (f"[0:v]split=2[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
            f"gblur=sigma=30,eq=brightness=-0.08[bg];[b]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]")


def export(job_dir: Path, source: Path, kind: str, thumb_text: str = "", thumb_at: float | None = None,
           accent: str = "#FFD23F", font: str = "Nirmala UI") -> Path:
    """Make one export of the rendered video (output.mp4) into job_dir/exports/."""
    if kind not in EXPORTS:
        raise ValueError("Unknown export")
    info = probe(source)
    out_dir = job_dir / "exports"
    out_dir.mkdir(exist_ok=True)
    src = str(source.resolve())
    ext = {"mp3": ".mp3", "thumbnail": ".jpg"}.get(kind, ".mp4")
    out = out_dir / f"{kind}{ext}"
    a_args = ["-map", "0:a?", "-c:a", "aac", "-b:a", "128k"]
    if kind == "whatsapp":
        kb = max(300, int(14.5 * 8000 / max(1.0, info.duration) - 128))
        w, h = (720, int(720 * info.height / info.width) // 2 * 2) if info.width <= info.height else \
            (int(720 * info.width / info.height) // 2 * 2, 720)
        args = ["-i", src, "-vf", f"scale={w}:{h},format=yuv420p", "-c:v", "libx264", "-preset", "medium",
                "-b:v", f"{kb}k", "-maxrate", f"{int(kb * 1.2)}k", "-bufsize", f"{kb * 2}k", *a_args,
                "-movflags", "+faststart", str(out)]
    elif kind in ("square", "landscape", "vertical"):
        w, h = {"square": (1080, 1080), "landscape": (1920, 1080), "vertical": (1080, 1920)}[kind]
        args = ["-i", src, "-filter_complex", _blur_fill(w, h), "-map", "[v]", "-c:v", "libx264", "-preset",
                "veryfast", "-crf", "20", *a_args, "-movflags", "+faststart", str(out)]
    elif kind == "mp3":
        args = ["-i", src, "-vn", "-c:a", "libmp3lame", "-b:a", "192k", str(out)]
    else:   # thumbnail: a frame + big text, at the video's own shape
        t = thumb_at if thumb_at is not None else min(2.0, info.duration / 3)
        w, h = (1280, 720) if info.width >= info.height else (1080, 1920)
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},eq=brightness=-0.05:contrast=1.08"
        if thumb_text.strip():
            from .captions import ass_color
            size = round(min(w, h) * 0.13)
            ass = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}", "", "[V4+ Styles]",
                   "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
                   "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
                   "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
                   f"Style: T,{font},{size},&H00141414,&H00141414,{ass_color(accent)},&H00000000,-1,0,0,0,100,100,"
                   f"0,0,3,{round(size * 0.25)},0,2,{round(w * 0.06)},{round(w * 0.06)},{round(h * 0.1)},1",
                   "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
                   "Dialogue: 0,0:00:00.00,0:00:10.00,T,,0,0,0,," + thumb_text.strip()[:40].replace("{", "(")]
            (out_dir / "thumb.ass").write_text("\n".join(ass) + "\n", encoding="utf-8-sig")
            vf += ",subtitles=thumb.ass"
        args = ["-ss", f"{t:.2f}", "-i", src, "-frames:v", "1", "-vf", vf, "-q:v", "2", str(out)]
    run_ffmpeg(args, cwd=out_dir, expected_duration=info.duration)
    return out


def safe_export_name(name: str) -> bool:
    return bool(re.match(r"^[a-z]+(_\d+)?\.(mp4|mp3|jpg|png)$", name))
