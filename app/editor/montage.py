"""Beat-synced cinematic montage (Beat-Sync Cinematic Edit skill, style by @shakirc.ai).

A folder of clips + one song -> a ~20 s 9:16 reel: cuts on the bars, the biggest transition on the drop,
eased speed ramps with frame blending, smooth transitions only (dissolve, focus-blur, zoom-through on the drop;
never slides, spins, glitches or white flashes), effects only at key transitions with the music ducked 4.5 dB
under each, mastered to about -8 LUFS / -1 dBTP.

Everything is plain numpy + ffmpeg (no librosa/OpenCV needed). The plan is written to edit.json before rendering,
and every render is kept as montage_vN.mp4 next to the earlier ones.

data/montages/<id>/
    meta.json       name, status, progress, clips, song, settings
    clip_<k>.<ext>  uploaded clips          song.<ext>  the song
    analysis.json   beat grid + clip motion  edit.json   the timeline (one entry per segment)
    montage_vN.mp4  renders                  sheet_vN.jpg contact sheet of each render (4 fps)
"""
from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
import time
import traceback
import uuid
from pathlib import Path

import numpy as np

from . import sfx
from .config import DATA_DIR, find_tool
from .media import filter_script_args, probe, run_ffmpeg
from .render import find_lut, grade_chain

MONTAGES_DIR = DATA_DIR / "montages"
W, H, FPS = 1080, 1920, 30
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_lock = threading.Lock()
_queue: "queue.Queue[str]" = queue.Queue()
_worker: threading.Thread | None = None

TRANSITIONS = {"fade": 0.5, "hblur": 0.4, "zoomin": 0.5}   # soft dissolve, focus-blur, zoom-through (drop only)


# ---------- song analysis ----------

