# Euphoria Editor (MVP)

Transcript-driven editing for talking-head videos in Indian languages. Upload a video, and the app
transcribes it, suggests cuts (long pauses, filler words), lets you click words to cut or restore them,
previews the edit instantly in the player, then renders an MP4 with burned-in captions and evened-out audio.

## Run it

Double-click `run.bat`. It opens http://127.0.0.1:8000 in your browser.
Everything runs offline on your PC, using the Python, ffmpeg and Whisper model in `..\tools` and `..\models`.

Command line instead of the browser:

    edit.bat "C:\videos\talk.mp4" --lang ml
    edit.bat "C:\videos\talk.mp4" --plan-only           (writes talk.edit.yaml to edit by hand)
    edit.bat "C:\videos\talk.mp4" --from-plan "C:\videos\talk.edit.yaml"

## Malayalam speech-to-text model (one-time setup)

Double-click `download_models.bat` once, on a good connection. It downloads
`adalat-ai/ct2-whisper-medium-ml-rmft` (Whisper medium fine-tuned for Malayalam, Apache-2.0) into `..\models`.
After that, Malayalam videos use it automatically (picked, or detected with "Detect automatically").
Until it is downloaded, the app falls back to Whisper "small" and says so on the review page.

To pick the best option for your clips, compare them on one test video:

    compare_stt.bat "C:\videos\clip.mp4" --lang ml

It runs Whisper small, the Malayalam model, and OpenAI whisper-1 (if a key is in `.env`), prints speed and
timestamp checks, and writes `clip.stt_compare.txt` with each transcript so you can count mistakes.
To use OpenAI for transcription instead, set `whisper: engine: openai` in `config.yaml`.
On a GPU machine set `device: cuda` and `compute_type: float16`.

## AI edits: retakes and chat (needs an API key)

Copy `.env.example` to `.env` and put your key in it: `LLM_API_KEY=...`. Any OpenAI-compatible API works;
set `llm: model:` in `config.yaml` (or `LLM_MODEL` / `LLM_BASE_URL` in `.env`) for other models or providers.

- **Retakes:** right after transcribing, the AI finds sentences you started, fumbled and said again, and cuts
  the earlier takes (shown in yellow). The "Find retakes" button runs it again.
- **Chat edits:** type what you want: "make a 30-second reel of the best part", "remove the part about pricing",
  "keep the pauses longer", in Malayalam, Hindi or English. If you ask for a length, it checks the result and
  adjusts once if it missed.
- **Undo** reverts any change, AI or manual.
- **Guardrails:** the AI only answers with word IDs. Every ID is checked against the transcript; invalid edits
  are dropped, a single retake can't remove more than 80 words, retakes together can't remove more than half the
  video, and nothing can cut every word. Captions always come from the transcript, never from the AI.

Command line: `edit.bat "C:\videos\talk.mp4" --lang ml --retakes`

## How it works

| Step | File | What it does |
|---|---|---|
| Transcribe | `editor/transcribe.py` | faster-whisper with word timestamps and voice-activity detection; per-language models; optional OpenAI whisper-1 |
| Plan | `editor/plan.py` | turns removed words and long pauses into cuts; saved as `edit.yaml` ("video as code") |
| AI edits | `editor/aiedit.py`, `editor/llm.py` | retake detection and chat edits; the AI returns word IDs, which are validated before use |
| Captions | `editor/captions.py` | groups kept words into short lines on the edited timeline, writes `.ass` subtitles |
| Render | `editor/render.py` | one ffmpeg pass: trim + join with click-free fades, captions, loudness normalisation, H.264 |
| Jobs | `editor/jobs.py` | one folder per video in `data/jobs/`, processed one at a time in the background |
| Web | `editor/server.py`, `web/index.html` | FastAPI backend and the review page |

Defaults (pause length, filler words, caption font and size, encode quality) are in `config.yaml`.

## Finishing: style, b-roll and sound (all optional)

Four editing skills are built in as panels under the transcript. Everything is off by default, so a plain
edit renders exactly as before. Every choice is saved in `edit.yaml` under `style` and `broll` (video as code),
can be undone, and can be changed by typing in the chat: "make the captions pop on keywords", "bigger",
"make the whoosh shorter and deeper", "duck the music another 6dB".

- **Draft (fast)** renders at 540p with a fast preset so you can check the edit; **Render final** renders at
  the video's own resolution and frame rate. Both are kept.
- **Style (HyperFrames):** animated title card for the first 2 seconds; word-synced captions (spoken word
  highlighted); keyword pops (scale to ~118% with a 150 ms ease-out, tinted in the accent colour); a zoom
  transition at each topic change (never between every sentence); optional punch-in zoom on jump cuts.
  **Auto-style** picks the title, keywords and topic changes with the AI, or by simple rules without a key.
  In the transcript, Shift-click a word to make it a keyword and Alt-click a word to start a new topic.
