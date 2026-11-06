---
name: creator-reel
description: "Turn one raw talking-head video into an edited creator reel (9:16): cuts, native-language captions, hook, split-screen motion graphics, text behind the head, green grade, SFX, comment CTA. Token-lean: one planning call, everything else is scripts. Used by the Euphoria app for every upload."
---

# Creator reel (token-lean)

Built on the product-launch-video skill's structure (steps → gates → scripts, a block catalog instead of hand-written
frames) and the reel-editor engine. **Claude plans; scripts build.** One planning call per video, no tools, no
code writing, no review loops. Nothing is hand-edited after a script exits 0.

`<S>` = `scripts/` · `<P>` = `prompts/` · cwd = the job folder · run every script with the same Python (`$PY`).

**Styles.** The Studio offers three edit styles (`../styles/`, studied from the reference reels in `assets/style/`):
`talking_head` (this pipeline + its preset), `faceless` (this pipeline on a generated background: `faceless_prep.py`
makes the "footage" from the script or a voice-over) and `product` (screen recordings: `activity.py` →
one planning call with `styles/product/planner.md` → `product_build.py` → the same render steps 4-5).
`edit_plan.json` carries `style` / `look`; `build_plan.py` reads `styles/<style>/style.json`.

## 0 · Setup (once per PC) → `tools.json`
`$PY <S>/setup_tools.py <tools_dir>` (Chromium, OpenCV, fonts, cut-out model). The Euphoria website does this from its Setup panel.
**Gate:** `tools.json` exists.

## 1 · Capture → `src.mp4`, `audio16k.wav`, `words.json`, `bg.png`
`$PY <S>/prep.py raw.mp4` · `$PY <S>/make_bg.py green` · `$PY <S>/transcribe.py audio16k.wav words.json --lang <ml|hi|en|auto>`
**Gate:** `words.json` has words. Hard stop if empty (no speech): report, don't invent.

## 2 · Plan (the only Claude call) → `edit_plan.json`
System prompt = `<P>/plan_rules.md`; output schema = `<P>/plan_schema.json`; user message = language, comment keyword,
creator notes, duration and the transcript as `index word@time` lines (pauses marked). The plan refers to **word
indexes only**. Call shape (Claude Code):
`claude -p --safe-mode --tools "" --strict-mcp-config --no-session-persistence --output-format json --json-schema "$(cat <P>/plan_schema.json)" --system-prompt-file <P>/plan_rules.md < message.txt`
**Gate:** valid JSON with `keep`, `headline`, `beats`; indexes inside the transcript (the builder clamps the rest).

## 3 · Build → `edit.json`, `subs.json`, `plan.json`, `pip.json`, `overlay.html`, `sfx_events.json`
`$PY <S>/build_plan.py edit_plan.json` — cuts (tightens pauses), auto caption chunks, face position (no AI),
split-screen layouts, zooms/punch-ins, grade, text-behind-head, SFX, and `templates/lean_overlay.html` filled from the block catalog.
**Gate:** exit 0; summary line printed.

## 4 · Render → `base_ov.mp4`  (cached: only what changed is drawn again)
`$PY <S>/masks.py 0 <back_until>` (only if `overlay_cfg.json` has a back range) ·
`$PY <S>/render_overlay.py ov all 0/2` ‖ `$PY <S>/render_overlay.py ov all 1/2` (parallel) ·
`$PY <S>/composite.py full ov base_ov.mp4`
**Gate:** `composite.py` prints `done N / N`.
**Render cache.** `render_overlay.py` gives every graphics frame a signature (what is on screen, times relative to the
frame) and keeps the PNGs in `ovcache/` (`ov_map.json` = frame → picture). `composite.py` renders 2-second chunks that
never cross a cut, keyed by everything that decides their pixels, into `vcache/`, renders only missing chunks (in
parallel), and joins them without re-encoding. `build_plan.py` keeps last build's choices (`stable.json`: zoom per
piece of video, punch-in words, caption lines) and snaps all times to a 1/120 s grid, so a fix at 0:05 re-renders only
the seconds around 0:05; parts that only moved in time are reused. The grade runs through a cached 3D lookup table.

## 5 · Finish → `out/reel.mp4`, `out/reel-master.mp4`
`$PY <S>/sfx.py sfx_events.json` · `$PY <S>/finish.py reel` (voice clean-up, −14 LUFS mix, master + small file, `final_sheet.jpg`, `first_frame.jpg`).
**Gate:** both MP4s exist; the hook is visible in `first_frame.jpg`.

---
**Look:** green-black panels, lime `#C6F432` accent, white text, `// LABEL` mono labels, lime word-box captions, olive grade + vignette.
**Blocks:** counter · list · checklist · steps · toggle · typing · strike · bars (split screen) · statement (full card) · sticker (face overlay) · cta (end). Add a block = add it to `templates/lean_overlay.html` `COMP`, `plan_rules.md` and `plan_schema.json`.
**Rules:** never add claims the speaker didn't say; keep the speaker's language; 3–7 beats per 25–60 s; one layout change every 3–6 s.
**Credits:** render engine from the reel-editor skill; structure from the product-launch-video (HyperFrames) skill.