def decode_mono(path: Path, sr: int = 22050) -> np.ndarray:
    out = subprocess.run([find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(path),
                          "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "pipe:1"],
                         capture_output=True, check=True, creationflags=_NO_WINDOW).stdout
    return np.frombuffer(out, dtype=np.float32).astype(np.float64)


def analyze_song(path: Path, sr: int = 22050) -> dict:
    """Beat grid from spectral flux: tempo by autocorrelation, beats by comb phase, bars from the kick band,
    a 'start' that skips a slow intro, and the drop (the biggest rise in energy)."""
    y = decode_mono(path, sr)
    if y.size < sr * 4:
        raise ValueError("The song is too short (needs at least a few seconds).")
    n_fft, hop = 2048, 512
    n = 1 + (y.size - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n)[:, None]
    frames = y[idx] * np.hanning(n_fft)[None, :]
    mag = np.abs(np.fft.rfft(frames, axis=1))
    logm = np.log1p(10 * mag)
    d = np.maximum(0, np.diff(logm, axis=0, prepend=logm[:1]))
    freqs = np.fft.rfftfreq(n_fft, 1 / sr)
    onset = d.sum(axis=1)
    kick = d[:, freqs < 150].sum(axis=1)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    fr = sr / hop
    onset = (onset - onset.mean()) / (onset.std() + 1e-9)
    kick_n = (kick - kick.mean()) / (kick.std() + 1e-9)
    onset = np.convolve(onset, np.ones(3) / 3, mode="same")
    # Beat phase follows the kick (hi-hats often sit on the off-beats); tempo uses everything.
    phase_env = np.convolve(kick_n + 0.3 * onset, np.ones(3) / 3, mode="same")

    # Tempo: autocorrelation of the onset envelope, 70-180 BPM, gently preferring ~120 BPM.
    lo, hi = int(fr * 60 / 180), int(fr * 60 / 70) + 1
    ac = np.correlate(onset, onset, mode="full")[onset.size - 1:]
    lags = np.arange(lo, hi)
    bpm_l = 60 * fr / lags
    weight = np.exp(-0.5 * (np.log2(bpm_l / 120) / 0.9) ** 2)
    k = lo + int(np.argmax(ac[lo:hi] * weight))
    if 1 <= k < ac.size - 1:                       # parabolic refinement of the peak
        a_, b_, c_ = ac[k - 1], ac[k], ac[k + 1]
        period = k + 0.5 * (a_ - c_) / (a_ - 2 * b_ + c_ + 1e-12)
    else:
        period = float(k)
    bpm = 60 * fr / period

    # Beat phase: the offset whose comb catches the most onset energy; then snap each beat to a local peak.
    offsets = np.arange(int(period))
    score = [phase_env[np.round(o + period * np.arange(int((n - o) / period))).astype(int)].sum() for o in offsets]
    off = int(offsets[int(np.argmax(score))])
    # A steady grid (no drift through quiet intros); each beat snaps to a nearby peak only if there is one.
    w = max(1, int(period * 0.1))
    beats = []
    for k in range(int((n - 1 - off) / period) + 1):
        p = int(round(off + k * period))
        a, b = max(0, p - w), min(n, p + w + 1)
        q = a + int(np.argmax(phase_env[a:b]))
        beats.append(q if phase_env[q] > 1.0 else p)
    beats = np.array(beats)
    beat_t = beats / fr + (n_fft / 2 + hop / 2) / sr      # frame index -> time of the attack
    # Downbeats: the beat phase (of 4) with the strongest kick.
    # (linear low-band energy, so an accented beat 1 wins over equal-looking flux peaks)
    low = mag[:, freqs < 150].sum(axis=1)
    peak_low = np.array([low[max(0, q - 1):q + 3].max() for q in beats])
    phase = int(np.argmax([peak_low[p::4].sum() for p in range(4)])) if beats.size >= 8 else 0
    bars = beat_t[phase::4]
    if bars.size < 3:
        raise ValueError("Couldn't find a steady beat in this song.")
    bar_len = float(np.median(np.diff(bars)))
    energy = np.array([rms[int(bars[i] * fr):int((bars[i] + bar_len) * fr)].mean() if int(bars[i] * fr) < n else 0
                       for i in range(bars.size)])
    med = float(np.median(energy)) or 1e-9
    start_i = int(next((i for i, e in enumerate(energy) if e >= 0.6 * med), 0))
    rise = [(energy[i:i + 2].mean() - energy[max(0, i - 2):i].mean(), i) for i in range(start_i + 2, bars.size - 1)]
    drop_i = max(rise)[1] if rise else min(bars.size - 1, start_i + 3)
    return {"bpm": round(float(bpm), 1), "bar": round(bar_len, 3), "beats": [round(float(t), 3) for t in beat_t],
            "bars": [round(float(t), 3) for t in bars], "start": round(float(bars[start_i]), 3),
            "drop": round(float(bars[drop_i]), 3), "duration": round(y.size / sr, 2)}


# ---------- clip analysis ----------

def _gray_frames(path: Path, fps: float | None, width: int = 96, seconds: float | None = None) -> np.ndarray:
    vf = (f"fps={fps}," if fps else "") + f"scale={width}:-2,format=gray"
    args = [find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(path)]
    if seconds:
        args += ["-t", f"{seconds}"]
    args += ["-vf", vf, "-f", "rawvideo", "pipe:1"]
    raw = subprocess.run(args, capture_output=True, check=True, creationflags=_NO_WINDOW).stdout
    info = probe(path)
    h = int(round(width * info.height / info.width / 2)) * 2
    count = len(raw) // (width * h)
    return np.frombuffer(raw[:count * width * h], np.uint8).reshape(count, h, width).astype(np.float32)


def analyze_clip(path: Path) -> dict:
    """Duration, fps, where the action is (motion energy) and whether it's 30p doubled into 60p."""
    info = probe(path)
    f = _gray_frames(path, 6)
    motion = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2)) if len(f) > 1 else np.zeros(1)
    win = max(1, int(1.5 * 6))
    sm = np.convolve(motion, np.ones(win) / win, mode="same")
    peak = float((int(np.argmax(sm)) + 1) / 6) if sm.size else info.duration / 2
    doubled = False
    if info.fps >= 50:
        g = _gray_frames(path, None, 64, seconds=2)
        if len(g) > 4:
            dd = np.abs(np.diff(g, axis=0)).mean(axis=(1, 2))
            doubled = bool(np.mean(dd < 0.15 * (np.percentile(dd, 90) + 1e-6)) > 0.35)
    return {"duration": round(info.duration, 3), "fps": round(info.fps, 3), "width": info.width,
            "height": info.height, "motion": round(float(motion.mean()), 3), "peak": round(peak, 2),
            "doubled": doubled}


# ---------- planning ----------

