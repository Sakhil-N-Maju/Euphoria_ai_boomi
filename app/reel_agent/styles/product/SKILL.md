---
name: product-style
description: Turn a screen recording of an app, website or digital product into a SaaS-launch style reel (framed window on a glowing background, auto-zoom on what moves, speed-ups of dull parts, kinetic title callouts, logo outro with a button). Use when the Studio style is "product".
---

# Product style (screen recordings → launch reel)

Studied from 13 references in `assets/style/product/` (contact sheets in `refs/`): Apple-style SaaS promos
(ElevenLabs Agents, Loom, Yodixa, Duolingo, a stock app, an Instagram feature concept, "Website Downloader").

## What the references do
- **The product is the hero, inside a frame**: the UI sits in a rounded window (or device) floating on a soft gradient
  / glow background (deep blue, green, orange-red, or light pastel). Soft drop shadow. Often slightly tilted or
  shown on a monitor/laptop POV shot.
- **Camera moves, the UI doesn't**: slow push-ins and pans to the part that matters (a button, a typed prompt, a
  chart), then back out. Fast parts are cut or sped up; nothing static stays on screen for long.
- **Kinetic text between/above the UI**: 1-6 words, big, clean sans (Inter/SF-like), words fade-blur in one by one
  ("Turn Thoughts", "Into Action", "Just Ask", "See The Magic"). One accent word in the brand colour or an italic serif.
- **Story**: hook line → problem (1 line) → 3-5 feature moments (each = UI moment + 2-4 word label) → payoff
  ("Pro Workflow Unleashed") → logo outro: product name, tagline, a pill button ("Talk to the team", "Try it free").
- **Pace**: 15-40 s total, a new moment every 1.5-3 s, speed ramps on typing/loading.
- **Sound**: music bed + whooshes on every move, soft clicks on UI taps, a hit on the logo.
- **Overlay top line** on POV versions ("POV: This took Claude 30 minutes") — the hook as a persistent caption.

## Rules for the editor
1. Show the real product only. Never invent features, numbers or UI that isn't in the recording or the notes.
2. Cut loading spinners, mouse hunting and dead time; speed up typing and scrolling (1.5-4x).
3. Zoom to where things change (the activity map tells you), never more than 2.2x, and ease in/out.
4. Callout text: ≤ 6 words, sentence case or Title Case, one idea per scene.
5. End on the product name + tagline + button.

## Preset
`style.json`: dark navy background with a blue glow (or light pastel with `look=light`), window with 28 px radius and
shadow, accent `#4F8BFF`, no colour grade on the UI, captions in a pill near the bottom only if there is a voice.
