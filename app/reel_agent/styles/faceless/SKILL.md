---
name: faceless-style
description: Make a no-face reel from only a topic or script (optionally the creator's voice-over or music): kinetic typography, motion-graphic blocks that build on the words, clean editorial backgrounds, comment CTA. Use when the Studio style is "faceless" (no talking head).
---

# Faceless style (topic / script → motion-graphics reel)

Studied from 13 references in `assets/style/no talking head/` (contact sheets in `refs/`): editorial explainers
("Your content is INVISIBLE", "Flow State" collage), minimal green "Attention" edit, stick-figure "Two salesmen" story,
red/black "ugoki" motion-curve explainers, "Claude & me" POV, sound-design breakdown.

## What the references do
- **Text IS the picture**: the script appears word by word, big, centred; one word per line gets weight, colour or an
  italic serif. Words blur/slide in on the beat of the voice.
- **Backgrounds are calm and consistent**: off-white paper with a faint grid (editorial), or near-black with one glow
  colour (red, green, blue). One accent colour per video.
- **Motion-graphic blocks build the idea**: lists and checklists that fill item by item, pills that toggle, counters,
  graphs that draw, "old → new" strikes, a typed prompt box, a hub with branches.
- **Rhythm**: a visual change every 1-2 s; a big full-screen word for the punchline ("WHY?", "USELESS", "STRUCTURE").
- **Story**: hook question → tension → 3-5 beats → punchline → "Comment “WORD”" CTA card.
- **Sound**: voice-over or music bed, plus clean UI sounds (pops, ticks, whooshes, keyboard).

## Rules for the editor
1. The script is the source of truth: every word on screen is from the script; blocks show what the line says.
2. Write tight scripts when asked to: 45-110 words, one idea per sentence, hook in the first line, CTA last.
3. One block at a time, never two panels at once; a plain kinetic-text moment between blocks.
4. 1-3 statement cards for the strongest words only.

## Looks = scene families (pick in the Studio)
Each look is a family of hand-built scene types (`creator-reel/templates/scenes.js`) modelled on the references'
editing — devices, figures, paper objects, a host — not just their colours. The AI only picks scenes and fills them in
(`planner.md` + `scenes_<look>.md`, schema `plan_schema.json`); all drawing is code, so it costs no extra tokens.
- **Devices** (`crimson`, "ugoki" reels): tilted 3D phone (list / chat / big number), code editor typing line by line,
  editing timeline with a moving playhead, self-drawing curve graph with chips, extruded glowing word, comment-box CTA.
- **Story** (`midnight`, "Two salesmen"): glowing stick figures with poses, props and check/x marks, neon outlined
  tags (with strike-through), speech bubbles, glowing line icons.
- **Editorial** (`paper`, "STRUCTURE" / "How to create videos"): torn ruled notepad with handwriting, red circled word
  and stamped word, huge condensed word with swipe underline and definition, magnifier over a brick wall revealing a
  phrase, pinned polaroids.
- **Presenter** (`violet`, "pov Claude & me"): an original cartoon host at the bottom whose mouth moves with the voice
  and who gestures on each scene; numbered app windows above (typed prompt, folder opened by a cursor, ticked
  checklist, chat), phones and icons.
Old names still work: light → paper, dark/ink → crimson; devices/story/editorial/presenter are aliases too.
Every scene's drawing depends only on times relative to it, and the host's state is part of the frame signature, so
the render cache and the "change only 0:05" edits work exactly as for the other styles.

## Captions (all styles)
- Never twice: a caption line whose meaningful words are already on screen (card, statement, hook, CTA, title) is left out.
- Lines break exactly where a card appears or leaves, and each line keeps one place for its whole life: big in the
  middle when nothing else is up, small under the card when one is. Nothing jumps mid-line.
- Faceless: a line stays up until the next one, so the screen is never empty.

## Preset
`style.json`: `look=light` paper (#F3F1EC, ink text, red accent) or `look=dark` (near-black, lime accent); captions are
the kinetic centre text (`st` mode at y 960), blocks centred on screen, no camera zoom.
