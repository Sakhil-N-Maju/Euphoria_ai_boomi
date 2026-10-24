"""Local web app: python -m editor.server, then open http://127.0.0.1:8000"""
from __future__ import annotations

import os
import shutil
import threading
import webbrowser

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from . import broll as brolllib
from . import jobs, llm, sfx
from . import style as stylelib
from .config import JOBS_DIR, WEB_DIR
from .media import probe
from .transcribe import LANGUAGES

app = FastAPI(title="Team Euphoria video editor")

from . import reel as reellib  # Claude-edited reels: /site studio + /api/reels
app.include_router(reellib.router)

VIDEO_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime", ".m4v": "video/mp4",
               ".webm": "video/webm", ".mkv": "video/x-matroska", ".avi": "video/x-msvideo"}
AUDIO_TYPES = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4", ".aac": "audio/aac",
               ".ogg": "audio/ogg", ".flac": "audio/flac", ".opus": "audio/ogg"}
SFX_KINDS = ("whoosh", "whoosh_soft", "pop", "tick", "hit", "key")


def _music_file(d):
    found = sorted(p for p in d.glob("music.*") if p.is_file())
    return found[0] if found else None


def _extras(job_id: str, plan: dict) -> dict:
    """What the review page needs next to a plan: the effective style and the edited timeline."""
    return {"style": stylelib.effective(plan), "timeline": jobs.timeline(job_id, plan)}


def _save_upload(file: UploadFile, dest) -> None:
    with open(dest, "wb") as out:
        shutil.copyfileobj(file.file, out, length=1024 * 1024)


def _get_dir(job_id: str):
    try:
        return jobs.job_dir(job_id)
    except KeyError:
        raise HTTPException(404, "No such video")


@app.on_event("startup")
def _startup() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    jobs.resume_interrupted()
    reellib.resume_interrupted()
    from . import montage
    for m in montage.list_all():
        if m.get("status") in ("render queued", "rendering"):
            montage.enqueue(m["id"], bool(m.get("draft")))


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/languages")
def languages():
    return LANGUAGES


@app.get("/api/jobs")
def list_jobs():
    return jobs.list_jobs()


@app.post("/api/jobs")
def upload(file: UploadFile = File(...), language: str = Form("auto")):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in VIDEO_TYPES:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Use one of: {', '.join(VIDEO_TYPES)}")
    if language not in LANGUAGES:
        raise HTTPException(400, "Unknown language")
    job_id, dest = jobs.create_job(file.filename or "video.mp4", language)
    with open(dest, "wb") as out:
        shutil.copyfileobj(file.file, out, length=1024 * 1024)
    jobs.enqueue(job_id, "analyze")
    return jobs.read_meta(job_id)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    d = _get_dir(job_id)
    result = {"meta": jobs.read_meta(job_id)}
    if (d / "edit.yaml").exists():
        result["transcript"] = jobs.load_transcript(job_id)
        result["plan"] = jobs.load_plan(job_id)
        result["chat"] = jobs.load_chat(job_id)
        result["undo"] = jobs.history_size(job_id)
        result.update(_extras(job_id, result["plan"]))
        music = _music_file(d)
        result["music"] = music.name if music else None
        result["outputs"] = {"draft": (d / "draft.mp4").exists(), "final": (d / "output.mp4").exists()}
        result["exports"] = sorted(p.name for p in (d / "exports").glob("*.*") if p.suffix in (".mp4", ".mp3", ".jpg", ".png")) \
            if (d / "exports").exists() else []
        result["has_fixes"] = (d / "transcript.orig.json").exists()
        from . import extras2
        result["library"] = extras2.library(d)
    return result


@app.get("/api/ai")
def ai_status():
    return {"configured": llm.configured(), "model": llm.model_name()}


def _need_plan(job_id: str):
    d = _get_dir(job_id)
    if not (d / "edit.yaml").exists():
        raise HTTPException(409, "This video hasn't been transcribed yet")
    return d


@app.post("/api/jobs/{job_id}/retakes")
def find_retakes(job_id: str):
    _need_plan(job_id)
    try:
        plan, found = jobs.apply_retakes(job_id)
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc))
    return {"plan": plan, "found": found, "undo": jobs.history_size(job_id), **_extras(job_id, plan)}


class ChatMessage(BaseModel):
    message: str