- **Look (Editorial Film Edit):** bright, soft black-and-white with a gentle highlight bloom and fine moving
  grain, on the b-roll only (the presenter's face stays clean) or on the whole video. Titles and captions are
  never graded.
- **B-roll (B-Roll Prompter, needs an API key):** "Plan b-roll" reads the current cut and marks about one
  moment every two sentences. Each prompt follows Subject + Action + Setting + Camera + Style, shares one style
  phrase, and ends with "No background music, natural diegetic sound only." Generate each clip in OpenArt (or
  any video model) at 5 s with the same model for all, upload it, and the app trims it to its slot (2-4 s,
  skipping the first frames), covers the speaker full screen or with a sliding split screen, keeps the voice
  running, and keeps the clip's own sound at -20 dB. "Download prompts" saves a notes file with every prompt.
- **Sound (Sound Design):** whoosh, pop, tick and hit are synthesised in `editor/sfx.py` with numpy, no sample
  packs, and placed from the sound map: whoosh on transitions (peaking on the cut), pop when the title lands,
  a soft tick on keyword pops only, a soft whoosh when b-roll comes in, a hit on b-roll marked as an impact.
  Upload a music bed (for example Lyria 3 in OpenArt: instrumental, loopable, ~95 BPM); it is levelled, looped,
  and ducked to -18 dB under speech and -10 dB in gaps, with a fade at the end.

| Step | File | What it does |
|---|---|---|
| Style | `editor/style.py` | style keys, validation, keyword/topic picks (rules or AI) |
| Timeline | `editor/timeline.py` | edited-time words, transition points, b-roll slots, sound map |
| B-roll | `editor/broll.py` | AI b-roll map, prompt formula, notes file |
| Sound | `editor/sfx.py` | effect synthesis, music ducking, the music + effects bed |

Defaults are in the `style` and `broll` sections of `config.yaml`.
Command line: `edit.bat "C:\videos\talk.mp4" --autostyle --draft`

## Reels, colour, montage and growth tools

- **Reel format (Reel Editor):** Style panel → Format → "Reel 9:16". Landscape or square video is cropped to
  1080×1920 around the face (a slider sets where the face is), captions move above Instagram's caption area and
  away from the like/comment buttons, and the voice gets a rumble cut, gentle compression and -14 LUFS.
  "Reel pacing" tightens pauses to about 0.2 s. A **call to action** types a comment keyword into a comment box in
  the last 3 seconds, with key-tap sounds.
- **Colour grade:** "Cinematic" (warm skin, cooler shadows, gentle contrast, vignette) works on any footage.
  **Look 01 teal-orange** (by @shakirc.ai) applies the bundled LUT exactly as the skill does; it is only for
  Sony S-Log3 / S-Gamut3.Cine footage, and the page warns when a video doesn't look like flat log footage.
  The LUT can be exported for other apps from the Style panel. The `.cube` files live in `luts/` and are kept out
  of git: they are someone else's work, so don't publish them in the repo.
- **Montage tab (Beat-Sync Cinematic Edit, style by @shakirc.ai):** add clips and one song. The app finds the
  tempo, bars and drop (numpy, no extra installs), skips a slow intro, cuts on the bars, puts the clip with the
  most motion on the drop with a zoom-through, uses eased slow-motion ramps with frame blending, smooth
  transitions only (dissolve, focus blur), no repeated clips, effects only at key transitions with the music dipped
  4.5 dB, and masters to about -8 LUFS. Every render is kept (`montage_vN.mp4`, `edit_vN.json`) with a 4 fps
  contact sheet. Not included: cut-out ride-ins, the wheel portal, the B&W band and the strip transition (they
  need a cut-out model).
- **Grow tab (Growth Starter + Viral Script, needs an API key):**
  - *Starter kit:* answer 7 questions (plus your current profile, what you found searching your topic, and up to 4
    screenshots). You get `starter-kit.md`: topic scored for audience size (TAM), study list, 3 formats to copy,
    bio A/B, name field, picture brief, highlights, 2-day warm-up, week-1 plan, practice plan.
  - *Script:* upload a screen recording of a reel that's working (it's transcribed here) or paste its words.
    You get a beat map of why it works, your script (Time | On screen | VO) in your language, 3 trial hooks, a
    caption, a DM line and what to check before recording. Your voice is saved as `style.md` and reused.
  - The app never logs into, scrapes or acts on Instagram: you do the searching, it does the writing. It never
    invents numbers; estimates are marked "est.".
- **Coach this take** (Edit view): 3 notes on energy, pace and the first 3 seconds of the uploaded take, from
  its transcript and timing.

| Step | File | What it does |
|---|---|---|
| Montage | `editor/montage.py` | song beat grid, clip motion, timeline plan, render |
| Grow | `editor/grow.py` | starter kit, scripts, style.md, take notes |

## Skills tab and marketplace skills

