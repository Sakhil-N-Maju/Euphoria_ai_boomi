"""Marketplace skills, page 2 (+ video-understand from page 1):

  broll-match-engine       B-roll library: the creator's own clips are described (AI vision on a frame, or the
                           file name) and matched to the planned b-roll moments, so no generation is needed
  social-carousel          Carousel: 5-7 slides (1080x1350 PNG) of the video's key points, over a blurred frame
  video-understand /       Review the render: frames of the rendered video + the captions go to an AI vision
  ffmpeg-analyse-video     model, which reports problems with timestamps (text over the face, cut-off text...)

AI replies are validated: clip and moment ids must exist, every clip is used at most once.
"""
from __future__ import annotations

import base64
import hashlib
import json
import subprocess
from pathlib import Path

from .captions import ass_color
from .config import find_tool
from .llm import LLMError, chat_json
from .media import probe, run_ffmpeg
from .timeline import edited_words

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _frame_jpeg(src: Path, at: float, width: int = 384) -> bytes:
    return subprocess.run([find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-ss", f"{at:.2f}",
                           "-i", str(src), "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", "-f", "image2",
                           "-c:v", "mjpeg", "pipe:1"], capture_output=True, creationflags=_NO_WINDOW).stdout


def _img(data: bytes) -> dict:
    return {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(data).decode()}}


# ---------- broll-match-engine ----------

def library(job_dir: Path) -> list[dict]:
    p = job_dir / "library.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def _save_library(job_dir: Path, items: list[dict]) -> None:
    (job_dir / "library.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


DESCRIBE_SYSTEM = """You describe stock clips for a video editor. For each numbered frame, write what the clip shows in
one short line (subject, action, setting, shot type), e.g. "close-up of hands typing on a laptop in a dark room".
Reply with JSON only: {"descriptions": ["...", "..."]} in the same order."""


def add_to_library(job_dir: Path, tmp: Path, name: str, use_ai: bool) -> dict:
    """Store a clip in the job's b-roll library with a thumbnail and a description."""
    h = hashlib.sha1(tmp.read_bytes()[: 4 * 1024 * 1024]).hexdigest()[:8]
    dest = job_dir / f"lib_{h}{tmp.suffix.lower()}"
    tmp.replace(dest)
    info = probe(dest)
    thumb = _frame_jpeg(dest, min(info.duration / 2, 2.0), 320)
    (job_dir / f"lib_{h}.jpg").write_bytes(thumb)
    desc = Path(name).stem.replace("_", " ").replace("-", " ")
    if use_ai and thumb:
        try:
            reply = chat_json(DESCRIBE_SYSTEM, [{"role": "user", "content": [
                {"type": "text", "text": f"Frame 1 (file name: {name})"}, _img(thumb)]}])
            got = reply.get("descriptions") or []
            if got and isinstance(got[0], str) and got[0].strip():
                desc = got[0].strip()[:140]
        except LLMError:
            pass        # no vision model: the file name is the description
    items = [i for i in library(job_dir) if i["file"] != dest.name]
    item = {"file": dest.name, "thumb": f"lib_{h}.jpg", "name": Path(name).name[:80], "duration": round(info.duration, 2),
            "has_audio": info.has_audio, "desc": desc}
    _save_library(job_dir, items + [item])
    return item


def remove_from_library(job_dir: Path, file: str) -> None:
    items = library(job_dir)
    keep = [i for i in items if i["file"] != file]
    for i in items:
        if i["file"] == file:
            (job_dir / i["file"]).unlink(missing_ok=True)
            (job_dir / i["thumb"]).unlink(missing_ok=True)
    _save_library(job_dir, keep)


MATCH_SYSTEM = """You are a video editor matching the creator's own b-roll clips to the moments of a talking-head video.
You get MOMENTS (id, what should be shown, the line it covers) and CLIPS (number, description). Assign the best clip
to each moment where one fits well. A clip is used at most once. Leave a moment out if no clip fits: a wrong
picture is worse than none.
Reply with JSON only: {"matches": [{"moment": "<moment id>", "clip": <clip number>, "why": "<few words>"}]}"""


def match_library(job_dir: Path, transcript: dict, plan: dict) -> list[dict]:
    lib = library(job_dir)
    moments = [b for b in plan.get("broll") or []]
    if not lib or not moments:
        return []
    words = transcript["words"]
    text = "MOMENTS:\n" + "\n".join(
        f'{b["id"]}: show "{b.get("show", "")}"; line: "{" ".join(w["text"] for w in words[b["from_word"]:b["to_word"] + 1])}"'
        for b in moments) + "\n\nCLIPS:\n" + "\n".join(f'{k}: {c["desc"]} ({c["duration"]}s)' for k, c in enumerate(lib))
    reply = chat_json(MATCH_SYSTEM, [{"role": "user", "content": text}])
    ids = {b["id"] for b in moments}
    used, out = set(), []
    for m in reply.get("matches") or []:
        try:
            k = int(m.get("clip"))
        except (TypeError, ValueError, AttributeError):
            continue
        mid = str(m.get("moment", ""))
        if mid in ids and 0 <= k < len(lib) and k not in used and mid not in {o["moment"] for o in out}:
            used.add(k)
            out.append({"moment": mid, "clip": lib[k]["file"], "desc": lib[k]["desc"], "why": str(m.get("why", ""))[:60],
                        "duration": lib[k]["duration"], "has_audio": lib[k]["has_audio"]})
    return out


# ---------- social-carousel ----------

CAROUSEL_SYSTEM = """You turn a talking-head video into an Instagram carousel, in the language the speaker uses (keep
English tech words in English). You get the transcript. Write 5-7 slides:
slide 1 = the hook (a big promise or question from the video), middle slides = one key point each, last slide =
the call to action (use the creator's comment keyword if one is given, else "Save this" / "Follow for more").
Each slide: "title" (max 6 words) and "body" (max 22 words). Only claims the speaker makes; never invent numbers.
Reply with JSON only: {"slides": [{"title": "...", "body": "..."}]}"""


def carousel(job_dir: Path, source: Path, transcript: dict, plan: dict, style: dict, font: str) -> list[str]:
    ew = edited_words(transcript, plan)
    text = " ".join(w["text"] for w in ew)
    extra = f'Comment keyword: {style["cta_keyword"]}\n' if style.get("cta_keyword") else ""
    reply = chat_json(CAROUSEL_SYSTEM, [{"role": "user", "content": extra + "TRANSCRIPT:\n" + text[:12000]}])
    slides = [s for s in reply.get("slides") or [] if isinstance(s, dict) and str(s.get("title", "")).strip()][:7]
    if not slides:
        raise ValueError("The AI didn't return any slides.")
    out_dir = job_dir / "exports"
    out_dir.mkdir(exist_ok=True)
    for old in out_dir.glob("carousel_*.png"):
        old.unlink()
    info = probe(source)
    W, H = 1080, 1350
    accent = ass_color(style.get("accent", "#FFD23F"))
    names = []
    for n, s in enumerate(slides, 1):
        t = info.duration * (n / (len(slides) + 1))
        title = str(s["title"]).strip()[:60].replace("{", "(").replace("}", ")")
        body = str(s.get("body", "")).strip()[:180].replace("{", "(").replace("}", ")")
        ass = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "",
               "[V4+ Styles]",
               "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
               "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
               "MarginL, MarginR, MarginV, Encoding",
               f"Style: Title,{font},96,{accent},{accent},&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,7,90,90,0,1",
               f"Style: Body,{font},54,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,7,90,90,0,1",
               f"Style: Num,{font},36,&H00B4B4B4,&H00B4B4B4,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,9,70,70,60,1",
               "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
               f"Dialogue: 0,0:00:00.00,0:00:10.00,Title,,0,0,0,,{{\\pos(90,{round(H * 0.3)})}}{title}",
               f"Dialogue: 0,0:00:00.00,0:00:10.00,Body,,0,0,0,,{{\\pos(90,{round(H * 0.3) + 260})}}{body}",
               f"Dialogue: 0,0:00:00.00,0:00:10.00,Num,,0,0,0,,{n}/{len(slides)}"]
        (out_dir / f"carousel_{n}.ass").write_text("\n".join(ass) + "\n", encoding="utf-8-sig")
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=28,"
              f"eq=brightness=-0.42:saturation=0.75,drawbox=x=90:y={round(H * 0.3) - 40}:w=120:h=10:color={style.get('accent', '#FFD23F').replace('#', '0x')}:t=fill,"
              f"subtitles=carousel_{n}.ass")
        name = f"carousel_{n}.png"
        run_ffmpeg(["-ss", f"{t:.2f}", "-i", str(source.resolve()), "-frames:v", "1", "-vf", vf, name],
                   cwd=out_dir, expected_duration=1)
        (out_dir / f"carousel_{n}.ass").unlink(missing_ok=True)
        names.append(name)
    return names


