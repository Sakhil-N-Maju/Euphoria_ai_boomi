"""Render an edit plan: cut, join, finish (zooms, b-roll, look, titles, captions), mix sound, encode.

The whole edit is one ffmpeg filtergraph written to filtergraph.txt in the job folder, so every render can be
inspected and re-run by hand. With every style option off the graph is the original: trim + join, captions,
loudness normalisation.

Layers, bottom to top (Editorial Film Edit: work from clean layers):
  source segments (+ punch-in / transition zoom) -> film look (optional, whole video)
  -> b-roll inserts (full screen or sliding split, own film look) -> title + captions (never graded)
  audio: voice (loudness-normalised) + bed (music ducked under the voice + synthesised effects) + b-roll ambience
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Callable

from . import sfx
from . import style as stylelib
from .captions import caption_lines, write_ass
from .config import APP_DIR, load_config
from .media import filter_script_args, probe, run_ffmpeg
from .plan import keep_segments
from .timeline import describe, speech_intervals

FADE = 0.012  # short audio fades at each join so cuts don't click
SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def out_size(width: int, height: int, draft: bool, short_side: int = 540, reel: bool = False) -> tuple[int, int]:
    """Native size for the final render (no upscaling); short side `short_side` for a fast draft.
    A reel is always 1080x1920 (540x960 as a draft)."""
    if reel:
        return (short_side, short_side * 16 // 9 // 2 * 2) if draft else (1080, 1920)
    w, h = float(width), float(height)
    if draft and min(w, h) > short_side:
        k = short_side / min(w, h)
        w, h = w * k, h * k
    return max(2, int(round(w / 2)) * 2), max(2, int(round(h / 2)) * 2)


def film_look(inp: str, out: str, w: int, h: int, tag: str) -> str:
    """Bright, soft B&W + gentle bloom + fine moving luma grain (Editorial Film Edit look).

    Neutral monochrome (no split toning), midtones opened up, a soft glow on highlights only, and grain that
    changes every frame. Works in grey so no colour can creep into the black-and-white.
    """
    sigma = max(3.0, round(min(w, h) * 0.018, 1))
    return (f"[{inp}]hue=s=0,eq=contrast=0.93:brightness=0.035:gamma=1.07,format=gray,split=2[{tag}a][{tag}b];"
            f"[{tag}b]lut=c0='clip((val-0.55*maxval)/0.45,0,maxval)',gblur=sigma={sigma}[{tag}g];"
            f"[{tag}a][{tag}g]blend=all_mode=screen:all_opacity=0.30,noise=c0s=6:c0f=t+u,format=yuv420p[{out}]")


def reel_crop(sw: int, sh: int, fx: float = 0.5, fy: float = 0.45) -> str | None:
    """Crop to 9:16 around the face position (fractions of the frame). None if already 9:16."""
    target = 9 / 16
    if sw / sh > target * 1.01:
        cw, ch = int(sh * target) // 2 * 2, sh // 2 * 2
        x = int(min(max(fx * sw - cw / 2, 0), sw - cw))
        return f"crop={cw}:{ch}:{x}:0"
    if sw / sh < target * 0.99:
        cw, ch = sw // 2 * 2, int(sw / target) // 2 * 2
        y = int(min(max(fy * sh - ch / 2, 0), sh - ch))
        return f"crop={cw}:{ch}:0:{y}"
    return None


def grade_chain(grade: str, lut: str | None = None) -> str | None:
    """Colour grade for the presenter footage.

    cinematic: the Reel Editor grade for ordinary (non-log) footage: gentle S-curve contrast, cooler shadows,
               warmer highlights and skin, a little vibrance, soft vignette.
    look01:    the Look 01 teal-orange LUT by @shakirc.ai. Expects Sony S-Log3 / S-Gamut3.Cine footage, decoded
               as legal-range BT.709, then vignette PI/8 and fine grain, exactly as in the skill.
    """
    if grade == "cinematic":
        return ("curves=master='0/0 0.25/0.215 0.5/0.5 0.75/0.79 1/1',"
                "colorbalance=rs=-0.025:gs=0.012:bs=0.045:rh=0.045:gh=0.006:bh=-0.035,"
                "vibrance=intensity=0.18,vignette=angle=PI/5,format=yuv420p")
    if grade == "look01" and lut:
        return (f"scale=in_range=tv:in_color_matrix=bt709:flags=lanczos,format=rgb48le,"
                f"lut3d=file='{lut}':interp=tetrahedral,format=rgb24,vignette=PI/8,format=yuv420p,noise=c0s=4:c0f=t")
    return None


def vhs_look(h: int) -> str:
    """vhs skill: soft tape blur, red/blue channel offset, warm saturated colour, moving noise and scanlines."""
    shift = max(2, round(h / 360))
    return (f"gblur=sigma=0.7,format=gbrp,rgbashift=rh={shift}:bh=-{shift},format=yuv420p,"
            f"eq=saturation=1.25:contrast=1.08:brightness=0.02,noise=c0s=10:c0f=t,"
            f"drawgrid=w=iw:h={max(3, h // 270)}:t=1:c=black@0.22,format=yuv420p")


VOICE_CLEAN = ("highpass=f=80,afftdn=nr=12:nf=-40:tn=1,deesser=i=0.4,"
               "equalizer=f=3000:t=q:w=1.2:g=2,")


def _ease(t0: float, t1: float, d: float) -> str:
    """0 -> 1 -> 0 over [t0, t1] with smoothstep ramps of d seconds (for overlay expressions)."""
    return (f"st(0,clip(min((t-{t0:.3f})/{d:.3f},({t1:.3f}-t)/{d:.3f}),0,1));"
            f"ld(0)*ld(0)*(3-2*ld(0))")


def build_filtergraph(segs: list[tuple[float, float]], has_audio: bool, subtitles: str | None,
                      loudnorm: bool, size: tuple[int, int] | None = None, fps: float = 30.0,
                      style: dict | None = None, transitions: list[float] | None = None,
                      broll: list[dict] | None = None, bed_input: int | None = None,
                      broll_cfg: dict | None = None, src_size: tuple[int, int] | None = None,
                      lut: str | None = None, speed: float = 1.0) -> str:
    """The filtergraph. `broll` items: {"input", "start", "end", "layout", "has_audio"} in edited time."""
    style = style or {}
    transitions = transitions or []
    broll = broll or []
    bcfg = broll_cfg or {}
    n = len(segs)
    parts = [f"[0:v]split={n}" + "".join(f"[vs{i}]" for i in range(n))]
    if has_audio:
        parts.append(f"[0:a]asplit={n}" + "".join(f"[as{i}]" for i in range(n)))

    punch_on = bool(style.get("punch_in"))
    punch_zoom = float(style.get("punch_zoom", 1.12))
    tz = float(style.get("transition_zoom", 1.15)) - 1
    td = float(style.get("transition_ms", 350)) / 1000
    fps_s = f"{fps:.3f}".rstrip("0").rstrip(".")
    reel = style.get("format") == "reel"
    crop916 = reel_crop(*src_size, float(style.get("face_x", 0.5)), float(style.get("face_y", 0.45))) \
        if (reel and src_size) else None

    concat_in = ""
    t_edit = 0.0
    since_break = 0
    for i, (s, e) in enumerate(segs):
        length = e - s
        local = [max(0.0, round(t - t_edit, 3)) for t in transitions if t_edit - 0.001 <= t < t_edit + length - 0.05]
        if any(abs(x) < 0.02 for x in local):
            since_break = 0
        punch = punch_zoom if (punch_on and since_break % 2 == 1) else 1.0
        chain = f"[vs{i}]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS"
        if crop916:
            chain += "," + crop916
        if size:
            w, h = size
            if local:
                bump = "+".join(f"between(it,{tk:.3f},{tk + td:.3f})*pow(1-(it-{tk:.3f})/{td:.3f},2)" for tk in local)
                z = f"{punch:.3f}*(1+{tz:.3f}*({bump}))"
                chain += (f",fps={fps_s},zoompan=z='{z}':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)*0.4'"
                          f":d=1:s={w}x{h}:fps={fps_s}")
            elif punch > 1.001:
                chain += (f",crop=w='trunc(iw/{punch:.3f}/2)*2':h='trunc(ih/{punch:.3f}/2)*2'"
                          f":x='(iw-ow)/2':y='(ih-oh)*0.4',scale={w}:{h}")
            else:
                chain += f",scale={w}:{h}"
            chain += ",setsar=1"
        parts.append(chain + f"[v{i}]")
        concat_in += f"[v{i}]"
        if has_audio:
            fade = min(FADE, length / 4)
            parts.append(
                f"[as{i}]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS,"
                f"afade=t=in:d={fade:.3f},afade=t=out:st={max(0.0, length - fade):.3f}:d={fade:.3f}[a{i}]"
            )
            concat_in += f"[a{i}]"
        t_edit += length
        since_break += 1
    a = 1 if has_audio else 0
    parts.append(f"{concat_in}concat=n={n}:v=1:a={a}[vc]" + ("[ac]" if has_audio else ""))

    cur = "vc"
    graded = grade_chain(style.get("grade", "none"), lut)
    if size and graded:
        parts.append(f"[{cur}]{graded}[vgrade]")
        cur = "vgrade"
    look = style.get("look", "clean")
    if size and look == "archival_all":
        parts.append(film_look(cur, "vlook", size[0], size[1], "lk"))
        cur = "vlook"
    elif size and look == "vhs":
        parts.append(f"[{cur}]{vhs_look(size[1])}[vlook]")
        cur = "vlook"

    # ---- b-roll inserts ----
    if size and broll:
        W, H = size
        split_d = float(bcfg.get("split_ms", 380)) / 1000
        for j, b in enumerate(broll):
            t0, t1 = b["start"], b["end"]
            split = b.get("layout") == "split"
            horizontal = W >= H
            bw, bh = ((W // 4) * 2, H) if (split and horizontal) else ((W, (H // 4) * 2) if split else (W, H))
            src = f"{b['input']}:v"
            parts.append(f"[{src}]fps={fps_s},scale={bw}:{bh}:force_original_aspect_ratio=increase,"
                         f"crop={bw}:{bh},setsar=1[br{j}]")
            tin = f"br{j}"
            if look in ("archival", "archival_all"):
                parts.append(film_look(tin, f"bt{j}", bw, bh, f"bl{j}"))
                tin = f"bt{j}"
            parts.append(f"[{tin}]format=yuv420p,setpts=PTS-STARTPTS+{t0:.3f}/TB[bv{j}]")
            enable = f"enable='between(t,{t0:.3f},{t1:.3f})'"
            if not split:
                parts.append(f"[{cur}][bv{j}]overlay=0:0:eof_action=pass:{enable}[ov{j}]")
            else:
                # Presenter split: the panel slides in softly while the presenter is reframed to the other half.
                e = _ease(t0, t1, split_d)
                blur = max(8, round(min(W, H) * 0.03))
                parts.append(f"[{cur}]split=2[sp{j}a][sp{j}b]")
                parts.append(f"[sp{j}a]gblur=sigma={blur}:{enable},eq=brightness=-0.12:{enable}[sg{j}]")
                if horizontal:
                    half = (W // 4) * 2
                    parts.append(f"[sp{j}b]crop={half}:{H}:{W // 4}:0[spc{j}]")
                    parts.append(f"[sg{j}][spc{j}]overlay=x='{W // 4}*(1-({e}))':y=0:eval=frame:{enable}[spo{j}]")
                    parts.append(f"[spo{j}][bv{j}]overlay=x='{W}-{half}*({e})':y=0:eval=frame:"
                                 f"eof_action=pass:{enable}[ov{j}]")
                else:
                    half = (H // 4) * 2
                    y0 = int(round(H * 0.1 / 2)) * 2
                    parts.append(f"[sp{j}b]crop={W}:{half}:0:{y0}[spc{j}]")
                    parts.append(f"[sg{j}][spc{j}]overlay=x=0:y='{y0}*(1-({e}))':eval=frame:{enable}[spo{j}]")
                    parts.append(f"[spo{j}][bv{j}]overlay=x=0:y='{H}-{half}*({e})':eval=frame:"
                                 f"eof_action=pass:{enable}[ov{j}]")
            cur = f"ov{j}"

    vchain = f"[{cur}]format=yuv420p"
    if subtitles:
        vchain += f",subtitles={subtitles}"
    parts.append(vchain + "[vout]")

    if has_audio:
        clean = VOICE_CLEAN if style.get("voice_clean") else ""
        if reel:
            # Reel Editor voice finish: rumble cut, gentle 2.2:1 compression, Instagram loudness (-14 LUFS)
            voice = (f"[ac]{clean}highpass=f=70,acompressor=threshold=-24dB:ratio=2.2:attack=8:release=140:makeup=2,"
                     + ("loudnorm=I=-14:TP=-1.5:LRA=11," if loudnorm else "") + "aresample=48000")
        else:
            voice = (f"[ac]{clean}" + ("acompressor=threshold=-22dB:ratio=2.5:attack=6:release=120:makeup=2,"
                                       if clean else "")
                     + ("loudnorm=I=-16:TP=-1.5:LRA=11," if loudnorm else "") + "aresample=48000")
        extras = []
        if bed_input is not None:
            parts.append(f"[{bed_input}:a]aresample=48000,aformat=channel_layouts=stereo[bed]")
            extras.append("[bed]")
        amb_db = float(bcfg.get("ambience_db", -20))
        for j, b in enumerate(broll):
            if not b.get("has_audio"):
                continue
            dur = b["end"] - b["start"]
            ms = int(round(b["start"] * 1000))
            parts.append(f"[{b['input']}:a]asetpts=PTS-STARTPTS,atrim=0:{dur:.3f},aresample=48000,"
                         f"aformat=channel_layouts=stereo,volume={amb_db}dB,afade=t=in:d=0.08,"
                         f"afade=t=out:st={max(0.0, dur - 0.15):.3f}:d=0.15,adelay={ms}|{ms}[amb{j}]")
            extras.append(f"[amb{j}]")
        if not extras:
            parts.append(voice + "[aout]")
        else:
            parts.append(voice + ",aformat=channel_layouts=stereo[voice]")
            parts.append(f"[voice]{''.join(extras)}amix=inputs={1 + len(extras)}:duration=first:normalize=0,"
                         f"alimiter=limit=0.95:level=0,aresample=48000[aout]")
    graph = ";\n".join(parts) + "\n"
    if abs(speed - 1.0) > 1e-3:
        # video-edit skill: speed up the finished video (voice keeps its pitch); captions and effects move with it
        graph = graph.replace("[vout]", "[vpre]").replace("[aout]", "[apre]")
        graph += f";\n[vpre]setpts=PTS/{speed:.3f}[vout]\n"
        if has_audio:
            graph = graph.rstrip("\n") + f";\n[apre]atempo={speed:.3f}[aout]\n"
    return graph


def find_lut(cfg: dict | None = None) -> Path | None:
    """The Look 01 LUT (config render.look01_lut, relative to the app folder), if it is installed."""
    cfg = cfg or load_config()
    rel = (cfg.get("render") or {}).get("look01_lut", "luts/Look01_TealOrange_Master_SLog3_65.cube")
    p = (APP_DIR / rel).resolve()
    return p if p.is_file() else None


def render(job_dir: Path, source: Path, transcript: dict, plan: dict, output: Path,
           on_progress: Callable[[float], None] | None = None, draft: bool = False) -> Path:
    cfg = load_config()
    rcfg = cfg["render"]
    ccfg = {**cfg["captions"], **(plan.get("captions") or {})}
    st = stylelib.effective(plan)

    info = probe(source)
    duration = float(plan.get("duration") or info.duration)
    segs = keep_segments(plan["cuts"], duration)
    if not segs:
        raise ValueError("The plan cuts the whole video; nothing left to render.")
    fps = info.fps if 10 <= info.fps <= 120 else 30.0
    size = out_size(info.width, info.height, draft, int(rcfg.get("draft_short_side", 540)),
                    reel=st.get("format") == "reel")
    tl = describe(transcript, plan, cfg, st)
    edited = sum(e - s for s, e in segs)

    # Title + captions
    subtitles = None
    captions_on = bool(ccfg.get("enabled", True) and transcript.get("words"))
    lines = caption_lines(transcript, plan, ccfg) if captions_on else []
    has_title = bool(st.get("title_enabled") and st.get("title"))
    has_cta = bool((st.get("cta_keyword") or "").strip())
    has_lower = bool((st.get("lower_name") or "").strip())
    translations = None
    if st.get("caption_lang") and lines:
        from . import extras, llm
        translations = extras.cached_translations(job_dir, st["caption_lang"])
        missing = [ln["text"] for ln in lines if ln["text"] not in translations]
        if missing and llm.configured():
            try:
                translations = {**translations, **extras.translate_lines(job_dir, missing, st["caption_lang"])}
            except llm.LLMError:
                pass        # captions fall back to the spoken language for lines that aren't translated
    if lines or has_title or has_cta or has_lower:
        write_ass(lines, size, ccfg, job_dir / "captions.ass", style=st, captions_on=captions_on, duration=edited,
                  translations=translations)
        subtitles = "captions.ass"   # relative: ffmpeg runs inside job_dir, avoiding Windows path escaping

    args = ["-i", str(source.resolve())]
    next_input = 1

    # Music + effects bed (one track, built in numpy so every level and time is exact)
    bed_input = None
    if info.has_audio:
        music = None
        if st.get("music"):
            found = sorted(p for p in job_dir.glob("music.*") if p.is_file())
            music = found[0] if found else None
        events = tl["sound_map"] if st.get("sfx") else []
        bed = sfx.build_bed(job_dir / "bed.wav", edited, events, st, music, speech_intervals(tl["words"]))
        if bed is not None:
            args += ["-i", bed.name]
            bed_input = next_input
            next_input += 1

    # B-roll clips, each trimmed at input so only the slot is decoded
    broll_inputs = []
    skip = float((cfg.get("broll") or {}).get("skip_start", 0.4))
    for item in plan.get("broll") or []:
        slot = tl["broll"].get(item["id"]) or {}
        clip = item.get("clip")
        if not clip or slot.get("start") is None or not SAFE_NAME.match(clip) or not (job_dir / clip).exists():
            continue
        trim = item.get("trim_start")
        trim = skip if trim is None else float(trim)
        clip_info = probe(job_dir / clip)
        trim = min(trim, max(0.0, clip_info.duration - 0.5))
        dur = slot["end"] - slot["start"]
        args += ["-ss", f"{trim:.3f}", "-t", f"{dur + 0.25:.3f}", "-i", clip]
        broll_inputs.append({"input": next_input, "start": slot["start"], "end": slot["end"],
                             "layout": item.get("layout", "full"), "has_audio": clip_info.has_audio})
        next_input += 1

    lut = None
    if st.get("grade") == "look01":
        src_lut = find_lut(cfg)
        if src_lut is None:
            raise ValueError("Look 01 needs its LUT file in app\\luts (Look01_TealOrange_Master_SLog3_65.cube).")
        lut = "look01.cube"            # copied next to the job: ffmpeg runs in job_dir, no Windows path escaping
        if not (job_dir / lut).exists() or (job_dir / lut).stat().st_size != src_lut.stat().st_size:
            shutil.copyfile(src_lut, job_dir / lut)
    graph = build_filtergraph(segs, info.has_audio, subtitles, rcfg.get("loudnorm", True), size=size, fps=fps,
                              style=st, transitions=tl["transitions"], broll=broll_inputs,
                              bed_input=bed_input, broll_cfg=cfg.get("broll") or {},
                              src_size=(info.width, info.height), lut=lut,
                              speed=float(st.get("speed", 1.0) or 1.0))
    (job_dir / "filtergraph.txt").write_text(graph, encoding="utf-8")

    args += [*filter_script_args("filtergraph.txt"), "-map", "[vout]"]
    if info.has_audio:
        args += ["-map", "[aout]", "-c:a", "aac", "-b:a", str(rcfg.get("audio_bitrate", "160k"))]
    preset = str(rcfg.get("draft_preset", "ultrafast")) if draft else str(rcfg.get("preset", "veryfast"))
    crf = rcfg.get("draft_crf", 28) if draft else rcfg.get("crf", 20)
    args += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", str(output.resolve())]

    run_ffmpeg(args, cwd=job_dir, expected_duration=edited / float(st.get("speed", 1.0) or 1.0),
               on_progress=on_progress)
    return output