The **Skills** tab lists every skill as a card for the selected video: switches turn it on or off, "Run" starts
it, "Open" jumps to its panel. Skills added from the video-editing marketplace
(claudemarketplaces.com/skills/category/video-editing), built into the app rather than called as plugins:

| Skill | In the app |
|---|---|
| subtitle-correction (sugarforever) | **Fix captions**: the AI fixes misheard names, numbers and English words; timings stay. Changed words get a dotted blue underline; "Restore original words" undoes it |
| subtitle-generation (eachlabs) | **Caption language**: English, Hindi, Malayalam and more, or both lines at once; translations are cached per video |
| subtitle-packager (postplusai) | Publish panel: **SRT, VTT, styled ASS** of the edited video |
| graphic-overlays (heygen-com/hyperframes) | **Lower-third** name and role card that slides in for 4 s |
| video-edit (heygen-com), ffmpeg toolkit | **Speed** of the finished video (voice keeps its pitch) and **exports**: WhatsApp size, 1:1, 16:9 and 9:16 with blurred fill, MP3, thumbnail with text |
| byted-las-video-edit (bytedance) | **Find shorts**: 2-3 self-contained highlight clips, each added as a new video in the list |
| caption-writer + content-repurposer (blacktwist) | **Post kit**: Instagram caption, hashtags, YouTube titles and description with chapters at real times, thumbnail text, LinkedIn post |

From page 2 of the marketplace (and video-understand from page 1):

| Skill | In the app |
|---|---|
| broll-match-engine (postplusai) | **Your own b-roll**: upload phone clips to the B-roll panel; the AI describes a frame of each (or uses the file name) and places the best one on each planned moment |
| social-carousel (open-design) | **Make carousel**: 5-7 slide images, 1080x1350, of the video's key points over a blurred frame |
| video-understand (heygen-com), ffmpeg-analyse-video (fabriqaai) | **Review render**: frames of the latest render go to an AI vision model, which lists problems with times (needs a model that reads images) |
| vhs (dot-skills) | **VHS tape** look: soft blur, colour fringing, moving noise, scanlines |
| audio-editing (clawfu-skills) | **Clean voice**: hum/rumble cut, hiss reduction, de-essing, a little presence, gentle compression |

Not added: dubbing, voice cloning, text-to-speech and lip-sync (they need paid cloud services), Lottie and
podcast generators (outside talking-head editing).

| Step | File | What it does |
|---|---|---|
| Marketplace skills | `editor/extras.py` | caption fixes, translation, subtitle files, post kit, shorts, exports |
| Marketplace page 2 | `editor/extras2.py` | b-roll library + matching, carousel, render review |

## Tests

    ..\tools\python\python.exe -m unittest discover tests

## Known limits

- Split screens reframe the presenter to the centre half (landscape) or the upper half (portrait). If the face
  sits off-centre, use full-screen b-roll for that moment.
- Keyword picks by rules work best in English; with an API key the AI picks them in any language.
- Whisper "small" is fast on a CPU but weak on Malayalam and other Indian languages, and on mixed
  English/Malayalam speech. The Malayalam model is better but still makes mistakes: its published word error
  rate is about 40%, and as a "medium" model it is several times slower than "small" on a CPU.
- The Malayalam model's page doesn't say how good its word timestamps are. Check cut points on a test clip.
- Whisper often leaves "um/uh" out of the transcript. Those are still removed when they leave a long
  enough gap, but short ones can slip through.

## Claude reel studio (website upload → Claude edits the reel)

Open http://127.0.0.1:8000/site → Studio. The first time, the **Set up this PC** panel installs Claude Code, signs you
in to your Claude Pro/Max account and installs the render tools, one button each (no terminal).

Every video uses the **creator-reel** skill (`reel_agent/creator-reel/SKILL.md`, token-lean):
1. Capture, no AI: normalise, Whisper word timings, background, fonts.
2. Plan, one Claude call: `claude -p` with no tools, the short rules in `prompts/plan_rules.md` and the schema in
   `prompts/plan_schema.json`. Claude reads only the transcript and returns a small JSON plan with word indexes:
   cuts, caption fixes, accent words, hook, text behind the head, graphics picked from the block catalog, CTA.
3. Build + render, no AI: `build_plan.py` makes cuts, captions, layouts, zooms, grade, SFX and the graphics
   (`templates/lean_overlay.html`), and the reel-editor engine renders `out/reel.mp4`. Retry reuses the saved plan,
   so it costs no new tokens.
The page shows how many tokens Claude used for each reel.

This uses the signed-in Claude account of whoever runs the app, so it is for the team's own use. A public
product needs Anthropic API keys (see Claude Code legal and compliance docs).

Credits: structure from the product-launch-video (HyperFrames) skill; render engine, overlay template and examples
from the reel-editor Claude skill; colour look ideas from the Look 01 skill by @shakirc.ai. Fonts from Fontsource
(OFL); person cut-out model u2net_human_seg (rembg releases). `reel_agent/euphoria-reel/` is the older, token-heavy
version and is no longer used.
