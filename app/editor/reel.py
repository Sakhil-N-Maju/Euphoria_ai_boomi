"""Claude-edited reels (creator-reel skill, token-lean).

A creator uploads a raw talking-head video on the website (/site → Studio). For every video:
  1. Capture (no AI): normalise, Whisper word timings, background, fonts.
  2. Plan: ONE call to Claude Code on this PC (`claude -p`, signed in with the team's own Claude account) with no
     tools, a short system prompt (reel_agent/creator-reel/prompts/plan_rules.md) and a JSON schema. Claude sees only
     the transcript and answers with a small edit plan that names word indexes.
  3. Build + render (no AI): build_plan.py turns the plan into cuts, captions, layouts, graphics, zooms and sound;
     the reel-editor engine renders out/reel.mp4.
The Setup panel on the website installs Claude Code, signs in and installs the render tools, so nothing needs a terminal.

Styles (reel_agent/styles/, picked in the Studio): talking_head (above), product (a screen recording: activity map ->
one plan call -> product_build.py) and faceless (a topic or script, optional voice-over/music: the AI can write the
script; the engine animates it on a generated background).
Corrections: "Fix words" and "Ask for a change" (optionally limited to a time range of the finished reel) change only
what they name; the render cache (ovcache/, vcache/, stable.json) re-renders only the frames that changed.

data/reels/<id>/  meta.json · raw.<ext> · words.json · edit_plan.json · ... · out/reel.mp4 · out/reel-master.mp4
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from . import tts
from .config import APP_DIR, DATA_DIR, WEB_DIR, find_tool

REELS_DIR = DATA_DIR / "reels"
TOOLS_DIR = DATA_DIR / "reel_tools"
SKILL_DIR = APP_DIR / "reel_agent" / "creator-reel"
SCRIPTS = SKILL_DIR / "scripts"
PROMPTS = SKILL_DIR / "prompts"
PY = sys.executable
WIN = os.name == "nt"
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
LANGS = {"ml": "Malayalam / Manglish", "hi": "Hindi", "en": "English", "ta": "Tamil", "auto": "Detect automatically"}
CAPTION_SCRIPTS = {"english": "English captions (translated from what you say)",
                   "mix_openai": "Native words in native script, English in English (OpenAI, accurate)",
                   "mix": "Native words in native script, English words in English (beta, offline)"}
CUT_MODES = {"gaps": "Only gaps and umms (keep everything I said)", "smart": "Also retakes and repeated lines (AI)"}
PACES = {"tight": "Tight (pauses ~0.1 s)", "natural": "Natural (pauses ~0.25 s)", "loose": "Relaxed (only long pauses)"}
REVISE_SET = {"headline", "back", "cta", "accent", "accent_color", "pace", "cut_fillers", "sfx", "zoom", "punch_ins"}
STYLES_DIR = APP_DIR / "reel_agent" / "styles"
# Edit styles (studied from assets/style/*; see reel_agent/styles/README.md). A reel without "style" in its meta was made
# before styles existed and keeps the original Euphoria look.
STYLES = {"talking_head": "Talking head - you, talking to the camera",
          "product": "Product - a screen recording of your app, website or product",
          "faceless": "No talking head - only a topic or script (we make the video)"}
LOOKS = {"product": ("dark", "light"), "faceless": ("crimson", "midnight", "paper", "violet")}   # devices, story, editorial, presenter
LOOK_ALIASES = {"faceless": {"light": "paper", "dark": "crimson", "ink": "crimson", "devices": "crimson",
                             "story": "midnight", "editorial": "paper", "presenter": "violet"}}
VOICES = {"none": "No voice (text, sound effects and your music)", "upload": "My voice-over (upload)",
          "elevenlabs": "ElevenLabs voice (API key in app/.env)", "windows": "Computer voice (Windows, English)"}
PRODUCT_VOICES = {"recording": "Sound from my recording", "elevenlabs": "AI narration (ElevenLabs)"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus"} | VIDEO_EXT
BUSY = ("queued", "preparing", "editing", "rendering")
LOG_KEEP = 400

router = APIRouter()
_q: "queue.Queue[str]" = queue.Queue()
_lock = threading.Lock()
_procs: dict[str, list[subprocess.Popen]] = {}
_worker: threading.Thread | None = None
_setup = {"tools": {"running": False, "log": [], "error": None}, "claude": {"running": False, "log": []},
          "login": {"running": False, "log": []}}
_cache: dict[str, tuple[float, object]] = {}


# ---------- small helpers ----------

def claude_bin() -> str | None:
    env = os.environ.get("CLAUDE_BIN")
    if env and Path(env).exists():
        return env
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    for p in (home / ".local" / "bin" / ("claude.exe" if WIN else "claude"),
              Path(os.environ.get("APPDATA", home)) / "npm" / "claude.cmd"):
        if p.exists():
            return str(p)
    return None


def tools_ready() -> bool:
    return (TOOLS_DIR / "tools.json").exists()


def cached(key: str, ttl: float, fn):
    now = time.time()
    if key in _cache and now - _cache[key][0] < ttl:
        return _cache[key][1]
    val = fn()
    _cache[key] = (now, val)
    return val


def rdir(rid: str) -> Path:
    if not rid or not all(c.isalnum() or c in "-_" for c in rid):
        raise KeyError(rid)
    d = REELS_DIR / rid
    if not (d / "meta.json").exists():
        raise KeyError(rid)
    return d


def read_meta(rid: str) -> dict:
    return json.loads((REELS_DIR / rid / "meta.json").read_text(encoding="utf-8"))


def write_meta(rid: str, meta: dict) -> None:
    p = REELS_DIR / rid / "meta.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def update(rid: str, **kw) -> dict:
    with _lock:
        m = read_meta(rid)
        m.update(kw)
        write_meta(rid, m)
        return m


def log(rid: str, kind: str, text: str) -> None:
    """kind: app | claude | step | warn"""
    text = (text or "").strip()
    if not text:
        return
    with _lock:
        m = read_meta(rid)
        lines = m.setdefault("log", [])
        lines.append({"t": round(time.time(), 1), "k": kind, "x": text[:1500]})
        m["log_n"] = m.get("log_n", 0) + 1
        if len(lines) > LOG_KEEP:
            del lines[: len(lines) - LOG_KEEP]
        write_meta(rid, m)


def posix(p) -> str:
    return Path(p).as_posix()


def script_env(d: Path, meta: dict) -> dict:
    env = dict(os.environ)
    ff = find_tool("ffmpeg")
    if os.path.dirname(ff):
        env["PATH"] = os.path.dirname(ff) + os.pathsep + env.get("PATH", "")
    env.update({"PY": posix(PY), "S": posix(SCRIPTS), "REEL_HOME": posix(d), "REEL_OUT": posix(d / "out"),
                "EUPHORIA_APP": posix(APP_DIR), "REEL_LANG": meta.get("language", "auto"),
                "HF_HUB_OFFLINE": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    return env


def run_script(rid: str, d: Path, args: list[str], meta: dict, label: str | None = None, quiet=False) -> str:
    if label:
        log(rid, "step", label)
    r = subprocess.run([PY, str(SCRIPTS / args[0]), *args[1:]], cwd=d, env=script_env(d, meta),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        raise RuntimeError(f"{label or args[0]} failed:\n{(r.stderr or r.stdout)[-1500:]}")
    if not quiet:
        for ln in [x for x in (r.stdout or "").splitlines() if x.strip()][-2:]:
            log(rid, "app", ln)
    return r.stdout or ""


def run_parallel(rid: str, d: Path, jobs: list[list[str]], meta: dict) -> None:
    ps = [subprocess.Popen([PY, str(SCRIPTS / a[0]), *a[1:]], cwd=d, env=script_env(d, meta),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                           errors="replace") for a in jobs]
    _procs.setdefault(rid, []).extend(ps)
    outs = [p.communicate()[0] for p in ps]
    for p, o in zip(ps, outs):
        if p.returncode:
            raise RuntimeError(f"Rendering the graphics failed:\n{o[-1500:]}")


# ---------- setup (shown on the website) ----------

def claude_version() -> str | None:
    exe = claude_bin()
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20)
        return (r.stdout or "").strip().split(" ")[0] or None
    except Exception:  # noqa: BLE001
        return None


def claude_auth() -> dict:
    exe = claude_bin()
    if not exe:
        return {"signed_in": False}
    try:
        r = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, timeout=25)
        data = {}
        try:
            data = json.loads(r.stdout or "{}")
        except json.JSONDecodeError:
            pass
        method = data.get("authMethod")
        ok = r.returncode == 0 and method not in (None, "none")
        return {"signed_in": ok, "method": method if ok else None}
    except Exception:  # noqa: BLE001
        return {"signed_in": False}


def setup_status() -> dict:
    exe = claude_bin()
    ver = cached("ver", 30, claude_version) if exe else None
    auth = cached("auth", 8, claude_auth) if exe else {"signed_in": False}
    st = {"claude": {"installed": bool(exe), "version": ver, "running": _setup["claude"]["running"],
                     "log": _setup["claude"]["log"][-6:]},
          "login": {"signed_in": auth.get("signed_in", False), "method": auth.get("method"),
                    "running": _setup["login"]["running"], "log": _setup["login"]["log"][-6:]},
          "tools": {"ready": tools_ready(), "running": _setup["tools"]["running"], "error": _setup["tools"]["error"],
                    "log": _setup["tools"]["log"][-8:]},
          "windows": WIN}
    st["ready"] = st["claude"]["installed"] and st["login"]["signed_in"] and st["tools"]["ready"]
    return st


def _bg(name: str, cmd: list[str], **kw) -> None:
    """Run a setup command in the background, keeping its output for the Setup panel."""
    s = _setup[name]
    if s["running"]:
        return
    s.update(running=True, log=[], error=None)

    def go():
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                 errors="replace", stdin=subprocess.DEVNULL, **kw)
            for line in p.stdout:
                if line.strip():
                    s["log"].append(line.strip()[:300])
                    del s["log"][:-60]
            if p.wait() != 0:
                s["error"] = (s["log"] or ["failed"])[-1]
        except Exception as exc:  # noqa: BLE001
            s["error"] = str(exc)
        finally:
            s["running"] = False
            _cache.clear()

    threading.Thread(target=go, daemon=True).start()


def _console(cmd: list[str]) -> None:
    """Open a visible console window (Windows) so the person can follow an installer or a sign-in."""
    subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)


@router.get("/api/setup/status")
def api_setup_status():
    return setup_status()


@router.post("/api/setup/tools")
def api_setup_tools():
    _bg("tools", [PY, str(SCRIPTS / "setup_tools.py"), str(TOOLS_DIR)])
    return setup_status()


@router.post("/api/setup/claude")
def api_setup_claude():
    if claude_bin():
        return setup_status()
    if WIN:
        _console(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                  "Write-Host 'Installing the AI engine...'; irm https://claude.ai/install.ps1 | iex; "
                  "Write-Host ''; Write-Host 'Done. Go back to the Euphoria page.'; Start-Sleep -Seconds 8"])
        _setup["claude"]["log"] = ["Installer opened in a new window. This page updates when it finishes."]
    else:
        _bg("claude", ["bash", "-c", "curl -fsSL https://claude.ai/install.sh | bash"])
    return setup_status()


@router.post("/api/setup/login")
def api_setup_login():
    exe = claude_bin()
    if not exe:
        raise HTTPException(409, "Install Claude Code first.")
    if WIN:
        bat = DATA_DIR / "claude_sign_in.cmd"
        bat.parent.mkdir(parents=True, exist_ok=True)
        bat.write_text("@echo off\r\ntitle Sign in to the AI engine\r\necho Sign in in the browser window that opens.\r\n"
                       f"\"{exe}\" auth login\r\necho.\r\necho Done. Close this window and go back to the Euphoria page."
                       "\r\ntimeout /t 15\r\n", encoding="utf-8")
        _console(["cmd", "/c", str(bat)])
        _setup["login"]["log"] = ["A sign-in window opened. Finish signing in in your browser."]
    else:
        _bg("login", [exe, "auth", "login"])
    _cache.pop("auth", None)
    return setup_status()


# ---------- the plan call (the only AI step) ----------

def transcript_message(meta: dict, words: list[dict], dur: float) -> str:
    lines, cur, prev_e = [], [], None
    for i, w in enumerate(words):
        if prev_e is not None and w["s"] - prev_e > 0.4:
            cur.append(f"(pause {w['s'] - prev_e:.1f}s)")
        cur.append(f"{i}:{w['w']}{'?' if w.get('p', 1) < 0.5 else ''}@{w['s']:.1f}")
        prev_e = w.get("e", w["s"] + 0.3)
        if len(cur) >= 14:
            lines.append(" ".join(cur)); cur = []
    if cur:
        lines.append(" ".join(cur))
    lang = LANGS.get(meta.get("language", "auto"), meta.get("language"))
    script = caption_script(meta).replace("mix_openai", "mix")
    mode = meta.get("cut_mode") or "gaps"
    return (f"Language: {lang}\nCaptions: {script}\nCutting: {mode}\nComment keyword: {meta.get('cta') or 'none'}\n"
            f"Creator notes: {meta.get('notes') or 'none'}\nDuration: {dur:.1f} s, {len(words)} words "
            f"(index:word@seconds, ? = unsure)\n\nTRANSCRIPT\n" + "\n".join(lines))


def caption_script(meta: dict) -> str:
    if meta.get("language") == "en":
        return "english"
    return meta.get("script") if meta.get("script") in CAPTION_SCRIPTS else "english"


def call_claude(rid: str, d: Path, meta: dict, message: str, schema: str | None = None, rules: str = "plan_rules.md",
                msg_name: str = "plan_message.txt") -> dict:
    exe = claude_bin()
    if not exe:
        raise RuntimeError("The AI engine isn't installed. Open Setup on this page and press Install.")
    schema = schema or (PROMPTS / "plan_schema.json").read_text(encoding="utf-8")
    flags = ["--safe-mode", "--tools", "", "--disallowedTools", "mcp__*", "--strict-mcp-config",
             "--mcp-config", '{"mcpServers":{}}', "--no-session-persistence", "--max-turns", "4",
             "--effort", os.environ.get("REEL_EFFORT", "medium")]
    if os.environ.get("REEL_CLAUDE_MODEL"):
        flags += ["--model", os.environ["REEL_CLAUDE_MODEL"]]
    rules_path = Path(rules) if Path(rules).is_absolute() else PROMPTS / rules
    base = [exe, "-p", "--output-format", "json", "--json-schema", schema,
            "--system-prompt-file", str(rules_path)]
    (d / msg_name).write_text(message, encoding="utf-8")
    for attempt in range(4):
        p = subprocess.Popen(base + flags, cwd=d, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        _procs.setdefault(rid, []).append(p)
        out, err = p.communicate(message, timeout=900)
        bad = re.search(r"unknown option '?(--[a-zA-Z-]+)", (err or "") + (out or ""))
        if p.returncode and bad and bad.group(1) in flags:          # older Claude Code: drop that flag, retry
            i = flags.index(bad.group(1))
            takes_value = i + 1 < len(flags) and not flags[i + 1].startswith("--")
            del flags[i:i + (2 if takes_value else 1)]
            log(rid, "warn", f"This AI engine version doesn't know {bad.group(1)}; retrying without it")
            continue
        break
    try:
        res = json.loads(out or "{}")
    except json.JSONDecodeError:
        raise RuntimeError(f"The AI returned something unexpected:\n{(out or err)[-800:]}")
    if res.get("is_error") or p.returncode:
        msg = res.get("result") or err or f"exit code {p.returncode}"
        if re.search(r"log ?in|auth|credential|401", str(msg), re.I):
            msg = "The AI engine isn't signed in. Open Setup on this page and press Sign in.\n" + str(msg)[:300]
        raise RuntimeError(str(msg)[-1200:])
    plan = res.get("structured_output")
    if not plan:
        txt = res.get("result") or ""
        a, b = txt.find("{"), txt.rfind("}")
        plan = json.loads(txt[a:b + 1]) if a >= 0 and b > a else None
    if not isinstance(plan, dict):
        raise RuntimeError("The AI didn't return an edit plan.")
    u = res.get("usage") or {}
    tokens = {"input": (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0)
              + (u.get("cache_creation_input_tokens") or 0), "output": u.get("output_tokens") or 0}
    update(rid, tokens=tokens, cost_usd=res.get("total_cost_usd"), model=res.get("model") or meta.get("model"))
    return plan



# ---------- versions, word edits and AI revisions (only what the creator asks changes) ----------

def save_plan(d: Path, plan: dict) -> None:
    tmp = d / "edit_plan.tmp"
    tmp.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, d / "edit_plan.json")


def versions(d: Path) -> list[dict]:
    p = d / "versions" / "versions.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def next_version(d: Path) -> int:
    return max([v["n"] for v in versions(d)] or [0]) + 1


def snapshot(d: Path, label: str, changes: list | None = None) -> int:
    """Keep the finished reel (plan + both videos) as version n, so any change can be compared or undone."""
    n = next_version(d)
    vd = d / "versions" / f"v{n}"
    vd.mkdir(parents=True, exist_ok=True)
    shutil.copy2(d / "edit_plan.json", vd / "edit_plan.json")
    if (d / "stable.json").exists():                 # the build's sticky choices, so going back restores them too
        shutil.copy2(d / "stable.json", vd / "stable.json")
    for f in ("reel.mp4", "reel-master.mp4"):
        if (d / "out" / f).exists():
            shutil.copy2(d / "out" / f, vd / f)
    vs = versions(d) + [{"n": n, "label": label[:120], "t": round(time.time()), "changes": changes or []}]
    (d / "versions" / "versions.json").write_text(json.dumps(vs, ensure_ascii=False, indent=1), encoding="utf-8")
    return n


def ensure_first_version(d: Path) -> None:
    """Reels made before versions existed: keep what's there as version 1 before the first change."""
    if not versions(d) and (d / "out" / "reel.mp4").exists() and (d / "edit_plan.json").exists():
        snapshot(d, "First edit")


