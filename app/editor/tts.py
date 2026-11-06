"""ElevenLabs voice-over for the reel studio (faceless reels and product narration).

Key: ELEVENLABS_API_KEY in app/.env (or the environment). Optional: ELEVENLABS_VOICE_ID (default voice),
ELEVENLABS_MODEL (default: eleven_v3 for Malayalam / auto-detect, eleven_multilingual_v2 otherwise).

Uses POST /v1/text-to-speech/{voice_id}/with-timestamps, which returns the audio and the start/end time of every
character, so word timings come straight from the voice (no Whisper pass). Every piece of speech is cached by
(model, voice, language, text): re-rendering or changing one line never pays for the lines that didn't change.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import urllib.error
import urllib.request
import wave
from pathlib import Path

from .config import DATA_DIR, env_value, find_tool

API = "https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps?output_format=mp3_44100_128"
VOICES_API = "https://api.elevenlabs.io/v1/voices"
SR = 48000
CACHE = DATA_DIR / "reels" / "_cache" / "tts"
LANG_CODES = {"ml": "ml", "hi": "hi", "ta": "ta", "en": "en"}


def api_key() -> str | None:
    return env_value("ELEVENLABS_API_KEY", "XI_API_KEY")


def ready() -> bool:
    return bool(api_key())


def check_voice_id(v: str) -> None:
    if v and not re.fullmatch(r"[A-Za-z0-9]{8,40}", v):
        raise RuntimeError("That ElevenLabs voice ID doesn't look right (copy it from Voices → your voice → ID).")


def account_voice() -> str:
    """No voice chosen: take a default (premade) voice from the account's own list, which every plan, free included,
    may use through the API. Needs the key's 'Voices: Read' permission; the pick is remembered."""
    key = api_key() or ""
    memo = CACHE / "account_voice.json"
    tag = hashlib.sha1(key.encode()).hexdigest()[:12]
    if memo.exists():
        m = json.loads(memo.read_text(encoding="utf-8"))
        if m.get("key") == tag and m.get("voice"):
            return m["voice"]
    req = urllib.request.Request(VOICES_API, headers={"xi-api-key": key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            voices = json.loads(r.read().decode("utf-8")).get("voices") or []
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError("Pick a voice: either paste a voice ID in the Studio (or ELEVENLABS_VOICE_ID in app/.env) "
                               "from ElevenLabs → Voices → My Voices → a default voice → ID, or give the API key "
                               "'Voices: Read' permission so the app can pick one.") from None
        raise RuntimeError(f"Couldn't list your ElevenLabs voices ({e.code}).") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Couldn't reach ElevenLabs: {e.reason}") from None
    pick = next((v for v in voices if v.get("category") == "premade"), None) or (voices[0] if voices else None)
    if not pick:
        raise RuntimeError("Your ElevenLabs account has no voices. Add one under Voices → My Voices.")
    CACHE.mkdir(parents=True, exist_ok=True)
    memo.write_text(json.dumps({"key": tag, "voice": pick["voice_id"], "name": pick.get("name")}), encoding="utf-8")
    return pick["voice_id"]


def voice_for(voice_id: str | None) -> str:
    v = (voice_id or "").strip() or (env_value("ELEVENLABS_VOICE_ID") or "").strip()
    check_voice_id(v)
    return v or account_voice()


def model_for(lang: str | None) -> str:
    return env_value("ELEVENLABS_MODEL") or ("eleven_v3" if lang in ("ml", "auto", None, "") else "eleven_multilingual_v2")


def _pieces(text: str, limit: int = 1800) -> list[str]:
    """split at sentence ends so no request is too long"""
    sents = re.split(r"(?<=[.!?।])\s+", text.strip())
    out, cur = [], ""
    for s in sents:
        while len(s) > limit:                              # one huge sentence: split at spaces
            if cur:
                out.append(cur); cur = ""
            cut = s.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            out.append(s[:cut].strip()); s = s[cut:].strip()
        if cur and len(cur) + 1 + len(s) > limit:
            out.append(cur); cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        out.append(cur)
    return [p for p in out if p]


def _request(text: str, voice: str, model: str, lang: str | None, previous: str | None) -> dict:
    body = {"text": text, "model_id": model}
    if LANG_CODES.get(lang or ""):
        body["language_code"] = LANG_CODES[lang]
    if previous:
        body["previous_text"] = previous[-400:]
    req = urllib.request.Request(API.format(voice=voice), data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"xi-api-key": api_key() or "", "Content-Type": "application/json",
                                          "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        if e.code == 401:
            raise RuntimeError("ElevenLabs rejected the API key (401). Check ELEVENLABS_API_KEY in app/.env and that "
                               "the key has Text to Speech access.") from None
        if "paid_plan_required" in detail or "library voices" in detail.lower():
            raise RuntimeError("This ElevenLabs voice is from the Voice Library, which free plans can't use through the API. "
                               "Leave the voice ID empty (the app then uses a default voice from your account) or paste the "
                               "ID of a voice under Voices → My Voices → Default voices.") from None
        if e.code in (402, 429) or "quota" in detail.lower():
            raise RuntimeError(f"ElevenLabs: out of credits or rate-limited ({e.code}). {detail}") from None
        if e.code == 404:
            raise RuntimeError("ElevenLabs couldn't find that voice ID (404). Use a voice from your Voices list.") from None
        raise RuntimeError(f"ElevenLabs error {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Couldn't reach ElevenLabs: {e.reason}") from None


def _decode(mp3: Path, wav: Path) -> float:
    """mp3 -> mono 48 kHz 16-bit WAV; returns its exact duration"""
    r = subprocess.run([find_tool("ffmpeg"), "-v", "error", "-y", "-i", str(mp3), "-ac", "1", "-ar", str(SR),
                        "-c:a", "pcm_s16le", str(wav)], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("Decoding the ElevenLabs audio failed: " + (r.stderr or "")[-300:])
    with wave.open(str(wav)) as w:
        return w.getnframes() / w.getframerate()


def _words(al: dict | None, offset: float) -> list[dict]:
    if not al or not al.get("characters"):
        return []
    out, cur, s, e = [], "", None, None
    for ch, a, b in zip(al["characters"], al["character_start_times_seconds"], al["character_end_times_seconds"]):
        if ch.isspace():
            if cur:
                out.append({"w": cur, "s": round(s + offset, 3), "e": round(e + offset, 3), "p": 1.0})
            cur, s = "", None
            continue
        if s is None:
            s = a
        cur += ch; e = b
    if cur:
        out.append({"w": cur, "s": round(s + offset, 3), "e": round(e + offset, 3), "p": 1.0})
    return [w for w in out if re.search(r"\w", w["w"])]


def speak(text: str, out_wav: Path, lang: str | None = None, voice_id: str | None = None) -> tuple[float, list[dict]]:
    """Text -> out_wav (mono 48 kHz). Returns (duration, words with start/end seconds; [] if no timings came back)."""
    if not api_key():
        raise RuntimeError("Add ELEVENLABS_API_KEY to app/.env and restart the app to use the ElevenLabs voice.")
    voice, model = voice_for(voice_id), model_for(lang)
    CACHE.mkdir(parents=True, exist_ok=True)
    frames, words, offset, prev, timed = [], [], 0.0, None, True
    for piece in _pieces(text):
        key = hashlib.sha1(json.dumps([model, voice, lang or "", piece, prev or ""]).encode("utf-8")).hexdigest()[:20]
        mp3, wav, meta = CACHE / f"{key}.mp3", CACHE / f"{key}.wav", CACHE / f"{key}.json"
        if not (mp3.exists() and meta.exists()):
            res = _request(piece, voice, model, lang, prev)
            if not res.get("audio_base64"):
                raise RuntimeError("ElevenLabs returned no audio.")
            tmp = mp3.with_suffix(".tmp")
            tmp.write_bytes(base64.b64decode(res["audio_base64"])); tmp.replace(mp3)
            meta.write_text(json.dumps({"alignment": res.get("alignment") or res.get("normalized_alignment")}), encoding="utf-8")
        if wav.exists():
            with wave.open(str(wav)) as w:
                dur = w.getnframes() / w.getframerate()
        else:
            dur = _decode(mp3, wav)
        pw = _words(json.loads(meta.read_text(encoding="utf-8")).get("alignment"), offset)
        timed = timed and bool(pw)
        words += pw
        with wave.open(str(wav)) as w:
            frames.append(w.readframes(w.getnframes()))
        offset += dur; prev = piece
    out_wav = Path(out_wav)
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        for f in frames:
            w.writeframes(f)
    return offset, (words if timed else [])
