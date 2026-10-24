"""Paths and settings. The app lives in <root>/app; tools and models sit beside it in <root>."""
from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml

APP_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = APP_DIR.parent
DATA_DIR = Path(os.environ.get("EDITOR_DATA_DIR", APP_DIR / "data"))
JOBS_DIR = DATA_DIR / "jobs"
MODELS_DIR = Path(os.environ.get("EDITOR_MODELS_DIR", ROOT_DIR / "models"))
WEB_DIR = APP_DIR / "web"
CONFIG_PATH = APP_DIR / "config.yaml"

_config: dict | None = None


def load_config() -> dict:
    """Return a fresh copy of config.yaml (cached after the first read)."""
    global _config
    if _config is None:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            _config = yaml.safe_load(f) or {}
    return copy.deepcopy(_config)


def env_value(*names: str) -> str | None:
    """First non-empty value among the given names: real environment variables, then app/.env (KEY=VALUE lines)."""
    for name in names:
        if os.environ.get(name):
            return os.environ[name].strip()
    env_file = APP_DIR / ".env"
    if env_file.exists():
        values = {}
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and not key.startswith("#"):
                values[key.strip()] = value.strip().strip('"').strip("'")
        for name in names:
            if values.get(name):
                return values[name]
    return None


def find_tool(name: str) -> str:
    """Locate ffmpeg/ffprobe: env override, then the bundled copy in tools/, then PATH."""
    env = os.environ.get(name.upper())
    if env:
        return env
    exe = name + (".exe" if os.name == "nt" else "")
    bundled = ROOT_DIR / "tools" / "ffmpeg" / "bin" / exe
    if bundled.exists():
        return str(bundled)
    return name