@app.post("/api/jobs/{job_id}/chat")
def chat(job_id: str, body: ChatMessage):
    _need_plan(job_id)
    message = body.message.strip()
    if not message:
        raise HTTPException(400, "Type what you want changed")
    try:
        result = jobs.chat(job_id, message[:2000])
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc))
    result["undo"] = jobs.history_size(job_id)
    result.update(_extras(job_id, result["plan"]))
    return result


@app.post("/api/jobs/{job_id}/undo")
def undo(job_id: str):
    _need_plan(job_id)
    try:
        plan = jobs.undo(job_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return {"plan": plan, "undo": jobs.history_size(job_id), **_extras(job_id, plan)}


class PlanUpdate(BaseModel):
    removed_words: list[int] | None = None
    settings: dict | None = None
    captions: dict | None = None
    style: dict | None = None


@app.put("/api/jobs/{job_id}/plan")
def put_plan(job_id: str, body: PlanUpdate):
    d = _get_dir(job_id)
    if not (d / "transcript.json").exists():
        raise HTTPException(409, "This video hasn't been transcribed yet")
    plan = jobs.update_plan(job_id, body.removed_words, body.settings, body.captions, body.style)
    extras = _extras(job_id, plan)
    return {**plan, "_undo": jobs.history_size(job_id), "_style": extras["style"], "_timeline": extras["timeline"]}


# ---------- finishing: auto-style, b-roll, music, sound effects ----------

@app.post("/api/jobs/{job_id}/autostyle")
def autostyle(job_id: str):
    _need_plan(job_id)
    plan, how = jobs.autostyle(job_id)
    return {"plan": plan, "how": how, "undo": jobs.history_size(job_id), **_extras(job_id, plan)}


@app.post("/api/jobs/{job_id}/broll/plan")
def broll_plan(job_id: str):
    _need_plan(job_id)
    try:
        plan, count = jobs.plan_broll(job_id)
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc))
    return {"plan": plan, "found": count, "undo": jobs.history_size(job_id), **_extras(job_id, plan)}


@app.patch("/api/jobs/{job_id}/broll/{broll_id}")
def broll_update(job_id: str, broll_id: str, body: dict):
    _need_plan(job_id)
    try:
        plan = jobs.update_broll(job_id, broll_id, changes=body)
    except KeyError:
        raise HTTPException(404, "No such b-roll moment")
    return {"plan": plan, "undo": jobs.history_size(job_id), **_extras(job_id, plan)}


@app.delete("/api/jobs/{job_id}/broll/{broll_id}")
def broll_delete(job_id: str, broll_id: str):
    _need_plan(job_id)
    try:
        plan = jobs.update_broll(job_id, broll_id, delete=True)
    except KeyError:
        raise HTTPException(404, "No such b-roll moment")
    return {"plan": plan, "undo": jobs.history_size(job_id), **_extras(job_id, plan)}


@app.post("/api/jobs/{job_id}/broll/{broll_id}/clip")
def broll_clip_upload(job_id: str, broll_id: str, file: UploadFile = File(...)):
    d = _need_plan(job_id)
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in VIDEO_TYPES:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Use one of: {', '.join(VIDEO_TYPES)}")
    if not broll_id.isalnum():
        raise HTTPException(404, "No such b-roll moment")
    name = f"broll_{broll_id}{ext}"
    tmp = d / f"upload_{broll_id}.tmp{ext}"
    _save_upload(file, tmp)
    try:
        info = probe(tmp)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, "That file doesn't look like a video ffmpeg can read")
    for old in d.glob(f"broll_{broll_id}.*"):
        old.unlink()
    tmp.replace(d / name)
    try:
        plan = jobs.update_broll(job_id, broll_id, clip={"clip": name, "clip_duration": round(info.duration, 3),
                                                        "clip_has_audio": info.has_audio})
    except KeyError:
        (d / name).unlink(missing_ok=True)
        raise HTTPException(404, "No such b-roll moment")
    return {"plan": plan, "undo": jobs.history_size(job_id), **_extras(job_id, plan)}


@app.get("/api/jobs/{job_id}/broll/{broll_id}/clip")
def broll_clip(job_id: str, broll_id: str):
    d = _get_dir(job_id)
    item = next((b for b in jobs.load_plan(job_id).get("broll") or [] if b["id"] == broll_id), None)
    if not item or not item.get("clip") or not (d / item["clip"]).exists():
        raise HTTPException(404, "No clip")
    path = d / item["clip"]
    return FileResponse(path, media_type=VIDEO_TYPES.get(path.suffix.lower(), "video/mp4"))