def word_state(d: Path) -> list[dict]:
    """Every transcribed word with its caption text and whether it is in the reel."""
    W = json.loads((d / "words.json").read_text(encoding="utf-8"))
    plan = json.loads((d / "edit_plan.json").read_text(encoding="utf-8"))
    n = len(W)
    clamp = lambda i: max(0, min(n - 1, int(i)))
    kept = set(i for a, b in (plan.get("keep") or [[0, n - 1]]) for i in range(clamp(min(a, b)), clamp(max(a, b)) + 1))
    man = plan.get("manual") or {}
    kept |= set(man.get("keep") or [])
    kept -= set(man.get("cut") or [])
    rep = json.loads((d / "cut_report.json").read_text()) if (d / "cut_report.json").exists() else {}
    fillers = set(rep.get("fillers") or [])
    fix = {**(plan.get("fix") or {}), **(plan.get("user_fix") or {})}
    out = []
    for i, w in enumerate(W):
        state = "filler" if i in fillers else "kept" if i in kept else "cut"
        out.append({"i": i, "w": fix.get(str(i), w["w"]), "heard": w["w"], "s": round(w["s"], 2), "state": state,
                    "edited": str(i) in (plan.get("user_fix") or {})})
    return out


def apply_edits(plan: dict, n: int, fix: dict | None = None, cut: list | None = None, keep: list | None = None) -> list[str]:
    """Spelling fixes and cut / bring-back of words. Touches nothing else in the plan."""
    done = []
    ok = lambda i: str(i).isdigit() and 0 <= int(i) < n
    fix = {str(k): str(v).strip() for k, v in (fix or {}).items() if ok(k) and str(v).strip()}
    if fix:
        plan.setdefault("user_fix", {}).update(fix)
        done.append(f"Changed the spelling of {len(fix)} word{'s' if len(fix) > 1 else ''}")
    man = plan.setdefault("manual", {"cut": [], "keep": []})
    cut = sorted(set(int(i) for i in cut or [] if ok(i)))
    keep = sorted(set(int(i) for i in keep or [] if ok(i)))
    if cut:
        man["cut"] = sorted(set(man.get("cut") or []) | set(cut))
        man["keep"] = [i for i in man.get("keep") or [] if i not in cut]
        done.append(f"Cut {len(cut)} word{'s' if len(cut) > 1 else ''}")
    if keep:
        man["keep"] = sorted(set(man.get("keep") or []) | set(keep))
        man["cut"] = [i for i in man.get("cut") or [] if i not in keep]
        done.append(f"Brought back {len(keep)} word{'s' if len(keep) > 1 else ''}")
    return done


