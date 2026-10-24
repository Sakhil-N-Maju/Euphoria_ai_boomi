"""Speech to text with word-level timestamps.

Two engines:
  local   faster-whisper on this PC. A language-specific model (config: whisper.language_models) is used
          when that language is picked or detected, if it has been downloaded; otherwise the default model.
  openai  OpenAI's whisper-1 API (word timestamps), using the key in app/.env.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Callable

from .config import MODELS_DIR, find_tool, load_config

# Whisper language codes for the languages the MVP targets. "auto" lets Whisper detect it.
LANGUAGES = {
    "auto": "Detect automatically",
    "ml": "Malayalam",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "bn": "Bengali",
    "mr": "Marathi",
    "gu": "Gujarati",
    "pa": "Punjabi",
    "ur": "Urdu",
    "en": "English",
}

_models: dict[str, object] = {}
_missing: set[str] = set()
_model_lock = threading.Lock()


def get_model(name: str | None = None):
    """Load a model once and reuse it (loading takes a few seconds). Raises if it isn't downloaded."""
    cfg = load_config()["whisper"]
    name = name or cfg["model"]
    with _model_lock:
        if name not in _models:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            from faster_whisper import WhisperModel

            _models[name] = WhisperModel(
                name,
                device=cfg.get("device", "cpu"),
                compute_type=cfg.get("compute_type", "int8"),
                download_root=str(MODELS_DIR),
                local_files_only=True,
            )
        return _models[name]


def model_available(name: str) -> bool:
    if name in _models:
        return True
    if name in _missing:
        return False
    try:
        get_model(name)
        return True
    except Exception:   # not downloaded (or broken download): fall back to the default model
        _missing.add(name)
        return False


def pick_model(language: str | None) -> tuple[str, str | None]:
    """Return (model name, note). The note explains a fallback, e.g. a language model not downloaded yet."""
    cfg = load_config()["whisper"]
    default = cfg["model"]
    special = (cfg.get("language_models") or {}).get(language or "")
    if not special:
        return default, None
    if model_available(special):
        return special, None
    return default, f"The {LANGUAGES.get(language, language)} model ({special}) isn't downloaded yet, so the " \
                    f"default '{default}' model was used. Run download_models.bat to get it."


def transcribe(path: str | Path, language: str = "auto",
               on_progress: Callable[[float], None] | None = None) -> dict:
    """Return {"language", "language_probability", "duration", "words": [...], "segments": [...], "model", "note"}.

    Each word: {"i", "text", "start", "end", "prob"}. Each segment lists the word indexes it contains.
    """
    engine = load_config()["whisper"].get("engine", "local")
    if engine == "openai":
        return transcribe_openai(path, language, on_progress)
    return transcribe_local(path, language, on_progress)


def transcribe_local(path: str | Path, language: str = "auto",
                     on_progress: Callable[[float], None] | None = None, model_name: str | None = None) -> dict:
    cfg = load_config()["whisper"]
    lang = None if language in (None, "", "auto") else language
    note = None

    if model_name is None:
        if lang is None and cfg.get("language_models"):
            # Detect the language with the default model first, then switch to that language's model if we have one.
            from faster_whisper.audio import decode_audio

            audio = decode_audio(str(path), sampling_rate=16000)
            detected, _prob, _all = get_model().detect_language(audio=audio, vad_filter=True)
            model_name, note = pick_model(detected)
            if model_name != cfg["model"]:
                lang = detected   # fine-tuned models are unreliable at detecting language themselves
        else:
            model_name, note = pick_model(lang)

    model = get_model(model_name)
    segments_iter, info = model.transcribe(
        str(path),
        language=lang,
        task="transcribe",
        beam_size=cfg.get("beam_size", 5),
        word_timestamps=True,
        vad_filter=cfg.get("vad_filter", True),
        condition_on_previous_text=False,   # reduces repeated-phrase hallucinations on long videos
    )

    words: list[dict] = []
    segments: list[dict] = []
    for seg in segments_iter:
        ids = []
        for w in seg.words or []:
            text = w.word.strip()
            if not text:
                continue
            ids.append(len(words))
            words.append({
                "i": len(words),
                "text": text,
                "start": round(float(w.start), 3),
                "end": round(float(w.end), 3),
                "prob": round(float(w.probability), 3),
            })
        segments.append({"start": round(seg.start, 3), "end": round(seg.end, 3),
                         "text": seg.text.strip(), "word_ids": ids})
        if on_progress and info.duration:
            on_progress(min(1.0, seg.end / info.duration))

    return {
        "language": info.language,
        "language_probability": round(float(info.language_probability), 3),
        "duration": round(float(info.duration), 3),
        "words": words,
        "segments": segments,
        "model": model_name,
        "note": note,
    }