@app.get("/api/jobs/{job_id}/broll.md")
def broll_notes(job_id: str):
    _need_plan(job_id)
    plan = jobs.load_plan(job_id)
    meta = jobs.read_meta(job_id)
    text = brolllib.notes_markdown(meta.get("name", "video"), plan.get("broll") or [],
                                   jobs.timeline(job_id, plan)["broll"], jobs.load_transcript(job_id)["words"])
    name = os.path.splitext(meta.get("name", "video"))[0] + "_broll_prompts.md"
    return PlainTextResponse(text, media_type="text/markdown",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/jobs/{job_id}/music")
def music_upload(job_id: str, file: UploadFile = File(...)):
    d = _need_plan(job_id)
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in AUDIO_TYPES and ext not in VIDEO_TYPES:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Use one of: {', '.join(AUDIO_TYPES)}")
    tmp = d / f"upload_music.tmp{ext}"
    _save_upload(file, tmp)
    try:
        if not probe_audio(tmp):
            raise ValueError
    except Exception:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, "That file has no audio ffmpeg can read")
    for old in d.glob("music.*"):
        old.unlink()
    tmp.replace(d / f"music{ext}")
    plan = jobs.update_plan(job_id, None, None, None, {"music": True})
    return {"plan": plan, "music": f"music{ext}", "undo": jobs.history_size(job_id), **_extras(job_id, plan)}


