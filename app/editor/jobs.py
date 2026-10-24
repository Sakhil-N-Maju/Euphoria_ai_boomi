"""Jobs: one folder per uploaded video, processed one at a time by a background worker.

data/jobs/<id>/
    meta.json        status, progress, name, language
    input.<ext>      the uploaded video
    transcript.json  words with timestamps
    edit.yaml        the edit plan (video as code)
    history/         earlier versions of edit.yaml, for undo
    chat.json        the chat-edit conversation
    captions.ass     captions + title on the edited timeline (written at render time)
    music.<ext>      optional music bed (uploaded)
    broll_<id>.<ext> optional b-roll clips (uploaded)
    bed.wav          music + synthesised sound effects (written at render time)
    draft.mp4        fast low-resolution draft
    output.mp4       the finished video
"""
from __future__ import annotations

import json
import queue
import threading
import time
import traceback
import uuid
from pathlib import Path

from . import aiedit, llm
from . import broll as brolllib
from . import plan as planlib
from . import style as stylelib
from .config import JOBS_DIR, load_config
from .media import probe
from .render import render
from .timeline import describe
from .transcribe import transcribe

_lock = threading.Lock()
_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
_worker: threading.Thread | None = None
_plan_lock = threading.RLock()     # one plan change at a time (review page, chat and retakes can overlap)
MAX_HISTORY = 50


def job_dir(job_id: str) -> Path:
    if not job_id.isalnum():
        raise KeyError(job_id)
    d = JOBS_DIR / job_id
    if not d.is_dir():
        raise KeyError(job_id)
    return d


def read_meta(job_id: str) -> dict:
    with _lock:
        return json.loads((job_dir(job_id) / "meta.json").read_text(encoding="utf-8"))


def update_meta(job_id: str, **changes) -> dict:
    with _lock:
        path = JOBS_DIR / job_id / "meta.json"
        meta = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        meta.update(changes)
        meta["updated"] = time.time()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return meta


def list_jobs() -> list[dict]:
    if not JOBS_DIR.exists():
        return []
    out = []
    for d in JOBS_DIR.iterdir():
        if (d / "meta.json").exists():
            try:
                out.append(read_meta(d.name))
            except (OSError, json.JSONDecodeError, KeyError):
                pass
    return sorted(out, key=lambda m: m.get("created", 0), reverse=True)


def create_job(filename: str, language: str) -> tuple[str, Path]:
    job_id = uuid.uuid4().hex[:12]
    d = JOBS_DIR / job_id
    d.mkdir(parents=True)
    ext = Path(filename).suffix.lower() or ".mp4"
    if not ext[1:].isalnum() or len(ext) > 6:
        ext = ".mp4"
    update_meta(job_id, id=job_id, name=Path(filename).name, created=time.time(), language=language,
                source=f"input{ext}", status="uploading", progress=0.0, error=None)
    return job_id, d / f"input{ext}"


def enqueue(job_id: str, action: str) -> None:
    status = {"analyze": "queued", "render": "render queued", "draft": "render queued"}[action]
    extra = {"render_kind": action} if action in ("render", "draft") else {}
    update_meta(job_id, status=status, progress=0.0, error=None, **extra)
    _queue.put((job_id, action))
    _ensure_worker()


def _ensure_worker() -> None:
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_work_loop, name="editor-worker", daemon=True)
        _worker.start()


def _work_loop() -> None:
    while True:
        job_id, action = _queue.get()
        try:
            if action == "analyze":
                analyze(job_id)
            elif action in ("render", "draft"):
                render_job(job_id, draft=action == "draft")
        except Exception as exc:  # report every failure on the job instead of killing the worker
            traceback.print_exc()
            update_meta(job_id, status="error", error=str(exc))
        finally:
            _queue.task_done()


def default_settings() -> dict:
    return dict(load_config()["edit"])