def apply_revision(plan: dict, rev: dict, n: int) -> list[str]:
    """Apply the AI's change set. Only the fields it names change; everything else stays byte for byte."""
    for k, v in (rev.get("set") or {}).items():
        if k in REVISE_SET and v is not None:
            plan[k] = v
    for k in rev.get("remove") or []:
        if k in ("headline", "back", "cta"):
            plan.pop(k, None)
    apply_edits(plan, n, rev.get("fix"), rev.get("cut_words"), rev.get("keep_words"))
    beats = plan.setdefault("beats", [])
    for u in rev.get("beats_update") or []:
        i = u.get("index")
        if isinstance(i, int) and 0 <= i < len(beats) and isinstance(u.get("fields"), dict):
            beats[i].update(u["fields"])
    for i in sorted({i for i in rev.get("beats_remove") or [] if isinstance(i, int) and 0 <= i < len(beats)}, reverse=True):
        del beats[i]
    for b in rev.get("beats_add") or []:
        if isinstance(b, dict) and b.get("type"):
            beats.append(b)
    return [str(x) for x in rev.get("summary") or []] or ["Applied your change"]


def plan_schema(style: str | None) -> str | None:
    """faceless has its own schema (the scene library); the others use the base one (None)"""
    p = STYLES_DIR / style / "plan_schema.json" if style == "faceless" else None
    return p.read_text(encoding="utf-8") if p and p.exists() else None


def revise_schema(style: str | None = None) -> str:
    base = json.loads(plan_schema(style) or (PROMPTS / "plan_schema.json").read_text(encoding="utf-8"))["properties"]
    beat = base["beats"]["items"]
    ints = {"type": "array", "items": {"type": "integer"}}
    setp = {k: base[k] for k in ("headline", "back", "cta", "accent") if k in base}
    setp.update({"accent_color": {"type": "string"}, "pace": {"type": "string", "enum": list(PACES)},
                 "cut_fillers": {"type": "boolean"}, "sfx": {"type": "boolean"}, "zoom": {"type": "boolean"},
                 "punch_ins": {"type": "boolean"}})
    return json.dumps({"type": "object", "properties": {
        "summary": {"type": "array", "items": {"type": "string"}}, "question": {"type": "string"},
        "fix": {"type": "object", "additionalProperties": {"type": "string"}},
        "cut_words": ints, "keep_words": ints,
        "set": {"type": "object", "properties": setp},
        "remove": {"type": "array", "items": {"type": "string", "enum": ["headline", "back", "cta"]}},
        "beats_update": {"type": "array", "items": {"type": "object", "properties": {
            "index": {"type": "integer"}, "fields": {"type": "object"}}, "required": ["index", "fields"]}},
        "beats_remove": ints, "beats_add": {"type": "array", "items": beat}}, "required": ["summary"]})


def revise_with_ai(rid: str, d: Path, meta: dict, plan: dict, words: list, request: str, rng: dict | None = None) -> dict:
    ws = word_state(d)
    lines, cur = [], []
    for w in ws:
        cur.append(f"{w['i']}:{w['w']}{'✂' if w['state'] != 'kept' else ''}@{w['s']:.1f}")
        if len(cur) >= 14:
            lines.append(" ".join(cur)); cur = []
    if cur:
        lines.append(" ".join(cur))
    shown = {k: v for k, v in plan.items() if k not in ("summary", "guessed", "claims", "fix", "user_fix")}
    shown["beats"] = [dict(b, index=i) for i, b in enumerate(plan.get("beats") or [])]
    msg = (f"Language: {LANGS.get(meta.get('language', 'auto'), meta.get('language'))}\n"
           f"Captions: {caption_script(meta).replace('mix_openai', 'mix')}\nCutting: {plan.get('cut_mode') or 'gaps'}\n\nCURRENT PLAN\n{json.dumps(shown, ensure_ascii=False)}\n\n"
           f"TRANSCRIPT (index:caption@seconds, ✂ = not in the reel)\n" + "\n".join(lines) +
           (f"\n\nTIME RANGE: the creator marked {fmt_t(rng['t0'])}-{fmt_t(rng['t1'])} of the finished reel = words "
            f"{min(rng['words'])}-{max(rng['words'])}. Change only things inside that range; everything else stays exactly as it is."
            if rng and rng["words"] else "") +
           f"\n\nCHANGE REQUEST\n{request}")
    log(rid, "step", "AI reads your request and changes only that (one small call)")
    style = style_of(meta)
    rules = str(system_prompt(d, style, "revise_rules.md", look=look_of(meta))) if style == "faceless" else "revise_rules.md"
    rev = call_claude(rid, d, meta, msg, schema=revise_schema(style), rules=rules, msg_name="revise_message.txt")
    (d / "revise_last.json").write_text(json.dumps(rev, ensure_ascii=False, indent=1), encoding="utf-8")
    if rev.get("question") and not any(rev.get(k) for k in ("fix", "cut_words", "keep_words", "set", "remove",
                                                              "beats_update", "beats_remove", "beats_add")):
        raise NeedsAnswer(rev["question"])
    skipped = limit_revision(rev, plan, rng) if rng and rng["words"] else []
    changes = apply_revision(plan, rev, len(words))
    save_plan(d, plan)
    for c in changes:
        log(rid, "claude", c)
    if skipped:
        changes.append("Left unchanged (outside your time range): " + "; ".join(dict.fromkeys(skipped)))
        log(rid, "warn", changes[-1])
    update(rid, last_changes=changes, version_label=request[:120])
    return plan


class NeedsAnswer(Exception):
    """The AI couldn't apply the change without asking something; nothing was changed."""


# ---------- edit styles ----------

def style_of(meta: dict) -> str | None:
    return meta.get("style") if meta.get("style") in STYLES else None


def load_style(style: str | None, look: str | None = None) -> dict:
    if not style:
        return {}
    st = json.loads((STYLES_DIR / style / "style.json").read_text(encoding="utf-8"))
    look = (st.get("aliases") or {}).get(look or "", look)
    if st.get("looks"):
        st.update(st["looks"].get(look or "") or next(iter(st["looks"].values())))
    return st


def look_of(meta: dict) -> str | None:
    style = style_of(meta)
    if style not in LOOKS:
        return None
    look = LOOK_ALIASES.get(style, {}).get(meta.get("look"), meta.get("look"))
    return look if look in LOOKS[style] else LOOKS[style][0]


