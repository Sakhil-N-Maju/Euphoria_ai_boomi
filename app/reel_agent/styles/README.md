# Edit styles

Three styles, learned from the reference reels in `assets/style/` (contact sheets of every reference: `<style>/refs/`).
The creator picks one in the Studio; the app passes it to the planner (Claude) and to the builders.

| id | Pick it when you have | Pipeline |
|---|---|---|
| `talking_head` | a video of yourself talking to the camera | creator-reel: cuts, captions, split-screen panels, punch-ins (`creator-reel/scripts/build_plan.py`) |
| `product` | a screen recording of an app, website or digital product | `product/scripts/product_build.py`: framed window, auto-zoom on what moves, speed-ups, title callouts, outro card |
| `faceless` | only a topic or a script (optionally your voice-over or music) | creator-reel engine on a generated background: kinetic captions + motion-graphic blocks, no face |

Each folder has:
- `SKILL.md` - what the style is (studied from the references) and the rules the editor follows. Read it before editing in that style.
- `style.json` - the preset the builders read (background, colours, captions, grade, zoom, sound).
- `planner.md` - extra rules appended to the planner's system prompt for this style.
- `refs/` - one contact sheet per reference reel (24 frames each).

All three render through the same cached engine (`creator-reel/scripts/render_overlay.py` + `composite.py`), so a
correction only re-renders the part of the timeline it touches.