def probe_audio(path) -> bool:
    import json
    import subprocess

    from .config import find_tool
    out = subprocess.run([find_tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_streams", str(path)],
                         capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if out.returncode != 0:
        return False
    return any(s.get("codec_type") == "audio" for s in json.loads(out.stdout or "{}").get("streams", []))


@app.delete("/api/jobs/{job_id}/music")
def music_delete(job_id: str):
    d = _need_plan(job_id)
    for old in d.glob("music.*"):
        old.unlink()
    plan = jobs.update_plan(job_id, None, None, None, {"music": False})
    return {"plan": plan, "music": None, "undo": jobs.history_size(job_id), **_extras(job_id, plan)}


@app.get("/api/jobs/{job_id}/music")
def music_file(job_id: str):
    d = _get_dir(job_id)
    m = _music_file(d)
    if not m:
        raise HTTPException(404, "No music")
    return FileResponse(m, media_type=AUDIO_TYPES.get(m.suffix.lower(), "audio/mpeg"))


@app.get("/api/jobs/{job_id}/sfx/{kind}.wav")
def sfx_preview(job_id: str, kind: str):
    d = _need_plan(job_id)
    if kind not in SFX_KINDS:
        raise HTTPException(404, "Unknown effect")
    st = stylelib.effective(jobs.load_plan(job_id))
    path = sfx.preview_wav(kind, st, d / f"preview_{kind}.wav")
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@app.post("/api/jobs/{job_id}/render")
def start_render(job_id: str, draft: bool = False):
    d = _get_dir(job_id)
    if not (d / "edit.yaml").exists():
        raise HTTPException(409, "This video hasn't been transcribed yet")
    status = jobs.read_meta(job_id).get("status")
    if status in ("queued", "transcribing", "finding retakes", "render queued", "rendering"):
        raise HTTPException(409, "This video is already being processed")
    jobs.enqueue(job_id, "draft" if draft else "render")
    return jobs.read_meta(job_id)


@app.get("/api/jobs/{job_id}/source")
def source_video(job_id: str):
    d = _get_dir(job_id)
    src = d / jobs.read_meta(job_id)["source"]
    return FileResponse(src, media_type=VIDEO_TYPES.get(src.suffix.lower(), "video/mp4"))


@app.get("/api/jobs/{job_id}/output")
def output_video(job_id: str, download: bool = False):
    d = _get_dir(job_id)
    out = d / "output.mp4"
    if not out.exists():
        raise HTTPException(404, "Not rendered yet")
    name = os.path.splitext(jobs.read_meta(job_id).get("name", "video"))[0] + "_edited.mp4"
    return FileResponse(out, media_type="video/mp4", filename=name if download else None)


@app.get("/api/jobs/{job_id}/draft")
def draft_video(job_id: str):
    d = _get_dir(job_id)
    out = d / "draft.mp4"
    if not out.exists():
        raise HTTPException(404, "No draft yet")
    return FileResponse(out, media_type="video/mp4")


@app.get("/api/jobs/{job_id}/edit.yaml")
def plan_file(job_id: str):
    d = _get_dir(job_id)
    return FileResponse(d / "edit.yaml", media_type="text/yaml", filename="edit.yaml")


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    d = _get_dir(job_id)
    if jobs.read_meta(job_id).get("status") in ("transcribing", "finding retakes", "rendering"):
        raise HTTPException(409, "Wait for this video to finish processing first")
    shutil.rmtree(d)
    return {"deleted": job_id}


# ---------- colour: Look 01 LUT (teal-orange cinematic grade) ----------

@app.get("/api/luts/look01.cube")
def lut_download(points: int = 65):
    """Export the Look 01 LUT for Premiere, DaVinci, CapCut... (expects S-Log3 / S-Gamut3.Cine input)."""
    from .render import find_lut
    lut = find_lut()
    if lut is None:
        raise HTTPException(404, "The Look 01 LUT isn't installed in app\\luts")
    if points == 33:
        small = lut.with_name(lut.name.replace("_65", "_33"))
        lut = small if small.exists() else lut
    return FileResponse(lut, media_type="text/plain", filename=lut.name)


@app.get("/api/jobs/{job_id}/looks_log")
def looks_log(job_id: str):
    """Rough check whether the footage looks like flat log footage (S-Log3) before applying Look 01."""
    d = _get_dir(job_id)
    meta = jobs.read_meta(job_id)
    if "looks_log" not in meta:
        import numpy as np
        import subprocess as sp

        from .config import find_tool
        raw = sp.run([find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-i", str(d / meta["source"]),
                      "-vf", "fps=1,scale=64:-2,format=gray", "-frames:v", "8", "-f", "rawvideo", "pipe:1"],
                     capture_output=True, creationflags=getattr(sp, "CREATE_NO_WINDOW", 0)).stdout
        y = np.frombuffer(raw, np.uint8).astype(float) / 255
        lo, hi = (np.percentile(y, 2), np.percentile(y, 98)) if y.size else (0, 1)
        meta = jobs.update_meta(job_id, looks_log=bool(lo > 0.08 and hi < 0.85 and hi - lo < 0.7))
    return {"looks_log": meta["looks_log"]}


@app.post("/api/jobs/{job_id}/coach")
def coach(job_id: str):
    """Growth Starter practice plan: 3 notes on energy, pace and the first 3 seconds of this take."""
    _need_plan(job_id)
    from . import grow
    try:
        notes = grow.coach(jobs.load_transcript(job_id), jobs.load_plan(job_id))
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc))
    history = jobs.load_chat(job_id) + [{"role": "assistant", "text": notes, "summary": "notes on this take"}]
    jobs._save_chat(job_id, history)
    return {"notes": notes, "metrics": grow.take_metrics(jobs.load_transcript(job_id), jobs.load_plan(job_id)),
            "chat": history}


# ---------- beat-synced montage (clips + song) ----------

def _mont(mid: str):
    from . import montage
    try:
        return montage, montage.mdir(mid)
    except KeyError:
        raise HTTPException(404, "No such montage")


@app.get("/api/montages")
def montages_list():
    from . import montage
    return montage.list_all()


class MontageNew(BaseModel):
    name: str = "Montage"


@app.post("/api/montages")
def montage_new(body: MontageNew):
    from . import montage
    montage.MONTAGES_DIR.mkdir(parents=True, exist_ok=True)
    return montage.create(body.name)


@app.get("/api/montages/{mid}")
def montage_get(mid: str):
    m, d = _mont(mid)
    return {"meta": m.read_meta(mid), "plan": m.load_plan(mid)}


@app.post("/api/montages/{mid}/clips")
def montage_clip(mid: str, file: UploadFile = File(...)):
    m, d = _mont(mid)
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in VIDEO_TYPES:
        raise HTTPException(400, f"Unsupported file type '{ext}'")
    tmp = d / f"upload_{os.urandom(4).hex()}{ext}"
    _save_upload(file, tmp)
    try:
        return m.add_clip(mid, tmp, file.filename or "clip")
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, f"Couldn't read that clip: {exc}")


