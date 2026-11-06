---
name: talking-head-style
description: Edit a creator's own talking-to-camera video like the talking-head references (split-screen graphic panels above the face, 1-3 word bold captions with an italic-serif accent word, punch-ins, comment-keyword CTA). Use when the Studio style is "talking_head".
---

# Talking-head style

Studied from 14 references in `assets/style/talking head/` (kallaway, nick_saraev and 9 creator reels; contact sheets in `refs/`).

## What the references do (the grammar)
- **Face is the anchor.** The speaker stays on screen for most of the reel. Every 2-4 s the layout changes:
  full face → split screen (graphic panel on top ~45 %, face below) → full face → full-screen statement card → ...
- **Panels show exactly what is being said**: a browser/app screenshot card, a number that counts up ("230 videos",
  "282 AI specialists"), a list or checklist that ticks on the words, a "before → after" strike, a typed prompt box.
  Panels sit on a calm background (light blurred or near-black), rounded cards with soft shadow.
- **Captions**: 1-3 words at a time, bold white sans (Inter-like), centred around the chest/lower third, no box on
  the face shots. One key word per line is bigger and in an **italic serif** in the accent colour (blue, yellow).
  On split screens the caption sits on the seam between panel and face.
- **Hook on frame 0**: a 2-line headline at the top ("Run A Whole Agency / Inside Claude Code") with one phrase in a
  highlight box.
- **Punch-ins** (quick 1.1x zoom) on emphasis words; slow push-in on long face shots.
- **Statement cards** for the 1-2 biggest words ("HOW", "ACTUALLY", "BROKEN"), huge, full screen.
- **CTA at the end**: "Comment “KEYWORD”" with the keyword in big quotes and a highlight colour.
- **Sound**: whoosh on every layout change, pops on list items, ticks on counters, one hit on the hook and the CTA.
  Clean, never louder than the voice.
- **Grade**: natural skin, gentle contrast, slight vignette. No heavy colour cast.

## Rules for the editor
1. Never cover the face for more than ~3 s (statement cards are the only full-screen covers, max 2).
2. One layout change every 3-6 s; a full-face moment between two panels.
3. Every graphic shows words the speaker actually said, landing on the word. Never invent numbers or names.
4. 3-7 accent words: the promise, numbers, product names. They become the big italic-serif caption word.
5. Keep the speaker's language and script in captions.

## Preset
`style.json`: yellow accent `#FFD43B`, neutral dark panels, captions `st` mode (stacked, big serif accent word) on the
face, one-line captions on split screens and cards, grade 0.6 without tint, punch-ins on.