def smoothstep(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def source_span(length: float, a: float, b: float) -> float:
    """Seconds of source used by an eased ramp from speed a to speed b over `length` output seconds."""
    return length * (a + b) / 2


def plan_montage(song: dict, clips: list[dict], length: float = 20.0) -> dict:
    """Write the timeline: one bar-aligned segment per clip (never a repeat), the hero clip on the drop."""
    bar = song["bar"]
    unit = bar if 1.2 <= bar <= 3.2 else (bar * 2 if bar < 1.2 else bar / 2)
    grid = [song["start"]]
    while grid[-1] + unit <= song["duration"] - 0.5:
        grid.append(round(grid[-1] + unit, 3))
    # Keep the drop inside the reel: start later (on the grid) if the drop is too far in.
    if song["drop"] - grid[0] > length * 0.7:
        start = max(t for t in grid if t <= song["drop"] - length * 0.35)
        grid = [t for t in grid if t >= start]
    slots_n = max(2, min(len(grid) - 1, int(round(length / unit))))
    n = len(clips)
    if n == 0:
        raise ValueError("Add some clips first.")
    order = list(range(n))
    hero = int(np.argmax([c["motion"] for c in clips]))
    drop_rel = song["drop"] - grid[0]
    # Bars per clip: one each, extra bars go to the most active clips (max 3 bars each).
    units = [1] * min(n, slots_n)
    used = order[:slots_n]
    if hero not in used:
        used[-1] = hero
    extra = slots_n - len(used)
    by_motion = sorted(range(len(used)), key=lambda i: -clips[used[i]]["motion"])
    i = 0
    while extra > 0 and by_motion:
        j = by_motion[i % len(by_motion)]
        if units[j] < 3:
            units[j] += 1
            extra -= 1
        i += 1
        if i > 10 * len(by_motion):
            break
    # Put the hero clip on the segment that starts closest to the drop.
    starts = np.cumsum([0] + units[:-1]) * unit
    target = int(np.argmin(np.abs(starts - drop_rel)))
    hi = used.index(hero)
    used[hi], used[target] = used[target], used[hi]
    units[hi], units[target] = units[target], units[hi]
    # Move bars between segments (total unchanged) so the hero clip starts exactly on the drop's bar.
    hpos = target
    want = int(round(drop_rel / unit))
    for _ in range(4 * slots_n):
        before = sum(units[:hpos])
        if before == want:
            break
        if before > want:
            pre = [i for i in range(hpos) if units[i] > 1]
            post = [i for i in range(hpos, len(units)) if units[i] < 3]
            if not pre or not post:
                break
            units[pre[-1]] -= 1
            units[post[0]] += 1
        else:
            pre = [i for i in range(hpos) if units[i] < 3]
            post = [i for i in range(hpos, len(units)) if units[i] > 1]
            if not pre or not post:
                break
            units[pre[-1]] += 1
            units[post[-1]] -= 1
    starts = np.cumsum([0] + units[:-1]) * unit
    total = float(sum(units) * unit)

    segs = []
    cut_points = [float(s) for s in starts[1:]]
    drop_cut = min(cut_points, key=lambda c: abs(c - drop_rel)) if cut_points else None
    kinds = ["fade", "hblur"]
    for k, (ci, u) in enumerate(zip(used, units)):
        c0, c1 = float(starts[k]), float(starts[k] + u * unit)
        t_in = 0.0 if k == 0 else TRANSITIONS[("zoomin" if abs(c0 - (drop_cut or -9)) < 1e-6 else kinds[k % 2])]
        t_out = 0.0 if k == len(used) - 1 else TRANSITIONS[("zoomin" if abs(c1 - (drop_cut or -9)) < 1e-6 else kinds[(k + 1) % 2])]
        out_len = (c1 - c0) + t_in / 2 + t_out / 2
        clip = clips[ci]
        is_hero = ci == hero
        # Speed: plenty of slow-mo. Hero: eased ramp into deep slow-mo; others alternate.
        if is_hero:
            a, b = 1.0, 0.3
        elif k % 2 == 0:
            a, b = 0.6, 0.6
        else:
            a, b = 1.0, 0.5
        span = source_span(out_len, a, b)
        if span > clip["duration"] - 0.1:            # clip too short: slow it down further (down to 0.2x)
            scale = max(0.2 / max(a, b), (clip["duration"] - 0.1) / span)
            a, b = round(a * scale, 3), round(b * scale, 3)
            span = source_span(out_len, a, b)
        src_in = float(np.clip(clip["peak"] - span / 2, 0, max(0.0, clip["duration"] - span - 0.05)))
        segs.append({"clip": ci, "name": clip.get("name", f"clip {ci + 1}"), "start": round(c0, 3),
                     "end": round(c1, 3), "out_len": round(out_len, 3), "in": round(src_in, 3),
                     "span": round(span, 3), "speed": [a, b], "zoom": bool(is_hero),
                     # 30p doubled into 60p: use every other frame; otherwise keep up to 60 fps for clean slow-mo
                     "src_fps": 30 if clip.get("doubled") else int(min(60, max(24, round(clip.get("fps", 30))))),
                     "transition_in": None if k == 0 else ("zoomin" if abs(c0 - (drop_cut or -9)) < 1e-6 else kinds[k % 2]),
                     "transition_in_s": t_in, "hero": is_hero})
    # Effects only at key transitions: the drop gets whoosh + hit, every other blur transition a soft whoosh.
    fx = []
    for k, s in enumerate(segs[1:], 1):
        if s["transition_in"] == "zoomin":
            fx += [{"t": s["start"], "kind": "whoosh", "what": "zoom-through on the drop"},
                   {"t": round(s["start"] + 0.02, 3), "kind": "hit", "what": "drop lands"}]
        elif s["transition_in"] == "hblur" and k % 4 == 1:
            fx.append({"t": s["start"], "kind": "whoosh_soft", "what": "focus-blur transition"})
    return {"song_start": grid[0], "length": round(total, 3), "bpm": song["bpm"], "bar": unit,
            "drop": round(drop_rel, 3), "segments": segs, "sfx": fx,
            "unused_clips": [clips[i].get("name", f"clip {i + 1}") for i in range(n) if i not in used]}


# ---------- render ----------

def speed_expr(out_len: float, a: float, b: float, knots: int = 12) -> str:
    """setpts expression mapping source time T -> output time for an eased speed ramp a -> b (piecewise linear)."""
    if abs(a - b) < 1e-6:
        return f"T/{a:.4f}"
    t = np.linspace(0, out_len, 400)
    s = a + (b - a) * smoothstep(t / out_len)
    u = np.concatenate([[0], np.cumsum((s[1:] + s[:-1]) / 2 * np.diff(t))])
    tk = np.linspace(0, out_len, knots + 1)
    uk = np.interp(tk, t, u)
    expr = f"{tk[-1]:.4f}+(T-{uk[-1]:.4f})/{b:.4f}"
    for j in range(knots - 1, -1, -1):
        slope = (tk[j + 1] - tk[j]) / max(1e-6, uk[j + 1] - uk[j])
        expr = f"if(lt(T,{uk[j + 1]:.4f}),{tk[j]:.4f}+(T-{uk[j]:.4f})*{slope:.5f},{expr})"
    return expr


def measure_lufs(path: Path) -> float | None:
    import re
    err = subprocess.run([find_tool("ffmpeg"), "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128",
                          "-f", "null", "-"], capture_output=True, text=True, creationflags=_NO_WINDOW).stderr
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    return float(m[-1]) if m else None


def build_graph(plan: dict, grade: str, lut: str | None, bed_input: int, draft: bool,
                gain_db: float = 0.0) -> str:
    w, h = (540, 960) if draft else (W, H)
    segs = plan["segments"]
    parts = []
    g = grade_chain(grade, lut) if grade != "none" else None
    for k, s in enumerate(segs):
        a, b = s["speed"]
        chain = (f"[{k}:v]setpts=PTS-STARTPTS,fps={s.get('src_fps', 60)},setpts='({speed_expr(s['out_len'], a, b)})/TB',"
                 f"framerate=fps={FPS}:interp_start=0:interp_end=255:scene=100")
        if g:
            chain += "," + g
        chain += f",scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
        if s.get("zoom"):          # subtle push-in on the hero shot only
            frames = max(1, int(s["out_len"] * FPS))
            chain += f",zoompan=z='1+0.05*on/{frames}':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d=1:s={w}x{h}:fps={FPS}"
        chain += f",setsar=1,trim=duration={s['out_len']:.3f},setpts=PTS-STARTPTS,fps={FPS},format=yuv420p"
        if k == 0:
            chain += ",fade=t=in:st=0:d=0.3"
        if k == len(segs) - 1:
            chain += f",fade=t=out:st={max(0, s['out_len'] - 0.8):.3f}:d=0.8"
        parts.append(chain + ",settb=AVTB" + f"[s{k}]")
    cur = "s0"
    for k, s in enumerate(segs[1:], 1):
        d = s["transition_in_s"]
        off = s["start"] - d / 2
        parts.append(f"[{cur}][s{k}]xfade=transition={s['transition_in']}:duration={d:.3f}:offset={off:.3f}[x{k}]")
        cur = f"x{k}"
    parts.append(f"[{cur}]format=yuv420p[vout]")
    # Master loud (about -8 LUFS) with a limiter that keeps true peaks under -1 dBTP.
    parts.append(f"[{bed_input}:a]volume={gain_db:.2f}dB,alimiter=limit=0.84:attack=5:release=50:level=0,"
                 f"aresample=48000[aout]")
    return ";\n".join(parts) + "\n"


def build_audio(path: Path, song_path: Path, plan: dict) -> Path:
    """Song from the chosen bar + effects; the music dips 4.5 dB under each effect."""
    n = int(round(plan["length"] * sfx.SR))
    raw = subprocess.run([find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
                          "-ss", f"{plan['song_start']:.3f}", "-i", str(song_path), "-t", f"{plan['length']:.3f}",
                          "-vn", "-f", "f32le", "-ac", "2", "-ar", str(sfx.SR), "pipe:1"],
                         capture_output=True, check=True, creationflags=_NO_WINDOW).stdout
    m = np.frombuffer(raw, np.float32).reshape(-1, 2).astype(np.float64)[:n]
    if m.shape[0] < n:
        m = np.vstack([m, np.zeros((n - m.shape[0], 2))])
    style = {"whoosh_ms": 450, "whoosh_hz": 800, "sfx_db": 0}
    duck = [(max(0.0, e["t"] - 0.3), e["t"] + 0.35) for e in plan["sfx"]]
    env = sfx.duck_envelope(n, duck, 0.0, 4.5, attack=0.08, release=0.25)
    fade = min(n, int(sfx.SR * 1.0))
    env[n - fade:] *= np.linspace(1, 0, fade)
    track = m * env[:, None]
    for e in plan["sfx"]:
        clip = sfx.effect(e["kind"], style)
        sfx.place(track, clip, e["t"] - sfx.sfx_offset(e["kind"], style), 10 ** (sfx.LEVELS[e["kind"]] / 20))
    sfx.write_wav(path, track)
    return path


# ---------- jobs ----------

def mdir(mid: str) -> Path:
    if not mid.isalnum():
        raise KeyError(mid)
    d = MONTAGES_DIR / mid
    if not d.is_dir():
        raise KeyError(mid)
    return d


def read_meta(mid: str) -> dict:
    with _lock:
        return json.loads((mdir(mid) / "meta.json").read_text(encoding="utf-8"))


def update_meta(mid: str, **changes) -> dict:
    with _lock:
        p = MONTAGES_DIR / mid / "meta.json"
        meta = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        meta.update(changes)
        meta["updated"] = time.time()
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(p)
        return meta


def create(name: str) -> dict:
    mid = uuid.uuid4().hex[:12]
    (MONTAGES_DIR / mid).mkdir(parents=True)
    return update_meta(mid, id=mid, name=name[:60] or "Montage", created=time.time(), status="new", progress=0.0,
                       clips=[], song=None, settings={"length": 20, "grade": "none"}, versions=[], error=None)


def list_all() -> list[dict]:
    if not MONTAGES_DIR.exists():
        return []
    out = []
    for d in MONTAGES_DIR.iterdir():
        if (d / "meta.json").exists():
            try:
                out.append(read_meta(d.name))
            except (OSError, ValueError, KeyError):
                pass
    return sorted(out, key=lambda m: m.get("created", 0), reverse=True)


def add_clip(mid: str, src: Path, name: str) -> dict:
    d = mdir(mid)
    info = analyze_clip(src)
    key = uuid.uuid4().hex[:6]
    dest = d / f"clip_{key}{src.suffix.lower()}"
    src.replace(dest)
    meta = read_meta(mid)
    clips = meta["clips"] + [{"file": dest.name, "name": Path(name).name[:80], **info}]
    return update_meta(mid, clips=clips, plan_stale=True)


def remove_clip(mid: str, file: str) -> dict:
    d = mdir(mid)
    meta = read_meta(mid)
    clips = [c for c in meta["clips"] if c["file"] != file]
    if len(clips) != len(meta["clips"]):
        (d / file).unlink(missing_ok=True)
    return update_meta(mid, clips=clips, plan_stale=True)


def set_song(mid: str, src: Path, name: str) -> dict:
    d = mdir(mid)
    for old in d.glob("song.*"):
        old.unlink()
    dest = d / f"song{src.suffix.lower()}"
    src.replace(dest)
    analysis = analyze_song(dest)
    (d / "analysis.json").write_text(json.dumps(analysis), encoding="utf-8")
    return update_meta(mid, song={"file": dest.name, "name": Path(name).name[:80], "bpm": analysis["bpm"],
                                  "start": analysis["start"], "drop": analysis["drop"],
                                  "duration": analysis["duration"]}, plan_stale=True)


def make_plan(mid: str, length: float | None = None, grade: str | None = None) -> dict:
    d = mdir(mid)
    meta = read_meta(mid)
    if not meta.get("song"):
        raise ValueError("Add a song first.")
    settings = dict(meta.get("settings") or {})
    if length is not None:
        settings["length"] = float(min(40, max(8, length)))
    if grade in ("none", "cinematic", "look01"):
        settings["grade"] = grade
    song = json.loads((d / "analysis.json").read_text(encoding="utf-8"))
    plan = plan_montage(song, meta["clips"], float(settings.get("length", 20)))
    (d / "edit.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")
    update_meta(mid, settings=settings, plan_stale=False)
    return plan


def load_plan(mid: str) -> dict | None:
    p = mdir(mid) / "edit.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def enqueue(mid: str, draft: bool = False) -> dict:
    meta = update_meta(mid, status="render queued", progress=0.0, error=None, draft=draft)
    _queue.put(mid)
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_loop, name="montage-worker", daemon=True)
        _worker.start()
    return meta