@app.delete("/api/montages/{mid}/clips/{name}")
def montage_clip_delete(mid: str, name: str):
    m, d = _mont(mid)
    return m.remove_clip(mid, name)


@app.post("/api/montages/{mid}/song")
def montage_song(mid: str, file: UploadFile = File(...)):
    m, d = _mont(mid)
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in AUDIO_TYPES and ext not in VIDEO_TYPES:
        raise HTTPException(400, f"Unsupported file type '{ext}'")
    tmp = d / f"upload_song{ext}"
    _save_upload(file, tmp)
    try:
        return m.set_song(mid, tmp, file.filename or "song")
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, f"Couldn't analyse that song: {exc}")


class MontagePlan(BaseModel):
    length: float | None = None
    grade: str | None = None


@app.post("/api/montages/{mid}/plan")
def montage_plan(mid: str, body: MontagePlan):
    m, d = _mont(mid)
    try:
        plan = m.make_plan(mid, body.length, body.grade)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"meta": m.read_meta(mid), "plan": plan}


@app.post("/api/montages/{mid}/render")
def montage_render(mid: str, draft: bool = False):
    m, d = _mont(mid)
    meta = m.read_meta(mid)
    if meta.get("status") in ("render queued", "rendering"):
        raise HTTPException(409, "Already rendering")
    if not meta.get("song") or not meta.get("clips"):
        raise HTTPException(400, "Add clips and a song first")
    return m.enqueue(mid, draft)


@app.get("/api/montages/{mid}/file/{name}")
def montage_file(mid: str, name: str, download: bool = False):
    m, d = _mont(mid)
    meta = m.read_meta(mid)
    allowed = {v["file"] for v in meta.get("versions", [])} | {v["sheet"] for v in meta.get("versions", [])}
    allowed |= {c["file"] for c in meta.get("clips", [])}
    if name not in allowed or not (d / name).exists():
        raise HTTPException(404, "No such file")
    media = "image/jpeg" if name.endswith(".jpg") else VIDEO_TYPES.get(os.path.splitext(name)[1], "video/mp4")
    return FileResponse(d / name, media_type=media, filename=name if download else None)


@app.delete("/api/montages/{mid}")
def montage_delete(mid: str):
    m, d = _mont(mid)
    if m.read_meta(mid).get("status") in ("rendering",):
        raise HTTPException(409, "Wait for the render to finish")
    shutil.rmtree(d)
    return {"deleted": mid}


# ---------- grow: starter kit, scripts (Growth Starter + Viral Script) ----------

@app.get("/api/grow")
def grow_list():
    from . import grow
    return {"files": grow.list_files(), "has_style": grow.latest("style") is not None}


@app.get("/api/grow/file/{name}")
def grow_file(name: str, download: bool = False):
    from . import grow
    try:
        text = grow.read_file(name)
    except KeyError:
        raise HTTPException(404, "No such file")
    headers = {"Content-Disposition": f'attachment; filename="{name}"'} if download else {}
    return PlainTextResponse(text, media_type="text/markdown", headers=headers)


IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


@app.post("/api/grow/starter")
def grow_starter(about: str = Form(""), topics: str = Form(""), audience: str = Form(""), language: str = Form(""),
                 face: str = Form(""), goal: str = Form(""), proof: str = Form(""), profile: str = Form(""),
                 research: str = Form(""), images: list[UploadFile] | None = File(None)):
    from . import grow
    pics = []
    for f in (images or [])[:4]:
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext in IMAGE_TYPES:
            data = f.file.read(6 * 1024 * 1024)
            pics.append((IMAGE_TYPES[ext], data))
    answers = dict(about=about, topics=topics, audience=audience, language=language, face=face, goal=goal,
                   proof=proof, profile=profile, research=research)
    if not (about.strip() or topics.strip()):
        raise HTTPException(400, "Tell it at least who you are and the topics you're thinking about")
    try:
        name, md = grow.starter_kit({k: v[:4000] for k, v in answers.items()}, pics)
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc))
    return {"name": name, "markdown": md}


