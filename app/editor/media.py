"""Thin wrappers around ffprobe/ffmpeg."""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable

from .config import find_tool

# Keep a console window from flashing up on Windows for every ffmpeg call.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class MediaInfo:
    duration: float
    width: int          # display width, after rotation
    height: int         # display height, after rotation
    fps: float
    has_audio: bool

    @property
    def vertical(self) -> bool:
        return self.height > self.width


def probe(path: str | Path) -> MediaInfo:
    out = subprocess.run(
        [find_tool("ffprobe"), "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, check=True, creationflags=_NO_WINDOW,
    ).stdout
    data = json.loads(out)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError("This file has no video stream.")
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    w, h = int(video["width"]), int(video["height"])
    rotation = 0
    for sd in video.get("side_data_list", []) or []:
        if "rotation" in sd:
            rotation = int(float(sd["rotation"]))
    if not rotation:
        rotation = int(float(video.get("tags", {}).get("rotate", 0) or 0))
    if abs(rotation) % 180 == 90:      # phone videos are often stored sideways
        w, h = h, w

    fps = 30.0
    rate = video.get("avg_frame_rate") or video.get("r_frame_rate") or "30/1"
    try:
        num, den = rate.split("/")
        if float(den):
            fps = float(num) / float(den)
    except ValueError:
        pass

    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
    return MediaInfo(duration=duration, width=w, height=h, fps=fps, has_audio=has_audio)


@lru_cache(maxsize=1)
def ffmpeg_major_version() -> int:
    out = subprocess.run([find_tool("ffmpeg"), "-version"], capture_output=True, text=True,
                         creationflags=_NO_WINDOW).stdout
    m = re.search(r"ffmpeg version n?(\d+)", out)
    return int(m.group(1)) if m else 6


def filter_script_args(script_name: str) -> list[str]:
    """ffmpeg 7+ reads a filtergraph from a file with -/filter_complex; older builds use -filter_complex_script."""
    if ffmpeg_major_version() >= 7:
        return ["-/filter_complex", script_name]
    return ["-filter_complex_script", script_name]


def run_ffmpeg(args: list[str], cwd: Path, expected_duration: float,
               on_progress: Callable[[float], None] | None = None) -> None:
    """Run ffmpeg, reporting progress as a 0..1 fraction. Raises RuntimeError with the log tail on failure."""
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-y", "-nostdin", "-progress", "pipe:1", "-nostats", *args]
    proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
    stderr_lines: list[str] = []

    import threading

    def drain_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_lines.append(line)
            if len(stderr_lines) > 200:
                del stderr_lines[:100]

    t = threading.Thread(target=drain_stderr, daemon=True)
    t.start()
    assert proc.stdout is not None
    for line in proc.stdout:
        key, _, value = line.strip().partition("=")
        if key == "out_time_us" and on_progress and expected_duration > 0:
            try:
                on_progress(min(1.0, int(value) / 1e6 / expected_duration))
            except ValueError:
                pass
    proc.wait()
    t.join(timeout=5)
    if proc.returncode != 0:
        tail = "".join(stderr_lines[-25:])
        raise RuntimeError(f"ffmpeg failed (exit {proc.returncode}):\n{tail}")
