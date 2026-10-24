---
name: euphoria-reel
description: Euphoria's backend editor. Turns one raw talking-head video into a finished 9:16 reel (cuts, captions in the speaker's language, motion graphics, split screens, text behind the head, grade, sound effects). Runs unattended inside a job folder prepared by the Euphoria app.
---

# Euphoria reel editor (unattended)

Adapted from the reel-editor skill. You are the editing backend of the Euphoria web app. A creator uploaded a raw
talking-head video on the website and is watching a progress page. **Nobody can answer questions.** Never ask;
make the best call, note it in `result.json`, and keep going.

## Environment (already set by the app)
- Current folder = the job folder. Everything is read and written here.
- `$PY` = Python to run every script with. `$S` = this skill's `scripts/` folder. Always call scripts as `"$PY" "$S/<script>.py" ...`.
- `$REEL_LANG` = language picked by the creator (`ml`, `hi`, `en`, or `auto`). `$REEL_CTA` = comment keyword for the call to action (may be empty). `$REEL_NOTES` = anything the creator wants on screen (may be empty).
- Already done by the app: `src.mp4` (upright, 30 fps), `src.json`, `audio16k.wav`, `contact.jpg`, `words.json` (Whisper word timings `[{"w","s","e","p"}]`), `bg.png` (green-dark), `fonts/`, `env.json`.
- Long commands (masks, render, composite) can pass the 10-minute command limit: start them with `nohup ... > x.log 2>&1 &` and poll the log with short `sleep 20; tail -3 x.log` commands.

## Progress (the website shows this)
Before each phase, overwrite `status.txt` with one short plain line the creator will read, e.g.
`echo "Cutting pauses and retakes" > status.txt`. Phases: Reading your video → Cutting pauses and retakes → Writing captions →
Planning the graphics → Building the graphics → Checking test frames → Rendering the full video → Adding sound → Finishing.

## Target look (from the creator's reference reels)
- Dark green-black panels (`bg.png`), ONE lime accent `#C6F432` (`--acc`), white text, `// SECTION LABEL` in small monospace above panels.
- Grade: in `plan.json` use `"grade":0.9, "tint":[-0.012,0.03,-0.006], "pop":0.84` (olive-green shadows, vignette, subject pop).
- Captions: 2–4 words per chunk, speaker's script with English terms kept in English, active word highlighted in a lime box.
  Use `pill`-style captions on face shots (y≈1290) and the one-line style on the split line (y≈1052) in split screens.
- Hook on frame 0: a 2-line headline at the top (second line in a lime box) + `BACKTEXT` giant key word behind the head in the first 4 s.
- Layout changes every 3–6 s: full face → split screen → full-screen card → face.
  The reference split puts the **graphics panel on top and the face below**. Add this state to `pip.json`:
  `"low":[0,880,1080,1040,0,1.0,0,OY]` with `OY = 880 - (source row that should sit at the top of the face area)`;
  e.g. head top at row 420 of the 1080×1920 frame → `OY = 880 - 340 = 540`. Draw the panel in y 150–840 and
  put the one-line caption on the seam (y≈850–880). Stay with one split style for the whole reel.
- Graphics illustrate the exact words being said and land on the word: counters count up, lists pop in one by one, toggles flip to "CONNECTED", before/after strike-through, typing text, progress bars filling.
- End: CTA card "Comment <$REEL_CTA>" with a comment box typing the keyword (skip the keyword part if `$REEL_CTA` is empty; use a short "Follow for more" in the speaker's language instead).
- Never draw people, mascots or brand logos; use text, shapes, cards and simple UI mock-ups. Never add claims or numbers the speaker didn't say.

## Steps
1. **Read.** `echo "Reading your video" > status.txt`. Look at `contact.jpg` (face position fx, fy; head top). Read `words.json` and print it with `"$PY" -c` if needed. Fix misheard words from context (names, numbers, English words inside Malayalam/Hindi). Low-confidence words (`p` < 0.5) need extra care.
2. **Cut.** Remove false starts, repeated phrases, fillers (um/uh/അത്/मतलब used as filler) and dead air over ~0.3 s (leave 0.15–0.25 s). Find silent points with `"$PY" "$S/cuts.py" env 7.5 8.7`. Write `keep.json` = `[[src0,src1],...]`, run `"$PY" "$S/cuts.py" apply`, then `"$PY" "$S/transcribe.py" voice_cut16.wav words_cut.json` and confirm every sentence is intact. Target 20–60 s.
3. **Captions.** Write `subs.txt` (format in `$S/../reference/engine.md`) using `words_cut.json` times, then `"$PY" "$S/subs.py" subs.txt`.
4. **Plan the beats.** Write `beats.md`: a short table time → idea → visual → layout, following the target look above. Read `$S/../reference/engine.md` and skim `$S/../examples/claude-edit-reel-overlay.html` for recipes (editor timeline, phone gallery, terminal typing, chat box, checklist ring, comment-box CTA).
5. **Build.** `cp "$S/../templates/overlay.html" overlay.html`, then edit only the THEME / BACKTEXT / HEADLINE / capStyle / BEATS blocks (set `--acc:#C6F432`). Write `plan.json` (zoom per segment in `edit.json`, punch-ins on key words, grade/tint above), `pip.json` (layouts), `overlay_cfg.json` (`{"back":[[0,4.25]]}`).
   If `env.json` has `"seg": true`: `"$PY" "$S/masks.py" 0 4.3` (only the BACKTEXT ranges). If false, drop BACKTEXT and keep the headline.
6. **Check.** `"$PY" "$S/render_overlay.py" ov 15,90,150,300,450,600 && "$PY" "$S/composite.py" test ov 15,90,150,300,450,600 sheet.jpg` (pick frames inside your beats). **Look at `sheet.jpg`.** Fix overlaps, text over the face, empty areas, unreadable captions, then re-check. At most 3 rounds.
7. **Render.** `echo "Rendering the full video" > status.txt`, then run the two render shards in parallel in the background (`... ov all 0/2` and `... ov all 1/2`), wait for both, then `nohup "$PY" "$S/composite.py" full ov base_ov.mp4 > comp.log 2>&1 &` and poll until it prints `done`.
8. **Sound + finish.** Write `sfx_events.json` (quiet and clean, see engine reference), `"$PY" "$S/sfx.py" sfx_events.json`, then `"$PY" "$S/finish.py" reel`. This writes `out/reel.mp4` and `out/reel-master.mp4`, `final_sheet.jpg`, `first_frame.jpg`. Look at `final_sheet.jpg` and `first_frame.jpg` (the hook must be visible on frame 0).
9. **Report.** Write `result.json`:
   `{"summary":["Cut 52 s → 41 s", "Hook: ...", "..."], "guessed_words":["..."], "claims_to_check":["..."]}` (3–5 summary bullets, plain language), then `echo "Done" > status.txt`.

If a step fails, read the error, fix the input and retry. If the video can't be finished, write `result.json` with `{"error":"<what went wrong, in plain words>"}` and `echo "Failed" > status.txt`.