@app.post("/api/grow/reference")
def grow_reference(file: UploadFile = File(...), language: str = Form("auto")):
    """Transcribe a screen recording of a reference reel (times included) for the script writer."""
    import tempfile

    from . import grow
    from .transcribe import transcribe
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in VIDEO_TYPES and ext not in AUDIO_TYPES:
        raise HTTPException(400, f"Unsupported file type '{ext}'")
    if language not in LANGUAGES:
        language = "auto"
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "ref" + ext)
        with open(p, "wb") as out:
            shutil.copyfileobj(file.file, out, length=1024 * 1024)
        try:
            tr = transcribe(p, language)
        except Exception as exc:
            raise HTTPException(500, f"Couldn't transcribe it: {exc}")
    return {"transcript": grow.transcript_with_times(tr), "language": tr.get("language"),
            "duration": tr.get("duration")}


class ScriptRequest(BaseModel):
    topic: str = ""
    audience: str = ""
    language: str = ""
    voice: str = ""
    cta: str = ""
    reference: str = ""
    notes: str = ""


@app.post("/api/grow/script")
def grow_script(body: ScriptRequest):
    from . import grow
    if not (body.reference.strip() or body.notes.strip()):
        raise HTTPException(400, "Add a reference reel: upload a screen recording or paste its words")
    try:
        name, md, style = grow.script({k: v[:6000] for k, v in body.model_dump().items()})
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc))
    return {"name": name, "markdown": md, "style": style}


# ---------- more marketplace skills: captions, post kit, shorts, exports ----------

@app.post("/api/jobs/{job_id}/fixwords")
def fix_words(job_id: str):
    """subtitle-correction: AI fixes misheard words in the transcript (timings unchanged)."""
    d = _need_plan(job_id)
    from . import extras
    transcript = jobs.load_transcript(job_id)
    try:
        fixes = extras.fix_words(transcript)
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc))
    if fixes:
        transcript = extras.apply_fixes(d, transcript, fixes)
    text = (f"Fixed {len(fixes)} misheard word{'s' if len(fixes) != 1 else ''}: "
            + "; ".join(f'{f["old"]} → {f["text"]}' for f in fixes[:12]) + ("…" if len(fixes) > 12 else "")
            + ". Words with a dotted blue underline were changed; “Restore original words” undoes it.") if fixes \
        else "No clear recognition mistakes found."
    history = jobs.load_chat(job_id) + [{"role": "assistant", "text": text, "summary": "caption fixes"}]
    jobs._save_chat(job_id, history)
    plan = jobs.load_plan(job_id)
    return {"fixes": fixes, "transcript": transcript, "chat": history, "plan": plan, **_extras(job_id, plan)}


@app.post("/api/jobs/{job_id}/restorewords")
def restore_words(job_id: str):
    d = _need_plan(job_id)
    from . import extras
    transcript = extras.restore_words(d)
    if transcript is None:
        raise HTTPException(409, "Nothing to restore")
    plan = jobs.load_plan(job_id)
    return {"transcript": transcript, "plan": plan, **_extras(job_id, plan)}


class TranslateRequest(BaseModel):
    lang: str
    dual: bool = False


@app.post("/api/jobs/{job_id}/translate")
def translate(job_id: str, body: TranslateRequest):
    """subtitle-generation: translated (or dual-language) captions."""
    d = _need_plan(job_id)
    from . import extras
    from .captions import caption_lines
    from .config import load_config
    if body.lang and body.lang not in extras.LANG_NAMES:
        raise HTTPException(400, "Unknown language")
    count = 0
    if body.lang:
        plan = jobs.load_plan(job_id)
        ccfg = {**load_config()["captions"], **(plan.get("captions") or {})}
        lines = caption_lines(jobs.load_transcript(job_id), plan, ccfg)
        try:
            count = len(extras.translate_lines(d, [ln["text"] for ln in lines], body.lang))
        except llm.LLMError as exc:
            raise HTTPException(502, str(exc))
    plan = jobs.update_plan(job_id, None, None, None, {"caption_lang": body.lang, "caption_dual": body.dual})
    return {"plan": plan, "translated": count, "undo": jobs.history_size(job_id), **_extras(job_id, plan)}


