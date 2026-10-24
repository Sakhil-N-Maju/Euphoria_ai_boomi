"""Sound design from code (Sound Design skill): every effect is synthesised with numpy, no sample packs.

Change a sound by changing its parameters here (or in the Style panel / chat: "make the whoosh shorter
and deeper"), then re-render. The "bed" is one audio track holding the music (ducked under the voice) and
every effect at its exact time; the renderer mixes it under the voice.
"""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np

from .config import find_tool

SR = 48000
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Peak level of each effect before the overall SFX trim, in dBFS. Effects peak just under the voice;
# keyword ticks are much quieter because they are frequent.
LEVELS = {"whoosh": -9.0, "whoosh_soft": -15.0, "pop": -10.0, "tick": -22.0, "hit": -7.0, "key": -20.0}


def _db(x: float) -> float:
    return 10 ** (x / 20)


def _norm(x: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    return x / peak if peak > 0 else x


def _svf_bandpass(x: np.ndarray, freqs: np.ndarray, q: float) -> np.ndarray:
    """State-variable band-pass whose centre frequency follows `freqs` sample by sample."""
    y = np.empty_like(x)
    low = band = 0.0
    damp = 1.0 / q
    f = 2 * np.sin(np.pi * np.clip(freqs, 20, SR / 6) / SR)
    for n in range(x.size):
        high = x[n] - low - damp * band
        band += f[n] * high
        low += f[n] * band
        y[n] = band
    return y


def _onepole_lowpass(x: np.ndarray, cutoff: np.ndarray | float) -> np.ndarray:
    cutoff = np.broadcast_to(np.asarray(cutoff, dtype=float), x.shape)
    a = np.exp(-2 * np.pi * np.clip(cutoff, 20, SR / 2.2) / SR)
    y = np.empty_like(x)
    acc = 0.0
    for n in range(x.size):
        acc = (1 - a[n]) * x[n] + a[n] * acc
        y[n] = acc
    return y


def whoosh(ms: float = 400, hz: float = 900, seed: int = 7) -> np.ndarray:
    """Band-passed noise, pitch sweeping down, swell then fade, low-pass closing at the tail."""
    n = int(SR * ms / 1000)
    t = np.linspace(0, 1, n, endpoint=False)
    noise = np.random.default_rng(seed).standard_normal(n)
    freqs = hz * 1.7 * (0.35 / 1.7) ** t                # sweep from 1.7x down to 0.35x the centre
    y = _svf_bandpass(_svf_bandpass(noise, freqs, q=1.2), freqs, q=1.2)   # 4-pole band-pass: airy, not hissy
    y = _onepole_lowpass(y, freqs * 3 * (1 - 0.7 * t ** 1.5))             # the low-pass closes at the tail
    env = np.where(t < 0.6, (t / 0.6) ** 2, ((1 - t) / 0.4) ** 1.6)
    return _norm(y * env)


def pop(ms: float = 50, f0: float = 780) -> np.ndarray:
    """Short sine burst with a fast pitch drop and an instant decay."""
    n = int(SR * ms / 1000)
    t = np.arange(n) / SR
    f = f0 * (1 - 0.45 * t / (ms / 1000))
    phase = 2 * np.pi * np.cumsum(f) / SR
    env = np.exp(-t / (ms / 1000 / 4.5))
    env[: int(SR * 0.0015)] *= np.linspace(0, 1, int(SR * 0.0015))   # 1.5 ms attack: no click
    return _norm(np.sin(phase) * env)


def tick(ms: float = 20, seed: int = 3) -> np.ndarray:
    """Quiet filtered click, high-passed above ~2 kHz."""
    n = int(SR * ms / 1000)
    t = np.arange(n) / SR
    x = np.random.default_rng(seed).standard_normal(n) * np.exp(-t / (ms / 1000 / 5))
    hp = x - _onepole_lowpass(x, 2200.0)
    return _norm(hp)


def hit(seed: int = 11) -> np.ndarray:
    """Low sine thump (~60 Hz, 200 ms decay) with a short noise transient on top."""
    n = int(SR * 0.45)
    t = np.arange(n) / SR
    f = 75 * np.exp(-t / 0.25) + 50
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.2)
    body[: int(SR * 0.002)] *= np.linspace(0, 1, int(SR * 0.002))
    m = int(SR * 0.018)
    trans = np.zeros(n)
    trans[:m] = _onepole_lowpass(np.random.default_rng(seed).standard_normal(m), 2500.0) * np.linspace(1, 0, m)
    return _norm(body + 0.35 * _norm(trans))


def key(seed: int = 3) -> np.ndarray:
    """Keyboard tap: a short filtered click plus a soft low 'thock' (Reel Editor recipe)."""
    rng = np.random.default_rng(seed)
    n = int(SR * 0.06)
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    click = (noise - _onepole_lowpass(noise, 1500.0)) * np.exp(-t / 0.006)
    click = _onepole_lowpass(click, 6500.0)
    thock = np.sin(2 * np.pi * 240 * t) * np.exp(-t / 0.014) * 0.5
    return _norm(click + thock)