def analyze(job_id: str) -> None:
    d = job_dir(job_id)
    meta = read_meta(job_id)
    source = d / meta["source"]
    info = probe(source)
    update_meta(job_id, status="transcribing", progress=0.0, duration=info.duration,
                width=info.width, height=info.height)

    last = [0.0]

    def progress(p: float) -> None:
        if p - last[0] >= 0.01:
            last[0] = p
            update_meta(job_id, progress=round(p, 3))

    transcript = transcribe(source, meta.get("language", "auto"), on_progress=progress)
    if not transcript["duration"]:
        transcript["duration"] = info.duration
    (d / "transcript.json").write_text(json.dumps(transcript, ensure_ascii=False, indent=1), encoding="utf-8")

    cfg = load_config()
    plan = planlib.build_plan(transcript, default_settings(), cfg.get("fillers", []),
                              captions={"enabled": cfg["captions"].get("enabled", True)}, source=meta["source"])
    planlib.save_plan(plan, d / "edit.yaml")
    update_meta(job_id, stt_model=transcript.get("model"), stt_note=transcript.get("note"))

    if cfg.get("llm", {}).get("auto_retakes", True) and llm.configured() and transcript["words"]:
        update_meta(job_id, status="finding retakes", progress=0.0)
        try:
            apply_retakes(job_id, snapshot=False)
            update_meta(job_id, retakes_error=None)
        except Exception as exc:   # AI problems must never block the plain edit
            update_meta(job_id, retakes_error=str(exc))
    update_meta(job_id, status="ready", progress=1.0, detected_language=transcript["language"],
                word_count=len(transcript["words"]))


def load_transcript(job_id: str) -> dict:
    return json.loads((job_dir(job_id) / "transcript.json").read_text(encoding="utf-8"))


def load_plan(job_id: str) -> dict:
    return planlib.load_plan(job_dir(job_id) / "edit.yaml")


def rebuild_plan(job_id: str, removed_words: list[int] | set[int] | None = None, settings: dict | None = None,
                 captions: dict | None = None, retakes: list[dict] | None = None, save: bool = True,
                 snapshot: bool = True, style: dict | None = None, broll: list[dict] | None = None) -> dict:
    """Rebuild the plan from the current one plus changes, and (by default) save it with an undo snapshot."""
    with _plan_lock:
        transcript = load_transcript(job_id)
        current = load_plan(job_id)
        merged_settings = {**default_settings(), **current.get("settings", {}), **(settings or {})}
        merged_captions = {**current.get("captions", {}), **(captions or {})}
        n = len(transcript["words"])
        merged_style = {**stylelib.clean_style(current.get("style") or {}, n),
                        **stylelib.clean_style(style or {}, n)}
        if removed_words is None:
            removed_words = current.get("removed_words", [])
        if retakes is None:
            retakes = current.get("retakes", [])
        if broll is None:
            broll = current.get("broll") or []
        plan = planlib.build_plan(transcript, merged_settings, load_config().get("fillers", []),
                                  removed_words=sorted(removed_words), captions=merged_captions,
                                  source=current.get("source", ""), retakes=retakes, style=merged_style,
                                  broll=broll)
        if save:
            if snapshot:
                push_history(job_id)
            planlib.save_plan(plan, job_dir(job_id) / "edit.yaml")
        return plan


def update_plan(job_id: str, removed_words: list[int] | None, settings: dict | None,
                captions: dict | None, style: dict | None = None) -> dict:
    """Rebuild the plan from the review page's choices and save it."""
    return rebuild_plan(job_id, removed_words, settings, captions, style=style)


def timeline(job_id: str, plan: dict | None = None) -> dict:
    """Edited-timeline facts for the review page: transitions, b-roll slots, sound map (no per-word list)."""
    plan = plan or load_plan(job_id)
    tl = describe(load_transcript(job_id), plan, load_config(), stylelib.effective(plan))
    tl.pop("words", None)
    return tl


# ---------- finishing: auto-style, b-roll ----------

def autostyle(job_id: str) -> tuple[dict, str]:
    """Pick a title, keywords and topic breaks (AI if configured, otherwise simple rules) and switch on the
    HyperFrames finishing: animated title, word-synced captions with keyword pops, transitions at topic changes."""
    transcript = load_transcript(job_id)
    current = load_plan(job_id)
    removed = set(current.get("removed_words", []))
    picked: dict = {}
    how = "rules"
    if llm.configured():
        try:
            picked = stylelib.ai_style(transcript, current)
            how = "AI"
        except llm.LLMError:
            picked = {}
    if not picked.get("keywords"):
        picked["keywords"] = stylelib.auto_keywords(transcript["words"], removed)
    if not picked.get("topic_breaks"):
        picked["topic_breaks"] = stylelib.auto_topic_breaks(transcript["words"], removed,
                                                             float(current.get("edited_duration", 0)))
    changes = {"caption_style": "highlight", "keyword_pop": True, "transitions": True, **picked}
    if picked.get("title"):
        changes["title_enabled"] = True
    plan = rebuild_plan(job_id, style=changes)
    return plan, how