def _split_points(audio, sr: int, target: float = 8.0, longest: float = 11.0) -> list[int]:
    """Chunk boundaries (in samples) at the quietest moment, so no chunk is longer than `longest` seconds."""
    import numpy as np

    hop = sr // 100
    n = len(audio) // hop
    if n == 0:
        return [0, len(audio)]
    fr = audio[: n * hop].reshape(n, hop)
    db = 20 * np.log10(np.sqrt((fr.astype("float64") ** 2).mean(1)) + 1e-9)
    db = np.convolve(db, np.ones(5) / 5, "same")
    cuts, lo, hi = [0], int(target * 100 * 0.6), int(longest * 100)
    while n - cuts[-1] > hi:
        s = cuts[-1]
        cuts.append(s + lo + int(np.argmin(db[s + lo: s + hi])))
    return [c * hop for c in cuts] + [len(audio)]


def transcribe_chunked(path: str | Path, language: str = "auto", prompt: str | None = None,
                       on_progress: Callable[[float], None] | None = None, task: str = "transcribe") -> dict:
    """Like transcribe_local, but in short pieces (about 7-11 s, split at the quietest moment).

    Whisper (and the fine-tuned Malayalam model even more) skips, or translates into English, whole stretches when
    it gets a 30-second window of mixed Malayalam and English; short pieces keep it writing every word in the
    speaker's own script. Same return shape as transcribe_local.
    task="translate" gives English captions for non-English speech. It always uses the default multilingual model:
    the fine-tuned Malayalam model ignores the translate task and writes Malayalam anyway."""
    from faster_whisper.audio import decode_audio

    cfg = load_config()["whisper"]
    sr = 16000
    audio = decode_audio(str(path), sampling_rate=sr)
    lang = None if language in (None, "", "auto") else language
    if lang is None:
        detected, _p, _all = get_model().detect_language(audio=audio, vad_filter=True)
        lang = detected
    if task == "translate" and lang != "en":
        model_name, note = cfg["model"], None
    else:
        model_name, note = pick_model(lang)
        task = "transcribe"
    model = get_model(model_name)
    cuts = _split_points(audio, sr)
    words: list[dict] = []
    segments: list[dict] = []
    for k, (a, b) in enumerate(zip(cuts, cuts[1:])):
        off = a / sr
        clip = audio[a:b]
        if len(clip) < sr * 0.3:
            continue
        seg_iter, _info = model.transcribe(clip, language=lang, task=task, beam_size=cfg.get("beam_size", 5),
                                           word_timestamps=True, vad_filter=False, condition_on_previous_text=False,
                                           initial_prompt=prompt or None)
        for seg in seg_iter:
            ids = []
            for w in seg.words or []:
                text = w.word.strip()
                if not text or "�" in text:
                    continue
                ids.append(len(words))
                words.append({"i": len(words), "text": text, "start": round(float(w.start) + off, 3),
                              "end": round(float(w.end) + off, 3), "prob": round(float(w.probability), 3)})
            if ids:
                segments.append({"start": round(seg.start + off, 3), "end": round(seg.end + off, 3),
                                 "text": seg.text.strip(), "word_ids": ids})
        if on_progress:
            on_progress((k + 1) / (len(cuts) - 1))
    return {"language": lang, "language_probability": 1.0, "duration": round(len(audio) / sr, 3), "words": words,
            "segments": segments, "model": model_name, "note": note, "chunks": [round(c / sr, 2) for c in cuts]}