# ---------- video-understand / ffmpeg-analyse-video: review the render ----------

REVIEW_SYSTEM = """You are the quality check for a finished vertical or horizontal social video. You get frames of the
RENDERED video with their times, and the captions that should be on screen. Look for real problems only:
captions or titles covering the face, text cut off at the edges or hidden behind Instagram's buttons (right side) or
caption area (bottom ~20%), unreadable text (low contrast, too small), a frame that looks broken (black, frozen,
stretched, badly cropped head), b-roll that doesn't match what is said, harsh colour or exposure.
Reply in markdown: a one-line verdict, then a table | Time | Problem | Fix | (only real problems; "No problems found"
if none), then up to 3 suggestions to make it stronger. Be specific and short. Never invent what you can't see."""


def review(source: Path, transcript: dict, plan: dict, speed: float = 1.0, frames: int = 8) -> str:
    from .llm import chat_text
    info = probe(source)
    times = [round(info.duration * (k + 0.5) / frames, 2) for k in range(frames)]
    ew = edited_words(transcript, plan)
    parts: list[dict] = [{"type": "text", "text": f"Video {info.width}x{info.height}, {info.duration:.1f}s."}]
    for t in times:
        data = _frame_jpeg(source, t, 512)
        if not data:
            continue
        near = " ".join(w["text"] for w in ew if abs(w["start"] * speed - t) < 1.5)
        parts += [{"type": "text", "text": f"Frame at {t:.1f}s. Words spoken around it: {near or '(none)'}"}, _img(data)]
    return chat_text(REVIEW_SYSTEM, [{"role": "user", "content": parts}])
