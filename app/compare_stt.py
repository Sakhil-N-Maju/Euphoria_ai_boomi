"""Compare speech-to-text options on one clip, so you can pick the best one for your language.

    python compare_stt.py C:\\videos\\clip.mp4 --lang ml

Runs the default model, the language-specific model (if downloaded) and, if a key is in .env, OpenAI whisper-1.
Prints speed and timestamp sanity checks, and writes <clip>.stt_compare.txt with each transcript side by side,
so you can read them and count mistakes yourself.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from editor import llm
from editor.config import load_config
from editor.transcribe import LANGUAGES, model_available, transcribe_local, transcribe_openai


def check(tr: dict) -> dict:
    words = tr["words"]
    bad = sum(1 for w in words if w["end"] <= w["start"])
    back = sum(1 for a, b in zip(words, words[1:]) if b["start"] < a["start"] - 0.01)
    low = sum(1 for w in words if w["prob"] < 0.5)
    return {"words": len(words), "zero_length": bad, "out_of_order": back,
            "low_confidence": low, "duration": tr["duration"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", type=Path)
    ap.add_argument("--lang", default="ml", choices=[k for k in LANGUAGES if k != "auto"])
    a = ap.parse_args()

    cfg = load_config()["whisper"]
    runs = [("default: " + cfg["model"], lambda: transcribe_local(a.video, a.lang, model_name=cfg["model"]))]
    special = (cfg.get("language_models") or {}).get(a.lang)
    if special:
        if model_available(special):
            runs.append((special, lambda: transcribe_local(a.video, a.lang, model_name=special)))
        else:
            print(f"(skipping {special}: not downloaded, run download_models.bat)")
    if llm.configured():
        runs.append(("openai: " + cfg.get("openai_model", "whisper-1"), lambda: transcribe_openai(a.video, a.lang)))
    else:
        print("(skipping OpenAI whisper-1: no key in .env)")

    report = []
    for name, fn in runs:
        print(f"\n== {name}")
        t = time.time()
        try:
            tr = fn()
        except Exception as exc:
            print(f"   failed: {exc}")
            report.append(f"===== {name}\nFAILED: {exc}\n")
            continue
        took = time.time() - t
        c = check(tr)
        speed = c["duration"] / took if took else 0
        print(f"   {took:.0f}s ({speed:.1f}x real time), {c['words']} words, low confidence {c['low_confidence']}, "
              f"zero-length {c['zero_length']}, out of order {c['out_of_order']}")
        text = " ".join(w["text"] for w in tr["words"])
        print("   " + text[:300] + ("…" if len(text) > 300 else ""))
        timing = "\n".join(f"  {w['start']:7.2f}-{w['end']:7.2f}  {w['text']}" for w in tr["words"][:40])
        report.append(f"===== {name}\n{took:.0f}s, {c}\n\n{text}\n\nFirst 40 words with timestamps "
                      f"(play the clip and check they line up):\n{timing}\n")

    out = a.video.with_suffix(".stt_compare.txt")
    out.write_text("\n".join(report), encoding="utf-8")
    print(f"\nFull transcripts: {out}")


if __name__ == "__main__":
    main()