def _loop() -> None:
    while True:
        mid = _queue.get()
        try:
            render_montage(mid)
        except Exception as exc:
            traceback.print_exc()
            update_meta(mid, status="error", error=str(exc))
        finally:
            _queue.task_done()


def render_montage(mid: str) -> Path:
    d = mdir(mid)
    meta = read_meta(mid)
    if meta.get("plan_stale") or not (d / "edit.json").exists():
        make_plan(mid)
        meta = read_meta(mid)
    plan = load_plan(mid)
    draft = bool(meta.get("draft"))
    update_meta(mid, status="rendering", progress=0.0)
    grade = (meta.get("settings") or {}).get("grade", "none")
    lut = None
    if grade == "look01":
        src = find_lut()
        if src is None:
            raise ValueError("Look 01 needs its LUT file in app\\luts.")
        lut = "look01.cube"
        if not (d / lut).exists():
            shutil.copyfile(src, d / lut)
    args = []
    for s in plan["segments"]:
        clip = meta["clips"][s["clip"]]
        args += ["-ss", f"{s['in']:.3f}", "-t", f"{s['span'] + 0.3:.3f}", "-i", clip["file"]]
    build_audio(d / "mix.wav", d / meta["song"]["file"], plan)
    args += ["-i", "mix.wav"]
    lufs = measure_lufs(d / "mix.wav")
    gain = min(18.0, max(-12.0, -8.0 - lufs)) if lufs is not None else 0.0
    graph = build_graph(plan, grade, lut, len(plan["segments"]), draft, gain)
    (d / "filtergraph.txt").write_text(graph, encoding="utf-8")
    versions = meta.get("versions") or []
    v = len(versions) + 1
    out = f"montage_v{v}{'_draft' if draft else ''}.mp4"
    args += [*filter_script_args("filtergraph.txt"), "-map", "[vout]", "-map", "[aout]",
             "-c:v", "libx264", "-preset", "ultrafast" if draft else "medium", "-crf", "28" if draft else "18",
             "-maxrate", "8M", "-bufsize", "16M", "-pix_fmt", "yuv420p", "-r", str(FPS),
             "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", "-t", f"{plan['length']:.3f}", out]

    def prog(p: float) -> None:
        update_meta(mid, progress=round(p, 3))

    run_ffmpeg(args, cwd=d, expected_duration=plan["length"], on_progress=prog)
    sheet = f"sheet_v{v}.jpg"
    subprocess.run([find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-i", out, "-vf",
                    "fps=4,scale=108:192,tile=20x4", "-frames:v", "1", sheet], cwd=str(d), creationflags=_NO_WINDOW)
    shutil.copyfile(d / "edit.json", d / f"edit_v{v}.json")
    versions.append({"v": v, "file": out, "sheet": sheet, "draft": draft, "time": time.time(),
                     "length": plan["length"], "grade": grade})
    update_meta(mid, status="done", progress=1.0, versions=versions)
    return d / out