def create_short(job_id: str, clip: dict) -> str:
    """byted-las-video-edit skill: a highlight clip of this video becomes its own video in the list."""
    import os
    import shutil
    src_dir = job_dir(job_id)
    meta = read_meta(job_id)
    current = load_plan(job_id)
    new_id = uuid.uuid4().hex[:12]
    d = JOBS_DIR / new_id
    d.mkdir(parents=True)
    src = src_dir / meta["source"]
    try:
        os.link(src, d / meta["source"])          # same file on disk, no copy
    except OSError:
        shutil.copyfile(src, d / meta["source"])
    shutil.copyfile(src_dir / "transcript.json", d / "transcript.json")
    transcript = load_transcript(job_id)
    n = len(transcript["words"])
    a, b = int(clip["from"]), int(clip["to"])
    removed = (set(current.get("removed_words", [])) & set(range(a, b + 1))) | (set(range(n)) - set(range(a, b + 1)))
    st = dict(current.get("style") or {})
    for key in ("keywords", "topic_breaks"):
        st[key] = [i for i in st.get(key, []) if a <= i <= b]
    if clip.get("title"):
        st["title"] = clip["title"]
    plan = planlib.build_plan(transcript, {**default_settings(), **current.get("settings", {})},
                              load_config().get("fillers", []), removed_words=sorted(removed),
                              captions=current.get("captions"), source=meta["source"], style=st)
    planlib.save_plan(plan, d / "edit.yaml")
    keep = {k: meta.get(k) for k in ("language", "detected_language", "stt_model", "width", "height", "duration")}
    update_meta(new_id, id=new_id, name=f'{Path(meta.get("name", "video")).stem} - {clip.get("title", "short")}.mp4',
                created=time.time(), source=meta["source"], status="ready", progress=1.0, error=None,
                word_count=n, parent=job_id, **keep)
    return new_id


def plan_broll(job_id: str) -> tuple[dict, int]:
    transcript = load_transcript(job_id)
    current = load_plan(job_id)
    items, _ = brolllib.plan_broll(transcript, current, stylelib.effective(current).get("look", "clean"))
    merged = brolllib.merge(current.get("broll") or [], items)
    return rebuild_plan(job_id, broll=merged), len(items)


def update_broll(job_id: str, broll_id: str, changes: dict | None = None, delete: bool = False,
                 clip: dict | None = None) -> dict:
    """Change one b-roll moment: fields from the review page, a newly uploaded clip, or remove it."""
    with _plan_lock:
        current = load_plan(job_id)
        items = [dict(b) for b in current.get("broll") or []]
        item = next((b for b in items if b["id"] == broll_id), None)
        if item is None:
            raise KeyError(broll_id)
        old_clip = item.get("clip")
        if delete:
            items = [b for b in items if b["id"] != broll_id]
        else:
            item.update(brolllib.clean_item_update(changes or {}))
            if clip is not None:
                item.update(clip)
        plan = rebuild_plan(job_id, broll=items)
        still_used = {b.get("clip") for b in items}
        if old_clip and old_clip not in still_used and old_clip.startswith("broll_"):   # library clips stay
            (job_dir(job_id) / old_clip).unlink(missing_ok=True)
        return plan


# ---------- undo ----------

def _history_dir(job_id: str) -> Path:
    return job_dir(job_id) / "history"


def push_history(job_id: str) -> None:
    src = job_dir(job_id) / "edit.yaml"
    if not src.exists():
        return
    h = _history_dir(job_id)
    h.mkdir(exist_ok=True)
    existing = sorted(h.glob("*.yaml"))
    current = src.read_text(encoding="utf-8")
    if existing and existing[-1].read_text(encoding="utf-8") == current:
        return
    n = int(existing[-1].stem) + 1 if existing else 1
    (h / f"{n:05d}.yaml").write_text(current, encoding="utf-8")
    for old in existing[:max(0, len(existing) + 1 - MAX_HISTORY)]:
        old.unlink()