def system_prompt(d: Path, style: str | None, base: str = "plan_rules.md", look: str | None = None) -> Path:
    """The planner's system prompt: the base rules plus the chosen style's notes (written into the job folder).
    Faceless also gets the scene list of the chosen look (styles/faceless/scenes_<look>.md)."""
    text = (PROMPTS / base).read_text(encoding="utf-8")
    extra = STYLES_DIR / style / "planner.md" if style else None
    if extra and extra.exists():
        text += "\n" + extra.read_text(encoding="utf-8")
    scenes = STYLES_DIR / style / f"scenes_{look}.md" if style and look else None
    if scenes and scenes.exists():
        text += "\n" + scenes.read_text(encoding="utf-8")
    out = d / ("system_prompt.md" if base == "plan_rules.md" else "system_prompt_" + base)
    out.write_text(text, encoding="utf-8")
    return out


def background(rid: str, d: Path, meta: dict) -> None:
    style = style_of(meta)
    if not style:
        run_script(rid, d, ["make_bg.py", "green"], meta, quiet=True)          # the original look
        return
    st = load_style(style, look_of(meta))
    run_script(rid, d, ["make_bg.py", st.get("bg", "neutral"), st.get("accent", "#4F8BFF")], meta, quiet=True)


def ff_run(args: list[str]) -> None:
    r = subprocess.run([find_tool("ffmpeg"), "-v", "error", "-y", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode:
        raise RuntimeError("ffmpeg failed: " + (r.stderr or "")[-600:])


def tts_windows(text: str, out: Path) -> None:
    """Windows' built-in speech (System.Speech): offline, robotic but clear. English voices on most PCs."""
    src = out.with_suffix(".txt")
    src.write_text(text, encoding="utf-8")
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          "$s.SetOutputToWaveFile($env:TTS_OUT); $s.Speak([IO.File]::ReadAllText($env:TTS_IN)); $s.Dispose()")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=600,
                       env=dict(os.environ, TTS_IN=str(src), TTS_OUT=str(out)))
    if r.returncode or not out.exists():
        raise RuntimeError("The Windows voice failed: " + (r.stderr or r.stdout or "")[-400:])


_HEAD = re.compile(r"^\s*(#{1,6}\s+.*|\*\*[^*]+\*\*\s*:?|__[^_]+__\s*:?)\s*$")
_LABEL = re.compile(r"^\s*(hook|intro(duction)?|outro|cta|call to action|body|main( point)?|conclusion|closing|ending|"
                    r"scene\s*\d+|part\s*\d+|step\s*\d+|point\s*\d+|voice ?over|vo|narrator|script)\s*[:|\-–—]\s*", re.I)
_TIMING = re.compile(r"\(\s*\d+(\.\d+)?\s*(s|sec|secs|seconds)?\s*[-–—to]+\s*\d+(\.\d+)?\s*(s|sec|secs|seconds)?\s*\)", re.I)


def clean_script(text: str) -> str:
    """The words to show and speak: drops markdown, headings ("**Introduction**"), stage directions and timings
    ("[0-5 sec | Hook]", "(5-12 sec)"), section labels ("Hook:") and quote marks around whole lines."""
    out = []
    for ln in (text or "").splitlines():
        if not ln.strip() or (_HEAD.match(ln) and len(re.sub(r"[*_#:]", " ", ln).split()) <= 6):
            continue
        t = re.sub(r"\[[^\]]*\]", " ", ln)                    # [stage directions / timings]
        t = _TIMING.sub(" ", t)
        t = re.sub(r"[*_#`>|]+", " ", t)                          # markdown leftovers
        t = re.sub(r"^\s*[-•]\s+", "", t)                        # bullet marks
        t = _LABEL.sub("", t)
        t = re.sub(r"\s+([,.!?;:])", r"\1", re.sub(r"\s+", " ", t)).strip()
        if len(t) >= 2 and t[0] in "\"“'‘" and t[-1] in "\"”'’":
            t = t[1:-1].strip()
        if re.search(r"\w", t):
            out.append(t)
    return " ".join(out)


SCRIPT_SCHEMA = json.dumps({"type": "object", "properties": {"script": {"type": "string"}, "title": {"type": "string"}},
                            "required": ["script"]})


def faceless_prepare(rid: str, d: Path, meta: dict) -> None:
    """No talking head: the script (written by the AI if asked), an optional voice, and a background 'video'."""
    background(rid, d, meta)
    if (d / "src.mp4").exists() and (d / "words.json").exists():
        return
    voice = meta.get("voice_file")
    script = d / "script.txt"
    if script.exists():                               # older jobs / Retry: make sure the script is clean
        raw = script.read_text(encoding="utf-8")
        if clean_script(raw) != raw.strip():
            script.write_text(clean_script(raw), encoding="utf-8")
            log(rid, "app", "Removed headings, timings and stage directions from the script")
            if meta.get("voice") in ("windows", "elevenlabs") and voice == "voice.wav":   # read the clean script aloud again
                voice = None
                update(rid, voice_file=None)
                for f in ("src.mp4", "words.json"):
                    if (d / f).exists():
                        (d / f).unlink()
    if not voice and not script.exists():
        if meta.get("script_mode") == "write":
            update(rid, status="editing", phase="AI is writing your script")
            log(rid, "step", "AI writes a short script from your topic (one small call)")
            lang = LANGS.get(meta.get("language", "auto"), meta.get("language"))
            msg = (f"Language: {lang}\nComment keyword: {meta.get('cta') or 'none'}\n\nTOPIC / NOTES\n"
                   f"{meta.get('script_text') or ''}")
            out = call_claude(rid, d, meta, msg, schema=SCRIPT_SCHEMA, rules=str(STYLES_DIR / "faceless" / "script_rules.md"),
                              msg_name="script_message.txt")
            text = clean_script(str(out.get("script") or ""))
            if len(text.split()) < 5:
                raise RuntimeError("The AI didn't write a usable script. Write a few lines yourself or try again.")
            script.write_text(text, encoding="utf-8")
            log(rid, "claude", "Script: " + text[:300] + ("..." if len(text) > 300 else ""))
        else:
            raw = meta.get("script_text") or ""
            text = clean_script(raw)
            if not text.split():
                raise RuntimeError("The script has no words left after removing headings and timings.")
            script.write_text(text, encoding="utf-8")
            if text != raw.strip():
                log(rid, "app", "Removed headings, timings and stage directions from the script")
    if not voice and meta.get("voice") == "elevenlabs":
        update(rid, phase="Recording the voice-over (ElevenLabs)")
        log(rid, "step", "ElevenLabs reads your script aloud (word timings come with the voice)")
        dur, wds = tts.speak(script.read_text(encoding="utf-8"), d / "voice.wav", meta.get("language"), meta.get("voice_id"))
        if wds:
            (d / "words.json").write_text(json.dumps(wds, ensure_ascii=False), encoding="utf-8")
        log(rid, "app", f"Voice-over ready: {dur:.1f} s" + ("" if wds else " (no word timings came back; transcribing it)"))
        voice = "voice.wav"
        update(rid, voice_file=voice)
    if not voice and meta.get("voice") == "windows":
        if WIN:
            update(rid, phase="Reading your script aloud (Windows voice)")
            tts_windows(script.read_text(encoding="utf-8"), d / "voice.wav")
            voice = "voice.wav"
            update(rid, voice_file=voice)
        else:
            log(rid, "warn", "The computer voice needs Windows; making the reel without a voice")
    update(rid, phase="Building the background")
    if voice:
        run_script(rid, d, ["faceless_prep.py", "script.txt", "--voice", voice], meta, "Laying your voice-over on the background", quiet=True)
        if not (d / "words.json").exists():
            update(rid, phase="Transcribing every word")
            run_script(rid, d, ["transcribe.py", "audio16k.wav", "words.json", "--lang", meta.get("language", "auto"),
                                "--task", "transcribe", "--engine", "local"], meta, "Timing every word of the voice-over", quiet=True)
    else:
        wps = load_style("faceless").get("words_per_second", 2.6)
        run_script(rid, d, ["faceless_prep.py", "script.txt", "--wps", str(wps)], meta, "Timing the script at reading speed", quiet=True)


def is_silent(wav: Path) -> bool:
    """True when a 16-bit WAV never gets above -50 dBFS (Whisper invents words on silence)."""
    import wave
    import numpy as np
    try:
        with wave.open(str(wav)) as w:
            a = np.frombuffer(w.readframes(w.getnframes()), np.int16)
        return not len(a) or float(np.abs(a).max()) < 32768 * 0.0032
    except Exception:  # noqa: BLE001
        return False