def extract_audio(path: str | Path, out: Path) -> Path:
    """Small mono speech-quality audio (about 0.5 MB per minute), well under the API's 25 MB limit."""
    subprocess.run([find_tool("ffmpeg"), "-hide_banner", "-y", "-nostdin", "-i", str(path), "-vn",
                    "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "64k", str(out)],
                   capture_output=True, check=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return out


def transcribe_openai(path: str | Path, language: str = "auto",
                      on_progress: Callable[[float], None] | None = None) -> dict:
    import requests

    from .llm import api_key, base_url

    key = api_key()
    if not key:
        raise RuntimeError("whisper.engine is 'openai' but there is no API key. Add OPENAI_API_KEY=... to app\\.env")
    cfg = load_config()["whisper"]
    with tempfile.TemporaryDirectory() as tmp:
        audio = extract_audio(path, Path(tmp) / "audio.mp3")
        if on_progress:
            on_progress(0.2)
        data = [("model", cfg.get("openai_model", "whisper-1")), ("response_format", "verbose_json"),
                ("timestamp_granularities[]", "word"), ("timestamp_granularities[]", "segment")]
        if language not in (None, "", "auto"):
            data.append(("language", language))
        with open(audio, "rb") as f:
            r = requests.post(f"{base_url()}/audio/transcriptions", headers={"Authorization": f"Bearer {key}"},
                              data=data, files={"file": ("audio.mp3", f, "audio/mpeg")}, timeout=600)
    if r.status_code != 200:
        raise RuntimeError(f"OpenAI transcription failed ({r.status_code}): {r.text[:500]}")
    result = transcript_from_openai(r.json())
    result["model"] = "openai:" + cfg.get("openai_model", "whisper-1")
    if on_progress:
        on_progress(1.0)
    return result


# OpenAI returns language names ("malayalam"); the rest of the app uses codes.
_NAME_TO_CODE = {v.lower(): k for k, v in LANGUAGES.items() if k != "auto"}


def transcript_from_openai(data: dict) -> dict:
    words = [{"i": i, "text": w["word"].strip(), "start": round(float(w["start"]), 3),
              "end": round(float(w["end"]), 3), "prob": 1.0}
             for i, w in enumerate(x for x in data.get("words", []) if x.get("word", "").strip())]
    segments = []
    for s in data.get("segments", []) or [{"start": 0.0, "end": float(data.get("duration", 0)),
                                             "text": data.get("text", "")}]:
        ids = [w["i"] for w in words if s["start"] - 0.05 <= (w["start"] + w["end"]) / 2 < s["end"] + 0.05]
        segments.append({"start": round(float(s["start"]), 3), "end": round(float(s["end"]), 3),
                         "text": s.get("text", "").strip(), "word_ids": ids})
    # Words that fell between segments: give each to the segment that starts before it.
    seen = {i for s in segments for i in s["word_ids"]}
    for w in words:
        if w["i"] not in seen and segments:
            target = max((s for s in segments if s["start"] <= w["start"]), key=lambda s: s["start"],
                         default=segments[0])
            target["word_ids"] = sorted(target["word_ids"] + [w["i"]])
    lang = str(data.get("language", "")).lower()
    return {
        "language": _NAME_TO_CODE.get(lang, lang),
        "language_probability": 1.0,
        "duration": round(float(data.get("duration") or (words[-1]["end"] if words else 0)), 3),
        "words": words,
        "segments": segments,
        "note": None,
    }


# ---------- OpenAI hybrid: accurate Manglish text from gpt-4o-transcribe, timing from the audio ----------

HYBRID_PROMPTS = {
    "ml": "Transcribe exactly what is said, word for word, in the speaker's order. The speaker mixes Malayalam and "
          "English. Write Malayalam words in Malayalam script and English words in English letters "
          "(e.g. 'ഞാൻ ഇപ്പോൾ Kerala Startup Mission-ന്റെ office-ലാണ്'). Keep fillers like ആ, ഉം, umm. Do not translate.",
    "hi": "Transcribe exactly what is said, word for word. Hindi words in Devanagari, English words in English letters. "
          "Keep fillers. Do not translate.",
    "ta": "Transcribe exactly what is said, word for word. Tamil words in Tamil script, English words in English "
          "letters. Keep fillers. Do not translate.",
}


def _wav_bytes(clip, sr: int) -> bytes:
    import io
    import wave

    import numpy as np

    pcm = (np.clip(clip, -1, 1) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm)
    return buf.getvalue()


def _place_words(words: list[str], clip, sr: int, off: float) -> list[dict]:
    """Give each word a start/end inside the clip. Words are laid along the clip's talking time only (pauses are
    skipped), each taking a share that grows with its length, so captions follow the voice, not the clock."""
    import numpy as np

    hop = sr // 100
    n = max(1, len(clip) // hop)
    db = 20 * np.log10(np.sqrt((clip[: n * hop].reshape(n, hop).astype("float64") ** 2).mean(1)) + 1e-9)
    db = np.convolve(db, np.ones(5) / 5, "same")
    floor, loud = np.percentile(db, 10), np.percentile(db, 90)
    talk = db > floor + max(6.0, (loud - floor) * 0.3)
    idx = np.flatnonzero(talk)
    if len(idx) < 5:
        idx = np.arange(n)
    weights = np.array([max(2, len(w)) + 1.5 for w in words], dtype=float)
    cum = np.concatenate([[0], np.cumsum(weights)]) / weights.sum()
    pos = lambda f: off + idx[min(len(idx) - 1, int(f * (len(idx) - 1)))] / 100
    out = []
    for k, w in enumerate(words):
        s, e = pos(cum[k]), pos(cum[k + 1])
        out.append({"text": w, "start": round(s, 3), "end": round(max(e, s + 0.08), 3)})
    return out


def transcribe_openai_hybrid(path: str | Path, language: str = "ml",
                             on_progress: Callable[[float], None] | None = None) -> dict:
    """Malayalam + English captions with timing. gpt-4o-transcribe gets the words right (it handles Manglish far
    better than Whisper) but returns no timestamps, so each ~8 s piece (split at pauses) is sent alone and its words
    are laid over that piece's speech. Timing error is about a few tenths of a second."""
    import requests
    from faster_whisper.audio import decode_audio

    from .llm import api_key, base_url

    key = api_key()
    if not key:
        raise RuntimeError("Malayalam + English (OpenAI) captions need an OpenAI key. Put LLM_API_KEY=... in app\\.env")
    cfg = load_config()["whisper"]
    model = cfg.get("openai_hybrid_model", "gpt-4o-transcribe")
    sr = 16000
    audio = decode_audio(str(path), sampling_rate=sr)
    lang = None if language in (None, "", "auto") else language
    cuts = _split_points(audio, sr)
    words: list[dict] = []
    segments: list[dict] = []
    for k, (a, b) in enumerate(zip(cuts, cuts[1:])):
        clip = audio[a:b]
        if len(clip) < sr * 0.3:
            continue
        data = {"model": model, "response_format": "json", "temperature": "0"}
        if lang:
            data["language"] = lang
        if HYBRID_PROMPTS.get(lang or ""):
            data["prompt"] = HYBRID_PROMPTS[lang]
        for attempt in range(3):
            r = requests.post(f"{base_url()}/audio/transcriptions", headers={"Authorization": f"Bearer {key}"},
                              data=data, files={"file": ("piece.wav", _wav_bytes(clip, sr), "audio/wav")}, timeout=180)
            if r.status_code < 500 and r.status_code != 429:
                break
        if r.status_code != 200:
            raise RuntimeError(f"OpenAI transcription failed ({r.status_code}): {r.text[:400]}")
        text = (r.json().get("text") or "").strip()
        toks = [t for t in text.split() if t.strip(".,!?…-")]
        if not toks:
            continue
        placed = _place_words(toks, clip, sr, a / sr)
        ids = []
        for w in placed:
            ids.append(len(words))
            words.append({"i": len(words), "text": w["text"], "start": w["start"], "end": w["end"], "prob": 0.9})
        segments.append({"start": round(a / sr, 3), "end": round(b / sr, 3), "text": text, "word_ids": ids})
        if on_progress:
            on_progress((k + 1) / (len(cuts) - 1))
    return {"language": lang or "auto", "language_probability": 1.0, "duration": round(len(audio) / sr, 3),
            "words": words, "segments": segments, "model": "openai:" + model, "note": None,
            "chunks": [round(c / sr, 2) for c in cuts]}