def history_size(job_id: str) -> int:
    h = _history_dir(job_id)
    return len(list(h.glob("*.yaml"))) if h.exists() else 0


def undo(job_id: str) -> dict:
    with _plan_lock:
        h = _history_dir(job_id)
        snaps = sorted(h.glob("*.yaml")) if h.exists() else []
        if not snaps:
            raise ValueError("Nothing to undo")
        last = snaps[-1]
        (job_dir(job_id) / "edit.yaml").write_text(last.read_text(encoding="utf-8"), encoding="utf-8")
        last.unlink()
        return load_plan(job_id)


# ---------- AI edits ----------

def apply_retakes(job_id: str, snapshot: bool = True) -> tuple[dict, list[dict]]:
    """Ask the AI for retakes, cut them, and save. Returns (plan, newly found retakes)."""
    transcript = load_transcript(job_id)
    found = aiedit.find_retakes(transcript)
    with _plan_lock:
        current = load_plan(job_id)
        old_ids = set(current.get("retake_words", []))
        new_ids = {i for r in found for i in range(r["remove_from"], r["remove_to"] + 1)}
        # Words that were retakes before but aren't now go back in; new retake words are cut.
        removed = (set(current.get("removed_words", [])) - (old_ids - new_ids)) | new_ids
        plan = rebuild_plan(job_id, removed, retakes=found, snapshot=snapshot)
    return plan, found


def load_chat(job_id: str) -> list[dict]:
    p = job_dir(job_id) / "chat.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def _save_chat(job_id: str, chat: list[dict]) -> None:
    (job_dir(job_id) / "chat.json").write_text(json.dumps(chat[-100:], ensure_ascii=False, indent=1), encoding="utf-8")


def chat(job_id: str, message: str) -> dict:
    transcript = load_transcript(job_id)
    with _plan_lock:
        current = load_plan(job_id)
        history = load_chat(job_id)

        def rebuild(removed, settings, captions, style=None):
            return rebuild_plan(job_id, removed, settings, captions, save=False, style=style)

        plan, reply, notes = aiedit.chat_edit(transcript, current, message, history, rebuild)
        changed = (plan["removed_words"] != current["removed_words"] or plan["settings"] != current["settings"]
                   or plan.get("captions") != current.get("captions")
                   or (plan.get("style") or {}) != (current.get("style") or {}))
        if changed:
            push_history(job_id)
            planlib.save_plan(plan, job_dir(job_id) / "edit.yaml")
        summary = aiedit.summarize(current, plan) if changed else "no changes"
        now = time.time()
        history += [{"role": "user", "text": message, "time": now},
                    {"role": "assistant", "text": reply, "time": now, "summary": summary, "notes": notes}]
        _save_chat(job_id, history)
    return {"plan": plan, "reply": reply, "summary": summary, "notes": notes, "chat": history}


def render_job(job_id: str, draft: bool = False) -> None:
    d = job_dir(job_id)
    meta = read_meta(job_id)
    update_meta(job_id, status="rendering", progress=0.0, render_kind="draft" if draft else "render")
    last = [0.0]

    def progress(p: float) -> None:
        if p - last[0] >= 0.01:
            last[0] = p
            update_meta(job_id, progress=round(p, 3))

    out = d / ("draft.mp4" if draft else "output.mp4")
    render(d, d / meta["source"], load_transcript(job_id), load_plan(job_id), out, on_progress=progress, draft=draft)
    if draft:
        update_meta(job_id, status="done", progress=1.0, draft_rendered=time.time())
    else:
        update_meta(job_id, status="done", progress=1.0, rendered=time.time())


def resume_interrupted() -> None:
    """On startup, re-queue jobs that were mid-way when the app was closed."""
    for meta in list_jobs():
        status = meta.get("status")
        if status in ("queued", "transcribing", "uploading"):
            if status == "uploading":
                update_meta(meta["id"], status="error", error="Upload was interrupted. Please upload again.")
            else:
                enqueue(meta["id"], "analyze")
        elif status in ("render queued", "rendering"):
            enqueue(meta["id"], "draft" if meta.get("render_kind") == "draft" else "render")
        elif status == "finding retakes":
            update_meta(meta["id"], status="ready", progress=1.0)
