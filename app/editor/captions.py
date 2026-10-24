"""Burned-in captions and the title card, written as one .ass subtitle file on the edited timeline.

Caption styles (HyperFrames notes):
  plain      one event per short line (the original look)
  highlight  word-synced: the word being spoken is tinted in the accent colour
  keyword pop (on top of either): a keyword scales up to ~115% with a 150 ms ease-out and stays tinted
"""
from __future__ import annotations

from pathlib import Path

from .timeline import edited_words

SENTENCE_END = (".", "?", "!", "।", "॥", ",", ":", ";")


def caption_lines(transcript: dict, plan: dict, cfg: dict) -> list[dict]:
    """Return [{"start", "end", "text", "words": [{"i","text","start","end"}]}] in edited-video time."""
    max_words = int(cfg.get("max_words", 4))
    max_chars = int(cfg.get("max_chars", 26))
    timed = edited_words(transcript, plan)

    lines: list[dict] = []
    cur: list[dict] = []

    def flush() -> None:
        if cur:
            lines.append({"start": cur[0]["start"], "end": cur[-1]["end"],
                          "text": " ".join(x["text"] for x in cur), "words": list(cur)})
            cur.clear()

    for w in timed:
        if cur:
            chars = len(" ".join(x["text"] for x in cur)) + 1 + len(w["text"])
            if (len(cur) >= max_words or chars > max_chars or w["start"] - cur[-1]["end"] > 0.6
                    or cur[-1]["text"].endswith(SENTENCE_END)):
                flush()
        cur.append(w)
    flush()

    # Smooth timing: a minimum on-screen time, and close tiny gaps so captions don't flicker.
    for i, line in enumerate(lines):
        nxt = lines[i + 1]["start"] if i + 1 < len(lines) else None
        end = max(line["end"], line["start"] + 0.5)
        if nxt is not None:
            if nxt - end < 0.3:
                end = nxt
            end = min(end, nxt)
        line["end"] = end
    return lines