@app.get("/api/jobs/{job_id}/subtitles.{fmt}")
def subtitle_file(job_id: str, fmt: str):
    """subtitle-packager: SRT / VTT / ASS of the edited video's captions."""
    d = _need_plan(job_id)
    from . import extras
    from .captions import caption_lines, write_ass
    from .config import load_config
    from .render import out_size
    if fmt not in ("srt", "vtt", "ass"):
        raise HTTPException(404, "Use .srt, .vtt or .ass")
    plan = jobs.load_plan(job_id)
    st = stylelib.effective(plan)
    ccfg = {**load_config()["captions"], **(plan.get("captions") or {})}
    lines = caption_lines(jobs.load_transcript(job_id), plan, ccfg)
    tr = extras.cached_translations(d, st.get("caption_lang") or "")
    name = os.path.splitext(jobs.read_meta(job_id).get("name", "video"))[0] + "." + fmt
    if fmt == "ass":
        meta = jobs.read_meta(job_id)
        size = out_size(meta.get("width") or 1080, meta.get("height") or 1920, False, reel=st.get("format") == "reel")
        p = d / "export.ass"
        write_ass(lines, size, ccfg, p, style=st, captions_on=True, duration=plan.get("edited_duration"),
                  translations=tr)
        text = p.read_text(encoding="utf-8-sig")
    else:
        text = extras.subtitles(lines, fmt, float(st.get("speed", 1.0) or 1.0), tr, bool(st.get("caption_dual")))
    return PlainTextResponse(text, media_type="text/plain; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/jobs/{job_id}/postkit")
def postkit(job_id: str):
    """caption-writer + content-repurposer: captions, titles, chapters, hashtags, thumbnail text."""
    d = _need_plan(job_id)
    from . import extras
    plan = jobs.load_plan(job_id)
    try:
        md = extras.post_kit(jobs.load_transcript(job_id), plan, stylelib.effective(plan),
                             jobs.read_meta(job_id).get("name", "video"))
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc))
    (d / "postkit.md").write_text(md, encoding="utf-8")
    return {"markdown": md}


@app.get("/api/jobs/{job_id}/postkit.md")
def postkit_file(job_id: str):
    d = _get_dir(job_id)
    if not (d / "postkit.md").exists():
        raise HTTPException(404, "No post kit yet")
    return PlainTextResponse((d / "postkit.md").read_text(encoding="utf-8"), media_type="text/markdown")


@app.post("/api/jobs/{job_id}/shorts")
def shorts(job_id: str):
    """byted-las-video-edit: find 2-3 highlight clips and add each as a new video."""
    _need_plan(job_id)
    from . import extras
    try:
        clips = extras.find_shorts(jobs.load_transcript(job_id), jobs.load_plan(job_id))
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc))
    for c in clips:
        c["job"] = jobs.create_short(job_id, c)
    return {"clips": clips}


class ExportRequest(BaseModel):
    text: str = ""
    at: float | None = None


@app.post("/api/jobs/{job_id}/export/{kind}")
def export_video(job_id: str, kind: str, body: ExportRequest):
    """video-edit (ffmpeg): export presets of the rendered video."""
    d = _get_dir(job_id)
    from . import extras
    if kind not in extras.EXPORTS:
        raise HTTPException(404, "Unknown export")
    src = d / "output.mp4"
    if not src.exists():
        raise HTTPException(409, "Render the final video first")
    st = stylelib.effective(jobs.load_plan(job_id))
    from .config import load_config
    try:
        out = extras.export(d, src, kind, body.text or st.get("title", ""), body.at, st.get("accent", "#FFD23F"),
                            load_config()["captions"].get("font", "Nirmala UI"))
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)[-600:])
    return {"name": out.name, "size": out.stat().st_size}


@app.get("/api/jobs/{job_id}/exports/{name}")
def export_file(job_id: str, name: str, download: bool = False):
    d = _get_dir(job_id)
    from . import extras
    p = d / "exports" / name
    if not extras.safe_export_name(name) or not p.exists():
        raise HTTPException(404, "No such export")
    media = {".mp4": "video/mp4", ".mp3": "audio/mpeg", ".jpg": "image/jpeg", ".png": "image/png"}[os.path.splitext(name)[1]]
    stem = os.path.splitext(jobs.read_meta(job_id).get("name", "video"))[0]
    return FileResponse(p, media_type=media, filename=f"{stem}_{name}" if download else None)


# ---------- marketplace page 2: b-roll library, carousel, render review ----------

@app.get("/api/jobs/{job_id}/library")
def library_list(job_id: str):
    d = _get_dir(job_id)
    from . import extras2
    return extras2.library(d)