def effect(kind: str, style: dict) -> np.ndarray:
    ms, hz = float(style.get("whoosh_ms", 400)), float(style.get("whoosh_hz", 900))
    if kind == "whoosh":
        return whoosh(ms, hz)
    if kind == "whoosh_soft":
        return whoosh(ms * 0.8, hz * 1.2, seed=9)
    if kind == "pop":
        return pop()
    if kind == "tick":
        return tick()
    if kind == "hit":
        return hit()
    if kind == "key":
        return key()
    raise ValueError(kind)


def place(track: np.ndarray, clip: np.ndarray, at: float, gain: float) -> None:
    start = int(round(at * SR))
    if start >= track.shape[0]:
        return
    if start < 0:
        clip, start = clip[-start:], 0
    end = min(track.shape[0], start + clip.shape[0])
    track[start:end] += clip[: end - start, None] * gain


def sfx_offset(kind: str, style: dict) -> float:
    """Seconds between an effect's start and the moment it should hit the cut."""
    if kind.startswith("whoosh"):
        ms = float(style.get("whoosh_ms", 400)) * (0.8 if kind == "whoosh_soft" else 1.0)
        return 0.6 * ms / 1000          # the whoosh peaks at 60% of its length, right on the cut
    return 0.0


def decode_audio(path: Path, seconds: float) -> np.ndarray:
    """Decode any audio/video file to 48 kHz stereo float32, looped or cut to `seconds`."""
    out = subprocess.run([find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
                          "-stream_loop", "-1", "-i", str(path), "-t", f"{seconds:.3f}", "-vn",
                          "-f", "f32le", "-ac", "2", "-ar", str(SR), "pipe:1"],
                         capture_output=True, check=True, creationflags=_NO_WINDOW).stdout
    data = np.frombuffer(out, dtype=np.float32).reshape(-1, 2).astype(np.float64)
    n = int(round(seconds * SR))
    if data.shape[0] < n:
        data = np.vstack([data, np.zeros((n - data.shape[0], 2))])
    return data[:n]


def duck_envelope(n: int, speech: list[tuple[float, float]], gap_db: float, duck_db: float,
                  attack: float = 0.12, release: float = 0.45) -> np.ndarray:
    """Gain curve for the music: gap_db between phrases, gap_db - duck_db under speech, smooth ramps."""
    target = np.full(n, _db(gap_db))
    low = _db(gap_db - duck_db)
    for s, e in speech:
        a, b = int(max(0, (s - attack) * SR)), int(min(n, e * SR))
        target[a:b] = low
    # Smooth with a moving average about as long as the ramps, so the music never jumps in level.
    k = max(1, int(SR * (attack + release) / 2))
    padded = np.concatenate([np.full(k, target[0]), target, np.full(k, target[-1])])
    c = np.concatenate([[0.0], np.cumsum(padded)])
    smooth = (c[k:] - c[:-k]) / k                      # running mean over k samples (fast for long videos)
    start = k - k // 2
    return smooth[start:start + n]


def build_bed(path: Path, duration: float, events: list[dict], style: dict, music: Path | None,
              speech: list[tuple[float, float]]) -> Path | None:
    """Write the music + effects track. Returns None when there is nothing to put in it."""
    n = int(round(duration * SR))
    if n <= 0:
        return None
    track = np.zeros((n, 2))
    used = False
    if music is not None and music.exists():
        m = decode_audio(music, duration)
        rms = float(np.sqrt(np.mean(m ** 2))) if m.size else 0.0
        if rms > 1e-5:
            m *= _db(-19.0) / rms                         # bring the bed to roughly speech loudness first
            env = duck_envelope(n, speech, float(style.get("music_db", -10)), float(style.get("duck_db", 8)))
            fade = min(n, int(SR * 1.5))                   # fade the music out over the last 1.5 s
            env[n - fade:] *= np.linspace(1, 0, fade)
            track += m * env[:, None]
            used = True
    if style.get("sfx") and events:
        trim = _db(float(style.get("sfx_db", 0)))
        cache: dict[str, np.ndarray] = {}
        for ev in events:
            kind = ev["kind"]
            if kind not in cache:
                cache[kind] = effect(kind, style)
            place(track, cache[kind], ev["t"] - sfx_offset(kind, style), _db(LEVELS[kind]) * trim)
            used = True
    if not used:
        return None
    write_wav(path, track)
    return path


def write_wav(path: Path, data: np.ndarray) -> None:
    if data.ndim == 1:
        data = np.stack([data, data], axis=1)
    pcm = (np.clip(data, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def preview_wav(kind: str, style: dict, path: Path) -> Path:
    """One effect on its own (with a little silence around it) so it can be auditioned on the review page."""
    clip = effect(kind, style) * _db(LEVELS[kind]) * _db(float(style.get("sfx_db", 0)))
    pad = np.zeros(int(SR * 0.15))
    write_wav(path, np.concatenate([pad, clip, pad]))
    return path
