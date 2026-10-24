"""Edit a video from the command line, no browser needed.

    python cli.py talk.mp4                      # transcribe, auto-cut, render talk_edited.mp4
    python cli.py talk.mp4 --lang ml --no-captions
    python cli.py talk.mp4 --plan-only          # stop after writing talk.edit.yaml so you can edit it
    python cli.py talk.mp4 --from-plan talk.edit.yaml
    python cli.py talk.mp4 --retakes            # also let the AI cut retakes (needs a key in .env)
    python cli.py talk.mp4 --draft              # fast low-resolution render for checking the edit
    python cli.py talk.mp4 --autostyle          # word-synced captions, keyword pops, transitions at topic changes
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

from editor import plan as planlib
from editor.config import load_config
from editor.render import render
from editor.transcribe import LANGUAGES, transcribe


def bar(label: str):
    start = time.time()

    def show(p: float) -> None:
        filled = int(p * 30)
        sys.stdout.write(f"\r{label} [{'#' * filled}{'.' * (30 - filled)}] {p * 100:5.1f}%  {time.time() - start:5.0f}s")
        sys.stdout.flush()
        if p >= 1:
            sys.stdout.write("\n")
    return show


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", type=Path)
    ap.add_argument("--lang", default="auto", choices=list(LANGUAGES))
    ap.add_argument("--out", type=Path)
    ap.add_argument("--min-silence", type=float)
    ap.add_argument("--keep-fillers", action="store_true")
    ap.add_argument("--no-captions", action="store_true")
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--from-plan", type=Path)
    ap.add_argument("--retakes", action="store_true", help="AI retake detection (needs LLM_API_KEY in .env)")
    ap.add_argument("--draft", action="store_true", help="fast low-resolution render")
    ap.add_argument("--autostyle", action="store_true",
                    help="word-synced captions, keyword pops and transitions at topic changes (picked by rules)")
    a = ap.parse_args()

    video = a.video.resolve()
    stem = video.with_suffix("")
    tpath = Path(f"{stem}.transcript.json")
    ppath = Path(f"{stem}.edit.yaml")
    out = (a.out or Path(f"{stem}_edited.mp4")).resolve()
    cfg = load_config()

    if tpath.exists():
        print(f"Using existing transcript {tpath.name}")
        transcript = json.loads(tpath.read_text(encoding="utf-8"))
    else:
        transcript = transcribe(video, a.lang, on_progress=bar("Transcribing"))
        tpath.write_text(json.dumps(transcript, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Language: {transcript['language']} ({transcript['language_probability']:.0%}), "
              f"{len(transcript['words'])} words")

    if a.from_plan:
        plan = planlib.load_plan(a.from_plan)
    else:
        settings = dict(cfg["edit"])
        if a.min_silence is not None:
            settings["min_silence"] = a.min_silence
        if a.keep_fillers:
            settings["remove_fillers"] = False
        plan = planlib.build_plan(transcript, settings, cfg.get("fillers", []),
                                  captions={"enabled": not a.no_captions}, source=video.name)
        if a.retakes:
            from editor.aiedit import find_retakes
            found = find_retakes(transcript)
            for r in found:
                print(f"Retake: words {r['remove_from']}-{r['remove_to']} cut, kept {r['kept_from']}-{r['kept_to']} "
                      f"({r['reason']})")
            ids = {i for r in found for i in range(r["remove_from"], r["remove_to"] + 1)}
            plan = planlib.build_plan(transcript, settings, cfg.get("fillers", []),
                                      removed_words=sorted(set(plan["removed_words"]) | ids),
                                      captions={"enabled": not a.no_captions}, source=video.name, retakes=found)
        if a.autostyle:
            from editor import style as stylelib
            removed = set(plan["removed_words"])
            plan["style"] = {**plan.get("style", {}), "caption_style": "highlight", "keyword_pop": True, "transitions": True,
                             "keywords": stylelib.auto_keywords(transcript["words"], removed),
                             "topic_breaks": stylelib.auto_topic_breaks(transcript["words"], removed,
                                                                        plan["edited_duration"])}
        planlib.save_plan(plan, ppath)
        print(f"Plan: {len(plan['cuts'])} cuts, {plan['duration']:.1f}s -> {plan['edited_duration']:.1f}s "
              f"(saved {ppath.name})")
    if a.plan_only:
        return

    with tempfile.TemporaryDirectory() as tmp:
        render(Path(tmp), video, transcript, plan, out, on_progress=bar("Rendering   "), draft=a.draft)
        if (Path(tmp) / "captions.ass").exists():
            shutil.copy(Path(tmp) / "captions.ass", f"{stem}.captions.ass")
    print(f"Done: {out}")


if __name__ == "__main__":
    main()