def _ass_time(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def ass_color(hex_rgb: str, alpha: int = 0) -> str:
    """'#RRGGBB' -> ASS '&HAABBGGRR'."""
    h = (hex_rgb or "#FFD23F").lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _word_events(line: dict, style: dict, upper: bool) -> list[tuple[float, float, str]]:
    """One event per word-time slice of a line, with the current word highlighted and keywords popped."""
    words = line["words"]
    accent = ass_color(style.get("accent", "#FFD23F"))
    highlight = style.get("caption_style") == "highlight"
    pop = bool(style.get("keyword_pop"))
    kw = set(style.get("keywords", [])) if pop else set()
    scale = round(float(style.get("pop_scale", 1.18)) * 100)
    ms = int(style.get("pop_ms", 150))

    def tok(w: dict) -> str:
        t = _ass_escape(w["text"])
        return t.upper() if upper else t

    events = []
    # Before the first word lands (line start == first word start, so usually empty), then one slice per word.
    for k, active in enumerate(words):
        s = active["start"] if k else line["start"]
        e = words[k + 1]["start"] if k + 1 < len(words) else line["end"]
        if e - s < 0.01:
            continue
        parts = []
        for j, w in enumerate(words):
            text = tok(w)
            if w["i"] in kw and j < k:            # already popped: stays big and tinted
                parts.append(f"{{\\c{accent}\\fscx{scale}\\fscy{scale}}}{text}{{\\r}}")
            elif w["i"] in kw and j == k:         # pops now: ease-out scale over pop_ms
                parts.append(f"{{\\c{accent}\\fscx100\\fscy100\\t(0,{ms},0.5,\\fscx{scale}\\fscy{scale})}}{text}{{\\r}}")
            elif j == k and highlight:
                parts.append(f"{{\\c{accent}}}{text}{{\\r}}")
            else:
                parts.append(text)
        events.append((s, e, " ".join(parts)))
    return events


def cta_times(duration: float, keyword: str) -> tuple[float, float, list[float]]:
    """Call-to-action card: (start, typing start, time of each typed letter). Last ~3 s of the video."""
    start = max(0.0, duration - 3.0)
    typing = start + 0.45
    step = min(0.09, 1.2 / max(1, len(keyword)))
    return start, typing, [round(typing + k * step, 3) for k in range(len(keyword))]


def write_ass(lines: list[dict], size: tuple[int, int], cfg: dict, path: Path, style: dict | None = None,
              captions_on: bool = True, duration: float | None = None,
              translations: dict[str, str] | None = None) -> None:
    """Write captions (if captions_on), the title card and the call-to-action card to an .ass file."""
    style = style or {}
    w, h = size
    vertical = h > w
    reel = style.get("format") == "reel"
    fsize = max(18, round(min(w, h) * float(cfg.get("size", 0.07))))
    margin_v = round(h * (float(cfg.get("bottom_margin", 0.16)) if vertical else 0.07))
    margin_l = margin_r = round(w * 0.08)
    if reel:
        # Instagram safe zones (Reel Editor): caption text sits above y~1560 of 1920 and clear of the
        # like/comment/share buttons on the right (x > 930 of 1080).
        margin_v = max(margin_v, round(h * 0.2))
        margin_l, margin_r = round(w * 0.06), round(w * 0.14)
    outline = max(2, round(fsize * 0.09))
    font = cfg.get("font", "Nirmala UI")
    upper = cfg.get("uppercase_latin", False)

    tsize = max(22, round(min(w, h) * 0.085))
    tfont = style.get("title_font") or font
    accent = ass_color(style.get("accent", "#FFD23F"))
    t_margin = round(h * (0.12 if vertical else 0.08))

    out = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {w}",
        f"PlayResY: {h}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{font},{fsize},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,"
        f"-1,0,0,0,100,100,0,0,1,{outline},0,2,{margin_l},{margin_r},{margin_v},1",
        # Title card: dark text on an accent box (BorderStyle 3 draws a box in the outline colour).
        f"Style: Title,{tfont},{tsize},&H00141414,&H00141414,{accent},&H00000000,"
        f"-1,0,0,0,100,100,0,0,3,{max(6, round(tsize * 0.28))},0,8,{round(w * 0.08)},{round(w * 0.08)},{t_margin},1",
        # Call to action: a line of text over a white "comment box" where the keyword types itself in.
        f"Style: CTALine,{font},{round(tsize * 0.8)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,"
        f"-1,0,0,0,100,100,0,0,1,{max(2, round(tsize * 0.07))},0,5,{round(w * 0.08)},{round(w * 0.08)},0,1",
        # Translated caption line (dual captions) and the lower-third name card (graphic-overlays skill)
        f"Style: Trans,{font},{round(fsize * 0.72)},&H00E6E6E6,&H00E6E6E6,&H00000000,&H64000000,"
        f"-1,0,0,0,100,100,0,0,1,{max(2, round(outline * 0.8))},0,2,{margin_l},{margin_r},"
        f"{max(4, margin_v - round(fsize * 1.25))},1",
        f"Style: LowerName,{font},{round(tsize * 0.62)},&H00FFFFFF,&H00FFFFFF,&H00141414,&H00000000,"
        f"-1,0,0,0,100,100,0,0,3,{max(6, round(tsize * 0.2))},0,1,0,0,0,1",
        f"Style: LowerRole,{font},{round(tsize * 0.44)},&H00141414,&H00141414,{accent},&H00000000,"
        f"-1,0,0,0,100,100,0,0,3,{max(4, round(tsize * 0.14))},0,1,0,0,0,1",
        f"Style: CTABox,{font},{round(tsize * 0.9)},&H00141414,&H00141414,&H00FFFFFF,&H00000000,"
        f"-1,0,0,0,100,100,0,0,3,{max(8, round(tsize * 0.35))},0,5,{round(w * 0.08)},{round(w * 0.08)},0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    title = (style.get("title") or "").strip()
    if style.get("title_enabled") and title:
        secs = float(style.get("title_seconds", 2.2))
        text = _ass_escape(title)
        # Scale in from 70% with an ease-out and fade, hold, fade out (lands at ~0.28 s, where the pop SFX sits).
        anim = "{\\fad(120,260)\\fscx70\\fscy70\\t(0,280,0.5,\\fscx100\\fscy100)}"
        out.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(secs)},Title,,0,0,0,,{anim}{text}")

    keyword = (style.get("cta_keyword") or "").strip()
    if keyword and duration:
        start, typing, letters = cta_times(duration, keyword)
        line = _ass_escape((style.get("cta_line") or "").strip() or "Comment")
        cx, y_line, y_box = w // 2, round(h * 0.6), round(h * 0.6) + round(tsize * 1.7)
        out.append(f"Dialogue: 2,{_ass_time(start)},{_ass_time(duration)},CTALine,,0,0,0,,"
                   f"{{\\pos({cx},{y_line})\\fad(200,0)\\fscx80\\fscy80\\t(0,250,0.5,\\fscx100\\fscy100)}}{line}")
        out.append(f"Dialogue: 2,{_ass_time(start + 0.15)},{_ass_time(typing)},CTABox,,0,0,0,,"
                   f"{{\\pos({cx},{y_box})\\fad(150,0)}}|")
        word = _ass_escape(keyword)
        for k, t in enumerate(letters):
            end = letters[k + 1] if k + 1 < len(letters) else duration
            cursor = "|" if k + 1 < len(letters) else ""
            out.append(f"Dialogue: 2,{_ass_time(t)},{_ass_time(end)},CTABox,,0,0,0,,"
                       f"{{\\pos({cx},{y_box})}}{word[:k + 1]}{cursor}")

    name = (style.get("lower_name") or "").strip()
    if name:
        t0 = float(style.get("lower_at", 2.5))
        if duration:
            t0 = min(t0, max(0.0, duration - 4.0))
        t1 = t0 + 4.0
        x = round(w * 0.07)
        y = round(h * (0.66 if vertical else 0.8))
        step = round(tsize * 0.95)
        out.append(f"Dialogue: 3,{_ass_time(t0)},{_ass_time(t1)},LowerName,,0,0,0,,"
                   f"{{\\move({x - round(w * 0.04)},{y},{x},{y},0,320)\\fad(200,250)}}{_ass_escape(name)}")
        role = (style.get("lower_role") or "").strip()
        if role:
            out.append(f"Dialogue: 3,{_ass_time(t0 + 0.12)},{_ass_time(t1)},LowerRole,,0,0,0,,"
                       f"{{\\move({x - round(w * 0.04)},{y + step},{x},{y + step},0,320)\\fad(200,250)}}"
                       f"{_ass_escape(role)}")

    lang = style.get("caption_lang") or ""
    trans = translations if (lang and translations) else None
    dual = bool(trans and style.get("caption_dual"))
    if captions_on:
        per_word = style.get("caption_style") == "highlight" or style.get("keyword_pop")
        if trans and not dual:
            per_word = False      # a translated line has no word timings of its own
        for line in lines:
            if trans:
                t = trans.get(line["text"])
                if t and dual:
                    out.append(f"Dialogue: 0,{_ass_time(line['start'])},{_ass_time(line['end'])},Trans,,0,0,0,,"
                               f"{_ass_escape(t)}")
                elif t:
                    line = {**line, "text": t, "words": None}
            if per_word and line.get("words"):
                for s, e, text in _word_events(line, style, upper):
                    out.append(f"Dialogue: 0,{_ass_time(s)},{_ass_time(e)},Default,,0,0,0,,{text}")
            else:
                text = _ass_escape(line["text"])
                if upper:
                    text = text.upper()
                out.append(f"Dialogue: 0,{_ass_time(line['start'])},{_ass_time(line['end'])},Default,,0,0,0,,{text}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8-sig")