@app.post("/api/jobs/{job_id}/library")
def library_add(job_id: str, file: UploadFile = File(...)):
    """broll-match-engine: add one of the creator's own clips to this video's b-roll library."""
    d = _need_plan(job_id)
    from . import extras2
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in VIDEO_TYPES:
        raise HTTPException(400, f"Unsupported file type '{ext}'")
    tmp = d / f"upload_lib{ext}"
    _save_upload(file, tmp)
    try:
        return extras2.add_to_library(d, tmp, file.filename or "clip", llm.configured())
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, f"Couldn't read that clip: {exc}")


@app.delete("/api/jobs/{job_id}/library/{name}")
def library_remove(job_id: str, name: str):
    d = _need_plan(job_id)
    from . import extras2
    if any(b.get("clip") == name for b in jobs.load_plan(job_id).get("broll") or []):
        raise HTTPException(409, "That clip is placed on a b-roll moment; replace or remove the moment first")
    extras2.remove_from_library(d, name)
    return extras2.library(d)


@app.get("/api/jobs/{job_id}/library/file/{name}")
def library_file(job_id: str, name: str):
    d = _get_dir(job_id)
    from . import extras2
    allowed = {i["file"] for i in extras2.library(d)} | {i["thumb"] for i in extras2.library(d)}
    if name not in allowed or not (d / name).exists():
        raise HTTPException(404, "No such file")
    media = "image/jpeg" if name.endswith(".jpg") else VIDEO_TYPES.get(os.path.splitext(name)[1], "video/mp4")
    return FileResponse(d / name, media_type=media)


@app.post("/api/jobs/{job_id}/broll/match")
def broll_match(job_id: str):
    """broll-match-engine: put the best library clip on each planned b-roll moment."""
    d = _need_plan(job_id)
    from . import extras2
    try:
        matches = extras2.match_library(d, jobs.load_transcript(job_id), jobs.load_plan(job_id))
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc))
    plan = jobs.load_plan(job_id)
    for m in matches:
        plan = jobs.update_broll(job_id, m["moment"], clip={"clip": m["clip"], "clip_duration": m["duration"],
                                                            "clip_has_audio": m["has_audio"]})
    return {"matches": matches, "plan": plan, "undo": jobs.history_size(job_id), **_extras(job_id, plan)}


@app.post("/api/jobs/{job_id}/carousel")
def make_carousel(job_id: str):
    """social-carousel: 5-7 slide images of the video's key points."""
    d = _need_plan(job_id)
    from . import extras2
    from .config import load_config
    plan = jobs.load_plan(job_id)
    src = d / "output.mp4" if (d / "output.mp4").exists() else d / jobs.read_meta(job_id)["source"]
    try:
        names = extras2.carousel(d, src, jobs.load_transcript(job_id), plan, stylelib.effective(plan),
                                 load_config()["captions"].get("font", "Nirmala UI"))
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(500, str(exc)[-400:])
    return {"slides": names}


@app.post("/api/jobs/{job_id}/review")
def review_render(job_id: str):
    """video-understand / ffmpeg-analyse-video: AI vision checks frames of the latest render."""
    d = _need_plan(job_id)
    from . import extras2
    meta = jobs.read_meta(job_id)
    final, draft = d / "output.mp4", d / "draft.mp4"
    cands = [(meta.get("rendered") or 0, final), (meta.get("draft_rendered") or 0, draft)]
    cands = [(t, p) for t, p in cands if p.exists()]
    if not cands:
        raise HTTPException(409, "Render a draft or the final video first")
    src = max(cands)[1]
    plan = jobs.load_plan(job_id)
    try:
        md = extras2.review(src, jobs.load_transcript(job_id), plan, float(stylelib.effective(plan).get("speed", 1) or 1))
    except llm.LLMError as exc:
        raise HTTPException(502, f"{exc} (this needs a model that can read images, e.g. gpt-4.1-mini)")
    history = jobs.load_chat(job_id) + [{"role": "assistant", "text": f"Review of the {'final' if src == final else 'draft'}:\n{md}",
                                        "summary": "render review"}]
    jobs._save_chat(job_id, history)
    return {"markdown": md, "chat": history}


def main() -> None:
    import uvicorn

    host = os.environ.get("EDITOR_HOST", "127.0.0.1")
    port = int(os.environ.get("EDITOR_PORT", "8000"))
    if os.environ.get("EDITOR_NO_BROWSER") != "1":
        threading.Timer(1.5, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
