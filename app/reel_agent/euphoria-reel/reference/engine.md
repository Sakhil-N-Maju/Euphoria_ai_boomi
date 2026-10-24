# Engine reference (read when you need details)

Everything runs on the creator's PC inside the job folder (the current folder). Scripts: `$S` = this skill's `scripts/` folder, run with `"$PY"`.

| Script | What it does | Output |
|---|---|---|
| `"$PY" $S/prep.py <video>` | Upright, 30 fps, H.264 copy of the upload (max 1440 px wide) + 16 kHz audio + contact sheet | `src.mp4`, `src.json`, `audio16k.wav`, `contact.jpg` |
| `"$PY" $S/reframe.py follow\|stack\|center` | Landscape → vertical. follow = cuts to whoever talks; stack = two speakers top/bottom | `vertical.mp4` (then `mv vertical.mp4 src.mp4`) |
| `"$PY" $S/transcribe.py audio16k.wav words.json` | Word timings with the app's Whisper | `words.json` `[{"w":word,"s":start}]` |
| `"$PY" $S/cuts.py env t0 t1 ...` | Loudness strip, 10 ms per character, to find silent cut points | printed |
| `"$PY" $S/cuts.py apply` | `keep.json` `[[src0,src1],...]` → cut audio + time map | `edit.json`, `voice_cut.wav`, `voice_cut16.wav` |
| `"$PY" $S/subs.py subs.txt` | Caption chunks (see format below) | `subs.json` |
| `"$PY" $S/masks.py [t0 t1 ...]` | Person cut-out masks (only for ranges that need text behind the person; it's ~0.6 s per frame) | `masks/*.png` |
| `"$PY" $S/make_bg.py dark\|light` | Background for split screens and cards | `bg.png` |
| `"$PY" $S/render_overlay.py ov all 0/2` + `1/2` (run both at once) | Graphics layer from `overlay.html` | `ov/*.png`, `ov_back/*.png` |
| `"$PY" $S/composite.py test ov 15,120,300 sheet.jpg` | Test frames → contact sheet (look at it!) | `sheet.jpg` |
| `"$PY" $S/composite.py full ov base_ov.mp4` | Full video: cuts, zoom, colour grade, subject pop, text behind person, layouts, graphics. Takes ~4–8 min for 40 s; run it in the background and poll | `base_ov.mp4` |
| `"$PY" $S/sfx.py` | Sound effects from `sfx_events.json` | `sfx.wav` |
| `"$PY" $S/finish.py <name>` | Voice processing, mix at −14 LUFS, master + <30 MB file, check images | outputs folder |

Long steps (masks, render, composite) can pass the 10-minute command limit: start them with `nohup ... > log 2>&1 &` and poll the log.

## After cutting: re-check the transcript
Run `transcribe.py voice_cut16.wav words_cut.json` and use those times (they are output times). Every sentence must read cleanly with no clipped word.

## Caption file `subs.txt`
One caption per line. Words as `<output time> <word>` separated by ` ; `. Flags before a word: `^` big key word, `*` accent colour, `~` italic serif (English words only).
```
0.16 Video ; 0.48 ^~editors-ന്
3.16 edit ; 3.46 ചെയ്തത് ; 3.60 ^*~Claude ; 3.92 ആണ്
```
Rules: 1–4 words per line, never end a line on "the/of/a/to/and/it". Fix words the speech model misheard (names, numbers, English words inside other languages). Keep the speaker's language and script; keep English terms in English. 3–7 accent words per reel.

## Zoom plan `plan.json`
```json
{"anchors":[{"until":999,"fx":0.54,"fy":0.45}],
 "zoom":[[1.0,1.04],[1.06,1.1]],
 "punch":[[1.6,1.12,1.13,2.04]],
 "grade":1.0, "pop":0.84}
```
- `anchors`: face position as fractions of the frame (look at `contact.jpg`). `zoom`: one `[start,end]` per segment in `edit.json` — alternate ~1.0 and ~1.1 across cuts so a cut never looks like a skip. `punch`: quick push-ins on emphasis words `[from, z, z, to]` (output times). Keep zoom ≤ 1.1 where text sits above the head.
- `grade`: 0 = no colour change, 1 = cinematic (contrast, warm skin, cooler shadows, vignette). `pop`: background brightness when masks exist (0.84 = subject stands out; 1 = off).

## Layouts `pip.json` (optional)
States are `[x, y, w, h, radius, scale, offset_x, offset_y]` of where the video sits on the 1080×1920 frame (the rest shows `bg.png`). Keys are `[time, state, easing]`; easing `step` = instant, `eo5` smooth out, `eio` smooth both, `eb` bouncy.
```json
{"states":{"full":[0,0,1080,1920,0,1,0,0],
  "split":[24,24,1032,980,40,1.0,0,-306],
  "win":[300,196,480,853,18,0.444444,300,196],
  "phone":[300,210,480,853,52,0.444444,300,210]},
 "keys":[[0,"full"],[4.2,"full"],[4.62,"win","eo5"],[7.9,"win"],[8.26,"full","eio"]]}
```
- `split` = face in a rounded card on top (y 24–1004), graphics panel below (y ~1080–1700). For "split" the offset_y picks which rows of the frame show: offset_y = 24 − (row you want at the top of the card).
- A state named `phone…` gets a phone bezel automatically.
- The `overlay.html` reads the same file, so graphics line up with the video.

## Graphics `overlay.html`
Copy `templates/overlay.html` to `the job folder/overlay.html`. Edit only the block between `EDIT THESE` lines:
- `BACKTEXT`: big words *behind* the person: `{t0, t1, text, top, size, color, glowAt}`. Also add the range to `overlay_cfg.json`: `{"back":[[0,4.25]]}` and run `masks.py 0 4.3`. Put the word so the head covers its lower third (top ≈ head-top minus 0.6 × size).
- `HEADLINE`: the hook text at the top for the first seconds. Must be on screen from frame 0.
- `capStyle(t)`: caption mode and height per time range. `st` = stacked (small words + one big glowing key word; best on the face shots, y≈1290), `in` = one line (split screens: y≈1052 under the card), `pill` = dark pill with the spoken word highlighted (good on colour cards), `none`.
- `BEATS`: `{layer:'id' or card:'id', t0, t1, build(el), draw(t, el)}`. `card` = full-screen background behind it (hides the video). `draw` must depend only on `t`.

Helpers available in the template: `ent(t,start,dur)` 0→1 ease, `pop(t,start,dur)` → `[scale, opacity]` with overshoot, `P(t,a,d)` linear 0→1, `eo/eo5/eio/eb` easings, `setT(el,opacity,transform,blur)`, `rng(seed)` for shakes, CSS classes `.block .big .sub` (full card text), `.sticker`, `.pill`, `.glass`, `.acc`.

### Beat recipes (copy and adapt)
```js
// Colour-block card with a big statement (hides the face)
{card:'b1', t0:4.3, t1:7.9,
 build(el){el.style.background='#7B5CFF';el.innerHTML=`<div class="block"><div class="big">13 skills</div><div class="sub">all free</div></div><div class="sticker" style="left:640px;top:520px">FREE</div>`},
 draw(t,el){const e=ent(t,4.3,0.4);setT(el,e*(1-eo(P(t,7.7,0.2))),`scale(${1.06-0.06*e})`,(1-e)*12);
   const [s,o]=pop(t,5.0,0.4);setT(el.querySelector('.sticker'),o,`rotate(8deg) scale(${s})`)}},
// Items that pop in one by one on the words that name them (split-screen panel, y 1100-1650)
{layer:'list', t0:13.6, t1:20.7,
 build(el){el.innerHTML=['install Node.js','add an API key','configure a server'].map((x,i)=>`<div class="abs pill glass" style="left:60px;top:${1110+i*90}px">${x}</div>`).join('')},
 draw(t,el){[14.4,15.0,15.7].forEach((k,i)=>{const [s,o]=pop(t,k,0.3);setT(el.children[i],o,`scale(${s})`)})}},
// Counter that rolls up to a number on the spoken word
{layer:'num', t0:26.2, t1:29.5,
 build(el){el.innerHTML=`<div class="abs" style="left:0;right:0;top:1150px;text-align:center;font:800 190px IT;color:var(--acc)" id="n1">0</div>`},
 draw(t,el){$('n1').textContent=Math.round(80*eo(P(t,26.7,0.6)))+'K+'}},
```
More complete examples (editor window with a live timeline, phone gallery, terminal typing, chat box with upload/skill/enter, progress ring checklist, phone mock-up with particles, screenshot proof card, comment box CTA): `examples/claude-edit-reel-overlay.html`.

### Sound effects `sfx_events.json`
`[[time, kind, dBFS, {options}], ...]` — kinds: `air` (whoosh, options dur/f0/f1), `tap`, `key`, `hit` (f0 50–80, dec), `pop`, `riser` (dur, put it so it ends on a hit), `swipe`, `shutter`, `glitch`, `ticks` (counting), `file` (`{"path":"my.wav"}`).
Clean & aesthetic: quiet by default (−30 to −36), one `air` per transition, `pop`/`tap` for things appearing, keyboard `key` taps while text types, 1–3 `hit`s at −22 to −26 for the biggest moments only, nothing on top of dense speech. No music, no melodic chimes.

### Instagram safe zones (1080×1920)
Top UI y < 170 · right buttons x > 930 between y 1100–1750 · caption text y > 1560. Keep text inside x 60–1020.