def product_narration(rid: str, d: Path, meta: dict, plan: dict) -> None:
    """ElevenLabs reads each scene's 'say' line -> narr_<hash>.wav + narration.json (scene index -> wav, length, words).
    Lines are cached, so a change to one scene only records that scene again."""
    lines = {i: clean_script(str(sc.get("say") or "")) for i, sc in enumerate(plan.get("scenes") or []) if isinstance(sc, dict)}
    lines = {i: t for i, t in lines.items() if t.split()}
    if not lines:
        log(rid, "warn", "The plan has no narration lines; keeping the recording's own sound")
        if (d / "narration.json").exists():
            (d / "narration.json").unlink()
        return
    update(rid, phase="Recording the narration (ElevenLabs)")
    out = {}
    for i, text in lines.items():
        name = "narr_" + hashlib.sha1(json.dumps([text, meta.get("voice_id"), meta.get("language")]).encode()).hexdigest()[:12] + ".wav"
        dur, wds = tts.speak(text, d / name, meta.get("language"), meta.get("voice_id"))
        out[str(i)] = {"wav": name, "dur": round(dur, 3), "words": wds, "text": text}
    (d / "narration.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    log(rid, "app", f"Narration ready: {len(out)} lines, {sum(v['dur'] for v in out.values()):.1f} s")


def product_message(meta: dict, words: list[dict], act: dict) -> str:
    rows, lines, still = act.get("rows") or [], [], None
    for r in rows:
        if r[1] < 0.002 or r[2] is None:
            still = r[0] if still is None else still
            continue
        if still is not None:
            lines.append(f"{still:.1f}-{r[0]:.1f} still"); still = None
        lines.append(f"{r[0]:.1f} {r[1]:.3f} box {r[2]:.2f},{r[3]:.2f}-{r[4]:.2f},{r[5]:.2f}")
    if still is not None:
        lines.append(f"{still:.1f}-{act.get('dur', 0):.1f} still")
    talk = " ".join(f"{i}:{w['w']}@{w['s']:.1f}" for i, w in enumerate(words)) or "none (no voice)"
    narr = ("Narration: YES - write a 'say' line for every scene (ElevenLabs speaks it over that scene; the recording's "
            "own sound is muted)\n") if meta.get("voice") == "elevenlabs" else ""
    return (narr + f"Product notes: {meta.get('notes') or 'none'}\nComment keyword / CTA: {meta.get('cta') or 'none'}\n"
            f"Language of on-screen text: {LANGS.get(meta.get('language', 'auto'), 'English')}\n"
            f"Recording: {act.get('dur', 0):.1f} s, {act.get('w')}x{act.get('h')}\n\n"
            f"ACTIVITY (time share-of-screen-changed box x0,y0-x1,y1 as fractions; 'still' = nothing moved)\n"
            + "\n".join(lines) + f"\n\nVOICE TRANSCRIPT\n{talk}")


def product_revise_schema() -> str:
    base = json.loads((STYLES_DIR / "product" / "plan_schema.json").read_text(encoding="utf-8"))["properties"]
    ints = {"type": "array", "items": {"type": "integer"}}
    return json.dumps({"type": "object", "properties": {
        "summary": {"type": "array", "items": {"type": "string"}}, "question": {"type": "string"},
        "scenes_update": {"type": "array", "items": {"type": "object", "properties": {
            "index": {"type": "integer"}, "fields": {"type": "object"}}, "required": ["index", "fields"]}},
        "scenes_remove": ints, "scenes_add": base["scenes"],
        "set": {"type": "object", "properties": {"title": base["title"], "outro": base["outro"],
                                                 "accent_color": {"type": "string"}, "sfx": {"type": "boolean"}}}},
        "required": ["summary"]})


def fmt_t(x: float) -> str:
    return f"{int(x // 60)}:{x % 60:04.1f}"


def range_info(d: Path, t0: float, t1: float) -> dict:
    """What lies inside output seconds t0-t1 of the current reel: word indexes (talking head / faceless)."""
    wo = json.loads((d / "words_out.json").read_text(encoding="utf-8")) if (d / "words_out.json").exists() else []
    inside = [w["i"] for w in wo if w.get("e", w["s"] + 0.3) >= t0 - 0.15 and w["s"] <= t1 + 0.15]
    if not inside and wo:
        mid = (t0 + t1) / 2
        inside = [min(wo, key=lambda w: abs(w["s"] - mid))["i"]]
    words = set(range(min(inside), max(inside) + 1)) if inside else set()     # cut words in between count too
    dur = json.loads((d / "edit.json").read_text())["dur"] if (d / "edit.json").exists() else 0
    return {"words": words, "dur": dur, "t0": t0, "t1": t1}


def limit_revision(rev: dict, plan: dict, rng: dict) -> list[str]:
    """Keep only the parts of the AI's change set that act inside the chosen time range. Returns what was skipped."""
    ok, skipped = rng["words"], []
    inside = lambda i: isinstance(i, int) and i in ok or str(i).isdigit() and int(i) in ok
    for key in ("cut_words", "keep_words"):
        if rev.get(key):
            keep = [i for i in rev[key] if inside(i)]
            if len(keep) < len(rev[key]):
                skipped.append(f"{len(rev[key]) - len(keep)} word cut(s) outside the range")
            rev[key] = keep
    if rev.get("fix"):
        keep = {k: v for k, v in rev["fix"].items() if inside(k)}
        if len(keep) < len(rev["fix"]):
            skipped.append("spelling changes outside the range")
        rev["fix"] = keep
    beats = plan.get("beats") or []
    def beat_in(b):
        try:
            return bool(set(range(int(b.get("from", 0)), int(b.get("to", b.get("from", 0))) + 1)) & ok)
        except (TypeError, ValueError):
            return False
    for key in ("beats_update",):
        if rev.get(key):
            keep = [u for u in rev[key] if isinstance(u.get("index"), int) and 0 <= u["index"] < len(beats) and beat_in(beats[u["index"]])]
            if len(keep) < len(rev[key]):
                skipped.append("graphics outside the range")
            rev[key] = keep
    if rev.get("beats_remove"):
        keep = [i for i in rev["beats_remove"] if isinstance(i, int) and 0 <= i < len(beats) and beat_in(beats[i])]
        if len(keep) < len(rev["beats_remove"]):
            skipped.append("removing graphics outside the range")
        rev["beats_remove"] = keep
    if rev.get("beats_add"):
        keep = [b for b in rev["beats_add"] if isinstance(b, dict) and beat_in(b)]
        if len(keep) < len(rev["beats_add"]):
            skipped.append("new graphics outside the range")
        rev["beats_add"] = keep
    start, end = rng["t0"] < 4.0, rng["t1"] >= rng["dur"] - 3.0
    cta_from = (plan.get("cta") or {}).get("from")
    st = dict(rev.get("set") or {})
    for k in list(st):
        if k in ("headline", "back") and not start:
            skipped.append(f"{k} (it is at the start)"); st.pop(k)
        elif k == "cta" and not (end or (cta_from is not None and inside(cta_from))):
            skipped.append("call to action (it is at the end)"); st.pop(k)
        elif k == "accent":
            old = [i for i in plan.get("accent") or [] if not inside(i)]
            st[k] = old + [i for i in st[k] or [] if inside(i)]
        elif k not in ("headline", "back", "cta", "accent"):
            skipped.append(f"{k.replace('_', ' ')} (changes the whole reel)"); st.pop(k)
    rev["set"] = st
    if rev.get("remove"):
        keep = [k for k in rev["remove"] if (k in ("headline", "back") and start) or (k == "cta" and end)]
        if len(keep) < len(rev["remove"]):
            skipped.append("removals outside the range")
        rev["remove"] = keep
    return skipped


def apply_product_revision(plan: dict, rev: dict, allowed: set | None = None, rng: dict | None = None) -> tuple[list[str], list[str]]:
    scenes = plan.setdefault("scenes", [])
    skipped = []
    ok = lambda i: isinstance(i, int) and 0 <= i < len(scenes) and (allowed is None or i in allowed)
    for u in rev.get("scenes_update") or []:
        if ok(u.get("index")) and isinstance(u.get("fields"), dict):
            scenes[u["index"]].update({k: v for k, v in u["fields"].items() if k in
                                       ("from", "to", "speed", "zoom", "focus", "text", "sub", "say")})
        elif isinstance(u.get("index"), int):
            skipped.append(f"scene {u['index'] + 1} (outside the range)")
    rm = sorted({i for i in rev.get("scenes_remove") or [] if ok(i)}, reverse=True)
    if len(rm) < len(rev.get("scenes_remove") or []):
        skipped.append("removing scenes outside the range")
    for i in rm:
        del scenes[i]
    for sc in rev.get("scenes_add") or []:
        if isinstance(sc, dict) and "from" in sc and "to" in sc:
            scenes.append(sc)
    scenes.sort(key=lambda sc: float(sc.get("from") or 0))
    for k, v in (rev.get("set") or {}).items():
        if v is None or k not in ("title", "outro", "accent_color", "sfx"):
            continue
        if rng and ((k == "title" and rng["t0"] >= 3.5) or (k == "outro" and rng["t1"] < rng["dur"] - 3.0)
                    or k in ("accent_color", "sfx")):
            skipped.append(f"{k.replace('_', ' ')} (outside the range)" if k in ("title", "outro") else f"{k.replace('_', ' ')} (changes the whole reel)")
            continue
        plan[k] = v
    return [str(x) for x in rev.get("summary") or []] or ["Applied your change"], skipped


def revise_product(rid: str, d: Path, meta: dict, plan: dict, request: str, rng: dict | None) -> dict:
    so = json.loads((d / "scenes_out.json").read_text()) if (d / "scenes_out.json").exists() else {"scenes": {}}
    shown = {k: v for k, v in plan.items() if k not in ("summary",)}
    shown["scenes"] = [dict(sc, index=i, out="-".join(f"{x:.1f}" for x in so["scenes"].get(str(i), [])) or "cut")
                       for i, sc in enumerate(plan.get("scenes") or [])]
    allowed = None
    note = ""
    if rng:
        allowed = {int(i) for i, (a, b) in so["scenes"].items() if int(i) >= 0 and b > rng["t0"] and a < rng["t1"]}
        note = (f"\n\nTIME RANGE: the creator marked {fmt_t(rng['t0'])}-{fmt_t(rng['t1'])} of the finished reel. "
                f"Change only scenes {sorted(allowed) or 'none'} (and the title if the range is at the start, the outro if at the end).")
    act = json.loads((d / "activity.json").read_text()) if (d / "activity.json").exists() else {}
    msg = (f"CURRENT PLAN\n{json.dumps(shown, ensure_ascii=False)}\n\n" + product_message(meta, [], act).split("\n\n", 1)[1]
           + note + f"\n\nCHANGE REQUEST\n{request}")
    log(rid, "step", "AI reads your request and changes only that (one small call)")
    rev = call_claude(rid, d, meta, msg, schema=product_revise_schema(), rules=str(STYLES_DIR / "product" / "revise_rules.md"),
                      msg_name="revise_message.txt")
    (d / "revise_last.json").write_text(json.dumps(rev, ensure_ascii=False, indent=1), encoding="utf-8")
    if rev.get("question") and not any(rev.get(k) for k in ("scenes_update", "scenes_remove", "scenes_add", "set")):
        raise NeedsAnswer(rev["question"])
    if rng:
        rng = dict(rng, dur=so.get("dur") or rng["dur"])
    changes, skipped = apply_product_revision(plan, rev, allowed, rng)
    save_plan(d, plan)
    for c in changes:
        log(rid, "claude", c)
    if skipped:
        changes.append("Left unchanged (outside your time range): " + "; ".join(dict.fromkeys(skipped)))
        log(rid, "warn", changes[-1])
    update(rid, last_changes=changes, version_label=request[:120])
    return plan


# ---------- the job ----------

def shards() -> int:
    """graphics renderers to run at once (one headless browser each)"""
    return max(1, int(os.environ.get("REEL_OV_SHARDS") or 2))


def process(rid: str) -> None:
    d = REELS_DIR / rid
    meta = read_meta(rid)
    if meta.get("status") == "cancelled":
        return
    update(rid, started=time.time(), error=None, status="preparing", phase="Reading your video")
    style = style_of(meta)
    try:
        if not tools_ready():
            raise RuntimeError("The render tools aren't installed yet. Open Setup on this page and press Install.")
        tools = json.loads((TOOLS_DIR / "tools.json").read_text(encoding="utf-8"))
        json.dump({"ffmpeg": find_tool("ffmpeg"), "chrome": tools.get("chrome", "playwright"), "chrome_args": [],
                   "asr": "app", "seg": bool(tools.get("seg")), "models": tools["models"], "home": str(d)},
                  open(d / "env.json", "w", encoding="utf-8"), indent=1)
        if not (d / "fonts").exists():
            shutil.copytree(tools["fonts"], d / "fonts")
        if style == "faceless":
            faceless_prepare(rid, d, meta)
        else:
            if not (d / "src.mp4").exists():
                run_script(rid, d, ["prep.py", str(d / meta["file"])], meta, "Normalising the video (upright, 30 fps)", quiet=True)
            background(rid, d, meta)
            if not (d / "words.json").exists() and style == "product" and is_silent(d / "audio16k.wav"):
                (d / "words.json").write_text("[]", encoding="utf-8")       # screen recording without a voice
                log(rid, "app", "No voice in the recording: titles carry the story, no captions")
            if not (d / "words.json").exists():
                update(rid, phase="Transcribing every word")
                task = "translate" if caption_script(meta) == "english" and meta.get("language") != "en" else "transcribe"
                engine = "openai" if caption_script(meta) == "mix_openai" else "local"
                label = ("Transcribing with OpenAI (Malayalam + English), timing from your voice" if engine == "openai"
                         else "Transcribing every word (Whisper" + (", English captions)" if task == "translate" else ")"))
                try:
                    run_script(rid, d, ["transcribe.py", "audio16k.wav", "words.json", "--lang", meta.get("language", "auto"),
                                        "--task", task, "--engine", engine], meta, label, quiet=True)
                except RuntimeError as exc:
                    if style != "product":
                        raise
                    log(rid, "warn", "No voice found in the recording; making it without captions")
                    (d / "words.json").write_text("[]", encoding="utf-8")
        words = json.loads((d / "words.json").read_text(encoding="utf-8"))
        if not words and style != "product":
            raise RuntimeError("No speech found in this video. Upload a take where you talk to the camera."
                               if style != "faceless" else "The script is empty.")
        log(rid, "app", f"{len(words)} words " + ("timed" if style == "faceless" else "transcribed"))
        src = json.loads((d / "src.json").read_text())
        if style == "product" and not (d / "activity.json").exists():
            update(rid, phase="Finding what moves on screen")
            run_script(rid, d, ["activity.py"], meta, "Mapping where the screen changes (for zooms and cuts)")

        if not (d / "edit_plan.json").exists():
            update(rid, status="editing", phase="AI is planning the edit")
            if style == "product":
                log(rid, "step", "AI reads the recording's activity map and plans scenes, zooms, speed-ups and titles (one pass)")
                act = json.loads((d / "activity.json").read_text())
                plan = call_claude(rid, d, meta, product_message(meta, words, act),
                                   schema=(STYLES_DIR / "product" / "plan_schema.json").read_text(encoding="utf-8"),
                                   rules=str(STYLES_DIR / "product" / "planner.md"))
            else:
                log(rid, "step", "AI reads the " + ("script" if style == "faceless" else "transcript")
                    + " and plans cuts, captions, hook and graphics (one pass)")
                plan = call_claude(rid, d, meta, transcript_message(meta, words, src["dur"]), schema=plan_schema(style),
                                   rules=str(system_prompt(d, style, look=look_of(meta))))
            if style:
                plan["style"] = style
                if look_of(meta):
                    plan["look"] = look_of(meta)
            if style == "faceless":
                plan["keep"] = [[0, len(words) - 1]]
                plan["cut_mode"] = "gaps" if meta.get("voice_file") else "none"
                plan.pop("back", None)
            (d / "edit_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
            tk = read_meta(rid).get("tokens") or {}
            if style == "product":
                log(rid, "claude", f"Plan ready: {len(plan.get('scenes', []))} scenes, outro \"{(plan.get('outro') or {}).get('name', '')}\""
                    + (f" · {tk.get('input', 0) + tk.get('output', 0):,} tokens" if tk else ""))
            else:
                log(rid, "claude", f"Plan ready: {len(plan.get('beats', []))} graphics, hook \"{(plan.get('headline') or {}).get('l1', '')}\""
                    + (f" · {tk.get('input', 0) + tk.get('output', 0):,} tokens" if tk else ""))
            for s_ in plan.get("summary") or []:
                log(rid, "claude", s_)
        plan = json.loads((d / "edit_plan.json").read_text(encoding="utf-8"))
        if style != "product" and ("pace" not in plan or "cut_mode" not in plan):
            plan.setdefault("pace", meta.get("pace") or "tight")
            plan.setdefault("cut_mode", meta.get("cut_mode") or "gaps")
            if plan["cut_mode"] == "gaps":           # everything said stays; only pauses and umms go
                plan["keep"] = [[0, len(words) - 1]]
            save_plan(d, plan)
        req = read_meta(rid).get("pending_revision")
        if req:
            update(rid, status="editing", phase="AI is applying your change")
            rng = read_meta(rid).get("pending_range")
            if style == "product":
                plan = revise_product(rid, d, read_meta(rid), plan, req,
                                      {"t0": rng[0], "t1": rng[1], "dur": 0} if rng else None)
            else:
                plan = revise_with_ai(rid, d, read_meta(rid), plan, words, req, range_info(d, rng[0], rng[1]) if rng else None)
            update(rid, pending_revision=None, pending_range=None)

        update(rid, status="rendering", phase="Cutting pauses, umms and retakes" if style != "product" else "Cutting the scenes")
        if style == "product":
            if meta.get("voice") == "elevenlabs":
                product_narration(rid, d, meta, plan)
            elif (d / "narration.json").exists():
                (d / "narration.json").unlink()
            run_script(rid, d, ["product_build.py", "edit_plan.json"], meta, "Building scenes, zooms, speed-ups, titles and sound")
        else:
            run_script(rid, d, ["build_plan.py", "edit_plan.json"], meta, "Building cuts, captions, layouts, graphics and sound")
            back = json.loads((d / "overlay_cfg.json").read_text()).get("back") or []
            if back:
                update(rid, phase="Building the graphics")
                run_script(rid, d, ["masks.py", "0", f"{back[0][1] + 0.1:.2f}"], meta, "Cutting you out for the text behind your head", quiet=True)
        update(rid, phase="Building the graphics")
        log(rid, "step", "Drawing the motion graphics (frames that didn't change are reused)")
        n = shards()
        run_parallel(rid, d, [["render_overlay.py", "ov", "all", f"{k}/{n}"] for k in range(n)], meta)
        update(rid, phase="Rendering the full video")
        out = run_script(rid, d, ["composite.py", "full", "ov", "base_ov.mp4"], meta, "Rendering: cuts, zooms, grade, layouts, graphics", quiet=True)
        reuse = next((ln for ln in out.splitlines() if ln.startswith("chunks ")), "")
        if reuse:
            log(rid, "app", "Video pieces " + reuse.replace("chunks ", "", 1))
        update(rid, phase="Adding sound")
        run_script(rid, d, ["sfx.py", "sfx_events.json"], meta, "Adding sound effects", quiet=True)
        if meta.get("music_file") and not (d / "music.wav").exists():
            ff_run(["-i", str(d / meta["music_file"]), "-vn", "-ac", "2", "-ar", "48000", str(d / "music.wav")])
        update(rid, phase="Finishing")
        run_script(rid, d, ["finish.py", "reel"], meta, "Mixing to Instagram loudness and exporting")
        if not (d / "out" / "reel.mp4").exists():
            raise RuntimeError("The render finished without a video file.")
        if style == "product":
            summary = plan.get("summary") or []
            report = {"summary": summary, "guessed_words": [], "claims_to_check": [],
                      "changes": read_meta(rid).get("last_changes") or [], "cuts": {}}
        else:
            report = {"summary": plan.get("summary") or [], "guessed_words": plan.get("guessed") or [],
                      "claims_to_check": plan.get("claims") or [], "changes": read_meta(rid).get("last_changes") or [],
                      "cuts": json.loads((d / "cut_report.json").read_text()) if (d / "cut_report.json").exists() else {}}
        (d / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        n = snapshot(d, read_meta(rid).get("version_label") or "First edit", report.get("changes") or [])
        update(rid, status="done", phase="Done", finished=time.time(), report=report, version=n, version_label=None)
        log(rid, "app", "Finished reel is ready")
    except NeedsAnswer as q:          # the AI asked a question instead of guessing: nothing changed
        update(rid, status="done", phase="Done", pending_revision=None, pending_range=None, version_label=None,
               question=str(q), finished=time.time())
        log(rid, "claude", "Question before changing anything: " + str(q))
    except Exception as exc:  # noqa: BLE001
        if read_meta(rid).get("status") == "cancelled":
            return
        traceback.print_exc()
        update(rid, status="failed", phase="Failed", error=str(exc)[-1500:], finished=time.time())
        log(rid, "warn", str(exc)[-600:])
    finally:
        _procs.pop(rid, None)


def _loop() -> None:
    while True:
        rid = _q.get()
        try:
            process(rid)
        finally:
            _q.task_done()


def enqueue(rid: str) -> None:
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_loop, daemon=True)
        _worker.start()
    _q.put(rid)


def resume_interrupted() -> None:
    REELS_DIR.mkdir(parents=True, exist_ok=True)
    for m in list_all():
        if m.get("status") == "queued":
            enqueue(m["id"])
        elif m.get("status") in ("preparing", "editing", "rendering"):
            update(m["id"], status="failed", phase="Failed", error="The app was closed during the edit. Press Retry.")


def list_all() -> list[dict]:
    out = []
    if REELS_DIR.exists():
        for p in REELS_DIR.iterdir():
            if (p / "meta.json").exists():
                try:
                    m = json.loads((p / "meta.json").read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    continue
                m.pop("log", None)
                out.append(m)
    return sorted(out, key=lambda m: m.get("created", 0), reverse=True)


def kill(rid: str) -> None:
    for p in _procs.get(rid, []):
        if p.poll() is None:
            if WIN:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
            else:
                p.terminate()


# ---------- routes ----------

@router.get("/site")
def site():
    return FileResponse(WEB_DIR / "site.html", media_type="text/html")


_SITE_MEDIA = {".mp4": "video/mp4", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


@router.get("/site/media/{name}")
def site_media(name: str):
    """Showcase reels/posters for the landing page's 3D cylinder (app/web/media)."""
    path = (WEB_DIR / "media" / name).resolve()
    if path.parent != (WEB_DIR / "media").resolve() or path.suffix.lower() not in _SITE_MEDIA or not path.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(path, media_type=_SITE_MEDIA[path.suffix.lower()], headers={"Cache-Control": "public, max-age=86400"})


@router.get("/api/reels/health")
def health():
    st = setup_status()
    return {"ready": st["ready"], "claude": st["claude"]["installed"], "signed_in": st["login"]["signed_in"],
            "tools": st["tools"]["ready"], "languages": LANGS, "scripts": CAPTION_SCRIPTS, "paces": PACES,
            "styles": STYLES, "voices": VOICES, "product_voices": PRODUCT_VOICES, "elevenlabs": tts.ready(),
            "windows": WIN, "queue": _q.qsize()}


@router.get("/api/reels")
def reels():
    return list_all()


def _save_upload(up: UploadFile, dest: Path) -> None:
    with open(dest, "wb") as out:
        shutil.copyfileobj(up.file, out, length=1024 * 1024)


@router.post("/api/reels")
def create(file: UploadFile | None = File(None), language: str = Form("ml"), cta: str = Form(""), notes: str = Form(""),
           script: str = Form("english"), pace: str = Form("tight"), cut_mode: str = Form("gaps"),
           style: str = Form("talking_head"), look: str = Form(""), script_text: str = Form(""),
           script_mode: str = Form("exact"), voice: str = Form("none"), voice_file: UploadFile | None = File(None),
           music: UploadFile | None = File(None), voice_id: str = Form("")):
    style = style if style in STYLES else "talking_head"
    if voice == "elevenlabs" and style in ("faceless", "product"):
        if not tts.ready():
            raise HTTPException(400, "ElevenLabs isn't set up: add ELEVENLABS_API_KEY=... to app/.env and restart the app.")
        try:
            tts.check_voice_id(voice_id.strip())
        except RuntimeError as exc:
            raise HTTPException(400, str(exc))
    if file is not None and not file.filename:
        file = None
    if voice_file is not None and not voice_file.filename:
        voice_file = None
    if music is not None and not music.filename:
        music = None
    ext = Path(file.filename).suffix.lower() if file else ""
    if style != "faceless":
        if not file:
            raise HTTPException(400, "Choose a video to edit." if style == "talking_head" else "Choose your screen recording.")
        if ext not in VIDEO_EXT:
            raise HTTPException(400, "Upload a video file (mp4, mov, m4v, webm, mkv or avi).")
    else:
        if voice == "upload" and not voice_file:
            raise HTTPException(400, "Add your voice-over file, or pick another voice option.")
        if not voice_file and len(script_text.split()) < (2 if script_mode == "write" else 5):
            raise HTTPException(400, "Write your script (or the topic, if the AI should write it).")
    for up, kinds in ((voice_file, AUDIO_EXT), (music, AUDIO_EXT)):
        if up and Path(up.filename).suffix.lower() not in kinds:
            raise HTTPException(400, f"{up.filename}: upload an audio file (mp3, wav, m4a) or a video.")
    if language not in LANGS:
        language = "auto"
    rid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    d = REELS_DIR / rid
    d.mkdir(parents=True)
    meta = {"id": rid, "created": time.time(), "style": style, "language": language, "cta": cta.strip()[:40],
            "notes": notes.strip()[:600], "script": script if script in CAPTION_SCRIPTS else "english",
            "pace": pace if pace in PACES else "tight", "cut_mode": cut_mode if cut_mode in CUT_MODES else "gaps",
            "status": "queued", "phase": "Waiting to start", "log": [], "log_n": 0}
    if file:
        _save_upload(file, d / f"raw{ext}")
        meta.update(name=file.filename or f"raw{ext}", file=f"raw{ext}")
    else:
        words = script_text.split()
        meta.update(name=(" ".join(words[:6]) + ("..." if len(words) > 6 else "")) or "Faceless reel", file=None)
    if style in LOOKS:
        look = LOOK_ALIASES.get(style, {}).get(look, look)
        meta["look"] = look if look in LOOKS[style] else LOOKS[style][0]
    if style == "product":
        meta["voice"] = voice if voice in PRODUCT_VOICES else "recording"
    if voice == "elevenlabs" and voice_id.strip():
        meta["voice_id"] = voice_id.strip()
    if style == "faceless":
        meta.update(script_text=script_text.strip()[:6000], script_mode="write" if script_mode == "write" else "exact",
                    voice=voice if voice in VOICES else "none", cut_mode="gaps")
        if voice_file:
            vext = Path(voice_file.filename).suffix.lower()
            _save_upload(voice_file, d / f"voice{vext}")
            meta.update(voice_file=f"voice{vext}", voice="upload")
    if music:
        mext = Path(music.filename).suffix.lower()
        _save_upload(music, d / f"music_in{mext}")
        meta["music_file"] = f"music_in{mext}"
    write_meta(rid, meta)
    log(rid, "app", f"Upload received · style: {STYLES[style].split(' - ')[0]}")
    enqueue(rid)
    return {k: v for k, v in meta.items() if k != "log"}


@router.get("/api/reels/{rid}")
def get(rid: str, since: int = 0):
    try:
        rdir(rid)
    except KeyError:
        raise HTTPException(404, "No such reel")
    m = read_meta(rid)
    total, lines = m.get("log_n", 0), m.pop("log", [])
    first = total - len(lines)
    m["log"] = lines[max(0, since - first):] if since else lines[-80:]
    m["queue_ahead"] = _q.qsize() if m.get("status") == "queued" else 0
    m["has_output"] = (REELS_DIR / rid / "out" / "reel.mp4").exists()
    return m


@router.get("/api/reels/{rid}/video")
def video(rid: str, kind: str = "final", download: bool = False, v: int = 0):
    try:
        d = rdir(rid)
    except KeyError:
        raise HTTPException(404, "No such reel")
    m = read_meta(rid)
    base = d / "versions" / f"v{int(v)}" if v else d / "out"
    p = {"final": base / "reel.mp4", "master": base / "reel-master.mp4", "raw": d / m["file"] if m.get("file") else None}.get(kind)
    if not p or not p.exists():
        raise HTTPException(404, "Not ready yet")
    stem = Path(m.get("name", "reel")).stem
    return FileResponse(p, media_type="video/mp4",
                        filename=f"{stem}_euphoria{'_master' if kind == 'master' else ''}.mp4" if download else None)


@router.get("/api/reels/{rid}/image/{name}")
def image(rid: str, name: str):
    if name not in ("final_sheet.jpg", "first_frame.jpg", "contact.jpg"):
        raise HTTPException(404, "No such image")
    try:
        p = rdir(rid) / name
    except KeyError:
        raise HTTPException(404, "No such reel")
    if not p.exists():
        raise HTTPException(404, "Not ready yet")
    return FileResponse(p, media_type="image/jpeg")


@router.post("/api/reels/{rid}/cancel")
def cancel(rid: str):
    try:
        rdir(rid)
    except KeyError:
        raise HTTPException(404, "No such reel")
    update(rid, status="cancelled", phase="Cancelled")
    kill(rid)
    return {"ok": True}


@router.post("/api/reels/{rid}/retry")
def retry(rid: str, replan: bool = False):
    try:
        d = rdir(rid)
    except KeyError:
        raise HTTPException(404, "No such reel")
    if read_meta(rid).get("status") in BUSY:
        raise HTTPException(409, "This reel is already being edited")
    if replan and (d / "edit_plan.json").exists():
        (d / "edit_plan.json").unlink()
    update(rid, status="queued", phase="Waiting to start", error=None)
    log(rid, "app", "Retrying" + (" with a new plan" if replan else " (reusing the saved AI plan, no new tokens)"))
    enqueue(rid)
    return {"ok": True}


def _editable(rid: str) -> Path:
    try:
        d = rdir(rid)
    except KeyError:
        raise HTTPException(404, "No such reel")
    if read_meta(rid).get("status") in BUSY:
        raise HTTPException(409, "This reel is being edited right now. Wait until it finishes.")
    if not (d / "edit_plan.json").exists() or not (d / "words.json").exists():
        raise HTTPException(409, "This reel has no edit yet. Press Retry first.")
    return d


@router.get("/api/reels/{rid}/words")
def words_api(rid: str):
    try:
        d = rdir(rid)
    except KeyError:
        raise HTTPException(404, "No such reel")
    if not (d / "words.json").exists() or not (d / "edit_plan.json").exists() or read_meta(rid).get("style") == "product":
        return []
    return word_state(d)


@router.post("/api/reels/{rid}/edit")
def edit_words(rid: str, body: dict):
    """Spelling fixes and cut / bring back words, straight from the page. No AI call; only these words change."""
    d = _editable(rid)
    if read_meta(rid).get("style") == "product":
        raise HTTPException(409, "Product reels are changed with Ask for a change.")
    plan = json.loads((d / "edit_plan.json").read_text(encoding="utf-8"))
    W = json.loads((d / "words.json").read_text(encoding="utf-8"))
    fix = dict(body.get("fix") or {})
    if body.get("everywhere"):           # same misheard word elsewhere gets the same spelling
        cur = {w["i"]: w["w"] for w in word_state(d)}
        for k, v in list(fix.items()):
            if str(k).isdigit() and int(k) in cur:
                same = cur[int(k)].strip(".,!?").lower()
                fix.update({str(i): v + (t[-1] if t[-1:] in ".,!?" and v[-1:] not in ".,!?" else "")
                            for i, t in cur.items() if t.strip(".,!?").lower() == same})
    ensure_first_version(d)
    done = apply_edits(plan, len(W), fix, body.get("cut"), body.get("keep"))
    if not done:
        raise HTTPException(400, "Nothing to change")
    save_plan(d, plan)
    update(rid, status="queued", phase="Waiting to start", error=None, last_changes=done, question=None,
           version_label="; ".join(done))
    for x in done:
        log(rid, "app", x)
    enqueue(rid)
    return {"ok": True, "changes": done}


@router.post("/api/reels/{rid}/revise")
def revise(rid: str, body: dict):
    """A change request in plain words. One small AI call turns it into a change set; only that changes."""
    d = _editable(rid)
    req = str(body.get("request") or "").strip()
    if not req:
        raise HTTPException(400, "Write what you want changed")
    rng = None
    if body.get("t0") is not None and body.get("t1") is not None and str(body.get("t0")) != "" and str(body.get("t1")) != "":
        try:
            t0, t1 = sorted((max(0.0, float(body["t0"])), max(0.0, float(body["t1"]))))
        except (TypeError, ValueError):
            raise HTTPException(400, "The time range must be two numbers of seconds")
        rng = [round(t0, 2), round(max(t1, t0 + 0.2), 2)]
    ensure_first_version(d)
    update(rid, status="queued", phase="Waiting to start", error=None, pending_revision=req[:1000], pending_range=rng,
           question=None, last_changes=[])
    log(rid, "app", "Change requested" + (f" for {fmt_t(rng[0])}-{fmt_t(rng[1])}" if rng else "") + ": " + req[:300])
    enqueue(rid)
    return {"ok": True}


@router.get("/api/reels/{rid}/versions")
def versions_api(rid: str):
    try:
        d = rdir(rid)
    except KeyError:
        raise HTTPException(404, "No such reel")
    return {"current": read_meta(rid).get("version"), "versions": versions(d)}


@router.post("/api/reels/{rid}/restore/{n}")
def restore(rid: str, n: int):
    """Go back to an earlier version: its plan and its videos, instantly (no re-render)."""
    d = _editable(rid)
    vd = d / "versions" / f"v{int(n)}"
    if not (vd / "edit_plan.json").exists():
        raise HTTPException(404, "No such version")
    shutil.copy2(vd / "edit_plan.json", d / "edit_plan.json")
    if (vd / "stable.json").exists():
        shutil.copy2(vd / "stable.json", d / "stable.json")
    (d / "out").mkdir(exist_ok=True)
    for f in ("reel.mp4", "reel-master.mp4"):
        if (vd / f).exists():
            shutil.copy2(vd / f, d / "out" / f)
    label = next((v["label"] for v in versions(d) if v["n"] == int(n)), "")
    update(rid, version=int(n), question=None)
    log(rid, "app", f"Back to version {n}" + (f" ({label})" if label else ""))
    return {"ok": True}


@router.post("/api/reels/{rid}/retranscribe")
def retranscribe(rid: str, body: dict | None = None):
    """Start this reel again from the transcript (new word timings, new AI plan). Earlier versions are kept."""
    try:
        d = rdir(rid)
    except KeyError:
        raise HTTPException(404, "No such reel")
    if read_meta(rid).get("status") in BUSY:
        raise HTTPException(409, "This reel is being edited right now. Wait until it finishes.")
    ensure_first_version(d)
    for f in ("words.json", "edit_plan.json", "cut_report.json"):
        if (d / f).exists():
            (d / f).unlink()
    body = body or {}
    update(rid, script=body.get("script") if body.get("script") in CAPTION_SCRIPTS else "english",
           cut_mode=body.get("cut_mode") if body.get("cut_mode") in CUT_MODES else "gaps")
    update(rid, status="queued", phase="Waiting to start", error=None, last_changes=["Transcribed again"],
           version_label="Transcribed again", question=None)
    log(rid, "app", "Transcribing again with the new word-by-word transcriber")
    enqueue(rid)
    return {"ok": True}


@router.delete("/api/reels/{rid}")
def delete(rid: str):
    try:
        d = rdir(rid)
    except KeyError:
        raise HTTPException(404, "No such reel")
    kill(rid)
    shutil.rmtree(d, ignore_errors=True)
    return {"ok": True}
